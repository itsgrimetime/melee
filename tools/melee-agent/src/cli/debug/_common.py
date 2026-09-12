"""Cross-cutting helpers shared by debug CLI command-group modules.

Carved out of cli/debug/__init__.py. These are the SHARED, NON-monkeypatched
helper/class/constant definitions used by sibling debug command-group modules.

Dependency floor: imports only stdlib + typer + ``.._common`` (CLI-wide
console/roots) + ``src.mwcc_debug``. This module NEVER imports the
``src.cli.debug`` package (the __init__) at load time -- that would be a cycle
(__init__ imports this module). The helpers here that reference a symbol which
lives elsewhere in the package (a helper that stayed in __init__.py, e.g. a
monkeypatched one, or a helper that lives in a sibling group module and is
re-exported into the package namespace) reach it via a call-time (deferred)
``from src.cli.debug import ...`` inside the function body, so the name resolves
against the fully-loaded package at call time and any
``monkeypatch.setattr(debug_cli, ...)`` still takes effect.
"""
from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    NoReturn,
    Optional,
)

import typer

if TYPE_CHECKING:  # annotation-only; the runtime objects live in the package
    from src.cli.debug import (  # noqa: F401
        _FrameFunctionNames,
        _RemotePcdumpResult,
        _SelectOrderCommandSourceRestore,
    )

from .._common import DEFAULT_MELEE_ROOT, console
from ...mwcc_debug import parse_pcdump
from ...mwcc_debug import cache as pcdump_cache
from ...mwcc_debug.source_patch import (
    extract_function,
    find_function as find_source_function,
    find_function_definitions,
)


__all__ = [
    "_MalformedSourceCandidate",
    "_SourceRestoreBytesError",
    "_abort_frame_function_not_in_dump",
    "_abort_function_not_in_dump",
    "_attach_frame_function_aliases",
    "_auto_pcdump_cache_metadata",
    "_coalesce_find_function_body_span",
    "_coalesce_force_phys_objective_fields",
    "_coalesce_generated_local_from_variant",
    "_coalesce_line_no",
    "_coalesce_parse_force_phys_map",
    "_coalesce_search_probe_root",
    "_coalesce_simple_identifier",
    "_compact_source_hunk_for_function",
    "_copy_propagation_repair_summary",
    "_copy_propagation_repair_text",
    "_copy_survived_continuation_handoff",
    "_copy_survived_repair_summary",
    "_copy_survived_variant_hit",
    "_effective_reg_class",
    "_emit_function_not_in_dump",
    "_format_select_order_residual",
    "_format_source_diff",
    "_frame_report_aliases",
    "_frame_source_context",
    "_frame_source_suggestions_from_report",
    "_full_unit_source_for_probe",
    "_generate_anti_coalesce_split_probes",
    "_generate_copy_survived_pointer_reset_probes",
    "_load_trace_copy_repair_target",
    "_looks_like_melee_root",
    "_make_real_score_status",
    "_name_magic_header_candidate_text",
    "_name_magic_header_for_source",
    "_parse_force_coalesce_pair_specs",
    "_parse_force_no_cse_node",
    "_parse_lifetime_layout_candidate",
    "_parse_probe_provenance",
    "_parse_select_order_guard_repair_seed",
    "_parse_virtual_order_csv",
    "_parse_virtual_pair_csv",
    "_path_inside_repo",
    "_pcdump_has_symbolic_stack_homes",
    "_pressure_signature_from_pcdump_or_exit",
    "_prevalidate_lifetime_layout_source_candidate",
    "_print_frame_suggestions",
    "_rank_select_order_candidates_real_first",
    "_read_expression_source",
    "_read_frame_reservation_expected_asm",
    "_register_class_from_pair_csv",
    "_remote_retained_source_terminal_blocker",
    "_resolve_existing_cli_file",
    "_resolve_frame_function_names",
    "_restore_source_snapshot",
    "_retain_coalesce_search_pcdump",
    "_retain_coalesce_search_source",
    "_same_filesystem_path",
    "_score_source_target_details",
    "_select_order_close_source_restore",
    "_select_order_complement_target_summary",
    "_select_order_default_complement_targets",
    "_select_order_force_phys_hit_registers",
    "_select_order_guard_repair_entry_protected_complement",
    "_select_order_guard_repair_seed_variants",
    "_select_order_guard_repair_variant_sort_key",
    "_select_order_json_safe",
    "_select_order_protected_register_preservation",
    "_select_order_residual_variant_labels_from_buckets",
    "_select_order_safe_label",
    "_select_order_source_attributed_fallback_lead_count",
    "_select_order_source_fingerprints",
    "_select_order_tag_targeted_interference_probe",
    "_select_order_variant_target_score",
    "_select_order_window_order_probe_reserve",
    "_solve_source_attribution_dict",
    "_source_path_for_function",
    "_source_restore_byte_guards",
    "_suggest_similar_functions",
    "_timeout_before_deadline",
    "_timeout_message",
    "_trace_copy_json_summary",
    "_validate_force_schedule",
]


def _looks_like_melee_root(path: Path) -> bool:
    return (path / "configure.py").is_file() and (path / "src" / "melee").is_dir()


def _format_source_diff(
    before: str,
    after: str,
    *,
    fromfile: str = "before",
    tofile: str = "after",
    context: int = 3,
) -> str:
    """Return a focused unified diff for source-preview commands."""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            n=context,
        )
    )


def _resolve_existing_cli_file(
    path: Path,
    *,
    melee_root: Path = DEFAULT_MELEE_ROOT,
    label: str = "file",
) -> Path:
    """Resolve a CLI path from cwd first, then from the repo root."""
    expanded = path.expanduser()
    if expanded.is_absolute():
        resolved = expanded.resolve()
        if resolved.is_file():
            return resolved
        raise typer.BadParameter(f"{label} not found: {resolved}")

    candidates = [
        (Path.cwd() / expanded).resolve(),
        (melee_root / expanded).resolve(),
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate
    raise typer.BadParameter(f"{label} not found: {candidates[0]}")


def _remote_retained_source_terminal_blocker(
    remote_result: _RemotePcdumpResult,
) -> str:
    from src.cli.debug import _RemotePcdumpResult, _remote_retained_source_dependency_context_evidence
    if remote_result.staged_source is None:
        return "remote-pcdump-failed"
    stderr_text = remote_result.stderr or ""
    lowered = stderr_text.lower()
    if "stdin source staging timed out" in lowered:
        return "remote-retained-source-stdin-transport-timeout"
    if "scp source staging timed out" in lowered:
        return "remote-retained-source-file-transport-timeout"
    if remote_result.staging_ack_confirmed is not True and (
        remote_result.returncode == 124
        or ("timed out after" in lowered and "running ssh" in lowered)
    ):
        if remote_result.staging_transport == "scp":
            return "remote-retained-source-file-transport-timeout"
        return "remote-retained-source-stdin-transport-timeout"
    if remote_result.returncode == 124:
        return "remote-retained-source-compile-timeout"
    if remote_result.staging_ack_confirmed is not True:
        if remote_result.staging_transport == "scp":
            return "remote-retained-source-file-staging-failed"
        return "remote-retained-source-staging-failed"
    if _remote_retained_source_dependency_context_evidence(stderr_text):
        return "remote-retained-source-dependency-context-mismatch"
    return "remote-retained-source-compile-failed"


def _validate_force_schedule(raw: str, *, option: str = "--force-schedule") -> str:
    if any(c in raw for c in '"\'; \t\r\n&|<^'):
        raise typer.BadParameter(
            f"{option} must not contain quotes, semicolons, whitespace, "
            "or shell metacharacters other than '>'"
        )
    return raw


def _parse_force_no_cse_node(raw: str, *, option: str) -> int:
    token = raw
    if token.startswith("iro:"):
        token = token[4:]
    if not token or token[0] in "+-":
        raise typer.BadParameter(
            f"{option} entry {raw!r} is invalid. Expected a non-negative "
            "IRO node number, optionally prefixed with 'iro:'"
        )
    try:
        value = int(token, 0)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{option} entry {raw!r} is invalid. Expected a decimal or 0x "
            "hex IRO node number"
        ) from exc
    if value < 0:
        raise typer.BadParameter(f"{option} entry {raw!r} must be non-negative")
    return value


def _read_frame_reservation_expected_asm(
    function: str,
    *,
    expected_asm: Optional[Path],
    no_expected: bool,
    melee_root: Path,
) -> str | None:
    from src.cli.debug import _tmp_asm_path_for_function
    if no_expected:
        return None
    if expected_asm is not None:
        if not expected_asm.exists():
            typer.echo(f"expected asm not found: {expected_asm}", err=True)
            raise typer.Exit(2)
        return expected_asm.read_text()

    asm_path = _tmp_asm_path_for_function(function)
    extract_cmd = [
        "melee-agent",
        "extract",
        "get",
        function,
        "--full",
        "--output",
        str(asm_path),
    ]
    proc = subprocess.run(
        extract_cmd,
        cwd=melee_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        typer.echo(proc.stderr or proc.stdout, err=True)
        raise typer.Exit(proc.returncode or 1)
    return asm_path.read_text()


def _frame_source_context(
    function_names: Iterable[str],
    *,
    melee_root: Path,
    source_file: Optional[Path] = None,
) -> dict[str, Any]:
    from src.cli.debug import _find_unit_for_function
    names = tuple(dict.fromkeys(str(name) for name in function_names if name))
    if not names:
        return {}
    source_path: Path | None = None
    if source_file is not None:
        source_path = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
    else:
        for name in names:
            unit = _find_unit_for_function(name, melee_root)
            if unit is None:
                continue
            candidate = melee_root / "src" / f"{unit}.c"
            if candidate.exists():
                source_path = candidate
                break
    if source_path is None:
        return {}
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    try:
        source_label = str(source_path.relative_to(melee_root))
    except ValueError:
        source_label = str(source_path)
    return {
        "source_text": source_text,
        "source_path": source_label,
        "source_function_names": names,
    }


def _pcdump_has_symbolic_stack_homes(pcdump_text: str) -> bool:
    return bool(re.search(
        r"(?<![@\w])(?:@[A-Za-z0-9_]\w*|[A-Za-z_]\w*)"
        r"(?:[+-](?:0x[0-9A-Fa-f]+|\d+))?\s*\(\s*r1\s*\)",
        pcdump_text,
    ))


def _frame_source_suggestions_from_report(
    report: dict,
    *,
    unit: str | None = None,
) -> list[dict]:
    from src.cli.debug import _format_stack_range
    function = report.get("function") or "<function>"
    src_rel = f"src/{unit}.c" if unit else "<source.c>"
    frame_target = f"{function}.frame-target.json"
    checkdiff_target = f"{function}.checkdiff.json"
    suggestions: list[dict] = []

    current_low = report.get("current_low_frame_expansion")
    if isinstance(current_low, dict):
        range_text = _format_stack_range(current_low)
        commands = [
            (
                f"python tools/checkdiff.py {function} --format json "
                f"--no-build > {checkdiff_target}"
            ),
            (
                f"melee-agent debug target derive -f {function} "
                f"--frame-from-checkdiff {checkdiff_target} --format json "
                f"> {frame_target}"
            ),
            (
                f"melee-agent debug target score-source {src_rel} "
                f"-f {function} --target {frame_target}"
            ),
            (
                f"melee-agent debug dump local {src_rel} -f {function} "
                "--diff --force-frame-from-diff"
            ),
        ]
        suggestions.append({
            "rank": 1,
            "kind": "suppress-unused-local-home",
            "origin": current_low.get("origin"),
            "range": {
                "start": current_low.get("start"),
                "end": current_low.get("end"),
                "size": current_low.get("size"),
            },
            "description": (
                f"Current source reserves an unused low local home at "
                f"{range_text}. For gm_801A9DD0-style cases this commonly "
                "comes from a held FP constant whose mutable local form gets "
                "a DLOCAL stack home. Try source shapes that keep the held FP "
                "constant live without a named mutable local home: split the "
                "constant lifetime, use direct literal/global expression at "
                "the final FP call, or compare against a matched sibling with "
                "the same SetNear/SetFar idiom."
            ),
            "commands": commands,
            "score_target": {
                "frame_size": report.get("expected", {}).get("frame_size")
                if isinstance(report.get("expected"), dict) else None,
                "score_command": commands[1],
            },
        })
        if current_low.get("alignment_growth_bytes"):
            suggestions.append({
                "rank": 2,
                "kind": "reduce-alignment-growth",
                "origin": current_low.get("origin"),
                "description": (
                    "The unused low home also changes the next 8-byte-aligned "
                    "scratch slot. Probe source variants that move int-to-float "
                    "magic-double scratch lifetimes away from the held FP "
                    "constant, then rank them with the frame target scorer."
                ),
                "commands": [commands[1]],
            })

    extra = report.get("extra_low_frame_reservation")
    if isinstance(extra, dict):
        commands = [
            (
                f"melee-agent debug target score-source {src_rel} "
                f"-f {function} --target {frame_target}"
            ),
            (
                f"melee-agent debug mutate lifetime-layout -f {function} "
                f"--frame-reservation-bytes {extra.get('size')}"
            ),
        ]
        suggestions.append({
            "rank": len(suggestions) + 1,
            "kind": "add-low-frame-reservation",
            "origin": extra.get("origin"),
            "range": {
                "start": extra.get("start"),
                "end": extra.get("end"),
                "size": extra.get("size"),
            },
            "description": (
                "The target reserves low-frame bytes before the first current "
                "callee/local stack access. Try explicit reservation probes or "
                "source lifetime changes that introduce a natural low local."
            ),
            "commands": commands,
        })

    if not suggestions:
        suggestions.append({
            "rank": 1,
            "kind": "derive-frame-target",
            "origin": "frame-size",
            "description": (
                "No unused-home signature was detected. Derive a frame target "
                "from checkdiff's expected/reference asm and use score-source to rank "
                "source candidates by frame-size and unused-range distance."
            ),
            "commands": [
                (
                    f"python tools/checkdiff.py {function} --format json "
                    f"--no-build > {checkdiff_target}"
                ),
                (
                    f"melee-agent debug target derive -f {function} "
                    f"--frame-from-checkdiff {checkdiff_target} "
                    f"--format json > {frame_target}"
                ),
                (
                    f"melee-agent debug target score-source {src_rel} "
                    f"-f {function} --target {frame_target}"
                ),
            ],
        })
    return suggestions


def _print_frame_suggestions(report: dict, suggestions: list[dict]) -> None:
    print(report["summary"])
    print()
    print("Frame source suggestions:")
    for suggestion in suggestions:
        print(f"{suggestion['rank']}. {suggestion['kind']}")
        print(f"   {suggestion['description']}")
        commands = suggestion.get("commands") or []
        if commands:
            print("   Commands:")
            for command in commands:
                print(f"     {command}")


def _source_path_for_function(func_name: str, melee_root: Path) -> Optional[Path]:
    from src.cli.debug import _find_unit_for_function
    unit = _find_unit_for_function(func_name, melee_root)
    if unit is not None:
        path = melee_root / "src" / f"{unit}.c"
        if path.is_file():
            return path

    src_root = melee_root / "src"
    if not src_root.is_dir():
        return None

    exact_matches: list[Path] = []
    for path in sorted(src_root.rglob("*.c")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if find_source_function(text, func_name) is not None:
            exact_matches.append(path)
    if len(exact_matches) == 1:
        return exact_matches[0]

    prefix = func_name.split("_", 1)[0].lower()
    if not prefix:
        return None
    prefix_matches = [
        path for path in sorted(src_root.rglob("*.c"))
        if path.stem.lower() == prefix
    ]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return None


def _frame_report_aliases(function: str, melee_root: Path) -> tuple[str, tuple[str, ...]]:
    from src.cli.debug import _append_unique, _fn_addr_from_name, _format_fn_addr, _report_function_virtual_address
    aliases: list[str] = [function]
    report_function = function
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        return report_function, tuple(aliases)

    requested_addr = _fn_addr_from_name(function)
    try:
        report = json.loads(report_path.read_text())
    except (OSError, json.JSONDecodeError):
        return report_function, tuple(aliases)

    matched_addr: int | None = requested_addr
    matched_names: list[str] = []
    for unit in report.get("units", []):
        if not isinstance(unit, Mapping):
            continue
        for entry in unit.get("functions", []):
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            addr = _report_function_virtual_address(entry)
            if name == function or (
                requested_addr is not None and addr == requested_addr
            ):
                _append_unique(matched_names, name)
                if matched_addr is None:
                    matched_addr = addr

    if matched_names:
        report_function = matched_names[0]
        for name in matched_names:
            _append_unique(aliases, name)
    if matched_addr is not None:
        fn_alias = _format_fn_addr(matched_addr)
        _append_unique(aliases, fn_alias)

    return report_function, tuple(aliases)


def _resolve_frame_function_names(
    function: str,
    pcdump_text: str,
    melee_root: Path,
) -> _FrameFunctionNames | None:
    from src.cli.debug import _FrameFunctionNames
    report_function, aliases = _frame_report_aliases(function, melee_root)
    available = {fn.name for fn in parse_pcdump(pcdump_text)}
    for alias in aliases:
        if alias in available:
            return _FrameFunctionNames(
                requested=function,
                report_function=report_function,
                pcdump_function=alias,
                aliases=aliases,
            )
    return None


def _attach_frame_function_aliases(
    report: dict,
    names: _FrameFunctionNames,
) -> None:
    from src.cli.debug import _FrameFunctionNames
    report["function"] = names.requested
    report["function_aliases"] = {
        "requested": names.requested,
        "report_function": names.report_function,
        "pcdump_function": names.pcdump_function,
        "aliases": list(names.aliases),
    }


def _looks_like_melee_root(path: Path) -> bool:
    return (path / "src" / "melee").is_dir()


def _effective_reg_class(
    explicit: Optional[str],
    *tokens: Optional[str],
    default: Optional[str] = None,
) -> Optional[str]:
    from src.cli.debug import _reg_class_from_virtual_token
    if explicit is not None:
        valid = {"0", "1", "gpr", "int", "r", "fp", "fpr", "f", "float"}
        if explicit.strip().lower() not in valid:
            raise typer.BadParameter(
                f"invalid register class {explicit!r}; expected gpr/int/0 or fp/fpr/1"
            )
        return explicit
    for token in tokens:
        inferred = _reg_class_from_virtual_token(token)
        if inferred is not None:
            return inferred
    return default


def _parse_virtual_pair_csv(value: str) -> list[tuple[int, int]]:
    from src.cli.debug import _parse_virtual_reg_token
    pairs: list[tuple[int, int]] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        sep = next(
            (candidate for candidate in (":", "=", "/") if candidate in token),
            None,
        )
        if sep is None:
            raise typer.BadParameter(
                f"invalid pair {token!r}; expected rA:rB, rA/rB, or rA=rB"
            )
        left, right = token.split(sep, 1)
        if not left.strip() or not right.strip():
            raise typer.BadParameter(
                f"invalid pair {token!r}; expected rA:rB, rA/rB, or rA=rB"
            )
        pairs.append((
            _parse_virtual_reg_token(left.strip()),
            _parse_virtual_reg_token(right.strip()),
        ))
    return pairs


def _register_class_from_pair_csv(value: str | None) -> str | None:
    from src.cli.debug import _reg_class_from_virtual_token
    if value is None:
        return None
    classes: set[str] = set()
    for raw_pair in value.split(","):
        token = raw_pair.strip()
        if not token:
            continue
        sep = next((candidate for candidate in (":", "=", "/") if candidate in token), None)
        if sep is None:
            continue
        left, right = token.split(sep, 1)
        for reg_token in (left, right):
            inferred = _reg_class_from_virtual_token(reg_token.strip())
            if inferred is not None:
                classes.add(inferred)
    if len(classes) > 1:
        raise typer.BadParameter(
            "mixed register classes in --target; use only GPR or only FPR pairs"
        )
    return next(iter(classes), None)


def _load_trace_copy_repair_target(
    path: Path,
    *,
    function: str,
) -> dict[str, Any]:
    from src.cli.debug import _register_class_name_from_id, _trace_copy_inferred_register_class, _trace_copy_json_int, _trace_copy_json_occurrence, _trace_copy_source_operand, _trace_mapping_int, _trace_register_class_name, _pressure_class_id
    trace_path = _resolve_existing_cli_file(
        path,
        melee_root=DEFAULT_MELEE_ROOT,
        label="trace-copy JSON",
    )
    try:
        payload = json.loads(trace_path.read_text())
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid trace-copy JSON: {exc}") from exc
    if isinstance(payload, list):
        if len(payload) != 1:
            raise typer.BadParameter(
                "trace-copy JSON lists are supported only when they contain one report"
            )
        payload = payload[0]
    if not isinstance(payload, Mapping):
        raise typer.BadParameter("trace-copy JSON must be an object")
    trace_function = payload.get("function")
    if trace_function is not None and str(trace_function) != function:
        raise typer.BadParameter(
            f"trace-copy JSON is for {trace_function!r}, not {function!r}"
        )
    from_mapping = payload.get("from_mapping")
    to_mapping = payload.get("to_mapping")
    from_virtual = _trace_copy_json_int(
        payload.get("from_virtual"),
        label="from_virtual",
    )
    to_virtual = _trace_copy_json_int(
        payload.get("to_virtual"),
        label="to_virtual",
    )
    from_class_id = _trace_mapping_int(from_mapping, "class_id")
    to_class_id = _trace_mapping_int(to_mapping, "class_id")
    nested_class_ids = {
        class_id
        for class_id in (from_class_id, to_class_id)
        if class_id is not None
    }
    if len(nested_class_ids) > 1:
        raise typer.BadParameter(
            "trace-copy JSON from_mapping/to_mapping class_id values conflict"
        )
    top_level_register_class = _trace_register_class_name(
        payload.get("register_class")
    )
    top_level_class_id = (
        _pressure_class_id(top_level_register_class)
        if top_level_register_class is not None
        else None
    )
    nested_class_id = next(iter(nested_class_ids), None)
    if (
        top_level_class_id is not None
        and nested_class_id is not None
        and top_level_class_id != nested_class_id
    ):
        raise typer.BadParameter(
            "trace-copy JSON register_class conflicts with mapping class_id"
        )
    nested_register_class = _register_class_name_from_id(nested_class_id)
    inferred_register_class = _trace_copy_inferred_register_class(
        payload,
        from_mapping=from_mapping,
        to_mapping=to_mapping,
        from_virtual=from_virtual,
        to_virtual=to_virtual,
    )
    class_sources = [
        register_class
        for register_class in (
            top_level_register_class,
            nested_register_class,
            inferred_register_class,
        )
        if register_class is not None
    ]
    if len(set(class_sources)) > 1:
        if top_level_register_class is not None:
            raise typer.BadParameter(
                "trace-copy JSON register_class conflicts with occurrence "
                "operands"
            )
        if nested_register_class is not None:
            raise typer.BadParameter(
                "trace-copy JSON mapping class_id conflicts with occurrence "
                "operands"
            )
        raise typer.BadParameter(
            "trace-copy JSON occurrence operands contain conflicting "
            "register classes"
        )
    register_class = (
        top_level_register_class
        or nested_register_class
        or inferred_register_class
    )
    class_id = (
        top_level_class_id
        if top_level_class_id is not None
        else (
            nested_class_id
            if nested_class_id is not None
            else (
                _pressure_class_id(inferred_register_class)
                if inferred_register_class is not None
                else None
            )
        )
    )
    return {
        "path": str(trace_path),
        "function": function,
        "from_virtual": from_virtual,
        "to_virtual": to_virtual,
        "trace_status": payload.get("status"),
        "likely_cause": payload.get("likely_cause"),
        "transform_category": payload.get("transform_category"),
        "first_absent_pass": payload.get("first_absent_pass"),
        "first_copy": _trace_copy_json_occurrence(payload.get("first_copy")),
        "last_copy": _trace_copy_json_occurrence(payload.get("last_copy")),
        "register_class": register_class,
        "class_id": class_id,
        "from_assigned_reg": _trace_mapping_int(from_mapping, "assigned_reg"),
        "to_assigned_reg": _trace_mapping_int(to_mapping, "assigned_reg"),
        "from_ig_idx": _trace_mapping_int(from_mapping, "ig_idx"),
        "to_ig_idx": _trace_mapping_int(to_mapping, "ig_idx"),
        "from_operand": _trace_copy_source_operand(
            from_mapping,
            virtual=from_virtual,
            register_class=register_class,
        ),
        "to_operand": _trace_copy_source_operand(
            to_mapping,
            virtual=to_virtual,
            register_class=register_class,
        ),
    }


def _trace_copy_json_summary(trace_target: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": trace_target.get("path"),
        "function": trace_target.get("function"),
        "from_virtual": trace_target.get("from_virtual"),
        "to_virtual": trace_target.get("to_virtual"),
        "status": trace_target.get("trace_status"),
        "likely_cause": trace_target.get("likely_cause"),
        "transform_category": trace_target.get("transform_category"),
        "first_absent_pass": trace_target.get("first_absent_pass"),
        "first_copy": trace_target.get("first_copy"),
        "last_copy": trace_target.get("last_copy"),
        "register_class": trace_target.get("register_class"),
        "class_id": trace_target.get("class_id"),
        "from_assigned_reg": trace_target.get("from_assigned_reg"),
        "to_assigned_reg": trace_target.get("to_assigned_reg"),
        "from_ig_idx": trace_target.get("from_ig_idx"),
        "to_ig_idx": trace_target.get("to_ig_idx"),
        "source_operands": {
            "from": trace_target.get("from_operand"),
            "to": trace_target.get("to_operand"),
        },
    }


def _copy_survived_variant_hit(variant: Mapping[str, Any]) -> bool:
    if variant.get("status") != "ok":
        return False
    objective = variant.get("objective")
    if not isinstance(objective, Mapping):
        return False
    if objective.get("force_phys_satisfied") is True:
        return True
    return bool(
        objective.get("target_coalesced")
        or objective.get("interference_removed")
        or objective.get("live_overlap_removed")
        or objective.get("target_spill_removed")
    )


def _coalesce_parse_force_phys_map(raw: str | None) -> dict[int, int]:
    if raw is None:
        return {}
    force_phys: dict[int, int] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split(":")]
        if len(parts) == 3:
            _class_part, ig_part, phys_part = parts
        elif len(parts) == 2:
            ig_part, phys_part = parts
        else:
            continue
        phys_part = re.sub(r"^[rRfF]", "", phys_part)
        try:
            force_phys[int(ig_part)] = int(phys_part)
        except ValueError:
            continue
    return force_phys


def _coalesce_simple_identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if re.match(r"^[A-Za-z_][A-Za-z_0-9]*$", value):
        return value
    return None


def _coalesce_generated_local_from_variant(
    variant: Mapping[str, Any],
) -> str | None:
    generated_local = _coalesce_simple_identifier(variant.get("generated_local"))
    if generated_local is not None:
        return generated_local
    provenance = variant.get("provenance")
    if (
        isinstance(provenance, Mapping)
        and provenance.get("kind") == "pointer-walk-loop"
        and provenance.get("variant") in {"induction", "end-pointer"}
    ):
        return "ll_probe_iter_0"
    source_retained = variant.get("source_retained")
    if not isinstance(source_retained, str):
        return None
    try:
        source_text = Path(source_retained).read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    match = re.search(r"\bll_probe_iter_\d+\b", source_text)
    return match.group(0) if match is not None else None


def _copy_survived_continuation_handoff(
    *,
    function: str,
    unit: str | None,
    trace_target: Mapping[str, Any],
    variant: Mapping[str, Any],
    transform_force_phys: str | None,
    melee_root: Path,
) -> dict[str, Any] | None:
    from src.cli.debug import _coalesce_cli_path_arg, _coalesce_generated_local_source_attribution, _coalesce_generated_local_source_cli_payload, _coalesce_primary_force_target
    source_retained = variant.get("source_retained")
    if not isinstance(source_retained, str) or not source_retained.endswith(".c"):
        return None
    pcdump_path = variant.get("pcdump_path")
    provenance = (
        dict(variant["provenance"])
        if isinstance(variant.get("provenance"), Mapping)
        else None
    )
    generated_local = _coalesce_generated_local_from_variant(variant)
    source_arg = _coalesce_cli_path_arg(source_retained, melee_root)
    source_arg_q = shlex.quote(source_arg)
    function_q = shlex.quote(function)
    unit_arg = f"src/{unit}.c" if unit is not None else None
    target_spec_placeholder = shlex.quote("<target-spec.json>")
    score_command = (
        f"melee-agent debug target score-source {source_arg_q} "
        f"-f {function_q} --target {target_spec_placeholder}"
    )
    if unit_arg is not None:
        score_command += f" --cflags-from {shlex.quote(unit_arg)}"
    score_command += " --json --checkdiff-guard --retain-pcdump"

    routes: list[dict[str, Any]] = [{
        "rank": 1,
        "kind": "score-retained-source",
        "command": score_command,
        "requires_target_spec": True,
    }]

    force_phys = _coalesce_parse_force_phys_map(transform_force_phys)
    target_ig, desired_phys, current_phys = _coalesce_primary_force_target(
        trace_target,
        force_phys,
    )
    reg_prefix = "f" if trace_target.get("register_class") == "fpr" else "r"
    generated_local_source = _coalesce_generated_local_source_attribution(
        source_retained,
        function,
        generated_local,
    )

    def append_node_route(kind: str, var_name: str) -> None:
        rank = len(routes) + 1
        command = [
            "melee-agent",
            "debug",
            "solve",
            "node-set-split",
            "-f",
            function,
            "--class",
            str(trace_target.get("register_class") or "gpr"),
            "--source-file",
            source_arg,
            "--ig",
            str(target_ig) if target_ig is not None else "<ig>",
        ]
        if current_phys is not None:
            command.extend(["--current-reg", f"{reg_prefix}{current_phys}"])
        if desired_phys is not None:
            command.extend(["--target-reg", f"{reg_prefix}{desired_phys}"])
        else:
            command.extend(["--target-reg", "<target-reg>"])
        command.extend(["--var", var_name, "--json"])
        if transform_force_phys:
            command.extend(["--force-phys", transform_force_phys])
        generated_source_payload = None
        if kind == "node-set-split-generated-local":
            generated_source_payload = _coalesce_generated_local_source_cli_payload(
                generated_local_source,
            )
            if generated_source_payload is not None:
                command.extend([
                    "--generated-local-source-json",
                    json.dumps(
                        generated_source_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ])
        route: dict[str, Any] = {
            "rank": rank,
            "kind": kind,
            "var": var_name,
            "command": shlex.join(command),
        }
        if generated_source_payload is not None:
            route["generated_local_source"] = generated_source_payload
        if target_ig is not None:
            route["target_ig"] = target_ig
        if current_phys is not None:
            route["current_reg"] = f"{reg_prefix}{current_phys}"
        if desired_phys is not None:
            route["target_reg"] = f"{reg_prefix}{desired_phys}"
        else:
            route["requires_force_phys"] = True
        if transform_force_phys:
            route["force_phys"] = transform_force_phys
        routes.append(route)

    seen_vars: set[str] = set()
    if generated_local is not None:
        append_node_route("node-set-split-generated-local", generated_local)
        seen_vars.add(generated_local)
    if provenance is not None:
        base = _coalesce_simple_identifier(provenance.get("base"))
        if base is not None and base not in seen_vars:
            append_node_route("node-set-split-pointer-base", base)
            seen_vars.add(base)
        counter = _coalesce_simple_identifier(
            provenance.get("counter") or provenance.get("index_expr")
        )
        if counter is not None and counter not in seen_vars:
            append_node_route("node-set-split-loop-counter", counter)
            seen_vars.add(counter)

    handoff: dict[str, Any] = {
        "kind": "copy-survived-generated-local-continuation",
        "status": "route-available",
        "source_retained": source_retained,
        "operator": variant.get("operator"),
        "generated_local": generated_local,
        "generated_local_source": generated_local_source,
        "source_attribution": provenance,
        "force_phys": transform_force_phys,
        "routes": routes,
    }
    if isinstance(pcdump_path, str):
        handoff["pcdump_path"] = pcdump_path
        routes[0]["pcdump_path"] = pcdump_path
    return handoff


def _copy_survived_repair_summary(
    trace_target: dict[str, Any],
    ranked_variants: list[dict],
    *,
    function: str | None = None,
    unit: str | None = None,
    transform_force_phys: str | None = None,
    melee_root: Path = DEFAULT_MELEE_ROOT,
) -> dict[str, Any]:
    from src.cli.debug import _copy_repair_candidate_summary, _retained_c_source_variant_hit
    summary = {
        "status": "not-run",
        "trace_status": trace_target.get("trace_status"),
        "likely_cause": trace_target.get("likely_cause"),
        "transform_category": trace_target.get("transform_category"),
        "register_class": trace_target.get("register_class"),
        "class_id": trace_target.get("class_id"),
        "from_virtual": trace_target.get("from_virtual"),
        "to_virtual": trace_target.get("to_virtual"),
        "from_assigned_reg": trace_target.get("from_assigned_reg"),
        "to_assigned_reg": trace_target.get("to_assigned_reg"),
        "from_ig_idx": trace_target.get("from_ig_idx"),
        "to_ig_idx": trace_target.get("to_ig_idx"),
        "scored_count": sum(
            1 for variant in ranked_variants if variant.get("status") == "ok"
        ),
        "failed_count": sum(
            1 for variant in ranked_variants if variant.get("status") != "ok"
        ),
    }
    for variant in ranked_variants:
        if _retained_c_source_variant_hit(variant):
            summarized_variant = variant
            if function is not None and "continuation" not in summarized_variant:
                continuation = _copy_survived_continuation_handoff(
                    function=function,
                    unit=unit,
                    trace_target=trace_target,
                    variant=summarized_variant,
                    transform_force_phys=transform_force_phys,
                    melee_root=melee_root,
                )
                if continuation is not None:
                    summarized_variant = dict(summarized_variant)
                    summarized_variant["continuation"] = continuation
            summary["status"] = "source-actionable"
            summary["best_variant"] = _copy_repair_candidate_summary(
                summarized_variant
            )
            return summary
    if ranked_variants:
        summary["status"] = "terminal-blocker"
        pointer_reset_variants = [
            variant for variant in ranked_variants
            if variant.get("operator") == "copy-survived-pointer-reset"
        ]
        if pointer_reset_variants:
            summary["pointer_reset_probe_count"] = len(pointer_reset_variants)
            summary["pointer_reset_failed_count"] = sum(
                1 for variant in pointer_reset_variants
                if variant.get("status") != "ok"
            )
            reset_sources = []
            for variant in pointer_reset_variants:
                provenance = variant.get("provenance")
                if not isinstance(provenance, Mapping):
                    continue
                from_local = provenance.get("from_local")
                to_local = provenance.get("to_local")
                if from_local and to_local:
                    reset_sources.append(f"{from_local}->{to_local}")
            unique_sources = sorted(set(reset_sources))
            force_progress = [
                str(variant.get("objective", {}).get("force_phys_progress_kind"))
                for variant in pointer_reset_variants
                if isinstance(variant.get("objective"), Mapping)
                and variant.get("objective", {}).get("force_phys_progress_kind")
            ]
            force_note = (
                ""
                if not force_progress
                else f"; force-phys progress: {', '.join(sorted(set(force_progress)))}"
            )
            summary["terminal_blocker"] = (
                "copy-survived pointer-reset repair exhausted scored "
                "source-visible reset probes"
                + (f" ({', '.join(unique_sources)})" if unique_sources else "")
                + " without coalescing the target pair, satisfying exact "
                "force-phys targets, or removing target interference, live "
                "overlap, or target spill pressure"
                + force_note
            )
        else:
            summary["terminal_blocker"] = (
                "copy-survived repair exhausted scored retained .c source "
                "candidates without "
                "coalescing the target pair or removing target interference, "
                "live overlap, or target spill pressure"
            )
    return summary


def _copy_propagation_repair_summary(
    trace_target: dict[str, Any],
    ranked_variants: list[dict],
) -> dict[str, Any]:
    from src.cli.debug import _copy_propagation_ranked_source_repairs, _copy_propagation_repair_applies, _copy_propagation_retained_source_shape_candidates, _copy_propagation_source_shape_terminal_summary, _copy_propagation_terminal_blocker, _copy_propagation_unmapped_operands, _copy_repair_candidate_summary, _retained_c_source_variant_hit, _trace_copy_pair_token
    from_operand = trace_target.get("from_operand")
    to_operand = trace_target.get("to_operand")
    if not isinstance(from_operand, Mapping):
        from_operand = {}
    if not isinstance(to_operand, Mapping):
        to_operand = {}
    summary = {
        "status": "not-applicable",
        "first_absent_pass": trace_target.get("first_absent_pass"),
        "first_copy": trace_target.get("first_copy"),
        "last_copy": trace_target.get("last_copy"),
        "register_class": trace_target.get("register_class"),
        "class_id": trace_target.get("class_id"),
        "target_pair": _trace_copy_pair_token(trace_target),
        "source_operands": {
            "from": dict(from_operand),
            "to": dict(to_operand),
        },
        "ranked_source_repairs": _copy_propagation_ranked_source_repairs(
            from_operand,
            to_operand,
        ),
    }
    if not _copy_propagation_repair_applies(trace_target):
        return summary
    for variant in ranked_variants:
        if _retained_c_source_variant_hit(variant):
            summary["status"] = "source-actionable"
            summary["best_source_candidate"] = _copy_repair_candidate_summary(
                variant
            )
            return summary
    unmapped_operands = _copy_propagation_unmapped_operands(
        [from_operand, to_operand]
    )
    summary["status"] = "terminal-blocker"
    summary["unmapped_operands"] = unmapped_operands
    retained_shape_candidates = _copy_propagation_retained_source_shape_candidates(
        ranked_variants
    )
    if retained_shape_candidates:
        summary["retained_source_shape_candidates"] = retained_shape_candidates
        terminal_summary = _copy_propagation_source_shape_terminal_summary(
            trace_target=trace_target,
            from_operand=from_operand,
            to_operand=to_operand,
            retained_candidates=retained_shape_candidates,
        )
        summary["terminal_summary"] = terminal_summary
        summary["terminal_blocker"] = terminal_summary["terminal_blocker"]
    else:
        summary["terminal_blocker"] = _copy_propagation_terminal_blocker(
            unmapped_operands
        )
    return summary


def _copy_propagation_repair_text(summary: Mapping[str, Any]) -> str | None:
    status = summary.get("status")
    if status in (None, "not-applicable"):
        return None
    line = (
        f"copy-propagation repair: {status} for "
        f"{summary.get('target_pair') or '?'}"
    )
    unmapped = summary.get("unmapped_operands")
    if status == "terminal-blocker" and isinstance(unmapped, list) and unmapped:
        rendered = ", ".join(
            f"{entry.get('token')}={entry.get('expression') or '?'}"
            for entry in unmapped
            if isinstance(entry, Mapping)
        )
        if rendered:
            line += f" - unmapped source operands: {rendered}"
    return line


def _parse_virtual_order_csv(value: str) -> list[tuple[int, int]]:
    from src.cli.debug import _parse_virtual_reg_token
    orders: list[tuple[int, int]] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        if "<" in token:
            left, right = token.split("<", 1)
            first, second = left, right
        elif ">" in token:
            left, right = token.split(">", 1)
            first, second = right, left
        else:
            raise typer.BadParameter(
                f"invalid order {token!r}; expected rA<rB or rB>rA"
            )
        if not first.strip() or not second.strip():
            raise typer.BadParameter(
                f"invalid order {token!r}; expected rA<rB or rB>rA"
            )
        orders.append((
            _parse_virtual_reg_token(first.strip()),
            _parse_virtual_reg_token(second.strip()),
        ))
    return orders


def _parse_probe_provenance(value: str) -> dict:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"--probe-provenance must be a JSON object: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("--probe-provenance must be a JSON object")
    return payload


def _restore_source_snapshot(path: Path, original: str) -> str | None:
    try:
        path.write_text(original)
        restored = path.read_text()
    except Exception as exc:
        return f"failed to restore {path}: {type(exc).__name__}: {exc}"
    if restored != original:
        return f"failed to restore {path}: restored content hash mismatch"
    return None


class _SourceRestoreBytesError(RuntimeError):
    def __init__(self, message: str, backup_path: Path | None = None):
        super().__init__(message)
        self.backup_path = backup_path


@contextmanager
def _source_restore_byte_guards(
    paths: Iterable[Path | None],
    *,
    melee_root: Path,
) -> Iterator[None]:
    from src.cli.debug import _source_restore_byte_guard, _unique_existing_source_restore_paths
    with ExitStack() as stack:
        for path in _unique_existing_source_restore_paths(paths):
            stack.enter_context(
                _source_restore_byte_guard(path, melee_root=melee_root)
            )
        yield


def _select_order_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value):
        return _select_order_json_safe(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {
            str(_select_order_json_safe(key)): _select_order_json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_select_order_json_safe(item) for item in value]
    return str(value)


def _select_order_variant_target_score(
    variant: Mapping[str, Any],
) -> dict[str, Any] | None:
    from src.cli.debug import _first_int, _select_order_int_mapping
    objective = variant.get("objective")
    candidates: list[Any] = []
    if isinstance(objective, Mapping):
        candidates.append(objective.get("target_score"))
        validator = objective.get("validator_payload")
        if isinstance(validator, Mapping):
            candidates.append(validator.get("target_score"))
    candidates.append(variant.get("target_score"))
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            return _select_order_json_safe(dict(candidate))
    if isinstance(objective, Mapping):
        targets = _select_order_int_mapping(objective.get("force_phys_targets"))
        assignments = objective.get("force_phys_assignments")
        if targets and isinstance(assignments, Mapping):
            virtuals: dict[str, dict[str, Any]] = {}
            matched = 0
            for virtual, expected in sorted(targets.items()):
                raw_assignment = assignments.get(
                    str(virtual),
                    assignments.get(virtual),
                )
                actual = None
                hit = False
                if isinstance(raw_assignment, Mapping):
                    actual = _first_int(raw_assignment.get("actual"))
                    status = raw_assignment.get("status")
                    hit = actual == expected or status == "hit"
                if hit:
                    matched += 1
                virtuals[str(virtual)] = {
                    "expected": expected,
                    "actual": actual,
                    "hit": hit,
                    "matched": hit,
                }
            return {
                "matched": matched,
                "total": len(virtuals),
                "targeted": len(virtuals),
                "virtuals": virtuals,
                "source": "force-phys-assignments",
            }
    return None


def _select_order_close_source_restore(
    source_restore: _SelectOrderCommandSourceRestore,
) -> tuple[bool, str | None]:
    from src.cli.debug import _SelectOrderCommandSourceRestore
    try:
        source_restore.close()
    except Exception as exc:
        return False, str(exc)
    path = source_restore.path
    original = source_restore.original
    if path is None or original is None:
        return True, None
    try:
        return path.exists() and path.read_bytes() == original, None
    except Exception as exc:
        return False, str(exc)


class _MalformedSourceCandidate(ValueError):
    def __init__(self, message: str, *, source_hunk: str | None = None):
        super().__init__(message)
        self.source_hunk = source_hunk


def _compact_source_hunk_for_function(
    source_text: str,
    function: str,
    *,
    context: int = 4,
    max_lines: int = 14,
) -> str:
    lines = source_text.splitlines()
    if not lines:
        return ""

    span = find_source_function(source_text, function)
    if span is not None:
        anchor_offset = span.sig_start
    else:
        match = re.search(rf"\b{re.escape(function)}\s*\(", source_text)
        if match is not None:
            anchor_offset = match.start()
        else:
            definitions = find_function_definitions(source_text)
            anchor_offset = definitions[0].sig_start if definitions else 0

    anchor_line = source_text[:anchor_offset].count("\n")
    start = max(0, anchor_line - context)
    end = min(len(lines), max(start + 1, anchor_line + max_lines - context))
    return "\n".join(f"{idx + 1}: {lines[idx]}" for idx in range(start, end))


def _prevalidate_lifetime_layout_source_candidate(
    path: Path,
    *,
    function: str,
) -> tuple[str, str | None]:
    source_text = path.read_text(encoding="utf-8", errors="replace")
    if find_source_function(source_text, function) is not None:
        return source_text, None

    names = [span.name for span in find_function_definitions(source_text)[:5]]
    suffix = f"; candidate defines: {', '.join(names)}" if names else ""
    raise _MalformedSourceCandidate(
        (
            f"target function {function} not found in candidate source before "
            f"compile: {path}{suffix}"
        ),
        source_hunk=_compact_source_hunk_for_function(source_text, function),
    )


def _name_magic_header_for_source(source: Path | None) -> Path | None:
    if source is None:
        return None
    header = source.with_suffix(".h")
    return header if header.exists() else None


def _name_magic_header_candidate_text(
    header_text: str,
    declarations: list[str] | tuple[str, ...],
) -> str:
    from src.cli.debug import _normalize_header_declaration
    missing = [
        declaration
        for declaration in (
            _normalize_header_declaration(item) for item in declarations
        )
        if declaration and declaration not in header_text
    ]
    if not missing:
        return header_text

    block = "\n".join(missing)
    lines = header_text.splitlines(keepends=True)
    offset = 0
    final_endif_offset: int | None = None
    for line in lines:
        if line.strip().startswith("#endif"):
            final_endif_offset = offset
        offset += len(line)
    if final_endif_offset is None:
        return header_text.rstrip() + "\n\n" + block + "\n"

    before = header_text[:final_endif_offset].rstrip()
    after = header_text[final_endif_offset:].lstrip("\n")
    return before + "\n\n" + block + "\n\n" + after


def _select_order_source_fingerprints(
    *,
    base_source: str,
    candidate_source: str,
    function: str,
) -> tuple[str, str]:
    candidate_function = extract_function(candidate_source, function)
    body_basis = candidate_function if candidate_function is not None else candidate_source
    body_hash = hashlib.sha256(body_basis.encode("utf-8")).hexdigest()[:16]
    base_function = extract_function(base_source, function) or base_source
    diff_text = "\n".join(difflib.unified_diff(
        base_function.splitlines(),
        body_basis.splitlines(),
        lineterm="",
    ))
    diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()[:16]
    return body_hash, diff_hash


def _rank_select_order_candidates_real_first(
    variants: list[dict],
) -> list[dict]:
    from src.cli.debug import _select_order_real_score_sort_key
    ranked = [dict(variant) for variant in variants]
    ranked.sort(key=_select_order_real_score_sort_key, reverse=True)
    for idx, variant in enumerate(ranked, start=1):
        variant["rank"] = idx
    return ranked


def _select_order_force_phys_hit_registers(
    variant: Mapping[str, Any],
) -> dict[str, int]:
    from src.cli.debug import _select_order_force_phys_hits, _select_order_int_mapping
    objective = variant.get("objective")
    if not isinstance(objective, Mapping):
        return {}
    targets = _select_order_int_mapping(objective.get("force_phys_targets"))
    hits = _select_order_force_phys_hits(variant)
    return {str(ig_idx): targets[ig_idx] for ig_idx in sorted(hits & targets.keys())}


def _select_order_protected_register_preservation(
    variant: Mapping[str, Any],
    protected_hits: Mapping[str, int] | Mapping[int, int],
) -> dict[str, Any]:
    achieved = _select_order_force_phys_hit_registers(variant)
    preserved: dict[str, int] = {}
    lost: dict[str, dict[str, Any]] = {}
    for raw_ig, raw_phys in protected_hits.items():
        if (
            not isinstance(raw_ig, (int, str))
            or not str(raw_ig).lstrip("-").isdigit()
        ):
            continue
        if isinstance(raw_phys, bool) or not isinstance(raw_phys, (int, str)):
            continue
        if not str(raw_phys).lstrip("-").isdigit():
            continue
        ig = str(int(raw_ig))
        expected = int(raw_phys)
        actual = achieved.get(ig)
        if actual == expected:
            preserved[ig] = expected
        else:
            lost[ig] = {
                "expected": expected,
                "actual": actual,
            }
    return {
        "protected_register_count": len(preserved) + len(lost),
        "protected_preserved_count": len(preserved),
        "preserved_protected_registers": preserved,
        "lost_protected_registers": lost,
    }


def _select_order_guard_repair_variant_sort_key(
    variant: Mapping[str, Any],
    *,
    protected_hits: Mapping[str, int],
) -> tuple[float, float, float, float, float, float, float]:
    from src.cli.debug import _select_order_float_sort_value
    objective = variant.get("objective")
    if not isinstance(objective, Mapping):
        return (
            0.0,
            0.0,
            0.0,
            -1_000_000.0,
            -1_000_000.0,
            -1_000_000.0,
            -1.0,
        )
    guard = variant.get("structural_guard")
    guard_accepted = (
        1.0
        if isinstance(guard, Mapping) and guard.get("accepted") is True
        else 0.0
    )
    achieved = _select_order_force_phys_hit_registers(variant)
    protected_count = sum(
        1
        for ig_idx, phys in protected_hits.items()
        if achieved.get(str(ig_idx)) == phys
    )
    satisfied_count = _select_order_float_sort_value(
        objective.get("force_phys_satisfied_count"),
        default=0.0,
    )
    complement_count = max(0.0, satisfied_count - float(protected_count))
    normalized_diff_lines = 1_000_000.0
    frame_delta = objective.get("frame_delta")
    if isinstance(guard, Mapping):
        normalized_diff_lines = _select_order_float_sort_value(
            guard.get("normalized_diff_lines"),
            default=1_000_000.0,
        )
        frame_delta = guard.get("frame_delta", frame_delta)
    frame_delta_value = abs(
        _select_order_float_sort_value(frame_delta, default=1_000_000.0)
    )
    force_distance = _select_order_float_sort_value(
        objective.get("force_phys_distance"),
        default=1_000_000.0,
    )
    match_percent = _select_order_float_sort_value(
        objective.get("match_percent"),
        default=-1.0,
    )
    return (
        guard_accepted,
        float(protected_count),
        complement_count,
        -normalized_diff_lines,
        -frame_delta_value,
        -force_distance,
        match_percent,
    )


def _select_order_complement_target_summary(
    *,
    force_phys: Mapping[int, int] | Mapping[str, int],
    seed_candidate: Mapping[str, Any],
    protected_registers: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    from src.cli.debug import _select_order_int_mapping
    objective_targets = _select_order_int_mapping(
        (seed_candidate.get("objective") or {}).get("force_phys_targets")
        if isinstance(seed_candidate.get("objective"), Mapping)
        else {}
    )
    targets = {
        str(ig_idx): int(phys)
        for ig_idx, phys in (
            objective_targets or _select_order_int_mapping(force_phys)
        ).items()
    }
    missing = dict(seed_candidate.get("missing_registers") or {})
    mismatched = dict(seed_candidate.get("mismatched_registers") or {})
    complement: dict[str, dict[str, Any]] = {}
    for ig_idx, expected in targets.items():
        if protected_registers.get(ig_idx) == expected:
            continue
        if ig_idx in missing:
            complement[ig_idx] = {
                "expected": expected,
                "actual": None,
                "status": "missing",
            }
            continue
        mismatch = mismatched.get(ig_idx)
        if isinstance(mismatch, Mapping):
            complement[ig_idx] = {
                "expected": expected,
                "actual": mismatch.get("actual"),
                "status": "mismatched",
            }
            continue
        complement[ig_idx] = {
            "expected": expected,
            "actual": None,
            "status": "unhit",
        }
    return dict(sorted(complement.items(), key=lambda item: int(item[0])))


def _select_order_tag_targeted_interference_probe(
    probe: Any,
    *,
    plan: Mapping[str, Any],
) -> Any:
    provenance = getattr(probe, "provenance", None)
    provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
    provenance["targeted_interference_source_transform"] = {
        "kind": "select-order-targeted-interference",
        "candidate_label": plan.get("candidate_label"),
        "source_retained": plan.get("source_retained"),
        "target_assignments": dict(plan.get("target_assignments") or {}),
        "probe_intents": list(plan.get("probe_intents") or []),
        "terminal_blockers": list(plan.get("terminal_blockers") or []),
    }
    try:
        return dataclasses.replace(
            probe,
            description=(
                f"{getattr(probe, 'description', '')} "
                "[select-order targeted interference repair]"
            ).strip(),
            provenance=provenance,
        )
    except (TypeError, ValueError):
        return probe


def _select_order_default_complement_targets(
    *,
    force_phys: Mapping[int, int],
    protected_registers: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    from src.cli.debug import _select_order_int_mapping
    targets = _select_order_int_mapping(force_phys)
    out: dict[str, dict[str, Any]] = {}
    for ig_idx, expected in targets.items():
        key = str(ig_idx)
        if protected_registers.get(key) == expected:
            continue
        out[key] = {
            "expected": expected,
            "actual": None,
            "status": "unhit",
        }
    return dict(sorted(out.items(), key=lambda item: int(item[0])))


def _select_order_guard_repair_entry_protected_complement(
    variant: Mapping[str, Any],
    *,
    force_phys: Mapping[int, int],
    protected_hits: Mapping[str, int],
    complement_targets: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    from src.cli.debug import _select_order_guard_repair_result_summary, _select_order_protected_complement_candidate_summary
    protected_registers = {
        str(ig_idx): int(phys)
        for ig_idx, phys in protected_hits.items()
        if str(ig_idx).lstrip("-").isdigit()
    }
    if not protected_registers:
        return None
    targets = (
        dict(complement_targets)
        if complement_targets
        else _select_order_default_complement_targets(
            force_phys=force_phys,
            protected_registers=protected_registers,
        )
    )
    if not targets:
        return None
    repair_summary = _select_order_guard_repair_result_summary(variant)
    if repair_summary is None:
        return None
    candidate_summary = _select_order_protected_complement_candidate_summary(
        repair_summary,
        protected_registers=protected_registers,
        complement_targets=targets,
    )
    return {
        "protected_registers": protected_registers,
        "protected_count": len(protected_registers),
        "complement_targets": targets,
        "complement_count": len(targets),
        "candidate": candidate_summary,
    }


def _select_order_guard_repair_seed_variants(
    ranked_variants: list[dict],
    *,
    force_phys: Mapping[int, int],
    max_seeds: int,
) -> list[dict]:
    from src.cli.debug import (
        _select_order_guard_repair_candidate_sort_key,
        _select_order_guard_repair_candidate_summary,
    )
    if not force_phys or max_seeds <= 0:
        return []
    seeds: list[tuple[tuple[float, float, float], dict]] = []
    for variant in ranked_variants:
        candidate = _select_order_guard_repair_candidate_summary(variant)
        if candidate is None:
            continue
        source_path = candidate.get("source_retained") or candidate.get("path")
        if not isinstance(source_path, str) or not source_path.endswith(".c"):
            continue
        seeds.append((_select_order_guard_repair_candidate_sort_key(candidate), variant))
    seeds.sort(key=lambda item: item[0])
    return [variant for _key, variant in seeds[:max_seeds]]


def _select_order_source_attributed_fallback_lead_count(
    fallback_leads: object,
    source_attributions: Mapping[int, Any] | Mapping[str, Any],
) -> int:
    from src.cli.debug import _select_order_source_attr_for_ig
    if not isinstance(fallback_leads, list):
        return 0
    count = 0
    for lead in fallback_leads:
        if not isinstance(lead, Mapping):
            continue
        try:
            target_ig = int(lead["target_ig"])
        except (KeyError, TypeError, ValueError):
            continue
        if _select_order_source_attr_for_ig(source_attributions, target_ig) is not None:
            count += 1
    return count


def _select_order_residual_variant_labels_from_buckets(
    buckets: Mapping[str, list[Mapping[str, Any]]],
) -> set[str]:
    labels: set[str] = set()
    for entries in buckets.values():
        for entry in entries:
            label = entry.get("label")
            if isinstance(label, str):
                labels.add(label)
    return labels


def _format_select_order_residual(residual: Mapping[str, Any]) -> str:
    if residual.get("status") != "ok":
        return (
            f"   residual: {residual.get('status')} "
            f"{residual.get('reason', '')}"
        ).rstrip()
    first = residual.get("first_divergence") or {}
    actual = first.get("baseline_reg")
    target = first.get("target_reg")
    actual_text = f"r{actual}" if isinstance(actual, int) else "?"
    target_text = f"r{target}" if isinstance(target, int) else "?"
    lever = residual.get("next_source_lever") or first.get("local_target") or "?"
    return (
        f"   residual: Case {first.get('case', '?')} "
        f"ig{first.get('ig_idx', '?')} {actual_text}->{target_text}; "
        f"next: {lever}"
    )


def _select_order_window_order_probe_reserve(
    window_order_fallback: object,
    max_count: int,
) -> int:
    if max_count <= 1:
        return 0
    if (
        not isinstance(window_order_fallback, Mapping)
        or not window_order_fallback.get("leads")
    ):
        return 0
    promoted = window_order_fallback.get("force_phys_attributed_temp_leads")
    if isinstance(promoted, list) and promoted:
        promoted_targets = {
            int(lead["target_ig"])
            for lead in promoted
            if isinstance(lead, Mapping)
            and not isinstance(lead.get("target_ig"), bool)
            and str(lead.get("target_ig", "")).lstrip("-").isdigit()
        }
        promoted_count = len(promoted_targets)
        if promoted_count:
            return min(
                max(max_count // 2, promoted_count * 3),
                max_count - 1,
            )
    return min(3, max_count - 1)


def _select_order_safe_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return cleaned[:80] or "candidate"


def _solve_source_attribution_dict(source) -> dict | None:
    if source is None:
        return None
    if isinstance(source, Mapping):
        return {
            key: source.get(key)
            for key in (
                "kind",
                "name",
                "type",
                "source_file",
                "source_line",
                "source_col",
                "expression",
                "base_virtual",
                "base_var",
                "field_offset",
                "field_name",
                "confidence",
                "base_confidence",
                "first_def",
                "call_symbol",
                "copy_chain",
                "use_sites",
            )
            if key in source
        }
    payload = {
        "kind": getattr(source, "kind", None),
        "name": getattr(source, "name", None),
        "type": getattr(source, "type", None),
        "source_file": getattr(source, "source_file", None),
        "source_line": getattr(source, "source_line", None),
        "source_col": getattr(source, "source_col", None),
        "expression": getattr(source, "expression", None),
        "base_virtual": getattr(source, "base_virtual", None),
        "base_var": getattr(source, "base_var", None),
        "field_offset": getattr(source, "field_offset", None),
        "field_name": getattr(source, "field_name", None),
        "confidence": getattr(source, "confidence", None),
        "base_confidence": getattr(source, "base_confidence", None),
        "call_symbol": getattr(source, "call_symbol", None),
    }
    first_def = getattr(source, "first_def", None)
    if first_def is not None:
        payload["first_def"] = dataclasses.asdict(first_def)
    copy_chain = getattr(source, "copy_chain", None)
    if copy_chain:
        payload["copy_chain"] = list(copy_chain)
    use_sites = getattr(source, "use_sites", None)
    if use_sites:
        payload["use_sites"] = [
            dataclasses.asdict(site) for site in use_sites
        ]
    return payload


def _same_filesystem_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _coalesce_search_probe_root(melee_root: Path, function: str) -> Path:
    from src.cli.debug import _safe_filename
    root = (
        melee_root
        / "build"
        / "mwcc_debug_cache"
        / "probes"
        / "coalesce_search"
        / _safe_filename(function)
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _retain_coalesce_search_source(
    source_path: Path,
    *,
    candidate_id: str,
    probe_root: Path,
    reason: str,
) -> Path:
    from src.cli.debug import _safe_filename
    source_text = source_path.read_text(encoding="utf-8")
    digest = hashlib.sha1(source_text.encode("utf-8")).hexdigest()[:12]
    retained_dir = probe_root / reason
    retained_dir.mkdir(parents=True, exist_ok=True)
    retained_path = retained_dir / f"{_safe_filename(candidate_id)}-{digest}.c"
    retained_path.write_text(source_text, encoding="utf-8")
    return retained_path


def _retain_coalesce_search_pcdump(
    pcdump_text: str,
    *,
    candidate_id: str,
    probe_root: Path,
    reason: str,
) -> Path:
    from src.cli.debug import _safe_filename
    digest = hashlib.sha1(pcdump_text.encode("utf-8")).hexdigest()[:12]
    retained_dir = probe_root / reason
    retained_dir.mkdir(parents=True, exist_ok=True)
    retained_path = (
        retained_dir / f"{_safe_filename(candidate_id)}-{digest}.pcdump.txt"
    )
    retained_path.write_text(pcdump_text, encoding="utf-8")
    return retained_path


def _parse_lifetime_layout_candidate(spec: str) -> tuple[str, str, Path]:
    if "=" not in spec:
        raise typer.BadParameter(
            f"invalid candidate {spec!r}; expected OPERATOR=path or LABEL:OPERATOR=path"
        )
    left, raw_path = spec.split("=", 1)
    if not left.strip() or not raw_path.strip():
        raise typer.BadParameter(
            f"invalid candidate {spec!r}; expected OPERATOR=path or LABEL:OPERATOR=path"
        )
    if ":" in left:
        label, operator = left.split(":", 1)
    else:
        label = left
        operator = left
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise typer.BadParameter(f"candidate path not found: {path}")
    return label.strip(), operator.strip(), path


def _parse_select_order_guard_repair_seed(spec: str) -> dict[str, str]:
    label, operator, path = _parse_lifetime_layout_candidate(spec)
    if path.suffix.lower() != ".c":
        raise typer.BadParameter(
            f"guard repair seed path must be a .c source: {path}"
        )
    return {
        "label": label,
        "operator": operator,
        "path": str(path),
    }


def _make_real_score_status(command: str, label: str) -> Callable[[str], None]:
    def _status(message: str) -> None:
        print(f"[{command}] {label}: {message}", file=sys.stderr, flush=True)

    return _status


def _full_unit_source_for_probe(
    probe: Any,
    source_path_for_probes: Path | None,
) -> Path | None:
    from src.cli.debug import _probe_requires_full_unit_source
    if not _probe_requires_full_unit_source(probe):
        return None
    return source_path_for_probes


def _path_inside_repo(path: Path, melee_root: Path) -> bool:
    try:
        path.resolve().relative_to(melee_root.resolve())
    except ValueError:
        return False
    return True


def _pressure_signature_from_pcdump_or_exit(
    signature_func: Callable[..., object],
    pcdump_text: str,
    function: str,
    **kwargs,
):
    try:
        return signature_func(pcdump_text, function, **kwargs)
    except ValueError as exc:
        if "not found in pcdump" not in str(exc):
            raise
        available = [fn.name for fn in parse_pcdump(pcdump_text)]
        _abort_function_not_in_dump(function, available)


def _generate_anti_coalesce_split_probes(
    source_text: str,
    function: str,
    var_name: str,
    *,
    max_probes: int,
):
    from ...mwcc_debug.mutators import (
        MutationUnsupported,
        mutate_anti_coalesce_copy_before_use,
    )
    from ...mwcc_debug.pressure_explorer import LifetimeLayoutProbe

    probes: list[LifetimeLayoutProbe] = []
    for read_idx in range(max(0, max_probes)):
        label = f"anti-coalesce-{var_name}-use{read_idx}"
        try:
            patched = mutate_anti_coalesce_copy_before_use(
                source_text,
                function,
                var_name,
                at_stmt_index=read_idx,
                new_name=f"{var_name}_split_{read_idx}",
            )
        except MutationUnsupported as exc:
            if "out of range" in str(exc):
                break
            continue
        if patched == source_text:
            continue
        probes.append(LifetimeLayoutProbe(
            label=label,
            operator="anti-coalesce-volatile-copy",
            description=(
                f"Force a non-coalesced copy of {var_name} for read site "
                f"{read_idx} by round-tripping it through a volatile local."
            ),
            source_text=patched,
            provenance={
                "kind": "anti-coalesce-volatile-copy",
                "var": var_name,
                "read_site": read_idx,
            },
        ))
    return probes


def _coalesce_find_function_body_span(
    source: str,
    function: str,
) -> tuple[int, int] | None:
    from src.cli.debug import _coalesce_find_matching
    for match in re.finditer(rf"\b{re.escape(function)}\s*\(", source):
        open_paren = source.find("(", match.start())
        if open_paren < 0:
            continue
        close_paren = _coalesce_find_matching(
            source,
            open_paren,
            open_char="(",
            close_char=")",
        )
        if close_paren is None:
            continue
        cursor = close_paren + 1
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1
        if cursor >= len(source) or source[cursor] != "{":
            continue
        close_brace = _coalesce_find_matching(
            source,
            cursor,
            open_char="{",
            close_char="}",
        )
        if close_brace is not None:
            return cursor + 1, close_brace
    return None


def _coalesce_line_no(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _generate_copy_survived_pointer_reset_probes(
    source_text: str,
    function: str,
    trace_target: Mapping[str, Any] | None,
    *,
    max_probes: int,
):
    from src.cli.debug import _copy_survived_pointer_reset_variants, _find_copy_survived_pointer_resets
    if trace_target is None or max_probes <= 0:
        return []
    likely = " ".join(
        str(trace_target.get(key) or "")
        for key in ("trace_status", "likely_cause", "transform_category")
    ).lower()
    if "copy-survived" not in likely:
        return []
    uses = _find_copy_survived_pointer_resets(
        source_text,
        function,
        trace_target,
    )
    if not uses:
        return []
    per_reset = [
        _copy_survived_pointer_reset_variants(source_text, use, index=index)
        for index, use in enumerate(uses)
    ]
    probes = []
    seen: set[str] = set()
    max_len = max((len(variants) for variants in per_reset), default=0)
    for variant_idx in range(max_len):
        for variants in per_reset:
            if len(probes) >= max_probes:
                return probes
            if variant_idx >= len(variants):
                continue
            probe = variants[variant_idx]
            if probe.source_text in seen:
                continue
            seen.add(probe.source_text)
            probes.append(probe)
    return probes


def _coalesce_force_phys_objective_fields(
    *,
    baseline_text: str,
    candidate_text: str,
    function: str,
    class_id: int,
    force_phys: Mapping[int, int],
) -> dict[str, Any]:
    from src.cli.debug import _coalesce_assigned_regs_from_pcdump
    if not force_phys:
        return {}
    baseline_assigned = _coalesce_assigned_regs_from_pcdump(
        baseline_text,
        function,
        class_id=class_id,
    )
    candidate_assigned = _coalesce_assigned_regs_from_pcdump(
        candidate_text,
        function,
        class_id=class_id,
    )
    assignments: dict[str, dict[str, Any]] = {}
    satisfied_count = 0
    baseline_satisfied_count = 0
    missing: list[int] = []
    mismatches: dict[str, dict[str, int | None]] = {}
    distance = 0
    baseline_distance = 0
    for ig_idx, expected in sorted(force_phys.items()):
        before = baseline_assigned.get(ig_idx)
        after = candidate_assigned.get(ig_idx)
        satisfied = after == expected
        baseline_satisfied = before == expected
        if satisfied:
            satisfied_count += 1
        if baseline_satisfied:
            baseline_satisfied_count += 1
        if after is None:
            missing.append(ig_idx)
        elif not satisfied:
            mismatches[str(ig_idx)] = {
                "expected": expected,
                "actual": after,
            }
        if after is None:
            distance += 1000
        else:
            distance += abs(after - expected)
        if before is None:
            baseline_distance += 1000
        else:
            baseline_distance += abs(before - expected)
        assignments[str(ig_idx)] = {
            "expected": expected,
            "before": before,
            "after": after,
            "baseline_satisfied": baseline_satisfied,
            "satisfied": satisfied,
        }
    target_count = len(force_phys)
    exact = satisfied_count == target_count
    if exact:
        progress_kind = "exact"
    elif satisfied_count > baseline_satisfied_count or distance < baseline_distance:
        progress_kind = "improved"
    elif satisfied_count < baseline_satisfied_count or distance > baseline_distance:
        progress_kind = "regressed"
    else:
        progress_kind = "unchanged"
    return {
        "force_phys_targets": {
            str(ig_idx): expected for ig_idx, expected in sorted(force_phys.items())
        },
        "force_phys_assignments": assignments,
        "force_phys_satisfied": exact,
        "force_phys_satisfied_count": satisfied_count,
        "force_phys_target_count": target_count,
        "force_phys_baseline_satisfied_count": baseline_satisfied_count,
        "force_phys_missing": missing,
        "force_phys_mismatches": mismatches,
        "force_phys_distance": distance,
        "force_phys_baseline_distance": baseline_distance,
        "force_phys_progress_kind": progress_kind,
    }


def _parse_force_coalesce_pair_specs(
    force_coalesce: str,
) -> list[tuple[int, int, int | None]]:
    from src.cli.debug import _parse_force_coalesce_virtual
    pairs: list[tuple[int, int, int | None]] = []
    for raw in force_coalesce.split(","):
        item = raw.strip()
        if not item:
            continue
        if "=" not in item:
            raise typer.BadParameter(
                f"invalid --force-coalesce pair {item!r}; expected virt=root"
            )
        lhs, rhs = item.split("=", 1)
        if not lhs.strip() or not rhs.strip():
            raise typer.BadParameter(
                f"invalid --force-coalesce pair {item!r}; expected virt=root"
            )
        left, left_class = _parse_force_coalesce_virtual(lhs)
        right, right_class = _parse_force_coalesce_virtual(rhs)
        if (
            left_class is not None
            and right_class is not None
            and left_class != right_class
        ):
            raise typer.BadParameter(
                f"invalid --force-coalesce pair {item!r}; mixed register classes"
            )
        pair_class = left_class if left_class is not None else right_class
        pairs.append((left, right, pair_class))
    return pairs


def _suggest_similar_functions(target: str, available: list[str], n: int = 5) -> list[str]:
    """Return up to `n` available function names that look similar to `target`.

    Uses Python's difflib for fuzzy ranking. Common typos (e.g. wrong
    case, missing underscore, trailing digit drift) are surfaced this way.
    """
    import difflib
    return difflib.get_close_matches(target, available, n=n, cutoff=0.5)


def _abort_function_not_in_dump(function: str, available_names: list[str]) -> None:
    """Emit a rich error message + exit. Used by every command that
    fails to find a function in a pcdump.
    """
    _emit_function_not_in_dump(function, available_names)
    raise typer.Exit(3)


def _abort_frame_function_not_in_dump(function: str, pcdump_text: str) -> NoReturn:
    available_names = [fn.name for fn in parse_pcdump(pcdump_text)]
    _emit_function_not_in_dump(
        function,
        available_names,
        include_available_sample=True,
        hint=(
            "Hint: this pcdump does not contain the requested function name. "
            "If it came from campaign notes or a semantic alias, retry with "
            "the canonical symbol listed above; otherwise regenerate coverage "
            "with `debug dump remote <c_file>` or `debug dump local <c_file>` "
            "after source/cache changes."
        ),
    )
    raise typer.Exit(3)


def _emit_function_not_in_dump(
    function: str,
    available_names: list[str],
    *,
    hint: Optional[str] = None,
    include_available_sample: bool = False,
) -> None:
    typer.echo(f"function '{function}' not found in pcdump.", err=True)
    suggestions = _suggest_similar_functions(function, available_names)
    if suggestions:
        typer.echo("", err=True)
        typer.echo("Did you mean one of these?", err=True)
        for s in suggestions:
            typer.echo(f"  - {s}", err=True)
    if include_available_sample or not suggestions:
        typer.echo("", err=True)
        sample_limit = 12
        sample = available_names[:sample_limit]
        if sample:
            if len(available_names) <= sample_limit:
                typer.echo("Functions in this dump:", err=True)
            else:
                typer.echo(
                    f"Sample of {len(available_names)} functions in this dump:",
                    err=True,
                )
            for s in sample:
                typer.echo(f"  - {s}", err=True)
            if len(available_names) > sample_limit:
                typer.echo(
                    f"  ... +{len(available_names) - sample_limit} more",
                    err=True,
                )
    typer.echo("", err=True)
    if hint is None:
        hint = (
            "Hint: check spelling, or if the source changed since the cache "
            "was generated, re-run `debug dump remote <c_file>`."
        )
    typer.echo(hint, err=True)


def _auto_pcdump_cache_metadata(
    pcdump: Optional[Path],
    function: Optional[str],
    melee_root: Path = DEFAULT_MELEE_ROOT,
) -> dict | None:
    """Return cache freshness metadata for auto-resolved pcdumps."""
    from src.cli.debug import _find_unit_for_function
    from src.cli.debug import _find_unit_for_function  # noqa: PLC0415
    if pcdump is not None or function is None:
        return None
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        return None
    entry = pcdump_cache.lookup(melee_root, unit)
    if entry is None:
        return None
    payload = {
        "unit": unit,
        "path": str(entry.path),
        "source_path": str(entry.source_path),
        "fresh": entry.fresh,
    }
    if entry.path.exists():
        payload["cache_mtime"] = entry.path.stat().st_mtime
    if entry.source_path.exists():
        payload["source_mtime"] = entry.source_path.stat().st_mtime
    return payload


def _timeout_message(cmd: list[str], timeout: float | None) -> str:
    if timeout is None:
        return f"timed out running {' '.join(cmd)}"
    return f"timed out after {timeout:g}s running {' '.join(cmd)}"


def _timeout_before_deadline(
    deadline: float | None,
    fallback_timeout: float | None,
    action: str,
    *,
    min_seconds: float = 0.1,
) -> tuple[float | None, str | None]:
    """Return a subprocess timeout clamped to a deadline, or an error."""
    if deadline is None:
        return fallback_timeout, None
    remaining = deadline - time.monotonic()
    if remaining < min_seconds:
        return None, f"budget exhausted before {action}"
    if fallback_timeout is None:
        return remaining, None
    return min(float(fallback_timeout), remaining), None


def _score_source_target_details(
    result: Any,
    target_spec: Mapping[str, Any],
) -> dict[str, Any]:
    target_virtuals_raw = target_spec.get("virtuals", {})
    target_virtuals: dict[int, int] = {}
    if isinstance(target_virtuals_raw, Mapping):
        for virtual, phys in target_virtuals_raw.items():
            try:
                target_virtuals[int(virtual)] = int(phys)
            except (TypeError, ValueError):
                continue

    wrong_by_virtual: dict[int, tuple[int, int | None]] = {}
    wrong_details: list[dict[str, Any]] = []
    for virtual, expected, actual in getattr(result, "wrong", []) or []:
        try:
            virtual_i = int(virtual)
            expected_i = int(expected)
            actual_i = int(actual)
        except (KeyError, TypeError, ValueError):
            continue
        normalized_actual = None if actual_i < 0 else actual_i
        wrong_by_virtual[virtual_i] = (expected_i, normalized_actual)
        wrong_details.append({
            "virtual": virtual_i,
            "expected": expected_i,
            "actual": normalized_actual,
        })

    virtuals: dict[str, dict[str, Any]] = {}
    for virtual, expected in sorted(target_virtuals.items()):
        if virtual in wrong_by_virtual:
            wrong_expected, actual = wrong_by_virtual[virtual]
            virtuals[str(virtual)] = {
                "expected": wrong_expected,
                "actual": actual,
                "matched": False,
            }
        else:
            virtuals[str(virtual)] = {
                "expected": expected,
                "actual": expected,
                "matched": True,
            }

    return {
        "total": getattr(result, "total", None),
        "matched": getattr(result, "matched", None),
        "targeted": getattr(result, "targeted", None),
        "virtual_distance": getattr(result, "virtual_distance", None),
        "virtual_penalty": getattr(result, "virtual_penalty", None),
        "virtuals": virtuals,
        "wrong": wrong_details,
        "spill_unexpected": list(getattr(result, "spill_unexpected", []) or []),
        "spill_missing": list(getattr(result, "spill_missing", []) or []),
        "spill_penalty": getattr(result, "spill_penalty", None),
        "interferer_distance": getattr(result, "interferer_distance", None),
        "interferer_penalty": getattr(result, "interferer_penalty", None),
        "frame": {
            "targeted": getattr(result, "frame_targeted", False),
            "size_actual": getattr(result, "frame_size_actual", None),
            "size_target": getattr(result, "frame_size_target", None),
            "size_distance": getattr(result, "frame_size_distance", None),
            "unused_distance": getattr(result, "frame_unused_distance", None),
            "penalty": getattr(result, "frame_penalty", None),
        },
    }


def _read_expression_source(
    path: Path | None,
    *,
    melee_root: Path,
) -> tuple[str | None, str | None]:
    if path is None:
        return None, None
    resolved = path if path.is_absolute() else melee_root / path
    try:
        return resolved.read_text(encoding="utf-8", errors="replace"), str(path)
    except OSError:
        return None, str(path)
