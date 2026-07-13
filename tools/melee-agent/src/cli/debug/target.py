"""`debug target ...` — define and score allocator targets.

Carved out of cli/debug/__init__.py. Contains the 10 target command
handlers (score-dump, dtk-objdump, derive, reanchor, force-phys-from-diff,
order-target, match-iter-first, score-source, score-force-phys,
score-simplify-order) and their group-private helpers.

Shared helpers (and module-level names the tests patch on the cli.debug
package) still live in cli/debug/__init__.py. They are reached via call-time
(deferred) ``from src.cli.debug import ...`` imports inside the function
bodies -- a load-time import would create a cycle (__init__ imports this
module) and would also break ``monkeypatch.setattr(debug_cli, ...)``
semantics, since the patched name must resolve against __init__ at call time.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Iterable, Iterator, Mapping, Optional

import typer

from ...mwcc_debug import (
    FunctionEvents,
    derive_target_from_function,
    find_function,
    parse_hook_events,
    parse_pcdump,
    score_function,
)
from ...mwcc_debug import local_safety
from ...mwcc_debug.iter_match import (
    MatchResult,
    instr_signature,
    match_virtual_for_expected_def,
)
from ...mwcc_debug.frame_reservations import analyze_frame_from_asm_text
from ...mwcc_debug.asm_parser import (
    AsmInstruction,
    extract_function as asm_extract_function,
    find_first_def as asm_find_first_def,
    parse_prologue_end as asm_parse_prologue_end,
)
from ...mwcc_debug.artifacts import ArtifactRun, create_run
from ...mwcc_debug.temp_scratch import scratch_path as mwcc_debug_scratch_path

target_app = typer.Typer(
    help="Define and score allocator targets."
)

__all__ = [
    '_MatchIterFirstReg',
    '_MATCH_ITER_RANGE_RE',
    '_MATCH_ITER_ALIASES',
    '_parse_match_iter_first_regs',
    '_match_iter_first_class_id',
    '_target_vector_actionability',
    '_target_vector_after_auto_verify',
    '_print_target_vector_actionability',
    '_build_match_iter_first_target_vector',
    '_force_phys_target_spec',
    '_frame_spec_from_checkdiff_target',
    '_cflags_with_same_tu_include_dir',
    '_build_match_iter_first_auto_verify_cmd',
    '_resolve_auto_verify_restore_timeout',
    '_resolve_auto_verify_restore_max_steps',
    '_auto_verify_restore_cleanup_hint',
    '_auto_verify_failure_exit_code',
    '_annotate_auto_verify_actionability',
    '_score_source_failure_payload',
    '_score_source_scope_payload',
    '_score_source_unsafe_lane_payload',
    '_normalize_score_source_rel',
    '_score_source_related_prefixes',
    '_score_source_should_stage_through_unit',
    '_score_source_compile_source_rel',
    '_score_source_retained_pcdump_path',
    '_resolve_candidate_c_source',
    '_pcdump_for_object',
    'score',
    'target_dtk_objdump',
    'derive_target',
    'reanchor_target',
    'force_phys_from_diff',
    'order_target_cmd',
    'match_iter_first',
    'score_source',
    'score_force_phys',
    'score_simplify_order',
]


@dataclasses.dataclass(frozen=True)
class _MatchIterFirstReg:
    kind: str
    number: int

    @property
    def name(self) -> str:
        return f"{self.kind}{self.number}"


_MATCH_ITER_RANGE_RE = re.compile(r"^([rf])(\d+)(?:-|\.\.)([rf])?(\d+)$")
_MATCH_ITER_ALIASES: dict[str, tuple[_MatchIterFirstReg, ...]] = {
    "gpr-callee": tuple(_MatchIterFirstReg("r", n) for n in range(31, 24, -1)),
    "callee-gpr": tuple(_MatchIterFirstReg("r", n) for n in range(31, 24, -1)),
    "gpr-volatile": tuple(_MatchIterFirstReg("r", n) for n in range(3, 13)),
    "volatile-gpr": tuple(_MatchIterFirstReg("r", n) for n in range(3, 13)),
    "fpr-callee": tuple(_MatchIterFirstReg("f", n) for n in range(31, 23, -1)),
    "callee-fpr": tuple(_MatchIterFirstReg("f", n) for n in range(31, 23, -1)),
    "fpr-volatile": tuple(_MatchIterFirstReg("f", n) for n in range(0, 14)),
    "volatile-fpr": tuple(_MatchIterFirstReg("f", n) for n in range(0, 14)),
}


def _parse_match_iter_first_regs(regs: str) -> list[_MatchIterFirstReg]:
    parsed: list[_MatchIterFirstReg] = []
    for token in regs.split(","):
        token = token.strip()
        if not token:
            continue
        alias = _MATCH_ITER_ALIASES.get(token.lower())
        if alias is not None:
            parsed.extend(alias)
            continue
        range_match = _MATCH_ITER_RANGE_RE.match(token.lower())
        if range_match:
            kind = range_match.group(1)
            end_kind = range_match.group(3)
            if end_kind is not None and end_kind != kind:
                raise ValueError(f"invalid mixed-kind reg range: {token}")
            start = int(range_match.group(2))
            end = int(range_match.group(4))
            step = -1 if start > end else 1
            parsed.extend(
                _MatchIterFirstReg(kind=kind, number=n)
                for n in range(start, end + step, step)
            )
            continue
        if len(token) < 2 or token[0] not in {"r", "f"}:
            raise ValueError(f"invalid reg token: {token}")
        try:
            number = int(token[1:])
        except ValueError as exc:
            raise ValueError(f"invalid reg token: {token}") from exc
        parsed.append(_MatchIterFirstReg(kind=token[0], number=number))
    return parsed


def _match_iter_first_class_id(kind: str) -> int | None:
    if kind == "r":
        return 0
    if kind == "f":
        return 1
    return None


def _target_vector_actionability(targets: list[dict]) -> dict:
    runnable = [
        target for target in targets
        if target.get("force_vector_runnable", True)
    ]
    already = [
        target for target in runnable
        if target.get("already_target") is True
    ]
    needs_move = [
        target for target in runnable
        if target.get("already_target") is False
    ]
    unknown = [
        target for target in runnable
        if target.get("already_target") is None
    ]

    common = {
        "target_count": len(targets),
        "runnable_target_count": len(runnable),
        "already_target_count": len(already),
        "needs_move_count": len(needs_move),
        "unknown_current_count": len(unknown),
    }
    if runnable and not needs_move and not unknown:
        return {
            **common,
            "status": "already-satisfied",
            "work_bucket": "source-lifetime/callee-save-shape",
            "summary": (
                "target vector already satisfied: every runnable target "
                "already has its requested physical register"
            ),
            "next_step": (
                "Treat this as source lifetime or callee-save shape evidence; "
                "inspect locals live across calls, inlined loops, and saved "
                "object pointers before trying allocator overrides."
            ),
            "avoid": (
                "Do not spend more time on force-vector probes for this vector; "
                "the requested physical-register assignments are already true."
            ),
        }
    if needs_move:
        return {
            **common,
            "status": "needs-move",
            "work_bucket": "allocator-target-vector",
            "summary": (
                "target vector has runnable entries that are not assigned to "
                "their requested physical registers"
            ),
            "next_step": (
                "Use the force-vector or force-iter-first probe as a diagnostic "
                "test, then translate useful hits into source shape changes."
            ),
        }
    if unknown:
        return {
            **common,
            "status": "current-unknown",
            "work_bucket": "allocator-target-vector",
            "summary": (
                "target vector has entries whose current physical register "
                "could not be read from colorgraph events"
            ),
            "next_step": (
                "Refresh or inspect the pcdump colorgraph before deciding "
                "whether force-vector probes are actionable."
            ),
        }
    return {
        **common,
        "status": "no-runnable-targets",
        "work_bucket": "allocator-target-vector",
        "summary": "no runnable target-vector entries were derived",
        "next_step": (
            "Use another diagnostic surface; this vector cannot drive a "
            "force-vector probe."
        ),
    }


def _target_vector_after_auto_verify(
    target_vector: dict,
    auto_verify_result: dict | None,
) -> dict:
    if (
        not isinstance(auto_verify_result, dict)
        or auto_verify_result.get("actionability") != "no_improvement"
    ):
        return target_vector
    actionability = dict(target_vector.get("actionability") or {})
    if actionability.get("status") != "needs-move":
        return target_vector

    effective = dict(target_vector)
    actionability.update(
        {
            "status": "auto-verify-no-improvement",
            "work_bucket": "source-lifetime/callee-save-shape",
            "summary": (
                "auto-verify proved the force-vector override made no "
                "improvement to the function match%"
            ),
            "next_step": (
                "Pivot to source-shape, temporary lifetime, helper-inline, "
                "or subset target analysis; treat the force-vector as "
                "diagnostic evidence, not the next action."
            ),
            "avoid": (
                "Do not continue full force-vector probing after auto-verify "
                "reports no improvement."
            ),
            "auto_verify_actionability": "no_improvement",
        }
    )
    effective["actionability"] = actionability
    effective["force_vector_recommended"] = False
    return effective


def _print_target_vector_actionability(actionability: dict) -> None:
    status = actionability.get("status")
    summary = actionability.get("summary")
    if not status or not summary:
        return
    print()
    print(f"Target-vector status: {status}")
    print(f"  {summary}")
    next_step = actionability.get("next_step")
    if next_step:
        print(f"  next: {next_step}")
    avoid = actionability.get("avoid")
    if avoid:
        print(f"  avoid: {avoid}")


def _build_match_iter_first_target_vector(
    results: list[dict],
    events: FunctionEvents | None,
) -> dict:
    """Build the full vector that should be tested as one iter-first probe."""
    current_by_class_ig: dict[tuple[int, int], int] = {}
    if events is not None:
        for section in events.colorgraph_sections:
            for decision in section.decisions:
                current_by_class_ig[
                    (section.class_id, decision.ig_idx)
                ] = decision.assigned_reg

    targets: list[dict] = []
    for result in results:
        if result.get("status") != "ok":
            continue
        kind = str(result.get("kind", "r"))
        reg = int(result["reg"])
        ig_idx = int(result["ig_idx"])
        class_id = _match_iter_first_class_id(kind)
        current_reg = (
            current_by_class_ig.get((class_id, ig_idx))
            if class_id is not None else None
        )
        force_phys_unscoped = f"{ig_idx}:{reg}"
        if class_id is not None:
            force_phys_entry = f"{class_id}:{ig_idx}:{reg}"
            force_vector_entry = f"class{class_id}:ig{ig_idx}:phys={kind}{reg}"
        else:
            force_phys_entry = force_phys_unscoped
            force_vector_entry = f"ig{ig_idx}:phys={kind}{reg}"
        targets.append({
            "target_reg": reg,
            "target_reg_name": str(result.get("reg_name") or f"{kind}{reg}"),
            "kind": kind,
            "class_id": class_id,
            "ig_idx": ig_idx,
            "current_reg": current_reg,
            "current_reg_name": (
                f"{kind}{current_reg}"
                if isinstance(current_reg, int) and current_reg >= 0 else None
            ),
            "already_target": (
                current_reg == reg if isinstance(current_reg, int) else None
            ),
            "force_phys_entry": force_phys_entry,
            "force_vector_entry": force_vector_entry,
        })

    phys_by_key: dict[tuple[int | None, int], list[dict]] = {}
    for target in targets:
        key = (target.get("class_id"), int(target["ig_idx"]))
        bucket = phys_by_key.setdefault(key, [])
        if not any(item["target_reg"] == target["target_reg"] for item in bucket):
            bucket.append(target)

    conflict_by_key: dict[tuple[int | None, int], dict] = {}
    for key, bucket in phys_by_key.items():
        if len(bucket) <= 1:
            continue
        class_id, ig_idx = key
        conflict_by_key[key] = {
            "class_id": class_id,
            "ig_idx": ig_idx,
            "target_regs": [int(item["target_reg"]) for item in bucket],
            "target_reg_names": [
                str(item.get("target_reg_name") or item["target_reg"])
                for item in bucket
            ],
        }

    force_iter_first: list[int] = []
    seen_iter_first: set[int] = set()
    force_phys: dict[str, int] = {}
    force_phys_csv_parts: list[str] = []
    force_phys_unscoped_csv_parts: list[str] = []
    force_vector_parts: list[str] = []
    seen_force_keys: set[tuple[int | None, int]] = set()
    for target in targets:
        ig_idx = int(target["ig_idx"])
        if ig_idx not in seen_iter_first:
            force_iter_first.append(ig_idx)
            seen_iter_first.add(ig_idx)
        key = (target.get("class_id"), ig_idx)
        conflict = conflict_by_key.get(key)
        runnable = conflict is None
        target["force_vector_runnable"] = runnable
        if conflict is not None:
            target["force_vector_conflict"] = conflict
            continue
        if key in seen_force_keys:
            continue
        seen_force_keys.add(key)
        force_phys[str(ig_idx)] = int(target["target_reg"])
        force_phys_csv_parts.append(str(target["force_phys_entry"]))
        force_phys_unscoped_csv_parts.append(f"{ig_idx}:{target['target_reg']}")
        force_vector_parts.append(str(target["force_vector_entry"]))

    conflicts = list(conflict_by_key.values())
    actionability = _target_vector_actionability(targets)
    return {
        "force_iter_first": force_iter_first,
        "force_iter_first_csv": ",".join(str(i) for i in force_iter_first),
        "force_phys": force_phys,
        "force_phys_unscoped_csv": ",".join(force_phys_unscoped_csv_parts),
        "force_phys_csv": ",".join(force_phys_csv_parts),
        "force_vector": ",".join(force_vector_parts),
        "force_vector_runnable": not conflicts,
        "conflicts": conflicts,
        "targets": targets,
        "actionability": actionability,
        "force_vector_recommended": (
            actionability.get("status") not in {
                "already-satisfied",
                "no-runnable-targets",
            }
        ),
    }


def _force_phys_target_spec(function: str, vector: dict) -> dict:
    return {
        "function": function,
        "virtuals": vector.get("force_phys", {}),
    }


@target_app.command(name="score-dump")
def score(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to score (required)"),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help="Target spec file (YAML or JSON, required). See "
                 "src/mwcc_debug/scoring.py for format.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    breakdown: Annotated[
        bool,
        typer.Option(
            "--breakdown",
            help="Print the score components in addition to the total.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit score as JSON."),
    ] = False,
    expression_baseline: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-baseline",
            help=(
                "Baseline pcdump used to derive expression anchors for the "
                "target virtuals. JSON output then reports expression_score "
                "so virtual renumbering does not look like false progress."
            ),
        ),
    ] = None,
    expression_source: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-source",
            help=(
                "C source used for FPR expression attribution. Relative paths "
                "are resolved from the Melee root."
            ),
        ),
    ] = None,
    expression_reg_class: Annotated[
        str,
        typer.Option(
            "--expression-reg-class",
            help="Register class for expression anchors: fpr or gpr.",
        ),
    ] = "fpr",
) -> None:
    """Tier 4: score a pcdump's coloring decisions against a target spec.

    Lower scores are better (perfect match = 0). Designed to be called by
    decomp-permuter as a custom scorer.
    """
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _resolve_pcdump_path,
        _load_target_spec,
        _abort_function_not_in_dump,
        _score_source_target_details,
        _score_expression_anchors,
        _read_expression_source,
    )
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    spec = _load_target_spec(target)
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])

    events_list = parse_hook_events(text)
    events = find_function(events_list, function)

    result = score_function(fn, spec, events=events)

    if json_out:
        target_details = _score_source_target_details(result, spec)
        payload: dict[str, Any] = {
            "function": function,
            "score": result.total,
            "matched": result.matched,
            "targeted": result.targeted,
            "virtual_distance": result.virtual_distance,
            "spill_unexpected": result.spill_unexpected,
            "spill_missing": result.spill_missing,
            "interferer_distance": result.interferer_distance,
            "frame_targeted": result.frame_targeted,
            "frame_size_actual": result.frame_size_actual,
            "frame_size_target": result.frame_size_target,
            "frame_size_distance": result.frame_size_distance,
            "frame_unused_distance": result.frame_unused_distance,
            "frame_penalty": result.frame_penalty,
        }
        baseline_text = (
            expression_baseline.read_text(encoding="utf-8", errors="replace")
            if expression_baseline is not None
            else None
        )
        source_text, source_file = _read_expression_source(
            expression_source,
            melee_root=DEFAULT_MELEE_ROOT,
        )
        expression_score = _score_expression_anchors(
            target_spec=spec,
            target_details=target_details,
            pcdump_text=text,
            function=function,
            fn=fn,
            candidate_source_text=source_text,
            candidate_source_file=source_file,
            baseline_pcdump_text=baseline_text,
            baseline_source_text=source_text,
            baseline_source_file=source_file,
            reg_class=expression_reg_class,
        )
        if expression_score is not None:
            payload["expression_score"] = expression_score
        print(json.dumps(payload))
        return

    if breakdown:
        print(f"Function:           {function}")
        print(f"Score:              {result.total:.2f}")
        print(f"Matched:            {result.matched} / {result.targeted}")
        print(f"Virtual penalty:    {result.virtual_penalty:.2f} "
              f"({result.virtual_distance} wrong)")
        print(f"Spill penalty:      {result.spill_penalty:.2f} "
              f"(unexpected={len(result.spill_unexpected)} "
              f"missing={len(result.spill_missing)})")
        print(f"Interferer penalty: {result.interferer_penalty:.2f} "
              f"(sum |Δdeg| = {result.interferer_distance})")
        if result.frame_targeted:
            print(f"Frame penalty:      {result.frame_penalty:.2f} "
                  f"(size {result.frame_size_actual} → "
                  f"{result.frame_size_target}, "
                  f"unused-range Δ={result.frame_unused_distance})")
    else:
        print(f"{result.total:.2f}")


@target_app.command(name="dtk-objdump")
def target_dtk_objdump(
    o_file: Annotated[
        Path,
        typer.Argument(help="Object file to disassemble for decomp-permuter scoring."),
    ],
    melee_root: Annotated[
        Optional[Path],
        typer.Option(
            "--melee-root",
            help="Melee repo root containing build/tools/dtk. Auto-detected by default.",
        ),
    ] = None,
    object_root: Annotated[
        Optional[Path],
        typer.Option(
            "--object-root",
            help=(
                "Root used to resolve relative object paths appended by "
                "decomp-permuter, for example a remote decomp-permuter checkout."
            ),
        ),
    ] = None,
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function",
            "-f",
            help="Emit only the exact named DTK .fn block.",
        ),
    ] = None,
    name_magic: Annotated[
        bool,
        typer.Option(
            "--name-magic/--no-name-magic",
            help=(
                "Apply checkdiff-style anonymous @N relocation renames "
                "against the matching target.o before disassembly."
            ),
        ),
    ] = True,
) -> None:
    """Emit GNU objdump-shaped PPC disassembly using the project dtk binary."""
    from ...mwcc_debug.dtk_objdump import DtkObjdumpError, disassemble_object

    try:
        sys.stdout.write(disassemble_object(
            o_file,
            melee_root=melee_root,
            object_root=object_root,
            name_magic=name_magic,
            function=function,
        ))
    except DtkObjdumpError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


def _frame_spec_from_checkdiff_target(checkdiff_json: Path) -> dict:
    if not checkdiff_json.exists():
        raise typer.BadParameter(
            f"checkdiff JSON not found: {checkdiff_json}"
        )
    try:
        payload = json.loads(checkdiff_json.read_text())
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"checkdiff JSON could not be parsed: {exc}"
        ) from exc
    except OSError as exc:
        raise typer.BadParameter(
            f"checkdiff JSON could not be read: {exc}"
        ) from exc

    target_asm = payload.get("target_asm") or payload.get("reference_asm")
    if not isinstance(target_asm, list) or not all(
        isinstance(line, str) for line in target_asm
    ):
        raise typer.BadParameter(
            "checkdiff JSON must contain target_asm or reference_asm lines"
        )

    frame = analyze_frame_from_asm_text("\n".join(target_asm))
    if frame.get("frame_size") is None:
        raise typer.BadParameter(
            "checkdiff target asm did not contain a stack-frame allocation"
        )
    return {
        "frame_size": frame["frame_size"],
        "access_ranges": frame.get("access_ranges", []),
        "unused_ranges": frame.get("unused_ranges", []),
        "symbolic_home_map": frame.get("symbolic_home_map", []),
    }



@target_app.command(name="derive")
def derive_target(
    function: Annotated[
        str,
        typer.Option("--function", "-f",
                     help="Function name to extract (required)"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: yaml (default) or json.",
            click_type=typer.Choice(["yaml", "json"], case_sensitive=False)
            if False  # typer.Choice not available pre-0.12; fall back to str
            else None,
        ),
    ] = "yaml",
    force_phys_safe: Annotated[
        bool,
        typer.Option(
            "--force-phys-safe",
            help="Build `virtuals` from the raw COLORGRAPH DECISIONS (the "
                 "representation the first-divergence analyzer consumes) instead "
                 "of the analyze_function reconstruction. Excludes r0, spilled "
                 "nodes, and coalesced aliases, so the map round-trips cleanly as "
                 "a same-source force-phys target. Scope with --class.",
        ),
    ] = False,
    frame_from_checkdiff: Annotated[
        Optional[Path],
        typer.Option(
            "--frame-from-checkdiff",
            help=(
                "Override the frame target with target_asm/reference_asm from "
                "a `tools/checkdiff.py <function> --format json` payload. "
                "Use this when the current pcdump frame differs from the "
                "expected object frame."
            ),
        ),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option("--class", help="Register class for --force-phys-safe "
                                     "(0=GPR, 1=FPR)."),
    ] = 0,
) -> None:
    """Tier 4: extract the current virtual→physical mapping as a target spec.

    Useful for capturing a known-good (or known-experimental) target to
    use later as input to `target score-dump` or `inspect guide`. Especially useful with
    Tier 5 force-phys: force the desired mapping, run pcdump, capture
    the result with this command, then save the spec and use it to
    score subsequent natural-source attempts.
    """
    from src.cli.debug import (  # noqa: PLC0415
        _resolve_pcdump_path,
        _abort_function_not_in_dump,
    )
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])

    events_list = parse_hook_events(text)
    events = find_function(events_list, function)

    if force_phys_safe:
        if events is None:
            raise typer.BadParameter(
                f"--force-phys-safe needs COLORGRAPH DECISIONS, but no hook "
                f"events were found for {function!r} in {pcdump}"
            )
        from ...mwcc_debug import first_divergence as fd
        virtuals = fd.decision_coloring(events, class_id)
        spilled = sorted({
            e.ig_idx for s in events.simplify_sections if s.class_id == class_id
            for e in s.entries if e.spilled and e.ig_idx >= 0
        })
        spec = {"function": function, "virtuals": virtuals, "spilled": spilled}
    else:
        spec = derive_target_from_function(fn, events=events)

    if frame_from_checkdiff is not None:
        spec["frame"] = _frame_spec_from_checkdiff_target(frame_from_checkdiff)

    fmt = (output_format or "yaml").lower()
    if fmt == "json":
        print(json.dumps(spec, indent=2))
    else:
        # Render as YAML manually (avoid PyYAML dependency for output)
        print(f"function: {spec['function']}")
        print(f"virtuals:")
        for v in sorted(spec["virtuals"]):
            print(f"  {v}: {spec['virtuals'][v]}")
        if spec.get("spilled"):
            print(f"spilled:")
            for v in spec["spilled"]:
                print(f"  - {v}")
        if spec.get("frame"):
            frame = spec["frame"]
            print("frame:")
            print(f"  frame_size: {frame.get('frame_size')}")
            access_ranges = frame.get("access_ranges") or []
            if access_ranges:
                print("  access_ranges:")
                for item in access_ranges:
                    print(
                        f"    - start: {item.get('start')}\n"
                        f"      end: {item.get('end')}\n"
                        f"      size: {item.get('size')}\n"
                        f"      kind: {item.get('kind')}"
                    )
            unused_ranges = frame.get("unused_ranges") or []
            if unused_ranges:
                print("  unused_ranges:")
                for item in unused_ranges:
                    print(
                        f"    - start: {item.get('start')}\n"
                        f"      end: {item.get('end')}\n"
                        f"      size: {item.get('size')}"
                    )
    typer.echo(
        "Hint: save stdout to a target file, then run "
        f"`melee-agent debug inspect guide -f {function} --target <file>`.",
        err=True,
    )


@target_app.command(name="reanchor")
def reanchor_target(
    target_json: Annotated[Path, typer.Argument(help="Saved TargetSpec JSON (from build_target_spec.save_json).")],
    pcdump: Annotated[Optional[Path], typer.Argument(help="New compile's pcdump. Auto-resolves via -f if omitted.")] = None,
    function: Annotated[str, typer.Option("--function", "-f", help="Function name.")] = "",
    class_id: Annotated[int, typer.Option("--class", help="Register class (0=GPR).")] = 0,
    output_format: Annotated[str, typer.Option("--format", help="yaml|json.")] = "yaml",
) -> None:
    """Express a saved TargetSpec in a new compile's ig-numbering (Unit 3).

    Runs the role matcher (forward + inverse round-trip) and prints the
    force-phys-safe target spec {function, virtuals, spilled} for the new compile
    on stdout; per-role diagnostics (gone/merged/split/ambiguous/unstable_identity/
    no_descriptor — all EXCLUDED from the map) go to stderr. Feed stdout to
    `inspect first-divergence` as the --force-phys target.
    """
    from src.cli.debug import _resolve_pcdump_path  # noqa: PLC0415
    if class_id != 0:
        typer.echo("reanchor supports only class 0 (GPR) at this time.", err=True)
        raise typer.Exit(2)
    from ...mwcc_debug import role_descriptor as rd_mod
    from ...mwcc_debug import role_reanchor as rr
    target = rd_mod.TargetSpec.load_json(target_json)
    fn = function or target.function
    pcdump = _resolve_pcdump_path(pcdump, fn)
    new_c = rd_mod.Compile.from_text(pcdump.read_text(), fn, "")
    res = rr.reanchor(target, new_c, class_id=class_id)
    spilled = sorted({e.ig_idx for s in new_c.fev.simplify_sections if s.class_id == class_id
                      for e in s.entries if e.spilled and e.ig_idx >= 0}) if new_c.fev else []
    spec = rr.reanchor_to_target_spec(res, fn, spilled=spilled)
    for ig, status in sorted(res.diagnostics.items()):
        print(f"[reanchor] role {ig}: {status} (excluded)", file=sys.stderr)
    print(f"[reanchor] {len(spec['virtuals'])} matched -> force-phys, "
          f"{len(res.diagnostics)} excluded", file=sys.stderr)
    if (output_format or "yaml").lower() == "json":
        print(json.dumps(spec, indent=2))
    else:
        print(f"function: {spec['function']}")
        print("virtuals:")
        for v in sorted(spec["virtuals"]):
            print(f"  {v}: {spec['virtuals'][v]}")
        if spec["spilled"]:
            print("spilled:")
            for v in spec["spilled"]:
                print(f"  - {v}")


@target_app.command(name="force-phys-from-diff")
def force_phys_from_diff(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required).",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    checkdiff_json: Annotated[
        Optional[Path],
        typer.Option(
            "--checkdiff-json",
            help=(
                "Existing `tools/checkdiff.py <function> --format json` "
                "payload. If omitted, this command runs checkdiff with "
                "--no-build."
            ),
        ),
    ] = None,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds when auto-running checkdiff.",
        ),
    ] = 60.0,
    verify: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help=(
                "Run bounded union, singleton, and prefix force-vector "
                "verification after deriving the target list."
            ),
        ),
    ] = False,
    force_vector_probes: Annotated[
        bool,
        typer.Option(
            "--force-vector-probes/--no-force-vector-probes",
            help=(
                "With --verify, run singleton and prefix diagnostic probes "
                "after the full force-vector union."
            ),
        ),
    ] = True,
    force_vector_checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--force-vector-checkdiff-timeout",
            help="Timeout in seconds for each force-vector checkdiff run.",
        ),
    ] = 60.0,
    allow_stale_pcdump: Annotated[
        bool,
        typer.Option(
            "--allow-stale-pcdump",
            help=(
                "Allow an auto-resolved cached pcdump whose source has "
                "changed since capture. Off by default because stale "
                "precolor data can map targets to the wrong ig_idx."
            ),
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Derive --force-phys targets from a register-only checkdiff.

    The command aligns target/current checkdiff assembly lines to the
    function's pre-coloring pcdump, maps each mismatching physical-register
    destination back to its virtual/ig node, and emits both target-spec JSON
    for `debug target score-dump` and a class-scoped force-vector suitable
    for `match-iter-first --force-vector` diagnostic verification.
    """
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _resolve_pcdump_path,
        _abort_function_not_in_dump,
        _checkdiff_asm_lines,
        _find_unit_for_function,
        _parse_force_vector,
        _run_force_vector_auto_verify,
        _read_force_phys_checkdiff_payload,
        _derive_force_phys_from_register_diff_lines,
    )
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        melee_root,
        require_fresh=not allow_stale_pcdump,
    )
    pcdump_text = pcdump_path.read_text()

    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre_pass = fn.last_precolor_pass()
    if pre_pass is None:
        typer.echo(
            f"no pre-coloring pass found in pcdump for {function}",
            err=True,
        )
        raise typer.Exit(4)

    events_fn = find_function(parse_hook_events(pcdump_text), function)
    checkdiff_payload, checkdiff_source = _read_force_phys_checkdiff_payload(
        function=function,
        melee_root=melee_root,
        checkdiff_json=checkdiff_json,
        checkdiff_timeout=checkdiff_timeout,
    )
    payload_function = checkdiff_payload.get("function")
    if isinstance(payload_function, str) and payload_function != function:
        typer.echo(
            f"checkdiff JSON is for {payload_function}, not {function}",
            err=True,
        )
        raise typer.Exit(2)

    target_asm = _checkdiff_asm_lines(checkdiff_payload, "target_asm")
    current_asm = _checkdiff_asm_lines(checkdiff_payload, "current_asm")
    vector = _derive_force_phys_from_register_diff_lines(
        target_asm,
        current_asm,
        pre_pass,
        events_fn,
    )
    target_spec = _force_phys_target_spec(function, vector)
    unit = _find_unit_for_function(function, melee_root)

    force_vector_result: dict | None = None
    if verify:
        force_vector = vector.get("force_vector")
        if not force_vector:
            force_vector_result = {
                "ran": False,
                "reason": "no force-vector targets were derived",
            }
        elif unit is None:
            force_vector_result = {
                "ran": False,
                "reason": "function not found in report.json",
            }
        else:
            src_path = melee_root / "src" / f"{unit}.c"
            if not src_path.exists():
                force_vector_result = {
                    "ran": False,
                    "reason": f"source not found: {src_path}",
                }
            else:
                try:
                    entries = _parse_force_vector(force_vector)
                    force_vector_result = _run_force_vector_auto_verify(
                        src_path=src_path,
                        function=function,
                        entries=entries,
                        melee_root=melee_root,
                        checkdiff_timeout=force_vector_checkdiff_timeout,
                        run_diagnostic_probes=force_vector_probes,
                    )
                    force_vector_result["ran"] = True
                except Exception as exc:
                    force_vector_result = {
                        "ran": False,
                        "reason": str(exc),
                    }

    classification = checkdiff_payload.get("classification")
    result_payload = {
        "function": function,
        "unit": unit,
        "pcdump": str(pcdump_path),
        "checkdiff_source": checkdiff_source,
        "checkdiff_classification": classification,
        "target_spec": target_spec,
        "force_phys": vector["force_phys"],
        "force_phys_csv": vector["force_phys_csv"],
        "force_vector": vector["force_vector"],
        "force_vector_recommended": vector.get("force_vector_recommended", True),
        "target_vector_actionability": vector["actionability"],
        "targets": vector["targets"],
        "conflicts": vector["conflicts"],
        "register_only_target_count": vector["register_only_target_count"],
        "frame_alignment": vector.get("frame_alignment"),
    }
    if force_vector_result is not None:
        result_payload["force_vector_verify"] = force_vector_result

    if json_out:
        print(json.dumps(result_payload, indent=2))
        return

    print(f"Function: {function}")
    if unit:
        print(f"Unit:     {unit}")
    print(f"PCDump:   {pcdump_path}")
    print(f"Checkdiff: {checkdiff_source}")
    frame_alignment = vector.get("frame_alignment") or {}
    if frame_alignment.get("applied"):
        print(
            "Frame alignment: "
            f"target=0x{frame_alignment['target_frame_size']:x} "
            f"current=0x{frame_alignment['current_frame_size']:x} "
            f"delta={frame_alignment['frame_delta']}"
        )
    print()
    if not vector["targets"]:
        print("No register-only physical-register target destinations derived.")
    else:
        print("Derived force-phys targets from register-only checkdiff:")
        for target in vector["targets"]:
            current = target.get("current_reg_name") or "?"
            status = (
                "already target"
                if target.get("already_target") is True
                else "needs move"
                if target.get("already_target") is False
                else "current unknown"
            )
            print(
                f"  class{target['class_id']} ig{target['ig_idx']} -> "
                f"{target['target_reg_name']} "
                f"(current {current}; {status}; "
                f"{target['occurrence_count']} occurrence"
                f"{'' if target['occurrence_count'] == 1 else 's'})"
            )
    _print_target_vector_actionability(vector["actionability"])
    if vector["conflicts"]:
        print()
        print("Conflicting targets skipped:")
        for conflict in vector["conflicts"]:
            print(
                f"  class{conflict['class_id']} ig{conflict['ig_idx']} "
                f"wanted both {conflict['kind']}{conflict['existing_phys']} "
                f"and {conflict['kind']}{conflict['conflicting_phys']}"
            )
    print()
    print("Target spec for debug target score-dump:")
    print(json.dumps(target_spec, indent=2))
    if vector["force_phys_csv"]:
        print()
        print(f"Force-phys vector: {vector['force_phys_csv']}")
    if vector["force_vector"] and vector.get("force_vector_recommended", True):
        print(f"Force-vector: {vector['force_vector']}")
    elif vector["force_vector"]:
        print(
            "Force-vector not recommended: "
            f"{vector['actionability'].get('summary')}"
        )
    if force_vector_result is not None:
        print()
        print("== force-vector verify ==")
        if not force_vector_result.get("ran"):
            print(f"  did not run: {force_vector_result.get('reason')}")
        else:
            union = force_vector_result.get("union", {})
            if isinstance(union, dict):
                print(
                    f"  union: {union.get('status')} "
                    f"(returncode {union.get('returncode')})"
                )
            probes = force_vector_result.get("probes")
            if isinstance(probes, list) and probes:
                print("  diagnostic probes:")
                for probe in probes:
                    print(
                        f"    {probe.get('label')}: {probe.get('status')} "
                        f"(returncode {probe.get('returncode')})"
                    )


@target_app.command(name="order-target")
def order_target_cmd(
    function: Annotated[
        str, typer.Option("--function", "-f", help="Function to derive (required)."),
    ],
    unit: Annotated[
        Optional[str],
        typer.Option("--unit", "-u",
                     help="TU path relative to src/ (e.g. melee/mn/mndiagram). "
                          "Auto-resolves via report.json if omitted."),
    ] = None,
    class_id: Annotated[
        int, typer.Option("--class-id", help="Register class (0=GPR)."),
    ] = 0,
    out: Annotated[
        Optional[Path],
        typer.Option("--out",
                     help="Where to write the OrderTarget YAML on a directed "
                          "result. Default: docs/superpowers/order-targets/"
                          "<function>.yaml. No file is written for non-directed "
                          "routings."),
    ] = None,
    checkdiff_timeout: Annotated[
        float, typer.Option("--checkdiff-timeout", help="Per-checkdiff timeout."),
    ] = 60.0,
    force_vector_timeout: Annotated[
        float,
        typer.Option(
            "--force-vector-timeout",
            help=(
                "Wall-clock timeout in seconds for the order-target "
                "force-vector union verifier."
            ),
        ),
    ] = 30.0,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit the full artifact as JSON."),
    ] = False,
) -> None:
    """Derive a proven order-distance target (the §4.2 class partition).

    Runs the pipeline end-to-end and persists an OrderTarget on a `directed`
    result. Every failure mode is a NAMED routing, not an error; the exit code
    mirrors routing: 0 directed, 3 unanchorable, 4 not_order_class,
    5 force_cap_blocked, 6 unstable_target.
    """
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _find_unit_for_function,
        _collect_order_target_inputs,
    )
    from src.mwcc_debug.order_target_derive import derive_order_target
    from src.search.directed.order_target import (
        Routing, validate_order_target,
    )

    melee_root = DEFAULT_MELEE_ROOT
    resolved_unit = unit or _find_unit_for_function(function, melee_root)
    if resolved_unit is None:
        typer.echo(
            f"function '{function}' not found in report.json; pass --unit.",
            err=True,
        )
        raise typer.Exit(2)

    inputs = _collect_order_target_inputs(
        function=function, unit=resolved_unit, class_id=class_id,
        melee_root=melee_root, checkdiff_timeout=checkdiff_timeout,
        force_vector_timeout=force_vector_timeout,
    )
    target = derive_order_target(inputs)

    if json_out:
        from dataclasses import asdict
        print(json.dumps(asdict(target), indent=2, default=list))
    else:
        print(f"Function: {target.function}")
        print(f"Unit:     {target.unit}")
        print(f"Routing:  {target.routing}")
        if target.class_evidence:
            print(f"Evidence: {target.class_evidence}")
        if target.routing == Routing.DIRECTED.value:
            print(f"Target roles: {target.target_roles}")
            print(f"Order vector: {target.order_target}")
            if target.unscored_roles:
                print(f"Unscored residual: {target.unscored_roles}")

    if target.routing == Routing.DIRECTED.value:
        validate_order_target(target)
        out_path = out or (
            melee_root / "docs" / "superpowers" / "order-targets"
            / f"{target.function}.yaml"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        target.save_yaml(out_path)
        if not json_out:
            print(f"Wrote {out_path}")

    raise typer.Exit(target.exit_code())


@target_app.command(name="match-iter-first")
def match_iter_first(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required)",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    regs: Annotated[
        str,
        typer.Option(
            "--regs",
            help="Comma-separated physical regs to report on "
                 "(for example r31,r30, f31-f30, gpr-callee for "
                 "r31-r25, or gpr-volatile,r0 for volatile target diffs; "
                 "default: r31,r30,r29,r28).",
        ),
    ] = "r31,r30,r29,r28",
    asm: Annotated[
        Optional[Path],
        typer.Option(
            "--asm",
            help="Override path to expected .s file. "
                 "Auto-resolves via report.json.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    auto_verify: Annotated[
        bool,
        typer.Option(
            "--auto-verify",
            help="When ambiguous targets are present, run "
                 "`debug dump local --force-iter-first <list>` to score the "
                 "recommended list against the expected output and "
                 "report the match% delta. Then restore object/report "
                 "state with a managed cleanup bounded by "
                 "MWCC_DEBUG_RESTORE_TIMEOUT, falling back to "
                 "MWCC_DEBUG_HANG_TIMEOUT. Restore failures print "
                 "cleanup_complete=false in JSON and exit non-zero. "
                 "Off by default — the explicit verify step costs ~10–30s.",
        ),
    ] = False,
    force_vector: Annotated[
        Optional[str],
        typer.Option(
            "--force-vector",
            help=(
                "Compose several force overrides and verify them together "
                "with `debug dump local --diff`. Entries are comma-separated: "
                "ig40:phys=r30, ig42:coalesce=38, "
                "class0:iter5:phys=r31, ig50:iter-first. The union is tested "
                "first, then singleton and prefix probes run by default to "
                "expose incompatible steps."
            ),
        ),
    ] = None,
    force_vector_probes: Annotated[
        bool,
        typer.Option(
            "--force-vector-probes/--no-force-vector-probes",
            help=(
                "When --force-vector is set, also test each singleton entry "
                "and each intermediate prefix after the full union."
            ),
        ),
    ] = True,
    force_vector_checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--force-vector-checkdiff-timeout",
            help="Timeout in seconds for each force-vector integrated checkdiff run.",
        ),
    ] = 60.0,
    allow_stale_pcdump: Annotated[
        bool,
        typer.Option(
            "--allow-stale-pcdump",
            help=(
                "Allow an auto-resolved cached pcdump whose source has "
                "changed since capture. Off by default because target "
                "derivation can produce stale ig_idx mappings."
            ),
        ),
    ] = False,
) -> None:
    """Recommend --force-iter-first arguments by reading the expected .s.

    For each physical register in --regs, finds the first instruction in
    the expected output that defines it (post-prologue), structurally
    aligns that instruction to the current pcdump's pre-coloring pass,
    and reports the virtual register (= ig_idx in MWCC's IG).

    Useful for local-vs-local iter-order cascades where rank-callees
    can't tell which local "should have" gotten r31. Pipe the output's
    ig_idx list into --force-iter-first.

    Warning: when any matched target has `[ambiguous]` confidence
    (multiple pre-coloring instructions matched the expected signature),
    feeding the full list to --force-iter-first can disturb unrelated
    code. Verify with `debug dump local <tu> --force-iter-first <list>
    --diff` (or run with --auto-verify) before trusting the suggestion.

    Auto-verify cleanup is bounded by MWCC_DEBUG_RESTORE_TIMEOUT, falling back
    to MWCC_DEBUG_HANG_TIMEOUT; restore failures print cleanup_complete=false.

    --force-vector composes multiple force overrides, verifies the union with
    integrated checkdiff, and probes individual/prefix steps for compatibility.
    """
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _ForceVectorEntry,
        _resolve_pcdump_path,
        _abort_function_not_in_dump,
        _ninja_cflags_for_unit,
        _find_unit_for_function,
        _smoke_mwcc_debug_compiler,
        _find_wibo,
        _find_compiler_dir,
        _build_local_dll,
        _cache_settle_seconds,
        _run_auto_verify_command_with_status,
        _source_path_for_function,
        _acquire_checkdiff_repo_lock,
        _build_and_match,
        _checkdiff_asm_lines,
        _get_match_pct,
        _parse_force_vector,
        _run_force_vector_auto_verify,
        _restore_object_report_for_unit,
        asm_extract_function,
        asm_find_first_def,
        asm_parse_prologue_end,
        match_virtual_for_expected_def,
        parse_pcdump,
        parse_hook_events,
        find_function,
    )
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        melee_root,
        require_fresh=not allow_stale_pcdump,
    )
    pcdump_text = pcdump_path.read_text()

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json. "
            f"Run `ninja build/GALE01/report.json` and retry.",
            err=True,
        )
        raise typer.Exit(2)

    if asm is None:
        asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
    else:
        asm_path = asm
    if not asm_path.exists():
        typer.echo(
            f"expected .s not found: {asm_path}\n"
            f"Run `python configure.py && ninja` to build it.",
            err=True,
        )
        raise typer.Exit(3)

    asm_text = asm_path.read_text()
    asm_fn = asm_extract_function(asm_text, function)
    if asm_fn is None:
        typer.echo(
            f"function '{function}' not found in {asm_path}",
            err=True,
        )
        raise typer.Exit(3)

    prologue_end = asm_parse_prologue_end(asm_fn.instructions)
    body = asm_fn.instructions[prologue_end:]

    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre_pass = fn.last_precolor_pass()
    if pre_pass is None:
        typer.echo(
            f"no pre-coloring pass found in pcdump for {function}",
            err=True,
        )
        raise typer.Exit(4)

    try:
        reg_list = _parse_match_iter_first_regs(regs)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    results: list[dict] = []
    for reg in reg_list:
        expected_def = asm_find_first_def(
            body,
            target_reg=reg.number,
            reg_kind=reg.kind,
        )
        if expected_def is None:
            results.append({
                "reg": reg.number,
                "kind": reg.kind,
                "reg_name": reg.name,
                "status": "unused",
                "note": (
                    f"{reg.name} never used as a destination in expected"
                ),
            })
            continue
        pos, expected_ist = expected_def
        match = match_virtual_for_expected_def(
            expected_ist=expected_ist,
            expected_position=pos,
            pre_pass=pre_pass,
            reg_kind=reg.kind,
        )
        if match is None:
            results.append({
                "reg": reg.number,
                "kind": reg.kind,
                "reg_name": reg.name,
                "status": "no_match",
                "note": f"no structural match in pre-coloring for "
                        f"`{expected_ist.opcode} {expected_ist.operands}`",
            })
            continue
        results.append({
            "reg": reg.number,
            "kind": reg.kind,
            "reg_name": reg.name,
            "status": "ok",
            "ig_idx": match.ig_idx,
            "virtual": match.virtual,
            "instr_idx": match.instruction_index,
            "opcode": expected_ist.opcode,
            "operands": expected_ist.operands,
            "confidence": match.confidence,
        })

    # Detect ambiguous matches up front so both text and JSON paths agree.
    ig_indices: list[int] = list(dict.fromkeys(
        r["ig_idx"] for r in results if r.get("status") == "ok"
    ))
    ambiguous_results = [
        r for r in results
        if r.get("status") == "ok" and r.get("confidence") == "ambiguous"
    ]
    has_ambiguous = bool(ambiguous_results)
    warning_message: Optional[str] = None
    if has_ambiguous:
        amb_regs = ", ".join(
            str(r.get("reg_name") or f"r{r['reg']}")
            for r in ambiguous_results
        )
        warning_message = (
            f"{len(ambiguous_results)} target(s) are [ambiguous] "
            f"({amb_regs}) — multiple pre-coloring instructions matched "
            f"the expected signature, and the closest-position pick may "
            f"be wrong. Before trusting this output, verify with "
            f"`debug dump local <c_file> --force-iter-first "
            f"{','.join(str(i) for i in ig_indices)} "
            f"--force-iter-first-fn {function} --diff` "
            f"(or pass --auto-verify on this command). If the diff "
            f"doesn't improve, the ambiguous assignments are wrong; "
            f"try a subset."
        )

    events_fn = find_function(parse_hook_events(pcdump_text), function)
    target_vector = _build_match_iter_first_target_vector(results, events_fn)

    force_vector_entries: list[_ForceVectorEntry] | None = None
    force_vector_result: Optional[dict] = None
    if force_vector is not None:
        effective_force_vector = force_vector
        if force_vector == "auto":
            effective_force_vector = target_vector["force_vector"]
            if not effective_force_vector:
                force_vector_result = {
                    "ran": False,
                    "reason": "no force-vector targets were derived",
                }
        if force_vector_result is None:
            try:
                force_vector_entries = _parse_force_vector(effective_force_vector)
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(2) from exc
            src_path = melee_root / "src" / f"{unit}.c"
            if not src_path.exists():
                force_vector_result = {
                    "ran": False,
                    "reason": f"source not found: {src_path}",
                }
            else:
                try:
                    force_vector_result = _run_force_vector_auto_verify(
                        src_path=src_path,
                        function=function,
                        entries=force_vector_entries,
                        melee_root=melee_root,
                        checkdiff_timeout=force_vector_checkdiff_timeout,
                        run_diagnostic_probes=force_vector_probes,
                    )
                    force_vector_result["ran"] = True
                except Exception as exc:
                    force_vector_result = {"ran": False, "reason": str(exc)}

    # Optional auto-verify: run debug dump local with the proposed iter-first
    # list, compare per-function match% against the baseline, and surface
    # the delta. Gated behind --auto-verify because the underlying MWCC
    # compile is the slow part (~10–30s in our local wibo path).
    auto_verify_result: Optional[dict] = None
    if auto_verify and ig_indices:
        try:
            src_path = melee_root / "src" / f"{unit}.c"
            if not src_path.exists():
                auto_verify_result = {
                    "ran": False,
                    "reason": f"source not found: {src_path}",
                }
            else:
                print(
                    f"[auto-verify] resolving baseline match% for {function}",
                    file=sys.stderr,
                )
                baseline_pct = _get_match_pct(function, melee_root)
                ig_csv_av = ",".join(str(i) for i in ig_indices)
                watchdog_s = os.environ.get("MWCC_DEBUG_HANG_TIMEOUT", "45")
                print(
                    f"[auto-verify] debug dump local watchdog: {watchdog_s}s "
                    f"without compile progress",
                    file=sys.stderr,
                )
                # Run debug dump local with the override. The dump itself is
                # discarded; dump local's local watchdog bounds no-progress
                # hangs, while this wrapper emits periodic status so long
                # runs are visibly alive.
                auto_verify_output = (
                    src_path.parent
                    / f".{function}.auto-verify.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
                )
                cmd = _build_match_iter_first_auto_verify_cmd(
                    src_path=src_path,
                    ig_csv=ig_csv_av,
                    function=function,
                    output_path=auto_verify_output,
                )
                status_label = (
                    f"--force-iter-first {ig_csv_av} "
                    f"--force-iter-first-fn {function}"
                )
                r_av = _run_auto_verify_command_with_status(
                    cmd,
                    cwd=melee_root / "tools" / "melee-agent",
                    status_label=status_label,
                )
                auto_verify_output.unlink(missing_ok=True)
                print(
                    "[auto-verify] reading post-verify match%",
                    file=sys.stderr,
                )
                new_pct = _get_match_pct(function, melee_root)
                delta = (
                    None if (new_pct is None or baseline_pct is None)
                    else new_pct - baseline_pct
                )
                auto_verify_result = {
                    "ran": True,
                    "returncode": r_av.returncode,
                    "status": "ok" if r_av.returncode == 0 else "verify_failed",
                    "force_iter_first": target_vector["force_iter_first"],
                    "force_iter_first_csv": target_vector["force_iter_first_csv"],
                    "force_phys": target_vector["force_phys"],
                    "force_phys_csv": target_vector["force_phys_csv"],
                    "force_vector": target_vector["force_vector"],
                    "baseline_pct": baseline_pct,
                    "new_pct": new_pct,
                    "delta": delta,
                    "stderr_tail": "\n".join(
                        r_av.stderr.splitlines()[-5:]
                    ) if r_av.stderr else "",
                }
                # Restore the report by rebuilding the .o cleanly so the
                # cached state isn't poisoned by our verify override.
                (
                    restore_timeout_s,
                    restore_timeout_source,
                ) = _resolve_auto_verify_restore_timeout()
                restore_max_steps = _resolve_auto_verify_restore_max_steps()
                print(
                    f"[auto-verify] restore timeout: {restore_timeout_s:g}s "
                    f"({restore_timeout_source})",
                    file=sys.stderr,
                )
                print(
                    f"[auto-verify] restore max dry-run steps: "
                    f"{restore_max_steps}",
                    file=sys.stderr,
                )
                print(
                    "[auto-verify] restoring clean object/report state",
                    file=sys.stderr,
                )
                restore_proc, restore_planned_steps = (
                    _restore_object_report_for_unit(
                        unit=unit,
                        melee_root=melee_root,
                        timeout_s=restore_timeout_s,
                        max_steps=restore_max_steps,
                        force=False,
                    )
                )
                if restore_planned_steps > restore_max_steps:
                    print(
                        f"[auto-verify] restore skipped: dry-run planned "
                        f"{restore_planned_steps} ninja steps, above "
                        f"MWCC_DEBUG_RESTORE_MAX_STEPS={restore_max_steps}",
                        file=sys.stderr,
                    )
                restore_stderr_tail = "\n".join(
                    restore_proc.stderr.splitlines()[-5:]
                ) if restore_proc.stderr else ""
                restore_result = {
                    "returncode": restore_proc.returncode,
                    "timeout_s": restore_timeout_s,
                    "timeout_source": restore_timeout_source,
                    "max_steps": restore_max_steps,
                    "planned_steps": restore_planned_steps,
                    "stderr_tail": restore_stderr_tail,
                }
                restore_hint = _auto_verify_restore_cleanup_hint(
                    restore_proc.stderr or ""
                )
                if restore_hint:
                    restore_result["cleanup_hint"] = restore_hint
                auto_verify_result["restore"] = restore_result
                if restore_proc.returncode == 0:
                    auto_verify_result["cleanup_complete"] = True
                else:
                    auto_verify_result["status"] = "restore_failed"
                    auto_verify_result["cleanup_complete"] = False
        except (subprocess.TimeoutExpired, Exception) as _av_exc:
            auto_verify_result = {"ran": False, "reason": str(_av_exc)}

    if isinstance(auto_verify_result, dict):
        _annotate_auto_verify_actionability(auto_verify_result)
        target_vector = _target_vector_after_auto_verify(
            target_vector,
            auto_verify_result,
        )

    if json_out:
        payload: dict = {
            "function": function,
            "unit": unit,
            "results": results,
            "has_ambiguous": has_ambiguous,
            "target_vector": target_vector,
            "force_iter_first": target_vector["force_iter_first"],
            "force_iter_first_csv": target_vector["force_iter_first_csv"],
            "force_phys": target_vector["force_phys"],
            "force_phys_csv": target_vector["force_phys_csv"],
            "force_vector": target_vector["force_vector"],
            "force_vector_runnable": target_vector.get(
                "force_vector_runnable", True,
            ),
            "force_vector_recommended": target_vector.get(
                "force_vector_recommended", True,
            ),
            "force_vector_conflicts": target_vector.get("conflicts", []),
            "target_vector_actionability": target_vector["actionability"],
        }
        if warning_message:
            payload["warning"] = warning_message
        if auto_verify_result is not None:
            payload["auto_verify"] = auto_verify_result
            status = auto_verify_result.get("status")
            if status:
                payload["auto_verify_status"] = status
            actionability = auto_verify_result.get("actionability")
            if actionability:
                payload["auto_verify_actionability"] = actionability
            if "cleanup_complete" in auto_verify_result:
                payload["cleanup_complete"] = auto_verify_result[
                    "cleanup_complete"
                ]
        if force_vector_result is not None:
            payload["force_vector_verify"] = force_vector_result
            union = force_vector_result.get("union")
            if isinstance(union, dict):
                payload["force_vector_status"] = union.get("status")
                payload["force_vector_match"] = union.get("match")
        print(json.dumps(payload, indent=2))
        exit_code = _auto_verify_failure_exit_code(auto_verify_result)
        if exit_code is not None:
            raise typer.Exit(exit_code)
        return

    print(f"Function: {function}")
    print(f"Unit:     {unit}")
    print(f"ASM:      {asm_path.relative_to(melee_root)}")
    print()
    print(f"Expected iter-first targets:")
    for r in results:
        reg_str = str(r.get("reg_name") or f"r{r['reg']}")
        virt_str = f"{r.get('kind', 'r')}{r['virtual']}" if r["status"] == "ok" else ""
        if r["status"] == "ok":
            print(
                f"  {reg_str} <- ig_idx {r['ig_idx']:<4} "
                f"(virt {virt_str}, instr {r['instr_idx']}: "
                f"{r['opcode']} {r['operands']}) [{r['confidence']}]"
            )
        else:
            print(f"  {reg_str} - {r['note']}")
    if ig_indices:
        ig_csv = ",".join(str(i) for i in ig_indices)
        print()
        print("Full target vector:")
        for target in target_vector["targets"]:
            current = target.get("current_reg_name") or "?"
            status = (
                "already target"
                if target.get("already_target") is True
                else "needs move"
                if target.get("already_target") is False
                else "current unknown"
            )
            print(
                f"  {target['target_reg_name']} <- ig_idx "
                f"{target['ig_idx']} (current {current}; {status})"
            )
        _print_target_vector_actionability(target_vector["actionability"])
        print()
        if target_vector.get("force_vector_recommended", True):
            print(f"Try:")
            print(
                f"  melee-agent debug dump local <source.c> "
                f"--force-iter-first {ig_csv} "
                f"--force-iter-first-fn {function} --diff"
            )
            if target_vector["force_phys_csv"]:
                print(
                    f"Force-phys vector for scorer setup: "
                    f"{target_vector['force_phys_csv']}"
                )
            if target_vector["force_vector"]:
                print(
                    f"Force-vector for diagnostic probes: "
                    f"{target_vector['force_vector']}"
                )
        else:
            print(
                "No allocator override probe recommended for this vector; "
                f"{target_vector['actionability'].get('next_step')}"
            )
        if target_vector.get("conflicts"):
            print("Force-vector conflicts omitted from runnable vector:")
            for conflict in target_vector["conflicts"]:
                class_part = (
                    f"class{conflict['class_id']}:"
                    if conflict.get("class_id") is not None else ""
                )
                regs = ", ".join(conflict.get("target_reg_names") or [])
                print(
                    f"  {class_part}ig{conflict['ig_idx']} has multiple "
                    f"target phys regs: {regs}"
                )
    if warning_message:
        print()
        print(f"WARNING: {warning_message}")
    if auto_verify_result is not None:
        print()
        print(f"== auto-verify ==")
        if auto_verify_result.get("ran"):
            base = auto_verify_result.get("baseline_pct")
            new = auto_verify_result.get("new_pct")
            delta = auto_verify_result.get("delta")
            base_str = (
                f"{base:.2f}%" if isinstance(base, (int, float)) else "?"
            )
            new_str = (
                f"{new:.2f}%" if isinstance(new, (int, float)) else "?"
            )
            delta_str = (
                f"{delta:+.2f}%" if isinstance(delta, (int, float))
                else "(unknown)"
            )
            print(
                f"  baseline -> with override: {base_str} -> {new_str} "
                f"({delta_str})"
            )
            actionability_note = auto_verify_result.get("actionability_note")
            if actionability_note:
                print(f"  actionability: {auto_verify_result.get('actionability')} - {actionability_note}")
            tail = auto_verify_result.get("stderr_tail")
            if tail:
                print(f"  stderr tail:")
                for line in tail.splitlines():
                    print(f"    {line}")
            restore = auto_verify_result.get("restore")
            if isinstance(restore, dict):
                print(
                    f"  restore object/report: exit "
                    f"{restore.get('returncode')} "
                    f"(timeout {restore.get('timeout_s')}s"
                    f" via {restore.get('timeout_source', 'unknown')}; "
                    f"planned {restore.get('planned_steps', '?')} steps, "
                    f"max {restore.get('max_steps', '?')})"
                )
                restore_tail = restore.get("stderr_tail")
                if restore_tail:
                    print(f"  restore stderr tail:")
                    for line in restore_tail.splitlines():
                        print(f"    {line}")
                cleanup_hint = restore.get("cleanup_hint")
                if cleanup_hint:
                    print(f"  cleanup hint: {cleanup_hint}")
        else:
            print(f"  did not run: {auto_verify_result.get('reason')}")
    if force_vector_result is not None:
        print()
        print("== force-vector verify ==")
        if not force_vector_result.get("ran"):
            print(f"  did not run: {force_vector_result.get('reason')}")
        else:
            union = force_vector_result.get("union", {})
            if isinstance(union, dict):
                print(
                    f"  union: {union.get('status')} "
                    f"(returncode {union.get('returncode')})"
                )
                for key in (
                    "force_phys_csv",
                    "force_phys_iter_csv",
                    "force_coalesce_csv",
                    "force_iter_first_csv",
                ):
                    if union.get(key):
                        print(f"    {key}: {union[key]}")
                stdout_tail = union.get("stdout_tail")
                if stdout_tail and union.get("status") != "match":
                    print("    stdout tail:")
                    for line in str(stdout_tail).splitlines():
                        print(f"      {line}")
            probes = force_vector_result.get("probes")
            if isinstance(probes, list) and probes:
                print("  diagnostic probes:")
                for probe in probes:
                    print(
                        f"    {probe.get('label')}: {probe.get('status')} "
                        f"(returncode {probe.get('returncode')})"
                    )
    exit_code = _auto_verify_failure_exit_code(auto_verify_result)
    if exit_code is not None:
        raise typer.Exit(exit_code)



def _cflags_with_same_tu_include_dir(cflags: str, unit_src_rel: str) -> str:
    """Make copied same-TU probes resolve quote-includes like the real source.

    The Melee build uses MWCC's `-cwd source`, so `"foo.h"` is resolved from
    the compiled file's directory. A probe copied under build/... needs the
    original source directory on the include path to keep local headers working.
    """
    unit_dir = Path(unit_src_rel).parent.as_posix()
    if not unit_dir or unit_dir == ".":
        return cflags
    return f"-i {shlex.quote(unit_dir)} {cflags}"



def _build_match_iter_first_auto_verify_cmd(
    *,
    src_path: Path,
    ig_csv: str,
    function: str,
    output_path: Optional[Path] = None,
) -> list[str]:
    if output_path is None:
        output_path = (
            src_path.parent
            / f".{function}.auto-verify.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
        )
    return [
        sys.executable, "-m", "src.cli", "debug",
        "dump", "local", str(src_path),
        "--force-iter-first", ig_csv,
        "--force-iter-first-fn", function,
        "-o", str(output_path),
    ]



def _resolve_auto_verify_restore_timeout(
    env: Optional[Mapping[str, str]] = None,
) -> tuple[float, str]:
    values = env if env is not None else os.environ
    restore_timeout = values.get("MWCC_DEBUG_RESTORE_TIMEOUT")
    if restore_timeout is not None:
        return float(restore_timeout), "MWCC_DEBUG_RESTORE_TIMEOUT"
    hang_timeout = values.get("MWCC_DEBUG_HANG_TIMEOUT")
    if hang_timeout is not None:
        return float(hang_timeout), "MWCC_DEBUG_HANG_TIMEOUT"
    return 180.0, "default"


def _resolve_auto_verify_restore_max_steps(
    env: Optional[Mapping[str, str]] = None,
) -> int:
    values = env if env is not None else os.environ
    return int(values.get("MWCC_DEBUG_RESTORE_MAX_STEPS", "64"))



def _auto_verify_restore_cleanup_hint(stderr: str) -> str:
    if "ninja: warning: premature end of file; recovering" not in stderr:
        return ""
    return (
        "ninja metadata looks truncated after an interrupted build; run "
        "`ninja -t recompact` from the repo root, then retry with "
        "`melee-agent debug dump restore-object-report <source.c>`. That command "
        "previews the ninja plan, refuses large rebuilds unless `--force` is "
        "passed, and owns the restore process group. If the warning persists, "
        "remove `.ninja_deps`/`.ninja_log`, then run `python configure.py` "
        "before retrying."
    )



def _auto_verify_failure_exit_code(auto_verify_result: Optional[dict]) -> Optional[int]:
    if not isinstance(auto_verify_result, dict) or not auto_verify_result.get("ran"):
        return None
    restore = auto_verify_result.get("restore")
    if not isinstance(restore, dict):
        return None
    returncode = restore.get("returncode")
    if returncode in (None, 0, "0"):
        return None
    try:
        numeric_returncode = int(returncode)
    except (TypeError, ValueError):
        return 1
    if numeric_returncode == 125:
        restore_text = "\n".join(
            str(restore.get(key, ""))
            for key in ("stdout", "stdout_tail", "stderr", "stderr_tail", "cleanup_hint")
        )
        if "refusing to launch restore" in restore_text:
            return None
    return numeric_returncode


def _annotate_auto_verify_actionability(auto_verify_result: dict) -> None:
    """Classify whether an auto-verified target is worth pursuing."""
    if not isinstance(auto_verify_result, dict) or not auto_verify_result.get("ran"):
        return
    delta = auto_verify_result.get("delta")
    if not isinstance(delta, (int, float)):
        auto_verify_result["actionability"] = "unknown"
        auto_verify_result["actionable"] = False
        auto_verify_result["actionability_note"] = (
            "auto-verify did not produce a numeric match% delta"
        )
        return
    if delta > 0.01:
        auto_verify_result["actionability"] = "improved"
        auto_verify_result["actionable"] = True
        auto_verify_result["actionability_note"] = (
            "forced target improved the function match%"
        )
    elif delta < -0.01:
        auto_verify_result["actionability"] = "regressed"
        auto_verify_result["actionable"] = False
        auto_verify_result["actionability_note"] = (
            "forced target made the function match% worse"
        )
    else:
        auto_verify_result["actionability"] = "no_improvement"
        auto_verify_result["actionable"] = False
        auto_verify_result["actionability_note"] = (
            "forced target matched but did not move the function match%"
        )



def _score_source_failure_payload(
    *,
    score_value: int,
    error: str,
    proc: subprocess.CompletedProcess[str] | None = None,
    timeout: float | None = None,
    returncode: int | None = None,
    unsafe_lane: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "score": score_value,
        "error": error,
    }
    if proc is not None:
        payload["returncode"] = proc.returncode
        if proc.stderr:
            payload["stderr_tail"] = proc.stderr[-4000:]
        if proc.stdout:
            payload["stdout_tail"] = proc.stdout[-4000:]
    elif returncode is not None:
        payload["returncode"] = returncode
    if timeout is not None:
        payload["timeout_seconds"] = timeout
    if unsafe_lane is not None:
        payload["unsafe_local_pcdump_lane"] = dict(unsafe_lane)
    return payload


def _score_source_scope_payload(
    *,
    function: str,
    c_file: str,
    source_rel: str,
    cflags_unit_rel: str,
) -> dict[str, Any]:
    candidate_id = Path(source_rel).stem or Path(c_file).stem
    return {
        "function": function,
        "score_function": function,
        "source_file": source_rel,
        "c_file": c_file,
        "source_retained": source_rel,
        "cflags_from": cflags_unit_rel,
        "candidate_id": candidate_id,
    }


def _apply_score_source_scope(
    payload: dict[str, Any],
    *,
    function: str,
    c_file: str,
    source_rel: str,
    cflags_unit_rel: str,
) -> dict[str, Any]:
    for key, value in _score_source_scope_payload(
        function=function,
        c_file=c_file,
        source_rel=source_rel,
        cflags_unit_rel=cflags_unit_rel,
    ).items():
        if value is not None:
            payload.setdefault(key, value)
    return payload


def _score_source_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _apply_score_source_target_verdict(payload: dict[str, Any]) -> None:
    target_score = payload.get("target_score")
    structural_guard = payload.get("structural_guard")
    if not isinstance(target_score, dict) or not isinstance(structural_guard, dict):
        return
    matched = _score_source_int(target_score.get("matched"))
    targeted = _score_source_int(target_score.get("targeted"))
    if matched is None or targeted is None or targeted <= 0:
        return

    target_score_accepted = matched > 0
    structural_guard["target_score_matched"] = matched
    structural_guard["target_score_targeted"] = targeted
    structural_guard["target_score_accepted"] = target_score_accepted

    if not target_score_accepted:
        reason = "target score missed all requested registers"
        structural_guard["accepted"] = False
        structural_guard["rejection_reason"] = (
            structural_guard.get("rejection_reason") or reason
        )
        payload["candidate_verdict"] = {
            "classification": "target-score-miss",
            "ledger": "revert candidate",
            "matched": matched,
            "targeted": targeted,
            "reason": reason,
        }
        return

    if matched < targeted:
        payload.setdefault(
            "candidate_verdict",
            {
                "classification": "target-score-partial-hit",
                "ledger": "active experiment",
                "matched": matched,
                "targeted": targeted,
                "reason": "target score hit some requested registers",
            },
        )
        return

    payload.setdefault(
        "candidate_verdict",
        {
            "classification": "target-score-hit",
            "ledger": "active experiment",
            "matched": matched,
            "targeted": targeted,
            "reason": "target score hit all requested registers",
        },
    )


def _apply_score_source_checkdiff_guard(
    payload: dict[str, Any],
    *,
    c_file: str,
    source_rel: str,
    melee_root: Path,
    function: str,
    timeout: float | None,
    deadline: float | None,
    full_unit_source: bool,
    score_real_tree: Any,
    update_score_from_normalized: bool = False,
) -> None:
    candidate_path = Path(c_file)
    if not candidate_path.is_absolute():
        candidate_path = melee_root / source_rel
    real_score = score_real_tree(
        candidate_path,
        function=function,
        melee_root=melee_root,
        timeout=timeout,
        deadline=deadline,
        include_structural_guard=True,
        full_unit_source=full_unit_source,
    )
    match_percent = getattr(real_score, "match_percent", None)
    match_percent_error = getattr(real_score, "match_percent_error", None)
    structural_guard = getattr(real_score, "structural_guard", None)
    structural_guard_error = getattr(real_score, "structural_guard_error", None)

    payload["match_percent"] = match_percent
    payload["checkdiff_match_percent"] = match_percent
    payload["structural_guard"] = structural_guard
    payload["structural_guard_error"] = structural_guard_error or match_percent_error
    checkdiff_payload = getattr(real_score, "checkdiff_payload", None)
    if isinstance(checkdiff_payload, dict):
        payload["checkdiff_evidence"] = checkdiff_payload
    guard = structural_guard if isinstance(structural_guard, dict) else {}
    normalized = guard.get("normalized_diff_lines")
    if (
        update_score_from_normalized
        and isinstance(normalized, int)
        and not isinstance(normalized, bool)
    ):
        payload["score"] = normalized
    _apply_score_source_target_verdict(payload)
    payload["checkdiff_guard"] = {
        "match_percent": match_percent,
        "classification_primary": guard.get("classification_primary"),
        "normalized_diff_lines": guard.get("normalized_diff_lines"),
        "hunk_count": guard.get("hunk_count"),
        "accepted": guard.get("accepted"),
    }


def _score_source_unsafe_lane_payload(
    *,
    source_rel: str,
    function: str,
    cflags_unit_rel: str,
    allow_unsafe: bool,
    related_source_prefixes: Iterable[str] = (),
) -> dict[str, Any] | None:
    related_prefixes = tuple(
        _normalize_score_source_rel(prefix).rstrip("/")
        for prefix in related_source_prefixes
    )
    if related_prefixes and not allow_unsafe:
        observed = local_safety.scan_local_wibo_processes()
        exact_guard = local_safety.guard_local_pcdump_lane(
            source_rel=source_rel,
            function=function,
            processes=observed,
            allow_unsafe=False,
        )
        unsafe_by_pid = {process.pid: process for process in exact_guard.processes}
        for process in observed:
            if not process.uninterruptible or process.source_rel is None:
                continue
            process_source = _normalize_score_source_rel(process.source_rel)
            if any(
                process_source == prefix or process_source.startswith(f"{prefix}/")
                for prefix in related_prefixes
            ):
                unsafe_by_pid[process.pid] = process
        lane_guard = local_safety.LocalLaneGuardResult(
            unsafe=bool(unsafe_by_pid),
            processes=list(unsafe_by_pid.values()),
        )
    else:
        lane_guard = local_safety.guard_local_pcdump_lane(
            source_rel=source_rel,
            function=function,
            allow_unsafe=allow_unsafe,
        )
    if not lane_guard.unsafe:
        return None
    message = local_safety.format_unsafe_lane_message(
        source_rel=source_rel,
        function=function,
        processes=lane_guard.processes,
    )
    if related_prefixes:
        message += (
            "\nRelated retained candidate prefix(es) treated as the same "
            f"local lane: {', '.join(related_prefixes)}"
        )
    return {
        "source": source_rel,
        "function": function,
        "cflags_unit": cflags_unit_rel,
        "message": message,
        "processes": [process.to_dict() for process in lane_guard.processes],
        "related_source_prefixes": list(related_prefixes),
    }


def _normalize_score_source_rel(source: str | None) -> str:
    if source is None:
        return ""
    value = str(source).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")


def _score_source_related_prefixes(
    *,
    source_rel: str,
    cflags_unit_rel: str,
) -> tuple[str, ...]:
    source_norm = _normalize_score_source_rel(source_rel)
    cflags_norm = _normalize_score_source_rel(cflags_unit_rel)
    if not source_norm or source_norm == cflags_norm:
        return ()
    if source_norm.startswith("src/"):
        return ()
    parent = str(PurePosixPath(source_norm).parent)
    prefixes: list[str] = []
    if parent not in {"", "."}:
        prefixes.append(parent)
    if _score_source_should_stage_through_unit(
        source_rel=source_norm,
        cflags_unit_rel=cflags_norm,
    ) and cflags_norm not in prefixes:
        prefixes.append(cflags_norm)
    return tuple(prefixes)


def _score_source_should_stage_through_unit(
    *,
    source_rel: str,
    cflags_unit_rel: str,
) -> bool:
    source_norm = _normalize_score_source_rel(source_rel)
    cflags_norm = _normalize_score_source_rel(cflags_unit_rel)
    return (
        source_norm != cflags_norm
        and cflags_norm.startswith("src/")
        and not source_norm.startswith("src/")
    )


@contextmanager
def _score_source_compile_source_rel(
    *,
    source_rel: str,
    cflags_unit_rel: str,
    melee_root: Path,
    timeout: float | None = None,
) -> Iterator[str]:
    from src.cli.debug import (  # noqa: PLC0415
        _acquire_source_score_repo_lock,
        _capture_source_file_snapshot,
        _preserve_source_restore_backup,
        _register_active_source_restore,
        _restore_source_file_snapshot,
        _stage_source_file_bytes,
        _unregister_active_source_restore,
    )
    if not _score_source_should_stage_through_unit(
        source_rel=source_rel,
        cflags_unit_rel=cflags_unit_rel,
    ):
        yield source_rel
        return

    candidate_path = melee_root / source_rel
    unit_path = melee_root / cflags_unit_rel
    with _acquire_source_score_repo_lock(melee_root, timeout=timeout):
        original = _capture_source_file_snapshot(unit_path)
        _register_active_source_restore(unit_path, original)
        release_active_restore = False
        supersede_newer_restores = False
        try:
            candidate_bytes = candidate_path.read_bytes()
            _stage_source_file_bytes(unit_path, candidate_bytes, original)
            yield cflags_unit_rel
        finally:
            try:
                restore_error = _restore_source_file_snapshot(unit_path, original)
                if restore_error is not None:
                    backup_path, backup_error = _preserve_source_restore_backup(
                        unit_path,
                        original.contents,
                        melee_root=melee_root,
                    )
                    if backup_error is not None:
                        restore_error = f"{restore_error}; {backup_error}"
                    elif backup_path is not None:
                        restore_error = (
                            f"{restore_error}; original bytes preserved at "
                            f"{backup_path}"
                        )
                        release_active_restore = True
                    raise RuntimeError(restore_error)
                release_active_restore = True
                supersede_newer_restores = True
            finally:
                if release_active_restore:
                    _unregister_active_source_restore(
                        unit_path,
                        original,
                        supersede_newer=supersede_newer_restores,
                    )


def _score_source_retained_pcdump_path(
    *,
    source_rel: str,
    melee_root: Path,
    pcdump_output: Path | None,
) -> Path:
    if pcdump_output is not None:
        return (
            pcdump_output
            if pcdump_output.is_absolute()
            else melee_root / pcdump_output
        )
    source_path = Path(source_rel)
    if not source_path.is_absolute():
        source_path = melee_root / source_path
    return source_path.with_suffix(".pcdump.txt")


def _load_force_phys_score_source_target(
    target: Path,
    *,
    function: str,
) -> dict[str, Any] | None:
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError):
        return None
    except Exception:
        return None
    if not isinstance(data, dict) or "force_phys" not in data:
        return None
    spec_function = data.get("function")
    if spec_function != function:
        typer.echo(
            f"target spec function mismatch: spec.function={spec_function!r} "
            f"!= --function={function!r}",
            err=True,
        )
        raise typer.Exit(2)
    class_id = data.get("class_id", 0)
    if not isinstance(class_id, int) or isinstance(class_id, bool):
        typer.echo("target spec class_id must be an integer", err=True)
        raise typer.Exit(2)
    raw_baseline = data.get("baseline_dump")
    if not isinstance(raw_baseline, str) or not raw_baseline:
        typer.echo("target spec missing baseline_dump", err=True)
        raise typer.Exit(2)
    baseline_dump = Path(raw_baseline).expanduser()
    if not baseline_dump.is_absolute():
        baseline_dump = (target.parent / baseline_dump).resolve()
    raw_force_phys = data.get("force_phys")
    if not isinstance(raw_force_phys, dict) or not raw_force_phys:
        typer.echo("target spec missing non-empty force_phys mapping", err=True)
        raise typer.Exit(2)
    force_phys: dict[int, int] = {}
    for raw_ig, raw_phys in raw_force_phys.items():
        if (
            not isinstance(raw_ig, int)
            or isinstance(raw_ig, bool)
            or not isinstance(raw_phys, int)
            or isinstance(raw_phys, bool)
        ):
            typer.echo("force_phys must map integer ig_idx to integer phys", err=True)
            raise typer.Exit(2)
        force_phys[raw_ig] = raw_phys
    coalesce_preservation = data.get("coalesce_preservation", True)
    if not isinstance(coalesce_preservation, bool):
        typer.echo("coalesce_preservation must be true/false", err=True)
        raise typer.Exit(2)
    return {
        "class_id": class_id,
        "baseline_dump": baseline_dump,
        "force_phys": force_phys,
        "coalesce_preservation": coalesce_preservation,
    }


def _score_source_force_phys_payload(
    pcdump_text: str,
    *,
    target: Path | None,
    function: str,
) -> dict[str, Any] | None:
    if target is None:
        return None
    config = _load_force_phys_score_source_target(target, function=function)
    if config is None:
        return None

    from ...mwcc_debug.simplify_order_scoring import (  # noqa: PLC0415
        LEX_BIG,
        STRUCTURAL_REJECTION_SCORE,
        extract_signature,
        find_coalesced_targets,
    )
    from ...mwcc_debug.simplify_search import (  # noqa: PLC0415
        precolor_distance,
        score_force_phys_assignment,
    )

    class_id = int(config["class_id"])
    baseline_dump = config["baseline_dump"]
    assert isinstance(baseline_dump, Path)
    force_phys = dict(config["force_phys"])
    try:
        baseline_text = baseline_dump.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"failed to read baseline_dump {baseline_dump}: {exc}", err=True)
        raise typer.Exit(2)
    baseline = extract_signature(baseline_text, function, class_id=class_id)
    if baseline is None:
        typer.echo(
            f"baseline pcdump {baseline_dump} does not contain {function!r}",
            err=True,
        )
        raise typer.Exit(2)
    candidate = extract_signature(pcdump_text, function, class_id=class_id)
    if candidate is None:
        score_value = 10**9
        return {
            "score": score_value,
            "error": f"function {function!r} not in candidate pcdump",
            "target": str(target),
            "target_spec": str(target),
            "score_mode": "force-phys",
        }

    coalesced_targets: set[int] = set()
    if config["coalesce_preservation"]:
        try:
            candidate_events = find_function(parse_hook_events(pcdump_text), function)
        except (AttributeError, TypeError, ValueError):
            candidate_events = None
        if candidate_events is not None and hasattr(
            candidate_events,
            "coalesce_sections",
        ):
            coalesced_targets = find_coalesced_targets(
                candidate_events,
                targets=set(force_phys),
                class_id=class_id,
            )
    dist = precolor_distance(baseline, candidate)
    force_score = score_force_phys_assignment(baseline, candidate, force_phys)
    missed = len(force_phys) - force_score.common_prefix_length
    structural_rejection = bool(coalesced_targets)
    score_value = (
        STRUCTURAL_REJECTION_SCORE
        if structural_rejection
        else missed * LEX_BIG + dist.total
    )
    virtuals = {}
    candidate_assigned = dict(candidate.assigned_regs)
    baseline_assigned = dict(baseline.assigned_regs)
    for ig, expected in sorted(force_phys.items()):
        actual = candidate_assigned.get(ig)
        baseline_actual = baseline_assigned.get(ig)
        virtuals[str(ig)] = {
            "expected": expected,
            "actual": actual,
            "baseline_actual": baseline_actual,
            "matched": actual == expected,
            "baseline_matched": baseline_actual == expected,
        }
    target_score = {
        "total": score_value,
        "matched": force_score.common_prefix_length,
        "targeted": len(force_phys),
        "virtual_distance": missed,
        "virtuals": virtuals,
        "source": "force-phys-assignments",
    }
    return {
        "score": score_value,
        "target_score": target_score,
        "force_phys_score": {
            "score": score_value,
            "targeted": len(force_phys),
            "force_phys_hits": force_score.common_prefix_length,
            "baseline_hits": force_score.baseline_common_prefix_length,
            "matched_igs": list(force_score.observed_prefix),
            "target_igs": list(force_score.target_prefix),
            "precolor_distance": {
                "total": dist.total,
                "ig_added": dist.ig_added,
                "ig_removed": dist.ig_removed,
                "coalesce_added": dist.coalesce_added,
                "coalesce_removed": dist.coalesce_removed,
                "spill_added": dist.spill_added,
                "spill_removed": dist.spill_removed,
            },
            "structural_rejection": structural_rejection,
            "coalesced_targets": sorted(coalesced_targets),
        },
        "target": str(target),
        "target_spec": str(target),
        "score_mode": "force-phys",
        "class_id": class_id,
    }


@target_app.command(name="score-source")
def score_source(
    c_file: Annotated[
        str,
        typer.Argument(
            help="Path to a .c file to compile (relative to melee root). "
                 "Can be a staging path inside `nonmatchings/`.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function within the TU to score.",
        ),
    ],
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec (YAML or JSON, from `debug target derive`).",
        ),
    ] = None,
    cflags_from: Annotated[
        Optional[str],
        typer.Option(
            "--cflags-from",
            help="Use cflags from this unit's ninja block instead of "
                 "inferring from c_file. Useful when c_file is a staged "
                 "candidate without its own ninja build block.",
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet", "-q",
            help="Suppress everything except the integer score on stdout. "
                 "Designed for use as permuter's external scorer command.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json/--no-json", help="Emit machine-readable scoring metadata."),
    ] = False,
    retain_pcdump: Annotated[
        bool,
        typer.Option(
            "--retain-pcdump/--no-retain-pcdump",
            help=(
                "Keep the generated pcdump beside the scored source, or at "
                "--pcdump-output when provided. JSON output reports the path."
            ),
        ),
    ] = False,
    pcdump_output: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump-output",
            help=(
                "Explicit destination for --retain-pcdump. Relative paths are "
                "resolved from the melee repo root. Supplying this implies "
                "pcdump retention."
            ),
        ),
    ] = None,
    checkdiff_guard: Annotated[
        bool,
        typer.Option(
            "--checkdiff-guard/--no-checkdiff-guard",
            help=(
                "In JSON mode, apply the candidate to the real source tree and "
                "include no-build checkdiff structural guard metadata."
            ),
        ),
    ] = False,
    full_unit_source: Annotated[
        bool,
        typer.Option(
            "--full-unit-source/--target-function-source",
            help=(
                "Treat C_FILE as a complete replacement for the compile unit "
                "when running the real-tree checkdiff guard. Required when a "
                "retained candidate defines helper/type/data context outside "
                "the target function."
            ),
        ),
    ] = False,
    remote: Annotated[
        bool,
        typer.Option(
            "--remote/--no-remote",
            help=(
                "Score through the remote pcdump backend directly, bypassing "
                "local wibo and patched compiler discovery."
            ),
        ),
    ] = False,
    remote_fallback: Annotated[
        bool,
        typer.Option(
            "--remote-fallback/--no-remote-fallback",
            help=(
                "Use the local scorer unless the unsafe local pcdump lane "
                "guard blocks it, then stage/score through the remote backend."
            ),
        ),
    ] = False,
    remote_host: Annotated[
        str,
        typer.Option(
            "--remote-host",
            help="SSH host alias for --remote/--remote-fallback.",
            envvar="MWCC_DEBUG_HOST",
        ),
    ] = "nzxt-local",
    remote_script: Annotated[
        str,
        typer.Option(
            "--remote-script",
            help="Path to run_pcdump.ps1 on the remote host.",
            envvar="MWCC_DEBUG_REMOTE_SCRIPT",
        ),
    ] = r"C:\Users\mikes\code\mwcc_debug\run_pcdump.ps1",
    remote_branch: Annotated[
        Optional[str],
        typer.Option(
            "--remote-branch",
            help="Branch to compile on the remote backend.",
            envvar="MWCC_DEBUG_BRANCH",
        ),
    ] = None,
    remote_no_pull: Annotated[
        bool,
        typer.Option(
            "--remote-no-pull",
            help="Forward --no-pull to the remote pcdump backend.",
        ),
    ] = False,
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout",
            help=(
                "Total score-source budget in seconds, shared by compile and "
                "optional checkdiff guard. Use 0 to disable."
            ),
        ),
    ] = 120.0,
    expression_baseline: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-baseline",
            help=(
                "Baseline pcdump used to derive expression anchors for the "
                "target virtuals. JSON output then reports expression_score "
                "that follows expression identity across virtual renumbering."
            ),
        ),
    ] = None,
    expression_source: Annotated[
        Optional[str],
        typer.Option(
            "--expression-source",
            help=(
                "Baseline C source for expression anchors. Defaults to "
                "--cflags-from when supplied, otherwise c_file."
            ),
        ),
    ] = None,
    expression_reg_class: Annotated[
        str,
        typer.Option(
            "--expression-reg-class",
            help="Register class for expression anchors: fpr or gpr.",
        ),
    ] = "fpr",
) -> None:
    """Compile a source via debug dump local, then score target or checkdiff evidence.

    Single-command flow for use as decomp-permuter's external scorer.
    Outputs an integer score (lower = better; 0 = perfect target match).
    Use `--quiet` to silence everything except the score itself.

    Wires:
        c_file → mwcceppc_debug.exe → pcdump.txt → parse → score_function
    """
    from src.cli.debug import (  # noqa: PLC0415
        _resolve_src_relative,
        _find_unit_for_function,
        _ninja_cflags_for_unit,
        _find_wibo,
        _find_compiler_dir,
        _load_target_spec,
        _run_command_with_optional_timeout,
        _acquire_source_score_repo_lock,
        _register_active_source_restore,
        _unregister_active_source_restore,
        _restore_source_snapshot,
        _make_expensive_restore_result,
        _build_and_match_with_diagnostic,
        _run_ninja_with_no_diag_retry,
        _score_source_target_details,
        _score_expression_anchors,
        _read_expression_source,
        _score_source_unsafe_lane_payload,
        _run_remote_pcdump,
        _remote_retained_source_terminal_blocker,
        _timeout_message,
        _score_source_candidate_real_tree,
        DEFAULT_MELEE_ROOT,
    )
    from ...mwcc_debug import (
        find_function,
        parse_hook_events,
        parse_pcdump,
        score_function,
    )
    from ...mwcc_debug.diff_capture import _env_with_child_hang_timeout

    melee_root = DEFAULT_MELEE_ROOT
    src_rel = _resolve_src_relative(c_file)

    # cflags: from the explicit unit OR from c_file's ninja block
    cflags_unit = cflags_from if cflags_from else c_file
    cflags_unit_rel = _resolve_src_relative(cflags_unit)
    stages_candidate_through_unit = _score_source_should_stage_through_unit(
        source_rel=src_rel,
        cflags_unit_rel=cflags_unit_rel,
    )
    effective_full_unit_source = bool(
        full_unit_source or stages_candidate_through_unit
    )
    related_source_prefixes = _score_source_related_prefixes(
        source_rel=src_rel,
        cflags_unit_rel=cflags_unit_rel,
    )
    artifact_run: ArtifactRun = create_run(
        melee_root,
        command=["debug", "target", "score-source"],
        provenance={
            "function": function,
            "source": str(src_rel),
            "cflags_from": str(cflags_unit_rel),
            "remote_requested": remote,
        },
    )
    candidate_path = melee_root / src_rel
    artifact_source: Path | None = None
    if candidate_path.is_file():
        artifact_source = artifact_run.retain_file(
            candidate_path,
            "source/candidate.c",
        )
    artifact_finalized = False

    def _emit_score_source_result(
        payload: dict[str, Any],
        *,
        state: str,
        emit_stdout: bool = True,
    ) -> None:
        nonlocal artifact_finalized
        if artifact_finalized:
            raise RuntimeError("score-source artifact run already finalized")
        artifact_score = artifact_run.retain_json("score.json", payload)
        artifact_run.finalize(state, result=payload)
        artifact_finalized = True
        if not emit_stdout:
            return
        if json_out:
            result = dict(payload)
            result.update(
                {
                    "artifact_run": str(artifact_run.run_dir),
                    "artifact_manifest": str(artifact_run.manifest_path),
                    "artifact_source": (
                        str(artifact_source) if artifact_source is not None else None
                    ),
                    "artifact_score": str(artifact_score),
                }
            )
            print(json.dumps(result))
        else:
            print(payload["score"])

    active_timeout = timeout if timeout and timeout > 0 else None
    command_deadline = (
        time.monotonic() + active_timeout
        if active_timeout is not None
        else None
    )

    unsafe_lane: dict[str, Any] | None = None
    use_remote_pcdump = remote
    remote_reason: str | None = "--remote" if remote else None
    if not remote:
        unsafe_lane = _score_source_unsafe_lane_payload(
            source_rel=src_rel,
            function=function,
            cflags_unit_rel=cflags_unit_rel,
            allow_unsafe=local_safety.allow_unsafe_local_pcdump(),
            related_source_prefixes=related_source_prefixes,
        )
        if unsafe_lane is not None:
            if remote_fallback:
                use_remote_pcdump = True
                remote_reason = "unsafe local pcdump lane"
            else:
                if not quiet:
                    typer.echo(unsafe_lane["message"], err=True)
                score_value = 2**30
                payload = _score_source_failure_payload(
                    score_value=score_value,
                    error="unsafe local pcdump lane",
                    returncode=124,
                    unsafe_lane=unsafe_lane,
                )
                payload["full_unit_source"] = effective_full_unit_source
                _apply_score_source_scope(
                    payload,
                    function=function,
                    c_file=c_file,
                    source_rel=src_rel,
                    cflags_unit_rel=cflags_unit_rel,
                )
                _emit_score_source_result(payload, state="failed")
                raise typer.Exit(0)

    pcdump_text: str
    remote_fallback_meta: dict[str, Any] | None = None
    if use_remote_pcdump:
        stage_source_path = (
            melee_root / src_rel
            if stages_candidate_through_unit
            else None
        )
        remote_result = _run_remote_pcdump(
            source_rel=src_rel,
            compile_source_rel=cflags_unit_rel,
            host=remote_host,
            remote_script=remote_script,
            timeout=active_timeout if active_timeout is not None else 60,
            branch=remote_branch,
            no_pull=remote_no_pull,
            stage_source_path=stage_source_path,
            stage_source_label=src_rel if stage_source_path is not None else None,
        )
        remote_fallback_meta = {
            "used": True,
            "reason": remote_reason,
            "host": remote_result.host,
            "source": src_rel,
            "compile_source": cflags_unit_rel,
            "staged_source": remote_result.staged_source,
            "returncode": remote_result.returncode,
            "stage_source_sha256": remote_result.stage_source_sha256,
            "staging_ack_confirmed": remote_result.staging_ack_confirmed,
            "staging_transport": remote_result.staging_transport,
            "remote_stage_source": remote_result.remote_stage_source,
        }
        if remote_result.returncode != 0 or not remote_result.stdout.strip():
            if not quiet and remote_result.stderr:
                typer.echo(remote_result.stderr, err=True)
            score_value = 2**30
            proc = subprocess.CompletedProcess(
                remote_result.cmd,
                remote_result.returncode,
                remote_result.stdout,
                remote_result.stderr,
            )
            terminal_blocker = _remote_retained_source_terminal_blocker(
                remote_result
            )
            payload = _score_source_failure_payload(
                score_value=score_value,
                error="remote pcdump failed",
                proc=proc,
                timeout=(
                    active_timeout
                    if remote_result.returncode == 124
                    else None
                ),
                unsafe_lane=unsafe_lane,
            )
            payload["terminal_blocker"] = terminal_blocker
            payload["remote_fallback"] = remote_fallback_meta
            payload["staging_ack_confirmed"] = remote_result.staging_ack_confirmed
            payload["staging_transport"] = remote_result.staging_transport
            if remote_result.remote_stage_source is not None:
                payload["remote_stage_source"] = remote_result.remote_stage_source
            if remote_result.stage_source_sha256 is not None:
                payload["stage_source_sha256"] = remote_result.stage_source_sha256
            payload["full_unit_source"] = effective_full_unit_source
            _apply_score_source_scope(
                payload,
                function=function,
                c_file=c_file,
                source_rel=src_rel,
                cflags_unit_rel=cflags_unit_rel,
            )
            _emit_score_source_result(payload, state="failed")
            raise typer.Exit(0)
        pcdump_text = remote_result.stdout
    else:
        # Resolve wibo + compiler only once we know a local compile will run.
        wibo_path = _find_wibo()
        if wibo_path is None or not wibo_path.exists():
            typer.echo("wibo not found. Run `debug dump setup` first.", err=True)
            _emit_score_source_result(
                {"error": "wibo not found"},
                state="failed",
                emit_stdout=False,
            )
            raise typer.Exit(2)
        debug_compiler = _find_compiler_dir() / "mwcceppc_debug.exe"
        if not debug_compiler.exists():
            typer.echo(
                "patched compiler not found. Run `debug dump setup` first.",
                err=True,
            )
            _emit_score_source_result(
                {"error": "patched compiler not found"},
                state="failed",
                emit_stdout=False,
            )
            raise typer.Exit(2)

        try:
            cflags, _mw_version = _ninja_cflags_for_unit(cflags_unit_rel)
        except typer.Exit as exc:
            if exc.exit_code == 2:
                _emit_score_source_result(
                    {"error": "compiler flags unavailable"},
                    state="failed",
                    emit_stdout=False,
                )
            raise
        if cflags_unit_rel != src_rel:
            cflags = _cflags_with_same_tu_include_dir(cflags, cflags_unit_rel)

        # Compile, generating pcdump under a unique per-PID name so parallel
        # scorer runs don't race on a shared pcdump.txt. The patched DLL reads
        # MWCC_DEBUG_PCDUMP_PATH; we write the file relative to melee_root
        # (which is the subprocess cwd) and read it back from the same path.
        pcdump_name = f"pcdump_score_{os.getpid()}_{int(time.time() * 1000)}.txt"
        pcdump_path = melee_root / pcdump_name
        if pcdump_path.exists():
            pcdump_path.unlink()

        # Use unique discard .o to avoid races across parallel scorers.
        discard_o = str(mwcc_debug_scratch_path("score_source_discard", suffix=".o"))

        env = (
            _env_with_child_hang_timeout(active_timeout)
            if active_timeout is not None
            else os.environ.copy()
        )
        env["MWCC_DEBUG_PCDUMP_PATH"] = pcdump_name

        compile_timeout = active_timeout

        try:
            try:
                with _score_source_compile_source_rel(
                    source_rel=src_rel,
                    cflags_unit_rel=cflags_unit_rel,
                    melee_root=melee_root,
                    timeout=compile_timeout,
                ) as compile_source_rel:
                    args = (
                        [str(wibo_path), str(debug_compiler)]
                        + shlex.split(cflags)
                        + ["-c", compile_source_rel, "-o", discard_o]
                    )
                    proc = _run_command_with_optional_timeout(
                        args,
                        cwd=melee_root,
                        env=env,
                        timeout=compile_timeout,
                    )
            except TimeoutError as exc:
                _emit_score_source_result(
                    {"error": str(exc)},
                    state="failed",
                    emit_stdout=False,
                )
                raise
            if not pcdump_path.exists():
                if not quiet:
                    typer.echo(proc.stderr, err=True)
                # Penalty for unscoreable candidates
                score_value = 2**30
                error = "pcdump missing"
                unsafe_lane = None
                if proc.returncode == 124:
                    error = proc.stderr or _timeout_message(args, compile_timeout)
                    unsafe_lane = _score_source_unsafe_lane_payload(
                        source_rel=src_rel,
                        function=function,
                        cflags_unit_rel=cflags_unit_rel,
                        allow_unsafe=False,
                        related_source_prefixes=related_source_prefixes,
                    )
                payload = _score_source_failure_payload(
                    score_value=score_value,
                    error=error,
                    proc=proc,
                    timeout=compile_timeout if proc.returncode == 124 else None,
                    unsafe_lane=unsafe_lane,
                )
                payload["full_unit_source"] = effective_full_unit_source
                _apply_score_source_scope(
                    payload,
                    function=function,
                    c_file=c_file,
                    source_rel=src_rel,
                    cflags_unit_rel=cflags_unit_rel,
                )
                _emit_score_source_result(payload, state="failed")
                raise typer.Exit(0)

            pcdump_text = pcdump_path.read_text()
        finally:
            for compiler_product in (pcdump_path, Path(discard_o)):
                try:
                    compiler_product.unlink(missing_ok=True)
                except OSError:
                    pass

    retained_pcdump_path: Path | None = None
    pcdump_retention_error: str | None = None
    if retain_pcdump or pcdump_output is not None:
        try:
            if pcdump_output is not None:
                destination = _score_source_retained_pcdump_path(
                    source_rel=src_rel,
                    melee_root=melee_root,
                    pcdump_output=pcdump_output,
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(pcdump_text, encoding="utf-8")
                retained_pcdump_path = destination
            else:
                retained_pcdump_path = artifact_run.retain_text(
                    "pcdump/candidate.txt",
                    pcdump_text,
                )
        except (OSError, ValueError) as exc:
            pcdump_retention_error = str(exc)

    try:
        force_phys_payload = _score_source_force_phys_payload(
            pcdump_text,
            target=target,
            function=function,
        )
    except typer.Exit as exc:
        if exc.exit_code == 2:
            _emit_score_source_result(
                {"error": "invalid force-phys target"},
                state="failed",
                emit_stdout=False,
            )
        raise
    if force_phys_payload is not None:
        score_value = int(force_phys_payload.get("score", 2**30))
        force_phys_payload["full_unit_source"] = effective_full_unit_source
        _apply_score_source_scope(
            force_phys_payload,
            function=function,
            c_file=c_file,
            source_rel=src_rel,
            cflags_unit_rel=cflags_unit_rel,
        )
        if retained_pcdump_path is not None:
            force_phys_payload["pcdump_path"] = str(retained_pcdump_path)
        if pcdump_retention_error is not None:
            force_phys_payload["pcdump_retention_error"] = pcdump_retention_error
        if remote_fallback_meta is not None:
            force_phys_payload["remote_fallback"] = remote_fallback_meta
        if unsafe_lane is not None and remote_fallback_meta is not None:
            force_phys_payload["unsafe_local_pcdump_lane"] = dict(unsafe_lane)
        if checkdiff_guard:
            _apply_score_source_checkdiff_guard(
                force_phys_payload,
                c_file=c_file,
                source_rel=src_rel,
                melee_root=melee_root,
                function=function,
                timeout=active_timeout,
                deadline=command_deadline,
                full_unit_source=effective_full_unit_source,
                score_real_tree=_score_source_candidate_real_tree,
            )
        _emit_score_source_result(force_phys_payload, state="completed")
        raise typer.Exit(0)

    # Parse + score
    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        if not quiet:
            typer.echo(
                f"function {function!r} not in compiled pcdump. "
                f"Candidate may have removed/renamed it.",
                err=True,
            )
        score_value = 2**30
        payload: dict[str, Any] = {
            "score": score_value,
            "error": f"function {function!r} not in compiled pcdump",
            "full_unit_source": effective_full_unit_source,
        }
        _apply_score_source_scope(
            payload,
            function=function,
            c_file=c_file,
            source_rel=src_rel,
            cflags_unit_rel=cflags_unit_rel,
        )
        if retained_pcdump_path is not None:
            payload["pcdump_path"] = str(retained_pcdump_path)
        if pcdump_retention_error is not None:
            payload["pcdump_retention_error"] = pcdump_retention_error
        if remote_fallback_meta is not None:
            payload["remote_fallback"] = remote_fallback_meta
        if unsafe_lane is not None:
            payload["unsafe_local_pcdump_lane"] = dict(unsafe_lane)
        _emit_score_source_result(payload, state="completed")
        raise typer.Exit(0)

    if target is None:
        if not json_out:
            if not quiet:
                typer.echo(
                    "--target is required unless --json is used for retained "
                    "checkdiff evidence.",
                    err=True,
                )
            _emit_score_source_result(
                {"error": "--target is required unless --json is used"},
                state="failed",
                emit_stdout=False,
            )
            raise typer.Exit(2)
        payload: dict[str, Any] = {
            "score": 0,
            "full_unit_source": effective_full_unit_source,
        }
        _apply_score_source_scope(
            payload,
            function=function,
            c_file=c_file,
            source_rel=src_rel,
            cflags_unit_rel=cflags_unit_rel,
        )
        if retained_pcdump_path is not None:
            payload["pcdump_path"] = str(retained_pcdump_path)
        if pcdump_retention_error is not None:
            payload["pcdump_retention_error"] = pcdump_retention_error
        if remote_fallback_meta is not None:
            payload["remote_fallback"] = remote_fallback_meta
        if unsafe_lane is not None and remote_fallback_meta is not None:
            payload["unsafe_local_pcdump_lane"] = dict(unsafe_lane)
        if checkdiff_guard:
            _apply_score_source_checkdiff_guard(
                payload,
                c_file=c_file,
                source_rel=src_rel,
                melee_root=melee_root,
                function=function,
                timeout=active_timeout,
                deadline=command_deadline,
                full_unit_source=effective_full_unit_source,
                score_real_tree=_score_source_candidate_real_tree,
                update_score_from_normalized=True,
            )
        _emit_score_source_result(payload, state="completed")
        return

    events_list = parse_hook_events(pcdump_text)
    events = find_function(events_list, function)

    try:
        target_spec = _load_target_spec(target)
    except typer.Exit as exc:
        if exc.exit_code == 2:
            _emit_score_source_result(
                {"error": "invalid target spec"},
                state="failed",
                emit_stdout=False,
            )
        raise
    result = score_function(fn, target_spec, events=events)

    # Permuter expects an integer
    score_value = int(result.total)
    payload: dict[str, Any] = {
        "score": score_value,
        "full_unit_source": effective_full_unit_source,
    }
    _apply_score_source_scope(
        payload,
        function=function,
        c_file=c_file,
        source_rel=src_rel,
        cflags_unit_rel=cflags_unit_rel,
    )
    if retained_pcdump_path is not None:
        payload["pcdump_path"] = str(retained_pcdump_path)
    if pcdump_retention_error is not None:
        payload["pcdump_retention_error"] = pcdump_retention_error
    if remote_fallback_meta is not None:
        payload["remote_fallback"] = remote_fallback_meta
    if unsafe_lane is not None and remote_fallback_meta is not None:
        payload["unsafe_local_pcdump_lane"] = dict(unsafe_lane)
    if json_out:
        target_details = _score_source_target_details(result, target_spec)
        payload["target_score"] = target_details
        baseline_text = (
            expression_baseline.read_text(encoding="utf-8", errors="replace")
            if expression_baseline is not None
            else None
        )
        baseline_source_value = (
            expression_source
            if expression_source is not None
            else cflags_unit_rel
        )
        baseline_source_text, baseline_source_file = _read_expression_source(
            Path(baseline_source_value),
            melee_root=melee_root,
        )
        candidate_source_text, candidate_source_file = _read_expression_source(
            Path(src_rel),
            melee_root=melee_root,
        )
        expression_score = _score_expression_anchors(
            target_spec=target_spec,
            target_details=target_details,
            pcdump_text=pcdump_text,
            function=function,
            fn=fn,
            candidate_source_text=candidate_source_text,
            candidate_source_file=candidate_source_file,
            baseline_pcdump_text=baseline_text,
            baseline_source_text=baseline_source_text,
            baseline_source_file=baseline_source_file,
            reg_class=expression_reg_class,
        )
        if expression_score is not None:
            payload["expression_score"] = expression_score
        if checkdiff_guard:
            _apply_score_source_checkdiff_guard(
                payload,
                c_file=c_file,
                source_rel=src_rel,
                melee_root=melee_root,
                function=function,
                timeout=active_timeout,
                deadline=command_deadline,
                full_unit_source=effective_full_unit_source,
                score_real_tree=_score_source_candidate_real_tree,
            )
        _emit_score_source_result(payload, state="completed")
        return
    _emit_score_source_result(payload, state="completed")


# ---------------------------------------------------------------------------
# score-simplify-order: permuter-callable scorer for simplify-order campaigns
# ---------------------------------------------------------------------------


def _resolve_candidate_c_source(object_file: Path) -> Optional[Path]:
    """Find the candidate .c source for a given permuter-produced .o.

    Resolution order (first hit wins):
      1. $PERMUTER_C_FILE — set by decomp-permuter's CustomCommandScorer
         when the patched version is in use.
      2. <object_file>.c — convention used by our setup-simplify-order-
         scorer command: the wrapper compile.sh copies the source next
         to the .o.
      3. <object_file with .o replaced by .c> — fallback for raw permuter
         workflows where the .o was renamed.

    Returns None if no source can be found. Callers fall back to the
    pcdump-sidecar fast path or fail with a clear error.
    """
    env_path = os.environ.get("PERMUTER_C_FILE")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    sidecar = Path(str(object_file) + ".c")
    if sidecar.exists():
        return sidecar
    if object_file.suffix == ".o":
        alt = object_file.with_suffix(".c")
        if alt.exists():
            return alt
    return None


def _pcdump_for_object(
    object_file: Path,
    *,
    debug_mode: bool = False,
) -> Optional[str]:
    """Return pcdump text for a permuter-produced .o file.

    Fast path: <object_file>.pcdump.txt exists alongside the .o. This
    is the artifact the setup-simplify-order-scorer wrapper compile.sh
    drops next to the .o by setting MWCC_DEBUG_PCDUMP_PATH=<o>.pcdump.txt
    during the per-candidate compile. Zero overhead per candidate.

    Slow path: not implemented in this version. If the sidecar pcdump
    is missing, returns None and the caller surfaces a clear error
    asking the user to re-run setup-simplify-order-scorer.

    Why not implement a recompile fallback here:
      * Permuter deletes the candidate .c immediately after compile, so
        we'd have to (a) recover the source via the resolver above, and
        (b) reinvoke the debug compiler with the unit's exact cflags.
      * Both are doable but inflate per-candidate latency by ~1s
        (mwcc+wibo cold start), which materially slows the campaign.
      * The sidecar approach demands a small setup-time wrapper script,
        which we already need to generate anyway for the scorer to be
        usable as a permuter `[scorer].command`.
      * Adding the recompile path later is one well-scoped change in
        this function; doing it both now and later means we never
        exercise the fast-path code that the production setup uses.
    """
    sidecar = Path(str(object_file) + ".pcdump.txt")
    if sidecar.exists():
        try:
            return sidecar.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            if debug_mode:
                print(
                    f"[score-simplify-order] failed to read pcdump sidecar "
                    f"{sidecar}: {e}",
                    file=sys.stderr,
                )
            return None
    return None


def _resolve_permuter_scorer_target(target: Path, object_file: Path) -> Path:
    """Resolve portable scorer target paths against the candidate object tree."""
    target = target.expanduser()
    if target.is_absolute() or target.exists():
        return target

    object_path = object_file.expanduser()
    if not object_path.is_absolute():
        object_path = (Path.cwd() / object_path).resolve()
    else:
        object_path = object_path.resolve()
    parts = object_path.parts
    if "nonmatchings" not in parts:
        return target
    nonmatchings_index = parts.index("nonmatchings")
    if nonmatchings_index + 1 >= len(parts):
        return target

    perm_root = Path(*parts[:nonmatchings_index])
    function_dir = Path(*parts[:nonmatchings_index + 2])
    candidates: list[Path] = []
    if target.parts and target.parts[0] == "nonmatchings":
        candidates.append(perm_root / target)
    candidates.append(function_dir / target)
    candidates.append(function_dir / target.name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else target



@target_app.command(name="score-force-phys")
def score_force_phys(
    object_file: Annotated[
        Path,
        typer.Argument(
            help="Path to the candidate .o file. Reads sibling <object>.pcdump.txt.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to score."),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help=(
                "Path to force-phys target YAML generated by "
                "setup-simplify-order-scorer --scorer-mode force-phys."
            ),
        ),
    ],
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit score breakdown as JSON."),
    ] = False,
    breakdown: Annotated[
        bool,
        typer.Option("--breakdown", help="Print human-readable breakdown."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Emit diagnostics to stderr."),
    ] = False,
) -> None:
    """Permuter scorer: lex-encoded force-phys assignment hits.

    This is the colorgraph-DISPENSE companion to score-simplify-order. It
    scores candidate pcdumps by whether target ig_idx values actually receive
    their requested physical registers, so candidates remain rankable even
    when simplify-order rows are all physical placeholders (-1).
    """
    import json as _json

    from ...mwcc_debug.simplify_order_scoring import (
        LEX_BIG,
        STRUCTURAL_REJECTION_SCORE,
        extract_signature,
        find_coalesced_targets,
    )
    from ...mwcc_debug.simplify_search import (
        precolor_distance,
        score_force_phys_assignment,
    )

    PENALTY_INF = 10**9

    def _emit_sentinel(reason: str) -> None:
        if debug:
            print(f"[score-force-phys] {reason}", file=sys.stderr)
        if json_out:
            print(_json.dumps({"score": PENALTY_INF, "error": reason}))
        else:
            print(PENALTY_INF)
        raise typer.Exit(0)

    if not object_file.exists():
        _emit_sentinel(f"object file not found: {object_file}")
    target = _resolve_permuter_scorer_target(target, object_file)

    try:
        import yaml  # type: ignore

        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        typer.echo(f"target spec file not found: {target}", err=True)
        raise typer.Exit(2)
    except Exception as exc:
        typer.echo(f"target spec error: {exc}", err=True)
        raise typer.Exit(2)
    if not isinstance(data, dict):
        typer.echo(f"target spec {target} must be a mapping", err=True)
        raise typer.Exit(2)
    spec_function = data.get("function")
    if spec_function != function:
        typer.echo(
            f"target spec function mismatch: spec.function={spec_function!r} "
            f"!= --function={function!r}",
            err=True,
        )
        raise typer.Exit(2)
    class_id = data.get("class_id", 0)
    if not isinstance(class_id, int) or isinstance(class_id, bool):
        typer.echo("target spec class_id must be an integer", err=True)
        raise typer.Exit(2)
    raw_baseline = data.get("baseline_dump")
    if not isinstance(raw_baseline, str) or not raw_baseline:
        typer.echo("target spec missing baseline_dump", err=True)
        raise typer.Exit(2)
    baseline_dump = Path(raw_baseline).expanduser()
    if not baseline_dump.is_absolute():
        baseline_dump = (target.parent / baseline_dump).resolve()
    raw_force_phys = data.get("force_phys")
    if not isinstance(raw_force_phys, dict) or not raw_force_phys:
        typer.echo("target spec missing non-empty force_phys mapping", err=True)
        raise typer.Exit(2)
    force_phys_map: dict[int, int] = {}
    for raw_ig, raw_phys in raw_force_phys.items():
        if (
            not isinstance(raw_ig, int)
            or isinstance(raw_ig, bool)
            or not isinstance(raw_phys, int)
            or isinstance(raw_phys, bool)
        ):
            typer.echo("force_phys must map integer ig_idx to integer phys", err=True)
            raise typer.Exit(2)
        force_phys_map[raw_ig] = raw_phys
    coalesce_preservation = data.get("coalesce_preservation", True)
    if not isinstance(coalesce_preservation, bool):
        typer.echo("coalesce_preservation must be true/false", err=True)
        raise typer.Exit(2)

    try:
        baseline_text = baseline_dump.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"failed to read baseline_dump {baseline_dump}: {exc}", err=True)
        raise typer.Exit(2)
    baseline = extract_signature(baseline_text, function, class_id=class_id)
    if baseline is None:
        typer.echo(
            f"baseline pcdump {baseline_dump} does not contain {function!r}",
            err=True,
        )
        raise typer.Exit(2)

    pcdump_text = _pcdump_for_object(object_file, debug_mode=debug)
    if pcdump_text is None:
        _emit_sentinel(
            f"pcdump sidecar missing for {object_file}; expected at "
            f"{object_file}.pcdump.txt"
        )

    candidate = extract_signature(pcdump_text, function, class_id=class_id)
    if candidate is None:
        _emit_sentinel(f"function {function!r} not in candidate pcdump")

    candidate_events = find_function(parse_hook_events(pcdump_text), function)
    coalesced_targets: set[int] = set()
    if coalesce_preservation and candidate_events is not None:
        coalesced_targets = find_coalesced_targets(
            candidate_events,
            targets=set(force_phys_map),
            class_id=class_id,
        )
    dist = precolor_distance(baseline, candidate)
    force_score = score_force_phys_assignment(baseline, candidate, force_phys_map)
    missed = len(force_phys_map) - force_score.common_prefix_length
    structural_rejection = bool(coalesced_targets)
    score = (
        STRUCTURAL_REJECTION_SCORE
        if structural_rejection
        else missed * LEX_BIG + dist.total
    )
    if json_out:
        print(_json.dumps({
            "score": score,
            "function": function,
            "targeted": len(force_phys_map),
            "force_phys_hits": force_score.common_prefix_length,
            "baseline_hits": force_score.baseline_common_prefix_length,
            "matched_igs": list(force_score.observed_prefix),
            "target_igs": list(force_score.target_prefix),
            "precolor_distance": {
                "total": dist.total,
                "ig_added": dist.ig_added,
                "ig_removed": dist.ig_removed,
                "coalesce_added": dist.coalesce_added,
                "coalesce_removed": dist.coalesce_removed,
                "spill_added": dist.spill_added,
                "spill_removed": dist.spill_removed,
            },
            "structural_rejection": structural_rejection,
            "coalesced_targets": sorted(coalesced_targets),
        }))
        return
    if breakdown:
        print(f"Function:          {function}")
        print(f"Score:             {score}")
        print(f"Target force-phys: {force_phys_map}")
        print(
            f"Force-phys hits:   {force_score.common_prefix_length} / "
            f"{len(force_phys_map)}"
        )
        print(f"Matched ig_idx:    {list(force_score.observed_prefix)}")
        print(f"Precolor distance: {dist.total}")
        if structural_rejection:
            print(f"Coalesce preservation: REJECTED {sorted(coalesced_targets)}")
        return
    print(score)


@target_app.command(name="score-simplify-order")
def score_simplify_order(
    object_file: Annotated[
        Path,
        typer.Argument(
            help="Path to the candidate .o file (positional). When "
                 "invoked from decomp-permuter's CustomCommandScorer, "
                 "this is the .o permuter just compiled.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function name to score within the candidate's TU "
                 "(required).",
        ),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help="Path to a simplify-order target YAML spec. See "
                 "SimplifyOrderTargetSpec in "
                 "src/mwcc_debug/simplify_order_scoring.py for the schema.",
        ),
    ],
    json_out: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit the score + breakdown as a single JSON object. "
                 "When unset, prints only the integer score (permuter "
                 "contract).",
        ),
    ] = False,
    breakdown: Annotated[
        bool,
        typer.Option(
            "--breakdown",
            help="Print human-readable score breakdown to stdout. "
                 "Implies non-permuter-contract output.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Emit diagnostic output to stderr (does not affect "
                 "stdout, so permuter still parses the integer).",
        ),
    ] = False,
    strict_polarity: Annotated[
        bool,
        typer.Option(
            "--strict-polarity",
            help=(
                "Exit non-zero when the polarity check is WRONG_POLARITY. "
                "Use in screening scripts to refuse high-volatile-target "
                "campaigns before they burn cloud compute. UNCERTAIN polarity "
                "is allowed in strict mode — only the structurally-impossible "
                "case is rejected."
            ),
        ),
    ] = False,
) -> None:
    """Permuter scorer: lex-encoded simplify-order + precolor distance.

    Outputs a single integer to stdout (lower = better, 0 = perfect).
    Designed to be invoked by decomp-permuter as a `[scorer].command`
    in settings.toml — see `debug permute setup-simplify-order-scorer`
    for the workflow that wires this up.

    The candidate's pcdump is read from the sibling `<object_file>.pcdump.txt`
    file that the wrapper compile.sh deposits during compilation. If that
    sidecar is missing the scorer emits the sentinel PENALTY_INF score so
    permuter treats the iteration as a compile failure rather than crashing.
    """
    # --strict-polarity implies --breakdown: the polarity diagnostic must
    # run for the strict exit to fire. Without this implication, passing
    # --strict-polarity alone would be a silent no-op.
    if strict_polarity:
        breakdown = True

    import json as _json

    from ...mwcc_debug.simplify_order_scoring import (
        Polarity,
        SimplifyOrderSpecError,
        classify_polarity,
        compute_lex_score,
        extract_signature,
        load_simplify_order_target_spec,
    )

    # Permuter's CustomCommandScorer treats PENALTY_INF (=10**9) as
    # "iteration is bad". We use the same value for any pre-score failure
    # mode (missing pcdump, missing function, malformed spec) so permuter
    # discards the iteration cleanly.
    PENALTY_INF = 10**9

    def _emit_sentinel(reason: str) -> None:
        if debug:
            print(f"[score-simplify-order] {reason}", file=sys.stderr)
        if json_out:
            print(_json.dumps({"score": PENALTY_INF, "error": reason}))
        else:
            print(PENALTY_INF)
        raise typer.Exit(0)

    if not object_file.exists():
        _emit_sentinel(f"object file not found: {object_file}")
        return  # for typing — Exit() raises
    target = _resolve_permuter_scorer_target(target, object_file)

    try:
        spec = load_simplify_order_target_spec(target)
    except SimplifyOrderSpecError as e:
        # Spec-level errors are user errors, not iteration errors. Print
        # to stderr with a high exit code so permuter logs them visibly
        # but DON'T print PENALTY_INF to stdout (which would be parsed
        # silently and never reported).
        typer.echo(f"target spec error: {e}", err=True)
        raise typer.Exit(2)

    if spec.function != function:
        typer.echo(
            f"target spec function mismatch: "
            f"spec.function={spec.function!r} != --function={function!r}",
            err=True,
        )
        raise typer.Exit(2)

    # Load the baseline signature once per call (cheap — small pcdump).
    try:
        baseline_text = spec.baseline_dump.read_text(encoding="utf-8")
    except OSError as e:
        typer.echo(
            f"failed to read baseline_dump {spec.baseline_dump}: {e}",
            err=True,
        )
        raise typer.Exit(2)
    baseline = extract_signature(
        baseline_text, function, class_id=spec.class_id,
    )
    if baseline is None:
        typer.echo(
            f"baseline pcdump {spec.baseline_dump} does not contain "
            f"function {function!r}",
            err=True,
        )
        raise typer.Exit(2)

    # Per-candidate: resolve pcdump for the .o.
    pcdump_text = _pcdump_for_object(object_file, debug_mode=debug)
    if pcdump_text is None:
        _emit_sentinel(
            f"pcdump sidecar missing for {object_file}; expected at "
            f"{object_file}.pcdump.txt. The wrapper compile.sh deposits "
            f"this file during each candidate compile."
        )
        return

    candidate = extract_signature(
        pcdump_text, function, class_id=spec.class_id,
    )
    if candidate is None:
        _emit_sentinel(
            f"function {function!r} not in candidate pcdump (codegen "
            f"path may have eliminated it)"
        )
        return

    candidate_events = find_function(parse_hook_events(pcdump_text), function)

    result = compute_lex_score(
        baseline,
        candidate,
        spec.simplify_order_target,
        candidate_events=candidate_events,
        spec=spec,
    )

    if json_out:
        payload = {
            "score": result.score,
            "function": function,
            "target_len": len(spec.simplify_order_target),
            "common_prefix_length": result.simplify_score.common_prefix_length,
            "missed_prefix": (
                len(spec.simplify_order_target)
                - result.simplify_score.common_prefix_length
            ),
            "precolor_distance": {
                "total": result.precolor_distance.total,
                "ig_added": result.precolor_distance.ig_added,
                "ig_removed": result.precolor_distance.ig_removed,
                "coalesce_added": result.precolor_distance.coalesce_added,
                "coalesce_removed": result.precolor_distance.coalesce_removed,
                "spill_added": result.precolor_distance.spill_added,
                "spill_removed": result.precolor_distance.spill_removed,
            },
            "observed_prefix": list(result.simplify_score.observed_prefix),
            "target_prefix": list(result.simplify_score.target_prefix),
        }
        print(_json.dumps(payload))
        return

    if breakdown:
        print(f"Function:          {function}")
        print(f"Score:             {result.score}")

        # Decide which mode we're in for rendering prefix vs suffix lines.
        is_late_mode = bool(spec.simplify_order_target_late)

        if is_late_mode:
            target_late = spec.simplify_order_target_late
            # Derive the observed suffix by slicing the last N elements of
            # the candidate's filtered simplify order, where N = len(target_late).
            n_late = len(target_late)
            observed_suffix = list(candidate.simplify_order[-n_late:]) if n_late else []
            print(f"Target suffix:     {list(target_late)}")
            print(f"Observed suffix:   {observed_suffix}")
            print(
                f"Common suffix:     "
                f"{result.common_suffix_length} / {n_late}"
            )
        else:
            print(f"Target prefix:     {list(result.simplify_score.target_prefix)}")
            print(
                f"Observed prefix:   {list(result.simplify_score.observed_prefix)}"
            )
            print(
                f"Common prefix:     "
                f"{result.simplify_score.common_prefix_length} / "
                f"{len(spec.simplify_order_target)}"
            )

        d = result.precolor_distance
        print(f"Precolor distance: {d.total}")
        print(
            f"  IG       +{d.ig_added} -{d.ig_removed}\n"
            f"  Coalesce +{d.coalesce_added} -{d.coalesce_removed}\n"
            f"  Spill    +{d.spill_added} -{d.spill_removed}"
        )
        # Coalesce-preservation diagnostic (deferred debt #19).
        # Only runs when force_phys is present (the check needs targets).
        if spec.force_phys:
            print("")  # separator
            if not spec.coalesce_preservation:
                print("Coalesce preservation:    DISABLED")
                print(
                    "  Constraint disabled via coalesce_preservation: false. "
                    "Candidates that coalesce target ig_idx values are NOT "
                    "rejected."
                )
            elif result.structural_rejection:
                aliased = ",".join(str(x) for x in sorted(result.coalesced_targets))
                print("Coalesce preservation:    REJECTED")
                print(
                    f"  Target ig_idx [{aliased}] coalesced as alias(es) into "
                    f"another root. The candidate's allocator graph has fewer "
                    f"independent nodes than the force_phys mapping presupposes. "
                    f"Rejected with score={result.score}."
                )
            else:
                print("Coalesce preservation:    ALL TARGETS INDEPENDENT")

        # Polarity diagnosis (deferred debt #20 pre-flight check).
        # Only runs when the target.yaml provides force_phys; otherwise
        # the screening agent didn't ask for the check and we stay quiet.
        if spec.force_phys:
            target_position = "late" if is_late_mode else "first"
            polarity = classify_polarity(spec.force_phys, target_position=target_position)
            print("")  # blank line separator
            if polarity is Polarity.WRONG_POLARITY:
                print("Polarity check:    WRONG POLARITY")
                if target_position == "first":
                    print(
                        "  At least one target physical is in the high-volatile "
                        "range (r10-r12). MWCC's volatile dispense is lowest-"
                        "first, so target ig_idx values at simplify positions "
                        "0/1/... get r3/r4/... not r10-r12. --want-first is the "
                        "wrong polarity for this target."
                    )
                    print(
                        "  Recommend: switch to `--want-late N,M` (Phase 3 of "
                        "deferred debt #20, shipped). The target ig_idx values "
                        "need to be at the END of simplify order so the lower "
                        "volatiles are consumed first."
                    )
                else:  # target_position == "late"
                    print(
                        "  At least one target physical is in the top "
                        "non-volatile range (r28-r31) or is r3. Those are "
                        "dispensed FIRST by MWCC's allocator, so target "
                        "ig_idx values at the END of simplify order won't "
                        "get them. --want-late is the wrong polarity for "
                        "this target."
                    )
                    print(
                        "  Recommend: switch to `--want-first N,M`. The "
                        "target ig_idx values should be at the START of "
                        "simplify order."
                    )
            elif polarity is Polarity.UNCERTAIN:
                print("Polarity check:    UNCERTAIN")
                print(
                    "  At least one target physical is mid-volatile (r4-r9). "
                    "--want-first may or may not reach the target depending "
                    "on interference state at dispense time. If campaign "
                    "produces prefix hits but no match% progress, consider "
                    "whether dispense direction is the issue."
                )
            elif polarity is Polarity.SAFE:
                print("Polarity check:    SAFE")
            else:
                raise ValueError(
                    f"unhandled Polarity value: {polarity!r} "
                    f"(this branch needs updating when Polarity is extended)"
                )

            if strict_polarity and polarity is Polarity.WRONG_POLARITY:
                raise typer.Exit(code=2)
        return

    # Permuter contract: single integer on stdout.
    print(result.score)
