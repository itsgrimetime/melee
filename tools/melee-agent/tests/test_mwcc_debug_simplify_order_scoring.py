"""Unit tests for the lex-encoded simplify-order scorer."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.mwcc_debug.simplify_order_scoring import (
    HIGH_VOLATILE_REGS,
    LEX_BIG,
    Polarity,
    SimplifyOrderSpecError,
    SimplifyOrderTargetSpec,
    UNCERTAIN_VOLATILE_REGS,
    classify_polarity,
    compute_lex_score,
    extract_signature,
    load_simplify_order_target_spec,
)
from src.mwcc_debug.simplify_search import BaselineSignature


# ---------------------------------------------------------------------------
# BaselineSignature factory — local helper that doesn't reach into the
# colorgraph parser, so the score tests are insulated from pcdump-format
# churn. Mirrors the shape `baseline_signature()` produces.
# ---------------------------------------------------------------------------


def _sig(
    *,
    ig: list[tuple[int, int]] | None = None,
    coalesce: list[tuple[int, int]] | None = None,
    spills: set[int] | None = None,
    simplify_order: tuple[int, ...] = (32, 33),
) -> BaselineSignature:
    return BaselineSignature(
        interference_edges=frozenset(ig or []),
        coalesce_mappings=frozenset(coalesce or []),
        spill_set=frozenset(spills or set()),
        simplify_order=simplify_order,
    )


# ---------------------------------------------------------------------------
# Score-formula tests
# ---------------------------------------------------------------------------


def test_lex_score_perfect_match_is_zero() -> None:
    """prefix == target_len AND distance.total == 0 → score 0."""
    baseline = _sig(simplify_order=(42, 32, 99))
    candidate = _sig(simplify_order=(42, 32, 100))
    target = (42, 32)
    result = compute_lex_score(baseline, candidate, target)
    assert result.score == 0
    assert result.simplify_score.common_prefix_length == 2
    assert result.precolor_distance.total == 0


def test_lex_score_target_hit_low_distance() -> None:
    """Hits target prefix but disturbs precolor → score = distance.total."""
    baseline = _sig(
        ig=[(1, 2), (3, 4)],
        simplify_order=(99, 99),
    )
    candidate = _sig(
        ig=[(1, 2), (3, 4), (5, 6)],  # +1 edge
        coalesce=[(7, 8)],              # +1 mapping
        simplify_order=(42, 32),
    )
    target = (42, 32)
    result = compute_lex_score(baseline, candidate, target)
    # prefix=2 of target_len=2, distance.total = 1 + 1 = 2
    assert result.simplify_score.common_prefix_length == 2
    assert result.precolor_distance.total == 2
    assert result.score == 2


def test_lex_score_prefix_dominates_distance() -> None:
    """ANY higher-prefix candidate ranks below ANY lower-prefix candidate.

    Specifically: prefix=2/2 with distance=10_000 should still score
    BELOW (better than) prefix=1/2 with distance=0.
    """
    baseline = _sig(simplify_order=(99, 99))
    # Candidate A: hits prefix=2 but disturbs a ton
    cand_a = _sig(
        ig=[(i, i + 1) for i in range(5000)],  # 5000 extra edges
        simplify_order=(42, 32),
    )
    # Candidate B: hits only prefix=1, zero disturbance
    cand_b = _sig(simplify_order=(42, 99))
    target = (42, 32)

    score_a = compute_lex_score(baseline, cand_a, target)
    score_b = compute_lex_score(baseline, cand_b, target)
    # Both should encode prefix-level dominance even at this distance:
    # A: 0*LEX_BIG + 5000 = 5000
    # B: 1*LEX_BIG + 0    = 1_000_000
    assert score_a.score == 5000
    assert score_b.score == LEX_BIG
    assert score_a.score < score_b.score  # higher prefix wins


def test_lex_score_no_progress_is_target_len_times_lex_big() -> None:
    """prefix=0/2 with zero distance → 2 * LEX_BIG."""
    baseline = _sig(simplify_order=(99, 99))
    candidate = _sig(simplify_order=(0, 0))
    target = (42, 32)
    result = compute_lex_score(baseline, candidate, target)
    assert result.score == 2 * LEX_BIG


def test_lex_score_empty_target_collapses_to_distance() -> None:
    """Empty target: no prefix to miss, score == distance.total.

    Lets the scorer be used in a "minimize precolor disturbance"
    campaign without specifying a simplify-order goal.
    """
    baseline = _sig(ig=[(1, 2)])
    candidate = _sig(ig=[(1, 2), (3, 4)])  # +1 edge
    target: tuple[int, ...] = ()
    result = compute_lex_score(baseline, candidate, target)
    assert result.simplify_score.common_prefix_length == 0
    assert result.precolor_distance.total == 1
    assert result.score == 1


def test_lex_score_distance_within_prefix_level_is_monotone() -> None:
    """Two candidates at same prefix: lower distance ⇒ lower score."""
    baseline = _sig(simplify_order=(99, 99))
    cand_low = _sig(
        ig=[(1, 2)],
        simplify_order=(42, 32),
    )
    cand_high = _sig(
        ig=[(1, 2), (3, 4), (5, 6)],
        simplify_order=(42, 32),
    )
    target = (42, 32)
    s_low = compute_lex_score(baseline, cand_low, target)
    s_high = compute_lex_score(baseline, cand_high, target)
    assert s_low.score < s_high.score
    assert s_low.score == 1   # +1 IG edge
    assert s_high.score == 3  # +3 IG edges


# ---------------------------------------------------------------------------
# Spec loader tests
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_spec_loader_reads_yaml_required_fields(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("# stub", encoding="utf-8")
    spec_path = _write_yaml(tmp_path, "spec.yaml", f"""\
        function: grVenom_80204284
        simplify_order_target: [42, 32]
        class_id: 0
        baseline_dump: {baseline}
    """)
    spec = load_simplify_order_target_spec(spec_path)
    assert spec.function == "grVenom_80204284"
    assert spec.simplify_order_target == (42, 32)
    assert spec.class_id == 0
    assert spec.baseline_dump == baseline


def test_spec_loader_class_id_defaults_to_zero(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("# stub", encoding="utf-8")
    spec_path = _write_yaml(tmp_path, "spec.yaml", f"""\
        function: fn_test
        simplify_order_target: [1]
        baseline_dump: {baseline}
    """)
    spec = load_simplify_order_target_spec(spec_path)
    assert spec.class_id == 0


def test_spec_loader_rejects_missing_baseline_dump_field(tmp_path: Path) -> None:
    spec_path = _write_yaml(tmp_path, "spec.yaml", """\
        function: fn_test
        simplify_order_target: [1, 2]
    """)
    with pytest.raises(SimplifyOrderSpecError, match="baseline_dump"):
        load_simplify_order_target_spec(spec_path)


def test_spec_loader_rejects_nonexistent_baseline_dump(tmp_path: Path) -> None:
    bogus = tmp_path / "does_not_exist.txt"
    spec_path = _write_yaml(tmp_path, "spec.yaml", f"""\
        function: fn_test
        simplify_order_target: [1, 2]
        baseline_dump: {bogus}
    """)
    with pytest.raises(SimplifyOrderSpecError, match="does not exist"):
        load_simplify_order_target_spec(spec_path)


def test_spec_loader_rejects_missing_function(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("# stub", encoding="utf-8")
    spec_path = _write_yaml(tmp_path, "spec.yaml", f"""\
        simplify_order_target: [1, 2]
        baseline_dump: {baseline}
    """)
    with pytest.raises(SimplifyOrderSpecError, match="function"):
        load_simplify_order_target_spec(spec_path)


def test_spec_loader_rejects_non_integer_target_entry(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("# stub", encoding="utf-8")
    spec_path = _write_yaml(tmp_path, "spec.yaml", f"""\
        function: fn_test
        simplify_order_target: [1, "not-an-int"]
        baseline_dump: {baseline}
    """)
    with pytest.raises(SimplifyOrderSpecError, match="simplify_order_target"):
        load_simplify_order_target_spec(spec_path)


def test_spec_loader_resolves_relative_baseline_dump(tmp_path: Path) -> None:
    """A relative baseline_dump path should resolve against the spec dir."""
    sub = tmp_path / "sub"
    sub.mkdir()
    baseline = sub / "baseline.txt"
    baseline.write_text("# stub", encoding="utf-8")
    spec_path = _write_yaml(sub, "spec.yaml", """\
        function: fn_test
        simplify_order_target: [1]
        baseline_dump: baseline.txt
    """)
    spec = load_simplify_order_target_spec(spec_path)
    assert spec.baseline_dump == baseline.resolve()


def test_spec_loader_missing_file_clear_error(tmp_path: Path) -> None:
    with pytest.raises(SimplifyOrderSpecError, match="not found"):
        load_simplify_order_target_spec(tmp_path / "nope.yaml")


def test_extract_signature_returns_none_for_missing_function() -> None:
    """A pcdump that doesn't mention `function` yields None."""
    text = "# empty pcdump — no FUNCTION sections"
    assert extract_signature(text, "fn_missing", class_id=0) is None


# ---------------------------------------------------------------------------
# `-1` placeholder filtering tests (Fix A — surfaced by ftColl_8007BAC0
# campaign on 2026-05-24, see docs/mwcc-debug-ftColl_8007BAC0-campaign-…)
# ---------------------------------------------------------------------------


def _pcdump(function: str, simplify_rows: list[tuple[int, int]]) -> str:
    """Build a minimal pcdump fixture for one function with given simplify rows.

    `simplify_rows` is a list of `(iter_idx, ig_idx)` pairs. Other columns
    (degree, array_size, flags) are set to fixed harmless values. Only one
    register-class section is emitted (class=0).
    """
    lines = [
        f"Starting function {function}",
        "SIMPLIFY GRAPH (class=0, n_colors=32, n_class_regs=32)",
        "iter ig_idx degree arraySize flags",  # header row, skipped
    ]
    for iter_idx, ig_idx in simplify_rows:
        lines.append(f"  {iter_idx} {ig_idx} 0 0 0x00")
    return "\n".join(lines) + "\n"


def test_extract_signature_filters_minus_one_entries() -> None:
    """`-1` placeholders are dropped; only real ig_idx entries remain."""
    text = _pcdump("fn_ftColl", [
        (0, -1),
        (1, -1),
        (2, 37),
        (3, -1),
        (4, 41),
    ])
    sig = extract_signature(text, "fn_ftColl", class_id=0)
    assert sig is not None
    assert sig.simplify_order == (37, 41)


def test_extract_signature_no_minus_ones_unchanged() -> None:
    """grVenom-shape pcdump with no `-1`s passes through unchanged."""
    text = _pcdump("grVenom", [
        (0, 42),
        (1, 32),
        (2, 17),
        (3, 8),
    ])
    sig = extract_signature(text, "grVenom", class_id=0)
    assert sig is not None
    assert sig.simplify_order == (42, 32, 17, 8)


def test_compute_lex_score_ftcoll_pattern_target_not_met() -> None:
    """Filtered simplify order `[..., 41, ..., 37, ...]` misses target `(37, 41)`.

    Mirrors ftColl_8007BAC0's pre-fix shape: raw order has 41 before 37
    interleaved with `-1` placeholders. After filtering, the prefix is
    `(41, 37, ...)` which has only `common_prefix_length=0` against
    `(37, 41)` — so score == 2 * LEX_BIG.
    """
    baseline = _sig(simplify_order=(99, 99))  # baseline irrelevant for the prefix check
    # Build the filtered candidate explicitly — extract_signature would have
    # produced this from a `[-1, -1, ..., 41, ..., 37, ...]` raw order.
    candidate = _sig(simplify_order=(41, 17, 37, 8, 22))
    target = (37, 41)
    result = compute_lex_score(baseline, candidate, target)
    assert result.simplify_score.common_prefix_length == 0
    assert result.score == 2 * LEX_BIG


def test_compute_lex_score_ftcoll_pattern_target_met() -> None:
    """Filtered order `[37, 41, ...]` satisfies target `(37, 41)` → score 0.

    This is the "win" shape the campaign is searching for: after filtering
    out `-1` placeholders, the candidate's simplify order starts with the
    target nodes.
    """
    baseline = _sig(simplify_order=(99, 99))
    candidate = _sig(simplify_order=(37, 41, 17, 8))
    target = (37, 41)
    result = compute_lex_score(baseline, candidate, target)
    assert result.simplify_score.common_prefix_length == 2
    assert result.score == 0


def test_compute_lex_score_grvenom_pattern_still_zero() -> None:
    """Regression: grVenom (no `-1`s) keeps scoring 0 on a target-hit."""
    baseline = _sig(simplify_order=(99, 99))
    candidate = _sig(simplify_order=(42, 32, 99))
    target = (42, 32)
    result = compute_lex_score(baseline, candidate, target)
    assert result.score == 0


def test_compute_lex_score_filters_minus_one_in_signatures_defensively() -> None:
    """If a caller hands in a signature with `-1`s baked in, score still works.

    This guards the entry point against a future regression where someone
    bypasses `extract_signature` and constructs `BaselineSignature` directly
    from `simplify_search.baseline_signature` (which yields the raw form).
    """
    baseline = _sig(simplify_order=(-1, -1, 99))
    candidate = _sig(simplify_order=(-1, 42, -1, 32))
    target = (42, 32)
    result = compute_lex_score(baseline, candidate, target)
    # After defensive filter: candidate's order is (42, 32) → prefix=2 → score 0
    assert result.simplify_score.common_prefix_length == 2
    assert result.score == 0


def test_compute_lex_score_filters_minus_one_in_target_defensively() -> None:
    """A spec author who writes `-1` in `simplify_order_target` gets it stripped.

    Defensive — `simplify_order_target` is meant to be real ig_idxs, but
    silently filtering rather than erroring matches the signature-side
    behavior and avoids surprising spec authors.
    """
    baseline = _sig(simplify_order=(99, 99))
    candidate = _sig(simplify_order=(37, 41, 99))
    target = (37, -1, 41)  # `-1` is filtered out before comparison
    result = compute_lex_score(baseline, candidate, target)
    assert result.simplify_score.target_prefix == (37, 41)
    assert result.simplify_score.common_prefix_length == 2
    assert result.score == 0


# ---------------------------------------------------------------------------
# Polarity classifier tests (deferred debt #20 — lbDvd_80018A2C campaign)
# ---------------------------------------------------------------------------


def test_classify_polarity_safe_non_volatile() -> None:
    """Target physicals in r25-r31 are safe for --want-first.

    Non-volatiles are dispensed top-down from r31 by
    obtain_nonvolatile_register, so positioning target ig_idx values at
    the front of simplify order naturally gives them r31, r30, ...
    """
    # grVenom-style: target physicals are non-volatiles
    polarity = classify_polarity({42: 31, 32: 30})
    assert polarity is Polarity.SAFE


def test_classify_polarity_safe_r3() -> None:
    """r3 is the lowest workingMask bit, also safe for --want-first."""
    polarity = classify_polarity({42: 3})
    assert polarity is Polarity.SAFE


def test_classify_polarity_uncertain_mid_volatile() -> None:
    """r4-r9 may or may not work depending on interference."""
    polarity = classify_polarity({42: 5})
    assert polarity is Polarity.UNCERTAIN


def test_classify_polarity_wrong_high_volatile() -> None:
    """r10-r12 are wrong polarity for --want-first.

    Volatile dispense is lowest-first; to land on r10/r11/r12, target
    ig_idx values need to be at LATE simplify positions so r3-r9 are
    consumed first. lbDvd_80018A2C is canonical.
    """
    # lbDvd-style: target physicals are r10, r12
    polarity = classify_polarity({44: 10, 46: 12})
    assert polarity is Polarity.WRONG_POLARITY


def test_classify_polarity_mixed_picks_worst() -> None:
    """If any target physical is wrong polarity, classify as WRONG."""
    polarity = classify_polarity({42: 31, 44: 12})
    assert polarity is Polarity.WRONG_POLARITY


def test_classify_polarity_uncertain_dominates_safe() -> None:
    """If any target is UNCERTAIN and none are WRONG, return UNCERTAIN."""
    polarity = classify_polarity({42: 31, 44: 5})
    assert polarity is Polarity.UNCERTAIN


def test_classify_polarity_empty_returns_safe() -> None:
    """Empty force_phys (i.e., no force-phys mapping was provided) is
    SAFE — the polarity check is opt-in via providing the mapping."""
    polarity = classify_polarity({})
    assert polarity is Polarity.SAFE


def test_high_volatile_regs_constant() -> None:
    """Document the exact set so future readers know the threshold."""
    assert HIGH_VOLATILE_REGS == frozenset({10, 11, 12})


def test_uncertain_volatile_regs_constant() -> None:
    """Document the exact set so future readers know the mid-volatile range."""
    assert UNCERTAIN_VOLATILE_REGS == frozenset({4, 5, 6, 7, 8, 9})


# ---------------------------------------------------------------------------
# force_phys field tests (Task 2 — pre-flight polarity check plumbing)
# ---------------------------------------------------------------------------


def _write_spec(tmp_path: Path, body: str, baseline_name: str = "base.txt") -> Path:
    """Helper: write a target spec YAML to tmp_path with a baseline_dump
    file that exists. Returns the spec path."""
    baseline = tmp_path / baseline_name
    baseline.write_text("pcdump placeholder", encoding="utf-8")
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text(textwrap.dedent(body), encoding="utf-8")
    return spec_path


def test_load_spec_without_force_phys(tmp_path: Path) -> None:
    """Existing specs without force_phys still load (backward-compat)."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: foo_func
        simplify_order_target: [34, 37, 32]
        class_id: 0
        baseline_dump: base.txt
        """,
    )

    spec = load_simplify_order_target_spec(spec_path)
    assert spec.function == "foo_func"
    assert spec.simplify_order_target == (34, 37, 32)
    assert spec.force_phys == {}  # default to empty dict


def test_load_spec_with_force_phys(tmp_path: Path) -> None:
    """force_phys parses as ig_idx (key, int) -> phys_reg (value, int)."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: gm_80173EEC
        simplify_order_target: [34, 37, 32]
        class_id: 0
        baseline_dump: base.txt
        force_phys:
          34: 31
          37: 30
          32: 29
          42: 28
          52: 28
          38: 28
        """,
    )

    spec = load_simplify_order_target_spec(spec_path)
    assert spec.force_phys == {34: 31, 37: 30, 32: 29, 42: 28, 52: 28, 38: 28}


def test_load_spec_force_phys_must_be_mapping(tmp_path: Path) -> None:
    """force_phys must be a YAML mapping, not a list or string."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: foo
        simplify_order_target: [1, 2]
        baseline_dump: base.txt
        force_phys:
          - 1
          - 2
        """,
    )
    with pytest.raises(SimplifyOrderSpecError, match="force_phys.*mapping"):
        load_simplify_order_target_spec(spec_path)


def test_load_spec_force_phys_rejects_non_int_keys(tmp_path: Path) -> None:
    """ig_idx keys must be integers."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: foo
        simplify_order_target: [1, 2]
        baseline_dump: base.txt
        force_phys:
          "thirty-four": 31
        """,
    )
    with pytest.raises(SimplifyOrderSpecError, match="force_phys.*integer key"):
        load_simplify_order_target_spec(spec_path)


def test_load_spec_force_phys_rejects_non_int_values(tmp_path: Path) -> None:
    """phys_reg values must be integers (the bare register number, not 'r31')."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: foo
        simplify_order_target: [1, 2]
        baseline_dump: base.txt
        force_phys:
          34: "r31"
        """,
    )
    with pytest.raises(SimplifyOrderSpecError, match="force_phys.*integer value"):
        load_simplify_order_target_spec(spec_path)


# ---------------------------------------------------------------------------
# find_coalesced_targets tests (Phase 2 Task 1 — coalesce-preservation helper)
# ---------------------------------------------------------------------------


from src.mwcc_debug.simplify_order_scoring import find_coalesced_targets
from src.mwcc_debug.colorgraph_parser import parse_hook_events, find_function


def _build_minimal_events_text(
    function: str,
    natural_mappings: list[tuple[int, int]],
    class_id: int = 0,
) -> str:
    """Build a minimal pcdump text with a single COALESCE section."""
    lines = [
        f"Starting function {function}",
        "",
        f"[COALESCE] enter class={class_id} n_virtuals=10",
        "[COALESCE] natural mappings (virt -> root):",
    ]
    for virt, root in natural_mappings:
        lines.append(f"  {virt} -> {root}")
    lines.extend([
        f"[COALESCE] exit class={class_id} n_virtuals=10 distinct_roots=8 forced=0",
        "",
        f"IG CONSTRUCTED (class={class_id}, n_nodes=10)",
    ])
    return "\n".join(lines)


def test_find_coalesced_targets_none_coalesced() -> None:
    """Returns empty set when no target ig_idx is coalesced."""
    text = _build_minimal_events_text(
        "test_fn",
        natural_mappings=[(5, 4), (6, 3)],
    )
    events = parse_hook_events(text)
    fn = find_function(events, "test_fn")
    assert fn is not None

    result = find_coalesced_targets(fn, targets={34, 37, 32}, class_id=0)
    assert result == set()


def test_find_coalesced_targets_one_coalesced() -> None:
    """Returns the single coalesced target ig_idx."""
    text = _build_minimal_events_text(
        "test_fn",
        natural_mappings=[(38, 3), (5, 4)],
    )
    events = parse_hook_events(text)
    fn = find_function(events, "test_fn")

    result = find_coalesced_targets(fn, targets={34, 37, 32, 38, 42, 52}, class_id=0)
    assert result == {38}


def test_find_coalesced_targets_multiple_coalesced() -> None:
    """Returns all coalesced target ig_idx values (gm_80173EEC output-139-1 case)."""
    text = _build_minimal_events_text(
        "gm_test",
        natural_mappings=[(42, 3), (38, 3), (99, 50)],
    )
    events = parse_hook_events(text)
    fn = find_function(events, "gm_test")

    result = find_coalesced_targets(
        fn, targets={34, 37, 32, 42, 52, 38}, class_id=0
    )
    assert result == {42, 38}


def test_find_coalesced_targets_wrong_class_ignored() -> None:
    """Mappings in other register classes are ignored."""
    text = _build_minimal_events_text(
        "test_fn",
        natural_mappings=[(38, 3)],
        class_id=1,
    )
    events = parse_hook_events(text)
    fn = find_function(events, "test_fn")

    result = find_coalesced_targets(fn, targets={38}, class_id=0)
    assert result == set()


def test_find_coalesced_targets_empty_targets_returns_empty() -> None:
    """Empty target set always returns empty (no work to do)."""
    text = _build_minimal_events_text(
        "test_fn",
        natural_mappings=[(38, 3), (42, 3)],
    )
    events = parse_hook_events(text)
    fn = find_function(events, "test_fn")

    result = find_coalesced_targets(fn, targets=set(), class_id=0)
    assert result == set()


def test_find_coalesced_targets_root_in_targets_not_coalesced() -> None:
    """A target ig_idx appearing only as a coalesce ROOT (RHS) is NOT
    coalesced — it's the destination, not the alias."""
    text = _build_minimal_events_text(
        "test_fn",
        natural_mappings=[(5, 32)],
    )
    events = parse_hook_events(text)
    fn = find_function(events, "test_fn")

    result = find_coalesced_targets(fn, targets={32}, class_id=0)
    assert result == set()


# ---------------------------------------------------------------------------
# coalesce_preservation field tests (Phase 2 Task 2)
# ---------------------------------------------------------------------------


def test_load_spec_default_coalesce_preservation_true(tmp_path: Path) -> None:
    """Specs without explicit coalesce_preservation default to True."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: gm_test
        simplify_order_target: [34, 37, 32]
        class_id: 0
        baseline_dump: base.txt
        force_phys:
          34: 31
          37: 30
        """,
    )
    spec = load_simplify_order_target_spec(spec_path)
    assert spec.coalesce_preservation is True


def test_load_spec_coalesce_preservation_explicit_false(tmp_path: Path) -> None:
    """Specs can opt out via coalesce_preservation: false."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: gm_test
        simplify_order_target: [34, 37, 32]
        baseline_dump: base.txt
        force_phys:
          34: 31
        coalesce_preservation: false
        """,
    )
    spec = load_simplify_order_target_spec(spec_path)
    assert spec.coalesce_preservation is False


def test_load_spec_coalesce_preservation_explicit_true(tmp_path: Path) -> None:
    """coalesce_preservation: true loads correctly (explicit-default case)."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: gm_test
        simplify_order_target: [34, 37, 32]
        baseline_dump: base.txt
        coalesce_preservation: true
        """,
    )
    spec = load_simplify_order_target_spec(spec_path)
    assert spec.coalesce_preservation is True


def test_load_spec_coalesce_preservation_rejects_non_bool(tmp_path: Path) -> None:
    """coalesce_preservation must be a boolean."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: gm_test
        simplify_order_target: [34, 37, 32]
        baseline_dump: base.txt
        coalesce_preservation: "yes"
        """,
    )
    with pytest.raises(SimplifyOrderSpecError, match="coalesce_preservation.*bool"):
        load_simplify_order_target_spec(spec_path)


# ---------------------------------------------------------------------------
# compute_lex_score with coalesce-preservation constraint
# (Phase 2 Task 3 — wires constraint into compute_lex_score)
# ---------------------------------------------------------------------------


from src.mwcc_debug.simplify_order_scoring import STRUCTURAL_REJECTION_SCORE


def _make_spec_for_coalesce_tests(tmp_path: Path, *, coalesce_preservation: bool = True) -> "SimplifyOrderTargetSpec":
    """Build a SimplifyOrderTargetSpec with force_phys={42: 31, 34: 30}.

    Used by the coalesce-preservation compute_lex_score tests. The
    baseline_dump file is written to tmp_path so spec validation passes.
    """
    baseline = tmp_path / "base.txt"
    baseline.write_text("pcdump placeholder", encoding="utf-8")
    spec_path = tmp_path / "target.yaml"
    import textwrap
    spec_path.write_text(textwrap.dedent(f"""\
        function: test_fn
        simplify_order_target: [34, 37]
        class_id: 0
        baseline_dump: {baseline}
        force_phys:
          42: 31
          34: 30
        coalesce_preservation: {"true" if coalesce_preservation else "false"}
    """), encoding="utf-8")
    return load_simplify_order_target_spec(spec_path)


def _make_candidate_events_no_coalesce(function: str) -> "FunctionEvents":
    """FunctionEvents for a candidate where no force_phys target is coalesced.

    Natural coalesce mappings: only ig_idx 5 and 6 are coalesced (not in
    the force_phys target set {42, 34}).
    """
    text = _build_minimal_events_text(
        function,
        natural_mappings=[(5, 4), (6, 3)],
    )
    events_list = parse_hook_events(text)
    fn = find_function(events_list, function)
    assert fn is not None
    return fn


def _make_candidate_events_coalesced_target(function: str) -> "FunctionEvents":
    """FunctionEvents for a candidate where ig_idx 42 (a force_phys key) is coalesced.

    Natural coalesce mappings: ig_idx 42 -> root 3 (42 is in the force_phys
    target set {42, 34}), and ig_idx 5 -> root 4 (not a target).
    """
    text = _build_minimal_events_text(
        function,
        natural_mappings=[(42, 3), (5, 4)],
    )
    events_list = parse_hook_events(text)
    fn = find_function(events_list, function)
    assert fn is not None
    return fn


# Import FunctionEvents for type annotation use in helpers (already available
# from the parse_hook_events import above).
from src.mwcc_debug.colorgraph_parser import FunctionEvents  # noqa: E402


def test_compute_lex_score_no_coalesce_no_rejection(tmp_path: Path) -> None:
    """No target ig_idx coalesced → normal scoring applies.

    Candidate pcdump has natural coalesce mappings that don't touch
    the target ig_idx set. The score is the normal lex-encoded value,
    not the sentinel; structural_rejection is False.
    """
    spec = _make_spec_for_coalesce_tests(tmp_path, coalesce_preservation=True)
    baseline = _sig(simplify_order=(99, 99))
    candidate = _sig(simplify_order=(34, 37, 17))
    candidate_events = _make_candidate_events_no_coalesce("test_fn")

    result = compute_lex_score(
        baseline, candidate, spec.simplify_order_target,
        candidate_events=candidate_events,
        spec=spec,
    )

    assert result.score < STRUCTURAL_REJECTION_SCORE
    assert result.structural_rejection is False
    assert result.coalesced_targets == frozenset()


def test_compute_lex_score_coalesced_target_rejected(tmp_path: Path) -> None:
    """Coalesced target ig_idx → score is the structural rejection sentinel.

    Uses a candidate where ig_idx 42 (in the force_phys target set) is
    coalesced into root 3. The score must be the sentinel, and the new
    flag fields must reflect the rejection.
    """
    spec = _make_spec_for_coalesce_tests(tmp_path, coalesce_preservation=True)
    baseline = _sig(simplify_order=(99, 99))
    candidate = _sig(simplify_order=(34, 37, 42))
    candidate_events = _make_candidate_events_coalesced_target("test_fn")

    result = compute_lex_score(
        baseline, candidate, spec.simplify_order_target,
        candidate_events=candidate_events,
        spec=spec,
    )

    assert result.score == STRUCTURAL_REJECTION_SCORE
    assert result.structural_rejection is True
    assert 42 in result.coalesced_targets


def test_compute_lex_score_coalesce_preservation_disabled(tmp_path: Path) -> None:
    """coalesce_preservation=False → constraint skipped, normal scoring.

    Same fixture as the rejection test, but the spec's
    coalesce_preservation is set to False. Expected: normal scoring
    runs, no rejection sentinel, structural_rejection is False.
    """
    spec = _make_spec_for_coalesce_tests(tmp_path, coalesce_preservation=False)
    baseline = _sig(simplify_order=(99, 99))
    candidate = _sig(simplify_order=(34, 37, 42))
    candidate_events = _make_candidate_events_coalesced_target("test_fn")

    result = compute_lex_score(
        baseline, candidate, spec.simplify_order_target,
        candidate_events=candidate_events,
        spec=spec,
    )

    assert result.score < STRUCTURAL_REJECTION_SCORE
    assert result.structural_rejection is False


def test_compute_lex_score_no_force_phys_skips_check(tmp_path: Path) -> None:
    """No force_phys → coalesce check skipped (nothing to check).

    Spec with force_phys={} (default). Even if the candidate has
    coalesce events for ig_idx values, the constraint is a no-op because
    there are no target ig_idx values to protect.
    """
    # Build a spec without force_phys
    baseline_file = tmp_path / "base.txt"
    baseline_file.write_text("pcdump placeholder", encoding="utf-8")
    spec_path = tmp_path / "target.yaml"
    import textwrap
    spec_path.write_text(textwrap.dedent(f"""\
        function: test_fn
        simplify_order_target: [34, 37]
        class_id: 0
        baseline_dump: {baseline_file}
    """), encoding="utf-8")
    spec = load_simplify_order_target_spec(spec_path)
    assert spec.force_phys == {}

    baseline = _sig(simplify_order=(99, 99))
    candidate = _sig(simplify_order=(34, 37, 42))
    # Even though the candidate coalesces 42, there's no force_phys target
    candidate_events = _make_candidate_events_coalesced_target("test_fn")

    result = compute_lex_score(
        baseline, candidate, spec.simplify_order_target,
        candidate_events=candidate_events,
        spec=spec,
    )

    assert result.score < STRUCTURAL_REJECTION_SCORE
    assert result.structural_rejection is False
    assert result.coalesced_targets == frozenset()


# ---------------------------------------------------------------------------
# common_suffix_length tests (Phase 3 Task 1 — late-target scorer foundation)
# ---------------------------------------------------------------------------


from src.mwcc_debug.simplify_order_scoring import (
    common_suffix_length,
)


def test_common_suffix_length_full_match() -> None:
    """When the observed suffix matches the target exactly, returns target_len."""
    observed = (10, 20, 46, 44)
    target = (46, 44)
    assert common_suffix_length(observed, target) == 2


def test_common_suffix_length_partial_match() -> None:
    """Returns the length of the longest matching suffix."""
    observed = (10, 20, 99, 44)
    target = (46, 44)
    assert common_suffix_length(observed, target) == 1


def test_common_suffix_length_no_match() -> None:
    """Zero when no suffix matches."""
    observed = (10, 20, 30)
    target = (46, 44)
    assert common_suffix_length(observed, target) == 0


def test_common_suffix_length_empty_observed() -> None:
    """Empty observed → 0."""
    observed: tuple[int, ...] = ()
    target = (46, 44)
    assert common_suffix_length(observed, target) == 0


def test_common_suffix_length_empty_target() -> None:
    """Empty target → 0 (no target positions to match)."""
    observed = (10, 20, 46, 44)
    target: tuple[int, ...] = ()
    assert common_suffix_length(observed, target) == 0


def test_common_suffix_length_observed_shorter_than_target() -> None:
    """If observed is shorter than target, can match at most observed length."""
    observed = (44,)
    target = (46, 44)
    # observed[-1:] == (44,), target[-1:] == (44,) → match length 1
    assert common_suffix_length(observed, target) == 1


def test_common_suffix_length_target_subset_of_observed() -> None:
    """Long observed with short target — match starts from the end."""
    observed = (1, 2, 3, 4, 5, 46, 44)
    target = (46, 44)
    assert common_suffix_length(observed, target) == 2


# ---------------------------------------------------------------------------
# simplify_order_target_late field tests (Phase 3 Task 2)
# ---------------------------------------------------------------------------


def test_load_spec_simplify_order_target_late(tmp_path: Path) -> None:
    """Specs with simplify_order_target_late parse correctly."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: lbDvd_test
        simplify_order_target_late: [46, 44]
        class_id: 0
        baseline_dump: base.txt
        force_phys:
          44: 10
          46: 12
        """,
    )
    spec = load_simplify_order_target_spec(spec_path)
    assert spec.simplify_order_target_late == (46, 44)
    assert spec.simplify_order_target == ()


def test_load_spec_simplify_order_target_late_default_empty(tmp_path: Path) -> None:
    """Specs without simplify_order_target_late default to empty tuple."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: gm_test
        simplify_order_target: [34, 37, 32]
        class_id: 0
        baseline_dump: base.txt
        """,
    )
    spec = load_simplify_order_target_spec(spec_path)
    assert spec.simplify_order_target_late == ()
    assert spec.simplify_order_target == (34, 37, 32)


def test_load_spec_rejects_both_target_fields(tmp_path: Path) -> None:
    """Cannot have both simplify_order_target and simplify_order_target_late."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: x
        simplify_order_target: [1, 2]
        simplify_order_target_late: [3, 4]
        class_id: 0
        baseline_dump: base.txt
        """,
    )
    with pytest.raises(
        SimplifyOrderSpecError,
        match="mutually exclusive|both.*target",
    ):
        load_simplify_order_target_spec(spec_path)


def test_load_spec_requires_at_least_one_target(tmp_path: Path) -> None:
    """At least one of simplify_order_target or simplify_order_target_late
    must be provided."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: x
        class_id: 0
        baseline_dump: base.txt
        """,
    )
    with pytest.raises(
        SimplifyOrderSpecError,
        match="missing.*simplify_order_target",
    ):
        load_simplify_order_target_spec(spec_path)


def test_load_spec_simplify_order_target_late_rejects_non_int(tmp_path: Path) -> None:
    """simplify_order_target_late entries must be integers."""
    spec_path = _write_spec(
        tmp_path,
        """
        function: x
        simplify_order_target_late: ["a", "b"]
        class_id: 0
        baseline_dump: base.txt
        """,
    )
    with pytest.raises(
        SimplifyOrderSpecError,
        match="simplify_order_target_late.*integer",
    ):
        load_simplify_order_target_spec(spec_path)


# ---------------------------------------------------------------------------
# compute_lex_score late-mode tests (Phase 3 Task 3)
# ---------------------------------------------------------------------------


def _make_spec_for_late_tests(
    tmp_path: Path,
    *,
    force_phys: dict | None = None,
    coalesce_preservation: bool = True,
) -> "SimplifyOrderTargetSpec":
    """Build a SimplifyOrderTargetSpec with simplify_order_target_late=(46, 44).

    Used by the late-mode compute_lex_score tests. force_phys defaults to
    {46: 12, 44: 10} which are HIGH_VOLATILE_REGS — the canonical late-mode
    use case. The baseline_dump file is written to tmp_path so spec
    validation passes.
    """
    baseline = tmp_path / "base_late.txt"
    baseline.write_text("pcdump placeholder", encoding="utf-8")
    spec_path = tmp_path / "target_late.yaml"
    if force_phys is None:
        force_phys = {46: 12, 44: 10}
    fp_lines = "\n".join(f"          {k}: {v}" for k, v in force_phys.items())
    spec_path.write_text(textwrap.dedent(f"""\
        function: test_fn_late
        simplify_order_target_late: [46, 44]
        class_id: 0
        baseline_dump: {baseline}
        force_phys:
{fp_lines}
        coalesce_preservation: {"true" if coalesce_preservation else "false"}
    """), encoding="utf-8")
    return load_simplify_order_target_spec(spec_path)


def test_compute_lex_score_late_full_match(tmp_path: Path) -> None:
    """Candidate whose filtered simplify order ENDS with [46, 44] → full suffix match.

    simplify_order_target_late=(46, 44), candidate ends with (46, 44).
    Expected: common_suffix_length == 2, score < LEX_BIG (no miss penalty).
    """
    spec = _make_spec_for_late_tests(tmp_path, force_phys={46: 12, 44: 10})
    baseline = _sig(simplify_order=(99, 99))
    # Candidate order ends with the target suffix: [1, 2, 3, 46, 44]
    candidate = _sig(simplify_order=(1, 2, 3, 46, 44))

    result = compute_lex_score(
        baseline, candidate, spec.simplify_order_target,
        spec=spec,
    )

    assert result.common_suffix_length == 2
    assert result.score < LEX_BIG


def test_compute_lex_score_late_partial_match(tmp_path: Path) -> None:
    """Candidate whose filtered simplify order ends with [99, 44] → partial suffix match.

    simplify_order_target_late=(46, 44), candidate ends with (99, 44):
    only the last element matches. Expected: common_suffix_length == 1,
    LEX_BIG <= score < 2*LEX_BIG.
    """
    spec = _make_spec_for_late_tests(tmp_path, force_phys={46: 12, 44: 10})
    baseline = _sig(simplify_order=(99, 99))
    # Candidate ends with 99, 44 — only the last slot matches
    candidate = _sig(simplify_order=(1, 2, 3, 99, 44))

    result = compute_lex_score(
        baseline, candidate, spec.simplify_order_target,
        spec=spec,
    )

    assert result.common_suffix_length == 1
    assert LEX_BIG <= result.score < 2 * LEX_BIG


def test_compute_lex_score_late_constraint_still_applies(tmp_path: Path) -> None:
    """Coalesce-preservation constraint runs BEFORE late-mode scoring.

    Candidate has ig_idx 46 (a force_phys key) coalesced. The spec uses
    simplify_order_target_late=(46, 44) with coalesce_preservation=True.
    Expected: score == STRUCTURAL_REJECTION_SCORE, structural_rejection is True.
    The coalesce check fires BEFORE late-mode scoring.
    """
    spec = _make_spec_for_late_tests(
        tmp_path, force_phys={46: 12, 44: 10}, coalesce_preservation=True
    )
    baseline = _sig(simplify_order=(99, 99))
    # Candidate ends with the target — would be a full match in late-mode
    candidate = _sig(simplify_order=(1, 2, 3, 46, 44))

    # Build candidate_events where ig_idx 46 is coalesced (LHS of natural mapping)
    text = _build_minimal_events_text(
        "test_fn_late",
        natural_mappings=[(46, 3)],  # 46 is coalesced alias -> root 3
    )
    events_list = parse_hook_events(text)
    candidate_events = find_function(events_list, "test_fn_late")
    assert candidate_events is not None

    result = compute_lex_score(
        baseline, candidate, spec.simplify_order_target,
        candidate_events=candidate_events,
        spec=spec,
    )

    assert result.score == STRUCTURAL_REJECTION_SCORE
    assert result.structural_rejection is True


def test_compute_lex_score_uses_late_when_late_set(tmp_path: Path) -> None:
    """Late-mode does suffix matching, NOT prefix matching.

    Candidate's filtered simplify order is [46, 44, 1, 2, 3] — it STARTS
    with [46, 44] but does NOT end with them. spec has
    simplify_order_target_late=(46, 44).

    If compute_lex_score were using prefix matching (front-mode), it would
    see common_prefix_length=2 and score=0. Instead, with suffix matching,
    the suffix is [2, 3], not [46, 44], so common_suffix_length=0 and
    score = 2 * LEX_BIG.

    This proves the function is using suffix matching, not accidentally
    doing prefix matching.
    """
    spec = _make_spec_for_late_tests(tmp_path, force_phys={46: 12, 44: 10})
    baseline = _sig(simplify_order=(99, 99))
    # Candidate STARTS with target — would win if prefix-matching
    # but ENDS with [1, 2, 3], so suffix matching sees no match
    candidate = _sig(simplify_order=(46, 44, 1, 2, 3))

    result = compute_lex_score(
        baseline, candidate, spec.simplify_order_target,
        spec=spec,
    )

    # Suffix of [46, 44, 1, 2, 3] against target [46, 44]:
    #   observed[-1]=3 != target[-1]=44 → common_suffix_length=0
    assert result.common_suffix_length == 0
    # score = (2 - 0) * LEX_BIG + distance = 2 * LEX_BIG (+ small distance)
    assert result.score >= 2 * LEX_BIG


# ---------------------------------------------------------------------------
# classify_polarity target_position tests (Phase 3 Task 4)
# ---------------------------------------------------------------------------


def test_classify_polarity_late_high_volatile_safe() -> None:
    """For --want-late, high-volatile (r10-r12) is the CORRECT polarity."""
    polarity = classify_polarity(
        {44: 10, 46: 12},
        target_position="late",
    )
    assert polarity is Polarity.SAFE


def test_classify_polarity_late_top_non_volatile_wrong() -> None:
    """For --want-late, top-down non-volatiles (r28-r31) are the WRONG
    polarity (they're dispensed first by obtain_nonvolatile_register, so
    target ig_idx at end won't get them)."""
    polarity = classify_polarity(
        {34: 31, 37: 30},
        target_position="late",
    )
    assert polarity is Polarity.WRONG_POLARITY


def test_classify_polarity_late_r3_wrong() -> None:
    """For --want-late, r3 (lowest workingMask bit) is wrong polarity
    (consumed first; target at end won't get it)."""
    polarity = classify_polarity(
        {44: 3},
        target_position="late",
    )
    assert polarity is Polarity.WRONG_POLARITY


def test_classify_polarity_late_mid_volatile_uncertain() -> None:
    """For --want-late, mid-volatile (r4-r9) is UNCERTAIN — depends on
    interference."""
    polarity = classify_polarity(
        {44: 5, 46: 6},
        target_position="late",
    )
    assert polarity is Polarity.UNCERTAIN


def test_classify_polarity_late_empty_safe() -> None:
    """Empty force_phys with target_position=late: SAFE (no targets to check)."""
    polarity = classify_polarity({}, target_position="late")
    assert polarity is Polarity.SAFE


def test_classify_polarity_default_position_is_first() -> None:
    """Default target_position=first preserves Phase 1 behavior."""
    polarity = classify_polarity({44: 10, 46: 12})  # no target_position kw
    assert polarity is Polarity.WRONG_POLARITY  # same as target_position=first


def test_classify_polarity_first_high_volatile_still_wrong() -> None:
    """Explicit target_position=first preserves the Phase 1 classification."""
    polarity = classify_polarity(
        {44: 10, 46: 12},
        target_position="first",
    )
    assert polarity is Polarity.WRONG_POLARITY
