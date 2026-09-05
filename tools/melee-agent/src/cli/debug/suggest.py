"""`debug suggest ...` — source-shape and mismatch fix suggestions.

Carved out of cli/debug/__init__.py. Contains the suggest_app Typer instance,
all 10 suggest command handlers, and their suggest-only private helpers.

Shared helpers (module-level names that tests patch on the cli.debug package)
still live in cli/debug/__init__.py.  They are reached via call-time (deferred)
``from src.cli.debug import ...`` imports inside the function bodies — a
load-time import would create a cycle (__init__ imports this module) and would
also break ``monkeypatch.setattr(debug_cli, ...)`` semantics, since the patched
name must resolve against __init__ at call time.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Annotated, Any, Mapping, Optional, Sequence

import typer

from .._common import DEFAULT_MELEE_ROOT
from ...mwcc_debug import (
    parse_pcdump,
)
from ...mwcc_debug.cast_audit import (
    audit_function_casts,
    crossref_with_asm,
    detect_signedness_mismatches,
    find_call_sites,
)
from ...mwcc_debug.frame_reservations import analyze_frame_reservations
from ...mwcc_debug.protected_expression_reconciliation import (
    _candidate_id_from_evidence_filename,
)
from ...mwcc_debug.signature_audit import (
    audit_signature_call_type,
    validate_signature_patches,
)
from ...mwcc_debug.source_patch import (
    find_function as find_source_function,
    find_function_definitions,
)

suggest_app = typer.Typer(help="Suggest source-shape and mismatch fixes.")

__all__ = [
    "_signature_source_for_function",
    "_signature_payload_match_percent",
    "_run_signature_candidate_checkdiff",
    "_signature_report_payload",
    "_print_signature_report",
    "_signature_sibling_baselines",
    "_signature_scoreable_sibling_functions",
    "_emit_suggest_schedule_source",
    "_attach_expression_source_generation_validation_hints",
    "_repo_relative_for_hint",
    "_load_protected_reconcile_candidate_scores",
    "_load_protected_reconcile_source_hunks",
    "_load_inline_boundary_score_payloads",
    "_score_json_file_base",
    "_select_inline_boundary_record",
    "_inline_boundary_source_path",
    "_inline_boundary_report_target_source",
    "_write_inline_boundary_probe_files",
    "_inline_boundary_score_source_hint",
]


# ── Mover helpers ─────────────────────────────────────────────────────────────


def _signature_source_for_function(
    *,
    function: str,
    source_file: Path | None,
    melee_root: Path,
) -> tuple[Path | None, str | None, str | None]:
    from src.cli.debug import _resolve_existing_cli_file, _find_unit_for_function  # noqa: PLC0415

    if source_file is not None:
        resolved = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
        return resolved, resolved.read_text(), None
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        return None, None, f"function not found in report.json: {function}"
    path = melee_root / "src" / f"{unit}.c"
    if not path.exists():
        return path, None, f"source file not found: {path}"
    return path, path.read_text(), None


def _signature_payload_match_percent(payload: Mapping[str, Any]) -> float | None:
    for key in ("fuzzy_match_percent", "match_percent", "percent"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _run_signature_candidate_checkdiff(
    *,
    function: str,
    candidate_source: str,
    source_path: Path,
    unit: str,
    melee_root: Path,
    timeout: float,
    rebuild_source: bool = False,
) -> dict:
    from src.cli.debug import _run_signature_candidate_checkdiff_many  # noqa: PLC0415

    return _run_signature_candidate_checkdiff_many(
        functions=[function],
        candidate_source=candidate_source,
        source_path=source_path,
        unit=unit,
        melee_root=melee_root,
        timeout=timeout,
        rebuild_source=rebuild_source,
    )[function]


def _signature_report_payload(
    report,
    *,
    checkdiff_source: str,
    source_path: Path | None,
    source_error: str | None,
    validation_enabled: bool,
) -> dict[str, Any]:
    payload = dataclasses.asdict(report)
    payload["checkdiff_source"] = checkdiff_source
    payload["source"] = str(source_path) if source_path is not None else None
    payload["source_error"] = source_error
    payload["validation_enabled"] = validation_enabled
    return payload


def _print_signature_report(
    report,
    *,
    checkdiff_source: str,
    source_path: Path | None,
    source_error: str | None,
    validation_enabled: bool,
) -> None:
    print(f"Signature suggestions for {report.function}")
    print(f"checkdiff: {checkdiff_source}")
    if source_path is not None:
        print(f"source: {source_path}")
    elif source_error:
        print(f"source: unavailable ({source_error})")
    summary = report.summary or {}
    stop = summary.get("stop_condition") or {}
    if stop:
        print(
            f"stop: {stop.get('kind')} "
            f"(patches={summary.get('patch_candidate_count', 0)}, "
            f"rebucketed={summary.get('rebucketed_audit_only_count', 0)}, "
            f"unrebucketed={summary.get('audit_only_unrebucketed', 0)})"
        )
    if not report.findings:
        print("No signature/type call-prep findings.")
        return
    for finding in report.findings:
        line = finding.source_line if finding.source_line is not None else "?"
        arg = finding.arg_index if finding.arg_index is not None else "?"
        print(
            f"- {finding.kind}: {finding.call_target or '?'} "
            f"arg {arg} at line {line}"
        )
        expected_reg = finding.expected.get("register")
        current_reg = finding.current.get("register")
        print(
            f"  expected {expected_reg or '?'} "
            f"{finding.expected.get('bank') or ''}; "
            f"current {current_reg or '?'} {finding.current.get('bank') or ''}"
        )
        for action in finding.actions:
            print(f"  action: {action.kind} ({action.confidence})")
            if action.patch is not None:
                print(
                    f"    patch: {action.patch.old!r} -> {action.patch.new!r}"
                )
            candidate = getattr(action, "candidate", None)
            source_variant = getattr(action, "source_variant", None)
            if source_variant is not None:
                variant_candidate = source_variant.candidate or candidate or {}
                print(
                    "    candidate: "
                    f"{variant_candidate.get('kind') or action.kind} "
                    f"{variant_candidate.get('helper') or '?'} "
                    f"({source_variant.label}, "
                    f"{variant_candidate.get('patch_status') or 'diagnostic'})"
                )
                print(
                    "      "
                    f"variant_id={source_variant.variant_id}, "
                    f"patches={len(source_variant.patches)}"
                )
            elif candidate:
                print(
                    "    candidate: "
                    f"{candidate.get('kind')} "
                    f"{candidate.get('current_type') or '?'} -> "
                    f"{candidate.get('proposed_type') or '?'} "
                    f"({candidate.get('blast_radius') or '?'}, "
                    f"{candidate.get('patch_status') or 'diagnostic'})"
                )
                if candidate.get("candidate_source") or candidate.get("expected_bank"):
                    print(
                        "      "
                        f"source={candidate.get('candidate_source') or '?'}, "
                        f"expected_bank={candidate.get('expected_bank') or '?'}, "
                        f"current_bank={candidate.get('current_bank') or '?'}"
                    )
            if action.rebucket:
                print(
                    f"    rebucket: {action.rebucket['reason']} -> "
                    f"{action.rebucket['work_bucket']}/"
                    f"{action.rebucket['subcategory']}"
                )
                print(f"      {action.rebucket['explanation']}")
                context = action.rebucket.get("prototype_context")
                if isinstance(context, dict):
                    print(
                        "      prototype: "
                        f"{context.get('current_type') or '?'} -> "
                        f"{context.get('proposed_type') or 'no-change'} "
                        f"({context.get('current_bank') or '?'} -> "
                        f"{context.get('expected_bank') or '?'})"
                    )
            if action.validation is not None:
                status = action.validation.get("status")
                delta = action.validation.get("delta_match_percent")
                primary = action.validation.get("primary")
                if isinstance(primary, dict):
                    primary_delta = primary.get("delta_match_percent")
                    siblings = action.validation.get("siblings") or []
                    sibling_summary = (
                        f"{len(siblings)} scored" if siblings else "none"
                    )
                    if primary_delta is None:
                        print(
                            f"    validation: {status}, "
                            f"retained={action.validation.get('retained')}, "
                            f"siblings {sibling_summary}"
                        )
                    else:
                        print(
                            f"    validation: {status}, "
                            f"primary delta {primary_delta:+.2f}%, "
                            f"retained={action.validation.get('retained')}, "
                            f"siblings {sibling_summary}"
                        )
                elif delta is None:
                    print(f"    validation: {status}")
                else:
                    print(f"    validation: {status}, delta {delta:+.2f}%")
    if validation_enabled:
        print("Validation used temp objects and restored the build object after scoring.")


def _signature_sibling_baselines(
    *,
    sibling_functions: list[str],
    melee_root: Path,
    checkdiff_timeout: float,
) -> dict[str, float | None]:
    from src.cli.debug import _find_unit_for_function, _read_signature_checkdiff_payload  # noqa: PLC0415

    baselines: dict[str, float | None] = {}
    for sibling in sibling_functions:
        if _find_unit_for_function(sibling, melee_root) is None:
            continue
        try:
            payload, _ = _read_signature_checkdiff_payload(
                function=sibling,
                melee_root=melee_root,
                checkdiff_json=None,
                checkdiff_timeout=checkdiff_timeout,
                no_build=True,
            )
        except typer.Exit:
            continue
        baselines[sibling] = _signature_payload_match_percent(payload)
    return baselines


def _signature_scoreable_sibling_functions(
    sibling_functions: list[str],
    sibling_baselines: dict[str, float | None],
) -> list[str]:
    return [sibling for sibling in sibling_functions if sibling in sibling_baselines]


def _emit_suggest_schedule_source(
    *,
    function: str,
    force_schedule: str,
    against: Path,
    pcdump: Path | None,
    source_file: Path | None,
    json_out: bool,
) -> None:
    from src.cli.debug import DEFAULT_MELEE_ROOT, _validate_force_schedule, _resolve_pcdump_path, _find_unit_for_function  # noqa: PLC0415
    from ...mwcc_debug.suggest_schedule import (
        render_json,
        render_text,
        run,
    )

    force_schedule = _validate_force_schedule(force_schedule)
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    if not against.is_file():
        raise typer.BadParameter(f"forced-path pcdump not found: {against}")
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            candidate = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(candidate)

    report = run(
        pcdump_path.read_text(),
        against.read_text(),
        function=function,
        force_schedule=force_schedule,
        source_text=source_text,
        source_file=source_label,
    )
    print(render_json(report) if json_out else render_text(report))


def _attach_expression_source_generation_validation_hints(
    generation: dict[str, Any],
    *,
    function: str,
    cflags_from: str | None,
    source_path: Path,
    melee_root: Path,
) -> None:
    repo = melee_root.resolve()
    source_cflags = cflags_from or _repo_relative_for_hint(source_path, repo)
    for candidate in generation.get("candidates", ()):
        if not isinstance(candidate, dict):
            continue
        raw_path = candidate.get("path")
        if not raw_path:
            continue
        candidate_path = Path(str(raw_path)).expanduser()
        candidate_rel = _repo_relative_for_hint(candidate_path, repo)
        if candidate_rel is None:
            candidate["score_source"] = {
                "status": "path-outside-repo",
                "reason": (
                    "debug target score-source requires generated .c files "
                    "under the melee repo; use --write-probes inside the repo "
                    "or copy this candidate there before scoring"
                ),
            }
            continue
        command = [
            "melee-agent",
            "debug",
            "target",
            "score-source",
            candidate_rel,
            "-f",
            function,
        ]
        if source_cflags:
            command.extend(["--cflags-from", source_cflags])
        command.extend([
            "--target",
            "<target.json>",
            "--expression-baseline",
            "<baseline.pcdump.txt>",
            "--expression-source",
            "<baseline-source.c>",
            "--expression-reg-class",
            "fpr",
            "--checkdiff-guard",
            "--json",
        ])
        candidate["score_source"] = {
            "status": "ready",
            "path": candidate_rel,
            "function": function,
            "cflags_from": source_cflags,
            "command": " ".join(shlex.quote(part) for part in command),
        }


def _repo_relative_for_hint(path: Path, repo: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(repo)).replace("\\", "/")
    except (OSError, ValueError):
        return None


def _load_protected_reconcile_candidate_scores(
    candidate_score_json: str | None,
) -> list[Mapping[str, Any]]:
    from src.cli.debug import DEFAULT_MELEE_ROOT, _resolve_existing_cli_file  # noqa: PLC0415

    if candidate_score_json is None:
        return []
    payloads: list[Mapping[str, Any]] = []
    for token in candidate_score_json.split(","):
        token = token.strip()
        if not token:
            continue
        path = _resolve_existing_cli_file(
            Path(token),
            melee_root=DEFAULT_MELEE_ROOT,
            label="candidate score JSON",
        )
        try:
            raw_payload = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                f"invalid candidate score JSON {path}: {exc}"
            ) from exc
        if (
            isinstance(raw_payload, Mapping)
            and isinstance(raw_payload.get("candidates"), list)
        ):
            payloads.append(raw_payload)
            continue
        if not isinstance(raw_payload, Mapping):
            raise typer.BadParameter(
                f"candidate score JSON must contain an object: {path}"
            )
        payload = dict(raw_payload)
        if not any(key in payload for key in ("candidate_id", "id", "probe_id")):
            payload["candidate_id"] = _score_json_file_base(path)
        payload["score_json"] = str(path)
        payloads.append(payload)
    return payloads


def _load_protected_reconcile_source_hunks(path: Path | None) -> list[Mapping[str, Any]]:
    from src.cli.debug import DEFAULT_MELEE_ROOT, _resolve_existing_cli_file  # noqa: PLC0415

    if path is None:
        return []
    resolved = _resolve_existing_cli_file(
        path,
        melee_root=DEFAULT_MELEE_ROOT,
        label="source hunks JSON",
    )
    try:
        raw_payload = json.loads(resolved.read_text())
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid source hunks JSON {resolved}: {exc}") from exc

    source_hunks = _source_hunks_from_payload(raw_payload)
    if source_hunks is None:
        raise typer.BadParameter(
            "source hunks JSON must be a hunk list or an object containing "
            "source_hunks/continuation.source_hunks"
        )
    return source_hunks


def _source_hunks_from_payload(raw_payload: Any) -> list[Mapping[str, Any]] | None:
    if _mapping_sequence(raw_payload):
        return [dict(item) for item in raw_payload]
    if not isinstance(raw_payload, Mapping):
        return None
    for key in ("source_hunks", "hunks"):
        value = raw_payload.get(key)
        if _mapping_sequence(value):
            return [dict(item) for item in value]
    continuation = raw_payload.get("continuation")
    if isinstance(continuation, Mapping):
        for key in ("source_hunks", "hunks"):
            value = continuation.get(key)
            if _mapping_sequence(value):
                return [dict(item) for item in value]
    return None


def _mapping_sequence(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and all(isinstance(item, Mapping) for item in value)
    )


def _load_inline_boundary_score_payloads(
    paths: list[str] | None,
) -> list[dict[str, Any]]:
    from src.cli.debug import _resolve_existing_cli_file  # noqa: PLC0415

    payloads: list[dict[str, Any]] = []
    for raw_path in paths or []:
        path = _resolve_existing_cli_file(
            Path(raw_path),
            melee_root=DEFAULT_MELEE_ROOT,
            label="score-source JSON",
        )
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                f"invalid score-source JSON {path}: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise typer.BadParameter(f"score-source JSON must be an object: {path}")
        row = dict(payload)
        if _looks_like_inline_boundary_checkdiff(row):
            row.setdefault("checkdiff_json", str(path))
        row.setdefault("score_json", str(path))
        row.setdefault("candidate_id", _score_json_file_base(path))
        payloads.append(row)
    return payloads


def _score_json_file_base(path: Path) -> str:
    base = _candidate_id_from_evidence_filename(path) or path.stem
    for suffix in (".checkdiff", "_checkdiff", "_score"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _looks_like_inline_boundary_checkdiff(row: Mapping[str, Any]) -> bool:
    return any(key in row for key in ("match", "fuzzy_match_percent", "classification"))


def _select_inline_boundary_record(
    report: Mapping[str, Any],
    *,
    function: str | None,
    inline_name: str | None,
) -> dict[str, Any]:
    records = report.get("records")
    if not isinstance(records, list):
        raise typer.BadParameter("inline leverage JSON is missing records[]")
    matches: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, Mapping):
            continue
        if item.get("verdict") != "lever":
            if not _is_void_duplication_continuation_seed(item):
                continue
        if item.get("shape_body") != "multi_statement":
            continue
        is_scalar_splice = (
            item.get("expansion_form") == "scalar_assignment_splice"
            and item.get("shape_return") == "scalar"
        )
        is_void_splice = (
            item.get("expansion_form") == "statement_splice"
            and item.get("shape_return") == "void"
        )
        is_void_duplication_seed = _is_void_duplication_continuation_seed(item)
        if not is_scalar_splice and not is_void_splice and not is_void_duplication_seed:
            continue
        if function and item.get("function") != function:
            continue
        if inline_name and item.get("inline_name") != inline_name:
            continue
        record = dict(item)
        if is_void_duplication_seed:
            record.setdefault("original_verdict", record.get("verdict"))
            record.setdefault("original_error", record.get("error"))
            record["verdict"] = "lever"
            record["expansion_form"] = "statement_splice"
            record["continuation_seed"] = "void_nontrivial_argument_duplication"
        matches.append(record)
    if not matches:
        raise typer.BadParameter(
            "no strict scalar-assignment-splice or void statement-splice inline "
            "leverage record matched"
        )
    if len(matches) != 1:
        raise typer.BadParameter(
            "multiple strict inline leverage records matched; pass "
            "--function and --inline-name"
        )
    return matches[0]


def _is_void_duplication_continuation_seed(item: Mapping[str, Any]) -> bool:
    return (
        item.get("verdict") == "unsupported"
        and item.get("shape_body") == "multi_statement"
        and item.get("shape_return") == "void"
        and item.get("error") == "nontrivial argument would be duplicated"
    )


def _inline_boundary_source_path(
    *,
    source_file: Path | None,
    report: Mapping[str, Any],
    record: Mapping[str, Any],
) -> Path:
    from src.cli.debug import _resolve_existing_cli_file  # noqa: PLC0415

    if source_file is not None:
        return _resolve_existing_cli_file(
            source_file,
            melee_root=DEFAULT_MELEE_ROOT,
            label="source file",
        )
    for value in (
        record.get("unit"),
        record.get("source"),
        _inline_boundary_report_target_source(report, record.get("function")),
    ):
        if isinstance(value, str) and value:
            return _resolve_existing_cli_file(
                Path(value),
                melee_root=DEFAULT_MELEE_ROOT,
                label="source file",
            )
    raise typer.BadParameter(
        "could not infer source file; pass --source-file"
    )


def _inline_boundary_report_target_source(
    report: Mapping[str, Any],
    function: Any,
) -> str | None:
    targets = report.get("targets")
    if not isinstance(targets, list):
        return None
    for item in targets:
        if not isinstance(item, Mapping):
            continue
        if function and item.get("function") != function:
            continue
        value = item.get("source")
        if isinstance(value, str) and value:
            return value
    return None


def _write_inline_boundary_probe_files(
    generation: dict[str, Any],
    *,
    output_dir: Path,
    source_path: Path,
    cflags_from: str | None,
    target_spec: Path | None,
    expression_baseline: Path | None,
    expression_source: str | None,
) -> None:
    from ...inline_leverage.boundary_variants import (
        inline_boundary_candidate_file_stem,
    )

    output_dir = output_dir.expanduser()
    if not output_dir.is_absolute():
        output_dir = DEFAULT_MELEE_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    target_map = generation.get("target_map")
    generated_target_spec = target_spec
    if generated_target_spec is None and isinstance(target_map, Mapping) and target_map:
        generated_target_spec = output_dir / "inline_boundary_target.json"
        generated_target_spec.write_text(
            json.dumps({
                "function": generation.get("function"),
                "virtuals": dict(target_map),
            }, indent=2)
            + "\n",
            encoding="utf-8",
        )
    for candidate in generation.get("candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        path = output_dir / f"{inline_boundary_candidate_file_stem(candidate)}.c"
        path.write_text(str(candidate.get("source_text") or ""), encoding="utf-8")
        candidate["path"] = str(path)
        candidate["score_source"] = _inline_boundary_score_source_hint(
            candidate_path=path,
            function=str(generation.get("source_function") or generation.get("function")),
            source_path=source_path,
            cflags_from=cflags_from,
            target_spec=generated_target_spec,
            expression_baseline=expression_baseline,
            expression_source=expression_source,
        )
    generation["write_probes"] = str(output_dir)
    if generated_target_spec is not None:
        generation["target_spec"] = str(generated_target_spec)


def _inline_boundary_score_source_hint(
    *,
    candidate_path: Path,
    function: str,
    source_path: Path,
    cflags_from: str | None,
    target_spec: Path | None,
    expression_baseline: Path | None,
    expression_source: str | None,
) -> dict[str, Any]:
    repo = DEFAULT_MELEE_ROOT.resolve()
    candidate_arg = _repo_relative_for_hint(candidate_path, repo) or str(candidate_path)
    cflags_arg = cflags_from or _repo_relative_for_hint(source_path, repo)
    command = [
        "melee-agent",
        "debug",
        "target",
        "score-source",
        candidate_arg,
        "--function",
        function,
    ]
    if cflags_arg:
        command.extend(["--cflags-from", cflags_arg])
    command.extend(["--target", str(target_spec) if target_spec else "<target.json>"])
    if expression_baseline is not None:
        command.extend(["--expression-baseline", str(expression_baseline)])
    if expression_source is not None:
        command.extend(["--expression-source", expression_source])
    command.extend([
        "--expression-reg-class",
        "gpr",
        "--full-unit-source",
        "--checkdiff-guard",
        "--retain-pcdump",
        "--json",
    ])
    return {
        "status": "ready" if target_spec is not None else "needs-target-spec",
        "path": candidate_arg,
        "function": function,
        "cflags_from": cflags_arg,
        "target_spec": str(target_spec) if target_spec else None,
        "command": " ".join(shlex.quote(part) for part in command),
    }


# ── Suggest command handlers ───────────────────────────────────────────────────


@suggest_app.command(name="signatures")
def suggest_signatures_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to inspect"),
    ],
    checkdiff_json: Annotated[
        Optional[Path],
        typer.Option(
            "--checkdiff-json",
            help=(
                "Existing tools/checkdiff.py --format json payload. If omitted, "
                "checkdiff is run for the function."
            ),
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file to audit. Defaults to the repo source for the function.",
        ),
    ] = None,
    build: Annotated[
        bool,
        typer.Option(
            "--build",
            help="Allow the initial checkdiff run to rebuild before auditing.",
        ),
    ] = False,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate",
            help=(
                "Compile each safe patch candidate to a temp object, run "
                "checkdiff --no-build under the repo lock, and attach scores."
            ),
        ),
    ] = False,
    sibling_function: Annotated[
        Optional[list[str]],
        typer.Option(
            "--sibling-function",
            help=(
                "Additional sibling function to score against validated "
                "source variants. Can be passed multiple times."
            ),
        ),
    ] = None,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds for checkdiff and validation compile steps.",
        ),
    ] = 60.0,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Suggest source levers for checkdiff call-prep signature mismatches."""
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _read_signature_checkdiff_payload,
        _signature_sibling_functions,
        _run_signature_candidate_checkdiff_many,
        _find_unit_for_function,
    )

    melee_root = DEFAULT_MELEE_ROOT
    source_path, source_text, source_error = _signature_source_for_function(
        function=function,
        source_file=source_file,
        melee_root=melee_root,
    )
    checkdiff_payload, checkdiff_source = _read_signature_checkdiff_payload(
        function=function,
        melee_root=melee_root,
        checkdiff_json=checkdiff_json,
        checkdiff_timeout=checkdiff_timeout,
        no_build=not build,
    )
    report = audit_signature_call_type(
        checkdiff_payload,
        source_text or "",
        function,
        source_file=str(source_path) if source_path is not None else None,
    )
    if validate:
        unit = _find_unit_for_function(function, melee_root)
        if source_text is None or source_path is None:
            typer.echo(
                f"--validate requires source text: {source_error or 'unavailable'}",
                err=True,
            )
            raise typer.Exit(2)
        if unit is None:
            typer.echo(
                f"--validate requires report.json unit for {function}",
                err=True,
            )
            raise typer.Exit(2)

        def run_candidate(candidate_source: str) -> dict:
            return _run_signature_candidate_checkdiff(
                function=function,
                candidate_source=candidate_source,
                source_path=source_path,
                unit=unit,
                melee_root=melee_root,
                timeout=checkdiff_timeout,
                rebuild_source=build,
            )

        sibling_functions = _signature_sibling_functions(
            function=function,
            source_text=source_text,
            explicit_siblings=list(sibling_function or []),
            report=report,
        )
        sibling_baselines = _signature_sibling_baselines(
            sibling_functions=sibling_functions,
            melee_root=melee_root,
            checkdiff_timeout=checkdiff_timeout,
        )
        sibling_functions = _signature_scoreable_sibling_functions(
            sibling_functions,
            sibling_baselines,
        )

        def run_candidate_multi(
            candidate_source: str,
            functions: list[str],
        ) -> dict[str, dict]:
            return _run_signature_candidate_checkdiff_many(
                functions=functions,
                candidate_source=candidate_source,
                source_path=source_path,
                unit=unit,
                melee_root=melee_root,
                timeout=checkdiff_timeout,
                rebuild_source=build,
            )

        validate_signature_patches(
            report,
            source_text,
            run_candidate,
            baseline_match_percent=_signature_payload_match_percent(
                checkdiff_payload
            ),
            primary_function=function,
            sibling_functions=sibling_functions,
            sibling_baseline_match_percent=sibling_baselines,
            run_candidate_multi=run_candidate_multi,
        )

    if json_out:
        print(json.dumps(
            _signature_report_payload(
                report,
                checkdiff_source=checkdiff_source,
                source_path=source_path,
                source_error=source_error,
                validation_enabled=validate,
            ),
            indent=2,
        ))
        return
    _print_signature_report(
        report,
        checkdiff_source=checkdiff_source,
        source_path=source_path,
        source_error=source_error,
        validation_enabled=validate,
    )


@suggest_app.command(name="frame")
def suggest_frame_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to inspect"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function.",
        ),
    ] = None,
    expected_asm: Annotated[
        Optional[Path],
        typer.Option(
            "--expected-asm",
            help="Expected target asm. Omit to extract via `extract get --full`.",
        ),
    ] = None,
    no_expected: Annotated[
        bool,
        typer.Option(
            "--no-expected",
            help="Do not compare against target asm; emit generic frame levers.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Suggest source/probe levers for stack-frame/local-area residuals."""
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _resolve_pcdump_path,
        _resolve_frame_function_names,
        _abort_frame_function_not_in_dump,
        _read_frame_reservation_expected_asm,
        _read_frame_reservation_current_asm,
        _pcdump_has_symbolic_stack_homes,
        _frame_source_context,
        _attach_frame_function_aliases,
        _find_unit_for_function,
        _frame_source_suggestions_from_report,
        _print_frame_suggestions,
    )

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    pcdump_text = pcdump_path.read_text()
    names = _resolve_frame_function_names(function, pcdump_text, melee_root)
    if names is None:
        _abort_frame_function_not_in_dump(function, pcdump_text)
    expected_text = _read_frame_reservation_expected_asm(
        names.report_function,
        expected_asm=expected_asm,
        no_expected=no_expected,
        melee_root=melee_root,
    )
    current_text = (
        _read_frame_reservation_current_asm(
            names.report_function,
            melee_root=melee_root,
        )
        if _pcdump_has_symbolic_stack_homes(pcdump_text)
        else None
    )
    source_context = _frame_source_context(
        names.aliases,
        melee_root=melee_root,
    )
    try:
        report = analyze_frame_reservations(
            pcdump_text,
            names.pcdump_function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
            display_function=function,
            **source_context,
        )
    except ValueError as exc:
        if "not found in pcdump" in str(exc):
            _abort_frame_function_not_in_dump(function, pcdump_text)
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    _attach_frame_function_aliases(report, names)
    unit = _find_unit_for_function(names.report_function, melee_root)
    suggestions = _frame_source_suggestions_from_report(report, unit=unit)
    if json_out:
        print(json.dumps({
            "function": function,
            "frame": report,
            "suggestions": suggestions,
        }, indent=2))
        return
    _print_frame_suggestions(report, suggestions)


@suggest_app.command(name="casts")
def suggest_casts(
    function: Annotated[
        str,
        typer.Argument(help="Function name to audit"),
    ],
    asm: Annotated[
        bool,
        typer.Option(
            "--asm",
            help="Cross-reference each call-site with the expected ASM "
                 "in build/GALE01/asm/. Detects integer-loaded args that "
                 "the source code wraps in (f32) (and vice versa).",
        ),
    ] = False,
    signedness: Annotated[
        bool,
        typer.Option(
            "--signedness",
            help="Scan the current-vs-expected ASM diff (via checkdiff) "
                 "for compare-opcode signedness mismatches: cmplwi (unsigned) "
                 "where expected has cmpwi (signed), or vice versa. "
                 "Requires the TU's .o to be built (`ninja <unit>.o`). "
                 "This is separate from the source-level cast audit.",
        ),
    ] = False,
    severity: Annotated[
        str,
        typer.Option(
            "--severity",
            help="Filter by severity: high/medium/low/all (default: medium+).",
        ),
    ] = "medium",
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit warnings as JSON."),
    ] = False,
) -> None:
    """Tier 7d: static lint for cast-mismatch and signedness patterns.

    Surfaces explicit casts on function arguments that are likely wrong —
    especially the `(f32)` cast on integer values that the matching agent
    identified as the `drop-variadic-cast` pattern in their session
    findings.

    Three-tier classification for cast warnings:
      HIGH — cast on a value the function declares as integer
      MEDIUM — cast on a value that LOOKS integer but can't be proven
      LOW — every other explicit cast (for general audit)

    With `--asm`, also cross-references the call site against
    build/GALE01/asm/<unit>.s to identify args loaded as integers when
    the source casts to float (and vice versa).

    With `--signedness`, scans the current-vs-expected ASM diff for
    compare-opcode mismatches: cmplwi (unsigned) where expected has cmpwi
    (signed), or vice versa. Useful when `u8 limit` → `int limit` gives
    a match improvement that the source-level cast audit misses.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT, _find_unit_for_function, _checkdiff_env_without_fingerprint  # noqa: PLC0415

    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    text = target_path.read_text()
    warnings = audit_function_casts(text, function)

    # Severity filter
    sev_order = {"high": 0, "medium": 1, "low": 2}
    min_level = sev_order.get(severity, 1) if severity != "all" else 99
    if severity != "all":
        warnings = [w for w in warnings if sev_order.get(w.severity, 99) <= min_level]

    asm_contexts: dict = {}
    if asm:
        asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
        if not asm_path.exists():
            typer.echo(
                f"asm file not found: {asm_path}\n"
                f"(try `ninja {asm_path.relative_to(melee_root)}`)",
                err=True,
            )
        else:
            span = find_source_function(text, function)
            if span:
                fn_text = text[span.sig_start : span.full_end]
                sites = find_call_sites(fn_text)
                contexts = crossref_with_asm(sites, asm_path, function)
                # Index by (call_target, source_line) for warning correlation
                for ctx in contexts:
                    key = (ctx.source_site.call_target, ctx.source_site.line)
                    asm_contexts[key] = ctx

    # Signedness check: diff current compiled vs expected, look for
    # cmplwi/cmpwi (unsigned/signed) opcode disagreements.
    sign_mismatches = []
    if signedness:
        try:
            proc = subprocess.run(
                ["python", "tools/checkdiff.py", function,
                 "--format", "json", "--no-build"],
                cwd=melee_root, capture_output=True, text=True, timeout=60,
                env=_checkdiff_env_without_fingerprint(),
            )
            if proc.returncode in (0, 1) and proc.stdout:
                diff_data = json.loads(proc.stdout)
                diff_lines = diff_data.get("diff", [])
                if diff_lines:
                    sign_mismatches = detect_signedness_mismatches(diff_lines)
        except (FileNotFoundError, subprocess.TimeoutExpired,
                json.JSONDecodeError):
            typer.echo(
                "signedness check: checkdiff failed or produced no output",
                err=True,
            )

    if json_out:
        data = []
        for w in warnings:
            entry = {
                "kind": "cast",
                "line": w.line,
                "call_target": w.call_target,
                "arg_index": w.arg_index,
                "cast_type": w.cast_type,
                "inner_expr": w.inner_expr,
                "severity": w.severity,
                "reason": w.reason,
            }
            data.append(entry)
        sign_data = []
        for sm in sign_mismatches:
            sign_data.append({
                "kind": "signedness",
                "current_opcode": sm.current_opcode,
                "expected_opcode": sm.expected_opcode,
                "current_line": sm.current_line,
                "expected_line": sm.expected_line,
                "mismatch_kind": sm.kind,
                "suggestion": sm.suggestion,
            })
        print(json.dumps({
            "function": function,
            "warnings": data,
            "signedness_mismatches": sign_data,
        }, indent=2))
        return

    print(f"Function: {function}")
    print(f"Source:   {target_path}")
    if not warnings:
        print(
            f"No casts at severity≥{severity}. "
            f"(Re-run with --severity all to see all explicit casts.)"
        )
    else:
        print(f"Cast warnings ({len(warnings)} at severity≥{severity}):")
        print()
        for w in warnings:
            marker = {"high": "!!", "medium": "!", "low": "·"}.get(w.severity, " ")
            print(f"  {marker} {target_path}:{w.line}  ({w.severity})")
            print(f"     ({w.cast_type}) {w.inner_expr}  →  "
                  f"{w.call_target}(... arg{w.arg_index} ...)")
            print(f"     {w.reason}")
            if asm:
                key = (w.call_target, w.line - (text[:0].count('\n')))
                # Find any matching context by call target + line proximity
                for (target_name, src_line), ctx in asm_contexts.items():
                    if target_name == w.call_target and ctx.asm_line_idx is not None:
                        kinds = ctx.arg_register_kinds
                        if kinds:
                            kind_str = ", ".join(f"{r}={k}"
                                                 for r, k in sorted(kinds.items()))
                            print(f"     ASM arg loads: {kind_str}")
                        break
            print()

    if sign_mismatches:
        print(f"Signedness mismatches ({len(sign_mismatches)} compare-opcode disagreements):")
        print()
        for sm in sign_mismatches:
            print(f"  !! signedness-type-mismatch")
            print(f"     current:  {sm.current_line}")
            print(f"     expected: {sm.expected_line}")
            print(f"     {sm.suggestion}")
            print()
    elif signedness:
        print("No signedness mismatches detected.")


@suggest_app.command(name="control-flow-shape")
def suggest_control_flow_shape(
    function: Annotated[
        str,
        typer.Option(
            "--function",
            "-f",
            help="Function to analyze.",
        ),
    ],
    checkdiff_json: Annotated[
        Path | None,
        typer.Option(
            "--checkdiff-json",
            help="Existing tools/checkdiff.py --format json payload.",
        ),
    ] = None,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds for live checkdiff.",
        ),
    ] = 60.0,
    no_build: Annotated[
        bool,
        typer.Option(
            "--no-build",
            help="Pass --no-build to live checkdiff for a fast stale-object read.",
        ),
    ] = False,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "Source file used to preflight whether suggested generated "
                "operators can materialize probes."
            ),
        ),
    ] = None,
    top: Annotated[
        int,
        typer.Option("--top", help="Maximum number of ranked suggestions."),
    ] = 5,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit suggestions as JSON."),
    ] = False,
) -> None:
    """Suggest source-level control-flow shape transforms from ASM diff JSON."""
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _read_control_flow_shape_checkdiff_payload,
        _checkdiff_asm_lines,
        _control_flow_prototype_context,
        _resolve_existing_cli_file,
        _find_unit_for_function,
    )
    from ...mwcc_debug.suggest_control_flow_shape import (
        annotate_source_materialization,
        analyze_control_flow_shape,
        render_json,
        render_text,
    )

    payload, checkdiff_source = _read_control_flow_shape_checkdiff_payload(
        function=function,
        melee_root=DEFAULT_MELEE_ROOT,
        checkdiff_json=checkdiff_json,
        checkdiff_timeout=checkdiff_timeout,
        no_build=no_build,
    )

    payload_function = payload.get("function")
    if payload_function is not None and not isinstance(payload_function, str):
        typer.echo("checkdiff JSON function field was not a string", err=True)
        raise typer.Exit(2)
    if isinstance(payload_function, str) and payload_function != function:
        typer.echo(
            f"checkdiff JSON function {payload_function} did not match {function}",
            err=True,
        )
        raise typer.Exit(2)

    target_asm = _checkdiff_asm_lines(payload, "target_asm")
    current_asm = _checkdiff_asm_lines(payload, "current_asm")
    classification_raw = payload.get("classification")
    classification = (
        classification_raw if isinstance(classification_raw, dict) else None
    )

    report = analyze_control_flow_shape(
        function=function,
        target_asm=target_asm,
        current_asm=current_asm,
        classification=classification,
        top=top,
    )
    source_preflight: dict[str, Any]
    resolved_source: Path | None = None
    source_text: str | None = None
    if source_file is not None:
        resolved_source = _resolve_existing_cli_file(
            source_file,
            melee_root=DEFAULT_MELEE_ROOT,
            label="source file",
        )
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            candidate_source = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if candidate_source.exists():
                resolved_source = candidate_source
    if resolved_source is not None:
        source_text = resolved_source.read_text(encoding="utf-8", errors="replace")
        prototype_context = _control_flow_prototype_context(
            resolved_source,
            DEFAULT_MELEE_ROOT,
            source_text=source_text,
        )
        annotate_source_materialization(
            report,
            function=function,
            source_text=source_text,
            prototype_context=prototype_context,
        )
        source_preflight = {
            "status": "ran",
            "source": str(resolved_source),
            "reason": "source operators were checked against the probe generator",
        }
    else:
        source_preflight = {
            "status": "source-unavailable",
            "source": None,
            "reason": "source file could not be resolved for preflight",
        }
    report["source_preflight"] = source_preflight
    report["checkdiff_source"] = checkdiff_source
    print(render_json(report) if json_out else render_text(report))


@suggest_app.command(name="register-tiebreak")
def suggest_register_tiebreak(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    register_class: Annotated[
        str,
        typer.Option(
            "--class", help="Register class: auto (default), gpr, or fpr.",
        ),
    ] = "auto",
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit guidance as JSON."),
    ] = False,
    force_vector_timeout: Annotated[
        float,
        typer.Option(
            "--force-vector-timeout",
            help=(
                "Per-probe wall-clock timeout for the diagnostic force-vector "
                "reachability check."
            ),
        ),
    ] = 30.0,
) -> None:
    """Suggest source levers for compiler-temp register tiebreaks.

    Thin caller of `debug solve coloring` (spec §7, Q6): this routes through
    the surrogate solver instead of the old heuristic so there are not two
    diverging lever vocabularies. Use it when a register assignment is
    reachable but no source variable is bound to the target IG.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT, _run_solve_coloring, _register_tiebreak_window_order_fallback  # noqa: PLC0415
    from ...mwcc_debug import tiebreak as tb

    if register_class.lower() == "auto":
        class_ids = [0, 1]
    else:
        class_ids = [tb.parse_register_class(register_class)]

    def _empty_force_phys_target(result) -> bool:
        return (
            result.exit_code == 3
            and "empty force-phys target" in (result.reason or "")
        )

    res = None
    fallback: dict | None = None
    fallback_leads: list = []
    attempted_classes: list[int] = []
    for idx, class_id in enumerate(class_ids):
        attempted_classes.append(class_id)
        res = _run_solve_coloring(
            function=function,
            class_id=class_id,
            pcdump=None,
            max_perturb=2,
            frontier=32,
            kinds=["order"],
            experimental_kinds=[],
            catalog_dir=(DEFAULT_MELEE_ROOT / "docs" / "superpowers"
                         / "lever-catalog"),
            force_vector_timeout=force_vector_timeout,
            allow_unreachable_order=True)
        fallback = None
        if (
            res.worksheet is not None
            and not res.worksheet.candidates
            and not res.worksheet.tooling_leads
            and not res.worksheet.window_order
        ):
            fallback = _register_tiebreak_window_order_fallback(
                function=function,
                class_id=class_id,
            )
        fallback_leads = (
            fallback.get("leads", [])
            if isinstance(fallback, dict) else []
        )
        if idx == len(class_ids) - 1 or not _empty_force_phys_target(res):
            break

    assert res is not None

    if res.worksheet is not None and json_out:
        payload = json.loads(res.worksheet.to_json())
        if fallback is not None:
            payload["window_order_fallback"] = fallback
        print(json.dumps(payload, indent=2))
    elif json_out:
        payload = {
            "function": function,
            "status": "solver-abstain" if res.exit_code == 3 else "solver-no-worksheet",
            "exit_code": res.exit_code,
            "reason": res.reason,
            "requested_register_class": register_class,
            "attempted_class_ids": attempted_classes,
            "node_set_delta": res.node_set_delta,
            "solver_diagnostics": res.solver_diagnostics,
            "terminal_proof": {
                "kind": "register-tiebreak-solver-result",
                "reason": res.reason,
                "next_step": (
                    "No register-tiebreak source lever worksheet was produced. "
                    "Use debug inspect guide with an external target spec and "
                    "fresh pcdump to inspect the residual allocator evidence."
                ),
            },
        }
        print(json.dumps(payload, indent=2))
    elif res.worksheet is not None:
        ws = res.worksheet
        typer.echo(f"solve {ws.function}: class {ws.class_id} "
                   f"G1 {ws.g1_rate*100:.1f}% "
                   f"current-structure-relabel={'yes' if ws.reachable else 'no'} -> "
                   f"{len(ws.candidates)} actionable, "
                   f"{len(ws.tooling_leads)} tooling-lead(s), "
                   f"{len(ws.window_order)} window-order, "
                   f"pairs={'ran' if ws.pair_escalation.ran else 'skipped'}")
        for c in ws.candidates:
            typer.echo(f"  #{c['rank']} [{c['surrogate_confidence']}] "
                       f"{c['perturbation']['kind']} "
                       f"ig{c['perturbation']['target_ig']} -> "
                       f"{[r['lever'] for r in c['c_realizations']]}")
        if fallback_leads:
            typer.echo("  window-order fallback:")
            for lead in fallback_leads:
                where, anchor = lead["order_move"]
                prefix = "f" if ws.class_id == 1 else "r"
                typer.echo(
                    f"  - move ig{lead['target_ig']} {where} ig{anchor}: "
                    f"{prefix}{lead['predicted_reg']} -> "
                    f"{prefix}{lead['perturbed_reg']} "
                    f"(observed {prefix}{lead['observed_reg']}, "
                    f"degree {lead['degree']}, "
                    f"distance {lead['move_distance']})"
                )
    if not json_out and res.reason:
        if fallback_leads:
            typer.echo("reason: window-order fallback lead(s) found")
        else:
            typer.echo(f"reason: {res.reason}")
    raise typer.Exit(0 if fallback_leads else res.exit_code)


@suggest_app.command(name="coalesce")
def suggest_coalesce_source(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required).",
        ),
    ],
    pair: Annotated[
        Optional[str],
        typer.Option(
            "-V", "--pair",
            help="Pair mode: 'virt=root' (e.g. '53=3' or 'f46=f56'). "
                 "Mutually exclusive with --discover/--trace-copy-json.",
        ),
    ] = None,
    trace_copy_json: Annotated[
        Optional[Path],
        typer.Option(
            "--trace-copy-json",
            help=(
                "trace-copy --json report to derive pair mode as "
                "copy destination=rooted to source, preserving register class."
            ),
        ),
    ] = None,
    discover: Annotated[
        bool,
        typer.Option(
            "--discover",
            help="Discover mode: find candidate coalesces that would "
                 "shorten the longest callee-save cascade. Mutually "
                 "exclusive with --pair/--trace-copy-json.",
        ),
    ] = False,
    register_class: Annotated[
        Optional[str],
        typer.Option(
            "--class",
            help="Register class for pair/discover mode: gpr/r/0 or fpr/f/1.",
        ),
    ] = None,
    top: Annotated[
        int,
        typer.Option(
            "--top",
            help="Discover mode: max candidates (default 3). Raises "
                 "BadParameter if passed in pair mode.",
        ),
    ] = 3,
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Path to pcdump.txt. Auto-resolves from cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    include_low_confidence: Annotated[
        bool,
        typer.Option(
            "--include-low-confidence",
            help="Use low-confidence bridge bindings for source-line "
                 "annotations.",
        ),
    ] = False,
) -> None:
    """Suggest C-source patterns producing a specific coalesce, or
    discover candidate coalesces that would shorten the cascade.

    Pair mode example:
        debug suggest coalesce -f fn_802461BC -V 53=3

    Discover mode example:
        debug suggest coalesce -f fn_802461BC --discover --top 5
    """
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _resolve_pcdump_path,
        _find_unit_for_function,
        _effective_reg_class,
        _parse_virtual_pair_csv,
        _register_class_from_pair_csv,
        _load_trace_copy_repair_target,
    )
    from ...mwcc_debug.call_return_shape import (
        summarize_call_return_use_shape_trace,
    )
    from ...mwcc_debug.suggest_coalesce import render_json, render_text, run

    selected_modes = sum([
        pair is not None,
        trace_copy_json is not None,
        discover,
    ])
    if selected_modes != 1:
        raise typer.BadParameter(
            "exactly one of --pair / --trace-copy-json / --discover required"
        )
    # --top only makes sense in discover mode
    if not discover and top != 3:
        raise typer.BadParameter(
            "--top is only valid with --discover"
        )

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(
        pcdump, function, melee_root, require_fresh=True,
    )
    text = pcdump_path.read_text()

    # Load source for the bridge — CLI handles this so the orchestrator
    # stays path-free (avoids circular import on cli.debug helpers).
    source_text = ""
    unit = _find_unit_for_function(function, melee_root)
    if unit is not None:
        src_path = melee_root / "src" / f"{unit}.c"
        if src_path.exists():
            source_text = src_path.read_text()

    parsed_pair: Optional[tuple[int, int]] = None
    target_source = "--pair"
    effective_class = _effective_reg_class(register_class, default="gpr")
    trace_target = None
    if pair is not None:
        try:
            pairs = _parse_virtual_pair_csv(pair)
        except typer.BadParameter as exc:
            raise typer.BadParameter(
                f"invalid --pair {pair!r}; expected 'virt=root' "
                "(e.g. '53=3' or 'f46=f56')"
            ) from exc
        if len(pairs) != 1:
            raise typer.BadParameter(
                f"invalid --pair {pair!r}; expected one pair"
            )
        parsed_pair = pairs[0]
        inferred_class = _register_class_from_pair_csv(pair)
        effective_class = _effective_reg_class(
            register_class or inferred_class,
            default="gpr",
        )
    elif trace_copy_json is not None:
        trace_target = _load_trace_copy_repair_target(
            trace_copy_json,
            function=function,
        )
        parsed_pair = (
            trace_target["to_virtual"],
            trace_target["from_virtual"],
        )
        trace_class = trace_target.get("register_class")
        effective_class = _effective_reg_class(
            register_class or trace_class,
            default="gpr",
        )
        target_source = "trace-copy-json"

    try:
        report = run(
            function=function,
            pair=parsed_pair,
            discover=discover,
            top=top,
            include_low_confidence=include_low_confidence,
            register_class=effective_class or "gpr",
            target_source=target_source if not discover else "--discover",
            pcdump_text=text,
            source_text=source_text,
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(3)
    if trace_target is not None:
        report.source_shape_summary = summarize_call_return_use_shape_trace(
            trace_target,
            function=function,
        )

    if json_out:
        print(render_json(report))
    else:
        print(render_text(report))


@suggest_app.command(name="schedule")
def suggest_schedule_source(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    force_schedule: Annotated[
        str,
        typer.Option(
            "--force-schedule",
            help=(
                "Target scheduler swap list that produced the forced pcdump, "
                "e.g. 'lwz:0x94>0x90,lwz:0xAC>0xA8'."
            ),
        ),
    ],
    against: Annotated[
        Path,
        typer.Option(
            "--against",
            help="Forced-path pcdump.txt to compare against the real path.",
        ),
    ],
    pcdump: Annotated[
        Path | None,
        typer.Option(
            "--pcdump",
            help="Real-path pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Path | None,
        typer.Option(
            "--source-file",
            help=(
                "C source file used for advisory IR/source provenance. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Suggest C source reshapes for a divergent scheduler decision."""
    _emit_suggest_schedule_source(
        function=function,
        force_schedule=force_schedule,
        against=against,
        pcdump=pcdump,
        source_file=source_file,
        json_out=json_out,
    )


@suggest_app.command(name="expression-interferer-repair")
def suggest_expression_interferer_repair_cmd(
    candidate_json: Annotated[
        Optional[str],
        typer.Option(
            "--candidate-json",
            "--score-json",
            help=(
                "Path, comma-separated paths, or a JSON file with a candidates "
                "array. Each payload should include expression_score and "
                "optional residual facts."
            ),
        ),
    ] = None,
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function",
            "-f",
            help=(
                "Target function label for diagnostics; pair with "
                "--source-function when the C source uses a different name."
            ),
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "Current retained C source used to generate protected "
                "row_offset/product FPR repair candidates."
            ),
        ),
    ] = None,
    source_function: Annotated[
        Optional[str],
        typer.Option(
            "--source-function",
            help=(
                "Function definition to patch inside --source-file when it "
                "differs from --function."
            ),
        ),
    ] = None,
    write_probes: Annotated[
        Optional[Path],
        typer.Option(
            "--write-probes",
            "--out-dir",
            help="Directory for generated source candidate .c files.",
        ),
    ] = None,
    cflags_from: Annotated[
        Optional[str],
        typer.Option(
            "--cflags-from",
            help=(
                "Compile flags unit to use when validating generated probes "
                "with debug target score-source."
            ),
        ),
    ] = None,
    max_source_candidates: Annotated[
        int,
        typer.Option(
            "--max-source-candidates",
            help="Maximum protected row/product source candidates to emit.",
        ),
    ] = 16,
    include_source: Annotated[
        bool,
        typer.Option(
            "--include-source",
            help="Include full candidate source text in JSON when not writing probes.",
        ),
    ] = False,
    focus_name: Annotated[
        str,
        typer.Option(
            "--focus-name",
            "--focus-expression",
            help="Expression anchor that must reach its expected register.",
        ),
    ] = "col_offset_product_fpr",
    attempted_families: Annotated[
        str,
        typer.Option(
            "--attempted-families",
            help="Comma-separated transform families already exhausted.",
        ),
    ] = "",
    recombine_status: Annotated[
        str,
        typer.Option(
            "--recombine-status",
            help="Status of any manual subhunk/recombine step.",
        ),
    ] = "not-run",
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Rank expression-scored FPR repair candidates without losing protected hits."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _resolve_existing_cli_file  # noqa: PLC0415
    from ...mwcc_debug.expression_interferer_repair import (
        ExpressionRepairCandidate,
        ProtectedExpressionPolicy,
        build_terminal_summary,
        generate_source_repair_candidate_files,
        generate_source_repair_candidates,
    )

    payloads: list[Mapping[str, Any]] = []
    if candidate_json is not None:
        for token in candidate_json.split(","):
            token = token.strip()
            if not token:
                continue
            path = Path(token).expanduser()
            if not path.is_file():
                raise typer.BadParameter(f"candidate JSON not found: {path}")
            raw_payload = json.loads(path.read_text())
            if (
                isinstance(raw_payload, Mapping)
                and isinstance(raw_payload.get("candidates"), list)
            ):
                payloads.extend(
                    item for item in raw_payload["candidates"]
                    if isinstance(item, Mapping)
                )
            elif isinstance(raw_payload, Mapping):
                payloads.append(raw_payload)
            else:
                raise typer.BadParameter(f"candidate JSON must be an object: {path}")

    if not payloads and candidate_json is not None:
        raise typer.BadParameter("at least one candidate JSON payload is required")
    if not payloads and source_file is None:
        raise typer.BadParameter(
            "provide --candidate-json for ranking or --source-file for generation"
        )

    policy = ProtectedExpressionPolicy(focus_name=focus_name)
    families = [
        item.strip()
        for item in attempted_families.split(",")
        if item.strip()
    ]
    summary: dict[str, Any]
    if payloads:
        candidates = [
            ExpressionRepairCandidate.from_payload(payload)
            for payload in payloads
        ]
        summary = build_terminal_summary(
            candidates,
            policy,
            attempted_families=families,
            recombine_status=recombine_status,
        )
    else:
        summary = {
            "status": "source-generation-only",
            "kind": "expression-scored-fpr-case-a-c2-input-not-run",
            "focus": {"name": focus_name},
            "remaining_blockers": [],
            "attempted_families": families,
            "recombine_status": recombine_status,
        }

    if source_file is not None:
        source_path = _resolve_existing_cli_file(
            source_file,
            melee_root=DEFAULT_MELEE_ROOT,
            label="source file",
        )
        patch_function = source_function or function
        if not patch_function:
            raise typer.BadParameter(
                "--source-function or --function is required with --source-file"
            )
        source_text = source_path.read_text()
        if write_probes is not None:
            generation = generate_source_repair_candidate_files(
                source_text,
                function=patch_function,
                terminal_summary=summary,
                output_dir=write_probes.expanduser(),
                max_candidates=max_source_candidates,
            )
        else:
            generation = generate_source_repair_candidates(
                source_text,
                function=patch_function,
                terminal_summary=summary,
                max_candidates=max_source_candidates,
                include_source=include_source,
            )
        generation["source_file"] = str(source_path)
        generation["source_function"] = patch_function
        if function and function != patch_function:
            generation["target_function"] = function
        if write_probes is not None:
            _attach_expression_source_generation_validation_hints(
                generation,
                function=patch_function,
                cflags_from=cflags_from,
                source_path=source_path,
                melee_root=DEFAULT_MELEE_ROOT,
            )
        if generation.get("status") == "blocked" and "reason" in generation:
            generation["source_function_hint"] = (
                "If the diagnostic function label differs from the C symbol, "
                "pass --source-function with the function name present in "
                "--source-file."
            )
        summary["source_generation"] = generation

    if json_out:
        print(json.dumps(summary, indent=2))
        return

    print(f"status: {summary['status']}")
    print(f"kind: {summary['kind']}")
    focus = summary.get("focus", {})
    if isinstance(focus, Mapping):
        print(
            "focus: "
            f"{focus.get('name', focus_name)} "
            f"expected f{focus.get('expected')} "
            f"best f{focus.get('best_actual')}"
        )
    best = summary.get("best_candidate") or summary.get("winner")
    if isinstance(best, Mapping):
        print(f"best: {best.get('candidate_id')}")
    blockers = summary.get("remaining_blockers", ())
    if isinstance(blockers, list):
        for blocker in blockers:
            if not isinstance(blocker, Mapping):
                continue
            print(f"case {blocker.get('case')}: {blocker.get('reason')}")
    source_generation = summary.get("source_generation")
    if isinstance(source_generation, Mapping):
        print(f"source_generation: {source_generation.get('status')}")
        candidates_out = source_generation.get("candidates", ())
        if isinstance(candidates_out, list):
            for candidate in candidates_out:
                if not isinstance(candidate, Mapping):
                    continue
                path = candidate.get("path")
                suffix = f" -> {path}" if path else ""
                print(f"source_candidate: {candidate.get('candidate_id')}{suffix}")


@suggest_app.command(name="protected-expression-reconcile")
def suggest_protected_expression_reconcile_cmd(
    expression_source: Annotated[
        Path,
        typer.Option(
            "--expression-source",
            help="Retained C source for the protected expression frontier.",
        ),
    ],
    expression_score_json: Annotated[
        Path,
        typer.Option(
            "--expression-score-json",
            help="score-source --json payload for --expression-source.",
        ),
    ],
    structural_source: Annotated[
        Path,
        typer.Option(
            "--structural-source",
            help="Retained C source for the lower structural frontier.",
        ),
    ],
    structural_score_json: Annotated[
        Path,
        typer.Option(
            "--structural-score-json",
            help="score-source --json payload for --structural-source.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option(
            "--function",
            "-f",
            help="Target/report function name used by diagnostics.",
        ),
    ],
    source_function: Annotated[
        Optional[str],
        typer.Option(
            "--source-function",
            help=(
                "Function definition to patch in retained sources when it "
                "differs from --function."
            ),
        ),
    ] = None,
    cflags_from: Annotated[
        Optional[str],
        typer.Option(
            "--cflags-from",
            help="Compile flags unit to include in emitted score-source hints.",
        ),
    ] = None,
    write_probes: Annotated[
        Optional[Path],
        typer.Option(
            "--write-probes",
            "--out-dir",
            help="Directory for generated reconciliation probe .c files.",
        ),
    ] = None,
    max_subhunks: Annotated[
        int,
        typer.Option(
            "--max-subhunks",
            help="Maximum non-overlapping structural subhunks per candidate.",
        ),
    ] = 3,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Maximum generated reconciliation candidates.",
        ),
    ] = 64,
    max_normalized_diff_lines: Annotated[
        int,
        typer.Option(
            "--max-normalized-diff-lines",
            help="Structural improvement ceiling; improved means strictly below this.",
        ),
    ] = 30,
    candidate_score_json: Annotated[
        Optional[str],
        typer.Option(
            "--candidate-score-json",
            help=(
                "Optional path or comma-separated paths to score-source JSON "
                "payloads for generated candidates. V1 never scores itself."
            ),
        ),
    ] = None,
    source_hunks_json: Annotated[
        Optional[Path],
        typer.Option(
            "--source-hunks-json",
            help=(
                "Optional JSON hunk list, or continuation JSON containing "
                "source_hunks, for explicit protected/manual subhunk ranges."
            ),
        ),
    ] = None,
    include_source: Annotated[
        bool,
        typer.Option(
            "--include-source",
            help="Include full generated candidate source text in JSON output.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Generate/rank dual-frontier protected expression reconciliation probes."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _resolve_existing_cli_file  # noqa: PLC0415
    from ...mwcc_debug.protected_expression_reconciliation import (
        reconcile_frontiers,
        render_text,
        with_candidate_output_metadata,
    )

    expr_source_path = _resolve_existing_cli_file(
        expression_source,
        melee_root=DEFAULT_MELEE_ROOT,
        label="expression source",
    )
    expr_score_path = _resolve_existing_cli_file(
        expression_score_json,
        melee_root=DEFAULT_MELEE_ROOT,
        label="expression score JSON",
    )
    struct_source_path = _resolve_existing_cli_file(
        structural_source,
        melee_root=DEFAULT_MELEE_ROOT,
        label="structural source",
    )
    struct_score_path = _resolve_existing_cli_file(
        structural_score_json,
        melee_root=DEFAULT_MELEE_ROOT,
        label="structural score JSON",
    )
    candidate_payloads = _load_protected_reconcile_candidate_scores(
        candidate_score_json
    )
    source_hunks = _load_protected_reconcile_source_hunks(source_hunks_json)

    try:
        expression_payload = json.loads(expr_score_path.read_text())
        structural_payload = json.loads(struct_score_path.read_text())
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid score JSON: {exc}") from exc
    if not isinstance(expression_payload, Mapping):
        raise typer.BadParameter("--expression-score-json must contain an object")
    if not isinstance(structural_payload, Mapping):
        raise typer.BadParameter("--structural-score-json must contain an object")

    patch_function = source_function or function
    report = reconcile_frontiers(
        expression_source_text=expr_source_path.read_text(),
        expression_score_payload=expression_payload,
        structural_source_text=struct_source_path.read_text(),
        structural_score_payload=structural_payload,
        target_function=function,
        source_function=patch_function,
        expression_path=expr_source_path,
        structural_path=struct_source_path,
        max_subhunks=max_subhunks,
        max_candidates=max_candidates,
        max_normalized_diff_lines=max_normalized_diff_lines,
        candidate_score_payloads=candidate_payloads,
        source_hunks=source_hunks,
    )
    if write_probes is not None:
        report = with_candidate_output_metadata(
            report,
            output_dir=write_probes.expanduser(),
            function=patch_function,
            cflags_from=cflags_from,
            repo_root=DEFAULT_MELEE_ROOT,
        )
    if json_out:
        print(json.dumps(report.to_dict(include_source=include_source), indent=2))
        return
    print(render_text(report))


@suggest_app.command(name="inline-boundary-continuation")
def suggest_inline_boundary_continuation_cmd(
    inline_leverage_json: Annotated[
        Path,
        typer.Option(
            "--inline-leverage-json",
            help="debug measure inline-leverage JSON report.",
        ),
    ],
    function: Annotated[
        Optional[str],
        typer.Option("--function", "-f", help="Function/report symbol."),
    ] = None,
    inline_name: Annotated[
        Optional[str],
        typer.Option("--inline-name", help="Inline helper name."),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file to mutate; defaults from the inline leverage report.",
        ),
    ] = None,
    target: Annotated[
        Optional[list[str]],
        typer.Option(
            "--target",
            help="Target virtual mapping such as 34=27. Can be passed repeatedly.",
        ),
    ] = None,
    target_spec: Annotated[
        Optional[Path],
        typer.Option(
            "--target-spec",
            "--target-json",
            help="Existing score-source target spec. If omitted with --write-probes, one is written.",
        ),
    ] = None,
    cflags_from: Annotated[
        Optional[str],
        typer.Option(
            "--cflags-from",
            help="Compile flags unit to include in emitted score-source hints.",
        ),
    ] = None,
    expression_baseline: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-baseline",
            help="Baseline pcdump path for score-source expression anchors.",
        ),
    ] = None,
    expression_source: Annotated[
        Optional[str],
        typer.Option(
            "--expression-source",
            help="Baseline source argument for score-source expression anchors.",
        ),
    ] = None,
    write_probes: Annotated[
        Optional[Path],
        typer.Option(
            "--write-probes",
            "--out-dir",
            help="Directory for generated candidate .c files.",
        ),
    ] = None,
    score_json: Annotated[
        Optional[list[str]],
        typer.Option(
            "--score-json",
            help="Existing score-source --json payload for a generated candidate.",
        ),
    ] = None,
    max_candidates: Annotated[
        Optional[int],
        typer.Option("--max-candidates", help="Maximum generated candidates."),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON."),
    ] = False,
) -> None:
    """Generate or close strict inline-leverage helper-boundary probes."""
    from src.cli.debug import _resolve_existing_cli_file  # noqa: PLC0415
    from ...inline_leverage.boundary_variants import (
        build_terminal_proof,
        generate_boundary_candidates,
        parse_target_map,
        rank_score_payloads,
    )

    report_path = _resolve_existing_cli_file(
        inline_leverage_json,
        melee_root=DEFAULT_MELEE_ROOT,
        label="inline leverage JSON",
    )
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"invalid inline leverage JSON {report_path}: {exc}"
        ) from exc
    if not isinstance(report, Mapping):
        raise typer.BadParameter("inline leverage JSON must be an object")

    record = _select_inline_boundary_record(
        report,
        function=function,
        inline_name=inline_name,
    )
    selected_function = str(record.get("function") or function or "")
    selected_inline = str(record.get("inline_name") or inline_name or "")
    source_path = _inline_boundary_source_path(
        source_file=source_file,
        report=report,
        record=record,
    )
    target_map = parse_target_map(
        ",".join(target) if target else None,
        function=selected_function,
    )
    generation = generate_boundary_candidates(
        source_path.read_text(),
        record,
        selected_function,
        target_map=target_map,
        max_candidates=max_candidates,
    )
    generation["inline_leverage_json"] = str(report_path)
    generation["source_file"] = str(source_path)
    generation["selected_record"] = record
    generation["inline_name"] = selected_inline

    resolved_target_spec = None
    if target_spec is not None:
        resolved_target_spec = _resolve_existing_cli_file(
            target_spec,
            melee_root=DEFAULT_MELEE_ROOT,
            label="target spec",
        )
    if write_probes is not None:
        _write_inline_boundary_probe_files(
            generation,
            output_dir=write_probes,
            source_path=source_path,
            cflags_from=cflags_from,
            target_spec=resolved_target_spec,
            expression_baseline=expression_baseline,
            expression_source=expression_source,
        )

    score_payloads = _load_inline_boundary_score_payloads(score_json)
    if score_payloads:
        ranked = rank_score_payloads(
            score_payloads,
            target_map=target_map,
            candidates=[
                candidate for candidate in generation.get("candidates", [])
                if isinstance(candidate, Mapping)
            ],
        )
        generation["ranked_scores"] = ranked
        terminal = build_terminal_proof(
            function=selected_function,
            record=record,
            candidates=[
                candidate for candidate in generation.get("candidates", [])
                if isinstance(candidate, Mapping)
            ],
            score_payloads=score_payloads,
            target_map=target_map,
        )
        if terminal is not None:
            generation["status"] = "terminal"
            generation["terminal_frontier"] = terminal

    if json_out:
        print(json.dumps(generation, indent=2))
        return

    print(f"status: {generation.get('status')}")
    print(f"function: {selected_function}")
    print(f"inline: {selected_inline}")
    print(f"candidates: {len(generation.get('candidates') or [])}")
    if generation.get("terminal_frontier"):
        terminal = generation["terminal_frontier"]
        print(f"terminal: {terminal.get('terminal_reason')}")
    for candidate in generation.get("candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        suffix = f" -> {candidate.get('path')}" if candidate.get("path") else ""
        print(
            "candidate: "
            f"{candidate.get('candidate_id')} "
            f"[{candidate.get('dimension_id')}]"
            f"{suffix}"
        )


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


@suggest_app.command(name="inlines")
def suggest_inlines_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function to analyze."),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option("--pcdump", help="Optional pcdump path."),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "Retained/full-unit C source to use instead of repo source "
                "for candidate generation."
            ),
        ),
    ] = None,
    seed_source: Annotated[
        str,
        typer.Option(
            "--seed-source",
            help="Candidate seed source: all, repeated, guide, coalesce, patterns, or duplicate-block.",
        ),
    ] = "all",
    budget: Annotated[
        int,
        typer.Option("--budget", help="Maximum candidate count."),
    ] = 8,
    max_span_statements: Annotated[
        int,
        typer.Option("--max-span-statements", help="Max statements per repeated group."),
    ] = 6,
    verify: Annotated[
        bool,
        typer.Option("--verify", help="Stage and verify candidates."),
    ] = False,
    apply_best: Annotated[
        bool,
        typer.Option("--apply-best", help="Apply best verified candidate."),
    ] = False,
    target: Annotated[
        Optional[Path],
        typer.Option("--target", help="Optional target spec for allocator scoring."),
    ] = None,
    score_output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--score-output-dir",
            help="Directory for retained full-unit score-source candidates.",
        ),
    ] = None,
    expression_baseline: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-baseline",
            help="Baseline pcdump path for score-source expression anchors.",
        ),
    ] = None,
    expression_source: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-source",
            help="Baseline source path for score-source expression anchors.",
        ),
    ] = None,
    expression_reg_class: Annotated[
        str,
        typer.Option(
            "--expression-reg-class",
            help="Register class for score-source expression anchors.",
        ),
    ] = "fpr",
    threshold: Annotated[
        float,
        typer.Option("--threshold", help="Minimum checkdiff delta for --apply-best."),
    ] = 0.05,
    keep_failed: Annotated[
        bool,
        typer.Option("--keep-failed", help="Preserve failed candidate diagnostics."),
    ] = False,
    emit_patches: Annotated[
        bool,
        typer.Option(
            "--emit-patches",
            help="Include full patched_source payloads in --json output.",
        ),
    ] = False,
    emit_hunks: Annotated[
        bool,
        typer.Option(
            "--emit-hunks",
            "--emit-diffs",
            help=(
                "Include compact unified hunks in --json output without "
                "full patched_source payloads."
            ),
        ),
    ] = False,
    trace_copies: Annotated[
        bool,
        typer.Option(
            "--trace-copies",
            help=(
                "With --verify, compile candidate pcdumps and trace newly "
                "introduced `mr` copies."
            ),
        ),
    ] = False,
    explain: Annotated[
        bool,
        typer.Option(
            "--explain",
            help="Alias for --trace-copies during --verify.",
        ),
    ] = False,
    trace_timeout: Annotated[
        float,
        typer.Option(
            "--trace-timeout",
            help="Timeout in seconds for each trace-copy pcdump compile.",
        ),
    ] = 60.0,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds for each checkdiff run during --verify.",
        ),
    ] = 60.0,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON."),
    ] = False,
) -> None:
    """Suggest hidden inline/helper/source-shape candidates."""
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _checkdiff_env_without_fingerprint,
        _find_unit_for_function,
        _resolve_existing_cli_file,
    )

    if seed_source not in {"all", "repeated", "guide", "coalesce", "patterns", "duplicate-block"}:
        raise typer.BadParameter(
            "--seed-source must be one of: all, repeated, guide, coalesce, patterns, duplicate-block"
        )
    if apply_best and not verify:
        typer.echo("--apply-best requires --verify", err=True)
        raise typer.Exit(2)
    if explain:
        trace_copies = True
    if trace_copies and not verify:
        typer.echo("--trace-copies/--explain requires --verify", err=True)
        raise typer.Exit(2)
    if target is not None and not verify:
        typer.echo("--target is only used with --verify", err=True)
    if target is not None and verify and apply_best:
        typer.echo(
            "--apply-best is not supported with --target score-source verification",
            err=True,
        )
        raise typer.Exit(2)

    from ...mwcc_debug.suggest_inlines import (
        build_inline_local_write_terminal_summary,
        render_json,
        render_text,
        run,
    )

    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    source_path = melee_root / "src" / f"{unit}.c"
    source_rel = str(source_path.relative_to(melee_root))
    resolved_source_file: Path | None = None
    if source_file is not None:
        resolved_source_file = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
    input_source_path = (
        resolved_source_file if resolved_source_file is not None else source_path
    )
    source = input_source_path.read_text()
    pcdump_text = ""
    if pcdump is not None:
        pcdump_text = pcdump.read_text()

    def _run_trace_pcdump(src_rel: str) -> str:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "pcdump.txt"
            env = os.environ.copy()
            pkg_root = str(melee_root / "tools" / "melee-agent")
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = (
                pkg_root if not existing
                else f"{pkg_root}{os.pathsep}{existing}"
            )
            cmd = [
                sys.executable,
                "-m",
                "src.cli",
                "debug",
                "dump",
                "local",
                src_rel,
                "--output",
                str(out_path),
                "--no-cache-sync",
                "--function",
                function,
            ]
            proc = subprocess.run(
                cmd,
                cwd=melee_root,
                capture_output=True,
                text=True,
                timeout=trace_timeout,
                env=env,
            )
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout).strip()
                raise RuntimeError(
                    detail or f"debug dump local exited {proc.returncode}"
                )
            if not out_path.exists():
                raise RuntimeError("debug dump local produced no pcdump output")
            return out_path.read_text()

    report = run(
        source=source,
        function=function,
        pcdump_text=pcdump_text,
        seed_source=seed_source,
        budget=budget,
        max_span_statements=max_span_statements,
        verify=False,
    )
    if verify and (target is not None or score_output_dir is not None or trace_copies):
        from ...mwcc_debug.candidate_verify import (
            CheckdiffResult,
            parse_checkdiff_json,
        )
        from ...mwcc_debug.source_candidate_scoring import (
            ScoreSourceConfig,
            SourceCandidate,
            score_source_candidates,
            source_row_to_candidate_score,
        )
        from ...mwcc_debug.source_shape import rank_scores

        target_path = (
            _resolve_existing_cli_file(
                target,
                melee_root=melee_root,
                label="target spec",
            )
            if target is not None
            else None
        )
        resolved_expression_baseline = None
        baseline_arg = expression_baseline if expression_baseline is not None else pcdump
        if baseline_arg is not None:
            resolved_expression_baseline = _resolve_existing_cli_file(
                baseline_arg,
                melee_root=melee_root,
                label="expression baseline",
            )
        if expression_source is not None:
            resolved_expression_source = _resolve_existing_cli_file(
                expression_source,
                melee_root=melee_root,
                label="expression source",
            )
        elif resolved_source_file is not None:
            resolved_expression_source = resolved_source_file
        else:
            resolved_expression_source = source_rel
        if score_output_dir is None:
            output_dir = (
                melee_root
                / "build"
                / "diagnostics"
                / "suggest_inlines"
                / function
                / "score_source"
                / f"{os.getpid()}_{int(time.time() * 1000)}"
            )
        else:
            output_dir = score_output_dir
            if not output_dir.is_absolute():
                output_dir = melee_root / output_dir
        candidates = [
            SourceCandidate(
                candidate_id=patch.candidate_id,
                source_text=patch.patched_source,
                summary=patch.summary,
                metadata=patch.metadata,
                source_hunks=tuple(patch.metadata.get("source_hunks") or ()),
            )
            for patch in report.patches
        ]
        config = ScoreSourceConfig(
            repo_root=melee_root,
            function=function,
            target=target_path,
            cflags_from=source_rel,
            expression_source=resolved_expression_source,
            expression_baseline=resolved_expression_baseline,
            expression_reg_class=expression_reg_class,
            output_dir=output_dir,
            timeout=checkdiff_timeout,
            checkdiff_guard=True,
            full_unit_source=True,
        )
        score_rows = score_source_candidates(candidates, config)
        trace_sets_by_candidate_id = {}
        if trace_copies:
            from ...mwcc_debug.copy_trace import list_new_copy_lifetimes
            from ...mwcc_debug.source_shape import (
                CandidateCopyTrace,
                CandidateCopyTraceSet,
                summarize_candidate_copy_traces,
            )

            def _copy_trace_error(note: str) -> CandidateCopyTraceSet:
                trace = CandidateCopyTrace(
                    from_virtual=None,
                    to_virtual=None,
                    status="trace-error",
                    likely_cause="trace-error",
                    note=note,
                )
                return CandidateCopyTraceSet(
                    traces=(trace,),
                    total_count=1,
                )

            def _candidate_copy_trace_from_report(copy_report) -> CandidateCopyTrace:
                return CandidateCopyTrace(
                    from_virtual=copy_report.from_virtual,
                    to_virtual=copy_report.to_virtual,
                    status=copy_report.status,
                    likely_cause=copy_report.likely_cause,
                    first_copy_pass=(
                        None if copy_report.first_copy is None
                        else copy_report.first_copy.pass_name
                    ),
                    last_copy_pass=(
                        None if copy_report.last_copy is None
                        else copy_report.last_copy.pass_name
                    ),
                    first_copy_block=(
                        None if copy_report.first_copy is None
                        else copy_report.first_copy.block_idx
                    ),
                    last_copy_block=(
                        None if copy_report.last_copy is None
                        else copy_report.last_copy.block_idx
                    ),
                    first_absent_pass=copy_report.first_absent_pass,
                    transform_category=copy_report.transform_category,
                    note=copy_report.note,
                )

            def _candidate_target_function(candidate) -> str:
                if candidate.anchor.scope_path:
                    return candidate.anchor.scope_path[0]
                return candidate.metadata.get("helper_function", function)

            def _candidate_priority_virtuals(
                candidate,
                *,
                candidate_pcdump: str,
                candidate_source: str,
            ) -> tuple[int, ...]:
                from ...mwcc_debug.symbol_bridge import (
                    find_all_virtuals_for_var,
                    list_bindings_with_basis,
                )

                virtuals: list[int] = list(candidate.anchor.virtuals)
                target_function = _candidate_target_function(candidate)
                fns = parse_pcdump(candidate_pcdump, function=target_function)
                fn = fns[0] if fns else None
                pre_pass = None if fn is None else fn.last_precolor_pass()
                if pre_pass is None:
                    return tuple(dict.fromkeys(virtuals))

                bindings, _basis = list_bindings_with_basis(
                    candidate_source,
                    target_function,
                    pre_pass,
                )
                for name in candidate.reads:
                    if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) is None:
                        continue
                    for binding in find_all_virtuals_for_var(bindings, name):
                        if binding.virtual >= 32:
                            virtuals.append(binding.virtual)
                return tuple(dict.fromkeys(virtuals))

            candidate_by_id = {
                candidate.candidate_id: candidate
                for candidate in report.candidates
            }
            baseline_trace_pcdump = pcdump_text or None
            trace_setup_error = None
            if baseline_trace_pcdump is None:
                try:
                    baseline_trace_pcdump = _run_trace_pcdump(source_rel)
                except Exception as exc:
                    trace_setup_error = f"{type(exc).__name__}: {exc}"
                    typer.echo(
                        f"[suggest-inlines] baseline pcdump unavailable for "
                        f"copy tracing: {trace_setup_error}",
                        err=True,
                    )
            for row in score_rows:
                candidate_id = str(row.get("candidate_id") or "")
                if trace_setup_error is not None:
                    trace_sets_by_candidate_id[candidate_id] = _copy_trace_error(
                        trace_setup_error
                    )
                    continue
                pcdump_value = row.get("pcdump_path")
                if not pcdump_value:
                    trace_sets_by_candidate_id[candidate_id] = _copy_trace_error(
                        "candidate pcdump unavailable from score-source"
                    )
                    continue
                pcdump_path = Path(str(pcdump_value))
                if not pcdump_path.is_file():
                    trace_sets_by_candidate_id[candidate_id] = _copy_trace_error(
                        f"candidate pcdump not found: {pcdump_path}"
                    )
                    continue
                try:
                    candidate_pcdump = pcdump_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                    traces = [
                        _candidate_copy_trace_from_report(copy_report)
                        for copy_report in list_new_copy_lifetimes(
                            baseline_trace_pcdump,
                            candidate_pcdump,
                            function,
                            reg_class="gpr",
                        )
                    ]
                    candidate = candidate_by_id.get(candidate_id)
                    candidate_source = ""
                    source_value = row.get("source_retained") or row.get("source_file")
                    if source_value:
                        source_path_for_trace = Path(str(source_value))
                        if source_path_for_trace.is_file():
                            candidate_source = source_path_for_trace.read_text(
                                encoding="utf-8",
                                errors="replace",
                            )
                    priority_virtuals = (
                        () if candidate is None
                        else _candidate_priority_virtuals(
                            candidate,
                            candidate_pcdump=candidate_pcdump,
                            candidate_source=candidate_source,
                        )
                    )
                    trace_sets_by_candidate_id[candidate_id] = (
                        summarize_candidate_copy_traces(
                            traces,
                            priority_virtuals=priority_virtuals,
                        )
                    )
                except Exception as exc:
                    trace_sets_by_candidate_id[candidate_id] = _copy_trace_error(
                        f"{type(exc).__name__}: {exc}"
                    )
        if target_path is None:
            def _checkdiff_runner(fn_name: str) -> CheckdiffResult:
                cmd = [
                    "python",
                    "tools/checkdiff.py",
                    fn_name,
                    "--no-tty",
                    "--format",
                    "json",
                ]
                proc = subprocess.run(
                    cmd,
                    cwd=melee_root,
                    capture_output=True,
                    text=True,
                    timeout=checkdiff_timeout,
                    env=_checkdiff_env_without_fingerprint(),
                )
                if not proc.stdout.strip():
                    cmd_text = " ".join(cmd)
                    raise RuntimeError(
                        proc.stderr.strip()
                        or f"checkdiff produced no JSON: {cmd_text}"
                    )
                return parse_checkdiff_json(proc.stdout)

            baseline_result = None
            try:
                baseline_result = _checkdiff_runner(function)
            except Exception as exc:
                typer.echo(
                    f"[suggest-inlines] baseline checkdiff unavailable: "
                    f"{type(exc).__name__}: {exc}",
                    err=True,
                )
            baseline_pct = (
                baseline_result.match_pct if baseline_result is not None else None
            )
            for row in score_rows:
                candidate_pct = _float_or_none(
                    row.get("checkdiff_match_percent") or row.get("match_percent")
                )
                if candidate_pct is not None:
                    row["checkdiff_pct"] = candidate_pct
                    row["checkdiff_match_percent"] = candidate_pct
                    row["match_percent"] = candidate_pct
                if candidate_pct is not None and baseline_pct is not None:
                    row["checkdiff_baseline_pct"] = baseline_pct
                    row["checkdiff_delta"] = candidate_pct - baseline_pct
        report.score_mode = "score-source"
        report.score_output_dir = str(output_dir)
        report.score_rows = score_rows
        scores = []
        for row in score_rows:
            score = source_row_to_candidate_score(row)
            trace_set = trace_sets_by_candidate_id.get(score.candidate_id)
            if trace_set is not None:
                score = dataclasses.replace(
                    score,
                    copy_traces=trace_set.raw_traces or trace_set.traces,
                    copy_trace_highlights=trace_set.traces,
                    copy_trace_total_count=trace_set.total_count,
                    copy_trace_omitted_count=trace_set.omitted_count,
                )
            scores.append(score)
        report.scores = rank_scores(scores)
        terminal = build_inline_local_write_terminal_summary(report)
        if terminal is not None:
            report.status = "terminal"
            report.terminal = True
            report.kind = str(terminal["kind"])
            report.family_id = str(terminal["family_id"])
            report.terminal_reason = str(terminal["terminal_reason"])
            report.terminal_blocker = str(terminal["terminal_blocker"])
            report.terminal_blockers = list(terminal["terminal_blockers"])
            report.terminal_summary = dict(terminal["terminal_summary"])
            report.source_model_proof = dict(terminal["source_model_proof"])
    elif verify:
        from ...mwcc_debug.candidate_verify import (
            CheckdiffResult,
            parse_checkdiff_json,
            verify_real_tree_patches,
        )
        from ...mwcc_debug.source_shape import (
            CandidateCopyTrace,
            CandidateCopyTraceSet,
            rank_scores,
            summarize_candidate_copy_traces,
        )

        def _candidate_copy_trace_from_report(copy_report) -> CandidateCopyTrace:
            return CandidateCopyTrace(
                from_virtual=copy_report.from_virtual,
                to_virtual=copy_report.to_virtual,
                status=copy_report.status,
                likely_cause=copy_report.likely_cause,
                first_copy_pass=(
                    None if copy_report.first_copy is None
                    else copy_report.first_copy.pass_name
                ),
                last_copy_pass=(
                    None if copy_report.last_copy is None
                    else copy_report.last_copy.pass_name
                ),
                first_copy_block=(
                    None if copy_report.first_copy is None
                    else copy_report.first_copy.block_idx
                ),
                last_copy_block=(
                    None if copy_report.last_copy is None
                    else copy_report.last_copy.block_idx
                ),
                first_absent_pass=copy_report.first_absent_pass,
                transform_category=copy_report.transform_category,
                note=copy_report.note,
            )

        def _candidate_target_function(candidate) -> str:
            if candidate.anchor.scope_path:
                return candidate.anchor.scope_path[0]
            return candidate.metadata.get("helper_function", function)

        def _candidate_priority_virtuals(
            candidate,
            candidate_pcdump: str,
        ) -> tuple[int, ...]:
            from ...mwcc_debug.symbol_bridge import (
                find_all_virtuals_for_var,
                list_bindings_with_basis,
            )

            virtuals: list[int] = list(candidate.anchor.virtuals)
            target_function = _candidate_target_function(candidate)
            fns = parse_pcdump(candidate_pcdump, function=target_function)
            fn = fns[0] if fns else None
            pre_pass = None if fn is None else fn.last_precolor_pass()
            if pre_pass is None:
                return tuple(dict.fromkeys(virtuals))

            bindings, _basis = list_bindings_with_basis(
                source_path.read_text(),
                target_function,
                pre_pass,
            )
            for name in candidate.reads:
                if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) is None:
                    continue
                for binding in find_all_virtuals_for_var(bindings, name):
                    if binding.virtual >= 32:
                        virtuals.append(binding.virtual)
            return tuple(dict.fromkeys(virtuals))

        def _checkdiff_runner(fn_name: str) -> CheckdiffResult:
            cmd = [
                "python",
                "tools/checkdiff.py",
                fn_name,
                "--no-build",
                "--no-tty",
                "--format",
                "json",
            ]
            proc = subprocess.run(
                cmd,
                cwd=melee_root,
                capture_output=True,
                text=True,
                timeout=checkdiff_timeout,
                env=_checkdiff_env_without_fingerprint(),
            )
            if not proc.stdout.strip():
                cmd_text = " ".join(cmd)
                raise RuntimeError(
                    proc.stderr.strip()
                    or f"checkdiff produced no JSON: {cmd_text}"
                )
            return parse_checkdiff_json(proc.stdout)

        baseline_result = None
        try:
            baseline_result = _checkdiff_runner(function)
        except Exception as exc:
            typer.echo(
                f"[suggest-inlines] baseline checkdiff unavailable: "
                f"{type(exc).__name__}: {exc}",
                err=True,
            )

        copy_trace_runner = None
        trace_setup_error = None
        baseline_trace_pcdump = pcdump_text or None
        candidate_by_id = {
            candidate.candidate_id: candidate
            for candidate in report.candidates
        }
        if trace_copies:
            if baseline_trace_pcdump is None:
                try:
                    baseline_trace_pcdump = _run_trace_pcdump(source_rel)
                except Exception as exc:
                    trace_setup_error = f"{type(exc).__name__}: {exc}"
                    typer.echo(
                        f"[suggest-inlines] baseline pcdump unavailable for "
                        f"copy tracing: {trace_setup_error}",
                        err=True,
                    )

            if baseline_trace_pcdump is None:
                def _copy_trace_runner(_candidate) -> CandidateCopyTraceSet:
                    trace = CandidateCopyTrace(
                        from_virtual=None,
                        to_virtual=None,
                        status="trace-error",
                        likely_cause="trace-error",
                        note=trace_setup_error,
                    )
                    return CandidateCopyTraceSet(
                        traces=(trace,),
                        total_count=1,
                    )
            else:
                from ...mwcc_debug.copy_trace import list_new_copy_lifetimes

                def _copy_trace_runner(_candidate) -> CandidateCopyTraceSet:
                    candidate_pcdump = _run_trace_pcdump(source_rel)
                    traces = [
                        _candidate_copy_trace_from_report(copy_report)
                        for copy_report in list_new_copy_lifetimes(
                            baseline_trace_pcdump,
                            candidate_pcdump,
                            function,
                            reg_class="gpr",
                        )
                    ]
                    candidate = candidate_by_id.get(_candidate.candidate_id)
                    priority_virtuals = (
                        () if candidate is None
                        else _candidate_priority_virtuals(
                            candidate,
                            candidate_pcdump,
                        )
                    )
                    return summarize_candidate_copy_traces(
                        traces,
                        priority_virtuals=priority_virtuals,
                    )

            copy_trace_runner = _copy_trace_runner

        report.scores = rank_scores(verify_real_tree_patches(
            function=function,
            source_path=source_path,
            patches=report.patches,
            checkdiff_runner=_checkdiff_runner,
            apply_best=apply_best,
            threshold=threshold,
            diagnostics_root=Path("nonmatchings") / function / "suggest_inlines",
            baseline_result=baseline_result,
            copy_trace_runner=copy_trace_runner,
        ))
    if json_out:
        print(render_json(
            report,
            emit_patches=emit_patches,
            emit_hunks=emit_hunks,
        ))
    else:
        print(render_text(report))
