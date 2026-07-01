"""`debug mutate ...` — focused source mutations for match-percent improvement.

Carved out of cli/debug/__init__.py. Contains the mutate_app Typer instance,
all 10 mutate command handlers, and their mutate-only private helpers.

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
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Callable, Iterable, Mapping, Optional

import typer

from .._common import DEFAULT_MELEE_ROOT
from ...mwcc_debug import (
    FunctionEvents,
    derive_target_from_function,
    find_function,
    parse_hook_events,
    parse_pcdump,
    score_function,
)
from ...mwcc_debug.diff_capture import CompileFailure
from ...mwcc_debug.frame_reservations import (
    analyze_frame_from_asm_text,
    analyze_frame_from_function,
    analyze_frame_reservations,
    evaluate_frame_transform_probe_results,
)
from ...mwcc_debug.source_patch import find_function as find_source_function
from ...mwcc_debug.pressure_explorer import HELPER_INLINE_LIFETIME_OPERATORS
from ...mwcc_debug.source_patch import (
    build_decl_order_candidates_for_scope,
    explain_decl_reorder_skip,
    get_decl_names_by_scope,
    reorder_decls_in_function_scope,
)

mutate_app = typer.Typer(
    help="Apply focused source mutations on specific variables or decls."
)

__all__: list[str] = [
    "mutate_app",
    "DeclCandidateFailure",
    "RankMode",
    "_control_flow_compile_source_variant",
    "_decl_order_candidate_count",
    "_flush_stdout_report",
    "_FPR_SELECT_ORDER_TRANSFORM_FAMILIES",
    "_GPR_SELECT_ORDER_TRANSFORM_FAMILIES",
    "_indexed_struct_checkdiff_hint",
    "_indexed_struct_compile_source_variant",
    "_parse_diagnose_force_phys",
    "_read_source_for",
    "_render_combined_score_ranking",
    "_render_gate_rejected_distribution",
    "_render_lex_ranking",
    "_render_triage_ranking",
    "_run_triage_subprocess",
    "_simplify_retained_probe_records",
    "_SimplifyRetainInterrupted",
    "_TriageResult",
    "_score_lifetime_layout_expression_score",
    "_score_lifetime_layout_objective",
    "_select_decl_order_scope",
]


def _source_hunks_for_probe(
    base_source: str | None,
    candidate_source: str,
    label: str,
) -> list[dict[str, object]]:
    if base_source is None:
        return []
    from ...mwcc_debug.source_hunks import diff_line_hunks

    safe_label = re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_") or "h"
    return [
        hunk.to_dict()
        for hunk in diff_line_hunks(
            base_source,
            candidate_source,
            hunk_prefix=f"{safe_label}_h",
        )
    ]


def _lifetime_layout_probe_source_hunks(
    *,
    probe: Any | None,
    base_source: str | None,
    candidate_source: str,
    label: str,
) -> list[dict[str, object]]:
    provenance = getattr(probe, "provenance", None)
    if isinstance(provenance, Mapping):
        payload = provenance.get("payload")
        if isinstance(payload, Mapping):
            source_hunks = payload.get("source_hunks")
            if isinstance(source_hunks, list) and source_hunks:
                return [dict(hunk) for hunk in source_hunks if isinstance(hunk, Mapping)]
        source_hunks = provenance.get("source_hunks")
        if isinstance(source_hunks, list) and source_hunks:
            return [dict(hunk) for hunk in source_hunks if isinstance(hunk, Mapping)]
    return _source_hunks_for_probe(base_source, candidate_source, label)


def _write_retained_pcdump(path: Path, pcdump_text: str | None) -> str | None:
    if not pcdump_text:
        return None
    pcdump_path = path.with_suffix(".pcdump.txt")
    pcdump_path.write_text(pcdump_text, encoding="utf-8")
    return str(pcdump_path)


def _compact_checkdiff_payload(
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    compact: dict[str, Any] = {}
    if "match" in payload:
        compact["match"] = payload.get("match")
    for key in ("match_percent", "fuzzy_match_percent"):
        if key in payload:
            compact[key] = payload.get(key)
    classification = payload.get("classification")
    if isinstance(classification, Mapping):
        compact_classification: dict[str, Any] = {
            "primary": classification.get("primary")
        }
        classification_truth_gate = classification.get("structural_truth_gate")
        if isinstance(classification_truth_gate, Mapping):
            compact_classification["structural_truth_gate"] = {
                "normalized_diff_lines": classification_truth_gate.get(
                    "normalized_diff_lines"
                )
            }
        compact["classification"] = compact_classification
    truth_gate = payload.get("structural_truth_gate")
    if isinstance(truth_gate, Mapping):
        compact["structural_truth_gate"] = {
            "normalized_diff_lines": truth_gate.get("normalized_diff_lines")
        }
    structural = payload.get("structural")
    if isinstance(structural, Mapping):
        compact["structural"] = {
            "opcode_similarity": structural.get("opcode_similarity")
        }
    frame_keys = {
        key: payload.get(key)
        for key in (
            "current_frame_size",
            "target_frame_size",
            "frame_size",
            "expected_frame_size",
        )
        if key in payload
    }
    if frame_keys:
        compact["frame"] = frame_keys
    return compact or None


def _checkdiff_match_percent(payload: Mapping[str, Any] | None) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("match_percent", "fuzzy_match_percent", "final_match_percent"):
        value = payload.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return None


def _checkdiff_normalized_diff_lines(
    payload: Mapping[str, Any] | None,
) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    for container in (
        payload.get("structural_truth_gate"),
        (
            payload.get("classification", {}).get("structural_truth_gate")
            if isinstance(payload.get("classification"), Mapping)
            else None
        ),
    ):
        if isinstance(container, Mapping):
            value = container.get("normalized_diff_lines")
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


def _control_flow_baseline_from_checkdiff(
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "match_percent": _checkdiff_match_percent(payload),
        "normalized_diff_lines": _checkdiff_normalized_diff_lines(payload),
    }


def _control_flow_checkdiff_delta(
    *,
    variant: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(baseline, Mapping):
        return None
    candidate_match = variant.get("final_match_percent")
    if candidate_match is None:
        candidate_match = variant.get("match_percent")
    if candidate_match is None:
        checkdiff = variant.get("checkdiff")
        candidate_match = (
            _checkdiff_match_percent(checkdiff)
            if isinstance(checkdiff, Mapping)
            else None
        )
    candidate_ndiff = None
    checkdiff = variant.get("checkdiff")
    if isinstance(checkdiff, Mapping):
        candidate_ndiff = _checkdiff_normalized_diff_lines(checkdiff)

    delta: dict[str, Any] = {}
    baseline_match = baseline.get("match_percent")
    if baseline_match is not None and candidate_match is not None:
        try:
            delta["match_percent"] = float(candidate_match) - float(baseline_match)
        except (TypeError, ValueError):
            pass
    baseline_ndiff = baseline.get("normalized_diff_lines")
    if baseline_ndiff is not None and candidate_ndiff is not None:
        try:
            delta["normalized_diff_lines"] = int(candidate_ndiff) - int(baseline_ndiff)
        except (TypeError, ValueError):
            pass
    return delta or None


def _control_flow_variant_improved_baseline(variant: Mapping[str, Any]) -> bool:
    delta = variant.get("checkdiff_delta")
    if not isinstance(delta, Mapping):
        return False
    ndiff_delta = delta.get("normalized_diff_lines")
    if ndiff_delta is not None:
        try:
            return int(ndiff_delta) < 0
        except (TypeError, ValueError):
            pass
    match_delta = delta.get("match_percent")
    if match_delta is not None:
        try:
            if float(match_delta) > 0.0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _control_flow_probe_metadata(probe: Any) -> dict[str, Any]:
    if isinstance(probe, Mapping):
        provenance = probe.get("provenance")
    else:
        provenance = getattr(probe, "provenance", None)
    if not isinstance(provenance, Mapping):
        return {}
    metadata: dict[str, Any] = {}
    for key in ("family_id", "suggestion_kind"):
        value = provenance.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def _control_flow_attach_probe_metadata(payload: dict[str, Any]) -> None:
    payload.update(_control_flow_probe_metadata(payload))


@mutate_app.command(name="decl-orders")
def enumerate_decl_orders(
    function: Annotated[
        str,
        typer.Argument(help="Function name to enumerate orderings for"),
    ],
    strategy: Annotated[
        str,
        typer.Option(
            "--strategy",
            help="Which orderings to try: 'promote' (move each var to "
                 "first plus bounded group/pair promotions), "
                 "'demote' (move each to last; N), "
                 "'swap' (adjacent pair swaps; N-1), 'all' (promote+demote+"
                 "swap), or 'full' (every permutation; N! — refuses for N>7).",
        ),
    ] = "promote",
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (percentage points) to consider a win. "
                 "Default 0.05 — catches the +0.05-0.09% chain wins that "
                 "matching agents observed permuter producing.",
        ),
    ] = 0.05,
    keep_best: Annotated[
        bool,
        typer.Option(
            "--keep-best",
            help="If the best ordering improves match% by ≥threshold, "
                 "leave it applied. Default reverts to original.",
        ),
    ] = False,
    iterate: Annotated[
        bool,
        typer.Option(
            "--iterate",
            help="After finding the best ordering, apply it and re-run "
                 "the enumeration from the new baseline. Repeats until no "
                 "improvement found (or --iterate-max reached). Stacks "
                 "small wins below the per-iteration threshold. Implies "
                 "--keep-best.",
        ),
    ] = False,
    iterate_max: Annotated[
        int,
        typer.Option(
            "--iterate-max",
            help="Cap on --iterate rounds. Prevents infinite loops if a "
                 "win-finding cycle emerges. Default 10.",
        ),
    ] = 10,
    iterate_threshold: Annotated[
        float,
        typer.Option(
            "--iterate-threshold",
            help="Per-round threshold when --iterate is set. Smaller than "
                 "--threshold lets the loop stack micro-wins (0.04% type) "
                 "that don't qualify as a single big win.",
        ),
    ] = 0.01,
    scope: Annotated[
        Optional[str],
        typer.Option(
            "--scope",
            help="Optional scope_path display string. When omitted, "
                 "enumerates the function-top scope first.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit results as JSON."),
    ] = False,
) -> None:
    """Tier 7b: enumerate local-decl orderings, find ones that improve match%.

    Most "stuck near 99%" cases have a 1-line declaration-reorder fix that
    permuter eventually finds at ~2000 iterations. This command brute-forces
    the small decl-order search space directly.

    Strategies (in order of cost):

      promote (default): for each of N locals, try promoting to position 0
        → N candidates, ~N×6sec
      demote: each → position N-1 → N candidates
      swap: each adjacent pair swap → N-1 candidates
      all: promote + demote + swap → ~3N candidates
      full: all N! permutations (refuses for N>7 — would take hours)

    Default reverts after enumeration. Pass --keep-best to apply the best
    winning ordering.
    """
    from src.cli.debug import (
        _build_and_match_with_diagnostic,
        _compute_melee_root,
        _find_unit_for_function,
        _get_match_pct,
    )
    melee_root = _compute_melee_root()
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    orig = target_path.read_text()
    scope_map = get_decl_names_by_scope(orig, function)
    available_scopes = [
        {
            "scope": "/".join(scope_path),
            "names": names,
            "declaration_count": len(names),
            "is_top_level": scope_path == (function,),
        }
        for scope_path, names in scope_map.items()
    ]
    selected_scope_reason = "explicit" if scope else "function-top"
    if scope:
        selected_scope = tuple(scope.split("/"))
    else:
        selected_scope = (function,)
        if not scope_map.get(selected_scope):
            nested_scopes = [
                scope_path
                for scope_path, names in scope_map.items()
                if scope_path != (function,) and len(names) >= 2
            ]
            if not nested_scopes:
                nested_scopes = [
                    scope_path
                    for scope_path in scope_map
                    if scope_path != (function,)
                ]
            if nested_scopes:
                selected_scope = nested_scopes[0]
                selected_scope_reason = "auto-nested"
    names = scope_map.get(selected_scope)
    if not names:
        available = ", ".join(
            f"{item['scope']} ({len(item['names'])} decls)"
            for item in available_scopes
        ) or "none"
        typer.echo(
            f"could not find a declaration block in {function} scope "
            f"{'/'.join(selected_scope)}. Available scopes: {available}.",
            err=True,
        )
        raise typer.Exit(3)
    n = len(names)

    if strategy == "full":
        if n > 7:
            typer.echo(
                f"--strategy full refused: {n} locals = {n}! permutations. "
                f"Use --strategy all for a tractable subset.",
                err=True,
            )
            raise typer.Exit(4)
    candidates = [
        (candidate.label, candidate.order)
        for candidate in build_decl_order_candidates_for_scope(
            orig,
            function,
            selected_scope,
            strategy,
        )
    ]
    if not candidates and strategy not in ("promote", "demote", "swap", "all", "full"):
        typer.echo(f"unknown --strategy: {strategy}", err=True)
        raise typer.Exit(2)
    if not candidates:
        typer.echo("no candidate orderings to try (function may have only 1 local).")
        return

    # Baseline match%. Rebuild the current source first so the result table
    # compares candidates against the actual working tree, not a stale report.
    baseline, baseline_diagnostic = _build_and_match_with_diagnostic(
        unit,
        function,
        melee_root,
    )
    if baseline is None:
        baseline = _get_match_pct(function, melee_root) or 0.0
    if not json_out:
        print(f"Function:    {function} ({n} locals: {', '.join(names)})")
        print(f"Source:      {target_path}")
        print(f"Scope:       {'/'.join(selected_scope)} ({selected_scope_reason})")
        print(f"Strategy:    {strategy} ({len(candidates)} candidates)")
        print(f"Baseline:    {baseline:.2f}%")
        if iterate:
            print(f"Mode:        --iterate (max {iterate_max} rounds, "
                  f"per-round threshold {iterate_threshold:.3f}%)")
        print()

    # When --iterate is set we want to stack wins. Each round:
    #   1. Re-read `current` as the baseline-of-the-round
    #   2. Sweep all candidates against it
    #   3. If best > iterate_threshold, apply it as the new baseline
    #   4. Else, terminate the iterate loop
    # If --iterate is NOT set, we just do one round and use the larger
    # --threshold to decide whether to apply (controlled by --keep-best).

    def run_one_round(round_idx: int, current_text: str,
                      round_baseline: float, round_threshold: float
                      ) -> tuple[Optional[str], float, Optional[list[int]], list[dict]]:
        """Run one enumeration sweep starting from `current_text`.

        Returns (best_label, best_pct, best_perm, per-candidate results).
        """
        r_results: list[dict] = []
        r_best_pct = round_baseline
        r_best_label: Optional[str] = None
        r_best_perm: Optional[list[int]] = None

        if iterate and not json_out:
            print(f"== Round {round_idx} ==")
            print(f"  Baseline: {round_baseline:.2f}%")

        for candidate_idx, (label, perm) in enumerate(candidates, start=1):
            if json_out:
                print(
                    f"[decl-orders] {candidate_idx}/{len(candidates)} {label}",
                    file=sys.stderr,
                    flush=True,
                )
            patched = reorder_decls_in_function_scope(
                current_text, function, selected_scope, perm,
            )
            if patched is None:
                reason = explain_decl_reorder_skip(
                    current_text, function, selected_scope, perm,
                )
                detail = f"skipped: {reason}" if reason else "skipped"
                if not json_out:
                    print(f"  {label}: {detail}")
                r_results.append({
                    "label": label,
                    "match_pct": None,
                    "delta": None,
                    "skipped": True,
                    "skip_reason": reason,
                })
                continue
            target_path.write_text(patched)
            pct, diagnostic = _build_and_match_with_diagnostic(
                unit,
                function,
                melee_root,
            )
            target_path.write_text(current_text)  # revert before next iter
            if pct is None:
                diagnostic = diagnostic or "build failed without diagnostic"
                if not json_out:
                    print(f"  {label}: BUILD FAILED: {diagnostic}")
                r_results.append({
                    "label": label,
                    "match_pct": None,
                    "delta": None,
                    "build_failed": True,
                    "diagnostic": diagnostic,
                })
                continue
            delta = pct - round_baseline
            r_results.append({"label": label, "match_pct": pct,
                              "delta": delta})
            tag = ""
            # epsilon: 91.64-91.59 = 0.04999... in IEEE float; without
            # tolerance a real +0.05 win at threshold 0.05 silently drops.
            if delta >= round_threshold - 1e-9:
                tag = "  WIN"
                if pct > r_best_pct:
                    r_best_pct = pct
                    r_best_label = label
                    r_best_perm = perm
            elif delta > 0:
                tag = "  (improved)"
            elif delta < 0:
                tag = "  (worse)"
            if not json_out:
                print(f"  {label}: {pct:.2f}%  delta={delta:+.2f}%{tag}")
        return r_best_label, r_best_pct, r_best_perm, r_results

    all_rounds: list[dict] = []
    current = orig
    current_pct = baseline
    applied_chain: list[str] = []  # labels of rounds that we kept
    applied_single_best = False

    try:
        if not iterate:
            # Single sweep — preserve previous behavior.
            best_label, best_pct, best_perm, results = run_one_round(
                round_idx=0,
                current_text=current,
                round_baseline=baseline,
                round_threshold=threshold,
            )
            all_rounds.append({
                "round": 0,
                "baseline_pct": baseline,
                "best_label": best_label,
                "best_pct": best_pct,
                "results": results,
            })
            if keep_best and best_label is not None and best_perm is not None:
                patched = reorder_decls_in_function_scope(
                    current, function, selected_scope, best_perm,
                )
                if patched is not None:
                    current = patched
                    applied_single_best = True
        else:
            # Iterate mode: each round must clear iterate_threshold to
            # continue. We always commit the win for the round (writes
            # back to disk before next sweep).
            for r_idx in range(iterate_max):
                r_best_label, r_best_pct, r_best_perm, r_results = (
                    run_one_round(
                        round_idx=r_idx,
                        current_text=current,
                        round_baseline=current_pct,
                        round_threshold=iterate_threshold,
                    )
                )
                all_rounds.append({
                    "round": r_idx,
                    "baseline_pct": current_pct,
                    "best_label": r_best_label,
                    "best_pct": r_best_pct,
                    "results": r_results,
                })
                if r_best_label is None or r_best_perm is None:
                    if not json_out:
                        print(f"  No more wins; stopping iterate loop.")
                    break
                # Apply the round's winner and use it as the next baseline
                patched = reorder_decls_in_function_scope(
                    current, function, selected_scope, r_best_perm,
                )
                if patched is None:
                    if not json_out:
                        print(f"  Could not re-apply best perm "
                              f"({r_best_label}); stopping.")
                    break
                current = patched
                current_pct = r_best_pct
                applied_chain.append(r_best_label)
                if not json_out:
                    print(f"  ** Applied {r_best_label}; new baseline "
                          f"{current_pct:.2f}%")
                    print()
            # After the loop, `current` holds the latest patched text.
            # The top-level best_pct/best_label reflect the cumulative
            # state vs the original baseline.
            best_pct = current_pct
            best_label = (" + ".join(applied_chain)
                          if applied_chain else None)
            best_perm = None  # n/a in iterate mode — we already applied
    finally:
        # Decide whether the disk-state to keep is the accumulated `current`
        # (iterate mode with at least one winning round; or single-sweep
        # with --keep-best after a successful win) or the original.
        had_wins = bool(applied_chain) if iterate else (
            applied_single_best
        )
        keep_final = had_wins and current != orig
        if keep_final:
            target_path.write_text(current)
            if iterate and not json_out:
                typer.echo(
                    f"[mwcc_debug] iterate kept {len(applied_chain)} "
                    f"winning round(s).",
                    err=True,
                )
        else:
            # No wins (or single-sweep without --keep-best). Always revert
            # to the original, regardless of any intermediate writes the
            # candidate loop might have done. The per-candidate revert in
            # run_one_round should leave disk at the round's baseline
            # already, but write `orig` defensively so we're independent
            # of that contract.
            current_disk = target_path.read_text()
            if current_disk != orig:
                target_path.write_text(orig)
                if not json_out:
                    typer.echo(
                        f"[mwcc_debug] reverted source (no wins above "
                        f"threshold).",
                        err=True,
                    )
        subprocess.run(
            ["ninja", f"build/GALE01/src/{unit}.o",
             "build/GALE01/report.json"],
            cwd=melee_root, capture_output=True,
        )

    if json_out:
        print(json.dumps({
            "function": function,
            "scope": "/".join(selected_scope),
            "selected_scope_reason": selected_scope_reason,
            "available_scopes": available_scopes,
            "baseline_pct": baseline,
            "baseline_diagnostic": baseline_diagnostic,
            "best_label": best_label,
            "best_pct": best_pct,
            "iterate": iterate,
            "applied_chain": applied_chain if iterate else [],
            "rounds": all_rounds,
        }, indent=2))
        return

    print()
    if best_label is None:
        if iterate:
            print(f"No wins clearing iterate-threshold "
                  f"{iterate_threshold:.3f}% in any round.")
        else:
            print(f"No ordering improved match by ≥{threshold:.2f}%.")
        return
    print(f"Best: {best_label} → {best_pct:.2f}% "
          f"(delta {best_pct - baseline:+.2f}%)")

    if iterate:
        print(f"Applied {len(applied_chain)} round(s) to {target_path}. "
              f"Verify with `git diff`.")
    elif keep_best and applied_single_best:
        print(f"Applied to {target_path}. Verify with `git diff`.")
    else:
        print("Source reverted. Re-run with --keep-best to apply the win.")



def _decl_order_candidate_count(
    source: str,
    function: str,
    scope_path: tuple[str, ...],
    strategy: str,
) -> int:
    names = get_decl_names_by_scope(source, function).get(scope_path) or []
    n = len(names)
    if strategy in ("promote", "all", "full"):
        return len(
            build_decl_order_candidates_for_scope(
                source,
                function,
                scope_path,
                strategy,
            )
        )
    if strategy in ("promote", "demote", "swap"):
        return max(0, n - 1)
    if strategy == "all":
        return max(0, 3 * (n - 1))
    if strategy == "full":
        import math
        return max(0, math.factorial(n) - 1)
    return 0


def _select_decl_order_scope(
    scope_map: dict[tuple[str, ...], list[str]],
    function: str,
    *,
    explicit_scope: str | None = None,
) -> tuple[tuple[str, ...], str]:
    if explicit_scope:
        return tuple(explicit_scope.split("/")), "explicit"
    selected_scope = (function,)
    selected_scope_reason = "function-top"
    if not scope_map.get(selected_scope):
        nested_scopes = [
            scope_path
            for scope_path, names in scope_map.items()
            if scope_path != (function,) and len(names) >= 2
        ]
        if not nested_scopes:
            nested_scopes = [
                scope_path
                for scope_path in scope_map
                if scope_path != (function,)
            ]
        if nested_scopes:
            selected_scope = nested_scopes[0]
            selected_scope_reason = "auto-nested"
    return selected_scope, selected_scope_reason








@dataclasses.dataclass(frozen=True)
class DiagnoseForcePhysEntry:
    class_id: int | None
    virtual: int
    phys: int
    token: str


def _parse_diagnose_force_phys(
    raw: str,
) -> tuple[list[DiagnoseForcePhysEntry], str, list[str]]:
    """Parse a diagnose-only force-phys proof vector."""
    from src.cli.debug import (
        _normalize_force_phys,
        _parse_force_phys_class,
        _parse_force_vector_int,
        _parse_force_vector_phys,
    )
    normalized, warnings = _normalize_force_phys(raw)
    entries: list[DiagnoseForcePhysEntry] = []
    for token in normalized.split(","):
        token = token.strip()
        if not token:
            continue
        parts = token.split(":")
        try:
            if len(parts) == 3:
                class_id = _parse_force_phys_class(parts[0])
                virtual = _parse_force_vector_int(parts[1], prefix="ig")
                phys = _parse_force_vector_phys(parts[2])
            elif len(parts) == 2:
                class_id = None
                virtual = _parse_force_vector_int(parts[0], prefix="ig")
                phys = _parse_force_vector_phys(parts[1])
            else:
                raise ValueError(
                    "expected IG:PHYS or CLASS:IG:PHYS"
                )
        except ValueError as exc:
            raise typer.BadParameter(
                f"--force-phys entry {token!r} is invalid: {exc}"
            ) from exc
        entries.append(DiagnoseForcePhysEntry(
            class_id=class_id,
            virtual=virtual,
            phys=phys,
            token=token,
        ))
    if not entries:
        raise typer.BadParameter("--force-phys did not contain any entries")
    return entries, normalized, warnings

@dataclasses.dataclass(frozen=True)
class DeclCandidateFailure:
    status: str
    diagnostic: Optional[str] = None
    candidate_path: Optional[Path] = None


def _read_source_for(function: str, melee_root: Path) -> tuple[Path, str]:
    from src.cli.debug import _find_unit_for_function
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    p = melee_root / "src" / f"{unit}.c"
    return p, p.read_text()


@mutate_app.command(name="type-change")
def mutate_type_change_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function containing the variable.",
        ),
    ],
    var: Annotated[
        str,
        typer.Option("--var", help="Local variable name to retype."),
    ],
    new_type: Annotated[
        str,
        typer.Option("--type", help="New type string (e.g., 'u32')."),
    ],
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file to mutate instead of resolving from report.json.",
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Write the mutated source back to the file. "
                 "Default: print to stdout.",
        ),
    ] = False,
    diff: Annotated[
        bool,
        typer.Option("--diff", help="Print a focused unified diff instead of the full mutated source."),
    ] = False,
) -> None:
    """Change a local variable's declared type."""
    from src.cli.debug import _format_source_diff, _read_source_for, _resolve_existing_cli_file, DEFAULT_MELEE_ROOT
    from ...mwcc_debug.mutators import MutationUnsupported, mutate_type_change

    melee_root = DEFAULT_MELEE_ROOT
    if source_file is not None:
        src_path = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
        source = src_path.read_text()
    else:
        src_path, source = _read_source_for(function, melee_root)
    try:
        out = mutate_type_change(source, function, var, new_type)
    except MutationUnsupported as e:
        typer.echo(f"mutation failed: {e}", err=True)
        raise typer.Exit(2)
    if apply:
        src_path.write_text(out)
        typer.echo(f"wrote: {src_path}", err=True)
    elif diff:
        print(
            _format_source_diff(
                source,
                out,
                fromfile=str(src_path),
                tofile=f"{src_path} (mutated)",
            ),
            end="",
        )
    else:
        print(out, end="")



@mutate_app.command(name="insert-alias")
def mutate_insert_alias_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function containing the variable.",
        ),
    ],
    var: Annotated[
        str,
        typer.Option("--var", help="Local variable name to alias."),
    ],
    at: Annotated[
        int,
        typer.Option(
            "--at",
            help="0-indexed N-th reading statement to alias before.",
        ),
    ] = 0,
    new_name: Annotated[
        Optional[str],
        typer.Option(
            "--name",
            help="Alias variable name (default: <var>_alias).",
        ),
    ] = None,
    scope: Annotated[
        Optional[str],
        typer.Option(
            "--scope",
            help="Optional exact scope_path display string, e.g. "
                 "fn/block@l10c4. Use var-to-virtual --all to inspect.",
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Write the mutated source back to the file. "
                 "Default: print to stdout.",
        ),
    ] = False,
    diff: Annotated[
        bool,
        typer.Option("--diff", help="Print a focused unified diff instead of the full mutated source."),
    ] = False,
) -> None:
    """Insert a fresh local copy of a variable before the N-th
    reading statement and rewrite that statement to use the alias."""
    from src.cli.debug import _format_source_diff, _read_source_for, DEFAULT_MELEE_ROOT
    from ...mwcc_debug.mutators import (
        MutationUnsupported, mutate_insert_alias_before_use,
    )

    melee_root = DEFAULT_MELEE_ROOT
    src_path, source = _read_source_for(function, melee_root)
    parsed_scope = tuple(scope.split("/")) if scope else None
    try:
        out = mutate_insert_alias_before_use(
            source,
            function,
            var,
            at_stmt_index=at,
            new_name=new_name,
            scope_filter=parsed_scope,
        )
    except MutationUnsupported as e:
        typer.echo(f"mutation failed: {e}", err=True)
        raise typer.Exit(2)
    if apply:
        src_path.write_text(out)
        typer.echo(f"wrote: {src_path}", err=True)
    elif diff:
        print(
            _format_source_diff(
                source,
                out,
                fromfile=str(src_path),
                tofile=f"{src_path} (mutated)",
            ),
            end="",
        )
    else:
        print(out, end="")




def _control_flow_compile_source_variant(
    diff_input,
    *,
    function: str,
    melee_root: Path,
    timeout: int,
):
    from ...mwcc_debug.diff_capture import compile_source_variant

    return compile_source_variant(
        diff_input,
        function=function,
        melee_root=melee_root,
        timeout=timeout,
    )


def _control_flow_stop_condition(
    kind: str,
    *,
    blocker: str | None,
    reason: str,
) -> dict[str, str | None]:
    return {"kind": kind, "blocker": blocker, "reason": reason}


def _control_flow_variant_has_score(variant: Mapping[str, Any]) -> bool:
    return variant.get("status") == "ok" and (
        variant.get("match_percent") is not None
        or variant.get("final_match_percent") is not None
        or isinstance(variant.get("checkdiff_delta"), Mapping)
        or isinstance(variant.get("checkdiff"), Mapping)
    )


def _control_flow_scored_variants(
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        variant for variant in variants if _control_flow_variant_has_score(variant)
    ]


def _control_flow_candidate_status_counts(
    variants: list[dict[str, Any]],
) -> dict[str, int]:
    scored_count = len(_control_flow_scored_variants(variants))
    return {
        "candidate_count": len(variants),
        "scored_count": scored_count,
        "unscored_count": len(variants) - scored_count,
        "build_failed_count": sum(
            1 for variant in variants if variant.get("status") == "build-failed"
        ),
        "failed_count": sum(
            1 for variant in variants if variant.get("status") == "failed"
        ),
        "ok_unscored_count": sum(
            1
            for variant in variants
            if variant.get("status") == "ok"
            and not _control_flow_variant_has_score(variant)
        ),
    }


def _control_flow_unscored_blocker(variants: list[dict[str, Any]]) -> str:
    counts = _control_flow_candidate_status_counts(variants)
    if counts["candidate_count"] and (
        counts["build_failed_count"] + counts["failed_count"]
        == counts["candidate_count"]
    ):
        return "control-flow-shape-candidates-build-failed"
    return "control-flow-shape-candidates-unscored"


def _control_flow_candidate_summary(variant: Mapping[str, Any]) -> dict[str, Any]:
    variant_probe = variant.get("probe")
    variant_provenance = (
        dict(variant_probe["provenance"])
        if isinstance(variant_probe, Mapping)
        and isinstance(variant_probe.get("provenance"), Mapping)
        else {}
    )
    return {
        "label": variant.get("label"),
        "status": variant.get("status"),
        "family_id": variant.get("family_id"),
        "suggestion_kind": variant.get("suggestion_kind"),
        "source_retained": variant.get("source_retained"),
        "pcdump_path": variant.get("pcdump_path"),
        "source_hunk_count": len(variant.get("source_hunks") or []),
        "checkdiff_delta": variant.get("checkdiff_delta"),
        "error": variant.get("error"),
        "owner_function": variant_provenance.get("owner_function"),
        "owner_kind": variant_provenance.get("owner_kind"),
        "variant": variant_provenance.get("variant"),
        "anchor_kind": variant_provenance.get("anchor_kind"),
        "base_expr": variant_provenance.get("base_expr"),
        "index_expr": variant_provenance.get("index_expr"),
        "byte_offset": variant_provenance.get("byte_offset"),
    }


def _control_flow_candidates_exhausted_proof(
    *,
    baseline: Mapping[str, Any] | None,
    variants: list[dict[str, Any]],
    family_results: list[Any],
) -> dict[str, Any]:
    scored = _control_flow_scored_variants(variants)
    best = scored[0] if scored else (variants[0] if variants else {})
    family = next(
        (
            item
            for item in family_results
            if isinstance(item, Mapping)
            and item.get("family_id") == best.get("family_id")
        ),
        None,
    )
    if family is None:
        family = next(
            (item for item in family_results if isinstance(item, Mapping)),
            {},
        )
    family_id = str(
        best.get("family_id") or family.get("family_id") or "control-flow-shape"
    )
    operator = str(best.get("operator") or family.get("operator") or "")
    suggestion_kind = str(
        best.get("suggestion_kind")
        or family.get("suggestion_kind")
        or "unspecified"
    )
    provenance = {}
    probe = best.get("probe")
    if isinstance(probe, Mapping) and isinstance(probe.get("provenance"), Mapping):
        provenance = dict(probe["provenance"])
    source_terms = []
    base_expr = provenance.get("base_expr")
    index_expr = provenance.get("index_expr")
    byte_offset = provenance.get("byte_offset")
    if base_expr and index_expr and byte_offset:
        source_terms.append(f"{base_expr}[{index_expr} + {byte_offset}]")
    variant_name = provenance.get("variant")
    if variant_name:
        source_terms.append(str(variant_name))
    source_focus = ", ".join(source_terms) or "the retained source hunks"
    best_candidate = {
        "label": best.get("label"),
        "operator": best.get("operator"),
        "family_id": best.get("family_id"),
        "suggestion_kind": best.get("suggestion_kind"),
        "status": best.get("status"),
        "match_percent": best.get("match_percent"),
        "final_match_percent": best.get("final_match_percent"),
        "source_hunks": best.get("source_hunks") or [],
        "source_retained": best.get("source_retained"),
        "pcdump_path": best.get("pcdump_path"),
        "checkdiff": best.get("checkdiff"),
        "checkdiff_delta": best.get("checkdiff_delta"),
    }
    candidate_summaries = [
        _control_flow_candidate_summary(variant) for variant in variants
    ]
    next_handoff_suffix = (
        "then rerun control-flow-shape-search with the same baseline."
        if baseline is not None
        else (
            "then rerun control-flow-shape-search with a baseline checkdiff if "
            "you need improvement deltas."
        )
    )
    terminal_reason = (
        "bounded control-flow shape candidates were generated and scored "
        "but did not improve the supplied baseline checkdiff"
        if baseline is not None
        else (
            "bounded control-flow shape candidates were generated and scored "
            "but did not reach a true 100% match"
        )
    )
    proof = {
        "family_id": family_id,
        "operator": operator,
        "suggestion_kind": suggestion_kind,
        "terminal_blocker": "control-flow-shape-candidates-exhausted",
        "terminal_reason": terminal_reason,
        "best_candidate": best_candidate,
        "candidate_summaries": candidate_summaries,
        "retained_evidence": {
            "source_retained": best.get("source_retained"),
            "pcdump_path": best.get("pcdump_path"),
            "source_hunk_count": len(best.get("source_hunks") or []),
            "checkdiff_delta": best.get("checkdiff_delta"),
        },
        "next_handoff": (
            "Use best_candidate.source_hunks, source_retained, and pcdump_path "
            f"to adjust the source-level {operator or 'control-flow'} spelling "
            f"around {source_focus}, "
            f"{next_handoff_suffix}"
        ),
    }
    if baseline is not None:
        proof["baseline"] = dict(baseline)
    proof.update(_control_flow_candidate_status_counts(variants))
    return proof


def _control_flow_candidates_unscored_proof(
    *,
    baseline: Mapping[str, Any] | None,
    variants: list[dict[str, Any]],
    family_results: list[Any],
) -> dict[str, Any]:
    best = variants[0] if variants else {}
    family = next(
        (
            item
            for item in family_results
            if isinstance(item, Mapping)
            and item.get("family_id") == best.get("family_id")
        ),
        None,
    )
    if family is None:
        family = next(
            (item for item in family_results if isinstance(item, Mapping)),
            {},
        )
    family_id = str(
        best.get("family_id") or family.get("family_id") or "control-flow-shape"
    )
    operator = str(best.get("operator") or family.get("operator") or "")
    suggestion_kind = str(
        best.get("suggestion_kind")
        or family.get("suggestion_kind")
        or "unspecified"
    )
    blocker = _control_flow_unscored_blocker(variants)
    terminal_reason = (
        "bounded control-flow shape candidates were generated but none produced "
        "checkdiff or match-score evidence; inspect retained source validity and "
        "compile errors before treating this source-shape family as exhausted"
    )
    proof = {
        "family_id": family_id,
        "operator": operator,
        "suggestion_kind": suggestion_kind,
        "terminal_blocker": blocker,
        "terminal_reason": terminal_reason,
        "best_candidate": {
            "label": best.get("label"),
            "operator": best.get("operator"),
            "family_id": best.get("family_id"),
            "suggestion_kind": best.get("suggestion_kind"),
            "status": best.get("status"),
            "source_hunks": best.get("source_hunks") or [],
            "source_retained": best.get("source_retained"),
            "pcdump_path": best.get("pcdump_path"),
            "error": best.get("error"),
        },
        "candidate_summaries": [
            _control_flow_candidate_summary(variant) for variant in variants
        ],
        "retained_evidence": {
            "source_retained": best.get("source_retained"),
            "pcdump_path": best.get("pcdump_path"),
            "source_hunk_count": len(best.get("source_hunks") or []),
            "error": best.get("error"),
        },
        "next_handoff": (
            "Inspect the retained source_hunks, source_retained files, and "
            "compile errors for the generated control-flow candidates; rerun "
            "control-flow-shape-search after the candidate source compiles, "
            "rather than moving to another source-shape family as exhausted."
        ),
    }
    if baseline is not None:
        proof["baseline"] = dict(baseline)
    proof.update(_control_flow_candidate_status_counts(variants))
    return proof


def _control_flow_empty_payload(
    *,
    function: str,
    source: Path | None,
    blocker: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "function": function,
        "source": str(source) if source is not None else None,
        "generated_source_dir": None,
        "probe_count": 0,
        "blocker": blocker,
        "stop_condition": _control_flow_stop_condition(
            "blocked",
            blocker=blocker,
            reason=reason,
        ),
        "probes": [],
        "variants": [],
    }


def _indexed_struct_compile_source_variant(
    diff_input,
    *,
    function: str,
    melee_root: Path,
    timeout: int,
):
    from ...mwcc_debug.diff_capture import compile_source_variant

    return compile_source_variant(
        diff_input,
        function=function,
        melee_root=melee_root,
        timeout=timeout,
    )


def _indexed_struct_checkdiff_hint(
    function: str,
    *,
    melee_root: Path,
    timeout: int,
) -> dict[str, Any] | None:
    command = [
        sys.executable,
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
        "--no-build",
        "--no-fingerprint",
    ]
    completed = subprocess.run(
        command,
        cwd=melee_root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    classification = payload.get("classification")
    if not isinstance(classification, dict):
        return None
    diagnostic = classification.get("indexed_struct_pointer_materialization")
    return diagnostic if isinstance(diagnostic, dict) else None


def _indexed_struct_stop_condition(
    kind: str,
    *,
    blocker: str | None,
    reason: str,
) -> dict[str, str | None]:
    return {"kind": kind, "blocker": blocker, "reason": reason}


def _indexed_struct_target_score(
    *,
    match_percent: float | None,
    match_percent_error: str | None,
) -> dict[str, Any]:
    matched = bool(match_percent == 100.0)
    return {
        "mode": "match-percent",
        "source": "indexed-struct-search",
        "matched": 1 if matched else 0,
        "targeted": 1,
        "candidate_match_percent": match_percent,
        "match_percent_error": match_percent_error,
    }


def _indexed_struct_terminal_proof(
    *,
    function: str,
    blocker: str,
    variants: list[dict[str, Any]],
    scan_status: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not variants:
        return None
    scored = [
        variant for variant in variants
        if variant.get("source_retained") or variant.get("pcdump_path")
    ]
    if not scored:
        return None
    families = sorted({
        str(variant.get("operator") or "indexed-struct-pointer")
        for variant in variants
    })
    best = sorted(
        scored,
        key=lambda variant: float(
            variant.get("final_match_percent")
            if variant.get("final_match_percent") is not None
            else variant.get("match_percent")
            if variant.get("match_percent") is not None
            else -1.0
        ),
        reverse=True,
    )[:8]
    retained_candidates: list[dict[str, Any]] = []
    for variant in best:
        retained_candidates.append({
            "label": variant.get("label"),
            "operator": variant.get("operator"),
            "status": variant.get("status"),
            "source_retained": variant.get("source_retained"),
            "pcdump_path": variant.get("pcdump_path"),
            "match_percent": variant.get("final_match_percent")
            if variant.get("final_match_percent") is not None
            else variant.get("match_percent"),
            "target_score": variant.get("target_score"),
            "source_hunks": variant.get("source_hunks") or [],
            "checkdiff": variant.get("checkdiff"),
            "error": variant.get("error"),
        })
    return {
        "status": "terminal",
        "kind": "indexed-struct-pointer-materialization-exhausted",
        "function": function,
        "terminal_blocker": blocker,
        "terminal_reason": (
            "bounded indexed-struct pointer source probes were scored, but no "
            "candidate reached a true 100% match"
        ),
        "exhausted_families": families,
        "evaluated_candidate_count": len(variants),
        "supported_candidate_count": scan_status.get("supported_candidate_count"),
        "rejected_candidate_count": scan_status.get("rejected_candidate_count"),
        "retained_candidates": retained_candidates,
        "next_source_handoff": (
            "indexed-struct pointer shape families were exhausted; next try a "
            "source-level frame/layout lever that changes stack reservation or "
            "base/index lifetime before retrying array-base versus element-pointer "
            "dematerialization"
        ),
    }


def _indexed_struct_empty_payload(
    *,
    function: str,
    source: Path | None,
    blocker: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "function": function,
        "source": str(source) if source is not None else None,
        "generated_source_dir": None,
        "probe_count": 0,
        "blocker": blocker,
        "stop_condition": _indexed_struct_stop_condition(
            "blocked",
            blocker=blocker,
            reason=reason,
        ),
        "probes": [],
        "variants": [],
    }



_LIFETIME_LAYOUT_RANKING = (
    "lifetime-layout pressure objective, final match percent tiebreaker"
)

_LIFETIME_LAYOUT_FOCUSES: dict[str, tuple[str, ...]] = {
    "b4-tree-loop": (
        "declaration-order",
        "indexed-pointer-loop",
        "loop-counter-hoist",
        "loop-counter-type",
        "pointer-base-call-loop",
        "pointer-walk-loop",
    ),
    "helper-inline-lifetime": HELPER_INLINE_LIFETIME_OPERATORS,
}

_LIFETIME_LAYOUT_TRANSFORM_FOCUSES: dict[str, tuple[str, ...]] = {
    "mixed-pcode-fpr-lifetime": (
        "mixed_pcode_fpr_lifetime_pressure_repair",
    ),
}


def _resolve_lifetime_layout_operator_filter(
    *,
    focus: str | None,
    operators: list[str] | None,
) -> tuple[str, ...] | None:
    selected: list[str] = []
    if focus:
        if focus in _LIFETIME_LAYOUT_TRANSFORM_FOCUSES:
            pass
        else:
            try:
                selected.extend(_LIFETIME_LAYOUT_FOCUSES[focus])
            except KeyError as exc:
                choices = ", ".join(
                    sorted(
                        {
                            *_LIFETIME_LAYOUT_FOCUSES,
                            *_LIFETIME_LAYOUT_TRANSFORM_FOCUSES,
                        }
                    )
                )
                raise typer.BadParameter(
                    f"unknown focus {focus!r}; choices: {choices}"
                ) from exc

    for operator in operators or []:
        for item in operator.split(","):
            item = item.strip()
            if item:
                selected.append(item)
    if not selected:
        return None
    return tuple(dict.fromkeys(selected))


def _resolve_lifetime_layout_transform_families(
    *,
    focus: str | None,
    families: list[str] | None,
) -> list[str] | None:
    selected: list[str] = []
    if focus:
        selected.extend(_LIFETIME_LAYOUT_TRANSFORM_FOCUSES.get(focus, ()))
    for family in families or []:
        for item in family.split(","):
            item = item.strip()
            if item:
                selected.append(item)
    if not selected:
        return None
    return list(dict.fromkeys(selected))


def _score_lifetime_layout_objective(
    delta,
    *,
    target_pairs: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    match_percent: float | None = None,
    stack_slot_localizer: dict | None = None,
    baseline_expression_score: Mapping[str, Any] | None = None,
    expression_score: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    has_target_pairs = bool(target_pairs)
    target_virtuals = {
        virtual for pair in target_pairs for virtual in pair
    }
    target_spill_removed = tuple(
        sorted(virtual for virtual in delta.spill_removed if virtual in target_virtuals)
    )
    frame_gain = (
        -delta.frame_delta
        if delta.frame_delta is not None and delta.frame_delta < 0
        else 0
    )
    normalized_target_pairs = {
        tuple(sorted(pair)) for pair in target_pairs
    }
    normalized_interference_removed = {
        tuple(sorted(pair)) for pair in delta.interference_removed
    }
    pair_detail_improvements = tuple(
        pair for pair in delta.target_pairs if pair.improved
    )
    target_pair_improved = bool(
        pair_detail_improvements
        or (normalized_target_pairs & normalized_interference_removed)
    )
    if delta.target_pairs:
        target_pair_all_clear = all(
            not pair.after.colorgraph_interference and not pair.after.live_overlap
            for pair in delta.target_pairs
        )
    else:
        target_pair_all_clear = False
    saved_f25_removed = "f25" in set(delta.saved_removed)
    frame_reaches_168 = delta.frame_before == 176 and delta.frame_after == 168

    reasons: list[str] = []
    regressions: list[str] = []
    topology_changes: list[str] = []
    if frame_gain:
        reasons.append("frame_reduced")
    elif delta.frame_delta is not None and delta.frame_delta > 0:
        regressions.append("frame_grew")
    if target_spill_removed:
        reasons.append("target_spill_removed")
    elif delta.spill_removed:
        reasons.append("spill_removed")
    if delta.spill_added:
        regressions.append("spill_added")
    if delta.interference_removed:
        if has_target_pairs:
            reasons.append("interference_removed")
        else:
            topology_changes.append("interference_removed")
    if delta.interference_added:
        regressions.append("interference_added")
    if delta.coalesce_added:
        reasons.append("coalesce_added")
    if delta.coalesce_removed:
        regressions.append("coalesce_removed")
    if saved_f25_removed:
        reasons.append("saved_f25_removed")
    if frame_reaches_168:
        reasons.append("frame_reaches_168")

    baseline_expression_matched = _lifetime_layout_score_int(
        baseline_expression_score,
        "matched",
    )
    expression_matched = _lifetime_layout_score_int(expression_score, "matched")
    expression_targeted = _lifetime_layout_score_int(expression_score, "targeted")
    if expression_targeted is None:
        expression_targeted = _lifetime_layout_score_int(
            baseline_expression_score,
            "targeted",
        )
    expression_delta = None
    if expression_matched is not None:
        expression_delta = expression_matched - (baseline_expression_matched or 0)
    expression_scored = (
        expression_score is not None
        and expression_matched is not None
        and expression_targeted is not None
        and expression_targeted > 0
    )
    expression_anchor_all_clear = bool(
        expression_scored and expression_matched == expression_targeted
    )
    expression_anchor_improved = bool(
        expression_scored and expression_delta is not None and expression_delta > 0
    )
    if expression_anchor_all_clear:
        reasons.append("expression_all_clear")
    elif expression_anchor_improved:
        reasons.append("expression_improved")
    elif expression_scored:
        regressions.append("no_expression_progress")

    if reasons:
        actionability = "improved"
    elif regressions:
        actionability = "regressed"
    else:
        actionability = "neutral"
    if (
        expression_scored
        and not expression_anchor_all_clear
        and not expression_anchor_improved
        and actionability == "improved"
    ):
        actionability = "exploratory-only"

    stack_slot_mismatch_count = None
    if stack_slot_localizer is not None:
        raw_count = stack_slot_localizer.get("mismatch_count")
        if isinstance(raw_count, int):
            stack_slot_mismatch_count = raw_count

    match_score = match_percent if match_percent is not None else -1.0
    interference_removed_score = (
        len(delta.interference_removed) if has_target_pairs else 0
    )
    sort_key = (
        float(actionability == "improved"),
        float(expression_anchor_all_clear),
        float(expression_anchor_improved),
        float(len(target_spill_removed)),
        float(len(delta.spill_removed)),
        float(interference_removed_score),
        float(len(delta.coalesce_added)),
        float(frame_gain),
        float(saved_f25_removed),
        float(frame_reaches_168),
        float(target_pair_all_clear),
        float(target_pair_improved),
        float(match_score),
        -float(len(delta.spill_added)),
        -float(len(delta.interference_added)),
        -float(len(delta.coalesce_removed)),
    )
    return {
        "target_pairs": [list(pair) for pair in target_pairs],
        "frame_delta": delta.frame_delta,
        "frame_before": delta.frame_before,
        "frame_after": delta.frame_after,
        "saved_removed": list(delta.saved_removed),
        "saved_added": list(delta.saved_added),
        "target_spill_removed": list(target_spill_removed),
        "spill_removed": list(delta.spill_removed),
        "spill_added": list(delta.spill_added),
        "interference_removed_count": len(delta.interference_removed),
        "interference_added_count": len(delta.interference_added),
        "coalesce_added_count": len(delta.coalesce_added),
        "coalesce_removed_count": len(delta.coalesce_removed),
        "saved_f25_removed": saved_f25_removed,
        "frame_reaches_168": frame_reaches_168,
        "target_pair_improved": target_pair_improved,
        "target_pair_all_clear": target_pair_all_clear,
        "match_percent": match_percent,
        "opcode_shape_preserved": None,
        "stack_slot_mismatch_count": stack_slot_mismatch_count,
        "baseline_expression_matched": baseline_expression_matched,
        "expression_matched": expression_matched,
        "expression_targeted": expression_targeted,
        "expression_delta": expression_delta,
        "expression_anchor_improved": expression_anchor_improved,
        "expression_anchor_all_clear": expression_anchor_all_clear,
        "actionability": actionability,
        "actionability_reasons": reasons,
        "actionability_regressions": regressions,
        "topology_changes": topology_changes,
        "sort_key": list(sort_key),
    }


def _lifetime_layout_score_int(
    score: Mapping[str, Any] | None,
    key: str,
) -> int | None:
    if not isinstance(score, Mapping):
        return None
    try:
        return int(score[key])
    except (KeyError, TypeError, ValueError):
        return None


def _score_lifetime_layout_expression_score(
    *,
    target_spec: Mapping[str, Any] | None,
    pcdump_text: str,
    function: str,
    candidate_source_text: str | None,
    candidate_source_file: str | None,
    baseline_pcdump_text: str | None,
    baseline_source_text: str | None,
    baseline_source_file: str | None,
    reg_class: str | None,
) -> dict[str, Any] | None:
    from src.cli.debug import (
        _score_expression_anchors,
        _score_source_target_details,
        find_function,
        parse_hook_events,
        parse_pcdump,
        score_function,
    )
    if not isinstance(target_spec, Mapping):
        return None
    fns = parse_pcdump(pcdump_text)
    fn = next((candidate for candidate in fns if candidate.name == function), None)
    if fn is None:
        return None
    events_list = parse_hook_events(pcdump_text)
    events = find_function(events_list, function)
    result = score_function(fn, target_spec, events=events)
    target_details = _score_source_target_details(result, target_spec)
    return _score_expression_anchors(
        target_spec=target_spec,
        target_details=target_details,
        pcdump_text=pcdump_text,
        function=function,
        fn=fn,
        candidate_source_text=candidate_source_text,
        candidate_source_file=candidate_source_file,
        baseline_pcdump_text=baseline_pcdump_text,
        baseline_source_text=baseline_source_text,
        baseline_source_file=baseline_source_file,
        reg_class=reg_class,
    )


def _lifetime_layout_metric_aliases(
    *,
    candidate_sig,
    delta,
    objective: Mapping[str, Any],
    real_score: Any,
) -> dict[str, Any]:
    pair_results = _lifetime_layout_pair_results(delta)
    pressure_delta = {
        "frame_delta": delta.frame_delta,
        "frame_before": delta.frame_before,
        "frame_after": delta.frame_after,
        "saved_added": list(delta.saved_added),
        "saved_removed": list(delta.saved_removed),
        "spill_added": list(delta.spill_added),
        "spill_removed": list(delta.spill_removed),
        "interference_added_count": len(delta.interference_added),
        "interference_removed_count": len(delta.interference_removed),
        "coalesce_added_count": len(delta.coalesce_added),
        "coalesce_removed_count": len(delta.coalesce_removed),
        "target_pairs": pair_results,
    }
    aliases = {
        "compile_status": "ok",
        "pressure_score": dict(objective),
        "pressure_delta": pressure_delta,
        "pair_results": pair_results,
        "frame_delta": delta.frame_delta,
        "saved_regs": list(candidate_sig.saved_regs),
        "match_percent": real_score.match_percent,
    }
    if real_score.match_percent_error is not None:
        aliases["metric_unavailable_reason"] = real_score.match_percent_error
    return aliases


def _lifetime_layout_pair_results(delta) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for pair in delta.target_pairs:
        results.append({
            "virtual": pair.before.virtual,
            "other_virtual": pair.before.other_virtual,
            "before_interference": pair.before.colorgraph_interference,
            "after_interference": pair.after.colorgraph_interference,
            "before_live_overlap": pair.before.live_overlap,
            "after_live_overlap": pair.after.live_overlap,
            "before_same_assigned_reg": pair.before.same_assigned_reg,
            "after_same_assigned_reg": pair.after.same_assigned_reg,
            "interference_removed": (
                pair.before.colorgraph_interference
                and not pair.after.colorgraph_interference
            ),
            "live_overlap_removed": (
                pair.before.live_overlap
                and not pair.after.live_overlap
            ),
            "improved": pair.improved,
            "before_reason": pair.before.reason,
            "after_reason": pair.after.reason,
        })
    return results


def _lifetime_layout_unavailable_metric_aliases(
    *,
    compile_status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "compile_status": compile_status,
        "pressure_score": None,
        "pressure_delta": None,
        "pair_results": [],
        "frame_delta": None,
        "saved_regs": [],
        "match_percent": None,
        "metric_unavailable_reason": reason,
        "unscored_reason": reason,
    }


def _rank_lifetime_layout_candidates(
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked = [dict(variant) for variant in variants]
    ranked.sort(key=_lifetime_layout_variant_sort_key, reverse=True)
    for idx, variant in enumerate(ranked, start=1):
        variant["rank"] = idx
    return ranked


def _lifetime_layout_variant_sort_key(variant: dict[str, Any]) -> tuple[float, ...]:
    if variant.get("status") != "ok":
        return (-1.0,)
    objective = variant.get("objective") or {}
    sort_key = objective.get("sort_key")
    if isinstance(sort_key, list):
        return tuple(float(item) for item in sort_key)
    if isinstance(sort_key, tuple):
        return tuple(float(item) for item in sort_key)
    return (0.0,)


def _lifetime_layout_terminal_summary(
    *,
    function: str,
    focus: str | None,
    operator_filter: tuple[str, ...] | None,
    transform_families: list[str] | None,
    transform_only_focus: bool,
    source_available: bool,
    target_pairs: list[tuple[int, int]],
    register_class: str,
    probes: list[Any],
    variants: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if probes or variants:
        return None

    if not source_available:
        blocker = "source-unavailable"
        reason = "no source text was available to generate lifetime-layout probes"
    elif transform_only_focus:
        blocker = "transform-corpus-no-source-anchors"
        families = ", ".join(transform_families or ()) or "<none>"
        reason = (
            f"focus {focus} requested transform-corpus family {families}, "
            "but the retained source shape exposed no materializable anchors"
        )
    elif operator_filter:
        blocker = "operator-filter-produced-no-probes"
        reason = (
            "the selected lifetime-layout operator filter produced no source probes"
        )
    else:
        blocker = "no-lifetime-layout-probes"
        reason = "no lifetime-layout source probe families matched the source"

    stop_condition = {
        "status": "blocked",
        "kind": "no-materializable-lifetime-layout-probes",
        "blocker": blocker,
        "reason": reason,
    }
    return {
        "status": "blocked",
        "kind": "lifetime-layout-empty-probe-set",
        "function": function,
        "focus": focus,
        "register_class": register_class,
        "target_pairs": [list(pair) for pair in target_pairs],
        "operator_filter": list(operator_filter) if operator_filter else None,
        "transform_families": list(transform_families or ()),
        "source_available": source_available,
        "probe_count": 0,
        "variant_count": 0,
        "blocker": blocker,
        "reason": reason,
        "stop_condition": stop_condition,
    }


def _lifetime_layout_force_phys_terminal_proof(
    *,
    function: str,
    force_phys: Mapping[int, int],
    variants: list[dict[str, Any]],
    transform_families: list[str] | None,
) -> dict[str, Any] | None:
    if not force_phys or not variants:
        return None
    retained: list[dict[str, Any]] = []
    best_hits = 0
    best_distance = None
    best_observed_distance = None
    best_observed_targets = 0
    for variant in variants:
        target_score = variant.get("target_score")
        if not isinstance(target_score, Mapping):
            continue
        hits = _lifetime_layout_score_int(target_score, "hits") or 0
        targeted = _lifetime_layout_score_int(target_score, "targeted") or len(force_phys)
        distance = _lifetime_layout_score_int(target_score, "distance_total")
        observed_distance = _lifetime_layout_score_int(
            target_score,
            "observed_distance_total",
        )
        observed_targets = _lifetime_layout_score_int(
            target_score,
            "observed_targets",
        ) or 0
        best_hits = max(best_hits, hits)
        if distance is not None:
            best_distance = distance if best_distance is None else min(best_distance, distance)
        if observed_distance is not None:
            if (
                observed_targets > best_observed_targets
                or (
                    observed_targets == best_observed_targets
                    and (
                        best_observed_distance is None
                        or observed_distance < best_observed_distance
                    )
                )
            ):
                best_observed_targets = observed_targets
                best_observed_distance = observed_distance
        retained.append({
            "label": variant.get("label"),
            "operator": variant.get("operator"),
            "status": variant.get("status"),
            "source_retained": variant.get("source_retained"),
            "pcdump_path": variant.get("pcdump_path"),
            "target_score": target_score,
            "source_hunks": variant.get("source_hunks") or [],
            "compile_status": variant.get("compile_status"),
            "error": variant.get("error"),
        })
        if targeted > 0 and hits >= targeted:
            return None
    if not retained:
        return None
    stop_condition = {
        "status": "exhausted",
        "kind": "global-load-lifetime-candidates-exhausted-no-full-target-hit",
        "best_hits": best_hits,
        "best_distance_total": best_distance,
        "best_observed_targets": best_observed_targets,
        "best_observed_distance_total": best_observed_distance,
    }
    return {
        "status": "exhausted",
        "kind": "lifetime-layout-force-phys-terminal-proof",
        "function": function,
        "attempted_targets": {str(ig): int(phys) for ig, phys in sorted(force_phys.items())},
        "transform_families": list(transform_families or ()),
        "candidate_count": len(retained),
        "best_hits": best_hits,
        "best_distance_total": best_distance,
        "best_observed_targets": best_observed_targets,
        "best_observed_distance_total": best_observed_distance,
        "retained_candidates": retained,
        "next_handoff": (
            "Bounded global-load/source-shape candidates were compiled and "
            "scored without satisfying every requested force-phys target. "
            "Use retained source_hunks and pcdumps to either keep a partial "
            "target hit as an active experiment or hand-write the next "
            "source-visible owner around the global-load/user_data boundary."
        ),
        "stop_condition": stop_condition,
    }


def _lifetime_layout_force_phys_target_score(
    pcdump_text: str,
    *,
    function: str,
    class_id: int,
    force_phys: Mapping[int, int],
) -> dict[str, Any]:
    assigned: dict[int, int] = {}
    for events in parse_hook_events(pcdump_text):
        if events.name != function:
            continue
        for section in events.colorgraph_sections:
            if section.class_id != class_id:
                continue
            for decision in section.decisions:
                assigned[int(decision.ig_idx)] = int(decision.assigned_reg)
    virtuals: dict[str, dict[str, object]] = {}
    hits = 0
    observed_distances: list[int] = []
    for ig_idx, expected in sorted(force_phys.items()):
        actual = assigned.get(int(ig_idx))
        hit = actual == int(expected)
        if hit:
            hits += 1
        distance = abs(actual - int(expected)) if actual is not None else None
        if distance is not None:
            observed_distances.append(distance)
        virtuals[str(ig_idx)] = {
            "expected": int(expected),
            "actual": actual,
            "hit": hit,
            "matched": hit,
            "distance": distance,
        }
    return {
        "virtuals": virtuals,
        "hits": hits,
        "matched": hits,
        "targeted": len(force_phys),
        "observed_targets": len(observed_distances),
        "observed_distance_total": sum(observed_distances) if observed_distances else None,
        "all_targets_observed": len(observed_distances) == len(force_phys),
        "distance_total": (
            sum(
                int(virtual["distance"])
                for virtual in virtuals.values()
                if virtual["distance"] is not None
            )
            if all(virtual["distance"] is not None for virtual in virtuals.values())
            else None
        ),
    }


_FRAME_TRANSFORM_RANKING = (
    "outgoing parameter-area words, expected frame-size objective, final match percent tiebreaker"
)

_FRAME_DIRECTED_DEFAULT_OPERATORS = (
    "frame-local-dematerialize",
    "frame-direct-literal-at-final-fp-call",
    "frame-direct-fp-global-at-final-call",
    "frame-direct-fp-expression-at-call",
    "frame-split-fp-const-lifetime",
    "frame-split-fp-global-lifetime",
    "frame-split-conversion-scratch-at-call",
    "frame-magic-scratch-relocation",
    "declaration-use-distance",
    "block-scope",
    "call-argument-tempization",
    "frame-reservation-pad-stack",
)

_FRAME_TRANSFORM_CORPUS_DEFAULT_FAMILIES = (
    "outgoing_parameter_area_shape",
    "assignment_expression_temp_seed",
    "string_literal_data_blob_field_shape",
    "raw_pointer_offset_struct_field_shape",
    "comma_operator_noop_expression_shape",
    "numeric_cast_shape",
    "void_to_value_return_shape",
    "global_pointer_alias_shape",
    "empty_do_while_barrier",
)

_FRAME_TRANSFORM_OUTGOING_FLOOR_FAMILIES = (
    "outgoing_parameter_area_shape",
)

_FPR_SELECT_ORDER_TRANSFORM_FAMILIES = (
    "pcode_only_fpr_fsubs_cast_owner_repair",
    "pcode_only_fpr_callarg_temp_repair",
    "coupled_fpr_coalesce_product_repair",
    "coloring_register_steering",
)

_GPR_SELECT_ORDER_TRANSFORM_FAMILIES = (
    "indexed_byte_address_temp_steering",
)



def _frame_transform_probe_plan(report: Mapping[str, Any]) -> dict[str, Any]:
    first_divergence = report.get("frame_first_divergence")
    if isinstance(first_divergence, Mapping):
        plan = first_divergence.get("frame_transform_probe_plan")
        if isinstance(plan, Mapping):
            return dict(plan)
    return {
        "status": "ready",
        "objective": "reduce current-vs-expected stack frame-size delta",
        "operator_priority": list(_FRAME_DIRECTED_DEFAULT_OPERATORS),
        "suggested_commands": [],
    }


def _frame_report_has_outgoing_parameter_floor_delta(
    frame_report: Mapping[str, Any],
) -> bool:
    floor = frame_report.get("outgoing_parameter_area_floor")
    if not isinstance(floor, Mapping):
        return False
    if floor.get("status") != "current-floor-larger":
        return False
    model = floor.get("parameter_word_count_model")
    if not isinstance(model, Mapping):
        return False
    current_words = model.get("current_parameter_words")
    expected_words = model.get("expected_parameter_words")
    if not isinstance(current_words, int) or not isinstance(expected_words, int):
        return False
    if current_words <= expected_words:
        return False
    current_accesses = floor.get("current_accesses_in_excess_floor")
    if isinstance(current_accesses, list) and current_accesses:
        return False
    frame_delta = frame_report.get("frame_delta")
    floor_delta = floor.get("floor_delta_bytes")
    return (
        (isinstance(frame_delta, int) and frame_delta != 0)
        or (isinstance(floor_delta, int) and floor_delta != 0)
    )


def _frame_transform_needs_outgoing_floor_source_bridge(
    frame_report: Mapping[str, Any],
) -> bool:
    return _frame_report_has_outgoing_parameter_floor_delta(frame_report)


def _frame_report_current_frame_size(report: Mapping[str, Any]) -> int | None:
    current = report.get("current")
    if not isinstance(current, Mapping):
        return None
    value = current.get("frame_size")
    return value if isinstance(value, int) else None


def _frame_report_expected_frame_size(report: Mapping[str, Any]) -> int | None:
    expected = report.get("expected")
    if not isinstance(expected, Mapping):
        return None
    value = expected.get("frame_size")
    return value if isinstance(value, int) else None


def _frame_transform_baseline_consistency(
    *,
    pcdump_frame_report: Mapping[str, Any],
    staged_frame_report: Mapping[str, Any],
    explicit_pcdump: bool,
    prefer_staged_source_baseline: bool,
) -> dict[str, Any]:
    pcdump_current = _frame_report_current_frame_size(pcdump_frame_report)
    staged_current = _frame_report_current_frame_size(staged_frame_report)
    expected_frame = (
        _frame_report_expected_frame_size(pcdump_frame_report)
        if _frame_report_expected_frame_size(pcdump_frame_report) is not None
        else _frame_report_expected_frame_size(staged_frame_report)
    )
    mismatch = (
        pcdump_current is not None
        and staged_current is not None
        and pcdump_current != staged_current
    )
    staged_authoritative = prefer_staged_source_baseline or not explicit_pcdump
    if mismatch and explicit_pcdump and not prefer_staged_source_baseline:
        status = "mismatch-explicit-pcdump-authoritative"
        reason = (
            "explicit --pcdump current frame differs from compiled --source-file "
            "baseline; retaining explicit pcdump as authoritative"
        )
    elif mismatch and staged_authoritative:
        status = "mismatch-staged-source-authoritative"
        reason = (
            "compiled --source-file baseline differs from pcdump and is "
            "authoritative for this run"
        )
    elif staged_authoritative:
        status = "staged-source-authoritative"
        reason = "compiled --source-file baseline is authoritative"
    else:
        status = "consistent"
        reason = (
            "explicit --pcdump and compiled --source-file baseline agree"
            if explicit_pcdump
            else "pcdump and staged source baseline agree"
        )
    return {
        "status": status,
        "reason": reason,
        "pcdump_current_frame_size": pcdump_current,
        "staged_current_frame_size": staged_current,
        "expected_frame_size": expected_frame,
        "explicit_pcdump": explicit_pcdump,
        "prefer_staged_source_baseline": prefer_staged_source_baseline,
    }


def _frame_transform_semantic_lever_status(
    *,
    source_text: str | None,
    operator_filter: tuple[str, ...],
    frame_reservation_delta: int | None,
    probes: list[Any],
    scan_status: Mapping[str, Any] | None,
) -> dict:
    operator = "frame-local-dematerialize"
    if frame_reservation_delta is None or frame_reservation_delta >= 0:
        return {"status": "not-needed", "operator": operator}
    if source_text is None:
        return {"status": "unavailable-no-source", "operator": operator}
    if operator not in operator_filter:
        return {"status": "excluded-by-operator-filter", "operator": operator}
    if isinstance(scan_status, Mapping):
        status = scan_status.get("status")
        if status == "semantic-lever-generated":
            if any(getattr(probe, "operator", None) == operator for probe in probes):
                return dict(scan_status)
            return {
                "status": "semantic-lever-not-emitted",
                "operator": operator,
                "reason": (
                    "source scan found a safe semantic local dematerialization, "
                    "but it was not emitted by the selected probe budget"
                ),
            }
        return dict(scan_status)
    return {
        "status": "scan-unavailable",
        "operator": operator,
        "reason": "semantic local dematerialization scan did not run",
    }


def _resolve_frame_transform_operator_filter(
    *,
    probe_plan: Mapping[str, Any],
    operators: list[str] | None,
) -> tuple[str, ...]:
    selected: list[str] = []
    selected.extend(_FRAME_DIRECTED_DEFAULT_OPERATORS)
    raw_priority = probe_plan.get("operator_priority")
    if isinstance(raw_priority, list):
        selected.extend(
            str(item)
            for item in raw_priority
            if isinstance(item, str) and item
        )
    for operator in operators or []:
        for item in operator.split(","):
            item = item.strip()
            if item:
                selected.append(item)
    return tuple(dict.fromkeys(selected))


def _frame_transform_variant_frame_model(
    candidate_text: str,
    function: str,
) -> dict[str, Any]:
    if f"Starting function {function}" in candidate_text:
        return analyze_frame_reservations(candidate_text, function)["current"]
    if re.search(rf"\.fn\s+{re.escape(function)}\b", candidate_text):
        return analyze_frame_from_asm_text(candidate_text)
    if "Starting function " in candidate_text:
        raise ValueError(f"{function} not found in pcdump")
    return analyze_frame_from_asm_text(candidate_text)


def _frame_transform_variant_from_model(
    *,
    label: str,
    operator: str,
    path: Path,
    frame_model: Mapping[str, Any],
    current_frame_size: int | None = None,
    expected_frame_size: int | None = None,
    match_percent: float | None = None,
    match_percent_error: str | None = None,
    source_retained: Path | None = None,
) -> dict[str, Any]:
    frame_size = frame_model.get("frame_size")
    variant = {
        "label": label,
        "operator": operator,
        "status": "ok",
        "path": str(path),
        "frame": dict(frame_model),
        "frame_size": frame_size if isinstance(frame_size, int) else None,
        "candidate_frame_size": frame_size if isinstance(frame_size, int) else None,
        "current_frame_size": current_frame_size,
        "expected_frame_size": expected_frame_size,
    }
    if match_percent is not None:
        variant["match_percent"] = match_percent
        variant["final_match_percent"] = match_percent
    if match_percent_error is not None:
        variant["match_percent_error"] = match_percent_error
    if source_retained is not None:
        variant["source_retained"] = str(source_retained)
    return variant


def _attach_frame_transform_probe_payload(
    variant: dict[str, Any],
    probe_payload: Mapping[str, Any] | None,
) -> None:
    if probe_payload is None:
        return
    payload = dict(probe_payload)
    variant["probe"] = payload
    description = payload.get("description")
    if isinstance(description, str):
        variant["description"] = description
    provenance = payload.get("provenance")
    if isinstance(provenance, Mapping):
        variant["provenance"] = dict(provenance)


def _materialize_frame_transform_probe_sources(
    probes,
    *,
    output_dir: Path | None,
    json_out: bool,
) -> tuple[Path | None, dict[str, Path]]:
    if not probes or not (json_out or output_dir is not None):
        return None, {}
    probe_dir = (
        output_dir
        if output_dir is not None
        else Path(tempfile.mkdtemp(prefix="melee_frame_transform_"))
    )
    probe_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for probe in probes:
        path = probe_dir / f"{probe.label}.c"
        path.write_text(probe.source_text)
        paths[probe.label] = path
    return probe_dir, paths


def _default_repo_probe_dir(
    melee_root: Path,
    *,
    family: str,
    function: str,
) -> Path:
    safe_family = re.sub(r"[^A-Za-z0-9_.-]+", "-", family).strip(".-") or "probe"
    safe_function = re.sub(r"[^A-Za-z0-9_.-]+", "-", function).strip(".-") or "fn"
    base = melee_root / "build" / "mwcc_debug_cache" / "probes" / safe_family
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{safe_function}-", dir=base))



def _lifetime_layout_probe_unit_source(
    function: str,
    source_file: Path,
    melee_root: Path,
) -> Path | None:
    from src.cli.debug import _source_path_for_function
    try:
        source_file.resolve().relative_to((melee_root / "src").resolve())
    except ValueError:
        return _source_path_for_function(function, melee_root)
    return source_file


@mutate_app.command(name="lifetime-layout")
def mutate_lifetime_layout_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to explore.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Baseline pcdump. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate lifetime/layout probes.",
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help=(
                "Directory for generated --compile-probes source files. "
                "When omitted, JSON output retains a temp directory because "
                "variant paths are machine-readable follow-up inputs."
            ),
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate pcdump/source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    pairs: Annotated[
        str,
        typer.Option(
            "--pairs",
            help=(
                "Comma-separated target virtual pairs, e.g. r37/r40,r43/r33 "
                "or f32/f38."
            ),
        ),
    ] = "",
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help="Compile generated source probes and report pressure deltas.",
        ),
    ] = False,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent plus "
                "checkdiff stack-slot deltas. Enabled by default; use "
                "--no-score-match-percent for faster pcdump-only scoring."
            ),
        ),
    ] = True,
    expression_target: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-target",
            help=(
                "Target spec used to expression-score compiled lifetime probes. "
                "When set, ranking demotes pressure-only candidates that do not "
                "move protected expression anchors."
            ),
        ),
    ] = None,
    expression_baseline: Annotated[
        Optional[Path],
        typer.Option(
            "--expression-baseline",
            help=(
                "Baseline pcdump used to derive expression anchors for "
                "--expression-target. Defaults to --pcdump."
            ),
        ),
    ] = None,
    expression_source: Annotated[
        Optional[str],
        typer.Option(
            "--expression-source",
            help=(
                "Baseline C source for expression anchors. Defaults to "
                "--source-file when available."
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
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to list or compile.",
        ),
    ] = 12,
    include_transform_corpus: Annotated[
        bool,
        typer.Option(
            "--include-transform-corpus/--no-include-transform-corpus",
            help=(
                "Opt in to transform-corpus source-shape probes after the "
                "existing lifetime/layout probe families."
            ),
        ),
    ] = False,
    transform_family: Annotated[
        Optional[list[str]],
        typer.Option(
            "--transform-family",
            help=(
                "Transform-corpus source-shape family to generate. Repeat or "
                "pass comma-separated names; passing this also opts in."
            ),
        ),
    ] = None,
    transform_force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--transform-force-phys",
            "--directed-force-phys",
            help=(
                "Proof mapping for transform-corpus source-shape probes, "
                "e.g. IG:PHYS or comma-separated IG:PHYS entries."
            ),
        ),
    ] = None,
    frame_reservation_bytes: Annotated[
        Optional[int],
        typer.Option(
            "--frame-reservation-bytes",
            help=(
                "Add a PAD_STACK(N) source probe for implicit no-access frame "
                "reservation gaps."
            ),
        ),
    ] = None,
    focus: Annotated[
        Optional[str],
        typer.Option(
            "--focus",
            help=(
                "Named probe-family bundle. `b4-tree-loop` focuses the "
                "x594_b4 tree loop problem space; `helper-inline-lifetime` "
                "focuses helper-inline/source-lifetime register cascades; "
                "`mixed-pcode-fpr-lifetime` focuses the mnDiagram row/callarg "
                "FPR pressure lane."
            ),
        ),
    ] = None,
    operators: Annotated[
        Optional[list[str]],
        typer.Option(
            "--operator",
            help=(
                "Only generate/compile probes from this operator family. "
                "Repeat or pass comma-separated names; combines with most "
                "focuses and narrows --focus helper-inline-lifetime."
            ),
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Explore lifetime/layout source probes and attribute pressure deltas."""
    from src.cli.debug import (
        _MalformedSourceCandidate,
        _SourceCandidateRealScore,
        _append_transform_corpus_probes,
        _compact_source_hunk_for_function,
        _find_unit_for_function,
        _full_unit_source_for_probe,
        _load_target_spec,
        _make_real_score_status,
        _parse_lifetime_layout_candidate,
        _parse_virtual_pair_csv,
        _path_inside_repo,
        _prevalidate_lifetime_layout_source_candidate,
        _pressure_class_id,
        _pressure_signature_from_pcdump_or_exit,
        _probe_requires_full_unit_source,
        _read_expression_source,
        _register_class_from_pair_csv,
        _resolve_existing_cli_file,
        _resolve_pcdump_path,
        _restore_source_snapshot,
        _score_lifetime_layout_expression_score,
        _score_lifetime_layout_objective,
        _score_source_candidate_real_tree,
        _source_path_for_function,
        DEFAULT_MELEE_ROOT,
    )
    from ...mwcc_debug.diff_capture import DiffInput, compile_source_variant
    from ...mwcc_debug.pressure_explorer import (
        compare_pressure_signatures,
        generate_lifetime_layout_probes,
        generate_source_lifetime_probes,
        pressure_signature_from_pcdump,
        render_pressure_delta,
    )

    pair_list = _parse_virtual_pair_csv(pairs)
    register_class = _register_class_from_pair_csv(pairs) or "gpr"
    class_id = _pressure_class_id(register_class)
    baseline_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    baseline_text = baseline_path.read_text()
    baseline = _pressure_signature_from_pcdump_or_exit(
        pressure_signature_from_pcdump,
        baseline_text,
        function,
        pairs=pair_list,
        class_id=class_id,
        spill_class_id=class_id,
    )
    operator_filter = _resolve_lifetime_layout_operator_filter(
        focus=focus,
        operators=operators,
    )
    resolved_transform_families = _resolve_lifetime_layout_transform_families(
        focus=focus,
        families=transform_family,
    )
    from ...search.directed.transform_probe_adapter import (
        TransformProbeConfigError,
        parse_transform_force_phys,
    )
    try:
        transform_force_phys_score = parse_transform_force_phys(transform_force_phys)
    except TransformProbeConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    transform_only_focus = (
        focus in _LIFETIME_LAYOUT_TRANSFORM_FOCUSES
        and not operators
    ) or (
        bool(resolved_transform_families)
        and not include_transform_corpus
        and not operators
        and focus is None
    )

    source_text = None
    source_path_for_probes: Path | None = None
    unit = None
    if source_file is not None:
        source_file = _resolve_existing_cli_file(
            source_file,
            melee_root=DEFAULT_MELEE_ROOT,
            label="source file",
        )
        source_text = source_file.read_text()
        source_path_for_probes = _lifetime_layout_probe_unit_source(
            function,
            source_file,
            DEFAULT_MELEE_ROOT,
        )
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            src_path = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if src_path.exists():
                source_text = src_path.read_text()
                source_path_for_probes = src_path

    if expression_target is None and (
        expression_baseline is not None or expression_source is not None
    ):
        raise typer.BadParameter(
            "--expression-target is required when using expression scoring options"
        )
    expression_target_spec: Mapping[str, Any] | None = None
    baseline_expression_score: dict[str, Any] | None = None
    baseline_expression_pcdump_text: str | None = None
    baseline_expression_source_text: str | None = None
    baseline_expression_source_file: str | None = None
    if expression_target is not None:
        expression_target = _resolve_existing_cli_file(
            expression_target,
            melee_root=DEFAULT_MELEE_ROOT,
            label="expression target",
        )
        expression_target_spec = _load_target_spec(expression_target)
        if expression_baseline is not None:
            expression_baseline = _resolve_existing_cli_file(
                expression_baseline,
                melee_root=DEFAULT_MELEE_ROOT,
                label="expression baseline",
            )
            baseline_expression_pcdump_text = expression_baseline.read_text(
                encoding="utf-8",
                errors="replace",
            )
        else:
            baseline_expression_pcdump_text = baseline_text
        expression_source_value = expression_source
        if expression_source_value is None and source_path_for_probes is not None:
            expression_source_value = str(source_path_for_probes)
        if expression_source_value is not None:
            (
                baseline_expression_source_text,
                baseline_expression_source_file,
            ) = _read_expression_source(
                Path(expression_source_value),
                melee_root=DEFAULT_MELEE_ROOT,
            )
        baseline_expression_score = _score_lifetime_layout_expression_score(
            target_spec=expression_target_spec,
            pcdump_text=baseline_text,
            function=function,
            candidate_source_text=baseline_expression_source_text,
            candidate_source_file=baseline_expression_source_file,
            baseline_pcdump_text=baseline_expression_pcdump_text,
            baseline_source_text=baseline_expression_source_text,
            baseline_source_file=baseline_expression_source_file,
            reg_class=expression_reg_class,
        )

    source_lifetime_families: list[dict] | None = None
    if source_text and focus == "helper-inline-lifetime":
        operator_filter = _resolve_lifetime_layout_operator_filter(
            focus=None,
            operators=operators,
        ) or operator_filter
        probes, source_lifetime_families = generate_source_lifetime_probes(
            source_text,
            function,
            max_probes=max_probes,
            operator_filter=operator_filter,
        )
    elif source_text and not transform_only_focus:
        probes = generate_lifetime_layout_probes(
            source_text,
            function,
            frame_reservation_bytes=frame_reservation_bytes,
            max_probes=max_probes,
            operator_filter=operator_filter,
        )
    else:
        probes = []

    if source_file is not None and (include_transform_corpus or transform_family):
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
    _append_transform_corpus_probes(
        probes,
        source_text=source_text,
        function=function,
        unit=unit,
        include=include_transform_corpus,
        families=resolved_transform_families,
        force_phys=transform_force_phys,
        max_probes=max_probes,
    )

    variants: list[dict] = []
    generated_source_dir: Path | None = None
    score_total = len(candidates or []) + (len(probes) if compile_probes else 0)
    score_index = 0

    def _emit_candidate_progress(
        event: str,
        *,
        index: int,
        label: str,
        operator: str,
        path: Path,
        error: str | None = None,
    ) -> None:
        payload = {
            "event": event,
            "index": index,
            "total": score_total,
            "label": label,
            "operator": operator,
            "path": str(path),
        }
        if error is not None:
            payload["error"] = error
        if json_out:
            print(json.dumps(payload), file=sys.stderr, flush=True)
        else:
            message = (
                f"[lifetime-layout] {index}/{score_total} {label} "
                f"[{operator}]: {path}"
            )
            if event.endswith("-failed") and error is not None:
                message += f" failed: {error}"
            elif event.endswith("-ok"):
                message += " ok"
            print(message, file=sys.stderr, flush=True)

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        unit_source: Path | None = None,
        full_unit_source: bool = False,
        probe: Any | None = None,
    ) -> None:
        nonlocal score_index
        score_index += 1
        current_index = score_index
        _emit_candidate_progress(
            "lifetime-layout-candidate-start",
            index=current_index,
            label=label,
            operator=operator,
            path=path,
        )
        try:
            if full_unit_source and unit_source is None:
                raise ValueError(
                    "full-unit transform probe requires a resolved unit source"
                )
            candidate_source_text: str | None = None
            if path.suffix == ".txt":
                candidate_text = path.read_text(encoding="utf-8", errors="replace")
            elif path.suffix == ".c":
                candidate_source_text, _ = (
                    _prevalidate_lifetime_layout_source_candidate(
                        path,
                        function=function,
                    )
                )
                try:
                    compile_kwargs = dict(
                        diff_input=DiffInput(
                            label=label,
                            token=str(path),
                            kind="source",
                            path=path,
                        ),
                        function=function,
                        melee_root=DEFAULT_MELEE_ROOT,
                        timeout=timeout,
                    )
                    if unit_source is not None:
                        compile_kwargs["unit_source"] = unit_source
                    candidate_text = compile_source_variant(**compile_kwargs)
                except CompileFailure as exc:
                    detail = str(exc)
                    if (
                        exc.returncode == 3
                        and "not found in pcdump" in detail
                    ):
                        raise _MalformedSourceCandidate(
                            (
                                f"{detail}; compiled probe pcdump omitted the "
                                f"target function. Source retained at {path}"
                            ),
                            source_hunk=_compact_source_hunk_for_function(
                                candidate_source_text,
                                function,
                            ),
                        ) from exc
                    raise
            else:
                raise ValueError(f"expected .txt pcdump or .c source, got {path}")
            real_score = _SourceCandidateRealScore(None, None)
            if score_match_percent and path.suffix == ".c":
                status = (
                    _make_real_score_status("lifetime-layout", label)
                    if not json_out
                    else None
                )
                restore_guard_path = source_path_for_probes
                restore_guard_original = (
                    restore_guard_path.read_text()
                    if restore_guard_path is not None
                    and restore_guard_path.exists()
                    else None
                )
                try:
                    score_kwargs = dict(
                        path=path,
                        function=function,
                        melee_root=DEFAULT_MELEE_ROOT,
                        timeout=timeout,
                        status=status,
                        include_stack_slot=True,
                    )
                    if full_unit_source:
                        score_kwargs["full_unit_source"] = True
                    real_score = _score_source_candidate_real_tree(**score_kwargs)
                finally:
                    if (
                        restore_guard_path is not None
                        and restore_guard_original is not None
                        and restore_guard_path.exists()
                        and restore_guard_path.read_text() != restore_guard_original
                    ):
                        restore_error = _restore_source_snapshot(
                            restore_guard_path,
                            restore_guard_original,
                        )
                        if restore_error:
                            raise RuntimeError(restore_error)
            candidate_expression_score = None
            if expression_target_spec is not None:
                candidate_expression_score = _score_lifetime_layout_expression_score(
                    target_spec=expression_target_spec,
                    pcdump_text=candidate_text,
                    function=function,
                    candidate_source_text=candidate_source_text,
                    candidate_source_file=str(path) if path.suffix == ".c" else None,
                    baseline_pcdump_text=baseline_expression_pcdump_text,
                    baseline_source_text=baseline_expression_source_text,
                    baseline_source_file=baseline_expression_source_file,
                    reg_class=expression_reg_class,
                )
            try:
                candidate_sig = pressure_signature_from_pcdump(
                    candidate_text,
                    function,
                    pairs=pair_list,
                    class_id=class_id,
                    spill_class_id=class_id,
                )
            except ValueError as exc:
                if path.suffix == ".c":
                    raise _MalformedSourceCandidate(
                        f"{exc}; compiled probe pcdump omitted the target "
                        f"function. Source retained at {path}",
                        source_hunk=_compact_source_hunk_for_function(
                            candidate_source_text or path.read_text(
                                encoding="utf-8",
                                errors="replace",
                            ),
                            function,
                        ),
                    ) from exc
                raise
            delta = compare_pressure_signatures(baseline, candidate_sig)
            objective = _score_lifetime_layout_objective(
                delta,
                target_pairs=pair_list,
                match_percent=real_score.match_percent,
                stack_slot_localizer=real_score.stack_slot_localizer,
                baseline_expression_score=baseline_expression_score,
                expression_score=candidate_expression_score,
            )
            variant = {
                "label": label,
                "operator": operator,
                "status": "ok",
                "path": str(path),
                "signature": candidate_sig.to_dict(),
                "delta": delta.to_dict(),
                "objective": objective,
                "_text": render_pressure_delta(label, operator, delta),
            }
            variant.update(
                _lifetime_layout_metric_aliases(
                    candidate_sig=candidate_sig,
                    delta=delta,
                    objective=objective,
                    real_score=real_score,
                )
            )
            if real_score.match_percent is not None:
                variant["final_match_percent"] = real_score.match_percent
                variant["match_percent"] = real_score.match_percent
            if real_score.match_percent_error is not None:
                variant["match_percent_error"] = real_score.match_percent_error
            if real_score.stack_slot_localizer is not None:
                variant["stack_slot_localizer"] = real_score.stack_slot_localizer
            if real_score.stack_slot_error is not None:
                variant["stack_slot_error"] = real_score.stack_slot_error
            if candidate_expression_score is not None:
                variant["expression_score"] = candidate_expression_score
            if path.suffix == ".c":
                variant["source_retained"] = str(path)
                pcdump_path = _write_retained_pcdump(path, candidate_text)
                if pcdump_path is not None:
                    variant["pcdump_path"] = pcdump_path
                if candidate_source_text is not None:
                    source_hunks = _lifetime_layout_probe_source_hunks(
                        probe=probe,
                        base_source=source_text,
                        candidate_source=candidate_source_text,
                        label=label,
                    )
                    if source_hunks:
                        variant["source_hunks"] = source_hunks
            if transform_force_phys_score:
                variant["target_score"] = _lifetime_layout_force_phys_target_score(
                    candidate_text,
                    function=function,
                    class_id=class_id,
                    force_phys=transform_force_phys_score,
                )
            provenance = getattr(probe, "provenance", None)
            if isinstance(provenance, Mapping):
                variant["provenance"] = dict(provenance)
            variants.append(variant)
            _emit_candidate_progress(
                "lifetime-layout-candidate-ok",
                index=current_index,
                label=label,
                operator=operator,
                path=path,
            )
        except Exception as exc:
            malformed_source = isinstance(exc, _MalformedSourceCandidate)
            failed = {
                "label": label,
                "operator": operator,
                "status": "malformed-source" if malformed_source else "failed",
                "path": str(path),
                "error": str(exc),
            }
            failed.update(
                _lifetime_layout_unavailable_metric_aliases(
                    compile_status=failed["status"],
                    reason=str(exc),
                )
            )
            if path.suffix == ".c" and path.exists():
                failed["source_retained"] = str(path)
                try:
                    source_hunks = _lifetime_layout_probe_source_hunks(
                        probe=probe,
                        base_source=source_text,
                        candidate_source=path.read_text(
                            encoding="utf-8",
                            errors="replace",
                        ),
                        label=label,
                    )
                    if source_hunks:
                        failed["source_hunks"] = source_hunks
                except OSError:
                    pass
            provenance = getattr(probe, "provenance", None)
            if isinstance(provenance, Mapping):
                failed["provenance"] = dict(provenance)
            if malformed_source and exc.source_hunk:
                failed["source_hunk"] = exc.source_hunk
            variants.append(failed)
            _emit_candidate_progress(
                "lifetime-layout-candidate-failed",
                index=current_index,
                label=label,
                operator=operator,
                path=path,
                error=str(exc),
            )

    for spec in candidates or []:
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes:
        if source_text is None:
            typer.echo("--compile-probes requires --source-file or repo source", err=True)
            raise typer.Exit(2)
        probe_dir = (
            output_dir
            if output_dir is not None
            else _default_repo_probe_dir(
                DEFAULT_MELEE_ROOT,
                family="lifetime-layout",
                function=function,
            )
        )
        probe_dir.mkdir(parents=True, exist_ok=True)
        generated_source_dir = probe_dir
        start_idx = len(variants)
        generated_unit_source = (
            source_path_for_probes
            if source_path_for_probes is not None
            and _path_inside_repo(probe_dir, DEFAULT_MELEE_ROOT)
            else None
        )
        try:
            for probe in probes:
                path = probe_dir / f"{probe.label}.c"
                path.write_text(probe.source_text)
                full_unit_source = _probe_requires_full_unit_source(probe)
                _score_candidate(
                    label=probe.label,
                    operator=probe.operator,
                    path=path,
                    unit_source=(
                        _full_unit_source_for_probe(probe, source_path_for_probes)
                        if full_unit_source
                        else generated_unit_source
                    ),
                    full_unit_source=full_unit_source,
                    probe=probe,
                )
        finally:
            generated_failed = any(
                variant["status"] != "ok" for variant in variants[start_idx:]
            )
            retain_generated = generated_failed or json_out or output_dir is not None
            if not retain_generated:
                shutil.rmtree(probe_dir, ignore_errors=True)

    ranked_variants = _rank_lifetime_layout_candidates(variants)
    terminal_summary = _lifetime_layout_terminal_summary(
        function=function,
        focus=focus,
        operator_filter=operator_filter,
        transform_families=resolved_transform_families,
        transform_only_focus=transform_only_focus,
        source_available=source_text is not None,
        target_pairs=pair_list,
        register_class=register_class,
        probes=probes,
        variants=ranked_variants,
    )
    force_phys_terminal_proof = _lifetime_layout_force_phys_terminal_proof(
        function=function,
        force_phys=transform_force_phys_score,
        variants=ranked_variants,
        transform_families=resolved_transform_families,
    )
    if force_phys_terminal_proof is not None:
        if terminal_summary is None:
            terminal_summary = force_phys_terminal_proof
        elif isinstance(terminal_summary, dict):
            terminal_summary = dict(terminal_summary)
            terminal_summary["force_phys_terminal_proof"] = force_phys_terminal_proof
    if json_out:
        payload = {
            "function": function,
            "register_class": register_class,
            "class_id": class_id,
            "ranking": _LIFETIME_LAYOUT_RANKING,
            "baseline": baseline.to_dict(),
            "probes": [probe.to_dict() for probe in probes],
            "variants": [
                {k: v for k, v in variant.items() if k != "_text"}
                for variant in ranked_variants
            ],
        }
        if focus is not None:
            payload["focus"] = focus
        if operator_filter is not None:
            payload["operator_filter"] = list(operator_filter)
        if source_lifetime_families is not None:
            payload["source_lifetime_families"] = source_lifetime_families
        if generated_source_dir is not None:
            payload["generated_source_dir"] = str(generated_source_dir)
        if baseline_expression_score is not None:
            payload["baseline_expression_score"] = baseline_expression_score
        if terminal_summary is not None:
            payload["terminal_summary"] = terminal_summary
            payload["stop_condition"] = terminal_summary["stop_condition"]
        print(json.dumps(payload, indent=2))
        return

    print(f"lifetime-layout pressure explorer - {function}")
    if focus is not None:
        print(f"focus: {focus}")
    if operator_filter is not None:
        print("operator filter: " + ", ".join(operator_filter))
    print(
        f"baseline: frame={baseline.frame_size if baseline.frame_size is not None else '?'} "
        f"saved={','.join(baseline.saved_regs) or '-'} "
        f"spills={','.join(str(v) for v in baseline.spill_set) or '-'}"
    )
    if probes:
        print("Probes:")
        for probe in probes:
            print(f"- {probe.label} [{probe.operator}]: {probe.description}")
    elif source_text is None:
        print("Probes: source unavailable; pass --source-file to generate them.")
    elif terminal_summary is not None:
        print(f"stop: {terminal_summary['reason']}")
    if variants:
        print(f"ranking: {_LIFETIME_LAYOUT_RANKING}")
        print("Variants:")
        for variant in ranked_variants:
            if variant["status"] == "ok":
                print(
                    f"{variant.get('rank', '?')}. "
                    f"{variant['label']} [{variant['operator']}]"
                )
                objective = variant.get("objective") or {}
                target_spill_removed = ",".join(
                    "r" + str(v)
                    for v in objective.get("target_spill_removed", [])
                ) or "-"
                print(
                    "  objective: "
                    f"actionability={objective.get('actionability', '?')} "
                    f"frame_delta={objective.get('frame_delta')} "
                    f"target_spill_removed={target_spill_removed} "
                    f"interference_removed={objective.get('interference_removed_count', 0)} "
                    f"coalesce_added={objective.get('coalesce_added_count', 0)}"
                )
                print(variant["_text"])
                if variant.get("final_match_percent") is not None:
                    print(
                        f"  final_match_percent: "
                        f"{variant['final_match_percent']:.6g}"
                    )
                if variant.get("match_percent_error"):
                    print(f"  match_percent_error: {variant['match_percent_error']}")
                if variant.get("stack_slot_localizer"):
                    localizer = variant["stack_slot_localizer"]
                    deltas = ",".join(str(d) for d in localizer.get("deltas", []))
                    mismatch_count = localizer.get("mismatch_count", 0)
                    print(
                        f"  stack_slot_localizer: {mismatch_count} mismatch(es)"
                        + (f", deltas={deltas}" if deltas else "")
                    )
                if variant.get("stack_slot_error"):
                    print(f"  stack_slot_error: {variant['stack_slot_error']}")
            else:
                print(
                    f"- {variant['label']} [{variant['operator']}] failed: "
                    f"{variant['error']}"
                )
                if variant.get("source_retained"):
                    print(f"  source: {variant['source_retained']}")
    elif not compile_probes and not candidates:
        print("Variants: none; pass --compile-probes or --candidate OPERATOR=path.")



@mutate_app.command(name="control-flow-shape-search")
def mutate_control_flow_shape_search_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function",
            "-f",
            help="Function to explore.",
        ),
    ],
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate control-flow shape probes.",
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help="Directory for generated control-flow probe source files.",
        ),
    ] = None,
    suggestions_json: Annotated[
        Optional[Path],
        typer.Option(
            "--suggestions-json",
            help=(
                "JSON output from debug suggest control-flow-shape. When "
                "provided, only suggested families are materialized."
            ),
        ),
    ] = None,
    baseline_checkdiff_json: Annotated[
        Optional[Path],
        typer.Option(
            "--baseline-checkdiff-json",
            help=(
                "Baseline tools/checkdiff.py --format json payload used to "
                "report checkdiff deltas."
            ),
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help="Compile generated control-flow shape source probes.",
        ),
    ] = True,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to list or compile.",
        ),
    ] = 12,
    operators: Annotated[
        Optional[list[str]],
        typer.Option(
            "--operator",
            help="Control-flow operator to generate; repeatable.",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Compile and score conservative control-flow shape source probes."""
    from src.cli.debug import (
        _control_flow_compile_source_variant,
        _find_unit_for_function,
        _make_real_score_status,
        _parse_lifetime_layout_candidate,
        _probe_requires_full_unit_source,
        _full_unit_source_for_probe,
        _resolve_existing_cli_file,
        _score_source_candidate_real_tree,
        DEFAULT_MELEE_ROOT,
    )
    from ...mwcc_debug.control_flow_shape import (
        DEFAULT_CONTROL_FLOW_OPERATORS,
        materialize_control_flow_suggestions,
        scan_control_flow_shape_probes,
    )
    from ...mwcc_debug.diff_capture import DiffInput

    melee_root = DEFAULT_MELEE_ROOT
    resolved_source: Path | None = None
    source_text: str | None = None
    candidate_specs = candidates or []
    operator_filter = tuple(operators or ())
    suggestion_items: list[Mapping[str, Any]] | None = None
    if suggestions_json is not None:
        suggestions_path = _resolve_existing_cli_file(
            suggestions_json,
            melee_root=melee_root,
            label="suggestions JSON",
        )
        try:
            suggestions_payload = json.loads(
                suggestions_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                f"invalid suggestions JSON: {exc}",
                param_hint="--suggestions-json",
            ) from exc
        if isinstance(suggestions_payload, Mapping):
            payload_function = suggestions_payload.get("function")
            if isinstance(payload_function, str) and payload_function != function:
                raise typer.BadParameter(
                    (
                        f"suggestions JSON function {payload_function!r} did "
                        f"not match {function!r}"
                    ),
                    param_hint="--suggestions-json",
                )
            raw_suggestions = suggestions_payload.get("suggestions")
        else:
            raw_suggestions = suggestions_payload
        if not isinstance(raw_suggestions, list):
            raise typer.BadParameter(
                "suggestions JSON must be a report with a suggestions list or a list",
                param_hint="--suggestions-json",
            )
        suggestion_items = [
            item for item in raw_suggestions if isinstance(item, Mapping)
        ]

    baseline: dict[str, Any] | None = None
    if baseline_checkdiff_json is not None:
        baseline_path = _resolve_existing_cli_file(
            baseline_checkdiff_json,
            melee_root=melee_root,
            label="baseline checkdiff JSON",
        )
        try:
            baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                f"invalid baseline checkdiff JSON: {exc}",
                param_hint="--baseline-checkdiff-json",
            ) from exc
        baseline = _control_flow_baseline_from_checkdiff(
            baseline_payload if isinstance(baseline_payload, Mapping) else None
        )

    if source_file is not None:
        resolved_source = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
        source_text = resolved_source.read_text(
            encoding="utf-8",
            errors="replace",
        )
    else:
        unit = _find_unit_for_function(function, melee_root)
        if unit is not None:
            candidate_source = melee_root / "src" / f"{unit}.c"
            if candidate_source.exists():
                resolved_source = candidate_source
                source_text = candidate_source.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

    if source_text is None and not candidate_specs:
        payload = _control_flow_empty_payload(
            function=function,
            source=None,
            blocker="source-unavailable",
            reason="source file could not be resolved",
        )
        if json_out:
            print(json.dumps(payload, indent=2))
        else:
            print("control-flow-shape-search")
            print("blocked: source-unavailable")
        return

    probes = []
    scan_status: Mapping[str, Any] = {
        "blocker": "no-control-flow-shape-probes",
        "reason": "no safe control-flow source transform matched",
        "supported_candidate_count": 0,
        "rejected_candidate_count": 0,
    }
    if source_text is not None:
        if suggestion_items is not None:
            probes, scan_status = materialize_control_flow_suggestions(
                source_text,
                function,
                suggestion_items,
                operator_filter=operator_filter or None,
                max_probes_per_family=max(1, max_probes),
            )
        else:
            probes, scan_status = scan_control_flow_shape_probes(
                source_text,
                function,
                operator_filter=operator_filter or None,
                max_probes=max_probes,
            )
        probes = probes[:max_probes]

    generated_source_dir: Path | None = None
    generated_probe_paths: dict[str, Path] = {}
    if probes and (json_out or compile_probes):
        if output_dir is not None:
            generated_source_dir = output_dir.expanduser()
            if not generated_source_dir.is_absolute():
                generated_source_dir = (Path.cwd() / generated_source_dir).resolve()
            generated_source_dir.mkdir(parents=True, exist_ok=True)
        else:
            generated_source_dir = Path(
                tempfile.mkdtemp(prefix="control-flow-shape-search-")
            )
        for probe in probes:
            path = generated_source_dir / f"{probe.label}.c"
            path.write_text(probe.source_text, encoding="utf-8")
            generated_probe_paths[probe.label] = path

    probe_payloads: list[dict[str, Any]] = []
    for probe in probes:
        payload = probe.to_dict()
        _control_flow_attach_probe_metadata(payload)
        payload["source_hunks"] = _source_hunks_for_probe(
            source_text,
            probe.source_text,
            probe.label,
        )
        probe_payloads.append(payload)
    probe_by_label = {str(probe["label"]): probe for probe in probe_payloads}
    variants: list[dict[str, Any]] = []

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        probe: dict[str, Any] | None = None,
    ) -> None:
        variant: dict[str, Any] = {
            "label": label,
            "operator": operator,
            "status": "ok",
            "path": str(path),
            "source_retained": str(path) if path.suffix == ".c" else None,
            "match_percent": None,
            "final_match_percent": None,
            "match_percent_error": None,
            "error": None,
            "probe": probe,
            "source_hunks": [],
            "pcdump_path": None,
        }
        if probe is not None:
            variant.update(_control_flow_probe_metadata(probe))
        if path.suffix == ".c":
            variant["source_hunks"] = _source_hunks_for_probe(
                source_text,
                path.read_text(encoding="utf-8", errors="replace"),
                label,
            )
        try:
            if path.suffix != ".c":
                raise ValueError(f"expected .c source candidate, got {path}")
            pcdump_text = _control_flow_compile_source_variant(
                DiffInput(
                    label=label,
                    token=str(path),
                    kind="source",
                    path=path,
                ),
                function=function,
                melee_root=melee_root,
                timeout=timeout,
            )
            variant["pcdump_path"] = _write_retained_pcdump(path, pcdump_text)
            if score_match_percent:
                status = (
                    _make_real_score_status("control-flow-shape-search", label)
                    if not json_out
                    else None
                )
                score = _score_source_candidate_real_tree(
                    path,
                    function=function,
                    melee_root=melee_root,
                    timeout=timeout,
                    status=status,
                    include_stack_slot=False,
                    include_structural_guard=True,
                )
                variant["match_percent"] = score.match_percent
                variant["final_match_percent"] = score.match_percent
                variant["match_percent_error"] = score.match_percent_error
                checkdiff = _compact_checkdiff_payload(score.checkdiff_payload)
                if checkdiff is not None:
                    variant["checkdiff"] = checkdiff
            checkdiff_delta = _control_flow_checkdiff_delta(
                variant=variant,
                baseline=baseline,
            )
            if checkdiff_delta is not None:
                variant["checkdiff_delta"] = checkdiff_delta
        except CompileFailure as exc:
            variant["status"] = "build-failed"
            variant["error"] = str(exc)
        except Exception as exc:
            variant["status"] = "failed"
            variant["error"] = str(exc)
        variants.append(variant)

    for spec in candidate_specs:
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        if operator not in DEFAULT_CONTROL_FLOW_OPERATORS:
            raise typer.BadParameter(
                "expected control-flow shape operator candidate",
                param_hint="--candidate",
            )
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes:
        for probe in probes:
            path = generated_probe_paths.get(probe.label)
            if path is None:
                continue
            _score_candidate(
                label=probe.label,
                operator=probe.operator,
                path=path,
                probe=probe_by_label.get(probe.label),
            )

    variants.sort(
        key=lambda variant: (
            0
            if variant.get("status") == "ok"
            and (
                variant.get("final_match_percent") == 100.0
                or variant.get("match_percent") == 100.0
            )
            else 1,
            -(
                float(
                    variant.get("final_match_percent")
                    if variant.get("final_match_percent") is not None
                    else variant.get("match_percent")
                    if variant.get("match_percent") is not None
                    else -1.0
                )
            ),
            str(variant.get("label") or ""),
        )
    )

    validated = any(
        variant.get("status") == "ok"
        and (
            variant.get("final_match_percent") == 100.0
            or variant.get("match_percent") == 100.0
        )
        for variant in variants
    )
    family_results = (
        scan_status.get("families")
        if isinstance(scan_status.get("families"), list)
        else []
    )
    scored_variants = _control_flow_scored_variants(variants)
    terminal_proofs = list(
        scan_status.get("terminal_proofs")
        if isinstance(scan_status.get("terminal_proofs"), list)
        else []
    )
    if validated:
        blocker = None
        stop_condition = _control_flow_stop_condition(
            "validated",
            blocker=None,
            reason="validated candidate found",
        )
    elif scored_variants and baseline is not None and any(
        _control_flow_variant_improved_baseline(variant) for variant in scored_variants
    ):
        blocker = None
        stop_condition = _control_flow_stop_condition(
            "improved",
            blocker=None,
            reason="at least one candidate improved the supplied baseline checkdiff",
        )
    elif variants and not scored_variants:
        blocker = _control_flow_unscored_blocker(variants)
        stop_condition = _control_flow_stop_condition(
            "blocked",
            blocker=blocker,
            reason=(
                "generated probes did not produce checkdiff or match-score "
                "evidence"
            ),
        )
        terminal_proofs.append(
            _control_flow_candidates_unscored_proof(
                baseline=baseline,
                variants=variants,
                family_results=family_results,
            )
        )
    elif variants and baseline is not None:
        blocker = "no-control-flow-shape-candidate-improved-checkdiff"
        stop_condition = _control_flow_stop_condition(
            "unvalidated",
            blocker=blocker,
            reason="all generated probes scored at or below the supplied baseline",
        )
        terminal_proofs.append(
            _control_flow_candidates_exhausted_proof(
                baseline=baseline,
                variants=variants,
                family_results=family_results,
            )
        )
    elif variants:
        blocker = "no-control-flow-shape-candidate"
        stop_condition = _control_flow_stop_condition(
            "unvalidated",
            blocker=blocker,
            reason="no control-flow shape candidate reached a true 100% match",
        )
        terminal_proofs.append(
            _control_flow_candidates_exhausted_proof(
                baseline=None,
                variants=variants,
                family_results=family_results,
            )
        )
    elif probes and not compile_probes and not candidate_specs:
        blocker = "no-control-flow-shape-candidate"
        stop_condition = _control_flow_stop_condition(
            "unvalidated",
            blocker=blocker,
            reason="safe control-flow shape probes were generated but not compiled",
        )
    elif family_results and all(
        isinstance(result, Mapping)
        and str(result.get("status")) in {"terminal", "unsupported"}
        for result in family_results
    ):
        blocker = "control-flow-shape-families-terminal"
        stop_condition = _control_flow_stop_condition(
            "terminal",
            blocker=blocker,
            reason="all selected control-flow shape families have terminal proofs",
        )
    else:
        blocker = str(scan_status.get("blocker") or "no-control-flow-shape-probes")
        stop_condition = _control_flow_stop_condition(
            "blocked",
            blocker=blocker,
            reason=str(scan_status.get("reason") or blocker),
        )

    payload = {
        "function": function,
        "source": str(resolved_source) if resolved_source is not None else None,
        "generated_source_dir": (
            str(generated_source_dir) if generated_source_dir is not None else None
        ),
        "probe_count": len(probes),
        "blocker": blocker,
        "stop_condition": stop_condition,
        "probes": probe_payloads,
        "variants": variants,
    }
    if baseline is not None:
        payload["baseline"] = baseline
    if family_results:
        payload["family_results"] = family_results
    if terminal_proofs:
        payload["terminal_proofs"] = terminal_proofs

    if json_out:
        print(json.dumps(payload, indent=2))
        return

    print("control-flow-shape-search")
    print(f"function: {function}")
    print(f"source: {payload['source']}")
    print(f"generated_source_dir: {payload['generated_source_dir']}")
    print(
        f"stop: {stop_condition['kind']}"
        + (f" ({stop_condition['blocker']})" if stop_condition["blocker"] else "")
    )
    for family in family_results:
        if not isinstance(family, Mapping):
            continue
        print(
            f"- family {family.get('family_id')} "
            f"{family.get('status')} probes={family.get('probe_count')}"
        )
    for variant in variants:
        line = f"- {variant['label']} [{variant['operator']}] {variant['status']}"
        if variant.get("final_match_percent") is not None:
            line += f" match={variant['final_match_percent']:.6g}"
        print(line)
        if variant.get("error"):
            print(f"  error: {variant['error']}")
        if variant.get("source_retained"):
            print(f"  source: {variant['source_retained']}")
        if variant.get("pcdump_path"):
            print(f"  pcdump: {variant['pcdump_path']}")



@mutate_app.command(name="indexed-struct-search")
def mutate_indexed_struct_search_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function",
            "-f",
            help="Function to explore.",
        ),
    ],
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate indexed-struct probes.",
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help="Compile generated indexed-struct source probes.",
        ),
    ] = True,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to list or compile.",
        ),
    ] = 12,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Compile and score indexed struct pointer dematerialization probes."""
    from src.cli.debug import (
        _find_unit_for_function,
        _indexed_struct_checkdiff_hint,
        _indexed_struct_compile_source_variant,
        _make_real_score_status,
        _parse_lifetime_layout_candidate,
        _probe_requires_full_unit_source,
        _full_unit_source_for_probe,
        _resolve_existing_cli_file,
        _score_source_candidate_real_tree,
        DEFAULT_MELEE_ROOT,
    )
    from ...mwcc_debug.diff_capture import CompileFailure, DiffInput
    from ...mwcc_debug.pressure_explorer import (
        scan_indexed_struct_pointer_probes,
    )

    melee_root = DEFAULT_MELEE_ROOT
    resolved_source: Path | None = None
    source_text: str | None = None
    candidate_specs = candidates or []
    if source_file is not None:
        resolved_source = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
        source_text = resolved_source.read_text(
            encoding="utf-8",
            errors="replace",
        )
    else:
        unit = _find_unit_for_function(function, melee_root)
        if unit is not None:
            candidate_source = melee_root / "src" / f"{unit}.c"
            if candidate_source.exists():
                resolved_source = candidate_source
                source_text = candidate_source.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

    if source_text is None and not candidate_specs:
        payload = _indexed_struct_empty_payload(
            function=function,
            source=None,
            blocker="source-unavailable",
            reason="source file could not be resolved",
        )
        if json_out:
            print(json.dumps(payload, indent=2))
        else:
            print("indexed-struct-search")
            print("blocked: source-unavailable")
        return

    probes = []
    scan_status: Mapping[str, Any] = {
        "blocker": "indexed-struct-hint-unavailable",
        "reason": (
            "checkdiff hint could not be associated with a supported source "
            "pointer initializer"
        ),
        "supported_candidate_count": 0,
        "rejected_candidate_count": 0,
    }
    if source_text is not None:
        hint = _indexed_struct_checkdiff_hint(
            function,
            melee_root=melee_root,
            timeout=timeout,
        )
        if hint is not None or not candidate_specs:
            probes, scan_status = scan_indexed_struct_pointer_probes(
                source_text,
                function,
                max_probes=max_probes,
            )
        probes = probes[:max_probes]

    generated_source_dir: Path | None = None
    generated_probe_paths: dict[str, Path] = {}
    if probes and (json_out or compile_probes):
        generated_source_dir = Path(
            tempfile.mkdtemp(prefix="indexed-struct-search-")
        )
        for probe in probes:
            path = generated_source_dir / f"{probe.label}.c"
            path.write_text(probe.source_text, encoding="utf-8")
            generated_probe_paths[probe.label] = path

    probe_payloads: list[dict[str, Any]] = []
    for probe in probes:
        payload = probe.to_dict()
        payload["source_hunks"] = _source_hunks_for_probe(
            source_text,
            probe.source_text,
            probe.label,
        )
        probe_payloads.append(payload)
    probe_by_label = {str(probe["label"]): probe for probe in probe_payloads}
    variants: list[dict[str, Any]] = []

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        probe: dict[str, Any] | None = None,
    ) -> None:
        variant: dict[str, Any] = {
            "label": label,
            "operator": operator,
            "status": "ok",
            "path": str(path),
            "source_retained": str(path) if path.suffix == ".c" else None,
            "match_percent": None,
            "final_match_percent": None,
            "match_percent_error": None,
            "error": None,
            "probe": probe,
            "source_hunks": [],
            "pcdump_path": None,
        }
        if path.suffix == ".c":
            variant["source_hunks"] = _source_hunks_for_probe(
                source_text,
                path.read_text(encoding="utf-8", errors="replace"),
                label,
            )
        try:
            if path.suffix != ".c":
                raise ValueError(f"expected .c source candidate, got {path}")
            pcdump_text = _indexed_struct_compile_source_variant(
                DiffInput(
                    label=label,
                    token=str(path),
                    kind="source",
                    path=path,
                ),
                function=function,
                melee_root=melee_root,
                timeout=timeout,
            )
            variant["pcdump_path"] = _write_retained_pcdump(path, pcdump_text)
            if score_match_percent:
                status = (
                    _make_real_score_status("indexed-struct-search", label)
                    if not json_out
                    else None
                )
                score = _score_source_candidate_real_tree(
                    path,
                    function=function,
                    melee_root=melee_root,
                    timeout=timeout,
                    status=status,
                    include_stack_slot=False,
                    include_structural_guard=True,
                )
                variant["match_percent"] = score.match_percent
                variant["final_match_percent"] = score.match_percent
                variant["match_percent_error"] = score.match_percent_error
                variant["target_score"] = _indexed_struct_target_score(
                    match_percent=score.match_percent,
                    match_percent_error=score.match_percent_error,
                )
                checkdiff = _compact_checkdiff_payload(score.checkdiff_payload)
                if checkdiff is not None:
                    variant["checkdiff"] = checkdiff
        except CompileFailure as exc:
            variant["status"] = "build-failed"
            variant["error"] = str(exc)
        except Exception as exc:
            variant["status"] = "failed"
            variant["error"] = str(exc)
        variants.append(variant)

    for spec in candidate_specs:
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        if operator != "indexed-struct-pointer":
            raise typer.BadParameter(
                "expected indexed-struct-pointer candidate",
                param_hint="--candidate",
            )
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes:
        for probe in probes:
            path = generated_probe_paths.get(probe.label)
            if path is None:
                continue
            _score_candidate(
                label=probe.label,
                operator=probe.operator,
                path=path,
                probe=probe_by_label.get(probe.label),
            )

    variants.sort(
        key=lambda variant: (
            0
            if variant.get("status") == "ok"
            and (
                variant.get("final_match_percent") == 100.0
                or variant.get("match_percent") == 100.0
            )
            else 1,
            -(
                float(
                    variant.get("final_match_percent")
                    if variant.get("final_match_percent") is not None
                    else variant.get("match_percent")
                    if variant.get("match_percent") is not None
                    else -1.0
                )
            ),
            str(variant.get("label") or ""),
        )
    )

    validated = any(
        variant.get("status") == "ok"
        and (
            variant.get("final_match_percent") == 100.0
            or variant.get("match_percent") == 100.0
        )
        for variant in variants
    )
    if validated:
        blocker = None
        stop_condition = _indexed_struct_stop_condition(
            "validated",
            blocker=None,
            reason="validated candidate found",
        )
    elif variants:
        blocker = "no-indexed-struct-candidate"
        stop_condition = _indexed_struct_stop_condition(
            "unvalidated",
            blocker=blocker,
            reason="no indexed-struct candidate reached a true 100% match",
        )
    elif probes and not compile_probes and not candidate_specs:
        blocker = "no-indexed-struct-candidate"
        stop_condition = _indexed_struct_stop_condition(
            "unvalidated",
            blocker=blocker,
            reason="safe indexed-struct probes were generated but not compiled",
        )
    else:
        blocker = str(scan_status.get("blocker") or "no-safe-materialized-pointer")
        stop_condition = _indexed_struct_stop_condition(
            "blocked",
            blocker=blocker,
            reason=str(scan_status.get("reason") or blocker),
        )

    payload = {
        "function": function,
        "source": str(resolved_source) if resolved_source is not None else None,
        "generated_source_dir": (
            str(generated_source_dir) if generated_source_dir is not None else None
        ),
        "probe_count": len(probes),
        "blocker": blocker,
        "stop_condition": stop_condition,
        "probes": probe_payloads,
        "variants": variants,
    }
    terminal_proof = (
        _indexed_struct_terminal_proof(
            function=function,
            blocker=blocker,
            variants=variants,
            scan_status=scan_status,
        )
        if blocker == "no-indexed-struct-candidate"
        else None
    )
    if terminal_proof is not None:
        payload["terminal_proof"] = terminal_proof

    if json_out:
        print(json.dumps(payload, indent=2))
        return

    print("indexed-struct-search")
    print(f"function: {function}")
    print(f"source: {payload['source']}")
    print(f"generated_source_dir: {payload['generated_source_dir']}")
    print(
        f"stop: {stop_condition['kind']}"
        + (f" ({stop_condition['blocker']})" if stop_condition["blocker"] else "")
    )
    for variant in variants:
        line = f"- {variant['label']} [{variant['operator']}] {variant['status']}"
        if variant.get("final_match_percent") is not None:
            line += f" match={variant['final_match_percent']:.6g}"
        print(line)
        if variant.get("error"):
            print(f"  error: {variant['error']}")
        if variant.get("source_retained"):
            print(f"  source: {variant['source_retained']}")
        if variant.get("pcdump_path"):
            print(f"  pcdump: {variant['pcdump_path']}")


def _name_magic_source_stop_condition(
    kind: str,
    *,
    blocker: str | None,
    reason: str,
) -> dict[str, str | None]:
    return {"kind": kind, "blocker": blocker, "reason": reason}


def _name_magic_source_evidence_payload(
    *,
    parsed: Any,
    checkdiff_payload: Mapping[str, Any],
    object_evidence: Mapping[str, Any],
    function: str,
) -> dict[str, Any]:
    anonymous_sdata2 = object_evidence.get("anonymous_sdata2")
    if isinstance(anonymous_sdata2, Mapping):
        anonymous_payload = list(anonymous_sdata2.values())
    else:
        anonymous_payload = []
    suggestions = object_evidence.get("name_magic_suggestions")
    payload = {
        "raw_relocations": [
            {
                **dict(relocation.__dict__),
                "operator_family": relocation.operator_family,
            }
            for relocation in parsed.relocations
        ],
        "residual_diff_count": parsed.residual_diff_count,
        "classification": checkdiff_payload.get("classification"),
        "anonymous_sdata2": anonymous_payload,
        "name_magic_suggestions": (
            list(suggestions) if isinstance(suggestions, list) else []
        ),
    }
    post_link = _name_magic_post_link_routes(
        function=function,
        parsed=parsed,
        object_evidence=object_evidence,
    )
    if post_link:
        payload["post_link_name_magic"] = post_link
    return payload


def _name_magic_post_link_routes(
    *,
    function: str,
    parsed: Any,
    object_evidence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    suggestions = object_evidence.get("name_magic_suggestions")
    exact_suggestions: set[tuple[str, str]] = set()
    if isinstance(suggestions, list):
        for suggestion in suggestions:
            if not isinstance(suggestion, Mapping):
                continue
            anonymous = suggestion.get("anonymous") or suggestion.get("name")
            target = suggestion.get("target")
            if isinstance(anonymous, str) and isinstance(target, str):
                exact_suggestions.add((anonymous, target))

    routes: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for relocation in getattr(parsed, "relocations", []) or []:
        current = getattr(relocation, "current_symbol", "")
        target = getattr(relocation, "expected_symbol", "")
        if not isinstance(current, str) or not current.startswith("@"):
            continue
        if not isinstance(target, str) or not target:
            continue
        key = (current, target)
        if key in seen:
            continue
        seen.add(key)
        route = {
            "operator": "post-link-name-magic",
            "anonymous_symbol": current,
            "target_symbol": target,
            "map": f"{current}={target}",
            "verify_command": (
                "melee-agent debug util verify-name-magic "
                f"-f {function} --map {current}={target}"
            ),
            "apply_auto_viable": key in exact_suggestions,
            "apply_auto_command": (
                "melee-agent debug util verify-name-magic "
                f"-f {function} --apply-auto"
            )
            if key in exact_suggestions
            else None,
            "reason": (
                "post-link rename preserves source shape and allocator "
                "behavior when no unique source literal site is safe"
            ),
        }
        routes.append({k: v for k, v in route.items() if v is not None})
    return routes


def _name_magic_source_blocked_payload(
    *,
    function: str,
    source: Path | None,
    blocker: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "function": function,
        "source": str(source) if source is not None else None,
        "generated_source_dir": None,
        "probe_count": 0,
        "blocker": blocker,
        "stop_condition": _name_magic_source_stop_condition(
            "blocked",
            blocker=blocker,
            reason=reason,
        ),
        "evidence": evidence or {},
        "probes": [],
        "variants": [],
    }
    return payload


def _name_magic_source_match_percent(variant: Mapping[str, Any]) -> float | None:
    value = variant.get("final_match_percent")
    if value is None:
        value = variant.get("match_percent")
    return float(value) if isinstance(value, (int, float)) else None


def _rank_name_magic_source_variants(
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked = list(variants)
    ranked.sort(
        key=lambda variant: (
            0
            if variant.get("status") == "ok"
            and variant.get("no_name_magic_match") is True
            else 1,
            0
            if variant.get("status") == "ok"
            and _name_magic_source_match_percent(variant) == 100.0
            else 1,
            0 if variant.get("status") == "ok" else 1,
            -(
                _name_magic_source_match_percent(variant)
                if _name_magic_source_match_percent(variant) is not None
                else -1.0
            ),
            str(variant.get("label") or ""),
        )
    )
    return ranked


def _name_magic_section_anchor_offsets_from_payload(
    payload: Mapping[str, Any],
) -> list[str]:
    from ...mwcc_debug.name_magic_source import parse_name_magic_relocation_evidence

    parsed = parse_name_magic_relocation_evidence(dict(payload))
    return sorted(
        {
            relocation.offset
            for relocation in parsed.relocations
            if relocation.current_symbol.startswith("...data.")
        }
    )


def _name_magic_section_anchor_verdict(
    evidence: Mapping[str, Any],
    variants: list[dict[str, Any]],
) -> dict[str, Any] | None:
    raw_relocations = evidence.get("raw_relocations")
    if not isinstance(raw_relocations, list):
        return None
    initial_offsets = sorted(
        {
            str(relocation.get("offset"))
            for relocation in raw_relocations
            if isinstance(relocation, Mapping)
            and str(relocation.get("current_symbol") or "").startswith("...data.")
        }
    )
    if not initial_offsets:
        return None

    for variant in variants:
        if variant.get("status") != "ok":
            continue
        if variant.get("operator") not in {
            "data-symbol-static-to-global",
            "name-magic-source-combined",
        }:
            continue
        checkdiff_payload = variant.get("checkdiff_payload")
        if not isinstance(checkdiff_payload, Mapping):
            continue
        remaining_offsets = _name_magic_section_anchor_offsets_from_payload(
            checkdiff_payload
        )
        resolved_offsets = [
            offset for offset in initial_offsets if offset not in remaining_offsets
        ]
        if not resolved_offsets:
            continue
        return {
            "status": (
                "source-fixable"
                if not remaining_offsets
                else "partially-source-fixable"
            ),
            "candidate_label": variant.get("label"),
            "operator": variant.get("operator"),
            "resolved_offsets": resolved_offsets,
            "remaining_offsets": remaining_offsets,
        }
    return None


_NAME_MAGIC_SOURCE_CANDIDATE_OPERATORS = {
    "bss-anchor-source-binding",
    "data-symbol-static-to-global",
    "sdata2-named-float-load",
    "name-magic-source-combined",
}



@mutate_app.command(name="name-magic-source-declarations")
def mutate_name_magic_source_declarations_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function",
            "-f",
            help="Function to explore.",
        ),
    ],
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate name-magic source probes.",
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help="Compile generated name-magic source probes.",
        ),
    ] = True,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily apply the whole candidate "
                "file in the real tree and validate with --no-name-magic."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to list or compile.",
        ),
    ] = 12,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Generate source declarations/references for name-magic relocation mismatches.

    Common switches: --score-match-percent, --no-score-match-percent,
    --compile-probes.
    """
    from src.cli.debug import (
        _find_unit_for_function,
        _make_real_score_status,
        _name_magic_header_candidate_text,
        _name_magic_header_for_source,
        _name_magic_object_evidence,
        _parse_lifetime_layout_candidate,
        _probe_requires_full_unit_source,
        _full_unit_source_for_probe,
        _resolve_existing_cli_file,
        _run_checkdiff_no_name_magic_json,
        _score_source_candidate_real_tree,
        _score_whole_source_candidate_no_name_magic,
        DEFAULT_MELEE_ROOT,
    )
    from ...mwcc_debug.name_magic_source import (
        NameMagicBlocker,
        generate_name_magic_source_probes,
        parse_name_magic_relocation_evidence,
    )

    melee_root = DEFAULT_MELEE_ROOT
    candidate_specs = candidates or []
    resolved_source: Path | None = None
    source_text: str | None = None
    unit = _find_unit_for_function(function, melee_root)

    if source_file is not None:
        resolved_source = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
        source_text = resolved_source.read_text(
            encoding="utf-8",
            errors="replace",
        )
    elif unit is not None:
        candidate_source = melee_root / "src" / f"{unit}.c"
        if candidate_source.exists():
            resolved_source = candidate_source
            source_text = candidate_source.read_text(
                encoding="utf-8",
                errors="replace",
            )

    def _emit(payload: dict[str, Any]) -> None:
        if json_out:
            print(json.dumps(payload, indent=2))
            return
        print("name-magic-source-declarations")
        print(f"function: {function}")
        print(f"source: {payload.get('source')}")
        stop = payload.get("stop_condition") or {}
        print(
            f"stop: {stop.get('kind')}"
            + (f" ({stop.get('blocker')})" if stop.get("blocker") else "")
        )
        section_anchor = payload.get("section_anchor_verdict")
        if isinstance(section_anchor, Mapping):
            print(f"section-anchor verdict: {section_anchor.get('status')}")
        if payload.get("generated_source_dir"):
            print(f"generated_source_dir: {payload['generated_source_dir']}")
        for variant in payload.get("variants", []):
            line = (
                f"- {variant['label']} [{variant['operator']}] "
                f"{variant['status']}"
            )
            if variant.get("final_match_percent") is not None:
                line += f" match={variant['final_match_percent']:.6g}"
            if variant.get("no_name_magic_match") is not None:
                line += f" no-name-magic={variant['no_name_magic_match']}"
            print(line)
            if variant.get("error"):
                print(f"  error: {variant['error']}")

    if source_text is None and not candidate_specs:
        _emit(
            _name_magic_source_blocked_payload(
                function=function,
                source=None,
                blocker="source-unavailable",
                reason="source file could not be resolved",
            )
        )
        return

    checkdiff_payload, checkdiff_error = _run_checkdiff_no_name_magic_json(
        function,
        melee_root=melee_root,
        timeout=timeout,
        no_build=False,
    )
    if checkdiff_error is not None or checkdiff_payload is None:
        _emit(
            _name_magic_source_blocked_payload(
                function=function,
                source=resolved_source,
                blocker=NameMagicBlocker.NO_NAME_MAGIC_VALIDATION_FAILED.value,
                reason=(
                    checkdiff_error
                    or "checkdiff --no-name-magic did not produce JSON"
                ),
            )
        )
        return

    if unit is None and not candidate_specs:
        _emit(
            _name_magic_source_blocked_payload(
                function=function,
                source=resolved_source,
                blocker="source-unavailable",
                reason="source unit could not be resolved from report.json",
            )
        )
        return

    if unit is not None:
        object_evidence, object_error = _name_magic_object_evidence(
            unit,
            melee_root,
        )
        if object_error is not None or object_evidence is None:
            _emit(
                _name_magic_source_blocked_payload(
                    function=function,
                    source=resolved_source,
                    blocker=object_error or "object-evidence-unavailable",
                    reason=object_error or "object evidence could not be read",
                )
            )
            return
    else:
        object_evidence = {
            "anonymous_sdata2": {},
            "name_magic_suggestions": [],
        }

    parsed = parse_name_magic_relocation_evidence(checkdiff_payload)
    evidence = _name_magic_source_evidence_payload(
        parsed=parsed,
        checkdiff_payload=checkdiff_payload,
        object_evidence=object_evidence,
        function=function,
    )

    classification = checkdiff_payload.get("classification")
    anonymous_sdata2 = object_evidence.get("anonymous_sdata2")
    has_anonymous_sdata2 = (
        isinstance(anonymous_sdata2, Mapping) and bool(anonymous_sdata2)
    )
    if (
        parsed.blocker
        == NameMagicBlocker.RAW_DIFF_NO_SUPPORTED_DATA_SYMBOL_PAIR
        and isinstance(classification, Mapping)
        and classification.get("primary") == "data-symbol-or-relocation"
        and has_anonymous_sdata2
        and not candidate_specs
    ):
        _emit(
            _name_magic_source_blocked_payload(
                function=function,
                source=resolved_source,
                blocker=NameMagicBlocker.SDATA2_POOL_ORDER_DEPENDENT.value,
                reason=(
                    ".sdata2 anonymous pool order evidence was present, but "
                    "checkdiff did not expose a same-offset source-addressable "
                    "relocation pair"
                ),
                evidence=evidence,
            )
        )
        return

    probes = []
    probe_blocker = parsed.blocker
    if source_text is not None and (
        parsed.blocker is None
        or parsed.blocker == NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR
    ):
        probes, probe_blocker = generate_name_magic_source_probes(
            source_text,
            function,
            checkdiff_payload,
            object_evidence["anonymous_sdata2"],
            max_probes=max_probes,
        )
    probes = probes[:max_probes]

    post_link_routes = evidence.get("post_link_name_magic")
    sdata2_source_site_blocked = (
        probe_blocker == NameMagicBlocker.UNSUPPORTED_SOURCE_SITE
        and isinstance(post_link_routes, list)
        and bool(post_link_routes)
    )
    if sdata2_source_site_blocked and not probes and not candidate_specs:
        _emit(
            _name_magic_source_blocked_payload(
                function=function,
                source=resolved_source,
                blocker=NameMagicBlocker.NO_NAME_MAGIC_CANDIDATE.value,
                reason=(
                    "sdata2 relocation has no safe unique source literal site; "
                    "use a post-link name-magic route from "
                    "evidence.post_link_name_magic"
                ),
                evidence=evidence,
            )
        )
        return

    if probe_blocker is not None and not probes and not candidate_specs:
        _emit(
            _name_magic_source_blocked_payload(
                function=function,
                source=resolved_source,
                blocker=probe_blocker.value,
                reason=getattr(parsed, "reason", None) or probe_blocker.value,
                evidence=evidence,
            )
        )
        return

    generated_source_dir: Path | None = None
    generated_probe_paths: dict[str, Path] = {}
    generated_probe_headers: dict[str, tuple[Path, Path]] = {}
    if probes and (json_out or compile_probes):
        generated_source_dir = Path(
            tempfile.mkdtemp(prefix="name-magic-source-declarations-")
        )
        target_header = _name_magic_header_for_source(resolved_source)
        target_header_text = (
            target_header.read_text(encoding="utf-8", errors="replace")
            if target_header is not None
            else None
        )
        for probe in probes:
            path = generated_source_dir / f"{probe.label}.c"
            path.write_text(probe.source_text, encoding="utf-8")
            generated_probe_paths[probe.label] = path
            if (
                probe.header_declarations
                and target_header is not None
                and target_header_text is not None
            ):
                header_path = generated_source_dir / f"{probe.label}.h"
                header_path.write_text(
                    _name_magic_header_candidate_text(
                        target_header_text,
                        probe.header_declarations,
                    ),
                    encoding="utf-8",
                )
                generated_probe_headers[probe.label] = (
                    header_path,
                    target_header,
                )

    probe_payloads = [probe.to_dict() for probe in probes]
    probe_by_label = {probe.label: probe.to_dict() for probe in probes}
    variants: list[dict[str, Any]] = []

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        probe: dict[str, Any] | None = None,
        header_path: Path | None = None,
        header_target: Path | None = None,
    ) -> None:
        variant: dict[str, Any] = {
            "label": label,
            "operator": operator,
            "status": "ok",
            "path": str(path),
            "source_retained": str(path) if path.suffix == ".c" else None,
            "match_percent": None,
            "final_match_percent": None,
            "match_percent_error": None,
            "no_name_magic_match": None,
            "error": None,
            "probe": probe,
        }
        if header_path is not None:
            variant["header_retained"] = str(header_path)
        if header_target is not None:
            variant["header_target"] = str(header_target)
        try:
            if path.suffix != ".c":
                raise ValueError(f"expected .c source candidate, got {path}")
            if score_match_percent:
                status = (
                    _make_real_score_status(
                        "name-magic-source-declarations",
                        label,
                    )
                    if not json_out
                    else None
                )
                score = _score_whole_source_candidate_no_name_magic(
                    path,
                    function=function,
                    melee_root=melee_root,
                    header_path=header_path,
                    header_target=header_target,
                    timeout=timeout,
                    status=status,
                )
                variant["match_percent"] = score.match_percent
                variant["final_match_percent"] = score.match_percent
                variant["match_percent_error"] = score.match_percent_error
                variant["no_name_magic_match"] = score.no_name_magic_match
                if score.checkdiff_payload is not None:
                    variant["checkdiff_payload"] = score.checkdiff_payload
                if score.match_percent_error is not None and (
                    score.match_percent is None
                    and score.no_name_magic_match is None
                ):
                    variant["status"] = "failed"
                    variant["error"] = score.match_percent_error
        except Exception as exc:
            variant["status"] = "failed"
            variant["error"] = str(exc)
        variants.append(variant)

    for spec in candidate_specs:
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        if operator not in _NAME_MAGIC_SOURCE_CANDIDATE_OPERATORS:
            raise typer.BadParameter(
                "expected name-magic source candidate operator",
                param_hint="--candidate",
            )
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes:
        for probe in probes:
            path = generated_probe_paths.get(probe.label)
            if path is None:
                continue
            header_pair = generated_probe_headers.get(probe.label)
            _score_candidate(
                label=probe.label,
                operator=probe.operator,
                path=path,
                probe=probe_by_label.get(probe.label),
                header_path=header_pair[0] if header_pair is not None else None,
                header_target=header_pair[1] if header_pair is not None else None,
            )

    ranked_variants = _rank_name_magic_source_variants(variants)
    section_anchor_verdict = _name_magic_section_anchor_verdict(
        evidence,
        ranked_variants,
    )
    validated = any(
        variant.get("status") == "ok"
        and variant.get("operator") != "bss-anchor-source-binding"
        and _name_magic_source_match_percent(variant) == 100.0
        and variant.get("no_name_magic_match") is True
        for variant in ranked_variants
    )
    if validated:
        blocker = None
        stop_condition = _name_magic_source_stop_condition(
            "validated",
            blocker=None,
            reason="validated candidate found",
        )
    elif ranked_variants:
        if (
            section_anchor_verdict is not None
            and section_anchor_verdict.get("status") == "source-fixable"
        ):
            blocker = (
                NameMagicBlocker.SECTION_ANCHOR_SOURCE_FIXABLE_RESIDUAL.value
            )
            stop_condition = _name_magic_source_stop_condition(
                "blocked",
                blocker=blocker,
                reason=(
                    "section-anchor relocations were source-fixable, but "
                    "residual no-name-magic mismatch remains"
                ),
            )
        else:
            blocker = NameMagicBlocker.NO_NAME_MAGIC_CANDIDATE.value
            stop_condition = _name_magic_source_stop_condition(
                "unvalidated",
                blocker=blocker,
                reason="no source candidate reached a true --no-name-magic match",
            )
    elif probes and not compile_probes and not candidate_specs:
        blocker = NameMagicBlocker.NO_NAME_MAGIC_CANDIDATE.value
        stop_condition = _name_magic_source_stop_condition(
            "unvalidated",
            blocker=blocker,
            reason="safe name-magic probes were generated but not compiled",
        )
    else:
        blocker = (
            probe_blocker.value
            if probe_blocker is not None
            else NameMagicBlocker.NO_NAME_MAGIC_CANDIDATE.value
        )
        stop_condition = _name_magic_source_stop_condition(
            "blocked",
            blocker=blocker,
            reason=blocker,
        )

    payload = {
        "function": function,
        "source": str(resolved_source) if resolved_source is not None else None,
        "generated_source_dir": (
            str(generated_source_dir) if generated_source_dir is not None else None
        ),
        "probe_count": len(probes),
        "blocker": blocker,
        "stop_condition": stop_condition,
        "evidence": evidence,
        "probes": probe_payloads,
        "variants": ranked_variants,
    }
    if section_anchor_verdict is not None:
        payload["section_anchor_verdict"] = section_anchor_verdict
    _emit(payload)



@mutate_app.command(name="frame-transform-search")
def mutate_frame_transform_search_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to explore.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Baseline pcdump. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    expected_asm: Annotated[
        Optional[Path],
        typer.Option(
            "--expected-asm",
            help="Path to expected target asm. Omit to extract via function.",
        ),
    ] = None,
    no_expected: Annotated[
        bool,
        typer.Option(
            "--no-expected",
            help="Allow planning without expected asm; validation will report no target.",
        ),
    ] = False,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file used to generate directed frame probes.",
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help=(
                "Directory for generated --compile-probes source files. "
                "When omitted, JSON output retains a temp directory because "
                "variant paths are machine-readable follow-up inputs."
            ),
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help=(
                "Candidate pcdump/source to score, repeatable. Format "
                "OPERATOR=path or LABEL:OPERATOR=path."
            ),
        ),
    ] = None,
    compile_probes: Annotated[
        bool,
        typer.Option(
            "--compile-probes/--no-compile-probes",
            help="Compile generated directed source probes.",
        ),
    ] = True,
    score_match_percent: Annotated[
        bool,
        typer.Option(
            "--score-match-percent/--no-score-match-percent",
            help=(
                "For source candidates, temporarily transfer into the real "
                "tree and read final report.json match percent. Enabled by "
                "default because ranking uses match percent as a tiebreaker."
            ),
        ),
    ] = True,
    max_probes: Annotated[
        int,
        typer.Option(
            "--max-probes",
            help="Maximum generated probes to list or compile.",
        ),
    ] = 12,
    include_transform_corpus: Annotated[
        bool,
        typer.Option(
            "--include-transform-corpus/--no-include-transform-corpus",
            help=(
                "Opt in to transform-corpus source-shape probes after "
                "frame-directed and lifetime fallback probes."
            ),
        ),
    ] = False,
    prefer_staged_source_baseline: Annotated[
        bool,
        typer.Option(
            "--prefer-staged-source-baseline/--no-prefer-staged-source-baseline",
            help=(
                "When --source-file and --pcdump are both supplied, prefer the "
                "compiled source-file baseline over the explicit pcdump. By "
                "default explicit pcdumps remain authoritative."
            ),
        ),
    ] = False,
    transform_family: Annotated[
        Optional[list[str]],
        typer.Option(
            "--transform-family",
            help=(
                "Transform-corpus source-shape family to generate. Repeat or "
                "pass comma-separated names; passing this also opts in and "
                "overrides the frame transform-corpus defaults."
            ),
        ),
    ] = None,
    transform_force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--transform-force-phys",
            "--directed-force-phys",
            help=(
                "Proof mapping for transform-corpus source-shape probes, "
                "e.g. IG:PHYS or comma-separated IG:PHYS entries."
            ),
        ),
    ] = None,
    operators: Annotated[
        Optional[list[str]],
        typer.Option(
            "--operator",
            help=(
                "Add an operator family to the directed search. Repeat or "
                "pass comma-separated names; values are unioned with the "
                "frame-divergence plan."
            ),
        ),
    ] = None,
    include_lifetime_fallback: Annotated[
        bool,
        typer.Option(
            "--include-lifetime-fallback/--no-include-lifetime-fallback",
            help=(
                "Also include existing lifetime-layout probes whose operator "
                "is selected by the frame-divergence plan."
            ),
        ),
    ] = True,
    frame_reservation_bytes: Annotated[
        Optional[int],
        typer.Option(
            "--frame-reservation-bytes",
            help=(
                "Override the inferred frame delta with a positive explicit "
                "PAD_STACK(N) probe size for frame-reservation-pad-stack."
            ),
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Per-candidate compile timeout in seconds.",
        ),
    ] = 120,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Compile and score directed source transforms for frame-size divergence."""
    from src.cli.debug import (
        _MalformedSourceCandidate,
        _SourceCandidateRealScore,
        _append_transform_corpus_probes,
        _compact_source_hunk_for_function,
        _detect_frame_residual_hint,
        _find_unit_for_function,
        _frame_report_aliases,
        _frame_source_context,
        _full_unit_source_for_probe,
        _make_real_score_status,
        _parse_lifetime_layout_candidate,
        _path_inside_repo,
        _pcdump_has_symbolic_stack_homes,
        _prevalidate_lifetime_layout_source_candidate,
        _probe_requires_full_unit_source,
        _read_frame_reservation_current_asm,
        _read_frame_reservation_expected_asm,
        _read_frame_reservation_source_current_asm,
        _resolve_existing_cli_file,
        _resolve_pcdump_path,
        _restore_source_snapshot,
        _score_source_candidate_real_tree,
        _source_path_for_function,
        DEFAULT_MELEE_ROOT,
    )
    from ...mwcc_debug.diff_capture import DiffInput, compile_source_variant
    from ...mwcc_debug.pressure_explorer import (
        generate_frame_directed_probes,
        generate_lifetime_layout_probes,
        scan_frame_local_dematerialization_probes,
    )

    melee_root = DEFAULT_MELEE_ROOT
    explicit_pcdump = pcdump is not None
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        melee_root,
        require_fresh=False,
    )
    pcdump_text = pcdump_path.read_text(encoding="utf-8", errors="replace")
    expected_text = _read_frame_reservation_expected_asm(
        function,
        expected_asm=expected_asm,
        no_expected=no_expected,
        melee_root=melee_root,
    )
    defer_explicit_pcdump_current_asm = explicit_pcdump and source_file is not None
    current_text = (
        _read_frame_reservation_current_asm(function, melee_root=melee_root)
        if _pcdump_has_symbolic_stack_homes(pcdump_text)
        and not defer_explicit_pcdump_current_asm
        else None
    )
    _report_function, source_aliases = _frame_report_aliases(function, melee_root)
    source_text = None
    source_label = None
    source_path_for_probes: Path | None = None
    unit = None
    if source_file is not None:
        source_file = _resolve_existing_cli_file(
            source_file,
            melee_root=melee_root,
            label="source file",
        )
        source_text = source_file.read_text(encoding="utf-8", errors="replace")
        source_label = str(source_file)
        if _path_inside_repo(source_file, melee_root):
            source_path_for_probes = source_file
    else:
        unit = _find_unit_for_function(function, melee_root)
        if unit is not None:
            src_path = melee_root / "src" / f"{unit}.c"
            if src_path.exists():
                source_text = src_path.read_text(encoding="utf-8", errors="replace")
                source_path_for_probes = src_path
                try:
                    source_label = str(src_path.relative_to(melee_root))
                except ValueError:
                    source_label = str(src_path)
    if source_path_for_probes is None:
        unit_for_path = unit or _find_unit_for_function(function, melee_root)
        if unit_for_path is not None:
            candidate_source = melee_root / "src" / f"{unit_for_path}.c"
            if candidate_source.exists():
                source_path_for_probes = candidate_source

    source_context = _frame_source_context(
        source_aliases,
        melee_root=melee_root,
        source_file=source_file,
    )
    try:
        frame_report = analyze_frame_reservations(
            pcdump_text,
            function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
            **source_context,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    if source_file is not None and (compile_probes or candidates):
        pcdump_frame_report = frame_report
        try:
            staged_pcdump_text = compile_source_variant(
                DiffInput(
                    label="source-baseline",
                    token=str(source_file),
                    kind="source",
                    path=source_file,
                ),
                function=function,
                melee_root=melee_root,
                timeout=timeout,
            )
            staged_current_text = None
            if _pcdump_has_symbolic_stack_homes(staged_pcdump_text):
                staged_current_text = _read_frame_reservation_source_current_asm(
                    source_file,
                    function=function,
                    melee_root=melee_root,
                    timeout=timeout,
                )
            if (
                explicit_pcdump
                and staged_current_text is not None
                and _pcdump_has_symbolic_stack_homes(pcdump_text)
            ):
                pcdump_frame_report = analyze_frame_reservations(
                    pcdump_text,
                    function,
                    expected_asm_text=expected_text,
                    current_asm_text=staged_current_text,
                    **source_context,
                )
            staged_frame_report = analyze_frame_reservations(
                staged_pcdump_text,
                function,
                expected_asm_text=expected_text,
                current_asm_text=staged_current_text,
                **source_context,
            )
            staged_source_baseline = {
                "status": "compiled",
                "source": str(source_file),
                "current_asm_status": (
                    "available" if staged_current_text is not None else "pcdump-only"
                ),
            }
            baseline_consistency = _frame_transform_baseline_consistency(
                pcdump_frame_report=pcdump_frame_report,
                staged_frame_report=staged_frame_report,
                explicit_pcdump=explicit_pcdump,
                prefer_staged_source_baseline=prefer_staged_source_baseline,
            )
            if prefer_staged_source_baseline or not explicit_pcdump:
                frame_report = staged_frame_report
                staged_source_baseline["authoritative"] = True
            else:
                frame_report = pcdump_frame_report
                staged_source_baseline["authoritative"] = False
            frame_report["staged_source_baseline"] = staged_source_baseline
            frame_report["baseline_consistency"] = baseline_consistency
        except (CompileFailure, ValueError, OSError) as exc:
            frame_report["staged_source_baseline"] = {
                "status": "unavailable",
                "source": str(source_file),
                "error": str(exc),
            }

    probe_plan = _frame_transform_probe_plan(frame_report)
    outgoing_floor_bridge_active = (
        _frame_transform_needs_outgoing_floor_source_bridge(frame_report)
    )
    operator_filter = _resolve_frame_transform_operator_filter(
        probe_plan=probe_plan,
        operators=operators,
    )
    current_frame_size = (frame_report.get("current") or {}).get("frame_size")
    if not isinstance(current_frame_size, int):
        current_frame_size = None
    expected_frame_size = None
    expected_model = frame_report.get("expected")
    if isinstance(expected_model, Mapping):
        raw_expected_frame = expected_model.get("frame_size")
        if isinstance(raw_expected_frame, int):
            expected_frame_size = raw_expected_frame
    frame_reservation_delta = (
        expected_frame_size - current_frame_size
        if current_frame_size is not None
        and expected_frame_size is not None
        and current_frame_size != expected_frame_size
        else None
    )
    if frame_reservation_bytes is not None:
        if frame_reservation_bytes <= 0:
            typer.echo("--frame-reservation-bytes must be positive", err=True)
            raise typer.Exit(2)
        frame_reservation_delta = frame_reservation_bytes

    probes = []
    if source_text is not None:
        directed = generate_frame_directed_probes(
            source_text,
            function,
            current_frame=frame_report.get("current"),
            target_frame=frame_report.get("expected"),
            frame_reservation_delta=frame_reservation_delta,
            max_probes=max_probes,
        )
        allowed = frozenset(operator_filter)
        probes.extend(probe for probe in directed if probe.operator in allowed)
        if include_lifetime_fallback and len(probes) < max_probes:
            remaining = max_probes - len(probes)
            probes.extend(
                generate_lifetime_layout_probes(
                    source_text,
                    function,
                    max_probes=remaining,
                    operator_filter=operator_filter,
                )
            )
        probes = probes[:max_probes]
    if (
        source_file is not None
        and (include_transform_corpus or transform_family or outgoing_floor_bridge_active)
    ):
        unit = _find_unit_for_function(function, melee_root)
    outgoing_floor_bridge_budget = (
        min(8, max(1, max_probes)) if outgoing_floor_bridge_active else 0
    )
    outgoing_floor_bridge_before = len(probes)
    transform_include = include_transform_corpus
    transform_defaults = _FRAME_TRANSFORM_CORPUS_DEFAULT_FAMILIES
    transform_max_probes = max_probes
    if outgoing_floor_bridge_active and not transform_family:
        transform_include = True
        transform_defaults = _FRAME_TRANSFORM_OUTGOING_FLOOR_FAMILIES
        transform_max_probes = max(max_probes, len(probes) + outgoing_floor_bridge_budget)
    _append_transform_corpus_probes(
        probes,
        source_text=source_text,
        function=function,
        unit=unit,
        include=transform_include,
        families=transform_family,
        force_phys=transform_force_phys,
        max_probes=transform_max_probes,
        default_families=transform_defaults,
    )
    outgoing_floor_bridge = {
        "status": "active" if outgoing_floor_bridge_active else "not-triggered",
        "families": (
            list(transform_family or _FRAME_TRANSFORM_OUTGOING_FLOOR_FAMILIES)
            if outgoing_floor_bridge_active
            else []
        ),
        "requested_probe_budget": outgoing_floor_bridge_budget,
        "generated_probe_count": max(0, len(probes) - outgoing_floor_bridge_before),
    }

    semantic_scan_status: Mapping[str, Any] | None = None
    if (
        source_text is not None
        and frame_reservation_delta is not None
        and frame_reservation_delta < 0
        and "frame-local-dematerialize" in operator_filter
    ):
        _semantic_scan_probes, semantic_scan_status = (
            scan_frame_local_dematerialization_probes(source_text, function)
        )
    semantic_lever_status = _frame_transform_semantic_lever_status(
        source_text=source_text,
        operator_filter=operator_filter,
        frame_reservation_delta=frame_reservation_delta,
        probes=probes,
        scan_status=semantic_scan_status,
    )
    frame_report["semantic_lever_status"] = semantic_lever_status

    variants: list[dict[str, Any]] = []
    generated_source_dir, generated_probe_paths = (
        _materialize_frame_transform_probe_sources(
            probes,
            output_dir=output_dir,
            json_out=json_out,
        )
    )
    candidate_probe_by_label: dict[str, dict[str, Any]] = {}

    def _score_candidate(
        *,
        label: str,
        operator: str,
        path: Path,
        source_retained: Path | None = None,
        unit_source: Path | None = None,
        full_unit_source: bool = False,
    ) -> None:
        probe_payload = candidate_probe_by_label.get(label)
        try:
            if full_unit_source and unit_source is None:
                raise ValueError(
                    "full-unit transform probe requires a resolved unit source"
                )
            candidate_source_text: str | None = None
            if path.suffix == ".txt":
                candidate_text = path.read_text(encoding="utf-8", errors="replace")
            elif path.suffix == ".c":
                candidate_source_text, _ = (
                    _prevalidate_lifetime_layout_source_candidate(
                        path,
                        function=function,
                    )
                )
                try:
                    compile_kwargs = dict(
                        diff_input=DiffInput(
                            label=label,
                            token=str(path),
                            kind="source",
                            path=path,
                        ),
                        function=function,
                        melee_root=melee_root,
                        timeout=timeout,
                    )
                    if unit_source is not None:
                        compile_kwargs["unit_source"] = unit_source
                    candidate_text = compile_source_variant(**compile_kwargs)
                except CompileFailure as exc:
                    detail = str(exc)
                    if exc.returncode == 3 and "not found in pcdump" in detail:
                        raise _MalformedSourceCandidate(
                            (
                                f"{detail}; compiled probe pcdump omitted the "
                                f"target function. Source retained at {path}"
                            ),
                            source_hunk=_compact_source_hunk_for_function(
                                candidate_source_text,
                                function,
                            ),
                        ) from exc
                    raise
            else:
                raise ValueError(f"expected .txt pcdump or .c source, got {path}")

            real_score = _SourceCandidateRealScore(None, None)
            if score_match_percent and path.suffix == ".c":
                status = (
                    _make_real_score_status("frame-transform-search", label)
                    if not json_out
                    else None
                )
                score_kwargs = dict(
                    path=path,
                    function=function,
                    melee_root=melee_root,
                    timeout=timeout,
                    status=status,
                    include_stack_slot=False,
                )
                if full_unit_source:
                    score_kwargs["full_unit_source"] = True
                real_score = _score_source_candidate_real_tree(**score_kwargs)
            pcdump_path = None
            if path.suffix == ".c":
                pcdump_path = _write_retained_pcdump(path, candidate_text)
            elif path.suffix == ".txt":
                pcdump_path = str(path)
            frame_model = _frame_transform_variant_frame_model(
                candidate_text,
                function,
            )
            variant = _frame_transform_variant_from_model(
                label=label,
                operator=operator,
                path=path,
                frame_model=frame_model,
                current_frame_size=current_frame_size,
                expected_frame_size=expected_frame_size,
                match_percent=real_score.match_percent,
                match_percent_error=real_score.match_percent_error,
                source_retained=source_retained or (path if path.suffix == ".c" else None),
            )
            if pcdump_path is not None:
                variant["pcdump_path"] = pcdump_path
            if candidate_source_text is not None:
                source_hunks = _source_hunks_for_probe(
                    source_text,
                    candidate_source_text,
                    label,
                )
                if source_hunks:
                    variant["source_hunks"] = source_hunks
            checkdiff = _compact_checkdiff_payload(real_score.checkdiff_payload)
            if checkdiff is not None:
                variant["checkdiff"] = checkdiff
            _attach_frame_transform_probe_payload(variant, probe_payload)
            variants.append(variant)
        except Exception as exc:
            malformed_source = isinstance(exc, _MalformedSourceCandidate)
            failed = {
                "label": label,
                "operator": operator,
                "status": "malformed-source" if malformed_source else "failed",
                "path": str(path),
                "error": str(exc),
            }
            if source_retained is not None:
                failed["source_retained"] = str(source_retained)
            elif path.suffix == ".c" and path.exists():
                failed["source_retained"] = str(path)
                try:
                    source_hunks = _source_hunks_for_probe(
                        source_text,
                        path.read_text(encoding="utf-8", errors="replace"),
                        label,
                    )
                    if source_hunks:
                        failed["source_hunks"] = source_hunks
                except OSError:
                    pass
            if malformed_source and exc.source_hunk:
                failed["source_hunk"] = exc.source_hunk
            _attach_frame_transform_probe_payload(failed, probe_payload)
            variants.append(failed)

    for spec in candidates or []:
        label, operator, path = _parse_lifetime_layout_candidate(spec)
        _score_candidate(label=label, operator=operator, path=path)

    if compile_probes:
        if source_text is None and not candidates:
            typer.echo(
                "--compile-probes requires --source-file, repo source, or "
                "--candidate OPERATOR=path.",
                err=True,
            )
            raise typer.Exit(2)
        if probes:
            probe_dir = generated_source_dir
            if probe_dir is None:
                probe_dir = Path(tempfile.mkdtemp(prefix="melee_frame_transform_"))
                probe_dir.mkdir(parents=True, exist_ok=True)
                generated_source_dir = probe_dir
            start_idx = len(variants)
            try:
                for probe in probes:
                    path = generated_probe_paths.get(probe.label)
                    if path is None:
                        path = probe_dir / f"{probe.label}.c"
                        path.write_text(probe.source_text)
                        generated_probe_paths[probe.label] = path
                    candidate_probe_by_label[probe.label] = probe.to_dict()
                    full_unit_source = _probe_requires_full_unit_source(probe)
                    _score_candidate(
                        label=probe.label,
                        operator=probe.operator,
                        path=path,
                        source_retained=path,
                        unit_source=_full_unit_source_for_probe(
                            probe,
                            source_path_for_probes,
                        ),
                        full_unit_source=full_unit_source,
                    )
            finally:
                generated_failed = any(
                    variant["status"] != "ok" for variant in variants[start_idx:]
                )
                retain_generated = generated_failed or json_out or output_dir is not None
                if not retain_generated:
                    shutil.rmtree(probe_dir, ignore_errors=True)

    evaluation = evaluate_frame_transform_probe_results(frame_report, variants)
    ranked_variants = evaluation.get("variants")
    if not isinstance(ranked_variants, list):
        ranked_variants = variants
    elif not ranked_variants and variants:
        ranked_variants = variants
    stop_condition = evaluation.get("stop_condition")

    if json_out:
        probe_payloads: list[dict[str, Any]] = []
        source_hunks_by_candidate: dict[str, list[dict[str, object]]] = {}
        for probe in probes:
            source_hunks = _source_hunks_for_probe(
                source_text,
                probe.source_text,
                probe.label,
            )
            if source_hunks:
                source_hunks_by_candidate[probe.label] = source_hunks
            probe_payload = {
                **probe.to_dict(),
                **(
                    {"source_retained": str(generated_probe_paths[probe.label])}
                    if probe.label in generated_probe_paths
                    else {}
                ),
            }
            if source_hunks:
                probe_payload["source_hunks"] = source_hunks
            probe_payloads.append(probe_payload)
        for variant in ranked_variants:
            if not isinstance(variant, Mapping):
                continue
            label = variant.get("label")
            hunks = variant.get("source_hunks")
            if isinstance(label, str) and isinstance(hunks, list) and hunks:
                source_hunks_by_candidate[label] = hunks
        payload = {
            "function": function,
            "ranking": _FRAME_TRANSFORM_RANKING,
            "baseline_pcdump": str(pcdump_path),
            "source": source_label,
            "frame_report": frame_report,
            "probe_plan": probe_plan,
            "operator_filter": list(operator_filter),
            "outgoing_floor_bridge": outgoing_floor_bridge,
            "semantic_lever_status": semantic_lever_status,
            "generated_source_dir": (
                str(generated_source_dir) if generated_source_dir is not None else None
            ),
            "probes": probe_payloads,
            "variants": ranked_variants,
            "source_hunks_by_candidate": source_hunks_by_candidate,
            "frame_transform_probe_evaluation": evaluation,
            "terminal_summary": evaluation.get("terminal_summary"),
            "stop_condition": stop_condition,
        }
        print(json.dumps(payload, indent=2))
        return

    current_frame = (frame_report.get("current") or {}).get("frame_size")
    expected_frame = (
        (frame_report.get("expected") or {}).get("frame_size")
        if isinstance(frame_report.get("expected"), Mapping)
        else None
    )
    print(f"frame-transform-search - {function}")
    print(f"ranking: {_FRAME_TRANSFORM_RANKING}")
    print(f"baseline: frame={current_frame if current_frame is not None else '?'}")
    print(f"expected: frame={expected_frame if expected_frame is not None else '?'}")
    print("operator filter: " + ", ".join(operator_filter))
    if semantic_lever_status.get("status") not in {"not-needed"}:
        print(
            "semantic lever: "
            f"{semantic_lever_status.get('status')}"
            f" [{semantic_lever_status.get('operator')}]"
        )
    if generated_source_dir is not None:
        print(f"generated source dir: {generated_source_dir}")
    print(
        "verdict: "
        f"{evaluation.get('verdict')} ({(stop_condition or {}).get('kind')})"
    )
    if stop_condition:
        print(f"stop condition: {stop_condition.get('reason')}")
    if ranked_variants:
        print("Variants:")
        for variant in ranked_variants:
            if variant.get("status") == "ok":
                print(
                    f"{variant.get('rank', '?')}. {variant['label']} "
                    f"[{variant['operator']}] frame="
                    f"{variant.get('candidate_frame_size')} remaining_delta="
                    f"{variant.get('remaining_frame_delta')} improvement="
                    f"{variant.get('frame_delta_improvement')}"
                )
                if variant.get("match_percent") is not None:
                    print(f"  match_percent: {variant['match_percent']:.6g}")
                if variant.get("description"):
                    print(f"  action: {variant['description']}")
                if variant.get("source_retained"):
                    print(f"  source: {variant['source_retained']}")
            else:
                print(
                    f"- {variant['label']} [{variant['operator']}] failed: "
                    f"{variant.get('error')}"
                )
                if variant.get("source_retained"):
                    print(f"  source: {variant['source_retained']}")
    elif probes:
        print("Probes:")
        for probe in probes:
            print(f"- {probe.label} [{probe.operator}]: {probe.description}")
        print("Variants: none; pass --compile-probes or --candidate OPERATOR=path.")
    else:
        print("Variants: none; pass --source-file or --candidate OPERATOR=path.")


def _render_gate_rejected_distribution(
    result,
    target: tuple[int, ...],
    *,
    top_n: int = 5,
) -> None:
    """Print the gate-rejected diagnostic: prefix-length histogram + top-N.

    Diagnostic is the answer to "did permuter ever produce a candidate that
    moved simplify-order toward target, even if it also disturbed precolor?"
    Without scoring rejected candidates we can't tell — the gate strips them
    out and we'd only see the count. This renderer surfaces:

      1. Histogram of `common_prefix_length` across all rejected candidates.
         A bin at len(target) means "permuter CAN produce the exact target
         order, just with precolor changes" — strong signal to consider a
         distance-metric gate.
      2. Top-N rejected candidates by `common_prefix_length` desc, with
         observed prefix and the gate's rejection reason for each.

    Renders nothing when `result.rejected_scored` is empty.

    Kept as a standalone function (not inline in the CLI command body) so
    it can be unit-tested directly and so a parallel per-adapter breakdown
    can land alongside without merge conflict.
    """
    rejected = result.rejected_scored
    if not rejected:
        return

    print(f"Gate-rejected diagnostic (n={len(rejected)}):")

    # Histogram by common_prefix_length. Build a sorted list of all bins
    # that appear plus the target-length bin so we always render it (even
    # at 0) since it's the headline signal.
    target_len = len(target)
    bins: dict[int, int] = {}
    for rc in rejected:
        bins[rc.score.common_prefix_length] = (
            bins.get(rc.score.common_prefix_length, 0) + 1
        )
    bins.setdefault(target_len, 0)

    print("  Common-prefix length distribution:")
    # Max width for column alignment, computed from the bins we'll print.
    max_count = max(bins.values()) if bins else 0
    count_width = max(3, len(str(max_count)))
    for length in sorted(bins):
        count = bins[length]
        label = f"prefix={length}"
        marker = "  <- target length" if length == target_len else ""
        # Pad label to a stable column width so the counts line up.
        print(f"    {label:<12} {count:>{count_width}} candidates{marker}")

    # Top-N by common_prefix_length descending. Ties broken by provenance
    # so the order is deterministic for tests.
    print()
    sorted_rejected = sorted(
        rejected,
        key=lambda rc: (-rc.score.common_prefix_length, rc.provenance),
    )
    shown = sorted_rejected[:top_n]
    print(f"  Best {len(shown)} gate-rejected by simplify-order:")
    for rc in shown:
        s = rc.score
        observed = ",".join(str(x) for x in s.observed_prefix) or "(empty)"
        # Annotate with precolor distance so the reader can spot
        # candidates that almost-preserved-precolor at a glance — pairs
        # naturally with the rank-combined ranking, but is a free
        # improvement to the existing diagnostic too.
        distance = rc.precolor_distance.total
        print(
            f"    {rc.provenance}: prefix={s.common_prefix_length}/"
            f"{len(s.target_prefix)} (observed: {observed}) "
            f"(distance={distance})"
        )
        print(f"       rejected: {rc.rejection_reason}")
    print()


class RankMode(str, Enum):
    """Ranking mode for `debug mutate simplify-order`'s headline output.

    `lex` (default, calibration-free): sort by common_prefix_length DESC
    then total precolor distance ASC. Surfaces target-hitting candidates
    first regardless of disturbance magnitude — robust across functions,
    target lengths, and mutation libraries.

    `combined` (legacy, requires α tuning): sort by
    `prefix_ratio - alpha * distance`. Useful when the user wants a
    continuous trade-off and is willing to calibrate alpha to the
    campaign's distance distribution.
    """

    lex = "lex"
    combined = "combined"


def _unified_candidates(
    result,
) -> list[tuple[str, object, object, str | None]]:
    """Merge gate-passing and gate-rejected candidates into a single list.

    Returns tuples of (provenance, simplify_score, precolor_distance,
    rejection_reason_or_None). `None` reason marks a passing candidate;
    a non-None string marks a gate-rejected one.

    Shared by both the lex and combined renderers so they can never drift
    on which buckets they pull from. The two modes only differ in their
    sort key and per-row rendering.
    """
    rows: list[tuple[str, object, object, str | None]] = []
    for sv in result.progress:
        rows.append((
            sv.variant.provenance,
            sv.score,
            sv.precolor_distance,
            None,
        ))
    for rc in result.rejected_scored:
        rows.append((
            rc.provenance,
            rc.score,
            rc.precolor_distance,
            rc.rejection_reason,
        ))
    return rows


def _render_combined_score_ranking(
    result,
    target: tuple[int, ...],
    *,
    alpha: float,
    top_n: int = 8,
) -> None:
    """Print the unified combined-score ranking across passing + rejected.

    Builds the combined score per candidate on the fly (so the alpha can
    change at render time without re-running the search). Pulls candidates
    from BOTH `result.progress` and `result.rejected_scored` — that's the
    point of the unified ranking: when permuter produces a candidate that
    hits the target simplify order but disturbs precolor by 1 edge, it
    should beat a candidate that preserves precolor but stays at prefix=0.

    Renders nothing when there are no compiled candidates to rank.
    """
    from ...mwcc_debug.simplify_search import combined_value

    rows = _unified_candidates(result)
    if not rows:
        return

    # Score on the fly via the shared helper so the renderer and the
    # `combined_score` function can never drift in formula or alpha
    # semantics.
    scored: list[tuple[float, str, object, object, str | None]] = []
    for prov, s, dist, reason in rows:
        combined = combined_value(s, dist, target, alpha)
        scored.append((combined, prov, s, dist, reason))

    # Sort: combined DESC, ties broken deterministically by provenance.
    scored.sort(key=lambda r: (-r[0], r[1]))
    shown = scored[:top_n]

    print(f"Best by combined score (alpha={alpha}, top {len(shown)}):")
    for combined, prov, s, dist, reason in shown:
        observed = ",".join(str(x) for x in s.observed_prefix) or "(empty)"
        print(
            f"  {prov}: combined={combined:.3f}  "
            f"prefix={s.common_prefix_length}/{len(s.target_prefix)} "
            f"(observed: {observed})"
        )
        print(
            f"     precolor distance: "
            f"IG +{dist.ig_added}/-{dist.ig_removed}, "
            f"coalesce +{dist.coalesce_added}/-{dist.coalesce_removed}, "
            f"spills +{dist.spill_added}/-{dist.spill_removed} "
            f"(total={dist.total})"
        )
        if reason:
            print(f"     gate rejected: {reason}")
        else:
            print(f"     gate passed")
    print()


def _render_lex_ranking(
    result,
    target: tuple[int, ...],
    *,
    top_n: int = 8,
) -> None:
    """Print the unified lexicographic ranking across passing + rejected.

    Sort key: `common_prefix_length` DESC primary, total precolor distance
    ASC secondary, provenance ASC tertiary (for deterministic ties).

    This is the calibration-free successor to combined-score ranking. The
    combined formula `ratio - alpha * distance` depends on knowing the
    campaign's distance scale to pick alpha; lex sidesteps that entirely
    by expressing "inspect target-hitting candidates first, lowest-
    disturbance variants of those next" directly as a sort key. No knob
    to tune across functions, target lengths, or mutation libraries.

    Pulls from BOTH `result.progress` and `result.rejected_scored` — same
    unified-list contract as the combined renderer. Renders nothing when
    there are no compiled candidates.
    """
    rows = _unified_candidates(result)
    if not rows:
        return

    # Sort: prefix DESC, distance ASC, provenance ASC. The lex contract
    # is "more prefix is always better; for equal prefix, less precolor
    # disturbance is better."
    rows.sort(key=lambda r: (-r[1].common_prefix_length, r[2].total, r[0]))
    shown = rows[:top_n]

    print(f"Best by simplify-order then distance (top {len(shown)}):")
    for prov, s, dist, reason in shown:
        observed = ",".join(str(x) for x in s.observed_prefix) or "(empty)"
        print(
            f"  {prov}: prefix={s.common_prefix_length}/{len(s.target_prefix)} "
            f"distance={dist.total} (observed: {observed})"
        )
        print(
            f"     precolor distance: "
            f"IG +{dist.ig_added}/-{dist.ig_removed}, "
            f"coalesce +{dist.coalesce_added}/-{dist.coalesce_removed}, "
            f"spills +{dist.spill_added}/-{dist.spill_removed}"
        )
        if reason:
            print(f"     gate rejected: {reason}")
        else:
            print(f"     gate passed")
    print()


def _render_force_phys_ranking(
    result,
    target_phys: dict[int, int],
    *,
    top_n: int = 8,
) -> None:
    """Print the unified force-phys ranking across passing + rejected."""
    rows = _unified_candidates(result)
    if not rows:
        return

    rows.sort(key=lambda r: (-r[1].common_prefix_length, r[2].total, r[0]))
    shown = rows[:top_n]

    target_text = ", ".join(
        f"ig{ig}->r{phys}" for ig, phys in target_phys.items()
    )
    print(f"Best by force-phys target then distance (top {len(shown)}):")
    print(f"  target: {target_text}")
    for prov, s, dist, reason in shown:
        observed = ", ".join(
            f"ig{ig}->r{target_phys[ig]}" for ig in s.observed_prefix
        ) or "(none)"
        print(
            f"  {prov}: hits={s.common_prefix_length}/{len(s.target_prefix)} "
            f"distance={dist.total} (matched: {observed})"
        )
        print(
            f"     precolor distance: "
            f"IG +{dist.ig_added}/-{dist.ig_removed}, "
            f"coalesce +{dist.coalesce_added}/-{dist.coalesce_removed}, "
            f"spills +{dist.spill_added}/-{dist.spill_removed}"
        )
        if reason:
            print(f"     gate rejected: {reason}")
        else:
            print("     gate passed")
    print()


def _flush_stdout_report() -> None:
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# --triage post-search composition: real-tree match% ranking
# ---------------------------------------------------------------------------
#
# Layer A of the workflow integration described in
# docs/mwcc-debug-diff-roadmap.md. After the simplify-order search
# completes its harvest, optionally invoke `debug permute triage` on the
# permuter output dir to surface a second ranking by *actual* real-tree
# match% — the ground-truth metric. Closes the methodology gap exposed by
# the grVenom_80204284 campaign, where the manual survey ranked by
# simplify-order distance and missed output-180-1 (the real fix at 100%)
# because it lived below the inspection cutoff.
#
# Subprocess vs library call: the existing `debug permute triage` command
# is tightly coupled to typer/CLI internals (in-loop typer.echo, JSON-vs-
# text branching, apply_best side effects). Subprocess composition via its
# stable `--json` interface is the MVP-correct choice — it preserves the
# existing logic untouched, gives us a deterministic parsed result, and
# isolates triage failures from the main command's exit code. If the
# triage logic later needs to be reused in three+ places, refactor to a
# library function then; today, subprocess is the right tool.


@dataclasses.dataclass(frozen=True)
class _TriageResult:
    """Captured output of one `debug permute triage --json` invocation.

    `data` is the parsed JSON payload when the subprocess succeeded
    *and* produced valid JSON; `None` in every other case.

    `parse_error` distinguishes the two failure modes when `data is
    None`:

    - `None` means the subprocess itself failed (`returncode != 0`); the
      caller emits the "Triage subprocess failed" wording.
    - A non-`None` string means the subprocess returned exit 0 but its
      stdout wasn't parseable JSON; the caller emits a distinct
      "exited cleanly but produced unparseable JSON output" wording so
      the user isn't confused by "subprocess failed; exit code: 0".

    Without this split, both branches funnel into the same error message
    and the user can't tell whether the subprocess crashed or just
    produced garbage stdout (each has different remediation).
    """

    returncode: int
    stdout: str
    stderr: str
    data: Optional[dict]
    parse_error: Optional[str] = None


def _run_triage_subprocess(
    perm_dir: Path,
    function: str,
    melee_root: Path,
) -> _TriageResult:
    """Invoke `python -m src.cli debug permute triage <perm_dir> -f <fn> --json`.

    Returns a `_TriageResult` with the subprocess exit code, captured
    stdout/stderr, the parsed JSON payload (or None), and a
    `parse_error` string when the subprocess succeeded but stdout
    wasn't parseable JSON (see `_TriageResult` for why this is split
    from the generic "data is None" case).

    Isolated as its own function so tests can monkeypatch the subprocess
    invocation without intercepting `subprocess.run` globally — there are
    other subprocess calls in this file (ninja, objdiff-cli) that we don't
    want to fake.

    Cycle time: each triage candidate costs ~5-10s (ninja + report.json
    regen). A 200-candidate harvest is ~30 minutes; a 20-candidate harvest
    is ~3 minutes. The caller emits a progress message before invocation
    so the user knows what they're waiting on.
    """
    cli_root = Path(__file__).resolve().parent.parent.parent
    cmd = [
        sys.executable, "-m", "src.cli",
        "debug", "permute", "triage",
        str(perm_dir),
        "--function", function,
        "--json",
    ]
    proc = subprocess.run(
        cmd,
        cwd=cli_root,
        capture_output=True,
        text=True,
    )
    parsed: Optional[dict] = None
    parse_error: Optional[str] = None
    if proc.returncode == 0:
        try:
            parsed = json.loads(proc.stdout)
        except (ValueError, json.JSONDecodeError) as exc:
            # Subprocess succeeded but stdout wasn't JSON. Record the
            # parse error so the caller can emit the distinct
            # "unparseable JSON" wording rather than the misleading
            # "subprocess failed" wording.
            parse_error = str(exc)
            parsed = None
    return _TriageResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        data=parsed,
        parse_error=parse_error,
    )


def _render_triage_ranking(
    triage_data: dict,
    *,
    result,
    perm_dir: Path,
    top_n: int = 8,
    rank_mode: Optional["RankMode"] = None,
    combined_alpha: float = 0.001,
    target: tuple[int, ...] = (),
) -> None:
    """Print the 'Best by real-tree match%' section.

    Pulls candidates from `triage_data["results"]` (status='ok' only —
    build-failed and no-function rows have no match%), sorts by match%
    DESC, and renders the top N with provenance, match%, delta vs
    baseline, and the cross-ranking position of the same candidate in
    the simplify-order results above.

    The cross-ranking honors the user's `--rank-mode`:

    - `lex` (default): sort by lex key (`prefix DESC, distance ASC,
      provenance`), annotation label is `simplify-order rank #N`.
    - `combined`: sort by combined-score key (`combined DESC, provenance`),
      annotation label is `combined rank #N`.

    Mode-aware so the rank annotation points at the same table the user
    sees above. Without this, a user in combined mode would get a
    `simplify-order rank #N` annotation that disagrees with the
    "Best by combined score" table — confusing.

    `rank_mode=None` is treated as lex (backward-compatible default for
    callers that pre-date the rank-mode threading).

    If any candidate hit 100.00%, surface a *** FIX FOUND *** banner
    BEFORE the ranking section — the headline a campaign agent needs to
    see first.
    """
    # Late import to avoid a forward-reference loop with the RankMode
    # enum below this module's class-definition order.
    if rank_mode is None:
        rank_mode = RankMode.lex

    results = triage_data.get("results") or []
    baseline_pct = triage_data.get("baseline_pct") or 0.0

    # Drop non-ok rows (build-failed / no-function); we only rank
    # candidates that produced a usable real-tree match%.
    ok = [r for r in results if r.get("status") == "ok"
          and r.get("match_pct") is not None]

    if not ok:
        print("Triage: no candidates produced a usable real-tree match%.")
        if results:
            n_build_failed = sum(
                1 for r in results if r.get("status") == "build-failed"
            )
            n_no_fn = sum(
                1 for r in results if r.get("status") == "no-function"
            )
            print(f"  ({n_build_failed} build failed, {n_no_fn} missing function)")
        print()
        return

    # Sort by match% DESC; tiebreak by path so output is deterministic.
    ok_sorted = sorted(
        ok,
        key=lambda r: (-(r.get("match_pct") or 0.0), str(r.get("path") or "")),
    )

    # Build the cross-ranking lookup, keyed by output dir name. Sort key
    # matches whichever ranking table was rendered above so the
    # cross-references stay consistent. If a candidate isn't in the
    # simplify-order results (cross-source dedup, compile failure inside
    # search, etc.), report "n/a".
    from ...mwcc_debug.simplify_search import combined_value

    so_rank: dict[str, int] = {}
    so_rows = _unified_candidates(result)
    if rank_mode is RankMode.combined:
        # Same sort key as `_render_combined_score_ranking`:
        # (-combined_value, provenance ASC).
        so_rows_sorted = sorted(
            so_rows,
            key=lambda r: (-combined_value(r[1], r[2], target, combined_alpha),
                           r[0]),
        )
        rank_label = "combined rank"
    else:
        # Lex (default): same key as `_render_lex_ranking`.
        so_rows_sorted = sorted(
            so_rows,
            key=lambda r: (-r[1].common_prefix_length, r[2].total, r[0]),
        )
        rank_label = "simplify-order rank"
    for i, (prov, _s, _d, _r) in enumerate(so_rows_sorted, 1):
        # Provenance for permuter rows looks like
        # "permuter output-NNNN-N/source.c"; extract the output dir name.
        if prov.startswith("permuter "):
            out_name = prov[len("permuter "):].split("/", 1)[0]
            so_rank[out_name] = i

    # Headline: if any candidate is 100%, lead with the FIX FOUND banner
    # so a skimming reader can't miss it. Threshold uses the same
    # float-precision epsilon as the existing triage WIN check.
    EPS = 1e-9
    top_candidate = ok_sorted[0]
    top_pct = top_candidate.get("match_pct") or 0.0
    if top_pct >= 100.00 - EPS:
        top_path = Path(str(top_candidate.get("path") or ""))
        top_dir = top_path.parent.name
        print("=" * 70)
        print("*** FIX FOUND ***")
        print(f"permuter {top_dir} produces {top_pct:.2f}% match "
              f"(baseline {baseline_pct:.2f}%).")
        print(f"Apply with: cp {top_path} <real-source-path>")
        print(f"            (or use `debug permute verify --apply` to stage it)")
        print("=" * 70)
        print()

    shown = ok_sorted[:top_n]
    print(f"Best by real-tree match% "
          f"(top {len(shown)}, baseline {baseline_pct:.2f}%):")
    for i, r in enumerate(shown, 1):
        path = Path(str(r.get("path") or ""))
        out_dir = path.parent.name
        pct = r.get("match_pct") or 0.0
        delta = r.get("delta") or 0.0
        so_pos = so_rank.get(out_dir)
        so_pos_str = (
            f"{rank_label} #{so_pos}" if so_pos is not None
            else f"{rank_label} n/a"
        )
        print(f"  {i}. permuter {out_dir}: {pct:.2f}%  "
              f"(delta {delta:+.2f}%, {so_pos_str})")
    print()


def _maybe_run_triage(
    *,
    triage_enabled: bool,
    with_permuter: bool,
    permuter_dir_resolved: Optional[Path],
    function: str,
    melee_root: Path,
    result,
    rank_mode: Optional["RankMode"] = None,
    combined_alpha: float = 0.001,
    target: tuple[int, ...] = (),
) -> None:
    """Compose `debug permute triage` after the simplify-order search.

    Encapsulates the four prerequisite checks (triage flag set,
    --with-permuter set, permuter dir resolved & non-empty, search
    completed) plus error capture and section rendering. Called from the
    CLI command body after all the existing rendering, before its early
    exits.

    `rank_mode` / `combined_alpha` / `target` are threaded through to
    `_render_triage_ranking` so the triage section's cross-rank
    annotation references the same ordering as the headline ranking
    table the user already saw above. Defaults preserve the original
    lex-mode behavior for any test or future caller that doesn't supply
    the mode explicitly.

    Designed so failures here never crash the parent command — the
    simplify-order rankings already rendered are still useful even when
    triage is unavailable.
    """
    if not triage_enabled:
        return

    if not with_permuter:
        typer.echo(
            "--triage requires permuter candidates; "
            "pass --with-permuter to enable. Skipping triage.",
            err=True,
        )
        return

    if permuter_dir_resolved is None or not permuter_dir_resolved.is_dir():
        # The --with-permuter branch above already printed an explanation
        # for why the permuter dir wasn't usable; just record that triage
        # is skipped without re-explaining.
        typer.echo(
            "--triage: no permuter dir available; nothing to triage.",
            err=True,
        )
        return

    # Count candidates before invoking the subprocess so we can emit an
    # accurate progress estimate and skip cleanly when the harvest is empty.
    # Guards against OSError (permissions, racey reads) — the triage
    # subprocess would error out anyway, but a clean early-skip is friendlier.
    try:
        candidate_count = sum(
            1 for d in permuter_dir_resolved.iterdir()
            if d.is_dir() and (d / "source.c").exists()
        )
    except OSError as exc:
        typer.echo(
            f"--triage: could not enumerate {permuter_dir_resolved} ({exc}); "
            f"skipping triage.",
            err=True,
        )
        return
    if candidate_count == 0:
        typer.echo(
            f"--triage: no candidate sources in {permuter_dir_resolved}; "
            f"nothing to triage.",
            err=True,
        )
        return

    print("=" * 70)
    print(f"Running triage on {candidate_count} candidate(s); this may "
          f"take a few minutes...")
    print("=" * 70)
    print()

    from src.cli.debug import _run_triage_subprocess
    triage = _run_triage_subprocess(
        permuter_dir_resolved, function, melee_root,
    )

    reproducer = (
        f"  reproduce: python -m src.cli debug permute triage "
        f"{permuter_dir_resolved} --function {function} --json"
    )

    if triage.data is None and triage.returncode == 0:
        # Subprocess exited cleanly but stdout wasn't parseable JSON
        # (`_run_triage_subprocess` sets `parse_error` in this case, but
        # we dispatch on `returncode == 0` for robustness against
        # external stubbing). Distinct from a subprocess failure — the
        # remediation is different (look at what the subprocess printed,
        # not its exit handling).
        print("Triage subprocess exited cleanly but produced unparseable "
              "JSON output; main report above is unaffected.")
        print(f"  exit code: {triage.returncode}")
        if triage.parse_error:
            print(f"  parse error: {triage.parse_error}")
        # Show a snippet of the stdout so the user can see what came out.
        # 200 chars is enough to recognize an error message / banner /
        # ANSI escape sequence without flooding the report.
        snippet = triage.stdout[:200].replace("\n", "\\n")
        more = "..." if len(triage.stdout) > 200 else ""
        print(f"  stdout (first 200 chars): {snippet}{more}")
        print(reproducer)
        print()
        return

    if triage.data is None:
        # Subprocess failed (non-zero exit). Surface what went wrong so
        # the user has a chance to debug, but don't crash — the main
        # report above is still useful.
        print("Triage subprocess failed; main report above is unaffected.")
        print(f"  exit code: {triage.returncode}")
        if triage.stderr.strip():
            # Cap stderr output to keep the report readable; reproducing
            # the full failure is what the exit code + reproducer command
            # is for.
            stderr_lines = triage.stderr.strip().splitlines()
            print("  stderr (first 5 lines):")
            for line in stderr_lines[:5]:
                print(f"    {line}")
        print(reproducer)
        print()
        return

    _render_triage_ranking(
        triage.data,
        result=result,
        perm_dir=permuter_dir_resolved,
        rank_mode=rank_mode,
        combined_alpha=combined_alpha,
        target=target,
    )


def _simplify_probe_filename(rank: int, provenance: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", provenance).strip(".-").lower()
    if not safe:
        safe = "probe"
    return f"rank-{rank:03d}-{safe[:80]}.c"


def _simplify_force_phys_target_score(signature, force_phys: Mapping[int, int]) -> dict:
    assigned = dict(signature.assigned_regs)
    virtuals: dict[str, dict[str, object]] = {}
    hits = 0
    for ig_idx, expected in sorted(force_phys.items()):
        actual = assigned.get(ig_idx)
        hit = actual == expected
        distance = abs(actual - expected) if actual is not None else None
        if hit:
            hits += 1
        virtuals[str(ig_idx)] = {
            "expected": expected,
            "actual": actual,
            "hit": hit,
            "matched": hit,
            "distance": distance,
        }
    return {
        "virtuals": virtuals,
        "hits": hits,
        "targeted": len(force_phys),
        "distance_total": (
            sum(
                int(virtual["distance"])
                for virtual in virtuals.values()
                if virtual["distance"] is not None
            )
            if all(virtual["distance"] is not None for virtual in virtuals.values())
            else None
        ),
    }


def _simplify_ranked_scored_candidates(result) -> list:
    return sorted(
        list(getattr(result, "scored_candidates", ()) or ()),
        key=lambda scored: (
            -scored.score.common_prefix_length,
            (
                scored.score.assignment_distance_total
                if scored.score.assignment_distance_total is not None
                else 1_000_000
            ),
            scored.precolor_distance.total,
            scored.variant.provenance,
        ),
    )


def _simplify_residual_force_phys_progressed(
    *,
    probe: Mapping[str, object],
    baseline_target_score: Mapping[str, object],
    residual_force_phys_target: Mapping[int, int],
) -> bool:
    probe_score = probe.get("target_score")
    if not isinstance(probe_score, Mapping):
        return False
    probe_virtuals = probe_score.get("virtuals")
    baseline_virtuals = baseline_target_score.get("virtuals")
    if not isinstance(probe_virtuals, Mapping) or not isinstance(baseline_virtuals, Mapping):
        return False
    for ig in residual_force_phys_target:
        key = str(ig)
        probe_virtual = probe_virtuals.get(key)
        baseline_virtual = baseline_virtuals.get(key)
        if not isinstance(probe_virtual, Mapping) or not isinstance(baseline_virtual, Mapping):
            continue
        if probe_virtual.get("hit") is True or probe_virtual.get("matched") is True:
            return True
        probe_distance = probe_virtual.get("distance")
        baseline_distance = baseline_virtual.get("distance")
        if (
            isinstance(probe_distance, int)
            and isinstance(baseline_distance, int)
            and probe_distance < baseline_distance
        ):
            return True
    return False


class _SimplifyRetainInterrupted(Exception):
    def __init__(
        self,
        *,
        records: list[dict[str, object]],
        last_candidate: str | None,
        abort_reason: str = "keyboard-interrupt",
    ) -> None:
        super().__init__(abort_reason)
        self.records = records
        self.last_candidate = last_candidate
        self.abort_reason = abort_reason


def _simplify_retained_probe_records(
    *,
    result,
    function: str,
    force_phys_target: Mapping[int, int],
    retain_probes: Path | None,
    melee_root: Path,
    retain_count: int,
    checkdiff_guard: bool,
    timeout: float | None,
) -> list[dict[str, object]]:
    from src.cli.debug import (
        _compact_source_hunk_for_function,
        _score_source_candidate_real_tree,
    )
    if retain_probes is not None:
        retain_dir = retain_probes if retain_probes.is_absolute() else melee_root / retain_probes
        retain_dir.mkdir(parents=True, exist_ok=True)
    else:
        retain_dir = None

    records: list[dict[str, object]] = []
    active_provenance: str | None = None
    try:
        for rank, scored in enumerate(
            _simplify_ranked_scored_candidates(result)[: max(0, retain_count)],
            1,
        ):
            active_provenance = scored.variant.provenance
            source_retained: str | None = None
            structural_guard = None
            structural_guard_error = None
            terminal_blocker = None
            if retain_dir is not None:
                probe_path = retain_dir / _simplify_probe_filename(
                    rank,
                    scored.variant.provenance,
                )
                probe_path.write_text(scored.variant.text, encoding="utf-8")
                source_retained = str(probe_path)
                if checkdiff_guard:
                    real_score = _score_source_candidate_real_tree(
                        probe_path,
                        function=function,
                        melee_root=melee_root,
                        timeout=timeout,
                        include_structural_guard=True,
                        full_unit_source=True,
                    )
                    structural_guard = real_score.structural_guard
                    structural_guard_error = (
                        real_score.structural_guard_error
                        or real_score.match_percent_error
                    )
                    if structural_guard_error:
                        terminal_blocker = structural_guard_error
                    elif (
                        isinstance(structural_guard, dict)
                        and not structural_guard.get("accepted", False)
                    ):
                        terminal_blocker = structural_guard.get("rejection_reason")

            target_score = (
                _simplify_force_phys_target_score(scored.signature, force_phys_target)
                if force_phys_target
                else {
                    "target_prefix": list(scored.score.target_prefix),
                    "observed_prefix": list(scored.score.observed_prefix),
                    "hits": scored.score.common_prefix_length,
                    "targeted": len(scored.score.target_prefix),
                }
            )
            records.append({
                "rank": rank,
                "provenance": scored.variant.provenance,
                "source_retained": source_retained,
                "source_hunk": _compact_source_hunk_for_function(
                    scored.variant.text,
                    function,
                ),
                "target_score": target_score,
                "force_phys_hits": scored.score.common_prefix_length,
                "baseline_force_phys_hits": scored.score.baseline_common_prefix_length,
                "force_phys_distance_total": scored.score.assignment_distance_total,
                "baseline_force_phys_distance_total": (
                    scored.score.baseline_assignment_distance_total
                ),
                "force_phys_assignment_improved_count": (
                    scored.score.assignment_improved_count
                ),
                "precolor_distance": dataclasses.asdict(scored.precolor_distance),
                "structural_guard": structural_guard,
                "structural_guard_error": structural_guard_error,
                "terminal_blocker": terminal_blocker,
            })
    except KeyboardInterrupt as exc:
        raise _SimplifyRetainInterrupted(
            records=records,
            last_candidate=active_provenance,
        ) from exc
    return records



@mutate_app.command(name="simplify-order")
def mutate_simplify_order_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--fn", "--function", "-f",
            help="Function to search.",
        ),
    ],
    want_first: Annotated[
        Optional[str],
        typer.Option(
            "--want-first",
            help="Comma-separated target ig_idx sequence to land at the "
                 "head of simplify order (e.g. '42,32'). Mutually exclusive "
                 "with --want-late.",
        ),
    ] = None,
    want_late: Annotated[
        Optional[str],
        typer.Option(
            "--want-late",
            help="Comma-separated target ig_idx sequence to land at the "
                 "TAIL of simplify order (e.g. '46,44'). Mutually exclusive "
                 "with --want-first. Use when the target nodes must be "
                 "simplified last.",
        ),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option(
            "--class",
            help="Register class to target. 0 = GPR (default).",
        ),
    ] = 0,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help="Score variants by force-phys assignment hits instead of "
                 "simplify-order proximity. Accepts IG:PHYS or CLASS:IG:PHYS "
                 "pairs, e.g. '53:4' or '0:53:4'. Mutually exclusive with "
                 "--want-first/--want-late.",
        ),
    ] = None,
    protect_force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--protect-force-phys",
            help=(
                "Force-phys assignments that must remain satisfied while "
                "searching residual targets. Defaults to --force-phys entries "
                "already satisfied by the retained/current baseline."
            ),
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "Retained full-TU source to mutate instead of the repo source. "
                "Requires --pcdump so the retained allocator state is the baseline."
            ),
        ),
    ] = None,
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Retained baseline pcdump for --source-file mode.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json/--no-json", help="Emit machine-readable search output."),
    ] = False,
    retain_probes: Annotated[
        Optional[Path],
        typer.Option(
            "--retain-probes",
            help="Directory where ranked retained candidate .c probes are written.",
        ),
    ] = None,
    retain_count: Annotated[
        int,
        typer.Option(
            "--retain-count",
            help="Maximum ranked probes to write/include in JSON.",
        ),
    ] = 5,
    checkdiff_guard: Annotated[
        bool,
        typer.Option(
            "--checkdiff-guard/--no-checkdiff-guard",
            help="Include checkdiff structural guard metrics for retained probes.",
        ),
    ] = False,
    preserve_precolor: Annotated[
        bool,
        typer.Option(
            "--preserve-precolor/--no-preserve-precolor",
            help="Reject variants that disturb the pre-coloring shape "
                 "(interference graph, coalesce mappings, spill set). "
                 "On by default.",
        ),
    ] = True,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Cap on variant compilation count.",
        ),
    ] = 100,
    skip_first_candidates: Annotated[
        int,
        typer.Option(
            "--skip-first-candidates",
            help=(
                "Skip the first N unique simplify-order candidates after "
                "dedupe. Use the previous JSON summary compiled/stream "
                "position to resume a long retained run."
            ),
        ),
    ] = 0,
    skip_provenance: Annotated[
        Optional[list[str]],
        typer.Option(
            "--skip-provenance",
            help="Exact candidate provenance to skip. Can be passed multiple times.",
        ),
    ] = None,
    skip_family: Annotated[
        Optional[list[str]],
        typer.Option(
            "--skip-family",
            help=(
                "Candidate provenance prefix to skip, e.g. 'type-change '. "
                "Can be passed multiple times."
            ),
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout", "-t",
            help="Per-compile timeout in seconds.",
        ),
    ] = 60,
    with_permuter: Annotated[
        bool,
        typer.Option(
            "--with-permuter",
            help="Also harvest pre-existing decomp-permuter output dirs "
                 "(<perm_root>/nonmatchings/<fn>/output-*/source.c). The "
                 "user runs permuter separately; this flag just adds the "
                 "permuter outputs to the variant stream. If no permuter "
                 "output is found a one-line hint is printed and the "
                 "search continues with the other adapters.",
        ),
    ] = False,
    permuter_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--permuter-dir",
            help="Override path resolution for --with-permuter. Defaults "
                 "to <perm_root>/nonmatchings/<fn>/ via MELEE_PERMUTER_ROOT "
                 "or ~/code/decomp-permuter.",
        ),
    ] = None,
    rank_mode: Annotated[
        RankMode,
        typer.Option(
            "--rank-mode",
            help="Ranking mode for the headline output. 'lex' (default, "
                 "calibration-free): sort all compiled candidates by "
                 "common_prefix_length DESC then total precolor distance "
                 "ASC. 'combined': sort by `prefix_ratio - alpha * distance` "
                 "(see --combined-alpha). Both pull from gate-passing AND "
                 "gate-rejected candidates uniformly; --preserve-precolor "
                 "still controls the binary gate.",
        ),
    ] = RankMode.lex,
    rank_combined: Annotated[
        bool,
        typer.Option(
            "--rank-combined/--no-rank-combined",
            help="Deprecated alias for --rank-mode combined. Kept for "
                 "backward compatibility with existing campaign scripts; "
                 "prefer --rank-mode combined in new code.",
        ),
    ] = False,
    combined_alpha: Annotated[
        float,
        typer.Option(
            "--combined-alpha",
            help="Weight on precolor distance in the combined score "
                 "(combined = prefix_ratio - alpha * distance). Higher alpha "
                 "punishes disturbance more. Only meaningful with "
                 "--rank-mode combined; ignored under lex. Default 0.001, "
                 "calibrated against observed permuter distance ranges "
                 "(100-300+) so prefix=N candidates outrank prefix=(N-1) "
                 "regardless of distance.",
        ),
    ] = 0.001,
    triage: Annotated[
        bool,
        typer.Option(
            "--triage/--no-triage",
            help="After the simplify-order harvest completes, invoke "
                 "`debug permute triage` on the permuter output dir and "
                 "append a second ranking by real-tree match% (the ground "
                 "truth). Requires --with-permuter. Closes the methodology "
                 "gap from the grVenom_80204284 campaign — where the actual "
                 "fix lived at output-180-1 but was buried below the "
                 "manual-inspection cutoff because the survey ranked by "
                 "simplify-order distance (a search-side proxy) instead of "
                 "match% (the ground-truth metric). If a 100% candidate is "
                 "found, the report surfaces a *** FIX FOUND *** banner so "
                 "future campaign agents can't miss it. Adds ~5-10s per "
                 "candidate to the run.",
        ),
    ] = False,
) -> None:
    """Search for source variants that produce a desired simplify order.

    Useful for stuck functions where the RA-input breakdown shows that
    simplify order is the only diverging input component. The search
    iterates variants from the existing source-mutation primitives
    (decl-orders, insert-alias, holder-lifetime, type-change), gates them on the
    preserve-precolor invariant, and ranks survivors by how much of the
    target prefix they reproduce.

    With ``--with-permuter``, pre-existing decomp-permuter output dirs
    are also harvested (no permuter is launched — run permuter
    separately first).

    Example:

      melee-agent debug mutate simplify-order \\
          --fn grVenom_80204284 --want-first '42,32'
    """
    from src.cli.debug import (
        _find_unit_for_function,
        _flush_stdout_report,
        DEFAULT_MELEE_ROOT,
        parse_hook_events,
    )
    from ...mwcc_debug.diff_capture import CompileFailure
    from ...mwcc_debug.simplify_search import (
        FunctionContext,
        baseline_signature,
        search,
    )
    from ...mwcc_debug.simplify_variants import (
        decl_orders_source,
        holder_lifetime_source,
        insert_alias_source,
        type_change_source,
    )
    from ...mwcc_debug.simplify_variants_permuter import (
        permuter_source,
        resolve_permuter_function_dir,
    )

    melee_root = DEFAULT_MELEE_ROOT
    emit = print if not json_out else (lambda *args, **kwargs: None)
    retained_mode = source_file is not None or pcdump is not None
    if retained_mode and (source_file is None or pcdump is None):
        typer.echo("--pcdump is required with --source-file retained mode", err=True)
        raise typer.Exit(2)
    if retain_count < 0:
        typer.echo("--retain-count must be non-negative", err=True)
        raise typer.Exit(2)
    if skip_first_candidates < 0:
        typer.echo("--skip-first-candidates must be non-negative", err=True)
        raise typer.Exit(2)
    skip_provenance_values = list(skip_provenance or [])
    skip_family_values = list(skip_family or [])

    # Mutual exclusion and at-least-one validation for objective selectors.
    if want_first is not None and want_late is not None:
        typer.echo(
            "error: --want-first and --want-late are mutually exclusive",
            err=True,
        )
        raise typer.Exit(2)
    objective_count = sum(
        option is not None for option in (want_first, want_late, force_phys)
    )
    if objective_count == 0:
        typer.echo(
            "error: must specify exactly one of --want-first, --want-late, "
            "or --force-phys",
            err=True,
        )
        raise typer.Exit(2)
    if objective_count > 1:
        typer.echo(
            "error: --want-first, --want-late, and --force-phys are "
            "mutually exclusive",
            err=True,
        )
        raise typer.Exit(2)

    # Parse the chosen flag into target / target_late tuples.
    target: tuple[int, ...] = ()
    target_late: tuple[int, ...] = ()
    force_phys_target: dict[int, int] = {}
    explicit_protected_force_phys: dict[int, int] = {}
    force_phys_normalized: Optional[str] = None
    protect_force_phys_normalized: Optional[str] = None

    if want_first is not None:
        raw = want_first.strip()
        if not raw:
            typer.echo("--want-first cannot be empty", err=True)
            raise typer.Exit(2)
        try:
            target = tuple(int(x.strip()) for x in raw.split(",") if x.strip())
        except ValueError:
            typer.echo(
                f"--want-first expects comma-separated integers; got {want_first!r}",
                err=True,
            )
            raise typer.Exit(2)
        if not target:
            typer.echo("--want-first parsed to an empty sequence", err=True)
            raise typer.Exit(2)

    if want_late is not None:
        raw_late = want_late.strip()
        if not raw_late:
            typer.echo("--want-late cannot be empty", err=True)
            raise typer.Exit(2)
        try:
            target_late = tuple(
                int(x.strip()) for x in raw_late.split(",") if x.strip()
            )
        except ValueError:
            typer.echo(
                f"--want-late expects comma-separated integers; got {want_late!r}",
                err=True,
            )
            raise typer.Exit(2)
        if not target_late:
            typer.echo("--want-late parsed to an empty sequence", err=True)
            raise typer.Exit(2)

    if force_phys is not None:
        try:
            entries, force_phys_normalized, _warnings = (
                _parse_diagnose_force_phys(force_phys)
            )
        except typer.BadParameter as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc
        force_phys_target = {
            entry.virtual: entry.phys
            for entry in entries
            if (class_id if entry.class_id is None else entry.class_id) == class_id
        }
        if not force_phys_target:
            available = ", ".join(
                str(class_id if entry.class_id is None else entry.class_id)
                for entry in entries
            )
            typer.echo(
                f"error: --force-phys has no entries for class {class_id} "
                f"(entry classes: {available})",
                err=True,
            )
            raise typer.Exit(2)
    if protect_force_phys is not None:
        if force_phys is None:
            typer.echo(
                "error: --protect-force-phys requires --force-phys",
                err=True,
            )
            raise typer.Exit(2)
        try:
            protected_entries, protect_force_phys_normalized, _warnings = (
                _parse_diagnose_force_phys(protect_force_phys)
            )
        except typer.BadParameter as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc
        explicit_protected_force_phys = {
            entry.virtual: entry.phys
            for entry in protected_entries
            if (class_id if entry.class_id is None else entry.class_id) == class_id
        }
        if not explicit_protected_force_phys:
            typer.echo(
                f"error: --protect-force-phys has no entries for class {class_id}",
                err=True,
            )
            raise typer.Exit(2)

    # Resolve the unit + source for the function.
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    source_path = melee_root / "src" / f"{unit}.c"
    if not source_path.exists():
        typer.echo(f"source not found: {source_path}", err=True)
        raise typer.Exit(2)

    from ...mwcc_debug.diff_capture import (
        DiffInput,
        compile_source_variant,
        function_pcdump_aliases,
    )

    pcdump_aliases = function_pcdump_aliases(function, melee_root)
    retained_source_path: Path | None = None
    retained_pcdump_path: Path | None = None
    if retained_mode:
        assert source_file is not None
        assert pcdump is not None
        retained_source_path = source_file.expanduser()
        if not retained_source_path.is_absolute():
            retained_source_path = (Path.cwd() / retained_source_path).resolve()
        if not retained_source_path.is_file():
            raise typer.BadParameter(f"source file not found: {retained_source_path}")
        retained_source_text = retained_source_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        if find_source_function(retained_source_text, function) is None:
            typer.echo(
                f"source file does not contain function {function!r}: "
                f"{retained_source_path}",
                err=True,
            )
            raise typer.Exit(2)
        retained_pcdump_path = pcdump.expanduser()
        if not retained_pcdump_path.is_absolute():
            retained_pcdump_path = (Path.cwd() / retained_pcdump_path).resolve()
        if not retained_pcdump_path.is_file():
            raise typer.BadParameter(f"pcdump not found: {retained_pcdump_path}")
        baseline_pcdump = retained_pcdump_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        ctx_source_path = retained_source_path
        compile_unit_source: Path | None = source_path
    else:
        ctx_source_path = source_path
        compile_unit_source = None
        diff_input = DiffInput(
            label="baseline",
            token=str(source_path),
            kind="source",
            path=source_path,
        )
        try:
            baseline_pcdump = compile_source_variant(
                diff_input,
                function=function,
                melee_root=melee_root,
                timeout=timeout,
            )
        except CompileFailure as exc:
            typer.echo(f"baseline compile failed:\n{exc}", err=True)
            raise typer.Exit(3)

    ctx = FunctionContext(
        function=function,
        unit=unit,
        source_path=ctx_source_path,
        melee_root=melee_root,
        pcdump_function_aliases=pcdump_aliases,
        compile_unit_source=compile_unit_source,
    )

    baseline_events = parse_hook_events(baseline_pcdump)
    baseline_lookup_names = (function, *ctx.pcdump_function_aliases)
    base_for_fn = next(
        (e for e in baseline_events if e.name in baseline_lookup_names),
        None,
    )
    if base_for_fn is None:
        tried = ", ".join(baseline_lookup_names)
        typer.echo(
            f"baseline pcdump has no events for {function}; "
            f"tried: {tried}; is the function actually compiled into this TU?",
            err=True,
        )
        raise typer.Exit(3)

    # Validate --class against what the function actually exercises. Union
    # of all sections so we surface classes that appear in any of
    # colorgraph / simplify / coalesce (some classes show up in coalesce
    # but not colorgraph if everything coalesced cleanly).
    available_classes = sorted({
        s.class_id for s in base_for_fn.colorgraph_sections
    } | {
        s.class_id for s in base_for_fn.simplify_sections
    } | {
        s.class_id for s in base_for_fn.coalesce_sections
    })
    if available_classes and class_id not in available_classes:
        ids = ", ".join(str(c) for c in available_classes)
        typer.echo(
            f"class {class_id} not present in {function}; "
            f"available class IDs: {ids}",
            err=True,
        )
        raise typer.Exit(3)

    baseline_sig = baseline_signature(base_for_fn, class_id=class_id)
    baseline_target_score = (
        _simplify_force_phys_target_score(baseline_sig, force_phys_target)
        if force_phys_target
        else None
    )
    baseline_assigned = dict(baseline_sig.assigned_regs)
    if explicit_protected_force_phys:
        protected_force_phys_target = dict(explicit_protected_force_phys)
    else:
        protected_force_phys_target = {
            ig_idx: phys
            for ig_idx, phys in force_phys_target.items()
            if baseline_assigned.get(ig_idx) == phys
        }
    residual_force_phys_target = {
        ig_idx: phys
        for ig_idx, phys in force_phys_target.items()
        if protected_force_phys_target.get(ig_idx) != phys
    }
    protected_mismatches = {
        ig_idx: {
            "expected": phys,
            "actual": baseline_assigned.get(ig_idx),
        }
        for ig_idx, phys in protected_force_phys_target.items()
        if baseline_assigned.get(ig_idx) != phys
    }
    if protected_mismatches:
        typer.echo(
            "retained baseline does not satisfy protected force-phys entries: "
            + json.dumps(protected_mismatches, sort_keys=True),
            err=True,
        )
        raise typer.Exit(3)

    if not baseline_sig.simplify_order and not force_phys_target:
        typer.echo(
            f"baseline has no simplify-graph entries for class {class_id}; "
            "the function may not exercise that register class.",
            err=True,
        )
        raise typer.Exit(3)

    emit(f"Function:        {function}")
    emit(f"Source:          {ctx_source_path}")
    if retained_mode:
        emit(f"Compile unit:    {source_path}")
        emit(f"Baseline pcdump: {retained_pcdump_path}")
    emit(f"Class:           {class_id}")
    if force_phys_target:
        target_force_text = ",".join(
            f"{ig}:r{phys}" for ig, phys in force_phys_target.items()
        )
        emit(f"Target force-phys: {target_force_text}")
        if force_phys_normalized is not None:
            emit(f"Force-phys arg:  {force_phys_normalized}")
        if protected_force_phys_target:
            protected_text = ",".join(
                f"{ig}:r{phys}"
                for ig, phys in sorted(protected_force_phys_target.items())
            )
            emit(f"Protected force-phys: {protected_text}")
        if residual_force_phys_target:
            residual_text = ",".join(
                f"{ig}:r{phys}"
                for ig, phys in sorted(residual_force_phys_target.items())
            )
            emit(f"Residual force-phys:  {residual_text}")
        if protect_force_phys_normalized is not None:
            emit(f"Protect arg:     {protect_force_phys_normalized}")
    elif target_late:
        emit(f"Target suffix:   {','.join(str(x) for x in target_late)}")
    else:
        emit(f"Target prefix:   {','.join(str(x) for x in target)}")
    emit(f"Baseline order:  "
         f"{','.join(str(x) for x in baseline_sig.simplify_order[:8])}"
         f"{'...' if len(baseline_sig.simplify_order) > 8 else ''}")
    emit(f"Preserve gate:   {'on' if preserve_precolor else 'off'}")
    emit(f"Max candidates:  {max_candidates}")

    sources: list = [
        decl_orders_source,
        insert_alias_source,
        holder_lifetime_source,
        type_change_source,
    ]
    # Track the resolved permuter dir at function scope so the post-search
    # --triage composition can reuse the same path the search adapters
    # consumed — no risk of the two paths diverging.
    resolved_permuter_dir: Optional[Path] = None
    if with_permuter:
        # Resolve the permuter dir up front so we can warn (once) if it
        # doesn't exist. The adapter itself silently yields nothing on a
        # missing dir; the warning is what tells the user "you probably
        # meant to run permuter first."
        if permuter_dir is not None:
            harvest_dir: Optional[Path] = permuter_dir
        else:
            harvest_dir = resolve_permuter_function_dir(function)
        if harvest_dir is None or not harvest_dir.is_dir():
            # Different remediation text depending on whether the user
            # explicitly supplied --permuter-dir: pointing them at
            # `nonmatchings/<fn>/` when they already overrode the path
            # would be misleading.
            if permuter_dir is not None:
                typer.echo(
                    f"--permuter-dir {permuter_dir}: directory does not "
                    f"exist. Continuing with the primitive adapters only.",
                    err=True,
                )
            else:
                typer.echo(
                    f"--with-permuter: no permuter output found "
                    f"(looked under nonmatchings/{function}/). "
                    f"Run `./permuter.py nonmatchings/{function}` in your "
                    f"decomp-permuter clone first, or pass --permuter-dir. "
                    f"Continuing with the primitive adapters only.",
                    err=True,
                )
        else:
            emit(f"Permuter dir:    {harvest_dir}")
            resolved_permuter_dir = harvest_dir

            def _permuter_adapter(ctx_):
                return permuter_source(ctx_, perm_dir_override=harvest_dir)

            sources.append(_permuter_adapter)
    emit()

    def _simplify_progress(compiled: int, limit: int, provenance: str) -> None:
        typer.echo(
            f"[simplify-order] compiling {compiled}/{limit}: {provenance}",
            err=True,
        )

    result = search(
        sources=sources,
        ctx=ctx,
        baseline=baseline_sig,
        target=target,
        target_late=target_late,
        force_phys=force_phys_target or None,
        protected_force_phys=protected_force_phys_target or None,
        class_id=class_id,
        max_candidates=max_candidates,
        timeout=timeout,
        preserve_precolor_enabled=preserve_precolor,
        progress_callback=_simplify_progress,
        skip_first_candidates=skip_first_candidates,
        skip_provenances=skip_provenance_values,
        skip_families=skip_family_values,
    )

    if json_out:
        retain_interrupt: _SimplifyRetainInterrupted | None = None
        try:
            ranked_probes = _simplify_retained_probe_records(
                result=result,
                function=function,
                force_phys_target=force_phys_target,
                retain_probes=retain_probes,
                melee_root=melee_root,
                retain_count=retain_count,
                checkdiff_guard=checkdiff_guard,
                timeout=timeout,
            )
        except _SimplifyRetainInterrupted as exc:
            retain_interrupt = exc
            ranked_probes = exc.records
        terminal_blocker = None
        if force_phys_target and residual_force_phys_target:
            residual_progress = [
                probe for probe in ranked_probes
                if _simplify_residual_force_phys_progressed(
                    probe=probe,
                    baseline_target_score=baseline_target_score,
                    residual_force_phys_target=residual_force_phys_target,
                )
            ]
            if not residual_progress:
                terminal_blocker = "no-retained-candidate-improved-residual-force-phys"
        if not ranked_probes and result.compile_failure_count:
            terminal_blocker = terminal_blocker or "retained-candidates-failed-compile"
        skip_controls_active = (
            skip_first_candidates > 0
            or bool(skip_provenance_values)
            or bool(skip_family_values)
        )
        if (
            retained_mode
            and skip_controls_active
            and result.total_compiles == 0
            and not ranked_probes
            and not result.compile_failure_count
        ):
            terminal_blocker = "retained-candidates-skipped-or-exhausted"
        if getattr(result, "aborted", False):
            terminal_blocker = (
                f"search-aborted-{getattr(result, 'abort_reason', None) or 'unknown'}"
            )
        if retain_interrupt is not None:
            terminal_blocker = (
                f"search-aborted-{retain_interrupt.abort_reason or 'unknown'}"
            )
        aborted = bool(getattr(result, "aborted", False)) or retain_interrupt is not None
        abort_reason = (
            getattr(result, "abort_reason", None)
            or (
                retain_interrupt.abort_reason
                if retain_interrupt is not None
                else None
            )
        )
        last_candidate = (
            getattr(result, "last_provenance", None)
            or (
                retain_interrupt.last_candidate
                if retain_interrupt is not None
                else None
            )
        )
        payload = {
            "function": function,
            "retained_mode": retained_mode,
            "source_file": str(retained_source_path) if retained_source_path else str(source_path),
            "pcdump": str(retained_pcdump_path) if retained_pcdump_path else None,
            "compile_unit_source": str(source_path),
            "class_id": class_id,
            "force_phys": {
                str(ig): phys for ig, phys in sorted(force_phys_target.items())
            },
            "protected_force_phys": {
                str(ig): phys
                for ig, phys in sorted(protected_force_phys_target.items())
            },
            "residual_force_phys": {
                str(ig): phys
                for ig, phys in sorted(residual_force_phys_target.items())
            },
            "baseline": {
                "simplify_order": list(baseline_sig.simplify_order),
                "target_score": baseline_target_score,
            },
            "summary": {
                "compiled": result.total_compiles,
                "skipped": getattr(result, "skipped_count", 0),
                "candidate_stream_position": getattr(
                    result, "candidate_stream_position", 0,
                ),
                "compile_failures": result.compile_failure_count,
                "gate_rejected": result.gate_rejected_count,
                "progress_hits": len(result.progress),
                "elapsed_seconds": result.elapsed_seconds,
            },
            "resume": {
                "skip_first_candidates": skip_first_candidates,
                "skip_provenances": skip_provenance_values,
                "skip_families": skip_family_values,
                "skipped_count": getattr(result, "skipped_count", 0),
                "skip_reasons": list(getattr(result, "skip_reasons", ()) or ()),
                "candidate_stream_position": getattr(
                    result, "candidate_stream_position", 0,
                ),
                "next_skip_first_candidates": getattr(
                    result, "candidate_stream_position", 0,
                ),
            },
            "ranked_probes": ranked_probes,
            "compile_failures": [
                dataclasses.asdict(failure)
                for failure in list(getattr(result, "compile_failures", ()) or ())
            ],
            "gate_rejection_reasons": list(result.gate_rejection_reasons),
            "aborted": aborted,
            "abort_reason": abort_reason,
            "last_candidate": last_candidate,
            "terminal_blocker": terminal_blocker,
        }
        print(json.dumps(payload, indent=2))
        if aborted:
            raise typer.Exit(130)
        return

    print(f"Compiled:        {result.total_compiles} variant(s)")
    compile_failures = list(getattr(result, "compile_failures", ()) or ())
    if compile_failures:
        print("Compile failure diagnostics:")
        for failure in compile_failures[:5]:
            provenance = getattr(failure, "provenance", "?")
            returncode = getattr(failure, "returncode", "?")
            diagnostic = getattr(failure, "diagnostic", "")
            print(f"  - {provenance} (rc={returncode}): {diagnostic}")
        if len(compile_failures) > 5:
            print(f"  ... {len(compile_failures) - 5} more failure(s)")
    print(f"Gate rejected:   {result.gate_rejected_count}")
    print(f"Progress hits:   {len(result.progress)}")
    print(f"Elapsed:         {result.elapsed_seconds:.1f}s")
    print()

    # Headline output: unified ranking of gate-passing + gate-rejected
    # candidates by the selected ranking mode. The campaign-3 use case
    # ("the 19 candidates that hit prefix=2 ranked by precolor disturbance")
    # only surfaces from this section — the existing progress / gate-rejected
    # sections split them by gate result.
    #
    # --rank-combined is a deprecated alias for --rank-mode combined; if the
    # user passes it, override rank_mode so existing scripts keep working.
    effective_rank_mode = (
        RankMode.combined if rank_combined else rank_mode
    )
    # In late-mode target is () and target_late carries the meaningful sequence;
    # pass the non-empty one to the renderers so their length checks are correct.
    effective_target = target_late if target_late else target
    if force_phys_target:
        _render_force_phys_ranking(result, force_phys_target)
        effective_target = tuple(force_phys_target.keys())
    elif effective_rank_mode is RankMode.combined:
        _render_combined_score_ranking(result, effective_target, alpha=combined_alpha)
    else:
        _render_lex_ranking(result, effective_target)

    if result.gate_rejection_reasons:
        print("Top gate-rejection reasons:")
        for reason in result.gate_rejection_reasons[:5]:
            print(f"  - {reason}")
        print()

    # Gate-rejected diagnostic: prefix-length distribution + top-N. Renders
    # nothing when there are no gate-rejected candidates; otherwise answers
    # "did any rejected candidate move simplify-order toward target?" — the
    # input for the harvest-vs-custom-scorer decision.
    if not force_phys_target:
        _render_gate_rejected_distribution(result, effective_target)

    # --triage composition: run `debug permute triage` after the harvest
    # to surface a second ranking by real-tree match% (the ground-truth
    # metric). Layer A of the workflow integration; closes the methodology
    # gap from the grVenom_80204284 campaign. Always runs before the early
    # exits below so progress=0 and exact-match paths still see the
    # ground-truth ranking.
    #
    # Thread `effective_rank_mode` + alpha + effective_target so the triage
    # section's cross-rank annotation references the same ordering as the
    # headline ranking table the user saw above — otherwise a user in
    # `--rank-mode combined` would see a "simplify-order rank #N"
    # annotation that disagrees with the "Best by combined score" table.
    _maybe_run_triage(
        triage_enabled=triage,
        with_permuter=with_permuter,
        permuter_dir_resolved=resolved_permuter_dir,
        function=function,
        melee_root=melee_root,
        result=result,
        rank_mode=effective_rank_mode,
        combined_alpha=combined_alpha,
        target=effective_target,
    )

    if result.exact_match is not None:
        if preserve_precolor:
            print("EXACT MATCH found:")
        else:
            print("Candidate is exact under perturbed precolor:")
            print("  preserve-precolor gate was off; verify by applying the "
                  "variant and running checkdiff before treating it as a real "
                  "match.")
        print(f"  provenance: {result.exact_match.provenance}")
        print(f"  parent:     {result.exact_match.parent_baseline}")
        print()
        print("Apply this variant manually to keep the change. Output is not "
              "auto-applied — review and commit by hand.")
        _flush_stdout_report()
        raise typer.Exit(0)

    if not result.progress:
        if force_phys_target:
            print("No variants improved force-phys assignments beyond baseline.")
        else:
            print("No variants made progress beyond baseline.")
        if not preserve_precolor and result.gate_rejected_count == 0:
            if force_phys_target:
                print("(Tried with --no-preserve-precolor — no candidate "
                      "changed the requested physical assignment.)")
            else:
                print("(Tried with --no-preserve-precolor — nothing changed the "
                      "simplify order at all.)")
        else:
            print("Consider:")
            if force_phys_target:
                print("  - Re-running with a wider candidate pool or more "
                      "source-shape levers while preserving the same "
                      "--force-phys objective.")
            else:
                print("  - Re-running with --no-preserve-precolor to see if any "
                      "variant produces the target order while disturbing other "
                      "RA inputs.")
            if not with_permuter:
                print("  - Running decomp-permuter (`./permuter.py "
                      f"nonmatchings/{function}`) then re-running this "
                      "command with --with-permuter to harvest its output.")
            else:
                print("  - Letting permuter run longer to grow the candidate "
                      "pool, then re-running the search.")
        _flush_stdout_report()
        raise typer.Exit(0)

    print(f"Top {min(3, len(result.progress))} progress candidate(s):")
    for i, scored in enumerate(result.progress[:3]):
        s = scored.score
        print(f"  {i + 1}. {scored.variant.provenance}")
        if force_phys_target:
            observed = ", ".join(
                f"ig{ig}->r{force_phys_target[ig]}"
                for ig in s.observed_prefix
            ) or "(none)"
            print(f"     force-phys hits: {s.common_prefix_length}/{len(s.target_prefix)}")
            print(f"     matched:         {observed}")
            print(f"     baseline:        {s.baseline_common_prefix_length}/"
                  f"{len(s.target_prefix)} matched")
        else:
            print(f"     prefix match:  {s.common_prefix_length}/{len(s.target_prefix)}")
            print(f"     observed:      {','.join(str(x) for x in s.observed_prefix)}")
            print(f"     baseline:      {s.baseline_common_prefix_length}/"
                  f"{len(s.target_prefix)} matched")
    print()
    if force_phys_target:
        print("These variants improve the force-phys objective but don't fully "
              "hit it. Inspect them with `debug inspect diff` to see what "
              "changed, then iterate.")
    else:
        print("These variants make partial progress but don't fully hit the "
              "target. Inspect them with `debug inspect diff` to see what "
              "changed, then iterate.")
    _flush_stdout_report()



@mutate_app.command(name="search")
def tier3_search(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to search (required).",
        ),
    ],
    budget: Annotated[
        int,
        typer.Option(
            "--budget",
            help="Maximum number of seed mutations to try. Hard cap "
                 "on seed count; truncated by priority order.",
        ),
    ] = 5,
    per_seed_time: Annotated[
        int,
        typer.Option(
            "--per-seed-time",
            help="Wall-clock seconds to permute each compiling seed. "
                 "The permuter runs against the seed's perm-dir for "
                 "this long, then is killed. Default 60s.",
        ),
    ] = 60,
    total_time: Annotated[
        int,
        typer.Option(
            "--total-time",
            help="Global wall-clock cap (seconds) across the whole "
                 "per-seed search. Stop early once exceeded, even if "
                 "seeds remain. Default 600s (10 minutes).",
        ),
    ] = 600,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec; auto-derived if omitted.",
        ),
    ] = None,
    blend: Annotated[
        float,
        typer.Option("--blend", help="mwcc-score blend weight."),
    ] = 0.1,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum delta (% improvement, post-transfer) to "
                 "consider a seed's permuter run a win when applying "
                 "with --apply-best. Default 0.05 — matches the global "
                 "debug permute verify default.",
        ),
    ] = 0.05,
    apply_best: Annotated[
        bool,
        typer.Option(
            "--apply-best",
            help="After ranking, if the winning seed's best candidate "
                 "improves real-source match by >= --threshold, "
                 "transfer it to the real tree via the same debug permute verify "
                 "machinery (with the inline_fn placeholder guard). "
                 "Off by default — dry-run semantics.",
        ),
    ] = False,
    include_low_confidence: Annotated[
        bool,
        typer.Option(
            "--include-low-confidence",
            help="Also generate seeds from bindings the symbol-bridge "
                 "flagged as low-confidence (red flags present: nested "
                 "decls, statics, extra compiler-introduced virtuals). "
                 "Off by default — skip these to avoid bad seeds on "
                 "functions where the cursor heuristic is unreliable. "
                 "Verify the binding manually via "
                 "`debug inspect var-to-virtual <var> -f FN --basis` before "
                 "opting in.",
        ),
    ] = False,
) -> None:
    """Tier 3: multi-start search over targeted mutation seeds.

    Workflow:
      1. Resolve pcdump + target.
      2. Enumerate variable bindings via the symbol bridge.
      3. Plan up to --budget seed mutations.
      4. Materialize each seed inside
         nonmatchings/<fn>/tier3_seed_<idx>/.
      5. Smoke-compile each. If all seeds fail, exit non-zero with a
         clear message.
      6. For each compiling seed, launch decomp-permuter (with
         mwcc-debug score blending) for up to --per-seed-time seconds.
         The global --total-time cap stops the loop early once
         exceeded.
      7. Find the best candidate each permuter produced and rank
         seeds by delta (baseline score minus best candidate's score).
      8. Print the top result with full diff path.
      9. If --apply-best is set, transfer the winning candidate into
         the real source tree via the same debug permute verify machinery (with
         the inline_fn placeholder check still firing).
    """
    from src.cli.debug import (
        _abort_function_not_in_dump,
        _build_local_dll,
        _find_compiler_dir,
        _find_unit_for_function,
        _find_wibo,
        _load_target_spec,
        _ninja_cflags_for_unit,
        _permuter_import_hint,
        _resolve_pcdump_path,
        _resolve_permuter_function_dir,
        _run_auto_verify_command_with_status,
        verify_perm,
        DEFAULT_MELEE_ROOT,
        analyze_frame_from_function,
        parse_hook_events,
        parse_pcdump,
        score_function,
    )
    from ...mwcc_debug.symbol_bridge import list_bindings
    from ...mwcc_debug.tier3_search import (
        find_best_candidate,
        materialize_seed,
        plan_seeds,
        plan_seeds_from_lifetime_layout_probes,
        rank_seed_results,
        run_per_seed_permute,
        save_compile_failure,
        smoke_compile,
    )
    from ...mwcc_debug.pressure_explorer import (
        generate_frame_directed_probes,
        generate_lifetime_layout_probes,
    )

    melee_root = DEFAULT_MELEE_ROOT
    explicit_target = target is not None

    # Resolve unit + sources
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    src_rel = f"src/{unit}.c"
    src_path = melee_root / src_rel
    base_source = src_path.read_text()

    # Resolve pcdump for the bridge
    pcdump_path = _resolve_pcdump_path(None, function, melee_root)
    text = pcdump_path.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre = fn.last_precolor_pass()
    if pre is None:
        typer.echo(
            f"no pre-coloring pass for {function}", err=True,
        )
        raise typer.Exit(3)

    # Resolve/derive the target spec before seed planning. Frame-specific
    # targets can drive seed generation, not just later candidate scoring.
    if target is None:
        target = melee_root / "build" / "mwcc_debug_cache" / \
            f"{unit}_target.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            events_list = parse_hook_events(text)
            events = find_function(events_list, function)
            spec = derive_target_from_function(fn, events=events)
            target.write_text(json.dumps(spec, indent=2))
            print(f"[tier3] derived target -> {target}")
    try:
        target_spec = _load_target_spec(target)
    except typer.Exit:
        raw_target_text = target.read_text() if target.exists() else ""
        try:
            raw_target = json.loads(raw_target_text) if raw_target_text else None
        except json.JSONDecodeError:
            raw_target = None
        if raw_target == {}:
            target_spec = {}
        else:
            raise

    bindings = list_bindings(base_source, function, pre)
    plans = []
    target_frame = target_spec.get("frame")
    if isinstance(target_frame, dict):
        frame_probes = generate_frame_directed_probes(
            base_source,
            function,
            current_frame=analyze_frame_from_function(fn),
            target_frame=target_frame,
            max_probes=budget,
        )
        plans.extend(plan_seeds_from_lifetime_layout_probes(
            frame_probes,
            budget=budget,
        ))
        if plans:
            print(
                "[tier3] using frame-directed seed plans from target frame"
            )
    remaining_budget = max(0, budget - len(plans))
    if remaining_budget:
        plans.extend(plan_seeds(
            bindings, budget=remaining_budget,
            include_low_confidence=include_low_confidence,
        ))
    if not plans:
        probes = generate_lifetime_layout_probes(
            base_source,
            function,
            max_probes=budget,
        )
        plans = plan_seeds_from_lifetime_layout_probes(
            probes,
            budget=budget,
        )
        if plans:
            print(
                "[tier3] no symbol-bridge seed plans; using "
                "source-shape probe fallback"
            )
    if not plans:
        # Diagnostic: if there ARE low-confidence bindings, explain.
        n_low = sum(1 for b in bindings if b.confidence == "low-confidence")
        if n_low and not include_low_confidence:
            typer.echo(
                f"no Tier 3 targets — {n_low} local binding(s) demoted to "
                f"low-confidence by red flags. Run `debug inspect var-to-virtual "
                f"<var> -f {function} --basis` to audit, then re-run "
                f"with --include-low-confidence if mapping looks correct.",
                err=True,
            )
        else:
            typer.echo(
                "no Tier 3 targets; fall back to `debug permute run -f "
                f"{function}` for a vanilla Tier 2 run.",
                err=True,
            )
        raise typer.Exit(1)

    print(f"[tier3] {len(plans)} seed plans:")
    for i, p in enumerate(plans):
        print(f"  seed{i}: {p.description}")

    # Materialize + smoke-compile
    wibo = _find_wibo()
    debug_compiler = _find_compiler_dir() / "mwcceppc_debug.exe"
    if wibo is None or not wibo.exists() or not debug_compiler.exists():
        typer.echo(
            "wibo or patched compiler missing. "
            "Run `debug dump setup` first.",
            err=True,
        )
        raise typer.Exit(4)
    cflags, _mw = _ninja_cflags_for_unit(src_rel)

    perm_dir = _resolve_permuter_function_dir(
        function, perm_root=perm_root, melee_root=melee_root)
    if not perm_dir.exists():
        typer.echo(
            f"{perm_dir} not found.\n"
            + _permuter_import_hint(
                function,
                perm_root=perm_root,
                melee_root=melee_root,
                unit=unit,
            ),
            err=True,
        )
        raise typer.Exit(2)

    baseline_score: Optional[int] = None
    if explicit_target and target_spec:
        baseline_events_list = parse_hook_events(text)
        baseline_events = find_function(baseline_events_list, function)
        baseline_score = int(score_function(
            fn,
            target_spec,
            events=baseline_events,
        ).total)
        print(f"[tier3] target baseline score={baseline_score}")

    materialized: list = []
    for i, plan in enumerate(plans):
        seed_dir = perm_dir / f"tier3_seed_{i}"
        out_c = materialize_seed(base_source, function, plan, seed_dir)
        if out_c is None:
            print(f"[tier3] seed{i}: mutation unsupported; skipping")
            continue
        result = smoke_compile(
            out_c, wibo, debug_compiler, cflags, melee_root,
            extra_include_dirs=[src_path.parent],
        )
        if result.ok:
            print(f"[tier3] seed{i}: compile=ok")
        else:
            log_path = save_compile_failure(seed_dir, result)
            print(f"[tier3] seed{i}: compile=FAIL — {result.one_line_reason}")
            print(f"         (full output: {log_path}, seed source: "
                  f"{seed_dir / 'base.c'})")
        seed_score = None
        if (
            result.ok
            and explicit_target
            and target_spec
            and result.pcdump_text
        ):
            seed_fns = parse_pcdump(result.pcdump_text)
            seed_fn = next(
                (candidate for candidate in seed_fns if candidate.name == function),
                None,
            )
            if seed_fn is not None:
                seed_events_list = parse_hook_events(result.pcdump_text)
                seed_events = find_function(seed_events_list, function)
                seed_score = int(score_function(
                    seed_fn,
                    target_spec,
                    events=seed_events,
                ).total)
                print(f"[tier3] seed{i}: target score={seed_score}")
        materialized.append((plan, seed_dir, result, seed_score))

    compiled = [m for m in materialized if m[2].ok]
    if not compiled:
        typer.echo(
            f"all {len(materialized)} tier3 seeds failed to compile.",
            err=True,
        )
        typer.echo("", err=True)
        typer.echo("Failed seeds (inspect each):", err=True)
        for i, (plan, seed_dir, result, _seed_score) in enumerate(materialized):
            typer.echo(
                f"  seed{i} ({plan.mutator} on {plan.target_var}): "
                f"{result.one_line_reason}",
                err=True,
            )
            typer.echo(
                f"    sources: {seed_dir / 'base.c'}",
                err=True,
            )
            typer.echo(
                f"    error:   {seed_dir / 'compile_error.txt'}",
                err=True,
            )
        typer.echo("", err=True)
        typer.echo(
            "Common causes: (a) symbol-bridge mapping is wrong (check "
            "`debug inspect var-to-virtual -f FN --basis`); (b) the mutation "
            "produced invalid C (look at base.c); (c) the function uses "
            "a pattern the mutators don't handle yet.",
            err=True,
        )
        raise typer.Exit(5)

    print()
    print(
        f"[tier3] {len(compiled)}/{len(materialized)} seeds compiled. "
        f"Per-seed permute budget: {per_seed_time}s. "
        f"Global cap: {total_time}s."
    )

    # Stage each compiling seed_dir to look like a permuter perm-dir.
    # Inherit target.o/compile.sh/settings.toml from the parent perm_dir
    # so the permuter has everything it needs.
    inherited_files = ["target.o", "compile.sh", "settings.toml"]
    for plan, seed_dir, _result, _seed_score in compiled:
        for fname in inherited_files:
            src_file = perm_dir / fname
            dst_file = seed_dir / fname
            if src_file.exists() and not dst_file.exists():
                shutil.copy2(src_file, dst_file)
        # Make compile.sh executable in case the copy stripped mode.
        sh = seed_dir / "compile.sh"
        if sh.exists():
            sh.chmod(0o755)

    # Build the runner closure. It invokes the permute_with_mwcc.py
    # wrapper directly against the seed_dir for `time_seconds` seconds,
    # then SIGTERMs it. Output lands inside seed_dir/output-N-M/.
    wrapper = (
        melee_root / "tools" / "melee-agent" / "scripts"
        / "permute_with_mwcc.py"
    )
    if not wrapper.exists():
        typer.echo(f"wrapper not found: {wrapper}", err=True)
        raise typer.Exit(4)

    def _permute_runner(
        seed_dir_arg: Path, fn_name: str, time_seconds: int,
    ) -> None:
        env = os.environ.copy()
        env["MELEE_PERMUTER_ROOT"] = str(perm_root)
        env["MELEE_ROOT"] = str(melee_root)
        env["MWCC_DEBUG_TARGET"] = str(target)
        env["MWCC_DEBUG_FN"] = fn_name
        env["MWCC_DEBUG_UNIT"] = src_rel
        env["MWCC_DEBUG_BLEND"] = str(blend)
        cmd = ["python", str(wrapper), str(seed_dir_arg), "-j", "1"]
        # Use subprocess.Popen + wait(timeout) so we can kill on
        # expiry. permuter.py runs indefinitely; we want a hard cap.
        proc = subprocess.Popen(
            cmd, env=env, cwd=perm_root,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            proc.wait(timeout=time_seconds)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    # Read the baseline score from the parent perm_dir's first seeded
    # output (the unmutated base.c's score). We don't have a clean
    # source of truth pre-permute — use the parent perm_dir's lowest-
    # scoring `output-N-M` as a coarse baseline if it exists, else None.
    parent_best = find_best_candidate(perm_dir)
    if baseline_score is None and parent_best is not None:
        m = re.match(r"^output-(\d+)-\d+$", parent_best.parent.name)
        if m:
            baseline_score = int(m.group(1))

    # Per-seed loop, respecting the global time budget.
    print("[tier3] launching per-seed permuter runs...")
    results: list = []
    deadline = time.monotonic() + total_time
    for i, (plan, seed_dir, _result, seed_score) in enumerate(compiled):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                f"[tier3] global --total-time={total_time}s exhausted; "
                f"skipping {len(compiled) - i} remaining seed(s)."
            )
            break
        # Don't let a per-seed timer run past the global cap.
        slot = min(per_seed_time, int(remaining))
        print(
            f"[tier3] seed{i}: permuting for {slot}s "
            f"({plan.description})..."
        )
        res = run_per_seed_permute(
            seed_idx=i,
            plan=plan,
            seed_dir=seed_dir,
            fn_name=function,
            per_seed_time=slot,
            runner=_permute_runner,
            baseline_score=baseline_score,
            seed_score=seed_score,
        )
        if res.error:
            print(f"[tier3] seed{i}: runner error: {res.error}")
        elif res.best_candidate is None:
            print(
                f"[tier3] seed{i}: no improvement after "
                f"{res.ran_seconds:.1f}s."
            )
        else:
            print(
                f"[tier3] seed{i}: best score={res.best_score} "
                f"(baseline={res.baseline_score}, delta={res.delta}) "
                f"in {res.ran_seconds:.1f}s; "
                f"candidate={res.best_candidate}"
            )
        results.append(res)

    print()
    ranked = rank_seed_results(results)
    if not ranked or all(r.best_candidate is None for r in ranked):
        typer.echo(
            "[tier3] No seed produced a permuter improvement. "
            "Consider increasing --per-seed-time, widening --budget, "
            "or inspecting individual seed_dirs manually.",
            err=True,
        )
        return

    print("[tier3] Ranked results (best first):")
    for r in ranked:
        if r.best_candidate is None:
            print(
                f"  seed{r.seed_idx}: delta=0 (no improvement) — "
                f"{r.plan.description}"
            )
        else:
            print(
                f"  seed{r.seed_idx}: delta={r.delta} "
                f"(score {r.baseline_score}->{r.best_score}) — "
                f"{r.plan.description}"
            )
            print(f"      candidate: {r.best_candidate}")

    winner = next(
        (r for r in ranked if r.best_candidate is not None), None,
    )
    if winner is None:
        return

    print()
    print(
        f"[tier3] Top: seed{winner.seed_idx} delta={winner.delta} "
        f"({winner.plan.description})"
    )
    print(f"        candidate: {winner.best_candidate}")
    diff_path = winner.best_candidate.parent / "diff.diff"
    if diff_path.exists():
        print(f"        diff:      {diff_path}")

    if not apply_best:
        print()
        print(
            "[tier3] --apply-best not set; re-run with --apply-best to "
            "transfer the winner via debug permute verify, or run manually:\n"
            f"  melee-agent debug permute verify {winner.best_candidate} "
            f"-f {function} --keep"
        )
        return

    # --apply-best: invoke debug permute verify in-process so the inline_fn
    # placeholder guard + 3-way merge logic from commit f39e264a9
    # still fires.
    print()
    print("[tier3] --apply-best: invoking debug permute verify with --keep...")
    verify_perm(
        candidate=winner.best_candidate,
        function=function,
        keep=True,
        force=False,
        threshold=threshold,
        json_out=False,
    )


def _looks_like_melee_root(path: Path) -> bool:
    return (path / "configure.py").is_file() and (path / "src" / "melee").is_dir()


def _package_melee_root() -> Path:
    package_path = Path(__file__).resolve()
    for parent in package_path.parents:
        if (
            (parent / "config" / "GALE01").exists()
            and (parent / "tools" / "checkdiff.py").exists()
        ):
            return parent
    for parent in package_path.parents:
        if _looks_like_melee_root(parent):
            return parent
    # src/cli/debug/__init__.py -> debug -> cli -> src -> melee-agent -> tools -> repo root
    return package_path.parents[5]


def _checkdiff_script_path(melee_root: Path) -> Path:
    """Return the authoritative checkdiff script while preserving target cwd.

    Matcher worktrees can carry stale fork-tooling overlays. Running the
    installed package's copy of checkdiff keeps classifier logic current while
    subprocess cwd still points at the worktree whose objects are being diffed.
    """
    package_checkdiff = _package_melee_root() / "tools" / "checkdiff.py"
    if package_checkdiff.exists():
        return package_checkdiff
    return melee_root / "tools" / "checkdiff.py"


def _select_order_variant_source_hunk(
    variant: Mapping[str, Any],
    *,
    function: str | None,
) -> str | None:
    from src.cli.debug import _compact_source_hunk_for_function
    if not function:
        return None
    source_path = variant.get("source_retained") or variant.get("path")
    if not isinstance(source_path, str) or not source_path.endswith(".c"):
        return None
    try:
        path = Path(source_path)
        if not path.exists():
            return None
        return _compact_source_hunk_for_function(
            path.read_text(encoding="utf-8", errors="replace"),
            function,
        )
    except OSError:
        return None
