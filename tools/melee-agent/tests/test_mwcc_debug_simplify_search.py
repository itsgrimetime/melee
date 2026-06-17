"""Unit tests for mwcc_debug simplify-order search core."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

from src.mwcc_debug.colorgraph_parser import (
    CoalesceSection,
    ColorgraphDecision,
    ColorgraphSection,
    FunctionEvents,
    SimplifyEntry,
    SimplifySection,
)
from src.mwcc_debug.simplify_search import (
    BaselineSignature,
    CombinedScore,
    DEFAULT_COMBINED_ALPHA,
    CompileFailureSummary,
    FunctionContext,
    GateResult,
    PrecolorDistance,
    RejectedCandidate,
    SearchResult,
    SimplifyScore,
    SourceVariant,
    baseline_signature,
    combined_score,
    precolor_distance,
    preserve_precolor,
    score_simplify_order,
    search,
)


def _decision(
    *,
    iter_idx: int,
    ig_idx: int,
    assigned: int = 30,
    interferers: list[tuple[int, int]] | None = None,
) -> ColorgraphDecision:
    return ColorgraphDecision(
        iter_idx=iter_idx,
        ig_idx=ig_idx,
        assigned_reg=assigned,
        degree=len(interferers or []),
        n_interferers=len(interferers or []),
        flags=0,
        interferers=interferers or [],
    )


def _events_for_class(
    *,
    class_id: int = 0,
    interference_edges: list[tuple[int, int]] | None = None,
    simplify_order: list[int] | None = None,
    coalesce_mappings: list[tuple[int, int]] | None = None,
    spilled_ig_idxs: set[int] | None = None,
    assigned_by_ig: dict[int, int] | None = None,
) -> FunctionEvents:
    """Build a single-class FunctionEvents from the four components."""
    interference_edges = interference_edges or []
    simplify_order = simplify_order or [32, 33]
    coalesce_mappings = coalesce_mappings or []
    spilled_ig_idxs = spilled_ig_idxs or set()
    assigned_by_ig = assigned_by_ig or {}

    adj: dict[int, list[tuple[int, int]]] = {}
    for a, b in interference_edges:
        adj.setdefault(a, []).append((b, 30))
        adj.setdefault(b, []).append((a, 30))

    ig_idxs = sorted(set(simplify_order) | set(adj.keys()) | set(assigned_by_ig))
    decisions = [
        _decision(
            iter_idx=i,
            ig_idx=ig,
            assigned=assigned_by_ig.get(ig, 30),
            interferers=sorted(adj.get(ig, [])),
        )
        for i, ig in enumerate(ig_idxs)
    ]

    events = FunctionEvents(name="fn_test")
    events.colorgraph_sections.append(ColorgraphSection(
        class_id=class_id,
        result=1,
        n_nodes=len(ig_idxs),
        decisions=decisions,
    ))
    events.simplify_sections.append(SimplifySection(
        class_id=class_id,
        n_colors=29,
        n_class_regs=40,
        entries=[
            SimplifyEntry(
                iter_idx=i,
                ig_idx=ig,
                degree=1,
                array_size=1,
                flags=0x08 if ig in spilled_ig_idxs else 0,
                spilled=ig in spilled_ig_idxs,
            )
            for i, ig in enumerate(simplify_order)
        ],
    ))
    events.coalesce_sections.append(CoalesceSection(
        class_id=class_id,
        n_virtuals=40,
        mappings=list(coalesce_mappings),
        distinct_roots=40 - len(coalesce_mappings),
        forced_count=0,
    ))
    return events


# ---------------------------------------------------------------------------
# BaselineSignature
# ---------------------------------------------------------------------------


def test_baseline_signature_extracts_all_four_components() -> None:
    events = _events_for_class(
        interference_edges=[(32, 33), (32, 34)],
        simplify_order=[32, 33, 34],
        coalesce_mappings=[(35, 32)],
        spilled_ig_idxs={34},
    )

    sig = baseline_signature(events, class_id=0)

    assert sig.interference_edges == frozenset({(32, 33), (32, 34)})
    assert sig.coalesce_mappings == frozenset({(35, 32)})
    assert sig.spill_set == frozenset({34})
    assert sig.simplify_order == (32, 33, 34)


def test_baseline_signature_normalizes_interference_edges() -> None:
    """Edges in the IG are symmetric — (a, b) == (b, a). We canonicalize
    to (min, max), so the signature dedupes both directions to one entry."""
    events = _events_for_class(
        interference_edges=[(40, 32), (33, 32)],
        simplify_order=[32, 33, 40],
    )

    sig = baseline_signature(events, class_id=0)

    assert sig.interference_edges == frozenset({(32, 33), (32, 40)})


def test_baseline_signature_empty_for_missing_class() -> None:
    events = _events_for_class(class_id=0, simplify_order=[32, 33])

    sig = baseline_signature(events, class_id=1)

    assert sig.simplify_order == ()
    assert sig.interference_edges == frozenset()
    assert sig.coalesce_mappings == frozenset()
    assert sig.spill_set == frozenset()


def test_baseline_signature_is_hashable() -> None:
    """BaselineSignature is frozen dataclass — used in sets/maps for dedup."""
    events = _events_for_class(simplify_order=[32, 33])
    sig_a = baseline_signature(events, class_id=0)
    sig_b = baseline_signature(events, class_id=0)

    s = {sig_a, sig_b}

    assert len(s) == 1


# ---------------------------------------------------------------------------
# Preserve-precolor gate
# ---------------------------------------------------------------------------


def test_gate_passes_when_only_simplify_order_differs() -> None:
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[32, 33, 34],
            coalesce_mappings=[(35, 32)],
        ),
        class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[33, 32, 34],
            coalesce_mappings=[(35, 32)],
        ),
        class_id=0,
    )

    result = preserve_precolor(baseline, candidate)

    assert result.passed is True
    assert result.reason == ""


def test_gate_rejects_when_interference_differs() -> None:
    baseline = baseline_signature(
        _events_for_class(interference_edges=[(32, 33)]), class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(interference_edges=[(32, 33), (32, 34)]), class_id=0,
    )

    result = preserve_precolor(baseline, candidate)

    assert result.passed is False
    assert "interference" in result.reason.lower()


def test_gate_rejects_when_coalesce_differs() -> None:
    baseline = baseline_signature(
        _events_for_class(
            simplify_order=[32, 33],
            coalesce_mappings=[(35, 32)],
        ),
        class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(
            simplify_order=[32, 33],
            coalesce_mappings=[(37, 32)],
        ),
        class_id=0,
    )

    result = preserve_precolor(baseline, candidate)

    assert result.passed is False
    assert "coalesce" in result.reason.lower()


def test_gate_rejects_when_spill_differs() -> None:
    baseline = baseline_signature(
        _events_for_class(simplify_order=[32, 33, 40], spilled_ig_idxs=set()),
        class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(simplify_order=[32, 33, 40], spilled_ig_idxs={40}),
        class_id=0,
    )

    result = preserve_precolor(baseline, candidate)

    assert result.passed is False
    assert "spill" in result.reason.lower()


def test_gate_passes_when_everything_matches() -> None:
    """If even simplify order matches, the gate still passes — the
    *scorer* decides whether this is a 'win' or 'no progress'."""
    events = _events_for_class(simplify_order=[32, 33])
    sig = baseline_signature(events, class_id=0)

    result = preserve_precolor(sig, sig)

    assert result.passed is True


# ---------------------------------------------------------------------------
# Simplify-order scoring
# ---------------------------------------------------------------------------


def test_score_exact_match_when_observed_starts_with_target() -> None:
    target = (42, 32)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[32, 42, 33]), class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(simplify_order=[42, 32, 33]), class_id=0,
    )

    score = score_simplify_order(baseline, candidate, target)

    assert score.is_exact_match is True
    assert score.common_prefix_length == 2
    assert score.baseline_common_prefix_length == 0
    assert score.observed_prefix == (42, 32)
    assert score.target_prefix == (42, 32)


def test_score_partial_progress_when_prefix_grows() -> None:
    target = (42, 32, 50)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[32, 42, 50]), class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(simplify_order=[42, 99, 50]), class_id=0,
    )

    score = score_simplify_order(baseline, candidate, target)

    assert score.is_exact_match is False
    assert score.common_prefix_length == 1
    assert score.baseline_common_prefix_length == 0


def test_score_no_progress_when_prefix_matches_baseline() -> None:
    target = (42, 32)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[32, 33]), class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(simplify_order=[33, 32]), class_id=0,
    )

    score = score_simplify_order(baseline, candidate, target)

    assert score.is_exact_match is False
    # Neither matches first position of target -> 0 length.
    assert score.common_prefix_length == 0
    assert score.baseline_common_prefix_length == 0


def test_score_regression_when_prefix_shrinks_relative_to_baseline() -> None:
    """If baseline already matches the first item but candidate doesn't,
    score is a regression — observable as common_prefix_length lower
    than baseline_common_prefix_length."""
    target = (42, 32)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[42, 99]), class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(simplify_order=[33, 99]), class_id=0,
    )

    score = score_simplify_order(baseline, candidate, target)

    assert score.is_exact_match is False
    assert score.common_prefix_length == 0
    assert score.baseline_common_prefix_length == 1


def test_score_with_empty_target_treats_as_trivial_match() -> None:
    target: tuple[int, ...] = ()
    baseline = baseline_signature(
        _events_for_class(simplify_order=[32, 33]), class_id=0,
    )

    score = score_simplify_order(baseline, baseline, target)

    assert score.is_exact_match is True
    assert score.common_prefix_length == 0


# ---------------------------------------------------------------------------
# Search driver
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path) -> FunctionContext:
    source = tmp_path / "src" / "melee" / "mn" / "fn_test.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_test(void) {}\n", encoding="utf-8")
    return FunctionContext(
        function="fn_test",
        unit="melee/mn/fn_test",
        source_path=source,
        melee_root=tmp_path,
    )


def _variants(seq: list[tuple[str, str]], parent: Path) -> Iterator[SourceVariant]:
    for prov, text in seq:
        yield SourceVariant(text=text, provenance=prov, parent_baseline=parent)


def _stub_compiles(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pcdumps_by_text: dict[str, str],
) -> list[str]:
    """Patch compile_source_variant in simplify_search to return canned text.

    Returns a list mutated by the stub recording each text it was called
    with (so tests can assert ordering / early-exit / count caps)."""
    calls: list[str] = []

    def fake_compile(diff_input, *, function, melee_root, timeout):
        calls.append(diff_input.path.read_text(encoding="utf-8"))
        text = pcdumps_by_text.get(calls[-1])
        if text is None:
            raise AssertionError(
                f"unexpected compile input:\n{calls[-1]!r}\n"
                f"known keys: {list(pcdumps_by_text)!r}"
            )
        return text

    monkeypatch.setattr(
        "src.mwcc_debug.simplify_search.compile_source_variant",
        fake_compile,
    )
    return calls


def _pcdump_for(
    simplify_order: list[int],
    interference_edges: list[tuple[int, int]] | None = None,
    assigned_by_ig: dict[int, int] | None = None,
) -> str:
    """Build a minimal hook-events pcdump string that the colorgraph
    parser can read into FunctionEvents."""
    lines = ["Starting function fn_test"]
    # Construct the colorgraph header with at-least the simplify members.
    adj: dict[int, list[tuple[int, int]]] = {}
    for a, b in interference_edges or []:
        adj.setdefault(a, []).append((b, 30))
        adj.setdefault(b, []).append((a, 30))
    assigned_by_ig = assigned_by_ig or {}
    ig_idxs = sorted(set(simplify_order) | set(adj.keys()) | set(assigned_by_ig))
    lines.append(f"COLORGRAPH DECISIONS (class=0, result=1, n_nodes={len(ig_idxs)})")
    lines.append("iter ig_idx assigned degree n_interferers flags")
    for i, ig in enumerate(ig_idxs):
        # Required form for _ITER_RE: "iter ig_idx rN degree array_size 0xflags"
        assigned = assigned_by_ig.get(ig, 30)
        lines.append(f"  {i}  {ig}  r{assigned}  {len(adj.get(ig, []))}  {len(adj.get(ig, []))}  0x0")
        if ig in adj:
            interferers = " ".join(f"{idx}=r{reg}" for idx, reg in adj[ig])
            lines.append(f"  interferers: {interferers}")
    lines.append("[COALESCE] enter class=0 n_virtuals=40")
    lines.append("[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0")
    lines.append("SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)")
    lines.append("iter ig_idx degree array_size flags")
    for i, ig in enumerate(simplify_order):
        lines.append(f"  {i}  {ig}  1  1  0x0")
    return "\n".join(lines) + "\n"


def test_search_returns_exact_match_when_variant_hits_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[32, 42]), class_id=0,
    )

    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "VARIANT_A": _pcdump_for([42, 32]),
        },
    )

    def src(_ctx):
        yield SourceVariant(text="VARIANT_A", provenance="hit", parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    assert result.exact_match is not None
    assert result.exact_match.provenance == "hit"
    # Stop early — no more variants compiled past the exact-match.
    assert result.total_compiles == 1


def test_search_force_phys_scores_assignment_when_simplify_order_is_unusable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(
            simplify_order=[-1, -1],
            assigned_by_ig={53: 5},
        ),
        class_id=0,
    )

    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "VARIANT_A": _pcdump_for(
                [-1, -1],
                assigned_by_ig={53: 4},
            ),
        },
    )

    def src(_ctx):
        yield SourceVariant(
            text="VARIANT_A",
            provenance="force-phys-hit",
            parent_baseline=ctx.source_path,
        )

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(53,),
        force_phys={53: 4},
        max_candidates=10,
        timeout=10,
        preserve_precolor_enabled=False,
    )

    assert result.exact_match is not None
    assert result.exact_match.provenance == "force-phys-hit"
    assert result.total_compiles == 1


def test_search_records_gate_rejections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[32, 42],
        ),
        class_id=0,
    )

    # variant_a disturbs the interference graph -> gate rejects
    # variant_b matches preserve-precolor but doesn't hit target
    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "VARIANT_A": _pcdump_for(
                [32, 42], interference_edges=[(32, 33), (32, 99)],
            ),
            "VARIANT_B": _pcdump_for(
                [32, 42], interference_edges=[(32, 33)],
            ),
        },
    )

    def src(_ctx):
        yield SourceVariant(text="VARIANT_A", provenance="gate-fail",
                            parent_baseline=ctx.source_path)
        yield SourceVariant(text="VARIANT_B", provenance="no-progress",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    assert result.exact_match is None
    assert result.gate_rejected_count == 1
    assert any(
        "interference" in r.lower() for r in result.gate_rejection_reasons
    )
    assert result.total_compiles == 2


def test_search_respects_max_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[32, 42]), class_id=0,
    )

    pcdumps = {f"VARIANT_{i}": _pcdump_for([32, 42]) for i in range(10)}
    _stub_compiles(monkeypatch, pcdumps_by_text=pcdumps)

    def src(_ctx):
        for i in range(10):
            yield SourceVariant(
                text=f"VARIANT_{i}",
                provenance=f"i={i}",
                parent_baseline=ctx.source_path,
            )

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=3,
        timeout=10,
    )

    assert result.total_compiles == 3
    assert result.exact_match is None


def test_search_does_not_enter_later_sources_after_max_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[32, 42]), class_id=0,
    )
    _stub_compiles(monkeypatch, pcdumps_by_text={"ONLY": _pcdump_for([32, 42])})
    entered_late_source = {"called": False}

    def first_source(_ctx):
        yield SourceVariant(
            text="ONLY",
            provenance="first",
            parent_baseline=ctx.source_path,
        )

    def late_source(_ctx):
        entered_late_source["called"] = True
        raise AssertionError("late source must not run after max_candidates")
        yield

    result = search(
        sources=[first_source, late_source],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=1,
        timeout=10,
    )

    assert result.total_compiles == 1
    assert entered_late_source["called"] is False


def test_search_does_not_pull_same_source_after_max_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[32, 42]), class_id=0,
    )
    _stub_compiles(monkeypatch, pcdumps_by_text={"ONLY": _pcdump_for([32, 42])})

    def source(_ctx):
        yield SourceVariant(
            text="ONLY",
            provenance="first",
            parent_baseline=ctx.source_path,
        )
        raise AssertionError("source must not be pulled after max_candidates")

    result = search(
        sources=[source],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=1,
        timeout=10,
    )

    assert result.total_compiles == 1


def test_search_ranks_progress_candidates_by_prefix_length(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[33, 99]), class_id=0,
    )

    # All preserve-precolor (no IG/coalesce/spill diff), but vary simplify order.
    # weaker: matches no prefix of target (42, 32)
    # better: matches 1 prefix
    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "WEAKER": _pcdump_for([99, 33]),
            "BETTER": _pcdump_for([42, 99]),
        },
    )

    def src(_ctx):
        yield SourceVariant(text="WEAKER", provenance="weaker",
                            parent_baseline=ctx.source_path)
        yield SourceVariant(text="BETTER", provenance="better",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    assert result.exact_match is None
    # Only "better" should be in progress (weaker is 0/0 = no progress).
    assert len(result.progress) >= 1
    assert result.progress[0].variant.provenance == "better"


def test_search_aggregates_across_multiple_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[33, 99]), class_id=0,
    )

    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "SRC_A_1": _pcdump_for([33, 99]),
            "SRC_B_1": _pcdump_for([42, 32]),
        },
    )

    def src_a(_ctx):
        yield SourceVariant(text="SRC_A_1", provenance="a:1",
                            parent_baseline=ctx.source_path)

    def src_b(_ctx):
        yield SourceVariant(text="SRC_B_1", provenance="b:1",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src_a, src_b],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    assert result.exact_match is not None
    assert result.exact_match.provenance == "b:1"
    # We hit exact match on the second source; total compiles is at least 2.
    assert result.total_compiles >= 2


def test_search_swallows_compile_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A bad variant shouldn't blow up the whole search — record the failure
    but keep going. Variants that fail to compile don't count against
    progress or gate rejections.
    """
    from src.mwcc_debug.diff_capture import CompileFailure

    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[33, 99]), class_id=0,
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        text = diff_input.path.read_text(encoding="utf-8")
        if text == "BAD":
            raise CompileFailure(
                side="A",
                command=["python", "-m", "src.cli"],
                stdout="",
                stderr="syntax error",
                returncode=1,
            )
        return _pcdump_for([42, 32])

    monkeypatch.setattr(
        "src.mwcc_debug.simplify_search.compile_source_variant",
        fake_compile,
    )

    def src(_ctx):
        yield SourceVariant(text="BAD", provenance="broken",
                            parent_baseline=ctx.source_path)
        yield SourceVariant(text="GOOD", provenance="match",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    assert result.exact_match is not None
    assert result.compile_failure_count == 1
    assert result.compile_failures[0] == CompileFailureSummary(
        provenance="broken",
        returncode=1,
        diagnostic="syntax error",
    )


def test_search_dedups_identical_variant_text_across_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """If two adapters happen to produce the same `variant.text`, the search
    driver should compile it only once. Per-adapter dedup catches duplicates
    within one source, but two adapters (e.g. decl-orders and a future
    permuter adapter producing the same permutation textually) can still
    collide. The driver-level dedup is the only thing that catches that.
    """
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[33, 99]), class_id=0,
    )

    # Both adapters yield "SHARED"; only the first should consume a compile
    # slot. The unique "UNIQUE_B" should also compile.
    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "SHARED": _pcdump_for([33, 99]),
            "UNIQUE_B": _pcdump_for([33, 99]),
        },
    )

    def src_a(_ctx):
        yield SourceVariant(text="SHARED", provenance="a:shared",
                            parent_baseline=ctx.source_path)

    def src_b(_ctx):
        yield SourceVariant(text="SHARED", provenance="b:shared",
                            parent_baseline=ctx.source_path)
        yield SourceVariant(text="UNIQUE_B", provenance="b:unique",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src_a, src_b],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    # Two unique texts -> two compiles, not three.
    assert result.total_compiles == 2


def test_search_cross_source_dedup_does_not_consume_max_candidates_slots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A duplicate `variant.text` must not count against `max_candidates`.
    Otherwise a buggy or noisy adapter could silently exhaust the cap with
    repeats and starve genuinely-new variants.
    """
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(simplify_order=[33, 99]), class_id=0,
    )

    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "DUPE": _pcdump_for([33, 99]),
            "FRESH": _pcdump_for([42, 32]),  # exact match
        },
    )

    def src_a(_ctx):
        # Emit DUPE 5 times, then FRESH. With max_candidates=3, the cap-naive
        # behavior would burn all 3 slots on DUPE and never see FRESH; the
        # dedup'd behavior should compile DUPE once + FRESH once.
        for _ in range(5):
            yield SourceVariant(text="DUPE", provenance="dup",
                                parent_baseline=ctx.source_path)
        yield SourceVariant(text="FRESH", provenance="fresh",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src_a],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=3,
        timeout=10,
    )

    assert result.exact_match is not None
    assert result.exact_match.provenance == "fresh"
    # DUPE compiled once + FRESH compiled once.
    assert result.total_compiles == 2


# ---------------------------------------------------------------------------
# Gate-rejected candidate scoring (diagnostic)
# ---------------------------------------------------------------------------


def test_search_scores_gate_rejected_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Every gate-rejected variant should appear in `rejected_scored` with
    a `SimplifyScore`. Without this, the search driver throws away the
    only signal that tells us whether permuter ever moved simplify-order
    toward target — even at the cost of disturbing precolor."""
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[32, 42],
        ),
        class_id=0,
    )

    # Three variants, all disturbing the interference graph -> all rejected.
    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "V1": _pcdump_for([32, 42], interference_edges=[(32, 33), (32, 99)]),
            "V2": _pcdump_for([42, 32], interference_edges=[(32, 33), (32, 100)]),
            "V3": _pcdump_for([99, 42], interference_edges=[(32, 33), (33, 99)]),
        },
    )

    def src(_ctx):
        for i, text in enumerate(["V1", "V2", "V3"]):
            yield SourceVariant(text=text, provenance=f"v{i + 1}",
                                parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    assert result.gate_rejected_count == 3
    assert len(result.rejected_scored) == 3
    for rc in result.rejected_scored:
        assert isinstance(rc, RejectedCandidate)
        assert isinstance(rc.score, SimplifyScore)


def test_search_rejected_scores_capture_partial_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """If a gate-rejected candidate ALSO happens to move simplify-order
    toward target, its score must reflect that — even though the gate
    rejected it. This is the headline diagnostic question: would a
    distance-metric gate have caught a partial win?"""
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[32, 33, 40],
        ),
        class_id=0,
    )

    # NO_PROGRESS: rejected, simplify_order still starts with 32 (prefix=0).
    # PARTIAL: rejected, simplify_order now starts with 42 (prefix=1).
    # FULL: rejected, simplify_order exactly matches target prefix (prefix=2).
    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "NO_PROGRESS": _pcdump_for([32, 33, 40], interference_edges=[(32, 99)]),
            "PARTIAL": _pcdump_for([42, 33, 40], interference_edges=[(32, 99)]),
            "FULL": _pcdump_for([42, 32, 40], interference_edges=[(32, 99)]),
        },
    )

    def src(_ctx):
        for text, prov in [("NO_PROGRESS", "no"), ("PARTIAL", "partial"),
                           ("FULL", "full")]:
            yield SourceVariant(text=text, provenance=prov,
                                parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    # All three are gate-rejected (interference graph differs); none make
    # it into progress/exact_match.
    assert result.exact_match is None
    assert result.progress == []
    assert result.gate_rejected_count == 3

    by_prov = {rc.provenance: rc for rc in result.rejected_scored}
    assert by_prov["no"].score.common_prefix_length == 0
    assert by_prov["partial"].score.common_prefix_length == 1
    assert by_prov["full"].score.common_prefix_length == 2
    # The "full" candidate's observed prefix should reach the target length.
    assert by_prov["full"].score.is_exact_match is True


def test_search_rejected_candidate_preserves_rejection_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The rejection reason from the gate is captured on each
    RejectedCandidate. Lets the diagnostic say "rejected because: X"
    next to each top entry."""
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[32, 33],
        ),
        class_id=0,
    )

    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "IG_DIFF": _pcdump_for(
                [32, 33], interference_edges=[(32, 33), (32, 99)],
            ),
        },
    )

    def src(_ctx):
        yield SourceVariant(text="IG_DIFF", provenance="bad",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    assert len(result.rejected_scored) == 1
    rc = result.rejected_scored[0]
    assert rc.rejection_reason
    # The gate produces a reason starting with "interference graph differs"
    # for IG mismatches.
    assert "interference" in rc.rejection_reason.lower()


def test_search_passing_candidates_still_excluded_from_rejected_scored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Gate-passing variants go to `progress`, NOT `rejected_scored`.
    The two lists are mutually exclusive — a candidate can't be in both."""
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[33, 99],
        ),
        class_id=0,
    )

    # PASSER: gate passes + simplify-order improves -> progress
    # REJECTED: gate rejects (IG mismatch) -> rejected_scored
    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            # gate passes: same IG as baseline; simplify_order shifts to (42, 99)
            "PASSER": _pcdump_for([42, 99], interference_edges=[(32, 33)]),
            # gate fails: IG differs
            "REJECTED": _pcdump_for(
                [42, 99], interference_edges=[(32, 33), (32, 100)],
            ),
        },
    )

    def src(_ctx):
        yield SourceVariant(text="PASSER", provenance="passer",
                            parent_baseline=ctx.source_path)
        yield SourceVariant(text="REJECTED", provenance="rejected",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    passer_provs = {sv.variant.provenance for sv in result.progress}
    rejected_provs = {rc.provenance for rc in result.rejected_scored}

    assert "passer" in passer_provs
    assert "rejected" in rejected_provs
    # Mutual exclusion: no provenance appears in both buckets.
    assert passer_provs.isdisjoint(rejected_provs)


# ---------------------------------------------------------------------------
# Precolor distance + combined scoring
# ---------------------------------------------------------------------------


def test_precolor_distance_counts_all_six_components() -> None:
    """Each of the six add/remove counts (IG, coalesce, spill) reflects the
    set delta between baseline and candidate exactly. The total is the
    sum across all six."""
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33), (32, 34)],
            simplify_order=[32, 33, 34, 40],
            coalesce_mappings=[(35, 32)],
            spilled_ig_idxs={40},
        ),
        class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(
            # IG: removed (32, 34); added (32, 99) and (33, 99).
            interference_edges=[(32, 33), (32, 99), (33, 99)],
            simplify_order=[32, 33, 40, 99],
            # Coalesce: removed (35, 32); added (37, 32).
            coalesce_mappings=[(37, 32)],
            # Spill: added 99; removed 40.
            spilled_ig_idxs={99},
        ),
        class_id=0,
    )

    dist = precolor_distance(baseline, candidate)

    assert dist.ig_added == 2  # (32, 99), (33, 99)
    assert dist.ig_removed == 1  # (32, 34)
    assert dist.coalesce_added == 1  # (37, 32)
    assert dist.coalesce_removed == 1  # (35, 32)
    assert dist.spill_added == 1  # 99
    assert dist.spill_removed == 1  # 40
    assert dist.total == 7


def test_precolor_distance_zero_when_baseline_matches() -> None:
    """When candidate equals baseline on all three preserve components,
    every count is zero and total=0. (Simplify-order differences don't
    contribute to precolor distance — that's a separate dimension.)"""
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[32, 33],
            coalesce_mappings=[(35, 32)],
            spilled_ig_idxs={34},
        ),
        class_id=0,
    )
    # Same preserve components but different simplify order — precolor
    # distance should still be zero.
    candidate = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[33, 32],  # reversed!
            coalesce_mappings=[(35, 32)],
            spilled_ig_idxs={34},
        ),
        class_id=0,
    )

    dist = precolor_distance(baseline, candidate)

    assert dist.ig_added == 0
    assert dist.ig_removed == 0
    assert dist.coalesce_added == 0
    assert dist.coalesce_removed == 0
    assert dist.spill_added == 0
    assert dist.spill_removed == 0
    assert dist.total == 0


def test_combined_score_uses_simplify_progress_ratio_and_alpha() -> None:
    """combined = (common_prefix_length / len(target)) - alpha * distance.total
    A known progress ratio and known distance produces a known combined."""
    target = (42, 32, 50, 51)  # len 4
    # Build baseline + candidate so common_prefix_length=2 (half progress)
    # and precolor adds 4 IG edges.
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[33, 99, 99, 99],  # baseline matches 0 of target
        ),
        class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(
            interference_edges=[
                (32, 33), (10, 11), (12, 13), (14, 15), (16, 17),
            ],  # 4 added
            simplify_order=[42, 32, 99, 99],  # matches first 2 of target
        ),
        class_id=0,
    )

    cs = combined_score(baseline, candidate, target, alpha=0.1)

    assert cs.simplify_score.common_prefix_length == 2
    assert cs.precolor_distance.ig_added == 4
    assert cs.precolor_distance.total == 4
    # ratio = 2/4 = 0.5; combined = 0.5 - 0.1*4 = 0.1
    assert cs.combined == pytest.approx(0.1)


def test_combined_score_empty_target() -> None:
    """With empty target, simplify_progress_ratio is 0.0 (defined choice
    — see CombinedScore docstring). Combined reduces to -alpha * distance."""
    target: tuple[int, ...] = ()
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[32, 33],
        ),
        class_id=0,
    )
    candidate = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33), (32, 99), (32, 100)],
            simplify_order=[32, 33],
        ),
        class_id=0,
    )

    cs = combined_score(baseline, candidate, target, alpha=0.05)

    assert cs.simplify_score.common_prefix_length == 0
    assert cs.precolor_distance.total == 2  # 2 IG added
    # ratio=0.0, combined = -0.05 * 2 = -0.1
    assert cs.combined == pytest.approx(-0.1)


def test_combined_score_higher_progress_beats_lower_distance() -> None:
    """Candidate A: prefix=2/2, distance=10. B: prefix=0/2, distance=0.
    With α=0.05: A's combined = 1.0 - 0.5 = 0.5; B's = 0.0. A wins."""
    target = (42, 32)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[99, 99],
        ),
        class_id=0,
    )
    # A: full progress, 10 IG edges added.
    cand_a_edges = [(32, 33)] + [(50 + i, 60 + i) for i in range(10)]
    candidate_a = baseline_signature(
        _events_for_class(
            interference_edges=cand_a_edges,
            simplify_order=[42, 32],
        ),
        class_id=0,
    )
    # B: zero progress, no precolor disturbance.
    candidate_b = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[99, 99],
        ),
        class_id=0,
    )

    score_a = combined_score(baseline, candidate_a, target, alpha=0.05)
    score_b = combined_score(baseline, candidate_b, target, alpha=0.05)

    assert score_a.combined == pytest.approx(0.5)
    assert score_b.combined == pytest.approx(0.0)
    assert score_a.combined > score_b.combined


def test_combined_score_lower_distance_wins_when_progress_ties() -> None:
    """Candidate A: prefix=2/2, distance=10. B: prefix=2/2, distance=2.
    Both hit full simplify-order progress. B wins on smaller disturbance."""
    target = (42, 32)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[99, 99],
        ),
        class_id=0,
    )
    cand_a = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)] + [(50 + i, 60 + i) for i in range(10)],
            simplify_order=[42, 32],
        ),
        class_id=0,
    )
    cand_b = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33), (50, 60), (51, 61)],
            simplify_order=[42, 32],
        ),
        class_id=0,
    )

    score_a = combined_score(baseline, cand_a, target, alpha=0.05)
    score_b = combined_score(baseline, cand_b, target, alpha=0.05)

    # Both at full progress (ratio=1.0).
    assert score_a.simplify_score.common_prefix_length == 2
    assert score_b.simplify_score.common_prefix_length == 2
    # B's smaller distance wins.
    assert score_b.combined > score_a.combined


def test_default_combined_alpha_matches_module_constant() -> None:
    """Sanity check: the module-level default α stays in sync with the
    value referenced by the CLI default and docstrings. The current value
    (0.001) is calibrated against permuter distance ranges observed in
    the 2026-05-23 grVenom batch (100-300+); see the constant's
    docstring for the reasoning. If this changes, also update:
      * the CLI's --combined-alpha default in cli/debug.py
      * the combined_score() docstring referencing the value
      * any campaign-doc references to the prior default"""
    assert DEFAULT_COMBINED_ALPHA == 0.001


def test_combined_score_with_zero_alpha_reduces_to_pure_simplify_ratio() -> None:
    """With α=0, the precolor distance penalty vanishes and the combined
    score equals the simplify-progress ratio. Candidates with identical
    simplify scores tie regardless of how much they disturb precolor.
    Locks the linearity in so a future refactor can't accidentally flip
    the sign or hardcode a non-zero floor."""
    target = (42, 32)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[99, 99],
        ),
        class_id=0,
    )
    # Two candidates with identical simplify progress but very different
    # precolor distances.
    cand_low_distance = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[42, 32],
        ),
        class_id=0,
    )
    cand_high_distance = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)] + [(50 + i, 60 + i) for i in range(20)],
            simplify_order=[42, 32],
        ),
        class_id=0,
    )

    # α=0.05: lower-distance candidate wins.
    low_005 = combined_score(baseline, cand_low_distance, target, alpha=0.05)
    high_005 = combined_score(baseline, cand_high_distance, target, alpha=0.05)
    assert low_005.combined > high_005.combined

    # α=0: candidates tie at the simplify-progress ratio (1.0 for full match).
    low_0 = combined_score(baseline, cand_low_distance, target, alpha=0.0)
    high_0 = combined_score(baseline, cand_high_distance, target, alpha=0.0)
    assert low_0.combined == high_0.combined == 1.0
    assert low_0.precolor_distance.total == 0
    assert high_0.precolor_distance.total == 20


def test_search_attaches_precolor_distance_to_passing_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """When the gate is on and a candidate passes, its `precolor_distance`
    is attached anyway and is structurally all zeros (the gate's pass
    condition implies the three preserve components match)."""
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[33, 99],
        ),
        class_id=0,
    )

    # PASSER: gate passes + makes progress (simplify_order matches first
    # target item).
    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "PASSER": _pcdump_for([42, 99], interference_edges=[(32, 33)]),
        },
    )

    def src(_ctx):
        yield SourceVariant(text="PASSER", provenance="ok",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    assert len(result.progress) == 1
    sv = result.progress[0]
    assert isinstance(sv.precolor_distance, PrecolorDistance)
    # Gate passed -> all preserve components match -> distance=0.
    assert sv.precolor_distance.total == 0


def test_search_attaches_precolor_distance_to_rejected_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Every gate-rejected candidate gets a non-zero `precolor_distance`
    attached (since the gate fails iff at least one preserve component
    differs)."""
    ctx = _ctx(tmp_path)
    baseline = baseline_signature(
        _events_for_class(
            interference_edges=[(32, 33)],
            simplify_order=[32, 42],
        ),
        class_id=0,
    )

    # Two IG edges added relative to baseline -> rejected, distance >= 2.
    _stub_compiles(
        monkeypatch,
        pcdumps_by_text={
            "V1": _pcdump_for(
                [42, 32],
                interference_edges=[(32, 33), (32, 99), (33, 100)],
            ),
        },
    )

    def src(_ctx):
        yield SourceVariant(text="V1", provenance="rejected",
                            parent_baseline=ctx.source_path)

    result = search(
        sources=[src],
        ctx=ctx,
        baseline=baseline,
        target=(42, 32),
        max_candidates=10,
        timeout=10,
    )

    assert len(result.rejected_scored) == 1
    rc = result.rejected_scored[0]
    assert isinstance(rc.precolor_distance, PrecolorDistance)
    # Two IG edges added; none removed; no coalesce/spill diff.
    assert rc.precolor_distance.ig_added == 2
    assert rc.precolor_distance.ig_removed == 0
    assert rc.precolor_distance.total == 2
