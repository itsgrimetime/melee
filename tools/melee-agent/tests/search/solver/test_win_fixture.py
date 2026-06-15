"""Unit coverage for the self-contained win-fixture pure helpers (T10c).

The win-fixture redesign (plan "T10b outcome → BINDING design amendment") makes
two decisions PURE and mwcc-free, so they are unit-testable over fixture text:
  1. the PRE-vs-POST admission decision (FULLNORM-0 over the two objects), and
  2. the POST-derived `phys_target` extraction from the post IG.

These tests pin both over hand-built COLORGRAPH / disasm text (no compiler).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from src.search.solver.win_fixture import (
    classify_normalized_diff,
    direct_evidence_verdict,
    extract_dtk_function,
    extract_phys_target_from_ig,
    is_register_only_admission,
    post_ig_reproduces_target,
    win_admission_verdict,
)


def _real_normalized_structural_lines():
    """Load tools/checkdiff.py's `normalized_structural_lines` by path (it lives
    outside the package, and is a PURE text function — no compiler), so the
    direct-evidence tests run on the SAME normalization the generator uses."""
    melee_root = Path(__file__).resolve().parents[5]
    spec = importlib.util.spec_from_file_location(
        "checkdiff_for_test", melee_root / "tools" / "checkdiff.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalized_structural_lines

# A minimal `dtk elf disasm` snippet: two functions, current `.fn ..., global`
# format with the `/* addr addr bytes */ mnemonic ...` body lines.
DTK_DISASM = """\
.section .text
.fn other_before, global
/* 00000000 00000000  7C 08 02 A6 */\tmflr r0
.endfn other_before

.fn target_fn, global
/* 00000010 00000010  94 21 FF 98 */\tstwu r1, -0x68(r1)
/* 00000014 00000014  7C 08 02 A6 */\tmflr r0
/* 00000018 00000018  90 01 00 04 */\tstw r0, 0x4(r1)
/* 0000001C 0000001C  4E 80 00 20 */\tblr
.endfn target_fn

.fn other_after, global
/* 00000030 00000030  4E 80 00 20 */\tblr
.endfn other_after
"""


def test_extract_dtk_function_scopes_and_normalizes():
    lines = extract_dtk_function(DTK_DISASM, "target_fn")
    assert lines[0] == "<target_fn>:"
    # exactly the 4 body instructions, comment stripped, +offset prefixed
    assert lines[1:] == [
        "+000: stwu r1, -0x68(r1)",
        "+004: mflr r0",
        "+008: stw r0, 0x4(r1)",
        "+00c: blr",
    ]
    # neighbors excluded
    assert "mflr r0" in lines[2]  # the target's, not other_before's
    assert extract_dtk_function(DTK_DISASM, "missing_fn") == []


def _fake_classify(register_only=True, frame_delta=True):
    """Stand-in for tools/checkdiff.py `classify_asm_diff`. Returns the shape the
    verdict consumes: a `primary` + `structural_truth_gate.normalized_diff_lines`.
    `frame_delta=True` reproduces the win shape (FULLNORM-0 but primary relabeled
    `stack-layout`); `register_only` toggles the strict-primary informational bit.
    """
    def classify(pre, post):
        if pre == post:
            return {"primary": "instruction-identical", "reasons": []}
        primary = "stack-layout" if frame_delta else (
            "normalized-structural-match" if register_only else "instruction-sequence")
        norm = 0 if (frame_delta or register_only) else 3
        return {"primary": primary,
                "structural_truth_gate": {"normalized_diff_lines": norm}}
    return classify


def test_admission_fullnorm0_with_frame_delta_is_admitted():
    # The decisive win shape: FULLNORM-0 (normalized_diff_lines==0) but the
    # stack-frame probe relabels primary `stack-layout`. Must ADMIT (the frame
    # delta is part of the win), even though strict_register_only is False.
    v = win_admission_verdict(["<f>:", "+000: a"], ["<f>:", "+000: b"],
                              classify_asm_diff=_fake_classify(frame_delta=True))
    assert v["admitted"] is True
    assert v["normalized_diff_lines"] == 0
    assert v["primary"] == "stack-layout"
    assert v["strict_register_only"] is False  # the OLD gate would have rejected
    assert v["pre_lines"] == 2 and v["post_lines"] == 2


def test_admission_rejects_structural_diff():
    # A genuine structural diff (normalized_diff_lines > 0) is NOT admissible.
    v = win_admission_verdict(["<f>:", "+000: a"], ["<f>:", "+000: b", "+004: c"],
                              classify_asm_diff=_fake_classify(
                                  register_only=False, frame_delta=False))
    assert v["admitted"] is False
    assert v["normalized_diff_lines"] == 3
    assert v["primary"] == "instruction-sequence"


def test_admission_instruction_identical_is_admitted():
    # Post identical to pre (e.g. a 100%-instruction-identical win): FULLNORM-0.
    v = win_admission_verdict(["<f>:", "+000: a"], ["<f>:", "+000: a"],
                              classify_asm_diff=_fake_classify())
    assert v["admitted"] is True
    assert v["normalized_diff_lines"] == 0
    assert v["primary"] == "instruction-identical"


# A minimal COLORGRAPH DECISIONS section in the REAL pcdump format the tiebreak
# parser accepts (header `COLORGRAPH DECISIONS (class=.., result=.., n_nodes=..)`
# preceded by `Starting function`; rows `iter ig_idx rN degree nIntfr 0xflags`
# each followed by an `interferers:` line). It is a VALID G1=100% graph (the
# surrogate's lowest-free-physical SELECT reproduces every observed reg):
#   node 32 interferes with the machine reg r0 (idx 0) -> blocked {0} -> r3;
#   node 33 interferes with r0 + node 32 (r3) -> blocked {0,3} -> r4;
#   node 34 spills (assignedReg r-1) -> EXCLUDED from phys_target.
POST_PCDUMP = """\
Starting function target_fn
COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)
iter  ig_idx  assignedReg degree  nIntfr  flags
0     32      r3         1       1       0x02
      interferers: 0=r0
1     33      r4         2       2       0x02
      interferers: 0=r0 32=r3
2     34      r-1        0       0       0x02
      interferers:
"""


def test_extract_phys_target_from_post_ig_drops_spill():
    pt = extract_phys_target_from_ig(POST_PCDUMP, "target_fn", class_id=0)
    # nodes 32->r3, 33->r4 retained; spilled node 34 dropped
    assert pt == {32: 3, 33: 4}


def test_post_ig_reproduces_target_confirms_at_g1_100():
    pt = extract_phys_target_from_ig(POST_PCDUMP, "target_fn", class_id=0)
    all_match, g1_rate, register_match = post_ig_reproduces_target(
        POST_PCDUMP, "target_fn", pt, class_id=0)
    assert all_match is True
    assert g1_rate == 1.0
    # every contested register present + ok
    assert set(register_match) == {32, 33}
    assert all(ok for *_x, ok in register_match.values())


def test_post_ig_reproduces_target_detects_mismatch():
    # A wrong target on a contested register must FAIL the actual-vs-target check.
    bad_target = {32: 5, 33: 4}  # node 32 should be r3, claim r5
    all_match, g1_rate, register_match = post_ig_reproduces_target(
        POST_PCDUMP, "target_fn", bad_target, class_id=0)
    assert all_match is False
    assert register_match[32][2] is False  # ok flag is False for the wrong reg


# ---------------------------------------------------------------------------
# DIRECT-EVIDENCE admission (amendment 2) — the T10d reject/flag verdict.
# These pin the PURE decision over inline asm fixtures shaped like the real
# mnDiagram functions, running on the SAME `normalized_structural_lines` the
# generator uses. Two checks: (i) bl-target multiset parity (verify-ib REL24
# method), (ii) every NORMALIZED diff line register-class.
# ---------------------------------------------------------------------------
NORMLINES = _real_normalized_structural_lines()


def test_direct_evidence_admits_pure_coloring():
    # bl-multisets equal AND the only body diff is a physical-register swap
    # (`addi r3,r4,0` -> `addi r5,r4,0`), which VANISHES in the register-masked
    # normalized space -> 0 normalized diff lines -> all register-class -> ADMIT.
    target = ["<f>:", "+000: addi r3,r4,0", "+004: bl helper", "+008: blr"]
    current = ["<f>:", "+000: addi r5,r4,0", "+004: bl helper", "+008: blr"]
    v = direct_evidence_verdict(target, current,
                                normalized_structural_lines=NORMLINES)
    assert v["admitted"] is True
    assert v["check_i_bl_multiset_equal"] is True
    assert v["check_ii_all_normalized_lines_register_class"] is True
    assert v["normalized_diff_lines"] == 0
    assert v["nonregister_class_lines"] == 0


def test_direct_evidence_excludes_on_call_shape_flag_c():
    # flag_c shape: current emits one EXTRA `bl HSD_SisLib_803A6368` (the
    # one-extra-call / window quarantine). bl-multiset parity FAILS (i).
    target = ["<f>:", "+000: bl HSD_SisLib_803A6368", "+004: blr"]
    current = ["<f>:", "+000: bl HSD_SisLib_803A6368",
               "+004: bl HSD_SisLib_803A6368", "+008: blr"]
    v = direct_evidence_verdict(target, current,
                                normalized_structural_lines=NORMLINES)
    assert v["admitted"] is False
    assert v["check_i_bl_multiset_equal"] is False
    # the extra call is reported as an "added" callee with its multiplicity
    assert v["bl_target_multiset_delta"]["added"] == {"HSD_SisLib_803A6368": 1}


def test_direct_evidence_excludes_on_instruction_delta_reject_b():
    # reject_b shape: an instruction-SELECTION change (`addi rN,rN,IMM` ->
    # `li rN,IMM`, different mnemonic) AND an instruction-COUNT delta (a deleted
    # `addi`). bl-multiset is equal, but check (ii) FAILS — these are NOT
    # register-class. This is the "2 near-admission lines get a direct-evidence
    # verdict rather than a label" case: excluded, not admitted.
    target = ["<f>:", "+000: addi r21,r26,0", "+004: bl helper",
              "+008: addi r3,r3,8", "+00c: blr"]
    current = ["<f>:", "+000: li r22,0", "+004: bl helper", "+008: blr"]
    v = direct_evidence_verdict(target, current,
                                normalized_structural_lines=NORMLINES)
    assert v["admitted"] is False
    assert v["check_i_bl_multiset_equal"] is True       # calls unchanged
    assert v["check_ii_all_normalized_lines_register_class"] is False
    assert v["nonregister_class_lines"] >= 1


def test_classify_normalized_diff_register_class_vs_structural():
    # A `replace` whose mnemonics MATCH (only a masked offset differs) is a
    # coloring/alignment cascade -> register-class; an inserted line is an
    # instruction-count delta -> non-register-class.
    res = classify_normalized_diff(
        ["lwz rN,IMM(rN)", "blr"],
        ["lwz rN,IMM(rN)", "li rN,IMM", "blr"])
    assert res["normalized_diff_lines"] == 1
    assert res["nonregister_class_lines"] == 1  # the inserted `li`
    res2 = classify_normalized_diff(["stw rN,IMM(rN)"], ["stw rN,IMM(rN)"])
    assert res2["normalized_diff_lines"] == 0
    assert res2["nonregister_class_lines"] == 0


# ---------------------------------------------------------------------------
# #619 — solve-coloring admission gates on the COMPUTED direct-evidence
# register-only property, NOT the checkdiff PRIMARY label. These pin the
# admission predicate that the CLI wires into the solve precondition.
# ---------------------------------------------------------------------------
def test_admission_admits_register_allocation_label_when_pure_permutation():
    # 8024227C-class: the checkdiff PRIMARY label is `register-allocation`
    # (NOT in REGISTER_ONLY_PRIMARIES, so the OLD label gate abstained), but the
    # function is a PROVABLE pure permutation — bl-multisets equal AND the only
    # body diff is a physical-register swap that vanishes in the masked space.
    # The computed property is authoritative -> ADMIT.
    target = ["<f>:", "+000: addi r3,r4,0", "+004: bl helper", "+008: blr"]
    current = ["<f>:", "+000: addi r5,r4,0", "+004: bl helper", "+008: blr"]
    res = is_register_only_admission(
        "register-allocation", target, current,
        normalized_structural_lines=NORMLINES)
    assert res["admitted"] is True
    assert res["via_label"] is False                 # NOT via the fast-path
    assert res["direct_evidence"]["admitted"] is True


def test_admission_admits_instruction_sequence_label_when_pure_permutation():
    # Most coloring walls carry instruction-sequence / normalized-near-match
    # primaries. A pure permutation under any such label must ADMIT on evidence.
    target = ["<f>:", "+000: lwz r30,8(r3)", "+004: mr r31,r30", "+008: blr"]
    current = ["<f>:", "+000: lwz r28,8(r3)", "+004: mr r29,r28", "+008: blr"]
    res = is_register_only_admission(
        "instruction-sequence", target, current,
        normalized_structural_lines=NORMLINES)
    assert res["admitted"] is True
    assert res["via_label"] is False


def test_admission_abstains_on_genuine_structural_diff_despite_label():
    # A genuinely-NON-register-only function: a label outside the set AND a real
    # structural residual (an extra `bl` — call-shape delta). Direct evidence
    # must NOT admit -> the gate still abstains (exit 3 preserved).
    target = ["<f>:", "+000: bl helper", "+004: blr"]
    current = ["<f>:", "+000: bl helper", "+004: bl extra", "+008: blr"]
    res = is_register_only_admission(
        "instruction-sequence", target, current,
        normalized_structural_lines=NORMLINES)
    assert res["admitted"] is False
    assert res["via_label"] is False
    assert res["direct_evidence"]["check_i_bl_multiset_equal"] is False


def test_admission_abstains_on_instruction_count_delta_despite_label():
    # An instruction-COUNT / SELECTION delta (deleted addi, addi->li) is NOT
    # register-class even with equal bl-multisets -> abstain.
    target = ["<f>:", "+000: addi r21,r26,0", "+004: bl helper",
              "+008: addi r3,r3,8", "+00c: blr"]
    current = ["<f>:", "+000: li r22,0", "+004: bl helper", "+008: blr"]
    res = is_register_only_admission(
        "instruction-sequence", target, current,
        normalized_structural_lines=NORMLINES)
    assert res["admitted"] is False
    assert res["direct_evidence"]["check_ii_all_normalized_lines_register_class"] is False


def test_admission_fast_path_admits_on_register_only_primary_label():
    # The label is kept as a fast-path HINT: a primary already in
    # REGISTER_ONLY_PRIMARIES admits immediately (via_label True), matching the
    # historical gate so the calibrated wins are unaffected. Evidence is still
    # computed for the record but does not need to be recomputed for the verdict.
    target = ["<f>:", "+000: addi r3,r4,0", "+004: blr"]
    current = ["<f>:", "+000: addi r5,r4,0", "+004: blr"]
    res = is_register_only_admission(
        "operand-register-or-offset", target, current,
        normalized_structural_lines=NORMLINES)
    assert res["admitted"] is True
    assert res["via_label"] is True
