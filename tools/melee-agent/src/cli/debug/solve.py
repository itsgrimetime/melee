"""`debug solve ...` -- inverse-coloring solver command group.

Carved out of cli/debug/__init__.py. Heavy algorithms live in
src/mwcc_debug/{node_set_split,allocator_ceiling,colorgraph_parser}.py; this
module is the typer surface + orchestration/output helpers.

Shared helpers (and module-level names the tests patch on the cli.debug
package) still live in cli/debug/__init__.py. They are reached via call-time
(deferred) ``from src.cli.debug import ...`` imports inside the function
bodies -- a load-time import would create a cycle (__init__ imports this
module) and would also break ``monkeypatch.setattr(debug_cli, ...)``
semantics, since the patched name must resolve against __init__ at call time.
Names imported plainly below (e.g. ``local_safety``, ``time``) are module
singletons whose patched *attributes* propagate, so they are safe at load time.
"""
from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import re
import shlex
import signal
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    Iterator,
    Mapping,
    NoReturn,
    Optional,
)

import typer

from ...mwcc_debug import local_safety

if TYPE_CHECKING:  # annotation-only; the runtime object lives in cli.debug
    from src.cli.debug import _RemotePcdumpResult  # noqa: F401
from ...mwcc_debug.source_patch import (
    find_function as find_source_function,
)
from ...mwcc_debug.source_patch import (
    transfer_candidate,
)

solve_app = typer.Typer(
    help="Inverse-coloring solver: surrogate-checked, §1.5-filtered C-move "
         "worksheets for register-only residuals."
)


__all__ = [
    "_NODE_SET_UNSAFE_SOURCE_CONFIDENCES",
    "_NodeSetSplitGenerationTimeout",
    "_NodeSetSplitPcdumpBackendFailure",
    "_NodeSetSplitPcdumpBackendResult",
    "_derive_node_set_delta_payload",
    "_emit_node_set_split_summary",
    "_node_set_delta_safe_source_attr",
    "_node_set_delta_source_action",
    "_node_set_generation_result_parts",
    "_node_set_split_blocked_summary",
    "_node_set_split_candidate_dir",
    "_node_set_split_candidate_source_path",
    "_node_set_split_changed_text",
    "_node_set_split_class_arg",
    "_node_set_split_cli_path",
    "_node_set_split_compile_signature_and_pcdump_backend",
    "_node_set_split_default_summary_path",
    "_node_set_split_force_phys_from_requests",
    "_node_set_split_load_generated_manifest",
    "_node_set_split_load_resume_summary",
    "_node_set_split_manifest_error",
    "_node_set_split_manifest_path_value",
    "_node_set_split_pending_candidate_ids",
    "_node_set_split_pending_candidate_records",
    "_node_set_split_probe_mentions_target",
    "_node_set_split_read_generated_manifest",
    "_node_set_split_remaining_timeout",
    "_node_set_split_remote_metadata",
    "_node_set_split_request_from_json",
    "_node_set_split_request_json",
    "_node_set_split_request_var_names",
    "_node_set_split_resume_command",
    "_node_set_split_resume_manifest_path",
    "_node_set_split_row_needs_resume",
    "_node_set_split_same_tu_compile_path",
    "_node_set_split_source_hunk",
    "_node_set_split_source_rel",
    "_node_set_split_summary_path",
    "_node_set_split_text_sha256",
    "_node_set_split_touched_ranges_from_json",
    "_node_set_split_write_generated_manifest",
    "_node_set_split_write_summary",
    "_parse_node_set_generated_local_source_json",
    "_print_solve_node_set_delta",
    "_register_number_from_name",
    "_register_tiebreak_force_phys_vector_targets",
    "_retain_node_set_split_failed_source",
    "_retain_node_set_split_pcdump",
    "_retain_node_set_split_source",
    "_run_node_set_split_generation_with_watchdog",
    "_sanitize_force_vector_verify_payload",
    "_solve_abstain_payload",
    "_solve_conflict_ig_idx",
    "_solve_force_vector_diagnostics",
    "_solver_probe_ctx_factory",
    "solve_allocator_ceiling_cmd",
    "solve_app",
    "solve_coloring_cmd",
    "solve_node_set_split_cmd",
]


def _register_tiebreak_force_phys_vector_targets(
    ig,
    force_phys: Mapping[int, int] | Mapping[str, int],
    *,
    class_id: int,
) -> list[dict[str, Any]]:
    from src.cli.debug import _select_order_int_mapping
    prefix = "f" if class_id == 1 else "r"
    targets: list[dict[str, Any]] = []
    for ig_idx, phys in sorted(_select_order_int_mapping(force_phys).items()):
        node = ig.nodes.get(ig_idx)
        targets.append({
            "ig_idx": ig_idx,
            "target_reg": phys,
            "target_reg_name": f"{prefix}{phys}",
            "already_target": (
                node is not None and getattr(node, "observed_reg", None) == phys
            ),
        })
    return targets




def _solver_probe_ctx_factory(ig, report, phys_target):
    """Build the live probe_ctx_fn from PRODUCTION derivations (codex blocker
    3): first-def opcode from the explain_virtuals report (li/lis -> constant,
    L2a), caller-visibility from the A2 provenance-KIND of the RAW source
    attribution (L2b), window residual from the function-level classifier
    (L2c), and the L1 strict-subset survival rule — all inside
    probe.derive_probe_context. Unit-tested directly; never hardcoded.

    NOTE (Amendment A2): the caller-visibility signal is the RAW
    SourceAttribution's provenance KIND (via source_attr_of), NOT the flattened
    `source_object_of` string — `source_object is not None` was the dead L2(b)
    branch this amendment closed. The factory therefore feeds
    derive_probe_context the post-A2 `source=` argument, matching the exact
    derivation the calibration gate's build_probe_ctx_fn uses on frozen
    artifacts."""
    from src.search.solver import probe as solver_probe

    win_res = solver_probe.is_window_order_residual(ig, phys_target)

    def probe_ctx_fn(p):
        return solver_probe.derive_probe_context(
            p, ig,
            first_def_opcode=solver_probe.first_def_opcode_of(report, p.target_ig),
            source=solver_probe.source_attr_of(report, p.target_ig),
            window_residual=win_res)
    return probe_ctx_fn




_NODE_SET_UNSAFE_SOURCE_CONFIDENCES = {
    "low-confidence",
    "ambiguous",
    "ambiguous-nested",
    "unsupported",
    "rejected",
}


def _node_set_delta_safe_source_attr(source) -> object | None:
    if source is None:
        return None
    confidence = getattr(source, "confidence", None)
    if confidence in _NODE_SET_UNSAFE_SOURCE_CONFIDENCES:
        return None
    return source




def _node_set_delta_source_action(entry: dict) -> str:
    source = entry.get("source") if isinstance(entry.get("source"), dict) else None
    live_range = entry.get("live_range")
    if source:
        loc = ""
        if source.get("source_file") and source.get("source_line") is not None:
            loc = f" at {source['source_file']}:{source['source_line']}"
        expr = source.get("expression") or source.get("name") or "the attributed value"
        return (
            f"Introduce a named temp/alias for {expr}{loc} before its first "
            "use, then keep the original value live until its last use so the "
            "allocator creates a separate virtual for one target register."
        )
    if live_range:
        return (
            f"Split ig{entry['target_ig']}'s live range around pcode "
            f"{live_range[0]}..{live_range[1]} with a named temp/alias; "
            "re-run `debug inspect explain-virtual` to bind it to source."
        )
    return (
        f"Introduce a named temp/alias for ig{entry['target_ig']}'s value near "
        "its first pcode occurrence; re-run `debug inspect explain-virtual` "
        "to pin the exact source line."
    )




def _solve_conflict_ig_idx(conflict) -> int | None:
    if not isinstance(conflict, dict):
        return None
    try:
        return int(conflict["ig_idx"])
    except (KeyError, TypeError, ValueError):
        return None




def _derive_node_set_delta_payload(
    *,
    function: str,
    class_id: int,
    ig,
    phys_target: dict[int, int],
    phys_conflicts: list[dict],
    report,
    coupled_residual: dict | None = None,
) -> dict | None:
    from src.cli.debug import _solve_source_attribution_dict
    target_igs = set(int(ig_idx) for ig_idx in phys_target)
    for conflict in phys_conflicts:
        conflict_ig = _solve_conflict_ig_idx(conflict)
        if conflict_ig is not None:
            target_igs.add(conflict_ig)
    if not target_igs:
        return None

    from src.mwcc_debug import tiebreak as tb

    prefix = tb.register_prefix(class_id)
    virtuals_by_ig = {}
    if report is not None:
        for attr in getattr(report, "virtuals", ()):
            if attr.ig_idx is not None:
                virtuals_by_ig[int(attr.ig_idx)] = attr

    entries: list[dict] = []
    for target_ig in sorted(target_igs):
        desired_regs = []
        if target_ig in phys_target:
            desired_regs.append(int(phys_target[target_ig]))
        conflicts = [
            conflict for conflict in phys_conflicts
            if _solve_conflict_ig_idx(conflict) == target_ig
        ]
        for conflict in conflicts:
            for key in ("existing_phys", "conflicting_phys"):
                value = conflict.get(key)
                if isinstance(value, int) and value not in desired_regs:
                    desired_regs.append(value)
        node = ig.nodes.get(target_ig) if ig is not None else None
        attr = virtuals_by_ig.get(target_ig)
        safe_source = _node_set_delta_safe_source_attr(
            attr.source if attr is not None else None
        )
        source = _solve_source_attribution_dict(safe_source)
        live_range = (
            list(attr.live_range)
            if attr is not None and attr.live_range is not None else None
        )
        entry = {
            "target_ig": target_ig,
            "current_virtual": f"{prefix}{target_ig}",
            "desired_registers": [f"{prefix}{reg}" for reg in sorted(desired_regs)],
            "current_register": (
                f"{prefix}{node.observed_reg}"
                if node is not None and node.observed_reg >= 0 else None
            ),
            "current_neighbors": (
                sorted(node.neighbors)
                if node is not None else []
            ),
            "current_degree": (
                len(node.neighbors)
                if node is not None else None
            ),
            "live_range": live_range,
            "source": source,
            "conflicts": conflicts,
            "missing_virtual": (
                f"target coloring requires splitting ig{target_ig} into a "
                "distinct same-class virtual for at least one desired register"
            ),
        }
        entry["source_action"] = _node_set_delta_source_action(entry)
        entries.append(entry)

    payload = {
        "kind": "node-set-delta",
        "blocker": "structurally-different-virtual",
        "function": function,
        "class_id": class_id,
        "register_prefix": prefix,
        "current_ig_node_count": len(ig.nodes) if ig is not None else None,
        "missing_virtuals": entries,
        # #714: solve coloring only DIAGNOSES the structurally-different-virtual
        # set; the ranked insert-alias / per-loop-split / decl-order-split /
        # anti-coalesce recipes are enumerated by the node-set-split solver.
        # Point the caller at it explicitly so the two-step flow is discoverable
        # (the issue author got stuck reaching for `search directed` -> no_roles).
        "next_step": (
            "enumerate ranked split recipes (insert-alias / per-loop-split / "
            "decl-order-split / anti-coalesce): write this --json payload to a "
            "file FILE and run `melee-agent debug solve node-set-split "
            "--node-set-delta FILE` (add --coupled for interdependent multi-ig "
            "rotations)"
        ),
    }
    # #705: honest coupling summary on the FPR node-set fallback (omitted on the
    # GPR/register-only path where no coupling summary is computed).
    if coupled_residual is not None:
        payload["coupled_residual"] = coupled_residual
    return payload




def _solve_abstain_payload(function: str, class_id: int, res) -> dict:
    payload = {
        "function": function,
        "class_id": class_id,
        "exit_code": res.exit_code,
        "reason": res.reason,
    }
    if res.node_set_delta is not None:
        payload["node_set_delta"] = res.node_set_delta
    diagnostics = getattr(res, "solver_diagnostics", None)
    if isinstance(diagnostics, Mapping):
        payload.update(diagnostics)
    return payload




def _solve_force_vector_diagnostics(
    *,
    class_id: int,
    phys_target: Mapping[int, int],
    force_vector_probe: Any,
    natural_pcdump: Path | None,
) -> dict[str, Any] | None:
    if not phys_target and not isinstance(force_vector_probe, Mapping):
        return None
    prefix = "f" if class_id == 1 else "r"
    ordered = sorted((int(ig), int(phys)) for ig, phys in phys_target.items())
    force_phys = {str(ig): phys for ig, phys in ordered}
    payload: dict[str, Any] = {
        "force_phys": force_phys,
        "force_phys_csv": ",".join(
            f"{class_id}:{ig}:{phys}" for ig, phys in ordered
        ),
        "force_vector": ",".join(
            f"class{class_id}:ig{ig}:phys={prefix}{phys}"
            for ig, phys in ordered
        ),
    }
    if natural_pcdump is not None:
        payload["natural_pcdump"] = str(natural_pcdump)
    if isinstance(force_vector_probe, Mapping):
        verify = _sanitize_force_vector_verify_payload(force_vector_probe)
        verify.setdefault("ran", True)
        payload["force_vector_verify"] = verify
        union = verify.get("union")
        payload["force_vector_probe_summary"] = {
            "ran": verify.get("ran") is True,
            "probe_count": verify.get("probe_count"),
            "union_status": (
                union.get("status") if isinstance(union, Mapping) else None
            ),
        }
    return payload




def _sanitize_force_vector_verify_payload(
    force_vector_probe: Mapping[str, Any],
) -> dict[str, Any]:
    def sanitize_probe(probe: Any) -> Any:
        if not isinstance(probe, Mapping):
            return probe
        sanitized = dict(probe)
        if sanitized.get("retained_pcdump") is not True:
            sanitized.pop("pcdump", None)
            sanitized.pop("forced_pcdump", None)
        return sanitized

    verify = dict(force_vector_probe)
    if isinstance(verify.get("union"), Mapping):
        verify["union"] = sanitize_probe(verify["union"])
    probes = verify.get("probes")
    if isinstance(probes, list):
        verify["probes"] = [sanitize_probe(probe) for probe in probes]
    return verify




def _print_solve_node_set_delta(delta: dict) -> None:
    typer.echo("node-set delta:")
    blocker = delta.get("blocker")
    if blocker:
        typer.echo(f"  blocker: {blocker}")
    for entry in delta.get("missing_virtuals", []):
        if not isinstance(entry, dict):
            continue
        desired = ",".join(entry.get("desired_registers") or [])
        current = entry.get("current_register") or "?"
        target_ig = entry.get("target_ig")
        typer.echo(
            f"  - ig{target_ig}: current {current}; target wants "
            f"{desired or '?'}"
        )
        missing = entry.get("missing_virtual")
        if missing:
            typer.echo(f"    missing: {missing}")
        action = entry.get("source_action")
        if action:
            typer.echo(f"    source action: {action}")
    # #714: make the recipe-generation step discoverable from solve coloring.
    next_step = delta.get("next_step")
    if next_step:
        typer.echo(f"  next step: {next_step}")




@solve_app.command("coloring")
def solve_coloring_cmd(
    function: Annotated[str, typer.Option("--function", "-f")],
    register_class: Annotated[str, typer.Option(
        "--class", help="Register class: gpr (default) or fpr.")] = "gpr",
    pcdump: Annotated[Optional[Path], typer.Option("--pcdump")] = None,
    checkdiff_json: Annotated[
        Optional[Path],
        typer.Option(
            "--checkdiff-json",
            help=(
                "Existing `tools/checkdiff.py <function> --format json` "
                "payload. When used with --pcdump, solve-coloring derives "
                "inputs from those explicit artifacts instead of compiling a "
                "fresh natural baseline."
            ),
        ),
    ] = None,
    max_perturb: Annotated[int, typer.Option("--max-perturb")] = 2,
    frontier: Annotated[int, typer.Option("--frontier")] = 32,
    kinds: Annotated[str, typer.Option(
        "--kinds", help="Enumerated kinds (advertised vocabulary; 'edge' "
        "expands to edge-add+edge-remove).")] = "node-add,edge,order",
    experimental_kinds: Annotated[str, typer.Option(
        "--experimental-kinds", help="e.g. coalesce (spec §1d).")] = "",
    catalog_dir: Annotated[Optional[Path], typer.Option(
        "--catalog-dir",
        help="Lever catalog dir (default: the tracked D0 catalog).")] = None,
    force_vector_probes: Annotated[
        bool,
        typer.Option(
            "--force-vector-probes/--no-force-vector-probes",
            help=(
                "Run singleton and prefix force-vector diagnostic probes after "
                "the union verify. Off by default; solve coloring only needs "
                "the union result for reachability."
            ),
        ),
    ] = False,
    force_vector_timeout: Annotated[
        Optional[float],
        typer.Option(
            "--force-vector-timeout",
            help=(
                "Per-probe wall-clock timeout in seconds for force-vector "
                "auto-verify. Defaults to MWCC_DEBUG_FORCE_VECTOR_TIMEOUT, "
                "MWCC_DEBUG_HANG_TIMEOUT, or 300s."
            ),
        ),
    ] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inverse register coloring: enumerate §1.5-filtered node-set/content
    perturbations, predict their coloring with the SELECT surrogate, map
    winners to C moves, emit a ranked worksheet. Exit 0=actionable candidate,
    3=abstain, 4=budgeted no-candidate (incl. window-order)."""
    from src.cli.debug import (
        DEFAULT_MELEE_ROOT,
        _register_tiebreak_window_order_fallback,
        _run_solve_coloring,
    )

    from ...mwcc_debug import tiebreak as tb

    class_id = tb.parse_register_class(register_class)
    requested_kinds = [k.strip() for k in kinds.split(",") if k.strip()]
    fpr_order_fallback_enabled = class_id == 1 and requested_kinds == ["order"]
    resolved_catalog = catalog_dir or (
        DEFAULT_MELEE_ROOT / "docs" / "superpowers" / "lever-catalog")
    res = _run_solve_coloring(
        function=function, class_id=class_id,
        pcdump=pcdump, checkdiff_json=checkdiff_json,
        max_perturb=max_perturb, frontier=frontier,
        kinds=requested_kinds,
        experimental_kinds=[k.strip() for k in experimental_kinds.split(",")
                            if k.strip()],
        catalog_dir=resolved_catalog,
        force_vector_probes=force_vector_probes,
        force_vector_timeout=force_vector_timeout,
        retain_force_vector_pcdumps=json_out and force_vector_probes,
        allow_unreachable_order=fpr_order_fallback_enabled)
    fallback: dict | None = None
    if (
        fpr_order_fallback_enabled
        and res.worksheet is not None
        and not res.worksheet.candidates
        and not res.worksheet.tooling_leads
        and not res.worksheet.window_order
    ):
        fallback = _register_tiebreak_window_order_fallback(
            function=function,
            class_id=class_id,
            pcdump_path=pcdump,
            allow_auto_pcdump=pcdump is None,
            pcdump_source="explicit" if pcdump is not None else None,
        )
    fallback_leads = (
        fallback.get("leads", [])
        if isinstance(fallback, dict) else []
    )
    if res.worksheet is not None and json_out:
        payload = res.worksheet.to_dict()
        diagnostics = getattr(res, "solver_diagnostics", None)
        if isinstance(diagnostics, Mapping):
            payload.update(diagnostics)
        if fallback is not None:
            payload["window_order_fallback"] = fallback
        print(json.dumps(payload, indent=2, default=str))
    elif json_out:
        print(json.dumps(_solve_abstain_payload(function, class_id, res),
                         indent=2, default=str))
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
                       f"{c['perturbation']['kind']} ig{c['perturbation']['target_ig']} -> "
                       f"{[r['lever'] for r in c['c_realizations']]}")
        if fallback_leads:
            typer.echo("  window-order fallback:")
            for lead in fallback_leads:
                where, anchor = lead["order_move"]
                typer.echo(
                    f"  - move ig{lead['target_ig']} {where} ig{anchor}: "
                    f"f{lead['predicted_reg']} -> "
                    f"f{lead['perturbed_reg']} "
                    f"(observed f{lead['observed_reg']}, "
                    f"degree {lead['degree']}, "
                    f"distance {lead['move_distance']})"
                )
    if not json_out and res.node_set_delta is not None:
        _print_solve_node_set_delta(res.node_set_delta)
    if not json_out and res.reason:
        if fallback_leads:
            typer.echo("reason: window-order fallback lead(s) found")
        else:
            typer.echo(f"reason: {res.reason}")
    raise typer.Exit(0 if fallback_leads else res.exit_code)




@solve_app.command("allocator-ceiling")
def solve_allocator_ceiling_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function these evidence files target."),
    ],
    evidence: Annotated[
        list[Path],
        typer.Option(
            "--evidence",
            "-e",
            help=(
                "JSON evidence file from solve-coloring, node-set-split, "
                "plan-transforms, or force-phys-from-diff."
            ),
        ),
    ],
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Classify exhausted allocator-rotation evidence without compiling."""
    from ...mwcc_debug.allocator_ceiling import (
        EvidenceFormatError,
        EvidenceFunctionMismatch,
        classify_allocator_ceiling,
        flatten_evidence_items,
        render_allocator_ceiling_text,
    )

    if not evidence:
        typer.echo("--evidence is required", err=True)
        raise typer.Exit(2)

    payloads: list[dict[str, Any]] = []
    for path in evidence:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            typer.echo(f"could not read --evidence {path}: {exc}", err=True)
            raise typer.Exit(2) from exc
        try:
            payloads.extend(flatten_evidence_items([loaded]))
        except EvidenceFormatError as exc:
            typer.echo(f"invalid --evidence {path}: {exc}", err=True)
            raise typer.Exit(2) from exc

    try:
        result = classify_allocator_ceiling(payloads, function=function)
    except (EvidenceFunctionMismatch, EvidenceFormatError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    if json_out:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(render_allocator_ceiling_text(result))
    raise typer.Exit(int(result["exit_code"]))




@dataclasses.dataclass
class _NodeSetSplitPcdumpBackendResult:
    signature: Any
    pcdump_text: str | None
    remote_fallback: dict[str, Any] | None = None
    unsafe_local_pcdump_lane: dict[str, Any] | None = None




@dataclasses.dataclass
class _NodeSetSplitPcdumpBackendFailure(Exception):
    message: str
    stop_reason: str
    terminal_blocker: str
    remote_fallback: dict[str, Any] | None = None
    unsafe_local_pcdump_lane: dict[str, Any] | None = None
    returncode: int | None = None
    stderr_tail: str | None = None

    def __str__(self) -> str:
        return self.message




def _node_set_split_source_rel(path: Path, melee_root: Path) -> str:
    try:
        return path.resolve().relative_to(melee_root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()




def _node_set_split_remote_metadata(
    remote_result: _RemotePcdumpResult,
    *,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "used": True,
        "reason": reason,
        "host": remote_result.host,
        "source": remote_result.source_rel,
        "compile_source": remote_result.compile_source_rel,
        "staged_source": remote_result.staged_source,
        "returncode": remote_result.returncode,
        "stage_source_sha256": remote_result.stage_source_sha256,
        "staging_ack_confirmed": remote_result.staging_ack_confirmed,
        "staging_transport": remote_result.staging_transport,
        "remote_stage_source": remote_result.remote_stage_source,
    }




def _node_set_split_compile_signature_and_pcdump_backend(
    path: Path,
    *,
    label: str,
    function: str,
    class_id: int,
    melee_root: Path,
    timeout: int | float,
    unit_source: Path | None = None,
    full_unit_source: bool = False,
    need_pcdump: bool = True,
    remote: bool = False,
    remote_fallback: bool = False,
    remote_host: str = "nzxt-local",
    remote_script: str = r"C:\Users\mikes\code\mwcc_debug\run_pcdump.ps1",
    remote_branch: str | None = None,
    remote_no_pull: bool = False,
) -> _NodeSetSplitPcdumpBackendResult:
    from src.cli.debug import (
        _node_set_split_compile_signature,
        _node_set_split_compile_signature_and_pcdump,
        _node_set_split_signature_from_pcdump_text,
        _remote_retained_source_terminal_blocker,
        _run_remote_pcdump,
        _same_filesystem_path,
        _score_source_related_prefixes,
        _score_source_unsafe_lane_payload,
    )
    source_rel = _node_set_split_source_rel(path, melee_root)
    compile_source_rel = (
        _node_set_split_source_rel(unit_source, melee_root)
        if unit_source is not None
        else source_rel
    )
    stage_source_path: Path | None = None
    stage_source_label: str | None = None
    if unit_source is not None and not _same_filesystem_path(path, unit_source):
        stage_source_path = path
        stage_source_label = source_rel

    unsafe_lane: dict[str, Any] | None = None
    use_remote = remote
    remote_reason: str | None = "--remote" if remote else None
    if not remote and remote_fallback:
        unsafe_lane = _score_source_unsafe_lane_payload(
            source_rel=source_rel,
            function=function,
            cflags_unit_rel=compile_source_rel,
            allow_unsafe=local_safety.allow_unsafe_local_pcdump(),
            related_source_prefixes=_score_source_related_prefixes(
                source_rel=source_rel,
                cflags_unit_rel=compile_source_rel,
            ),
        )
        if unsafe_lane is not None:
            use_remote = True
            remote_reason = "unsafe local pcdump lane"

    if not use_remote:
        if need_pcdump:
            compiled = _node_set_split_compile_signature_and_pcdump(
                path,
                label=label,
                function=function,
                class_id=class_id,
                melee_root=melee_root,
                timeout=timeout,
                unit_source=unit_source,
                full_unit_source=full_unit_source,
            )
            if isinstance(compiled, tuple) and len(compiled) == 2:
                return _NodeSetSplitPcdumpBackendResult(compiled[0], compiled[1])
            return _NodeSetSplitPcdumpBackendResult(compiled, None)
        return _NodeSetSplitPcdumpBackendResult(
            _node_set_split_compile_signature(
                path,
                label=label,
                function=function,
                class_id=class_id,
                melee_root=melee_root,
                timeout=timeout,
                unit_source=unit_source,
                full_unit_source=full_unit_source,
            ),
            None,
        )

    remote_result = _run_remote_pcdump(
        source_rel=source_rel,
        compile_source_rel=compile_source_rel,
        host=remote_host,
        remote_script=remote_script,
        timeout=timeout,
        branch=remote_branch,
        no_pull=remote_no_pull,
        stage_source_path=stage_source_path,
        stage_source_label=stage_source_label,
    )
    remote_meta = _node_set_split_remote_metadata(
        remote_result,
        reason=remote_reason,
    )
    if remote_result.returncode != 0 or not remote_result.stdout.strip():
        terminal_blocker = _remote_retained_source_terminal_blocker(remote_result)
        raise _NodeSetSplitPcdumpBackendFailure(
            message=(
                f"remote pcdump failed for {label}: "
                f"{(remote_result.stderr or '').strip() or 'empty pcdump'}"
            ),
            stop_reason=terminal_blocker,
            terminal_blocker=terminal_blocker,
            remote_fallback=remote_meta,
            unsafe_local_pcdump_lane=unsafe_lane,
            returncode=remote_result.returncode,
            stderr_tail=(remote_result.stderr or "")[-4000:] or None,
        )
    try:
        signature = _node_set_split_signature_from_pcdump_text(
            remote_result.stdout,
            function=function,
            class_id=class_id,
        )
    except Exception as exc:
        raise _NodeSetSplitPcdumpBackendFailure(
            message=f"remote pcdump parse failed for {label}: {exc}",
            stop_reason="remote-pcdump-failed",
            terminal_blocker="remote-pcdump-failed",
            remote_fallback=remote_meta,
            unsafe_local_pcdump_lane=unsafe_lane,
            returncode=remote_result.returncode,
            stderr_tail=(remote_result.stderr or "")[-4000:] or None,
        ) from exc
    return _NodeSetSplitPcdumpBackendResult(
        signature,
        remote_result.stdout,
        remote_fallback=remote_meta,
        unsafe_local_pcdump_lane=unsafe_lane,
    )




@contextmanager
def _node_set_split_same_tu_compile_path(
    path: Path,
    *,
    function: str,
    melee_root: Path,
    unit_source: Path | None,
    full_unit_source: bool = False,
) -> Iterator[Path]:
    """Compile same-TU probes through the original source path.

    `debug dump local --unit-source` borrows flags from the real TU, but MWCC
    still compiles the probe path directly. Large node-set full-TU probes under
    build/mwcc_debug_cache have hit the compiler diagnostic path and pinned wibo
    in UE state even when the same source builds cleanly through ninja. For
    those same-TU probes, temporarily transfer the candidate function into the
    real unit source and compile that path, matching the real-tree score/apply
    path while keeping cache sync disabled in the dump command.
    """
    from src.cli.debug import (
        _acquire_source_score_repo_lock,
        _fresh_pcdump_cache_path_for_restore,
        _preserve_pcdump_cache_freshness_after_restore,
        _register_active_source_restore,
        _restore_source_snapshot,
        _unregister_active_source_restore,
    )
    if unit_source is None:
        yield path
        return

    try:
        source_path = path.resolve()
        unit_path = unit_source.resolve()
    except OSError:
        yield path
        return

    if source_path == unit_path:
        yield path
        return

    try:
        unit = str(unit_path.relative_to(melee_root / "src")).removesuffix(".c")
    except ValueError:
        unit = None

    with _acquire_source_score_repo_lock(melee_root):
        candidate_text = path.read_text(encoding="utf-8", errors="replace")
        original = unit_path.read_text(encoding="utf-8", errors="replace")
        fresh_cache_path = _fresh_pcdump_cache_path_for_restore(
            unit=unit,
            melee_root=melee_root,
        )
        _register_active_source_restore(unit_path, original)
        restore_error: str | None = None
        try:
            if full_unit_source:
                if find_source_function(candidate_text, function) is None:
                    raise ValueError(
                        f"target function {function} not found in candidate "
                        f"source {path}"
                    )
                unit_path.write_text(candidate_text, encoding="utf-8")
            elif transfer_candidate(candidate_text, unit_path, function) is None:
                raise ValueError(
                    f"target function {function} not found in candidate "
                    f"source {path} or unit source {unit_path}"
                )
            yield unit_path
        finally:
            if unit_path.read_text(encoding="utf-8", errors="replace") != original:
                restore_error = _restore_source_snapshot(unit_path, original)
            if restore_error is None:
                _preserve_pcdump_cache_freshness_after_restore(
                    cache_path=fresh_cache_path,
                    source_path=unit_path,
                    original=original,
                )
            _unregister_active_source_restore(unit_path)
            if restore_error is not None:
                raise RuntimeError(restore_error)




def _retain_node_set_split_source(
    candidate_path: Path,
    *,
    candidate_id: str,
    probe_root: Path,
    reason: str,
) -> Path:
    from src.cli.debug import _safe_filename
    source_text = candidate_path.read_text(encoding="utf-8")
    digest = hashlib.sha1(source_text.encode("utf-8")).hexdigest()[:12]
    retained_dir = probe_root / reason
    retained_dir.mkdir(parents=True, exist_ok=True)
    retained_path = retained_dir / f"{_safe_filename(candidate_id)}-{digest}.c"
    retained_path.write_text(source_text, encoding="utf-8")
    return retained_path




def _retain_node_set_split_pcdump(
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


def _node_set_split_target_score_hits(objective: Mapping[str, Any]) -> int:
    target_score = objective.get("target_score")
    if not isinstance(target_score, Mapping):
        return 0
    hits = target_score.get("hits")
    if isinstance(hits, bool):
        return int(hits)
    if isinstance(hits, int):
        return max(0, hits)
    if isinstance(hits, str):
        try:
            return max(0, int(hits, 0))
        except ValueError:
            return 0
    return 0




def _retain_node_set_split_failed_source(
    candidate_path: Path,
    *,
    candidate_id: str,
    probe_root: Path,
) -> Path:
    return _retain_node_set_split_source(
        candidate_path,
        candidate_id=candidate_id,
        probe_root=probe_root,
        reason="compile_failed",
    )




def _node_set_split_blocked_summary(
    *,
    function: str,
    class_id: int,
    target_ig: int | None,
    reason: str,
    threshold: float,
) -> dict[str, Any]:
    from ...mwcc_debug.node_set_split import (
        NodeSetSplitRequest,
        summarize_node_set_split_scores,
    )

    request = NodeSetSplitRequest(
        function=function,
        class_id=class_id,
        target_ig=target_ig if target_ig is not None else -1,
        blocked_reason=reason,
    )
    return summarize_node_set_split_scores(
        function,
        request,
        [],
        [],
        threshold,
    )




def _node_set_split_remaining_timeout(
    *,
    started_at: float,
    budget: float | None,
    per_call_timeout: float,
    min_seconds: float = 0.1,
) -> float | None:
    """Return a child timeout clamped to the remaining global budget."""
    if budget is None:
        return per_call_timeout
    remaining = budget - (time.monotonic() - started_at)
    if remaining < min_seconds:
        return None
    return min(per_call_timeout, remaining)




def _register_number_from_name(register: str | None) -> int | None:
    if register is None:
        return None
    match = re.match(r"^[rf](?P<num>\d+)$", register.strip(), re.IGNORECASE)
    if match is None:
        return None
    return int(match.group("num"))




def _node_set_split_force_phys_from_requests(requests: list[Any]) -> dict[int, int]:
    force_phys: dict[int, int] = {}
    for request in requests:
        target_reg = _register_number_from_name(getattr(request, "target_reg", None))
        if target_reg is None:
            continue
        force_phys[int(request.target_ig)] = target_reg
    return force_phys




def _node_set_split_request_var_names(requests: list[Any] | None) -> set[str]:
    names: set[str] = set()
    if requests is None:
        return names
    for request in requests:
        name = getattr(request, "var_name", None)
        if isinstance(name, str) and re.match(r"^[A-Za-z_]\w*$", name):
            names.add(name)
    return names




def _node_set_split_changed_text(before: str, after: str) -> str:
    lines: list[str] = []
    for line in difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        n=1,
        lineterm="",
    ):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            lines.append(line[1:])
        elif line.startswith(" "):
            lines.append(line[1:])
    return "\n".join(lines)




def _node_set_split_probe_mentions_target(
    probe: Any,
    *,
    source_text: str,
    candidate_text: str,
    target_names: set[str],
) -> bool:
    if not target_names:
        return True

    locality_texts: list[str] = []
    payload = getattr(probe, "payload", None)
    if payload not in (None, "", {}, ()):
        locality_texts.append(str(payload))
    span = getattr(probe, "span", None)
    if (
        isinstance(span, tuple)
        and len(span) == 2
        and all(isinstance(value, int) for value in span)
    ):
        start, end = span
        if 0 <= start <= end <= len(source_text):
            locality_texts.append(source_text[start:end])

    texts = (
        locality_texts
        if locality_texts
        else [_node_set_split_changed_text(source_text, candidate_text)]
    )

    for name in target_names:
        pattern = r"\b" + re.escape(name) + r"\b"
        if any(re.search(pattern, text) for text in texts):
            return True
    return False




def _node_set_split_source_hunk(before: str, after: str, label: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"{label}:before",
            tofile=f"{label}:after",
            lineterm="",
        )
    )




def _emit_node_set_split_summary(summary: dict[str, Any], *, json_out: bool) -> None:
    if json_out:
        print(json.dumps(summary, indent=2, default=str))
        return

    print(f"node-set-split {summary.get('function')}: {summary.get('status')}")
    stop_condition = summary.get("stop_condition")
    if isinstance(stop_condition, dict):
        kind = stop_condition.get("kind")
        omitted = summary.get("omitted_count", 0)
        print(f"stop: {kind} ({omitted} candidate(s) omitted)")
    request = summary.get("request") or {}
    if request.get("target_ig") is not None:
        target_reg = request.get("target_reg") or "?"
        print(f"target: ig{request.get('target_ig')} -> {target_reg}")
    if summary.get("blocked_reason"):
        print(f"reason: {summary['blocked_reason']}")
    print(
        f"generated: {summary.get('generated_count', 0)}; "
        f"scored: {summary.get('scored_count', 0)}; "
        f"realized: {summary.get('realized_count', 0)}"
    )
    if summary.get("best_candidate_id"):
        print(
            f"best: {summary['best_candidate_id']} "
            f"({summary.get('best_checkdiff_delta'):+.2f}%)"
        )
    for row in (summary.get("candidates") or [])[:8]:
        candidate_id = row.get("candidate_id")
        objective = row.get("objective_status")
        delta = row.get("checkdiff_delta")
        delta_text = "unscored" if delta is None else f"{delta:+.2f}%"
        print(f"- {candidate_id}: {objective}, {delta_text}")




def _node_set_split_cli_path(path: Path, melee_root: Path) -> str:
    try:
        return path.resolve().relative_to(melee_root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)




def _node_set_split_default_summary_path(
    *,
    melee_root: Path,
    function: str,
    request: Any,
) -> Path:
    from src.cli.debug import _safe_filename
    target = getattr(request, "target_ig", None)
    var_name = getattr(request, "var_name", None) or "request"
    target_reg = getattr(request, "target_reg", None) or "target"
    stem = _safe_filename(f"ig{target}_{var_name}_{target_reg}")
    return (
        melee_root
        / "build"
        / "diagnostics"
        / _safe_filename(function)
        / "node_set_split"
        / f"{stem}.json"
    )




def _node_set_split_summary_path(
    *,
    output: Path | None,
    melee_root: Path,
    function: str,
    request: Any,
) -> Path:
    if output is not None:
        return output if output.is_absolute() else melee_root / output
    return _node_set_split_default_summary_path(
        melee_root=melee_root,
        function=function,
        request=request,
    )




def _node_set_split_write_summary(summary: dict[str, Any], path: Path) -> None:
    summary["output"] = str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")




def _node_set_split_resume_manifest_path(summary_path: Path) -> Path:
    return summary_path.with_suffix(".manifest.json")




def _node_set_split_candidate_dir(summary_path: Path) -> Path:
    return summary_path.with_suffix(".candidates")




def _node_set_split_text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()




def _node_set_split_candidate_source_path(
    summary_path: Path,
    *,
    candidate_id: str,
    index: int,
) -> Path:
    from src.cli.debug import _safe_filename
    return (
        _node_set_split_candidate_dir(summary_path)
        / f"{index:04d}-{_safe_filename(candidate_id)}.c"
    )




def _node_set_split_request_json(request: Any) -> dict[str, Any]:
    if dataclasses.is_dataclass(request):
        return dataclasses.asdict(request)
    if isinstance(request, Mapping):
        return dict(request)
    return {}




def _node_set_split_request_from_json(
    payload: Any,
    *,
    function: str,
    class_id: int,
) -> Any | None:
    if not isinstance(payload, Mapping):
        return None
    from ...mwcc_debug.node_set_split import NodeSetSplitRequest

    fields = {field.name for field in dataclasses.fields(NodeSetSplitRequest)}
    data: dict[str, Any] = {
        key: payload[key] for key in fields if key in payload
    }
    data["function"] = str(data.get("function") or function)
    try:
        data["class_id"] = int(data.get("class_id", class_id))
        data["target_ig"] = int(data["target_ig"])
    except (KeyError, TypeError, ValueError):
        return None
    target_regs = data.get("target_regs")
    if isinstance(target_regs, list):
        data["target_regs"] = tuple(str(item) for item in target_regs)
    elif target_regs is None:
        data["target_regs"] = ()
    source_scope_path = data.get("source_scope_path")
    if isinstance(source_scope_path, list):
        data["source_scope_path"] = tuple(str(item) for item in source_scope_path)
    return NodeSetSplitRequest(**data)




def _node_set_split_manifest_error(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(2)




def _node_set_split_read_generated_manifest(
    summary_path: Path,
) -> dict[str, Any]:
    manifest_path = _node_set_split_resume_manifest_path(summary_path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _node_set_split_manifest_error(
            f"could not read node-set-split manifest {manifest_path}: {exc}"
        )
    if not isinstance(payload, dict):
        _node_set_split_manifest_error(
            f"node-set-split manifest {manifest_path} must be a JSON object"
        )
    if payload.get("version") != 1:
        _node_set_split_manifest_error(
            f"unsupported node-set-split manifest version: {payload.get('version')}"
        )
    if payload.get("kind") != "node-set-split-generated-candidates":
        _node_set_split_manifest_error(
            f"unsupported node-set-split manifest kind: {payload.get('kind')}"
        )
    return payload




def _node_set_split_manifest_path_value(
    raw_path: Any,
    *,
    manifest_path: Path,
    melee_root: Path,
) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    root_path = melee_root / path
    if root_path.exists():
        return root_path
    return manifest_path.parent / path




def _node_set_split_touched_ranges_from_json(
    raw_ranges: Any,
) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    if not isinstance(raw_ranges, list):
        return ()
    for item in raw_ranges:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
        ):
            try:
                ranges.append((int(item[0]), int(item[1])))
            except (TypeError, ValueError):
                continue
    return tuple(ranges)




def _node_set_split_write_generated_manifest(
    summary_path: Path,
    patches: list[Any],
    *,
    function: str,
    class_id: int,
    source_file: Path,
    source_text: str,
    request: Any,
    coupled_requests: list[Any] | None,
    melee_root: Path,
) -> Path:
    manifest_path = _node_set_split_resume_manifest_path(summary_path)
    candidate_dir = _node_set_split_candidate_dir(summary_path)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, patch in enumerate(patches):
        candidate_id = str(patch.candidate_id)
        source_path = _node_set_split_candidate_source_path(
            summary_path,
            candidate_id=candidate_id,
            index=index,
        )
        source_path.write_text(patch.patched_source, encoding="utf-8")
        records.append({
            "index": index,
            "candidate_id": candidate_id,
            "summary": str(patch.summary),
            "source_path": str(source_path),
            "source_sha256": _node_set_split_text_sha256(patch.patched_source),
            "touched_ranges": [
                [int(start), int(end)]
                for start, end in getattr(patch, "touched_ranges", ()) or ()
            ],
            "hunk": getattr(patch, "hunk", "") or "",
            "metadata": dict(getattr(patch, "metadata", {}) or {}),
        })
    manifest = {
        "version": 1,
        "kind": "node-set-split-generated-candidates",
        "function": function,
        "class_id": class_id,
        "source_file": str(source_file),
        "source_sha256": _node_set_split_text_sha256(source_text),
        "request": _node_set_split_request_json(request),
        "coupled_requests": [
            _node_set_split_request_json(req)
            for req in (coupled_requests or [])
        ],
        "candidate_order": [record["candidate_id"] for record in records],
        "candidates": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return manifest_path




def _node_set_split_load_generated_manifest(
    summary_path: Path,
    *,
    manifest_payload: dict[str, Any] | None,
    function: str,
    class_id: int,
    source_file: Path,
    source_text: str,
    melee_root: Path,
) -> list[Any]:
    from src.cli.debug import _same_filesystem_path

    from ...mwcc_debug.source_shape import CandidatePatch

    manifest_path = _node_set_split_resume_manifest_path(summary_path)
    payload = manifest_payload or _node_set_split_read_generated_manifest(
        summary_path
    )
    if payload.get("function") != function:
        _node_set_split_manifest_error(
            f"manifest is for {payload.get('function')}, not {function}"
        )
    try:
        manifest_class_id = int(payload.get("class_id"))
    except (TypeError, ValueError):
        _node_set_split_manifest_error("manifest has invalid class_id")
    if manifest_class_id != class_id:
        _node_set_split_manifest_error(
            f"manifest class_id is {manifest_class_id}, not {class_id}"
        )
    manifest_source = _node_set_split_manifest_path_value(
        payload.get("source_file"),
        manifest_path=manifest_path,
        melee_root=melee_root,
    )
    if not _same_filesystem_path(manifest_source, source_file):
        _node_set_split_manifest_error(
            f"manifest source file is {manifest_source}, not {source_file}"
        )
    if payload.get("source_sha256") != _node_set_split_text_sha256(source_text):
        _node_set_split_manifest_error(
            f"manifest source hash mismatch for {source_file}"
        )

    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        _node_set_split_manifest_error("manifest candidates must be a list")
    by_id: dict[str, Mapping[str, Any]] = {}
    for record in raw_candidates:
        if not isinstance(record, Mapping):
            _node_set_split_manifest_error("manifest candidate must be an object")
        candidate_id = str(record.get("candidate_id") or "")
        if not candidate_id:
            _node_set_split_manifest_error("manifest candidate missing candidate_id")
        by_id[candidate_id] = record
    order = payload.get("candidate_order")
    if not isinstance(order, list):
        order = [record.get("candidate_id") for record in raw_candidates]

    patches: list[Any] = []
    for raw_candidate_id in order:
        candidate_id = str(raw_candidate_id)
        record = by_id.get(candidate_id)
        if record is None:
            _node_set_split_manifest_error(
                f"manifest candidate_order references missing {candidate_id}"
            )
        candidate_path = _node_set_split_manifest_path_value(
            record.get("source_path"),
            manifest_path=manifest_path,
            melee_root=melee_root,
        )
        try:
            candidate_text = candidate_path.read_text(encoding="utf-8")
        except OSError as exc:
            _node_set_split_manifest_error(
                f"could not read retained candidate {candidate_id}: {exc}"
            )
        if record.get("source_sha256") != _node_set_split_text_sha256(
            candidate_text
        ):
            _node_set_split_manifest_error(
                f"retained candidate hash mismatch for {candidate_id}: "
                f"{candidate_path}"
            )
        metadata = dict(record.get("metadata") or {})
        metadata["manifest_source_path"] = str(candidate_path)
        patches.append(CandidatePatch(
            candidate_id=candidate_id,
            patched_source=candidate_text,
            summary=str(record.get("summary") or candidate_id),
            touched_ranges=_node_set_split_touched_ranges_from_json(
                record.get("touched_ranges")
            ),
            hunk=str(record.get("hunk") or ""),
            metadata=metadata,
        ))
    return patches




def _node_set_split_row_needs_resume(row: Mapping[str, Any]) -> bool:
    if row.get("score_status") == "budget-exhausted":
        return True
    return (
        row.get("objective_status") == "realized"
        and row.get("checkdiff_pct") is None
        and row.get("checkdiff_delta") is None
    )




def _node_set_split_pending_candidate_ids(
    patches: list[Any],
    rows: list[Any],
) -> set[str]:
    final_ids: set[str] = set()
    pending_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        candidate_id = row.get("candidate_id")
        if candidate_id is None:
            continue
        candidate_id = str(candidate_id)
        if _node_set_split_row_needs_resume(row):
            pending_ids.add(candidate_id)
        else:
            final_ids.add(candidate_id)
    for patch in patches:
        candidate_id = str(patch.candidate_id)
        if candidate_id not in final_ids:
            pending_ids.add(candidate_id)
    return pending_ids




def _node_set_split_pending_candidate_records(
    patches: list[Any],
    summary: Mapping[str, Any],
    *,
    summary_path: Path,
) -> list[dict[str, Any]]:
    rows = summary.get("candidates") if isinstance(summary, Mapping) else None
    pending_ids = _node_set_split_pending_candidate_ids(
        patches,
        rows if isinstance(rows, list) else [],
    )
    records: list[dict[str, Any]] = []
    for index, patch in enumerate(patches):
        candidate_id = str(patch.candidate_id)
        if candidate_id not in pending_ids:
            continue
        metadata = getattr(patch, "metadata", {}) or {}
        source_path = metadata.get("manifest_source_path")
        if source_path is None:
            source_path = str(_node_set_split_candidate_source_path(
                summary_path,
                candidate_id=candidate_id,
                index=index,
            ))
        records.append({
            "candidate_id": candidate_id,
            "summary": str(patch.summary),
            "source_path": str(source_path),
            "touched_ranges": [
                [int(start), int(end)]
                for start, end in getattr(patch, "touched_ranges", ()) or ()
            ],
        })
    return records




def _node_set_split_load_resume_summary(
    resume_summary: Path | None,
    *,
    function: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if resume_summary is None:
        return None, None
    try:
        payload = json.loads(resume_summary.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(f"could not read --resume-summary: {exc}", err=True)
        raise typer.Exit(2) from exc
    if not isinstance(payload, dict):
        typer.echo("--resume-summary must be a JSON object", err=True)
        raise typer.Exit(2)
    prior_function = payload.get("function")
    if (
        function is not None
        and isinstance(prior_function, str)
        and prior_function
        and prior_function != function
    ):
        typer.echo(
            f"--resume-summary is for {prior_function}, not {function}",
            err=True,
        )
        raise typer.Exit(2)
    manifest = _node_set_split_resume_manifest_path(resume_summary)
    resume_mode = (
        "manifest"
        if manifest.exists()
        else "regenerated-no-manifest"
    )
    return payload, resume_mode




def _node_set_split_class_arg(class_id: int, fallback: str) -> str:
    if class_id == 1:
        return "fpr"
    if class_id == 0:
        return "gpr"
    return fallback




def _node_set_split_resume_command(
    *,
    function: str,
    register_class: str,
    class_id: int,
    request: Any,
    resolved_source: Path,
    melee_root: Path,
    summary_path: Path,
    node_set_delta: Path | None,
    force_phys: str | None,
    generated_local_source_json: str | None,
    max_read_sites: int,
    threshold: float,
    timeout: int,
    coupled: bool,
    remote_host: str,
    remote_script: str,
    remote_branch: str | None,
    remote_no_pull: bool,
    retain_generated: bool,
) -> str:
    command: list[str] = [
        "melee-agent",
        "debug",
        "solve",
        "node-set-split",
        "-f",
        function,
        "--class",
        _node_set_split_class_arg(class_id, register_class),
        "--source-file",
        _node_set_split_cli_path(resolved_source, melee_root),
    ]
    if node_set_delta is not None:
        command.extend(["--node-set-delta", str(node_set_delta)])
    if coupled:
        command.append("--coupled")
    target_ig = getattr(request, "target_ig", None)
    if target_ig is not None and int(target_ig) >= 0:
        command.extend(["--ig", str(target_ig)])
    current_reg = getattr(request, "current_reg", None)
    if current_reg is not None:
        command.extend(["--current-reg", str(current_reg)])
    target_reg = getattr(request, "target_reg", None)
    if target_reg is not None:
        command.extend(["--target-reg", str(target_reg)])
    var_name = getattr(request, "var_name", None)
    if var_name is not None:
        command.extend(["--var", str(var_name)])
    if force_phys:
        command.extend(["--force-phys", force_phys])
    if generated_local_source_json:
        command.extend(["--generated-local-source-json", generated_local_source_json])
    command.extend(["--max-read-sites", str(max_read_sites)])
    command.extend(["--threshold", f"{threshold:g}"])
    command.extend(["--timeout", str(timeout)])
    command.extend(["--remote", "--max-candidates", "0"])
    command.extend([
        "--resume-summary",
        _node_set_split_cli_path(summary_path, melee_root),
    ])
    command.extend(["--output", _node_set_split_cli_path(summary_path, melee_root)])
    command.extend(["--remote-host", remote_host])
    command.extend(["--remote-script", remote_script])
    if remote_branch:
        command.extend(["--remote-branch", remote_branch])
    if remote_no_pull:
        command.append("--remote-no-pull")
    if retain_generated:
        command.append("--retain-generated")
    command.append("--json")
    return shlex.join(command)




def _parse_node_set_generated_local_source_json(
    raw: str | None,
) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"--generated-local-source-json is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter(
            "--generated-local-source-json must decode to an object"
        )
    return payload




class _NodeSetSplitGenerationTimeout(TimeoutError):
    pass




def _run_node_set_split_generation_with_watchdog(
    fn: Callable[[], Any],
    *,
    timeout_s: float | None,
) -> Any:
    if timeout_s is None:
        return fn()
    if timeout_s <= 0:
        raise _NodeSetSplitGenerationTimeout("node-set generation budget exhausted")

    def _handle_timeout(_signum: int, _frame: Any) -> NoReturn:
        raise _NodeSetSplitGenerationTimeout(
            "node-set generation watchdog timed out"
        )

    try:
        previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _handle_timeout)
        signal.setitimer(signal.ITIMER_REAL, max(0.001, float(timeout_s)))
    except (AttributeError, ValueError):
        return fn()
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)




def _node_set_generation_result_parts(result: Any) -> tuple[list[Any], dict[str, Any]]:
    if hasattr(result, "patches"):
        patches = list(getattr(result, "patches") or [])
        metadata = {
            "stop_reason": getattr(result, "stop_reason", None),
            "elapsed_seconds": getattr(result, "elapsed_seconds", None),
            "budget_seconds": getattr(result, "budget_seconds", None),
            "candidate_limit": getattr(result, "candidate_limit", None),
            "generation_complete": getattr(result, "generation_complete", True),
        }
        return patches, metadata
    return list(result or []), {}




@solve_app.command("node-set-split")
def solve_node_set_split_cmd(
    function: Annotated[
        Optional[str],
        typer.Option("--function", "-f", help="Function to mutate."),
    ] = None,
    register_class: Annotated[
        str,
        typer.Option("--class", help="Register class: gpr/r/0 or fpr/f/1."),
    ] = "gpr",
    target_ig: Annotated[
        Optional[int],
        typer.Option("--ig", "--target-ig", help="COLORGRAPH ig_idx to move."),
    ] = None,
    current_reg: Annotated[
        Optional[str],
        typer.Option("--current-reg", help="Observed physical register."),
    ] = None,
    target_reg: Annotated[
        Optional[str],
        typer.Option("--target-reg", help="Desired physical register."),
    ] = None,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            "--transform-force-phys",
            help=(
                "Exact force-phys target map to score for every retained "
                "candidate, e.g. 34:27,44:25."
            ),
        ),
    ] = None,
    var_name: Annotated[
        Optional[str],
        typer.Option("--var", help="Source variable to split or extend."),
    ] = None,
    generated_local_source_json: Annotated[
        Optional[str],
        typer.Option(
            "--generated-local-source-json",
            "--generated-local-source",
            help=(
                "JSON generated-local source payload from coalesce-search "
                "continuations (kind/name/type/initializer/source_line)."
            ),
        ),
    ] = None,
    node_set_delta: Annotated[
        Optional[Path],
        typer.Option(
            "--node-set-delta",
            help="JSON node_set_delta payload from `debug solve coloring`.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file to use. Defaults to report.json's TU source.",
        ),
    ] = None,
    max_read_sites: Annotated[
        int,
        typer.Option("--max-read-sites", help="Bound alias/lifetime read sites."),
    ] = 4,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Maximum source candidates to evaluate; 0 means unlimited.",
        ),
    ] = 16,
    budget: Annotated[
        Optional[float],
        typer.Option(
            "--budget",
            help="Global wall-clock budget in seconds for compile/score probes.",
        ),
    ] = None,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum checkdiff percentage-point win for an improvement.",
        ),
    ] = 0.05,
    apply_best: Annotated[
        bool,
        typer.Option(
            "--apply-best",
            help="Leave the best verified improving candidate applied.",
        ),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Per-candidate compile timeout seconds."),
    ] = 120,
    coupled: Annotated[
        bool,
        typer.Option(
            "--coupled",
            help=(
                "Realize a COUPLED rotation: move every bindable missing "
                "virtual in --node-set-delta to its target register "
                "simultaneously (for interdependent N-ig cycles where single-ig "
                "moves all land wrong-register). Requires --node-set-delta."
            ),
        ),
    ] = False,
    remote: Annotated[
        bool,
        typer.Option(
            "--remote/--no-remote",
            help=(
                "Compile allocator pcdumps through the remote backend, "
                "bypassing local wibo/compiler discovery."
            ),
        ),
    ] = False,
    remote_fallback: Annotated[
        bool,
        typer.Option(
            "--remote-fallback/--no-remote-fallback",
            help=(
                "Use the local pcdump lane unless the unsafe-lane guard "
                "requires the remote backend."
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
    resume_summary: Annotated[
        Optional[Path],
        typer.Option(
            "--resume-summary",
            help=(
                "Prior node-set-split summary to resume. Existing summaries "
                "without manifests are regenerated and rescored."
            ),
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output",
            help=(
                "Write the JSON summary to this path. Relative paths resolve "
                "from the melee repo root."
            ),
        ),
    ] = None,
    retain_generated: Annotated[
        bool,
        typer.Option(
            "--retain-generated/--no-retain-generated",
            help=(
                "Retain/report generated candidate sources for remote "
                "continuation diagnostics."
            ),
        ),
    ] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Realize a solve-coloring node-set split with source-shape candidates; use --coupled with --node-set-delta for interdependent rotations.

    Candidates are accepted only when they move the requested ig to the target
    physical register without adding spills, then improve real-tree checkdiff
    by at least `--threshold`.

    With `--coupled`, candidates must move EVERY bindable missing virtual in the
    delta to its target register at once (an interdependent rotation), composing
    the per-ig source edits into one patch.
    """
    from src.cli.debug import (
        DEFAULT_MELEE_ROOT,
        _apply_node_set_split_patch,
        _coalesce_parse_force_phys_map,
        _coalesce_simple_identifier,
        _find_unit_for_function,
        _fresh_node_set_split_source_baseline_pct,
        _node_set_split_steering_children,
        _resolve_existing_cli_file,
        _safe_filename,
        _same_filesystem_path,
        _score_node_set_split_candidate,
    )

    from ...mwcc_debug import tiebreak as tb
    from ...mwcc_debug.node_set_split import (
        NodeSetSplitRequest,
        _generated_pointer_walk_local_blocker,
        _order_node_set_patches_for_search,
        _source_scope_path_for_name,
        annotate_target_color_select_order_leads,
        evaluate_coupled_node_set_split_signature,
        evaluate_node_set_split_signature,
        generate_coupled_node_set_split_patches,
        generate_node_set_introduce_binding_patches,
        generate_node_set_split_patches,
        is_node_set_request_introducible,
        request_from_node_set_delta,
        requests_from_node_set_delta,
        summarize_node_set_split_scores,
    )
    from ...mwcc_debug.source_shape import CandidateScore

    if max_candidates < 0:
        typer.echo("--max-candidates must be >= 0", err=True)
        raise typer.Exit(2)
    if budget is not None and budget < 0:
        typer.echo("--budget must be >= 0", err=True)
        raise typer.Exit(2)
    try:
        generated_local_source = _parse_node_set_generated_local_source_json(
            generated_local_source_json
        )
    except typer.BadParameter as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    if coupled and node_set_delta is None and resume_summary is None:
        typer.echo(
            "--coupled requires --node-set-delta (the coupled set comes from "
            "the delta's missing-virtual list)",
            err=True,
        )
        raise typer.Exit(2)
    started_at = time.monotonic()
    deadline = started_at + budget if budget is not None else None
    candidate_limit = None if max_candidates == 0 else max_candidates
    if resume_summary is not None:
        try:
            resume_summary = _resolve_existing_cli_file(
                resume_summary,
                melee_root=DEFAULT_MELEE_ROOT,
                label="resume summary",
            )
        except typer.BadParameter as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc

    try:
        class_id = tb.parse_register_class(register_class)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    force_phys_targets = _coalesce_parse_force_phys_map(force_phys)

    delta_payload: dict[str, Any] | None = None
    if node_set_delta is not None:
        try:
            delta_payload = json.loads(node_set_delta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            typer.echo(f"could not read --node-set-delta: {exc}", err=True)
            raise typer.Exit(2) from exc
        prelim = request_from_node_set_delta(delta_payload, target_ig=target_ig)
        if function is None and prelim is not None and prelim.function:
            function = prelim.function
        if prelim is not None and prelim.class_id in {0, 1}:
            class_id = prelim.class_id

    resume_payload, resume_mode = _node_set_split_load_resume_summary(
        resume_summary,
        function=function,
    )
    resume_manifest_payload: dict[str, Any] | None = None
    if resume_summary is not None and resume_mode == "manifest":
        resume_manifest_payload = _node_set_split_read_generated_manifest(
            resume_summary
        )
        manifest_function = resume_manifest_payload.get("function")
        if function is None and isinstance(manifest_function, str):
            function = manifest_function
        try:
            manifest_class_id = int(resume_manifest_payload.get("class_id"))
        except (TypeError, ValueError):
            manifest_class_id = None
        if manifest_class_id in {0, 1}:
            class_id = manifest_class_id
            register_class = _node_set_split_class_arg(class_id, register_class)
    if (
        function is None
        and isinstance(resume_payload, Mapping)
        and isinstance(resume_payload.get("function"), str)
    ):
        function = str(resume_payload["function"])
    if resume_summary is not None:
        candidate_limit = None

    if function is None:
        typer.echo(
            "--function is required unless --node-set-delta names one",
            err=True,
        )
        raise typer.Exit(2)

    unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    compile_unit_source = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
    if not compile_unit_source.exists():
        typer.echo(f"source not found: {compile_unit_source}", err=True)
        raise typer.Exit(2)
    if source_file is None:
        resolved_source = compile_unit_source
    else:
        resolved_source = _resolve_existing_cli_file(
            source_file,
            melee_root=DEFAULT_MELEE_ROOT,
            label="source file",
        )
    if not resolved_source.exists():
        typer.echo(f"source not found: {resolved_source}", err=True)
        raise typer.Exit(2)
    source_text = resolved_source.read_text(encoding="utf-8", errors="replace")
    full_unit_source = not _same_filesystem_path(
        resolved_source,
        compile_unit_source,
    )

    coupled_requests: list[NodeSetSplitRequest] | None = None
    if coupled:
        if delta_payload is not None:
            coupled_requests = [
                dataclasses.replace(
                    req, function=req.function or function, class_id=class_id
                )
                for req in requests_from_node_set_delta(
                    delta_payload,
                    source_text=source_text,
                    source_file=resolved_source,
                    include_introducible=True,
                )
            ]
        elif resume_manifest_payload is not None:
            coupled_requests = [
                req for req in (
                    _node_set_split_request_from_json(
                        item,
                        function=function,
                        class_id=class_id,
                    )
                    for item in (
                        resume_manifest_payload.get("coupled_requests") or []
                    )
                )
                if req is not None
            ]
        else:
            coupled_requests = []
        if len(coupled_requests) < 2:
            aggregate = NodeSetSplitRequest(
                function=function,
                class_id=class_id,
                target_ig=target_ig if target_ig is not None else -1,
                blocked_reason=(
                    "coupled mode needs >=2 bindable missing virtuals "
                    f"(found {len(coupled_requests)})"
                ),
            )
            summary = summarize_node_set_split_scores(
                function,
                aggregate,
                [],
                [],
                threshold,
                stop_reason="no-coupled-probes",
                coupled_requests=coupled_requests,
            )
            _emit_node_set_split_summary(summary, json_out=json_out)
            raise typer.Exit(3)
        # Synthesized aggregate request: stands in for the single `request`
        # everywhere downstream (summary/apply); the per-ig moves ride in
        # `coupled_requests` and the coupled evaluator.
        manifest_request = (
            _node_set_split_request_from_json(
                resume_manifest_payload.get("request"),
                function=function,
                class_id=class_id,
            )
            if resume_manifest_payload is not None
            else None
        )
        if manifest_request is not None:
            request = dataclasses.replace(
                manifest_request,
                function=manifest_request.function or function,
                class_id=class_id,
            )
        else:
            request = NodeSetSplitRequest(
                function=function,
                class_id=class_id,
                target_ig=coupled_requests[0].target_ig,
                target_reg="+".join(
                    req.target_reg or "?" for req in coupled_requests
                ),
                var_name="+".join(req.var_name or "?" for req in coupled_requests),
            )
    elif delta_payload is not None:
        request = request_from_node_set_delta(
            delta_payload,
            target_ig=target_ig,
            source_text=source_text,
            source_file=resolved_source,
        )
        if request is None:
            summary = _node_set_split_blocked_summary(
                function=function,
                class_id=class_id,
                target_ig=target_ig,
                reason="node-set delta has no matching missing virtual",
                threshold=threshold,
            )
            _emit_node_set_split_summary(summary, json_out=json_out)
            raise typer.Exit(3)
        if not request.function:
            request = dataclasses.replace(request, function=function)
    else:
        manifest_request = (
            _node_set_split_request_from_json(
                resume_manifest_payload.get("request"),
                function=function,
                class_id=class_id,
            )
            if resume_manifest_payload is not None
            else None
        )
        if manifest_request is not None:
            request = dataclasses.replace(
                manifest_request,
                function=manifest_request.function or function,
                class_id=class_id,
            )
        elif target_ig is None or target_reg is None:
            typer.echo(
                "explicit mode requires --ig and --target-reg",
                err=True,
            )
            raise typer.Exit(2)
        else:
            request = NodeSetSplitRequest(
                function=function,
                class_id=class_id,
                target_ig=target_ig,
                current_reg=current_reg,
                target_reg=target_reg,
                var_name=var_name,
                blocked_reason=None if var_name else "no source variable supplied",
            )

    if generated_local_source is not None:
        payload_name = _coalesce_simple_identifier(generated_local_source.get("name"))
        if payload_name is None:
            typer.echo(
                "--generated-local-source-json needs simple identifier field 'name'",
                err=True,
            )
            raise typer.Exit(2)
        if request.var_name is not None and request.var_name != payload_name:
            typer.echo(
                "--generated-local-source-json name does not match --var",
                err=True,
            )
            raise typer.Exit(2)
        initializer = generated_local_source.get("initializer")
        source_type = generated_local_source.get("type")
        if not isinstance(initializer, str) or not initializer.strip():
            typer.echo(
                "--generated-local-source-json needs string field 'initializer'",
                err=True,
            )
            raise typer.Exit(2)
        if not isinstance(source_type, str) or not source_type.strip():
            typer.echo(
                "--generated-local-source-json needs string field 'type'",
                err=True,
            )
            raise typer.Exit(2)
        source_line = generated_local_source.get("source_line")
        source_scope_path = _source_scope_path_for_name(
            source_text,
            function,
            payload_name,
            source_line=source_line if isinstance(source_line, int) else None,
        )
        request = dataclasses.replace(
            request,
            var_name=payload_name,
            blocked_reason=None,
            source_expression=initializer.strip(),
            source_type=source_type.strip(),
            source_kind=(
                str(generated_local_source.get("kind")).strip()
                if generated_local_source.get("kind") is not None
                else "generated-pointer-walk-local"
            ),
            source_scope_path=source_scope_path or request.source_scope_path,
        )

    if (
        request.blocked_reason is not None or request.var_name is None
    ) and not is_node_set_request_introducible(request):
        reason = request.blocked_reason or "no bindable source variable"
        request = dataclasses.replace(
            request,
            function=request.function or function,
            class_id=class_id,
            blocked_reason=reason,
        )
        summary = summarize_node_set_split_scores(
            function,
            request,
            [],
            [],
            threshold,
        )
        _emit_node_set_split_summary(summary, json_out=json_out)
        raise typer.Exit(3)

    request = dataclasses.replace(
        request,
        function=request.function or function,
        class_id=class_id,
    )
    summary_path = _node_set_split_summary_path(
        output=output,
        melee_root=DEFAULT_MELEE_ROOT,
        function=function,
        request=request,
    )
    resume_command = _node_set_split_resume_command(
        function=function,
        register_class=register_class,
        class_id=class_id,
        request=request,
        resolved_source=resolved_source,
        melee_root=DEFAULT_MELEE_ROOT,
        summary_path=summary_path,
        node_set_delta=node_set_delta,
        force_phys=force_phys,
        generated_local_source_json=generated_local_source_json,
        max_read_sites=max_read_sites,
        threshold=threshold,
        timeout=timeout,
        coupled=coupled,
        remote_host=remote_host,
        remote_script=remote_script,
        remote_branch=remote_branch,
        remote_no_pull=remote_no_pull,
        retain_generated=retain_generated,
    )
    generation_metadata: dict[str, Any] = {}
    if resume_summary is not None and resume_mode == "manifest":
        patches = _node_set_split_load_generated_manifest(
            resume_summary,
            manifest_payload=resume_manifest_payload,
            function=function,
            class_id=class_id,
            source_file=resolved_source,
            source_text=source_text,
            melee_root=DEFAULT_MELEE_ROOT,
        )
    else:
        def _generate_node_set_candidates() -> Any:
            if coupled_requests is not None:
                return generate_coupled_node_set_split_patches(
                    source_text,
                    function,
                    coupled_requests,
                    max_read_sites=max_read_sites,
                    max_per_ig=(
                        12 if candidate_limit is None
                        else min(12, max(1, candidate_limit))
                    ),
                    # candidate_limit is None for `--max-candidates 0`
                    # (exhaustive); forward that as 0 so the generator does
                    # not silently re-cap at 24.
                    max_candidates=(
                        candidate_limit if candidate_limit is not None else 0
                    ),
                    deadline=deadline,
                    return_result=True,
                )
            if is_node_set_request_introducible(request):
                return generate_node_set_introduce_binding_patches(
                    source_text,
                    function,
                    request,
                    max_read_sites=max_read_sites,
                    max_candidates=candidate_limit,
                    deadline=deadline,
                )
            return generate_node_set_split_patches(
                source_text,
                function,
                request,
                max_read_sites=max_read_sites,
                max_candidates=candidate_limit,
                deadline=deadline,
            )

        watchdog_timeout = (
            None
            if deadline is None or budget == 0
            else max(0.0, deadline - time.monotonic())
        )
        try:
            raw_generation = _run_node_set_split_generation_with_watchdog(
                _generate_node_set_candidates,
                timeout_s=watchdog_timeout,
            )
        except _NodeSetSplitGenerationTimeout:
            patches = []
            generation_metadata = {
                "stop_reason": "budget-exhausted",
                "elapsed_seconds": time.monotonic() - started_at,
                "budget_seconds": budget,
                "candidate_limit": candidate_limit,
                "generation_complete": False,
            }
        else:
            patches, generation_metadata = _node_set_generation_result_parts(
                raw_generation
            )
    patches = _order_node_set_patches_for_search(patches)
    generation_stop_reason = generation_metadata.get("stop_reason")
    generation_budget_exhausted = (
        generation_stop_reason == "budget-exhausted"
        or
        deadline is not None and time.monotonic() >= deadline
    )
    if not patches:
        if generation_budget_exhausted:
            summary = summarize_node_set_split_scores(
                function,
                request,
                [],
                [],
                threshold,
                stop_reason="budget-exhausted",
                candidate_limit=candidate_limit,
                budget_seconds=budget,
                elapsed_seconds=(
                    generation_metadata.get("elapsed_seconds")
                    or time.monotonic() - started_at
                ),
                coupled_requests=coupled_requests,
                resume_command=resume_command,
                resume_mode=resume_mode,
            )
            _node_set_split_write_summary(summary, summary_path)
            _emit_node_set_split_summary(summary, json_out=json_out)
            raise typer.Exit(4)
        generated_local_blocker = None
        if (
            coupled_requests is None
            and not is_node_set_request_introducible(request)
            and request.var_name is not None
        ):
            generated_local_blocker = _generated_pointer_walk_local_blocker(
                source_text,
                function,
                request,
            )
        if generated_local_blocker is not None:
            no_candidate_reason = (
                f"generated pointer-walk local {request.var_name} has no safe "
                "read-site source candidates"
            )
        else:
            no_candidate_reason = (
                "no coupled candidates generated (a rotation ig produced no "
                "realizable edit; the moves may share a source var)"
                if coupled_requests is not None
                else "no introduce-binding candidates generated"
                if is_node_set_request_introducible(request)
                else "no source candidates generated"
            )
        request = dataclasses.replace(
            request,
            blocked_reason=no_candidate_reason,
        )
        summary = summarize_node_set_split_scores(
            function,
            request,
            [],
            [],
            threshold,
            stop_reason=(
                "no-coupled-probes"
                if coupled_requests is not None else "no-source-probes"
            ),
            coupled_requests=coupled_requests,
            resume_mode=resume_mode,
        )
        if generated_local_blocker is not None:
            summary["source_attribution_blocker"] = generated_local_blocker
            fallback_vars = (
                generated_local_blocker.get("candidate_fallback_vars") or []
            )
            for fallback_var in fallback_vars:
                command = [
                    "melee-agent",
                    "debug",
                    "solve",
                    "node-set-split",
                    "-f",
                    function,
                    "--class",
                    register_class,
                    "--source-file",
                    str(resolved_source),
                    "--ig",
                    str(request.target_ig),
                ]
                if request.current_reg is not None:
                    command.extend(["--current-reg", request.current_reg])
                if request.target_reg is not None:
                    command.extend(["--target-reg", request.target_reg])
                command.extend(["--var", str(fallback_var), "--json"])
                summary.setdefault("next_steps", []).append(
                    "rerun node-set-split on the retained source with "
                    f"fallback var {fallback_var}: {shlex.join(command)}"
                )
        if output is not None:
            _node_set_split_write_summary(summary, summary_path)
        _emit_node_set_split_summary(summary, json_out=json_out)
        raise typer.Exit(3)
    manifest_path: Path | None = (
        _node_set_split_resume_manifest_path(resume_summary)
        if resume_summary is not None and resume_mode == "manifest"
        else None
    )
    manifest_candidate_count = len(patches) if manifest_path is not None else 0

    def ensure_manifest() -> Path:
        nonlocal manifest_candidate_count, manifest_path
        if manifest_path is None or manifest_candidate_count != len(patches):
            manifest_path = _node_set_split_write_generated_manifest(
                summary_path,
                patches,
                function=function,
                class_id=class_id,
                source_file=resolved_source,
                source_text=source_text,
                request=request,
                coupled_requests=coupled_requests,
                melee_root=DEFAULT_MELEE_ROOT,
            )
            manifest_candidate_count = len(patches)
        return manifest_path

    if (
        patches
        and manifest_path is None
        and (
            output is not None
            or retain_generated
            or budget is not None
            or resume_summary is not None
        )
    ):
        ensure_manifest()

    def emit_summary(
        summary: dict[str, Any],
        *,
        write_for_resume: bool = False,
    ) -> None:
        pending_count = int(summary.get("pending_count") or 0)
        if patches and (
            manifest_path is not None
            or pending_count > 0
            or output is not None
            or retain_generated
            or write_for_resume
        ):
            current_manifest = ensure_manifest()
            summary["manifest_path"] = str(current_manifest)
            summary["generated_candidate_manifest"] = str(current_manifest)
            summary["pending_candidates"] = (
                _node_set_split_pending_candidate_records(
                    patches,
                    summary,
                    summary_path=summary_path,
                )
            )
            if pending_count > 0:
                summary["exhaustive"] = False
        if (
            pending_count > 0
            and isinstance(summary.get("stop_condition"), dict)
            and summary["stop_condition"].get("resume_command")
        ):
            write_for_resume = True
        if output is not None or write_for_resume:
            _node_set_split_write_summary(summary, summary_path)
        _emit_node_set_split_summary(summary, json_out=json_out)

    if patches and generation_stop_reason == "budget-exhausted":
        summary = summarize_node_set_split_scores(
            function,
            request,
            patches,
            [],
            threshold,
            stop_reason="budget-exhausted",
            candidate_limit=candidate_limit,
            budget_seconds=budget,
            elapsed_seconds=(
                generation_metadata.get("elapsed_seconds")
                or time.monotonic() - started_at
            ),
            coupled_requests=coupled_requests,
            resume_command=resume_command,
            resume_mode=resume_mode,
        )
        emit_summary(summary, write_for_resume=True)
        raise typer.Exit(4)

    def backend_blocked_summary(
        failure: _NodeSetSplitPcdumpBackendFailure,
        *,
        scored: list[dict[str, Any]],
        candidate_id: str | None = None,
        retained_source: str | None = None,
    ) -> dict[str, Any]:
        blocked = summarize_node_set_split_scores(
            function,
            request,
            patches,
            scored,
            threshold,
            stop_reason=failure.stop_reason,
            candidate_limit=candidate_limit,
            budget_seconds=budget,
            elapsed_seconds=time.monotonic() - started_at,
            coupled_requests=coupled_requests,
            resume_command=resume_command,
            resume_mode=resume_mode,
        )
        blocked["status"] = "blocked"
        blocked["blocked_reason"] = str(failure)
        blocked["terminal_blocker"] = failure.terminal_blocker
        blocked["exhaustive"] = False
        blocked["retain_generated"] = retain_generated
        if candidate_id is not None:
            blocked["candidate_id"] = candidate_id
        if retained_source is not None:
            blocked["source_path"] = retained_source
        if failure.remote_fallback is not None:
            blocked["remote_fallback"] = failure.remote_fallback
        if failure.unsafe_local_pcdump_lane is not None:
            blocked["unsafe_local_pcdump_lane"] = (
                failure.unsafe_local_pcdump_lane
            )
        if failure.returncode is not None:
            blocked["returncode"] = failure.returncode
        if failure.stderr_tail:
            blocked["stderr_tail"] = failure.stderr_tail
        return blocked

    baseline_timeout = _node_set_split_remaining_timeout(
        started_at=started_at,
        budget=budget,
        per_call_timeout=float(timeout),
    )
    if baseline_timeout is None:
        summary = summarize_node_set_split_scores(
            function,
            request,
            patches,
            [],
            threshold,
            stop_reason="budget-exhausted",
            candidate_limit=candidate_limit,
            budget_seconds=budget,
            elapsed_seconds=time.monotonic() - started_at,
            coupled_requests=coupled_requests,
            resume_command=resume_command,
            resume_mode=resume_mode,
        )
        emit_summary(summary, write_for_resume=True)
        raise typer.Exit(4)

    try:
        baseline_compiled = _node_set_split_compile_signature_and_pcdump_backend(
            resolved_source,
            label="baseline",
            function=function,
            class_id=class_id,
            melee_root=DEFAULT_MELEE_ROOT,
            timeout=baseline_timeout,
            unit_source=compile_unit_source,
            full_unit_source=full_unit_source,
            need_pcdump=False,
            remote=remote,
            remote_fallback=remote_fallback,
            remote_host=remote_host,
            remote_script=remote_script,
            remote_branch=remote_branch,
            remote_no_pull=remote_no_pull,
        )
        baseline_sig = baseline_compiled.signature
    except _NodeSetSplitPcdumpBackendFailure as exc:
        summary = backend_blocked_summary(exc, scored=[])
        emit_summary(summary, write_for_resume=True)
        raise typer.Exit(3) from exc
    except Exception as exc:
        request = dataclasses.replace(
            request,
            blocked_reason=f"baseline compile failed: {exc}",
        )
        summary = summarize_node_set_split_scores(
            function,
            request,
            [],
            [],
            threshold,
            coupled_requests=coupled_requests,
            resume_mode=resume_mode,
        )
        emit_summary(summary)
        raise typer.Exit(3) from exc

    baseline_match_timeout = _node_set_split_remaining_timeout(
        started_at=started_at,
        budget=budget,
        per_call_timeout=float(timeout),
    )
    if baseline_match_timeout is None:
        summary = summarize_node_set_split_scores(
            function,
            request,
            patches,
            [],
            threshold,
            stop_reason="budget-exhausted",
            candidate_limit=candidate_limit,
            budget_seconds=budget,
            elapsed_seconds=time.monotonic() - started_at,
            coupled_requests=coupled_requests,
            resume_command=resume_command,
            resume_mode=resume_mode,
        )
        emit_summary(summary, write_for_resume=True)
        raise typer.Exit(4)

    baseline_pct, baseline_pct_error = _fresh_node_set_split_source_baseline_pct(
        source_path=resolved_source,
        unit=unit,
        function=function,
        melee_root=DEFAULT_MELEE_ROOT,
        timeout=baseline_match_timeout,
        deadline=deadline,
        compile_unit_source=compile_unit_source,
    )
    if baseline_pct is None:
        request = dataclasses.replace(
            request,
            blocked_reason=(
                baseline_pct_error
                or "could not refresh baseline match percent"
            ),
        )
        summary = summarize_node_set_split_scores(
            function,
            request,
            [],
            [],
            threshold,
            coupled_requests=coupled_requests,
            resume_mode=resume_mode,
        )
        emit_summary(summary)
        raise typer.Exit(3)

    scored_candidates: list[dict[str, Any]] = []
    stop_reason: str | None = (
        "candidate-limit" if generation_stop_reason == "candidate-limit" else None
    )
    probe_root = (
        DEFAULT_MELEE_ROOT
        / "build"
        / "mwcc_debug_cache"
        / "probes"
        / "node_set_split"
    )
    probe_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="node_set_split_",
        dir=probe_root,
    ) as temp_name:
        temp_dir = Path(temp_name)
        seen_patch_sources = {patch.patched_source for patch in patches}
        patch_index = 0
        while patch_index < len(patches):
            patch = patches[patch_index]
            patch_index += 1
            if (
                candidate_limit is not None
                and len(scored_candidates) >= candidate_limit
            ):
                stop_reason = "candidate-limit"
                break
            source_rejection_reason = getattr(patch, "metadata", {}).get(
                "source_rejection_reason"
            )
            if source_rejection_reason:
                objective = {
                    "status": "source-rejected",
                    "source_rejection_reason": source_rejection_reason,
                    "error": source_rejection_reason,
                }
                score = CandidateScore(
                    patch.candidate_id,
                    compile_ok=False,
                    checkdiff_pct=None,
                    checkdiff_delta=None,
                    pcdump_score_delta=None,
                    diagnostics_path=None,
                    status="source-rejected",
                    score_reason=source_rejection_reason,
                )
                scored_candidates.append({
                    "score": score,
                    "objective": objective,
                })
                continue
            candidate_timeout = _node_set_split_remaining_timeout(
                started_at=started_at,
                budget=budget,
                per_call_timeout=float(timeout),
            )
            if candidate_timeout is None:
                stop_reason = "budget-exhausted"
                break
            candidate_path: Path | None = None
            try:
                candidate_path = (
                    temp_dir / f"{_safe_filename(patch.candidate_id)}.c"
                )
                candidate_path.write_text(patch.patched_source, encoding="utf-8")
                compiled = _node_set_split_compile_signature_and_pcdump_backend(
                    candidate_path,
                    label=patch.candidate_id,
                    function=function,
                    class_id=class_id,
                    melee_root=DEFAULT_MELEE_ROOT,
                    timeout=candidate_timeout,
                    unit_source=compile_unit_source,
                    full_unit_source=full_unit_source,
                    need_pcdump=True,
                    remote=remote,
                    remote_fallback=remote_fallback,
                    remote_host=remote_host,
                    remote_script=remote_script,
                    remote_branch=remote_branch,
                    remote_no_pull=remote_no_pull,
                )
                candidate_sig = compiled.signature
                candidate_pcdump_text = compiled.pcdump_text
                if coupled_requests is not None:
                    objective = evaluate_coupled_node_set_split_signature(
                        baseline_sig,
                        candidate_sig,
                        coupled_requests,
                        force_phys=force_phys_targets,
                    )
                else:
                    objective = evaluate_node_set_split_signature(
                        baseline_sig,
                        candidate_sig,
                        request,
                        force_phys=force_phys_targets,
                    )
                if compiled.remote_fallback is not None:
                    objective["remote_fallback"] = compiled.remote_fallback
                if compiled.unsafe_local_pcdump_lane is not None:
                    objective["unsafe_local_pcdump_lane"] = (
                        compiled.unsafe_local_pcdump_lane
                    )
                if (
                    objective.get("status") == "wrong-register"
                    and candidate_pcdump_text is not None
                ):
                    candidate_ig = tb.load_ig(
                        candidate_pcdump_text,
                        function,
                        class_id=class_id,
                    )
                    if candidate_ig is not None:
                        objective = annotate_target_color_select_order_leads(
                            objective,
                            candidate_ig,
                            coupled_requests or [request],
                        )
            except _NodeSetSplitPcdumpBackendFailure as exc:
                retained_source = None
                if candidate_path is not None and candidate_path.exists():
                    try:
                        diagnostics_path = _retain_node_set_split_failed_source(
                            candidate_path,
                            candidate_id=patch.candidate_id,
                            probe_root=probe_root,
                        )
                        retained_source = str(diagnostics_path)
                    except OSError:
                        retained_source = str(candidate_path)
                summary = backend_blocked_summary(
                    exc,
                    scored=scored_candidates,
                    candidate_id=patch.candidate_id,
                    retained_source=retained_source,
                )
                emit_summary(summary, write_for_resume=True)
                raise typer.Exit(3) from exc
            except Exception as exc:
                try:
                    if candidate_path is None or not candidate_path.exists():
                        diagnostics_path = None
                        score_reason = str(exc)
                    else:
                        diagnostics_path = _retain_node_set_split_failed_source(
                            candidate_path,
                            candidate_id=patch.candidate_id,
                            probe_root=probe_root,
                        )
                        score_reason = str(exc)
                except OSError as retain_exc:
                    diagnostics_path = None
                    score_reason = (
                        f"{exc}; failed to retain candidate source: {retain_exc}"
                    )
                objective = {"status": "compile-failed", "error": str(exc)}
                if diagnostics_path is not None:
                    objective["source_path"] = str(diagnostics_path)
                score = CandidateScore(
                    patch.candidate_id,
                    compile_ok=False,
                    checkdiff_pct=None,
                    checkdiff_delta=None,
                    pcdump_score_delta=None,
                    diagnostics_path=diagnostics_path,
                    status="compile-failed",
                    score_reason=score_reason,
                )
                scored_candidates.append({
                    "score": score,
                    "objective": objective,
                })
                continue

            source_retained: str | None = None
            pcdump_retained: str | None = None
            source_hunk = getattr(patch, "hunk", None) or None
            should_retain_probe = (
                retain_generated
                or _node_set_split_target_score_hits(objective) > 0
            )
            if objective.get("status") == "realized":
                if source_hunk is not None:
                    objective["source_hunk"] = source_hunk
                try:
                    retained_path = _retain_node_set_split_source(
                        candidate_path,
                        candidate_id=patch.candidate_id,
                        probe_root=probe_root,
                        reason="realized",
                    )
                    source_retained = str(retained_path)
                    objective["source_path"] = source_retained
                except OSError as retain_exc:
                    objective["source_retention_error"] = str(retain_exc)
                if candidate_pcdump_text is not None:
                    try:
                        retained_pcdump = _retain_node_set_split_pcdump(
                            candidate_pcdump_text,
                            candidate_id=patch.candidate_id,
                            probe_root=probe_root,
                            reason="realized",
                        )
                        pcdump_retained = str(retained_pcdump)
                        objective["pcdump_path"] = pcdump_retained
                    except OSError as retain_exc:
                        objective["pcdump_retention_error"] = str(retain_exc)
                score_timeout = _node_set_split_remaining_timeout(
                    started_at=started_at,
                    budget=budget,
                    per_call_timeout=float(timeout),
                )
                if score_timeout is None:
                    stop_reason = "budget-exhausted"
                    score = CandidateScore(
                        patch.candidate_id,
                        compile_ok=False,
                        checkdiff_pct=None,
                        checkdiff_delta=None,
                        pcdump_score_delta=None,
                        diagnostics_path=None,
                        status="budget-exhausted",
                        score_reason="budget exhausted before checkdiff scoring",
                    )
                    scored_candidates.append({
                        "score": score,
                        "objective": objective,
                    })
                    break
                score = _score_node_set_split_candidate(
                    patch,
                    function=function,
                    source_path=compile_unit_source,
                    baseline_pct=baseline_pct,
                    melee_root=DEFAULT_MELEE_ROOT,
                    timeout=score_timeout,
                    temp_dir=temp_dir,
                    deadline=deadline,
                    full_unit_source=full_unit_source,
                )
            else:
                if objective.get("status") == "wrong-register":
                    try:
                        retained_path = _retain_node_set_split_source(
                            candidate_path,
                            candidate_id=patch.candidate_id,
                            probe_root=probe_root,
                            reason="wrong_register",
                        )
                        source_retained = str(retained_path)
                        objective["source_path"] = source_retained
                    except OSError as retain_exc:
                        objective["source_retention_error"] = str(retain_exc)
                    if candidate_pcdump_text is not None:
                        try:
                            retained_pcdump = _retain_node_set_split_pcdump(
                                candidate_pcdump_text,
                                candidate_id=patch.candidate_id,
                                probe_root=probe_root,
                                reason="wrong_register",
                            )
                            pcdump_retained = str(retained_pcdump)
                            objective["pcdump_path"] = pcdump_retained
                        except OSError as retain_exc:
                            objective["pcdump_retention_error"] = str(retain_exc)
                elif should_retain_probe:
                    retain_reason = (
                        "target_score"
                        if _node_set_split_target_score_hits(objective) > 0
                        else "retained"
                    )
                    try:
                        retained_path = _retain_node_set_split_source(
                            candidate_path,
                            candidate_id=patch.candidate_id,
                            probe_root=probe_root,
                            reason=retain_reason,
                        )
                        source_retained = str(retained_path)
                        objective["source_path"] = source_retained
                    except OSError as retain_exc:
                        objective["source_retention_error"] = str(retain_exc)
                    if candidate_pcdump_text is not None:
                        try:
                            retained_pcdump = _retain_node_set_split_pcdump(
                                candidate_pcdump_text,
                                candidate_id=patch.candidate_id,
                                probe_root=probe_root,
                                reason=retain_reason,
                            )
                            pcdump_retained = str(retained_pcdump)
                            objective["pcdump_path"] = pcdump_retained
                        except OSError as retain_exc:
                            objective["pcdump_retention_error"] = str(retain_exc)
                score = CandidateScore(
                    patch.candidate_id,
                    compile_ok=True,
                    checkdiff_pct=None,
                    checkdiff_delta=None,
                    pcdump_score_delta=None,
                    diagnostics_path=None,
                    status="objective-failed",
                    score_reason=str(objective.get("status")),
                )
                if objective.get("status") == "wrong-register":
                    steering_children = _node_set_split_steering_children(
                        patch,
                        function=function,
                        unit=unit,
                        coupled_requests=coupled_requests or [request],
                        seen_sources=seen_patch_sources,
                        objective=objective,
                    )
                    if steering_children:
                        patches[patch_index:patch_index] = steering_children
            scored_entry = {
                "score": score,
                "objective": objective,
            }
            if source_retained is not None:
                scored_entry["source_retained"] = source_retained
            if pcdump_retained is not None:
                scored_entry["pcdump_path"] = pcdump_retained
            if source_hunk is not None:
                scored_entry["source_hunk"] = source_hunk
            scored_candidates.append(scored_entry)

    generation_limit_reached = (
        candidate_limit is not None and len(patches) >= candidate_limit
    )
    summary = summarize_node_set_split_scores(
        function,
        request,
        patches,
        scored_candidates,
        threshold,
        stop_reason=stop_reason,
        candidate_limit=candidate_limit,
        budget_seconds=budget,
        elapsed_seconds=time.monotonic() - started_at,
        coupled_requests=coupled_requests,
        resume_command=(
            resume_command
            if stop_reason in {"candidate-limit", "budget-exhausted"}
            or generation_limit_reached
            else None
        ),
        resume_mode=resume_mode,
    )
    summary["retain_generated"] = retain_generated

    apply_error: str | None = None
    if apply_best and summary.get("status") == "improved":
        best_id = summary.get("best_candidate_id")
        best_patch = next(
            (patch for patch in patches if patch.candidate_id == best_id),
            None,
        )
        if best_patch is None:
            apply_error = f"best candidate disappeared: {best_id}"
        else:
            apply_timeout = _node_set_split_remaining_timeout(
                started_at=started_at,
                budget=budget,
                per_call_timeout=float(timeout),
            )
            if apply_timeout is None:
                apply_error = "budget exhausted before applying best candidate"
            else:
                applied_pct, apply_error = _apply_node_set_split_patch(
                    best_patch,
                    function=function,
                    unit=unit,
                    source_path=compile_unit_source,
                    melee_root=DEFAULT_MELEE_ROOT,
                    timeout=apply_timeout,
                    deadline=deadline,
                    full_unit_source=full_unit_source,
                )
        if best_patch is not None and apply_error is None:
            summary["applied"] = True
            summary["applied_candidate_id"] = best_id
            summary["applied_checkdiff_pct"] = applied_pct
        elif best_patch is not None:
            summary["applied"] = False
            summary["apply_error"] = apply_error

    emit_summary(
        summary,
        write_for_resume=(
            isinstance(summary.get("stop_condition"), dict)
            and bool(summary["stop_condition"].get("resume_command"))
        ),
    )
    if apply_error is not None:
        raise typer.Exit(5)
    if summary.get("status") == "improved":
        raise typer.Exit(0)
    if summary.get("status") == "blocked":
        raise typer.Exit(3)
    raise typer.Exit(4)
