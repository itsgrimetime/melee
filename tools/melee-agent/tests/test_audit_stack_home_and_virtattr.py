"""Audit regression tests for stack_home_explorer and virtual_attribution.

Covers three confirmed correctness bugs:

BUG 6/9 (stack_home_explorer._variant_target_objective): a target was reported
target_fixed=True when its stack-home slot merely MOVED to a different WRONG
offset, because the baseline-keyed mismatch lookup also required the target's
BASELINE current_offset to match the variant's measured current_offset.

BUG 8 (stack_home_explorer._find_function_bounds): the first textual occurrence
of 'name(' (usually a forward-declaration) plus the next '{' captured an
unrelated function body instead of the real definition.

BUG 10 (virtual_attribution.explain_virtuals): infos was keyed by virtual NUMBER
only, so when a function has both GPR r42 and FPR f42 the later overwrote the
former and live_range/use_count were read from the wrong register class.
"""

from __future__ import annotations

from src.mwcc_debug import virtual_attribution
from src.mwcc_debug.parser import VirtualRegInfo
from src.mwcc_debug.stack_home_explorer import (
    _find_function_bounds,
    _variant_target_objective,
)
from src.mwcc_debug.virtual_attribution import explain_virtuals

# ---------------------------------------------------------------------------
# BUG 6/9: _variant_target_objective must not report a slot that moved to a
# still-wrong offset as fixed.
# ---------------------------------------------------------------------------


def _result_with_mismatches(mismatches: list[dict]) -> dict:
    return {
        "match_percent": 99.0,
        "stack_slot_localizer": {
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
        },
    }


def test_target_not_fixed_when_slot_moves_to_different_wrong_offset() -> None:
    """RED before fix: slot moved 0x30 -> 0x38 but expected is 0x34.

    The localizer reports a fresh mismatch at current_offset=0x38/expected
    0x34. The bug's baseline-keyed lookup compares against the target's baseline
    current_offset (0x30) and misses this mismatch -> wrongly target_fixed.
    """
    targets = [{"opcode": "stfs", "current_offset": 0x30, "expected_offset": 0x34}]
    result = _result_with_mismatches([
        {
            "opcode": "stfs",
            "current_offset": 0x38,
            "expected_offset": 0x34,
            "delta": -4,
        }
    ])

    objective = _variant_target_objective(targets, result)

    assert objective["fixed_count"] == 0
    assert objective["target_fixed"] is False
    # Diagnostic baseline is still preserved in the per-target status.
    assert objective["target_statuses"][0]["baseline_current_offset"] == 0x30


def test_target_fixed_when_no_remaining_mismatch_for_expected() -> None:
    """OVER-CORRECTION GUARD (positive): empty mismatches -> truly fixed."""
    targets = [{"opcode": "stfs", "current_offset": 0x30, "expected_offset": 0x34}]
    result = _result_with_mismatches([])

    objective = _variant_target_objective(targets, result)

    assert objective["fixed_count"] == 1
    assert objective["target_fixed"] is True


def test_target_not_fixed_when_mismatch_still_at_baseline_offset() -> None:
    """OVER-CORRECTION GUARD (negative): slot unchanged at baseline 0x30.

    Ensures the fix does not over-trigger and call an UNMOVED target fixed.
    """
    targets = [{"opcode": "stfs", "current_offset": 0x30, "expected_offset": 0x34}]
    result = _result_with_mismatches([
        {
            "opcode": "stfs",
            "current_offset": 0x30,
            "expected_offset": 0x34,
            "delta": 4,
        }
    ])

    objective = _variant_target_objective(targets, result)

    assert objective["fixed_count"] == 0
    assert objective["target_fixed"] is False


def test_target_fixed_ignores_unrelated_remaining_mismatch() -> None:
    """OVER-CORRECTION GUARD: a mismatch for a DIFFERENT (opcode,expected)
    must not mark this target unfixed once its own slot reached expected."""
    targets = [{"opcode": "stfs", "current_offset": 0x30, "expected_offset": 0x34}]
    result = _result_with_mismatches([
        {
            "opcode": "lwz",
            "current_offset": 0x48,
            "expected_offset": 0x44,
            "delta": -4,
        }
    ])

    objective = _variant_target_objective(targets, result)

    assert objective["fixed_count"] == 1
    assert objective["target_fixed"] is True


# ---------------------------------------------------------------------------
# BUG 8: _find_function_bounds must return the real definition, not an
# unrelated body captured via a forward-declaration.
# ---------------------------------------------------------------------------


SOURCE_WITH_PROTOTYPE = """\
static void fn_target(float a);

static void fn_other(void)
{
    int marker_other = 1;
}

static void fn_target(float a)
{
    int use_target = (int) a;
}
"""


def test_find_function_bounds_skips_prototype_and_returns_definition() -> None:
    """RED before fix: prototype 'fn_target(float a);' is the first match and
    the following '{' belongs to fn_other -> wrong body captured."""
    bounds = _find_function_bounds(SOURCE_WITH_PROTOTYPE, "fn_target")
    assert bounds is not None
    span = SOURCE_WITH_PROTOTYPE[bounds[0]:bounds[1]]

    assert "use_target" in span
    assert "marker_other" not in span


SOURCE_WITHOUT_PROTOTYPE = """\
static void fn_other(void)
{
    int marker_other = 1;
}

static void fn_target(float a)
{
    int use_target = (int) a;
}
"""


def test_find_function_bounds_definition_first_still_works() -> None:
    """OVER-CORRECTION GUARD: no prototype, definition is the first
    occurrence -> still returns the definition correctly."""
    bounds = _find_function_bounds(SOURCE_WITHOUT_PROTOTYPE, "fn_target")
    assert bounds is not None
    span = SOURCE_WITHOUT_PROTOTYPE[bounds[0]:bounds[1]]

    assert "use_target" in span
    assert "marker_other" not in span


# ---------------------------------------------------------------------------
# BUG 10: explain_virtuals must read live_range/use_count from the resolved
# register class, not whichever VirtualRegInfo happened to land last in a
# number-keyed dict.
# ---------------------------------------------------------------------------


# pcdump exercising virtual 42 in BOTH the GPR (r42) and FPR (f42) classes.
DUAL_CLASS_PCDUMP = """\
Starting function fn_dual
BEFORE REGISTER COLORING
fn_dual
B0: Succ={} Pred={} Labels={}
    lwz r42,8(r3)
    add r5,r42,r4
    stw r42,12(r3)
    frsp f42,f1
    stfs f42,0x30(r1)
AFTER REGISTER COLORING
fn_dual
B0: Succ={} Pred={} Labels={}
    lwz r10,8(r3)
    add r5,r10,r4
    stw r10,12(r3)
    frsp f6,f1
    stfs f6,0x30(r1)
COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
  iter ig_idx phys degree nIntfr flags
    0 42 r10 0 0 0x00
COLORGRAPH DECISIONS (class=1, result=1, n_nodes=1)
  iter ig_idx phys degree nIntfr flags
    0 42 r6 0 0 0x00
"""


def _gpr42_info() -> VirtualRegInfo:
    return VirtualRegInfo(
        virtual=42,
        physical=10,
        physical_class="GPR",
        reg_kind="r",
        first_use=0,
        last_use=2,
        use_count=3,
    )


def _fpr42_info() -> VirtualRegInfo:
    return VirtualRegInfo(
        virtual=42,
        physical=6,
        physical_class="FPR",
        reg_kind="f",
        first_use=10,
        last_use=11,
        use_count=2,
    )


def test_explain_virtuals_reads_gpr_class_for_dual_class_virtual(monkeypatch) -> None:
    """RED before fix: number-keyed infos lose the GPR entry to the FPR entry,
    so a gpr request reports the FPR's live_range/use_count."""
    monkeypatch.setattr(
        virtual_attribution,
        "analyze_function",
        lambda fn: [_gpr42_info(), _fpr42_info()],
    )

    report = explain_virtuals(
        DUAL_CLASS_PCDUMP,
        "fn_dual",
        virtuals=[42],
        reg_class="gpr",
    )

    entry = report.virtuals[0]
    assert entry.class_id == 0
    assert entry.use_count == 3
    assert entry.live_range == (0, 2)


def test_explain_virtuals_reads_fpr_class_for_dual_class_virtual(monkeypatch) -> None:
    """The fpr request must report the FPR's live_range/use_count."""
    monkeypatch.setattr(
        virtual_attribution,
        "analyze_function",
        lambda fn: [_gpr42_info(), _fpr42_info()],
    )

    report = explain_virtuals(
        DUAL_CLASS_PCDUMP,
        "fn_dual",
        virtuals=[42],
        reg_class="fpr",
    )

    entry = report.virtuals[0]
    assert entry.class_id == 1
    assert entry.use_count == 2
    assert entry.live_range == (10, 11)


def test_explain_virtuals_single_gpr_class_still_resolves(monkeypatch) -> None:
    """OVER-CORRECTION GUARD: a function with only r42 still resolves to the
    GPR info under a gpr request."""
    monkeypatch.setattr(
        virtual_attribution,
        "analyze_function",
        lambda fn: [_gpr42_info()],
    )

    report = explain_virtuals(
        DUAL_CLASS_PCDUMP,
        "fn_dual",
        virtuals=[42],
        reg_class="gpr",
    )

    entry = report.virtuals[0]
    assert entry.class_id == 0
    assert entry.use_count == 3
    assert entry.live_range == (0, 2)
