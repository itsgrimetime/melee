"""Kill switch — frozen-fixture retrodiction of a known win (§6c).

The premise under test: directed order-distance descends toward a forced-ORDER-
proven target and the metric retrodicts a known win. The kill switch scores
THREE FIXED candidate sources (pre_win / win / negative control) of the GATING
witness — selected by tests/fixtures/order_distance/eligibility.json — through
the SAME generalized scoring core the loop uses. It is mutator-independent.

Four assertions (all must hold, else the premise is REFUTED and the campaign
STOPs):
  (a) pre_win and win round-trip-anchor the EXACT same target-role set.
  (b) order_distance(win) < order_distance(pre_win) (both §3.3-valid).
  (c) the RECORDED named_pair (order_target.yaml, with provenance) is inverted
      in pre_win and correct in win — the pair relation is DERIVED from each
      candidate's ranks_by_role and the proven vector's direction (B7).
  (d) order_distance(negative_control) >= order_distance(pre_win).

No eligible witness (eligibility.json gating_fixture == null) is a HARD STOP
with an explicit orchestrator report — never a silent pass. The result is
written to docs/superpowers/results/ on every outcome.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class KillSwitchResult:
    passed: bool
    assertion_a: bool
    assertion_b: bool
    assertion_c: bool
    assertion_d: bool
    failure_reason: str
    detail: dict
    result_doc_path: Optional[str] = None


def evaluate_kill_switch(
    *,
    scores: dict,        # {"pre_win"|"win"|"negative_control": CandidateScore}
    named_pair: tuple,   # (ig_a, ig_b) — the RECORDED pair (order_target.yaml)
    order_target: dict,  # the proven vector {ig: rank}; gives the pair's direction
) -> KillSwitchResult:
    """Apply the four §6c assertions. The pair relation per candidate is
    derived from CandidateScore.ranks_by_role (no disconnected inputs)."""
    pre = scores.get("pre_win")
    win = scores.get("win")
    neg = scores.get("negative_control")

    for name, cs in (("pre_win", pre), ("win", win), ("negative_control", neg)):
        if cs is None or not cs.valid:
            reason = (
                f"{name} candidate is invalid "
                f"({getattr(cs, 'invalid_reason', 'missing')}); cannot retrodict"
            )
            return KillSwitchResult(
                False, False, False, False, False, reason,
                {"scores": {k: _cs_dict(v) for k, v in scores.items()}},
            )

    # (a) same anchored target-role set.
    a = set(pre.ranks_by_role) == set(win.ranks_by_role)

    # (b) strict descent.
    b = win.order_distance < pre.order_distance

    # (c) the RECORDED pair: inverted in pre_win, correct in win, direction
    #     from the proven vector. Derived from ranks_by_role (B7).
    ig_a, ig_b = named_pair
    pair_present = all(
        ig in cs.ranks_by_role for cs in (pre, win) for ig in (ig_a, ig_b)
    ) and ig_a in order_target and ig_b in order_target
    if pair_present:
        target_dir = order_target[ig_a] < order_target[ig_b]
        pre_dir = pre.ranks_by_role[ig_a] < pre.ranks_by_role[ig_b]
        win_dir = win.ranks_by_role[ig_a] < win.ranks_by_role[ig_b]
        c = (pre_dir != target_dir) and (win_dir == target_dir)
    else:
        c = False

    # (d) negative control does not descend.
    d = neg.order_distance >= pre.order_distance

    passed = a and b and c and d
    reasons = []
    if not a:
        reasons.append("assertion (a) failed: anchored target-role sets differ "
                       f"(pre={sorted(pre.ranks_by_role)} win={sorted(win.ranks_by_role)}) "
                       "— this win class is invisible to role-stable order distance")
    if not b:
        reasons.append(f"assertion (b) failed: no strict descent "
                       f"(pre={pre.order_distance} win={win.order_distance})")
    if not c:
        reasons.append("assertion (c) failed: the recorded pair "
                       f"{tuple(named_pair)} did not flip in the intended direction "
                       f"(pre_ranks={pre.ranks_by_role} win_ranks={win.ranks_by_role} "
                       f"target={order_target})")
    if not d:
        reasons.append("assertion (d) failed: negative control descended "
                       f"(pre={pre.order_distance} neg={neg.order_distance}) "
                       "— the metric admits false positives")
    return KillSwitchResult(
        passed, a, b, c, d, "; ".join(reasons),
        {
            "pre_win": _cs_dict(pre), "win": _cs_dict(win),
            "negative_control": _cs_dict(neg),
            "named_pair": list(named_pair),
            "order_target": dict(order_target),
        },
    )


def _cs_dict(cs: Any) -> dict:
    if cs is None:
        return {"present": False}
    return {
        "valid": cs.valid, "invalid_reason": cs.invalid_reason,
        "order_distance": cs.order_distance,
        "ranks_by_role": cs.ranks_by_role, "coverage": cs.coverage,
    }


def _score_fixture(fixtures: Path, target: Any, ref_descs: dict, name: str):
    from src.search.directed.order_metric import score_candidate_reanchored
    pc = (fixtures / f"{name}.pcdump.txt").read_text(encoding="utf-8")
    src = (fixtures / f"{name}.c").read_text(encoding="utf-8")
    return score_candidate_reanchored(
        pc, ref_descs, function=target.function, class_id=target.class_id,
        order_target=target.order_target, phys_target=target.phys_target,
        cand_source=src,
    )


def run_kill_switch_from_fixtures(fixtures_root: Any) -> KillSwitchResult:
    """Live-bytes driver: select the gating witness via eligibility.json, score
    its frozen pcdumps via the shared core, apply the assertions, score the
    cardstate chain as the non-gating secondary witness, and WRITE the result
    doc on every outcome (pass / fire / hard-stop)."""
    from src.mwcc_debug.role_descriptor import Compile, build_descriptors
    from src.search.directed.order_target import OrderTarget

    root = Path(fixtures_root)
    eligibility = json.loads((root / "eligibility.json").read_text(encoding="utf-8"))
    gating = eligibility.get("gating_fixture")

    if not gating:
        res = KillSwitchResult(
            False, False, False, False, False,
            "HARD STOP: no derivation-eligible witness (eligibility.json "
            "gating_fixture is null) — ORCHESTRATOR ACTION REQUIRED: revisit "
            "the kill-switch function assignment (§6c contingency exhausted)",
            {"eligibility": eligibility},
        )
        res.result_doc_path = _write_result_doc(res, "(none)", eligibility)
        return res

    fixtures = root / gating
    target = OrderTarget.load_yaml(fixtures / "order_target.yaml")
    if len(target.named_pair) != 2:
        res = KillSwitchResult(
            False, False, False, False, False,
            f"KILL SWITCH FIRED: {gating}/order_target.yaml has no recorded "
            f"named_pair ({target.named_pair_provenance or 'no provenance'}). "
            f"Either the T6 generator was not run, or NO persistent role pair "
            f"flips between pre_win and win — the win class is invisible to "
            f"role-stable order distance (the §6c assertion (a)/(c) firing at "
            f"freeze time). ORCHESTRATOR ACTION REQUIRED: this is a refutation "
            f"signal on the gating witness, not a fixture-regeneration errand.",
            {"eligibility": eligibility},
        )
        res.result_doc_path = _write_result_doc(res, target.function, eligibility)
        return res

    pre_pc = (fixtures / "pre_win.pcdump.txt").read_text(encoding="utf-8")
    pre_src = (fixtures / "pre_win.c").read_text(encoding="utf-8")
    ref_descs = build_descriptors(
        Compile.from_text(pre_pc, target.function, pre_src),
        class_id=target.class_id,
    )
    scores = {
        name: _score_fixture(fixtures, target, ref_descs, name)
        for name in ("pre_win", "win", "negative_control")
    }
    res = evaluate_kill_switch(
        scores=scores, named_pair=tuple(target.named_pair),
        order_target=target.order_target,
    )
    res.detail["gating_fixture"] = gating
    res.detail["named_pair_provenance"] = target.named_pair_provenance

    # Secondary witness (non-gating, reported): the cardstate chain scored as
    # a monotone sequence against ITS OWN target, when that target is directed.
    chain_dir = root / "fn_803ACD58"
    chain_yaml = chain_dir / "order_target.yaml"
    if chain_yaml.exists():
        ctarget = OrderTarget.load_yaml(chain_yaml)
        cpre_pc = (chain_dir / "pre_win.pcdump.txt").read_text(encoding="utf-8")
        cpre_src = (chain_dir / "pre_win.c").read_text(encoding="utf-8")
        cref = build_descriptors(
            Compile.from_text(cpre_pc, ctarget.function, cpre_src),
            class_id=ctarget.class_id,
        )
        seq = []
        for name in ("pre_win", "win", "chain_2", "chain_3"):
            if not (chain_dir / f"{name}.pcdump.txt").exists():
                continue
            cs = _score_fixture(chain_dir, ctarget, cref, name)
            seq.append({"step": name, "valid": cs.valid,
                        "order_distance": cs.order_distance})
        ods = [s["order_distance"] for s in seq
               if s["valid"] and s["order_distance"] is not None]
        res.detail["secondary_witness_chain"] = {
            "sequence": seq,
            "non_increasing": all(x >= y for x, y in zip(ods, ods[1:])),
        }
    else:
        res.detail["secondary_witness_chain"] = {
            "sequence": [],
            "note": "cardstate target not directed or not generated — not scored",
        }

    res.result_doc_path = _write_result_doc(res, target.function, eligibility)
    return res


def _write_result_doc(res: KillSwitchResult, function: str, eligibility: dict) -> str:
    here = Path(__file__).resolve()
    # tools/melee-agent/src/search/directed/kill_switch.py -> worktree root
    root = here.parents[5]
    out = root / "docs" / "superpowers" / "results" \
        / "2026-06-12-order-distance-kill-switch-result.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    verdict = "PASSED — premise holds; proceed to Plan C" if res.passed \
        else "FIRED / STOPPED — premise refuted or witness unavailable; STOP. " \
             "Keep the shipped phys-match objective; route the pool to the " \
             "permuter arm."
    lines = [
        "# Order-distance kill-switch result",
        "",
        f"**Gating function:** {function}",
        f"**Gating fixture (eligibility.json):** {eligibility.get('gating_fixture')}",
        f"**Verdict:** {verdict}",
        "",
        "## Assertions",
        f"- (a) same anchored target-role set: {res.assertion_a}",
        f"- (b) strict descent win < pre_win: {res.assertion_b}",
        f"- (c) recorded named pair flips in intended direction: {res.assertion_c}",
        f"- (d) negative control does not descend: {res.assertion_d}",
        "",
        f"**Failure reason:** {res.failure_reason or '(none)'}",
        "",
        "## Detail",
        "",
    ]
    # Render the detail as a 4-space-indented code block (avoids nesting a
    # fenced block inside this module's own source/markdown).
    for detail_line in json.dumps(res.detail, indent=2).splitlines():
        lines.append("    " + detail_line)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)
