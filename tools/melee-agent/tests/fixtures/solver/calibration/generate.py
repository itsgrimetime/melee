#!/usr/bin/env python3
"""Freeze the five §1.5 calibration fixtures from REAL functions.

Requires a working local mwcc-debug (`melee-agent debug dump doctor` PASSES).
Run from tools/melee-agent:

    python tests/fixtures/solver/calibration/generate.py

SAFETY CONTRACTS (mirrors the order-distance kill-switch generator):
  * every TU swap is try/finally-restored byte-exact (swapped_paths);
  * the whole run holds the repo build lock and exports CHECKDIFF_NO_LOCK=1
    AFTER our own acquisition so children/in-process collectors no-op instead
    of deadlocking;
  * collection goes through the T3 order-target collector's fresh-everything
    contract (fresh checkdiff WITH build, fresh baseline pcdump, no cache);
  * ABORT LOUDLY per fixture on any precondition failure — never freeze a
    placeholder (codex blocker 2: fixtures must be REAL function+IG+target).

HEADER-LOCK NOTE (T10 execution finding; zq-probe report 2026-06-12 substrate
note 4): the two win-recovery base/post sources live on the campaign branch
`claude/mndiagram-802427B4-investigation`, which carries divergent mn headers
(`mndiagram*.static.h`, `mndiagram.h`). Compiling that historical `.c` against
the CURRENT worktree headers does NOT reproduce the near-match state. So for
the win fixtures we swap the `.c` AND the colocated mn headers from the SAME
revision (the proven reproduce-a-worktree-state technique). The reject fixtures
are collected from the CURRENT worktree per the plan and use no header swap.

PLAN-TYPO CORRECTION (recorded in FIXTURE_PROVENANCE.md): fixture 3 in the plan
text reads function=mnDiagram_HandleInput / unit=melee/mn/mndiagram — that
symbol does not exist in upstream or the worktree. The real S2 function (spec
§6 / task brief: "mnDiagram2_HandleInput S2 (rejected_a)") is
mnDiagram2_HandleInput in melee/mn/mndiagram2. Corrected here.

T10c WIN-FIXTURE REDESIGN (plan "T10b outcome → BINDING design amendment"). The
win fixtures are now SELF-CONTAINED pre/post pairs (NOT base-vs-dol):
  1. `phys_target` := the POST-win build's ACTUAL coloring (every post-IG node's
     observed register), extracted from the post pcdump in the SAME build
     context — not the dol. The win's outcome IS that coloring; the §3 gate
     asserts the surrogate reaches it (predict_assignments(post_ig) ==
     phys_target, which holds at G1=100%).
  2. Admission is judged on the PRE-vs-POST OBJECT pair (their diff IS the win),
     via the SAME `classify_asm_diff` arbiter checkdiff uses. The admission rule
     is FULLNORM-0 (`normalized_diff_lines == 0`): the masked-structural diff
     (registers/immediates/labels/relocations masked) is zero, so every real
     difference is a register assignment — "pure coloring." A win that grows the
     frame by the slot its alias/temp local reserves still satisfies FULLNORM-0
     (the frame delta is part of the win, recorded in provenance); it fails only
     the STRICTER `primary in REGISTER_ONLY_PRIMARIES` check, because the
     stack-frame probe relabels the primary `stack-layout`. order_target_derive
     itself documents FULLNORM-0 as "the pool's STRONGEST admission signal."
     WHY this route over base-vs-dol: after 114 commits of TU-context drift the
     win BASE-vs-dol states became FULLNORM-0-but-±8B-frame-gapped `stack-layout`
     residuals → strictly excluded → 0/2 froze (T10b). The POST states reproduce
     faithfully today, so collecting the target at POST is the faithful fixture.
  3. The frozen artifact carries BOTH IGs (base.pcdump.txt = pre = the solver's
     input; post_win.pcdump.txt = post = the gate's re-extraction target), the
     post-derived phys_target, and the admission provenance.
The pure decisions (extract_phys_target_from_ig, win_admission_verdict,
post_ig_reproduces_target, extract_dtk_function) live in
src.search.solver.win_fixture and are unit-tested mwcc-free.

T10d REJECT/FLAG DIRECT-EVIDENCE ADMISSION (plan "Calibration admission
amendment 2", triage-11 window). The reject/flag fixtures are STILL collected
against the live dol target (collection point unchanged), but admission no
longer keys on the checkdiff PRIMARY label (#611's identical-multiset FP
mislabels two of them inline-boundary while open). A reject/flag fixture is
admitted on DIRECT EVIDENCE — both must hold:
  (i)  bl-target multisets byte-identical between current and target (the
       verify-ib REL24 method: `R_PPC_REL24`/`bl` call edges as a multiset);
  (ii) every NORMALIZED truth-gate diff line is register-class (no
       instruction-count, call-shape/selection, or non-sanctioned reloc-symbol
       delta — a pure register reassignment vanishes from the masked space, so
       any surviving normalized-diff line is by construction structural).
Both are `win_fixture.direct_evidence_verdict` (pure, injected
`normalized_structural_lines`, unit-tested). Admitted → freeze (IG dump,
force-phys phys_target, predict_assignments expectations, the T3 filter token);
the record carries BOTH the verdict and the FP-prone primary label. Excluded →
abort loudly with the evidence; for reject_b a structural exclusion flags the
SUBSTITUTION QUESTION (a different real caller-invisible-split function) back to
the orchestrator — the generator never picks a synthetic substitute.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent              # .../tests/fixtures/solver/calibration
AGENT_ROOT = HERE.parents[3]                        # .../tools/melee-agent
MELEE_ROOT = AGENT_ROOT.parents[1]                  # worktree root
sys.path.insert(0, str(AGENT_ROOT))

from src.search.adapters import _acquire_repo_build_lock          # noqa: E402
from src.search.solver.win_fixture import (                       # noqa: E402
    direct_evidence_verdict,
    extract_dtk_function,
    extract_phys_target_from_ig,
    post_ig_reproduces_target,
    win_admission_verdict,
)
from src.search.solver.calibration_whole_solver import (          # noqa: E402
    recompute_verdict_audit,
    run_whole_solver_node_add,
)


def _checkdiff_module():
    """Lazy-load tools/checkdiff.py as a module (it lives outside the package;
    importing the whole module by path keeps the generator's admission verdicts
    on the SAME arbiter — `classify_asm_diff`, `normalized_structural_lines` —
    the live checkdiff path uses)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "checkdiff_for_calibration", MELEE_ROOT / "tools" / "checkdiff.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _classify_asm_diff():
    return _checkdiff_module().classify_asm_diff

MEMORY_DIR = Path("/Users/mike/.claude/projects/-Users-mike-code-melee/memory")

# mn headers a win-fixture historical `.c` transitively depends on (must be
# swapped from the SAME revision — see HEADER-LOCK NOTE). Missing-at-rev files
# are skipped (the helper tolerates absent paths).
WIN_HEADER_FILES = [
    "src/melee/mn/mndiagram.static.h",
    "src/melee/mn/mndiagram2.static.h",
    "src/melee/mn/mndiagram3.static.h",
    "src/melee/mn/mndiagram.h",
]

FIXTURES = [
    dict(name="win_cursorproc", function="mnDiagram_CursorProc",
         unit="melee/mn/mndiagram", kind="win_recovery",
         base_rev="ea5da317c^1", post_rev="ea5da317c",
         alias_source_object_candidates=["gp", "flow"],
         expected="alias_in_top8", header_lock=True),
    dict(name="win_80241e78", function="mnDiagram_80241E78",
         unit="melee/mn/mndiagram", kind="win_recovery",
         base_rev="c1aea2d0c~1", post_rev="c1aea2d0c",
         alias_source_object_candidates=["data", "digit"],
         expected="alias_in_top8", header_lock=True),
    # T10e (orchestrator "Calibration class ruling", A1 rev 2 clause 6,
    # post-mine-rejex): the three reject-confirmations resolve to TWO real
    # exemplars (rejected_a, flagged_c — direct-evidence-admissible register-only
    # partials carrying the class signal) + ONE Class-B plant over a frozen win
    # IG. The OLD mnDiagram* picks (HandleInput-S2 / 80242C0C / CreateStatRow)
    # are RETIRED — all three were direct-evidence-excluded structural in run-4.
    dict(name="reject_a_gm_80164504", function="gm_80164504",
         unit="melee/gm/gm_1601", kind="reject_confirmation",
         base_rev=None, post_rev=None,
         alias_source_object_candidates=[], expected="rejected_a",
         header_lock=False, real_exemplar=True),
    dict(name="flag_c_ftPp_SpecialS_0_Coll", function="ftPp_SpecialS_0_Coll",
         unit="melee/ft/chara/ftNana/ftNn_Init", kind="reject_confirmation",
         base_rev=None, post_rev=None,
         alias_source_object_candidates=[],
         expected="flagged_c_exit4_window_order", header_lock=False,
         real_exemplar=True),
    # rejected_b (Amendment A2): a REAL synthetic-intermediate node in the FROZEN
    # flag_c IG (ftPp_SpecialS_0_Coll). The run-5 source=None plant was INFEASIBLE
    # (no traced node has source=None); A2 re-grounds rejected_b on the provenance
    # KIND — a compiler-synthesized intermediate (implicit-temp / copy-coalesce)
    # has no caller-level C boundary -> rejected_b. ig55 (implicit-temp
    # `addi r55,r54,1`) is runtime (L2(a) passes) + caller-invisible (L2(b)
    # rejects) + enumeration-reachable at hops=2. Reuses the frozen flag_c
    # artifacts (NO recompile) via process_reject_b_from_flag_c.
    dict(name="reject_b_ftPp_SpecialS_0_Coll", function="ftPp_SpecialS_0_Coll",
         unit="melee/ft/chara/ftNana/ftNn_Init", kind="reject_b_synthetic",
         base_rev=None, post_rev=None, source_fixture="flag_c_ftPp_SpecialS_0_Coll",
         alias_source_object_candidates=[], expected="rejected_b",
         header_lock=False, real_exemplar=True),
]

# Catalog snapshot: lever entries the calibration realize step consumes.
CATALOG_SNAPSHOT = {
    "node-add": [
        {"lever": "alias", "tier": "a",
         "note": "T* a = x; route specific reads (CursorProc gp/flow-alias; "
                 "80241E78 loop-tail data_alias)"},
        {"lever": "temp-for-expr", "tier": "a",
         "note": "T t = expr; (80241E78 (f32)digit through base temp)"},
        {"lever": "anchoring", "tier": "a", "note": "second-genuine-use anchoring"},
        {"lever": "per-loop-local", "tier": "a",
         "note": "snap1/saved1, snap2/saved2 per loop"},
        {"lever": "inline-base-cast", "tier": "a",
         "note": "((CardBufEntry*)g)[i].f — NOT a cached pointer-temp"},
    ],
    "edge-add": [{"lever": "statement-hoist-sink", "tier": "b",
                  "note": "move a def/use across the other value's range"}],
    "edge-remove": [{"lever": "statement-hoist-sink", "tier": "b",
                     "note": "move a def/use across the other value's range"}],
    "order": [{"lever": "decl-reorder", "tier": "c",
               "note": "census caveat: order-only rarely byte-eliminates (0/13)"}],
}


@contextmanager
def swapped_paths(swaps: list[tuple[Path, str]]):
    """Byte-exact try/finally restore for one or more files. `swaps` is a list
    of (path, new_text); any path that does not exist on disk is created and
    removed on exit (so a header absent at the historical rev never leaks)."""
    originals: list[tuple[Path, bytes | None]] = []
    try:
        for path, text in swaps:
            originals.append((path, path.read_bytes() if path.exists() else None))
            path.write_text(text, encoding="utf-8")
        yield
    finally:
        for path, original in reversed(originals):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)


def run(argv, cwd, timeout=900):
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=os.environ.copy())
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed (rc={proc.returncode}): {' '.join(map(str, argv))}\n"
            f"{(proc.stderr or proc.stdout or '')[-1500:]}")
    return proc


def git_show(rev: str, path: str) -> str | None:
    """`git show rev:path`; None if the path does not exist at that rev."""
    proc = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=MELEE_ROOT,
                          capture_output=True, text=True, timeout=60)
    return proc.stdout if proc.returncode == 0 else None


def header_swaps_for(rev: str) -> list[tuple[Path, str]]:
    """The mn header (path, text) swaps for a win fixture at `rev`."""
    swaps: list[tuple[Path, str]] = []
    for rel in WIN_HEADER_FILES:
        text = git_show(rev, rel)
        if text is not None:
            swaps.append((MELEE_ROOT / rel, text))
    return swaps


def dump_pcdump(tu: Path, function: str, out: Path,
                keep_obj: Path | None = None) -> None:
    argv = [sys.executable, "-m", "src.cli", "debug", "dump", "local", str(tu),
            "--function", function, "--output", str(out), "--no-cache-sync"]
    if keep_obj is not None:
        argv += ["--keep-obj", str(keep_obj)]
    run(argv, cwd=AGENT_ROOT)


def disassemble_function(obj_path: Path, function: str) -> list[str]:
    """Normalized instruction lines for `function` from a compiled `.o`, via the
    project dtk binary (`build/tools/dtk elf disasm`) — the same disassembler
    checkdiff uses. Output feeds `classify_asm_diff` for the admission verdict."""
    dtk = MELEE_ROOT / "build" / "tools" / "dtk"
    if not dtk.exists():
        raise SystemExit(f"dtk not found at {dtk} — cannot classify win diff.")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        asm = Path(td) / "disasm.s"
        proc = subprocess.run([str(dtk), "elf", "disasm", str(obj_path),
                               str(asm)], capture_output=True, text=True,
                              timeout=120, cwd=MELEE_ROOT)
        if proc.returncode != 0 or not asm.exists():
            raise SystemExit(
                f"dtk disasm failed (rc={proc.returncode}): "
                f"{(proc.stderr or proc.stdout or '')[-400:]}")
        return extract_dtk_function(asm.read_text(encoding="utf-8"), function)


def run_checkdiff_asm(function: str) -> dict:
    """Run a FRESH checkdiff (WITH build) for `function` and return the target
    vs current disassembly pair + the (possibly #611-FP) primary label. This is
    the input to the direct-evidence verdict — it does NOT gate on the primary
    label (amendment 2: the reject/flag admission must not depend on it)."""
    proc = subprocess.run(
        [sys.executable, str(MELEE_ROOT / "tools" / "checkdiff.py"),
         function, "--format", "json"],
        capture_output=True, text=True, timeout=900, cwd=MELEE_ROOT,
        env=os.environ.copy())
    if proc.returncode not in (0, 1) or not (proc.stdout or "").strip():
        raise SystemExit(
            f"[{function}] checkdiff failed (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '')[-500:]} — do NOT freeze.")
    payload = json.loads(proc.stdout)
    classification = payload.get("classification") or {}
    primary = (classification.get("primary")
               if isinstance(classification, dict) else str(classification)
               ) or "unknown"
    target_asm = payload.get("target_asm") or payload.get("reference_asm") or []
    current_asm = payload.get("current_asm") or []
    if not target_asm or not current_asm:
        raise SystemExit(
            f"[{function}] checkdiff returned no target/current asm — "
            f"do NOT freeze.")
    return {"checkdiff_primary": primary,
            "target_asm": list(target_asm),
            "current_asm": list(current_asm),
            "payload": payload}


def collect_phys_target(function: str, unit: str, *,
                        base_pcdump_text: str, checkdiff_payload: dict) -> dict:
    """phys_target := the PRODUCTION target-vs-current register-diff force-phys
    vector (`_derive_force_phys_from_register_diff_lines`, the exact function the
    order-target collector calls), derived from FRESH artifacts (the just-dumped
    base pcdump + the just-run checkdiff asm). Called ONLY after the
    direct-evidence verdict ADMITS the fixture.

    Reachability is collected best-effort via the full order-target collector;
    its forcing-set AUTO-VERIFY step raises on a register whose first-def is in
    the prologue (empty anchor window -> `_parse_force_vector("")`), which is NOT
    a freeze-blocker for a REJECT fixture (the filter rejects the constant node
    BEFORE any landing is attempted; reachability is irrelevant to a reject).
    On that edge case `reachable` is recorded as None (unknown) with the reason.
    """
    import src.cli.debug as debugcli
    from src.mwcc_debug.colorgraph_parser import find_function, parse_hook_events
    from src.mwcc_debug.parser import parse_pcdump

    fns = parse_pcdump(base_pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        raise SystemExit(f"[{function}] not in fresh baseline pcdump — "
                         f"do NOT freeze.")
    pre_pass = fn.last_precolor_pass()
    events_fn = find_function(parse_hook_events(base_pcdump_text), function)
    target_asm = debugcli._checkdiff_asm_lines(checkdiff_payload, "target_asm")
    current_asm = debugcli._checkdiff_asm_lines(checkdiff_payload, "current_asm")
    vector = debugcli._derive_force_phys_from_register_diff_lines(
        target_asm, current_asm, pre_pass, events_fn)
    phys_target = {int(k): int(v) for k, v in vector["force_phys"].items()}
    conflicts = list(vector.get("conflicts", []))

    classification = checkdiff_payload.get("classification") or {}
    primary = (classification.get("primary")
               if isinstance(classification, dict) else str(classification)
               ) or "unknown"

    reachable = None
    reachable_note = "not-collected"
    try:
        inputs = debugcli._collect_order_target_inputs(
            function=function, unit=unit, class_id=0,
            melee_root=MELEE_ROOT, checkdiff_timeout=120.0)
        reachable = bool(inputs.forced_class_clean) and not inputs.phys_conflicts
        reachable_note = "forcing-set-verified"
        # Prefer the collector's phys_target if it agrees (identical derivation).
        if inputs.phys_target:
            phys_target = {int(k): int(v) for k, v in inputs.phys_target.items()}
    except Exception as exc:        # empty-anchor force-vector edge case et al.
        reachable_note = (f"forcing-set auto-verify unavailable "
                          f"({type(exc).__name__}: {str(exc)[:120]}); "
                          f"irrelevant to a reject fixture")
    return {
        "checkdiff_primary": primary,
        "phys_target": phys_target,
        "phys_conflicts": conflicts,
        "reachable": reachable,
        "reachable_note": reachable_note,
    }


def process(fx: dict) -> dict:
    """Dispatch on fixture kind: win fixtures take the SELF-CONTAINED pre/post
    path (T10c redesign); reject/flag REAL exemplars take the direct-evidence
    dol-target path PLUS the T10e whole-solver assertion; the rejected_b
    synthetic-intermediate fixture reuses a frozen flag-fixture IG (Amendment A2);
    the (retired) Class-B plant takes the win-IG plant path."""
    if fx["kind"] == "win_recovery":
        return process_win(fx)
    if fx["kind"] == "plant_rejected_b":
        return process_plant_rejected_b(fx)
    if fx["kind"] == "reject_b_synthetic":
        return process_reject_b_from_flag_c(fx)
    return process_reject(fx)


def process_win(fx: dict) -> dict:
    """SELF-CONTAINED win fixture (T10c). Compile BOTH the pre (base) and post
    sources in the worktree context (header-locked); admit on the PRE-vs-POST
    object diff being FULLNORM-0; collect phys_target from the POST IG's actual
    coloring; verify the surrogate reproduces it at G1=100%. Freeze BOTH IGs."""
    wdir = HERE / fx["name"]
    wdir.mkdir(parents=True, exist_ok=True)
    tu = MELEE_ROOT / "src" / f"{fx['unit']}.c"
    rel_tu = f"src/{fx['unit']}.c"
    fn = fx["function"]

    base_src = git_show(fx["base_rev"], rel_tu)
    if base_src is None:
        raise SystemExit(f"[{fx['name']}] base rev {fx['base_rev']!r} "
                         f"has no {rel_tu} — do NOT freeze.")
    post_src = git_show(fx["post_rev"], rel_tu)
    if post_src is None:
        raise SystemExit(f"[{fx['name']}] post rev {fx['post_rev']!r} "
                         f"has no {rel_tu} — do NOT freeze.")
    if fn not in base_src or fn not in post_src:
        raise SystemExit(f"[{fx['name']}] {fn} missing from base/post source "
                         f"— do NOT freeze.")
    (wdir / "base.c").write_text(base_src, encoding="utf-8")
    (wdir / "post_win.c").write_text(post_src, encoding="utf-8")

    pre_obj = wdir / f".{fn}.pre.{os.getpid()}.o"
    post_obj = wdir / f".{fn}.post.{os.getpid()}.o"
    try:
        # ---- PRE: solver-input IG + object (header-locked) -----------------
        base_swaps = [(tu, base_src)] + header_swaps_for(fx["base_rev"])
        with swapped_paths(base_swaps):
            dump_pcdump(tu, fn, wdir / "base.pcdump.txt", keep_obj=pre_obj)
        # ---- POST: gate re-extraction IG + object (header-locked) ----------
        post_swaps = [(tu, post_src)] + header_swaps_for(fx["post_rev"])
        with swapped_paths(post_swaps):
            dump_pcdump(tu, fn, wdir / "post_win.pcdump.txt", keep_obj=post_obj)

        # ---- Admission: PRE-vs-POST object diff is FULLNORM-0 (pure coloring)
        classify = _classify_asm_diff()
        pre_asm = disassemble_function(pre_obj, fn)
        post_asm = disassemble_function(post_obj, fn)
        if not pre_asm or not post_asm:
            raise SystemExit(f"[{fx['name']}] empty disasm for {fn} "
                             f"(pre={len(pre_asm)}, post={len(post_asm)}) — "
                             f"do NOT freeze.")
        verdict = win_admission_verdict(pre_asm, post_asm,
                                        classify_asm_diff=classify)
        if not verdict["admitted"]:
            raise SystemExit(
                f"[{fn}] PRE-vs-POST diff NOT register-only (FULLNORM-0): "
                f"primary={verdict['primary']!r}, "
                f"normalized_diff_lines={verdict['normalized_diff_lines']} "
                f"(>0 = structural). The win is not a pure-coloring delta in "
                f"this context — do NOT freeze.")
    finally:
        pre_obj.unlink(missing_ok=True)
        post_obj.unlink(missing_ok=True)

    # ---- phys_target := POST coloring; verify the surrogate reaches it ------
    post_text = (wdir / "post_win.pcdump.txt").read_text(encoding="utf-8")
    phys_target = extract_phys_target_from_ig(post_text, fn, class_id=0)
    if not phys_target:
        raise SystemExit(f"[{fn}] empty post phys_target (no non-spill nodes) "
                         f"— do NOT freeze.")
    all_match, g1_rate, _rm = post_ig_reproduces_target(
        post_text, fn, phys_target, class_id=0)
    if not (all_match and g1_rate == 1.0):
        raise SystemExit(
            f"[{fn}] surrogate does NOT reproduce the post coloring "
            f"(all_match={all_match}, post G1={g1_rate:.4f}); the §3 "
            f"actual-vs-target check would fail — do NOT freeze.")

    record = {
        "name": fx["name"], "function": fn, "unit": fx["unit"],
        "class_id": 0, "kind": fx["kind"],
        # phys_target is POST-DERIVED (the win's actual coloring), not dol.
        "phys_target": {str(k): v for k, v in phys_target.items()},
        "reachable": True,           # FULLNORM-0 admitted + surrogate reproduces
        "expected": {"outcome": fx["expected"]},
        "alias": {"source_object_candidates": fx["alias_source_object_candidates"],
                  "lever": "alias"},
        "admission": {
            "mode": "pre_vs_post_fullnorm0",
            "primary": verdict["primary"],
            "normalized_diff_lines": verdict["normalized_diff_lines"],
            "strict_register_only": verdict["strict_register_only"],
            "pre_instr_lines": verdict["pre_lines"],
            "post_instr_lines": verdict["post_lines"],
            "base_rev": fx["base_rev"], "post_rev": fx["post_rev"],
        },
        "post_g1_rate": g1_rate,
        "phys_target_source": "post_win.pcdump.txt",
    }
    (wdir / "fixture.json").write_text(json.dumps(record, indent=2),
                                       encoding="utf-8")
    return record


# T3 filter-summary schema token per fixture (the bare key the §1.5 filter
# emits; the richer `expected` descriptor carries the exit-4/window-order tail).
EXPECTED_FILTER_TOKEN = {
    "rejected_a": "rejected_a",
    "rejected_b": "rejected_b",
    "flagged_c_exit4_window_order": "flagged_c",
}


def _phys_target_expectations(base_pcdump_text: str, function: str,
                              class_id: int = 0) -> dict:
    """T2-binding expectations: run `predict_assignments` (the surrogate) over
    the frozen BASE IG and record the predicted coloring + G1 — NEVER copy
    expected registers from narrative text. The §1.5 fixtures' T11 role is to
    REACH THE FILTER, so the predicted base coloring is recorded as provenance
    (the predictor on the solver-input IG), not asserted equal to phys_target."""
    from src.mwcc_debug import tiebreak as tb
    ig = tb.load_ig(base_pcdump_text, function, class_id=class_id)
    if ig is None:
        raise SystemExit(f"[{function}] no COLORGRAPH class={class_id} in base "
                         f"pcdump — cannot derive expectations; do NOT freeze.")
    g1 = tb.validate_g1(ig, function)
    predicted = tb.predict_assignments(ig)
    return {
        "predicted_base_coloring": {str(k): int(v) for k, v in predicted.items()},
        "base_g1_rate": g1.rate,
    }


def _explain_report(pcdump_text: str, function: str, source_text: str,
                    source_file: str, ig):
    """The frozen source-attribution bridge: explain_virtuals over the dumped
    pre-coloring pcode for EVERY IG node (ig_idx N == virtual rN, the production
    mapping). Feeds probe.derive_probe_context with no oracle."""
    from src.mwcc_debug.virtual_attribution import explain_virtuals
    return explain_virtuals(pcdump_text, function, virtuals=sorted(ig.nodes),
                            source_text=source_text, source_file=source_file)


def _freeze_bridge(report, path: Path) -> dict:
    """Serialize the explain_virtuals report to JSON (the frozen bridge the
    calibration test reloads to reconstruct ProbeContext without recompiling).
    Only the fields probe.py reads (ig_idx -> source.name/expression/
    first_def.opcode) are needed, but we freeze the whole to_dict for audit."""
    data = report.to_dict()
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data


def _pick_target_ig(report, ig, phys_target: dict, expected: str):
    """Identify the IG node carrying the class signal AND reachable by the
    production enumeration's implicated set:
      rejected_a  -> a li/lis-constant first-def node in the IMPLICATED set of
                     the contested residual (1-hop, widened to 2-hop per spec
                     open Q1, cap 64); the production enumerate_single targets
                     exactly this set, so the constant node must be in it for the
                     whole-solver to GENERATE a candidate against it.
      flagged_c   -> a contested node that is part of the window-shift residual
                     (callee-save observed->desired uniform delta).
    Returns (target_ig, signal_detail) — signal_detail carries the implicated
    `hops` the whole-solver assertion must use. Raises SystemExit if no
    implicated node carries the signal (do NOT freeze a signal-absent fixture)."""
    from src.search.solver import probe
    from src.search.solver.enumerate import implicated_nodes
    contested = sorted(int(k) for k in phys_target)
    pt_int = {int(k): v for k, v in phys_target.items()}
    if expected == "rejected_a":
        # Search the implicated set the production enumeration actually targets,
        # widening 1-hop -> 2-hop (the constant node is often 2-hop from the
        # runtime residual it coalesces near). The chosen hops is RECORDED so the
        # whole-solver assertion uses the identical EnumConfig.
        for hops in (1, 2):
            impl = implicated_nodes(ig, pt_int, hops=hops, cap=64)
            for ig_idx in sorted(impl):
                op = probe.first_def_opcode_of(report, ig_idx)
                if op and op.strip().lower() in ("li", "lis"):
                    node = ig.nodes.get(ig_idx)
                    return ig_idx, {
                        "first_def_opcode": op,
                        "implicated_hops": hops,
                        "observed_reg": node.observed_reg if node else None,
                        "desired_reg": (phys_target.get(str(ig_idx))
                                        if str(ig_idx) in phys_target
                                        else phys_target.get(ig_idx)),
                        "contested_residual": contested,
                    }
        raise SystemExit(
            f"[{report.function}] no li/lis-constant first-def node in the "
            f"1-hop OR 2-hop implicated set of the contested residual "
            f"{contested} (rejected_a signal NOT enumeration-reachable); "
            f"do NOT freeze.")
    if expected == "flagged_c_exit4_window_order":
        # The whole-target window-shift signal (probe.is_window_order_residual)
        # must hold; pick any contested callee-save node as the flag target.
        if not probe.is_window_order_residual(ig, {int(k): v for k, v
                                                   in phys_target.items()}):
            raise SystemExit(
                f"[{report.function}] phys_target is NOT a uniform callee-save "
                f"window-shift residual — flagged_c signal ABSENT; do NOT freeze.")
        ig_idx = contested[0]
        node = ig.nodes.get(ig_idx)
        return ig_idx, {
            "observed_reg": node.observed_reg if node else None,
            "desired_reg": phys_target.get(str(ig_idx),
                                           phys_target.get(ig_idx)),
            "window_order_residual": True,
        }
    if expected == "rejected_b":
        # Amendment A2: rejected_b targets a RUNTIME compiler-synthesized
        # intermediate with NO source-level variable (implicit-temp /
        # copy/coalesce-product) that is enumeration-reachable in the implicated
        # set. RUNTIME (first-def NOT li/lis) is required so L2(a) passes and the
        # verdict is genuinely rejected_b (not rejected_a). Search 1-hop -> 2-hop
        # (these synthetic temps sit near the contested residual).
        for hops in (1, 2):
            impl = implicated_nodes(ig, pt_int, hops=hops, cap=64)
            for ig_idx in sorted(impl):
                src = probe.source_attr_of(report, ig_idx)
                if src is None:
                    continue
                kind = getattr(src, "kind", None)
                if kind not in ("implicit-temp", "copy/coalesce-product"):
                    continue
                # caller-invisible by KIND, and runtime (not a li/lis constant)?
                if probe.caller_visible_source_of(src):
                    continue                       # defensive (kind gate failed)
                op = probe.first_def_opcode_of(report, ig_idx)
                if op and op.strip().lower() in ("li", "lis"):
                    continue                       # would be rejected_a, not _b
                node = ig.nodes.get(ig_idx)
                # require the node be enumeration-targetable (has a use-set family)
                if node is None or not node.neighbors:
                    continue
                return ig_idx, {
                    "source_kind": kind,
                    "first_def_opcode": op,
                    "implicated_hops": hops,
                    "observed_reg": node.observed_reg if node else None,
                    "contested_residual": contested,
                }
        raise SystemExit(
            f"[{report.function}] no RUNTIME synthetic-intermediate "
            f"(implicit-temp/copy-coalesce, non-li/lis) node in the 1-hop OR "
            f"2-hop implicated set (rejected_b signal NOT enumeration-reachable "
            f"per Amendment A2); do NOT freeze.")
    raise SystemExit(f"unexpected expected={expected!r}")


def _whole_solver_record(ig, phys_target: dict, report, *, target_ig: int,
                         expected: str, hops: int = 1) -> dict:
    """Run the PRODUCTION enumerate+filter (calibration_whole_solver) over the
    frozen IG + bridge and record the whole-solver verdict (A1 rev 2): the
    enumeration GENERATES node-add candidates for target_ig and the production
    filter DROPS them (rejected token) / QUARANTINES them (flagged_c), with the
    recompute-equality audit. Also runs the BROKEN-FILTER control (§3) and
    asserts it FAILS the gate. `hops` = the implicated-set hop distance at which
    the signal node is reachable (1, widened to 2 per spec open Q1)."""
    from src.search.solver import probe as _probe
    from src.search.solver.calibration_whole_solver import (
        broken_filter_admit_everything,
    )
    from src.search.solver.enumerate import EnumConfig
    cfg = EnumConfig(implicated_hops=hops)
    pt_int = {int(k): v for k, v in phys_target.items()}
    window_residual = _probe.is_window_order_residual(ig, pt_int)
    if expected in ("rejected_a", "rejected_b"):
        v = run_whole_solver_node_add(
            ig, pt_int, target_ig=target_ig, report=report,
            window_residual=window_residual, expected_reject_token=expected,
            config=cfg)
        token, ok = expected, (
            v.candidates_for_target > 0
            and v.rejected_count == v.candidates_for_target
            and v.survived_in_full == 0 and v.survived_in_partial == 0
            and v.survived_in_window == 0)
        audit = recompute_verdict_audit(ig, report, target_ig=target_ig,
                                        window_residual=window_residual,
                                        config=cfg)
        audit_ok = (audit["reasons"] == [expected] and audit["admits"] == 0)
    else:  # flagged_c
        v = run_whole_solver_node_add(
            ig, pt_int, target_ig=target_ig, report=report,
            window_residual=window_residual, expected_flag="flagged_c",
            config=cfg)
        token, ok = "flagged_c", (
            v.candidates_for_target > 0 and v.flagged_count > 0
            and v.flagged_count == v.survived_in_window
            and v.survived_in_full == 0 and v.survived_in_partial == 0)
        audit = recompute_verdict_audit(ig, report, target_ig=target_ig,
                                        window_residual=window_residual,
                                        config=cfg)
        audit_ok = "flagged_c" in audit["flags"]

    # §3 BROKEN-FILTER control: admit-everything must let target candidates
    # survive into the hit buckets (the clean-reject/flag gate predicate FAILS).
    _hard_reject = expected in ("rejected_a", "rejected_b")
    bf = run_whole_solver_node_add(
        ig, pt_int, target_ig=target_ig, report=report,
        window_residual=window_residual,
        expected_reject_token=(expected if _hard_reject else None),
        expected_flag=(None if _hard_reject else "flagged_c"),
        filter_fn=broken_filter_admit_everything, config=cfg)
    bf_survivors = (bf.survived_in_full + bf.survived_in_partial
                    + bf.survived_in_window)
    if _hard_reject:
        # The clean-reject gate requires the production filter to REJECT every
        # target candidate (0 admitted by the enum filter). Under admit-
        # everything, the enum filter ADMITS them all -> the clean-reject
        # predicate (0 admitted) FAILS. (Survivors are unreliable here: a
        # constant/synthetic node-add is non-productive, so it leaves no hit even
        # when admitted — the admitted-count is the faithful signal.)
        broken_filter_breaks_gate = (
            bf.target_candidates_admitted_by_enum_filter
            == bf.candidates_for_target
            and bf.candidates_for_target > 0)
    else:
        # flag_c: under admit-everything the candidates are NOT quarantined to
        # the window bucket (the gate predicate flagged==window FAILS).
        broken_filter_breaks_gate = bf.survived_in_window != bf.candidates_for_target

    return {
        "expected_token": token,
        "target_ig": target_ig,
        "implicated_hops": hops,
        "candidates_for_target": v.candidates_for_target,
        "rejected_count": v.rejected_count,
        "flagged_count": v.flagged_count,
        "survived_in_full": v.survived_in_full,
        "survived_in_partial": v.survived_in_partial,
        "survived_in_window": v.survived_in_window,
        "production_filter_token": v.reject_token,
        "whole_solver_reject_assertion_ok": bool(ok),
        "recompute_equality_audit_ok": bool(v.audit_equal and audit_ok),
        "recompute_audit": {"reasons": audit["reasons"],
                            "flags": audit["flags"],
                            "admits": audit["admits"],
                            "candidates": audit["candidates"]},
        "broken_filter_control": {
            "survivors_under_admit_everything": bf_survivors,
            "breaks_gate": bool(broken_filter_breaks_gate)},
        # Full production enumeration trace frozen for audit (A1 rev 2 §7).
        "enumeration_trace": {
            "filter_counts": dict(v.enum_result.filter_counts),
            "evals_per_kind": dict(v.enum_result.evals_per_kind),
            "full_hits": len(v.enum_result.full_hits),
            "partial_hits": len(v.enum_result.partial_hits),
            "window_order_hits": len(v.enum_result.window_order_hits),
            "truncated": v.enum_result.truncated,
            "last_kind": v.enum_result.last_kind},
    }


WIN_FIXTURE_DIRS = ["win_cursorproc", "win_80241e78"]
WIN_FIXTURE_FUNCS = {"win_cursorproc": "mnDiagram_CursorProc",
                     "win_80241e78": "mnDiagram_80241E78"}


def process_plant_rejected_b(fx: dict) -> dict:
    """Class-B plant over a frozen win pre-IG (A1 rev 2 §1-2).

    The plant is an ORDINARY node-add targeting a virtual whose FROZEN
    attribution has source=None (intra-inline / untraced -> caller_visible_source
    False -> rejected_b). The ProbeContext is derived by the PRODUCTION probe.py
    over the frozen raw artifacts (NO oracle); the plant is forced-injected into
    the production enumerate+filter path; the harness recomputes passes_1_5_filter
    over the same derived context and asserts the verdict equals `rejected_b`
    (A1 rev 2 §1 audit). Paired-trace invariance (§4) + broken-filter control
    (§3) are recorded.

    PRECONDITION: a win IG must contain a source=None virtual. If NEITHER frozen
    win IG has one (the mine-rejex NEGATIVE COVERAGE for Class B — every traced
    first-def yields a non-empty expression), the plant CANNOT be instantiated on
    a genuine source=None node. Per the brief, that is REPORTED (do NOT fabricate
    a source=None node) — it forces a spec-relax decision to the orchestrator.
    This function probes BOTH wins, records the negative coverage, and ABORTS."""
    from src.mwcc_debug import tiebreak as tb
    from src.search.solver import probe

    probe_results = {}
    plant_site = None      # (win_name, function, ig_idx) of the first source=None
    for win_name in WIN_FIXTURE_DIRS:
        wdir = HERE / win_name
        pcdump_p = wdir / "base.pcdump.txt"
        src_p = wdir / "base.c"
        if not pcdump_p.exists() or not src_p.exists():
            probe_results[win_name] = {"error": "frozen win artifacts missing"}
            continue
        fn = WIN_FIXTURE_FUNCS[win_name]
        pcdump_text = pcdump_p.read_text(encoding="utf-8")
        src_text = src_p.read_text(encoding="utf-8")
        none_nodes = {}
        total = 0
        for class_id in (0, 1):
            ig = tb.load_ig(pcdump_text, fn, class_id=class_id)
            if ig is None:
                continue
            report = _explain_report(pcdump_text, fn, src_text, str(src_p), ig)
            for ig_idx in sorted(ig.nodes):
                total += 1
                if probe.source_object_of(report, ig_idx) is None:
                    none_nodes.setdefault(class_id, []).append(ig_idx)
                    if plant_site is None:
                        plant_site = (win_name, fn, class_id, ig_idx)
        probe_results[win_name] = {
            "function": fn,
            "ig_nodes_probed": total,
            "source_none_nodes": none_nodes,
            "source_none_count": sum(len(v) for v in none_nodes.values()),
        }

    if plant_site is not None:
        # A genuine source=None node EXISTS — build the plant (no-oracle,
        # recompute-equality audit, paired-trace invariance, broken-filter
        # control). [This branch is currently UNREACHED — both wins are 0/0 —
        # but is implemented so a future win IG with a source=None node freezes
        # the plant automatically rather than re-reporting the gap.]
        return _build_rejected_b_plant(fx, plant_site, probe_results)

    # NEGATIVE COVERAGE (mine-rejex Class B, reproduced): no source=None node in
    # either frozen win IG. Do NOT fabricate one. REPORT the spec-relax question.
    raise SystemExit(
        "[reject_b_plant] CLASS-B PLANT INFEASIBLE — no source=None virtual in "
        "EITHER frozen win IG (probe: "
        + json.dumps({k: {"function": v.get("function"),
                          "source_none_count": v.get("source_none_count"),
                          "ig_nodes_probed": v.get("ig_nodes_probed")}
                      for k, v in probe_results.items()})
        + "). Every traced first-def yields a non-empty expression -> "
        "source_object_of != None -> caller_visible_source True -> the filter "
        "never reaches the rejected_b branch via a real win-IG node. Per A1 "
        "rev 2 §2 + the task brief, this is a SPEC-RELAX decision for the "
        "orchestrator (NOT a fabricated source=None node). The pure plant "
        "machinery (no-oracle derivation, broken-filter control, paired-trace) "
        "is built + unit-tested in test_calibration_t10e.py; only the FROZEN "
        "instantiation over a real win IG is blocked.")


def _build_rejected_b_plant(fx: dict, plant_site, probe_results: dict) -> dict:
    """Freeze the Class-B plant on a real source=None win-IG node (A1 rev 2
    §1-7). UNREACHED in the current corpus (both wins 0/0 source=None); kept for
    a future qualifying win IG. The plant: an ordinary node-add targeting the
    source=None virtual, ProbeContext via production probe over the frozen
    artifacts, the recompute-equality audit, paired-trace invariance vs the
    unplanted baseline, and the broken-filter control."""
    from src.mwcc_debug import tiebreak as tb
    from src.search.solver.calibration_whole_solver import (
        broken_filter_admit_everything, build_probe_ctx_fn,
        paired_trace_invariance, recompute_verdict_audit,
    )
    from src.search.solver.enumerate import EnumConfig, enumerate_single
    from src.search.solver.types import Perturbation, PerturbationKind
    from src.search.solver.validity import passes_1_5_filter

    win_name, fn, class_id, target_ig = plant_site
    wdir_win = HERE / win_name
    pcdump_text = (wdir_win / "base.pcdump.txt").read_text(encoding="utf-8")
    src_text = (wdir_win / "base.c").read_text(encoding="utf-8")
    ig = tb.load_ig(pcdump_text, fn, class_id=class_id)
    report = _explain_report(pcdump_text, fn, src_text,
                             str(wdir_win / "base.c"), ig)

    # phys_target := contest the plant target (the win's POST phys_target keys
    # are post-IG; for the plant we only need target_ig contested so the
    # generator targets it). Use its observed reg as a "wrong" desired to keep
    # it a genuine contested node, but the FILTER rejects before any landing.
    node = ig.nodes[target_ig]
    pt = {target_ig: node.observed_reg}
    cfg = EnumConfig()
    probe_ctx_fn = build_probe_ctx_fn(ig, report, window_residual=False)

    # The plant candidate (ordinary node-add; NO oracle fields).
    nbrs = sorted(n for n in node.neighbors if n in ig.nodes)
    plant = Perturbation(PerturbationKind.NODE_ADD, target_ig=target_ig,
                         use_set=(nbrs[0],) if nbrs else (), new_ig=999_999,
                         position="after", interfere_original=True)

    # No-oracle audit: recompute passes_1_5_filter over the derived context.
    plant_ctx = probe_ctx_fn(plant)
    plant_verdict = passes_1_5_filter(plant, plant_ctx)
    audit = recompute_verdict_audit(ig, report, target_ig=target_ig,
                                    window_residual=False)

    # Baseline-vs-planted enumeration (paired-trace). Baseline contests a
    # DIFFERENT node so the plant target appears only in the planted run.
    other = next((i for i in sorted(ig.nodes) if i != target_ig), target_ig)
    baseline = enumerate_single(ig, {other: ig.nodes[other].observed_reg},
                                config=cfg, filter_fn=passes_1_5_filter,
                                probe_ctx_fn=probe_ctx_fn, kinds=("node-add",))
    planted = enumerate_single(ig, {other: ig.nodes[other].observed_reg,
                                    target_ig: node.observed_reg},
                               config=cfg, filter_fn=passes_1_5_filter,
                               probe_ctx_fn=probe_ctx_fn, kinds=("node-add",))
    paired = paired_trace_invariance(baseline, planted, plant_target_ig=target_ig)

    # Broken-filter control.
    bf = enumerate_single(ig, pt, config=cfg,
                          filter_fn=broken_filter_admit_everything,
                          probe_ctx_fn=probe_ctx_fn, kinds=("node-add",))

    wdir = HERE / fx["name"]
    wdir.mkdir(parents=True, exist_ok=True)
    _freeze_bridge(report, wdir / "bridge.json")
    record = {
        "name": fx["name"], "kind": fx["kind"], "real_exemplar": False,
        "plant_over_win": win_name, "function": fn, "class_id": class_id,
        "target_ig": target_ig,
        "expected": {"outcome": "rejected_b", "filter_token": "rejected_b"},
        "no_oracle_audit": {
            "plant_verdict_reason": plant_verdict.reason,
            "recompute_equal": plant_verdict.reason == "rejected_b",
            "audit_reasons": audit["reasons"]},
        "paired_trace_invariance": {
            "invariant": paired.invariant,
            "non_plant_identities_unchanged": paired.non_plant_identities_unchanged,
            "non_plant_outcomes_unchanged": paired.non_plant_outcomes_unchanged,
            "truncated_unchanged": paired.truncated_unchanged},
        "broken_filter_control": {
            "survivors_under_admit_everything": (
                len([r for r in bf.full_hits + bf.partial_hits
                     if r["perturbation"].target_ig == target_ig]))},
        "probe_results": probe_results,
    }
    (wdir / "fixture.json").write_text(json.dumps(record, indent=2),
                                       encoding="utf-8")
    return record


def _reload_report_from_bridge(bridge: dict):
    """Rebuild a REAL VirtualAttributionReport from a frozen bridge.json so it
    round-trips through `report.to_dict()` (used by _freeze_bridge) AND is read by
    the production probe.py (kind/name/source_file/source_line/first_def.opcode).
    Reconstructs the frozen dataclasses field-for-field (unknown keys ignored)."""
    from src.mwcc_debug.virtual_attribution import (
        InstructionSite, InterfererAttribution, PairInterference,
        SourceAttribution, VirtualAttribution, VirtualAttributionReport,
    )

    def _site(d):
        if not d:
            return None
        return InstructionSite(
            pass_name=d.get("pass_name", ""), block_idx=d.get("block_idx", -1),
            instr_idx=d.get("instr_idx", -1), opcode=d.get("opcode", ""),
            operands=d.get("operands", ""))

    def _source(d):
        if d is None:
            return None
        return SourceAttribution(
            kind=d.get("kind", ""), confidence=d.get("confidence", ""),
            name=d.get("name"), type=d.get("type"),
            source_file=d.get("source_file"), source_line=d.get("source_line"),
            source_col=d.get("source_col"), expression=d.get("expression"),
            base_virtual=d.get("base_virtual"), base_var=d.get("base_var"),
            base_confidence=d.get("base_confidence"),
            field_offset=d.get("field_offset"), field_name=d.get("field_name"),
            first_def=_site(d.get("first_def")),
            call_symbol=d.get("call_symbol"),
            copy_chain=tuple(d.get("copy_chain") or ()),
            use_sites=tuple(_site(s) for s in (d.get("use_sites") or ())))

    def _interferer(d):
        return InterfererAttribution(
            virtual=d.get("virtual"), assigned_reg=d.get("assigned_reg"),
            source=_source(d.get("source")))

    def _va(d):
        lr = d.get("live_range")
        return VirtualAttribution(
            virtual=d.get("virtual"), status=d.get("status", ""),
            class_id=d.get("class_id"), ig_idx=d.get("ig_idx"),
            assigned_reg=d.get("assigned_reg"),
            live_range=tuple(lr) if lr else None,
            live_blocks=tuple(d.get("live_blocks") or ()),
            use_count=d.get("use_count", 0),
            first_occurrence=_site(d.get("first_occurrence")),
            last_occurrence=_site(d.get("last_occurrence")),
            source=_source(d.get("source")),
            interferers=tuple(_interferer(i) for i in (d.get("interferers") or ())),
            note=d.get("note"))

    def _pair(d):
        return PairInterference(
            virtual=d.get("virtual"), other_virtual=d.get("other_virtual"),
            colorgraph_interference=d.get("colorgraph_interference", False),
            live_overlap=d.get("live_overlap", False),
            same_assigned_reg=d.get("same_assigned_reg"),
            reason=d.get("reason", ""))

    return VirtualAttributionReport(
        function=bridge.get("function", ""),
        virtuals=tuple(_va(v) for v in bridge.get("virtuals", ())),
        pair_interferences=tuple(_pair(p) for p
                                 in bridge.get("pair_interferences", ())))


def process_reject_b_from_flag_c(fx: dict) -> dict:
    """Amendment A2 rejected_b: freeze on a REAL synthetic-intermediate node in an
    ALREADY-frozen flag-fixture IG (NO recompile — the artifacts exist on master).

    The run-5 source=None plant was infeasible (every traced node carries an
    expression). A2 re-grounds rejected_b on the provenance KIND: a
    compiler-synthesized intermediate (implicit-temp / copy-coalesce) has no
    caller-level C expression an alias can split -> caller_visible_source False ->
    rejected_b. We reuse the frozen `source_fixture` IG + bridge, pick a RUNTIME
    synthetic node via _pick_target_ig(expected='rejected_b') (runtime so L2(a)
    passes and the verdict is rejected_b, not rejected_a), run the production
    whole-solver assertion + recompute audit + broken-filter control, and freeze a
    self-contained `reject_b_<fn>` dir. ABORTS LOUDLY if the source fixture is
    absent or no qualifying node exists (never a placeholder)."""
    from src.mwcc_debug import tiebreak as tb

    wdir = HERE / fx["name"]
    src_dir = HERE / fx["source_fixture"]
    src_pcdump = src_dir / "base.pcdump.txt"
    src_bridge = src_dir / "bridge.json"
    src_fixture = src_dir / "fixture.json"
    for p in (src_pcdump, src_bridge, src_fixture):
        if not p.exists():
            raise SystemExit(
                f"[{fx['name']}] source fixture artifact {p} missing — the "
                f"flag_c fixture must be frozen first; do NOT freeze.")
    wdir.mkdir(parents=True, exist_ok=True)

    src_rec = json.loads(src_fixture.read_text())
    fn = fx["function"]
    if src_rec.get("function") != fn:
        raise SystemExit(
            f"[{fx['name']}] source fixture function {src_rec.get('function')!r} "
            f"!= {fn!r} — do NOT freeze.")
    class_id = src_rec.get("class_id", 0)
    pcdump_text = src_pcdump.read_text(encoding="utf-8")
    ig = tb.load_ig(pcdump_text, fn, class_id=class_id)
    if ig is None:
        raise SystemExit(f"[{fx['name']}] source pcdump has no COLORGRAPH for "
                         f"{fn} — do NOT freeze.")
    report = _reload_report_from_bridge(json.loads(src_bridge.read_text()))

    # Reuse the source fixture's REAL phys_target (the flag_c window residual).
    phys_target_s = {str(k): v for k, v in src_rec["phys_target"].items()}
    target_ig, signal_detail = _pick_target_ig(report, ig, phys_target_s,
                                               "rejected_b")
    hops = signal_detail.get("implicated_hops", 1)
    whole_solver = _whole_solver_record(ig, phys_target_s, report,
                                        target_ig=target_ig,
                                        expected="rejected_b", hops=hops)
    if not whole_solver["whole_solver_reject_assertion_ok"]:
        raise SystemExit(
            f"[{fn}] WHOLE-SOLVER rejected_b assertion FAILED for ig={target_ig} "
            f"({whole_solver}) — do NOT freeze.")
    if not whole_solver["recompute_equality_audit_ok"]:
        raise SystemExit(
            f"[{fn}] recompute-equality audit FAILED "
            f"({whole_solver['recompute_audit']}) — do NOT freeze.")
    if not whole_solver["broken_filter_control"]["breaks_gate"]:
        raise SystemExit(
            f"[{fn}] BROKEN-FILTER control did NOT break the gate (§3) — do NOT "
            f"freeze.")

    # Self-contained freeze: copy the source IG + bridge, write a new fixture.json
    # (so the CI fixture-test loader reloads it identically to the other reals).
    (wdir / "base.pcdump.txt").write_text(pcdump_text, encoding="utf-8")
    _freeze_bridge(report, wdir / "bridge.json")
    matched_fn_span = src_rec.get("matched_fn_span")
    record = {
        "name": fx["name"], "function": fn, "unit": fx["unit"],
        "class_id": class_id, "kind": fx["kind"],
        "real_exemplar": fx.get("real_exemplar", True),
        "reused_from": fx["source_fixture"],
        "phys_target": phys_target_s,
        "reachable": src_rec.get("reachable"),
        "expected": {"outcome": fx["expected"],
                     "filter_token": EXPECTED_FILTER_TOKEN[fx["expected"]]},
        "target_ig": target_ig,
        "class_signal": signal_detail,
        "whole_solver": whole_solver,
        "bridge_file": "bridge.json",
        "matched_fn_span": matched_fn_span,
        "provenance": {
            "amendment": "A2",
            "rule": "caller-invisible iff synthetic-intermediate KIND "
                    "(implicit-temp / copy-coalesce / nameless-lineless first-def)",
            "target_kind": signal_detail.get("source_kind"),
            "target_first_def_opcode": signal_detail.get("first_def_opcode"),
            "note": "reuses the frozen flag_c IG/bridge (no recompile); the "
                    "synthetic node is genuinely caller-invisible (no source "
                    "variable an alias can split).",
        },
        "alias": {"source_object_candidates": [], "lever": None},
    }
    (wdir / "fixture.json").write_text(json.dumps(record, indent=2),
                                       encoding="utf-8")
    return record


def process_reject(fx: dict) -> dict:
    """Reject/flag fixture under the DIRECT-EVIDENCE admission (amendment 2).

    Collected against the live dol target (UNCHANGED collection point), but the
    admission no longer keys on the checkdiff PRIMARY label (#611 leaves it FP).
    Instead: (i) bl-target multiset parity (verify-ib REL24 method) AND (ii)
    every normalized truth-gate diff line register-class. Admitted → freeze
    (IG dump, force-phys phys_target, predict_assignments expectations, the T3
    filter token). Excluded → abort loudly with the direct-evidence record."""
    wdir = HERE / fx["name"]
    wdir.mkdir(parents=True, exist_ok=True)
    tu = MELEE_ROOT / "src" / f"{fx['unit']}.c"

    base_src = tu.read_text(encoding="utf-8")
    if fx["function"] not in base_src:
        raise SystemExit(f"[{fx['name']}] {fx['function']} not in worktree "
                         f"source — do NOT freeze.")
    (wdir / "base.c").write_text(base_src, encoding="utf-8")

    norm_lines_fn = _checkdiff_module().normalized_structural_lines
    with swapped_paths([(tu, base_src)]):
        dump_pcdump(tu, fx["function"], wdir / "base.pcdump.txt")
        cd = run_checkdiff_asm(fx["function"])
        verdict = direct_evidence_verdict(
            cd["target_asm"], cd["current_asm"],
            normalized_structural_lines=norm_lines_fn)
        if not verdict["admitted"]:
            # Honest exclusion: record the evidence for the provenance, then
            # abort (the partial base.c/base.pcdump.txt are cleaned in main()).
            reason = (
                f"check_i_bl_multiset_equal="
                f"{verdict['check_i_bl_multiset_equal']} "
                f"(bl delta {verdict['bl_target_multiset_delta']}); "
                f"check_ii_all_normalized_lines_register_class="
                f"{verdict['check_ii_all_normalized_lines_register_class']} "
                f"({verdict['nonregister_class_lines']} non-register-class of "
                f"{verdict['normalized_diff_lines']} normalized diff lines); "
                f"checkdiff primary (FP-prone, NOT used)="
                f"{cd['checkdiff_primary']!r}")
            sub = ("  SUBSTITUTION QUESTION → ORCHESTRATOR: this is the "
                   "caller-invisible-split (rejected_b) fixture; a structural "
                   "exclusion means a different real function with the "
                   "caller-invisible-split property is needed. Do NOT pick a "
                   "substitute in the generator."
                   if fx["expected"] == "rejected_b" else "")
            raise SystemExit(
                f"[{fx['function']}] DIRECT-EVIDENCE EXCLUSION: {reason}.{sub}")
        # Admitted: collect phys_target from the PRODUCTION register-diff vector
        # (fresh base pcdump + the just-run checkdiff payload).
        base_pcdump_text = (wdir / "base.pcdump.txt").read_text(encoding="utf-8")
        target = collect_phys_target(
            fx["function"], fx["unit"],
            base_pcdump_text=base_pcdump_text, checkdiff_payload=cd["payload"])

    expectations = _phys_target_expectations(base_pcdump_text, fx["function"])

    # ---- T10e WHOLE-SOLVER ASSERTION (A1 rev 2) -----------------------------
    # Freeze the source-attribution bridge and run the PRODUCTION enumerate+
    # filter to assert the class-signal node's candidates are rejected/flagged.
    from src.mwcc_debug import tiebreak as tb
    ig = tb.load_ig(base_pcdump_text, fx["function"], class_id=0)
    if ig is None:
        raise SystemExit(f"[{fx['function']}] no COLORGRAPH class=0 in dump — "
                         f"do NOT freeze.")
    report = _explain_report(base_pcdump_text, fx["function"], base_src,
                             str(wdir / "base.c"), ig)
    _freeze_bridge(report, wdir / "bridge.json")
    phys_target_s = {str(k): v for k, v in target["phys_target"].items()}
    target_ig, signal_detail = _pick_target_ig(report, ig, phys_target_s,
                                               fx["expected"])
    hops = signal_detail.get("implicated_hops", 1)
    whole_solver = _whole_solver_record(ig, phys_target_s, report,
                                        target_ig=target_ig,
                                        expected=fx["expected"], hops=hops)
    if not whole_solver["whole_solver_reject_assertion_ok"]:
        raise SystemExit(
            f"[{fx['function']}] WHOLE-SOLVER assertion FAILED: the production "
            f"enumerate+filter did NOT cleanly reject/flag target ig={target_ig} "
            f"({whole_solver}) — do NOT freeze.")
    if not whole_solver["recompute_equality_audit_ok"]:
        raise SystemExit(
            f"[{fx['function']}] recompute-equality audit FAILED "
            f"({whole_solver['recompute_audit']}) — do NOT freeze.")
    if not whole_solver["broken_filter_control"]["breaks_gate"]:
        raise SystemExit(
            f"[{fx['function']}] BROKEN-FILTER control did NOT break the gate "
            f"(§3) — a filter that can't fail can't pass; do NOT freeze.")

    record = {
        "name": fx["name"], "function": fx["function"], "unit": fx["unit"],
        "class_id": 0, "kind": fx["kind"],
        "real_exemplar": fx.get("real_exemplar", False),
        "checkdiff_primary": target["checkdiff_primary"],
        "phys_target": phys_target_s,
        "reachable": target["reachable"],
        "reachable_note": target.get("reachable_note"),
        "phys_conflicts": target.get("phys_conflicts", []),
        "expected": {"outcome": fx["expected"],
                     "filter_token": EXPECTED_FILTER_TOKEN[fx["expected"]]},
        "target_ig": target_ig,
        "class_signal": signal_detail,
        "whole_solver": whole_solver,
        "bridge_file": "bridge.json",
        "expectations": expectations,
        "admission": {
            "mode": "direct_evidence",
            "checkdiff_primary": cd["checkdiff_primary"],  # FP-prone, recorded
            "check_i_bl_multiset_equal":
                verdict["check_i_bl_multiset_equal"],
            "check_ii_all_normalized_lines_register_class":
                verdict["check_ii_all_normalized_lines_register_class"],
            "bl_target_multiset_delta": verdict["bl_target_multiset_delta"],
            "normalized_diff_lines": verdict["normalized_diff_lines"],
            "nonregister_class_lines": verdict["nonregister_class_lines"],
        },
        "alias": {"source_object_candidates": fx["alias_source_object_candidates"],
                  "lever": "alias"},
    }
    (wdir / "fixture.json").write_text(json.dumps(record, indent=2),
                                       encoding="utf-8")
    return record


def main() -> None:
    snap = HERE / "catalog_snapshot"
    snap.mkdir(exist_ok=True)
    for kind, entries in CATALOG_SNAPSHOT.items():
        (snap / f"{kind}.json").write_text(json.dumps(entries, indent=2),
                                           encoding="utf-8")
    results = {}
    aborts: dict[str, str] = {}
    with _acquire_repo_build_lock(MELEE_ROOT, label="solver calibration freeze"):
        os.environ["CHECKDIFF_NO_LOCK"] = "1"
        try:
            for fx in FIXTURES:
                print(f"=== {fx['name']} ===", flush=True)
                try:
                    results[fx["name"]] = process(fx)
                    print(json.dumps(results[fx["name"]], indent=2), flush=True)
                except SystemExit as exc:
                    aborts[fx["name"]] = str(exc)
                    print(f"ABORT [{fx['name']}]: {exc}", flush=True)
        finally:
            os.environ.pop("CHECKDIFF_NO_LOCK", None)
    print(f"\nfroze {len(results)}/5 fixtures")
    if aborts:
        print("ABORTED fixtures (gate-blocking gaps — report at Task-12):",
              flush=True)
        for name, msg in aborts.items():
            print(f"  - {name}: {msg}", flush=True)
    if len(results) != 5:
        raise SystemExit("NOT all five fixtures froze — gate-blocking gap; "
                         "report to the orchestrator at the Task-12 checkpoint.")


if __name__ == "__main__":
    main()
