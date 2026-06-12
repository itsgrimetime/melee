#!/usr/bin/env python3
"""Generate the kill-switch frozen artifacts (pcdumps, OrderTargets, negative
controls, eligibility.json) from the committed fixture sources.

Requires a working local mwcc-debug (`melee-agent debug dump doctor` PASSES).
Run from tools/melee-agent:

    python tests/fixtures/order_distance/generate.py

SAFETY CONTRACTS:
  * B8 — every TU swap is try/finally-restored (byte-exact), even on Ctrl-C
    or an exception mid-compile.
  * B9 — the whole run holds the repo-wide build lock
    (src.search.adapters._acquire_repo_build_lock) and exports
    CHECKDIFF_NO_LOCK=1 so children (checkdiff, dump local) and the in-process
    T3 collector — which all re-acquire the SAME lock file — no-op instead of
    deadlocking (the established _checkdiff_env_for_locked_child contract).
    The export happens AFTER our own acquisition (else our own acquisition
    would no-op too).
  * Cache coherence — derivation goes through the T3 collector, whose
    fresh-everything contract compiles its own baseline pcdump and runs
    checkdiff WITH a build; the fixture pcdumps here are likewise written to
    explicit paths with --no-cache-sync. The shared baseline cache is never
    read or written.
  * Negative controls are EXACT committed edits, verified non-improving at
    freeze; a control that improves match% aborts the run loudly.
  * eligibility.json always records the outcome — no silent unrunnable path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../tests/fixtures/order_distance
AGENT_ROOT = HERE.parents[2]                    # .../tools/melee-agent
MELEE_ROOT = AGENT_ROOT.parents[1]              # worktree root
sys.path.insert(0, str(AGENT_ROOT))

from src.mwcc_debug.order_target_derive import derive_order_target  # noqa: E402
from src.search.adapters import _acquire_repo_build_lock  # noqa: E402
from src.search.directed.order_metric import score_candidate_reanchored  # noqa: E402
from src.search.directed.order_target import OrderTarget, Routing  # noqa: E402

WITNESSES = [
    {
        "name": "mnDiagram_802427B4",
        "function": "mnDiagram_802427B4",
        "unit": "melee/mn/mndiagram",
        "tu": MELEE_ROOT / "src" / "melee" / "mn" / "mndiagram.c",
        # Exact negative-control candidates (adjacent uninitialized decl swaps
        # inside mnDiagram_802427B4 at a527c0227~1; the first verified
        # non-improving one is used):
        "control_swaps": [
            ("    HSD_Text* text;\n    HSD_Text* row_text;",
             "    HSD_Text* row_text;\n    HSD_Text* text;"),
            ("    f32 x_spacing;\n    f32 y_spacing;",
             "    f32 y_spacing;\n    f32 x_spacing;"),
        ],
        "chain": [],  # no secondary chain for this witness
    },
    {
        "name": "fn_803ACD58",
        "function": "fn_803ACD58",
        "unit": "sysdolphin/baselib/hsd_3AA7",
        "tu": MELEE_ROOT / "src" / "sysdolphin" / "baselib" / "hsd_3AA7.c",
        # chain step 0 (=pre_win) decl block: icon_size; hdr_plus_icon; i;
        # The win lever is the hdr_plus_icon/i pair, so the control swaps the
        # OTHER adjacent pair:
        "control_swaps": [
            ("    s32 icon_size;\n    s32 hdr_plus_icon;",
             "    s32 hdr_plus_icon;\n    s32 icon_size;"),
        ],
        "chain": ["chain_2.c", "chain_3.c"],  # secondary monotone witness
    },
]


class BuildFailure(RuntimeError):
    """The (swapped-in) TU source did not compile against the current repo
    tree — a recordable not-eligible finding, distinct from an infra crash."""


@contextmanager
def swapped_tu(tu_path: Path, source_text: str):
    """B8: byte-exact restore on EVERY exit path."""
    original = tu_path.read_bytes()
    try:
        tu_path.write_text(source_text, encoding="utf-8")
        yield
    finally:
        tu_path.write_bytes(original)


def run(argv, cwd, timeout=900):
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=os.environ.copy())
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed (rc={proc.returncode}): {' '.join(map(str, argv))}\n"
            f"{(proc.stderr or proc.stdout or '')[-1500:]}"
        )
    return proc


def dump_pcdump(tu: Path, function: str, out: Path) -> None:
    run([sys.executable, "-m", "src.cli", "debug", "dump", "local", str(tu),
         "--function", function, "--output", str(out), "--no-cache-sync"],
        cwd=AGENT_ROOT)


def checkdiff_pct(function: str) -> float:
    proc = subprocess.run(
        [sys.executable, str(MELEE_ROOT / "tools" / "checkdiff.py"),
         function, "--format", "json"],
        cwd=MELEE_ROOT, capture_output=True, text=True, timeout=900,
        env=os.environ.copy(),
    )
    # rc 0=match, 1=mismatch (both emit JSON); anything else, or an empty
    # stdout (a "ninja failed:" build error goes to stderr with rc=1), is a
    # hard failure. Mirror the T3 collector's clean-hard-error contract
    # (_collect_order_target_inputs, the rc/empty-stdout guard) rather than
    # raising a raw JSONDecodeError — a frozen historical source that no longer
    # compiles against HEAD is a recordable not-eligible finding, not a crash.
    if proc.returncode not in (0, 1) or not (proc.stdout or "").strip():
        raise BuildFailure(
            f"checkdiff/build failed for {function} (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '')[-500:]}"
        )
    payload = json.loads(proc.stdout)
    return float(payload.get("fuzzy_match_percent") or 0.0)


def derive(function: str, unit: str) -> OrderTarget:
    """Run the §4.2 pipeline in-process via the T3 collector (the TU on disk is
    the base being derived — the caller swapped it in)."""
    import src.cli.debug as debugcli
    inputs = debugcli._collect_order_target_inputs(
        function=function, unit=unit, class_id=0,
        melee_root=MELEE_ROOT, checkdiff_timeout=120.0,
    )
    return derive_order_target(inputs)


def choose_named_pair(pre, win, order_target: dict) -> tuple[list, str]:
    """B7: record the pair assertion (c) pins — the first persistent role pair
    inverted in pre_win and correct in win (target direction from the proven
    vector)."""
    if not (pre.valid and win.valid):
        return [], "unavailable: pre/win candidate invalid under the target"
    persistent = sorted(set(pre.ranks_by_role) & set(win.ranks_by_role))
    for a, b in combinations(persistent, 2):
        tdir = order_target[a] < order_target[b]
        pre_dir = pre.ranks_by_role[a] < pre.ranks_by_role[b]
        win_dir = win.ranks_by_role[a] < win.ranks_by_role[b]
        if pre_dir != tdir and win_dir == tdir:
            return [a, b], (
                f"auto-selected at freeze: first persistent pair inverted in "
                f"pre_win and correct in win (target: ig{a} before ig{b})"
            )
    return [], "NO flipping pair among persistent roles — assertion (c) will fire"


def process_witness(w: dict) -> dict:
    wdir = HERE / w["name"]
    fn, unit, tu = w["function"], w["unit"], w["tu"]
    pre_src = (wdir / "pre_win.c").read_text(encoding="utf-8")
    win_src = (wdir / "win.c").read_text(encoding="utf-8")

    # Negative control: first committed exact swap verified non-improving.
    # A frozen historical source that no longer compiles against HEAD (e.g. an
    # identifier whose declaration was removed by a later restructure) is the
    # §6c eligibility risk in its strongest form: the base is not derivation-
    # eligible. Record that as a non-directed routing and continue — main()'s
    # gating then promotes the §6c contingency witness. No silent unrunnable
    # path; the build error is captured verbatim into class_evidence.
    try:
        with swapped_tu(tu, pre_src):
            base_pct = checkdiff_pct(fn)
    except BuildFailure as exc:
        return {
            "routing": Routing.UNSTABLE_TARGET.value,
            "class_evidence": (
                "frozen pre-win source does not compile against the current "
                f"repo tree — not derivation-eligible: {exc}"
            ),
            "base_match_percent": None,
            "negative_control_edit": None,
            "negative_control_match_percent": None,
            "not_eligible_reason": "pre_win_source_does_not_compile_against_HEAD",
        }
    control_src, control_desc, control_pct = None, None, None
    for old, new in w["control_swaps"]:
        if old not in pre_src:
            continue
        candidate = pre_src.replace(old, new, 1)
        with swapped_tu(tu, candidate):
            pct = checkdiff_pct(fn)
        if pct <= base_pct:
            control_src, control_desc, control_pct = candidate, f"swap: {old!r} -> {new!r}", pct
            break
    if control_src is None:
        raise SystemExit(
            f"[{w['name']}] every candidate control swap improved match% or was "
            f"absent — pick a different adjacent decl pair and re-run (loud abort; "
            f"assertion (d) requires a verified non-improving control)."
        )
    (wdir / "negative_control.c").write_text(control_src, encoding="utf-8")

    # Pcdumps for pre/win/control (+ chain steps).
    sources = {"pre_win": pre_src, "win": win_src, "negative_control": control_src}
    for extra in w["chain"]:
        sources[extra.removesuffix(".c")] = (wdir / extra).read_text(encoding="utf-8")
    for name, src in sources.items():
        with swapped_tu(tu, src):
            dump_pcdump(tu, fn, wdir / f"{name}.pcdump.txt")

    # Derivation on the pre-win base (the eligibility check). The classifier's
    # Step-1 precondition RAISES ValueError when the checkdiff primary is not
    # register-only (a structural diff / normalized-structural-match is not in
    # the order-distance pool). That raise IS the routing-out signal for this
    # witness — record it as not_order_class (valid data per the derivation-as-
    # classifier design) so the eligibility machine consumes it; never crash
    # the freeze. The verbatim classifier message is kept as class_evidence.
    try:
        with swapped_tu(tu, pre_src):
            target = derive(fn, unit)
    except ValueError as exc:
        if "not in the order-distance pool" not in str(exc):
            raise
        return {
            "routing": Routing.NOT_ORDER_CLASS.value,
            "class_evidence": str(exc),
            "base_match_percent": base_pct,
            "negative_control_edit": control_desc,
            "negative_control_match_percent": control_pct,
            "not_eligible_reason": "checkdiff_primary_not_register_only",
        }

    record = {
        "routing": target.routing,
        "class_evidence": target.class_evidence,
        "base_match_percent": base_pct,
        "negative_control_edit": control_desc,
        "negative_control_match_percent": control_pct,
    }
    if target.routing != Routing.DIRECTED.value:
        return record

    # Score pre/win against the derived target to record the named pair (B7).
    from src.mwcc_debug.role_descriptor import Compile, build_descriptors
    pre_pc = (wdir / "pre_win.pcdump.txt").read_text(encoding="utf-8")
    ref_descs = build_descriptors(
        Compile.from_text(pre_pc, fn, pre_src), class_id=0
    )
    def _score(name: str, src_text: str):
        return score_candidate_reanchored(
            (wdir / f"{name}.pcdump.txt").read_text(encoding="utf-8"),
            ref_descs, function=fn, class_id=0,
            order_target=target.order_target, phys_target=target.phys_target,
            cand_source=src_text,
        )
    pair, provenance = choose_named_pair(
        _score("pre_win", pre_src), _score("win", win_src), target.order_target
    )
    target.named_pair = pair
    target.named_pair_provenance = provenance
    target.save_yaml(wdir / "order_target.yaml")
    record["named_pair"] = pair
    record["named_pair_provenance"] = provenance
    return record


def main() -> None:
    results: dict = {}
    with _acquire_repo_build_lock(MELEE_ROOT, label="kill-switch fixture generation"):
        # B9: children + the in-process collector re-acquire the SAME lock
        # file; the env flag makes those acquisitions no-op (established
        # contract). Exported AFTER our own acquisition, removed on exit.
        os.environ["CHECKDIFF_NO_LOCK"] = "1"
        try:
            for w in WITNESSES:
                print(f"=== {w['name']} ===", flush=True)
                results[w["name"]] = process_witness(w)
                print(json.dumps(results[w["name"]], indent=2), flush=True)
        finally:
            os.environ.pop("CHECKDIFF_NO_LOCK", None)

    # Eligibility: the PRIMARY witness gates whenever it derives `directed` —
    # even with an empty named_pair (then T7 FIRES with the precise cause: no
    # persistent pair flips => the win is invisible to role-stable order
    # distance, the §6c assertion (a)/(c) firing at freeze time — it must NOT
    # be dodged by falling back). The cardstate witness is promoted ONLY when
    # the primary base is not derivation-eligible (§6c contingency). Never
    # silent — null means HARD STOP at T7 with an orchestrator report.
    gating = None
    r_802 = results.get("mnDiagram_802427B4") or {}
    r_card = results.get("fn_803ACD58") or {}
    if r_802.get("routing") == Routing.DIRECTED.value:
        gating = "mnDiagram_802427B4"
    elif r_card.get("routing") == Routing.DIRECTED.value:
        gating = "fn_803ACD58"
    eligibility = {
        "gating_fixture": gating,
        "witnesses": results,
        "notes": (
            "gating: mnDiagram_802427B4 whenever it derives directed (an "
            "empty named_pair then FIRES at T7 — the win invisible to "
            "role-stable order distance is a refutation, never dodged); "
            "fn_803ACD58 (pure decl-order chain) is promoted ONLY when the "
            "primary base is not derivation-eligible (§6c contingency). "
            "null gating_fixture => NO derivation-eligible witness: the kill "
            "switch hard-stops and the orchestrator must revisit the "
            "kill-switch function assignment."
        ),
    }
    (HERE / "eligibility.json").write_text(
        json.dumps(eligibility, indent=2), encoding="utf-8"
    )
    print(f"\ngating_fixture: {gating}")
    if gating is None:
        print("NO derivation-eligible witness — T7 will hard-stop with an "
              "orchestrator report. This is a recorded finding, not a silent pass.")


if __name__ == "__main__":
    main()
