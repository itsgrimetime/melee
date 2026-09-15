"""Pure tests for mwcc_debug diff reports."""
from __future__ import annotations

from src.mwcc_debug.colorgraph_parser import (
    CoalesceSection,
    ColorgraphDecision,
    ColorgraphSection,
    FunctionEvents,
    SimplifyEntry,
    SimplifySection,
)
from src.mwcc_debug.diff_report import (
    DivergenceKind,
    compare_function_dumps,
    render_text_report,
)


def pcdump_for(pass_body: str, function: str = "fn_test") -> str:
    return f"""
Starting function {function}
BEFORE REGISTER COLORING
{function}
B0: Succ={{}} Pred={{}} Labels={{L0 }}
    li r32, 0
{pass_body}
AFTER REGISTER COLORING
{function}
B0: Succ={{}} Pred={{}} Labels={{L0 }}
    li r3, 0
""".strip()


def test_identical_dumps_have_no_divergence() -> None:
    text = pcdump_for("")

    report = compare_function_dumps(text, text, function="fn_test")

    assert report.earliest is None
    assert all(not p.changed for p in report.passes)
    assert "NO DIVERGENCE" in render_text_report(report)


def _pcdump_with_after_body(pass_body: str, after_li_value: int, function: str = "fn_test") -> str:
    """Variant of pcdump_for that also lets the AFTER REGISTER COLORING `li`
    immediate be customized, so a single test can diverge BOTH passes.
    """
    return f"""
Starting function {function}
BEFORE REGISTER COLORING
{function}
B0: Succ={{}} Pred={{}} Labels={{L0 }}
    li r32, 0
{pass_body}
AFTER REGISTER COLORING
{function}
B0: Succ={{}} Pred={{}} Labels={{L0 }}
    li r3, {after_li_value}
""".strip()


def test_earliest_text_pass_divergence_is_reported() -> None:
    # Diverge BOTH passes so cascade tracking has something to mark.
    left = _pcdump_with_after_body("    add r33, r32, r3", after_li_value=0)
    right = _pcdump_with_after_body("    add r33, r32, r4", after_li_value=1)

    report = compare_function_dumps(left, right, function="fn_test")

    assert report.earliest is not None
    assert report.earliest.pass_name == "BEFORE REGISTER COLORING"
    rendered = render_text_report(report)
    assert "EARLIEST DIVERGENCE: BEFORE REGISTER COLORING" in rendered
    assert "cascade from pass 1" in rendered


def test_different_pass_lists_are_meta_divergence() -> None:
    left = pcdump_for("")
    right = pcdump_for("").replace(
        "AFTER REGISTER COLORING",
        "AFTER COPY PROPAGATION\nfn_test\nB0: Succ={} Pred={} Labels={L0 }\n"
        "    li r32, 0\nAFTER REGISTER COLORING",
    )

    report = compare_function_dumps(left, right, function="fn_test")

    assert report.earliest is not None
    assert report.earliest.kind == DivergenceKind.META
    assert "pass list differs" in report.earliest.summary


def test_inspect_snapshots_can_be_earliest_divergence() -> None:
    pcdump = pcdump_for("")
    inspect_a = "FUNCTION: fn_test\nSTATEMENTS\n  i = arg0 + 1\n"
    inspect_b = "FUNCTION: fn_test\nSTATEMENTS\n  i = arg0 - 1\n"

    report = compare_function_dumps(
        pcdump,
        pcdump,
        function="fn_test",
        inspect_text_a=inspect_a,
        inspect_text_b=inspect_b,
    )

    assert report.earliest is not None
    assert report.earliest.pass_name == "Frontend: STATEMENTS"
    rendered = render_text_report(report)
    assert "EARLIEST DIVERGENCE: Frontend: STATEMENTS" in rendered
    assert "LOWERING SUMMARY" in rendered
    assert "earliest stage: front-end source IR" in rendered
    assert "source statements/ENodes differ before backend PCode exists" in rendered


def _decision(
    *,
    iter_idx: int,
    ig_idx: int,
    assigned: int,
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


def _events(assigned_a: int, assigned_b: int, *, extra_interference: bool = False) -> FunctionEvents:
    events = FunctionEvents(name="fn_test")
    interferers_32 = [(33, assigned_b)]
    if extra_interference:
        interferers_32.append((34, 30))
    events.colorgraph_sections.append(ColorgraphSection(
        class_id=1,
        result=1,
        n_nodes=2,
        decisions=[
            _decision(iter_idx=0, ig_idx=32, assigned=assigned_a, interferers=interferers_32),
            _decision(iter_idx=1, ig_idx=33, assigned=assigned_b, interferers=[(32, assigned_a)]),
        ],
    ))
    events.simplify_sections.append(SimplifySection(
        class_id=1,
        n_colors=29,
        n_class_regs=40,
        entries=[
            SimplifyEntry(iter_idx=0, ig_idx=32, degree=1, array_size=1, flags=0, spilled=False),
            SimplifyEntry(iter_idx=1, ig_idx=33, degree=1, array_size=1, flags=0, spilled=False),
        ],
    ))
    events.coalesce_sections.append(CoalesceSection(
        class_id=1,
        n_virtuals=40,
        mappings=[(35, 32)],
        distinct_roots=39,
        forced_count=0,
    ))
    return events


def test_ra_same_input_different_coloring_is_intrinsic() -> None:
    text = pcdump_for("")
    report = compare_function_dumps(
        text,
        text,
        function="fn_test",
        events_a=[_events(31, 30)],
        events_b=[_events(29, 30)],
    )

    ra = next(p for p in report.passes if p.pass_name == "AFTER REGISTER COLORING")
    assert ra.ra is not None
    assert ra.ra.classification == "intrinsic"
    assert report.earliest is not None
    assert report.earliest.kind == DivergenceKind.RA_INTRINSIC

    rendered = render_text_report(report)
    assert "DIVERGENCE (intrinsic)" in rendered
    assert any(
        "output: class 1: coloring output differs" in line for line in rendered.splitlines()
    )


def test_ra_different_input_is_input_derived() -> None:
    text = pcdump_for("")
    report = compare_function_dumps(
        text,
        text,
        function="fn_test",
        events_a=[_events(31, 30, extra_interference=False)],
        events_b=[_events(29, 30, extra_interference=True)],
    )

    ra = next(p for p in report.passes if p.pass_name == "AFTER REGISTER COLORING")
    assert ra.ra is not None
    assert ra.ra.classification == "input-derived"
    assert report.earliest is not None
    assert report.earliest.kind == DivergenceKind.RA_INPUT_DERIVED

    rendered = render_text_report(report)
    assert "DIVERGENCE (input-derived)" in rendered
    # The B fixture adds (34, 30) to ig_idx 32's interferers. After
    # normalization that surfaces as a new (32, 34) edge in the
    # interference graph component of the input diff.
    assert any(
        "interference graph differs" in line for line in rendered.splitlines()
    )
    assert any(
        "(32, 34)" in line for line in rendered.splitlines()
    )
    assert "earliest stage: register-allocation input" in rendered
    assert "allocator inputs changed" in rendered


def _ra_events(
    *,
    interference_edges: list[tuple[int, int, int]] | None = None,
    simplify_order: list[int] | None = None,
    coalesce_mappings: list[tuple[int, int]] | None = None,
    spilled_ig_idxs: set[int] | None = None,
    class_id: int = 1,
) -> FunctionEvents:
    """Build a FunctionEvents with one register class, parametrized per
    input component. Lets each new test isolate one sub-signature.

    `interference_edges` is a list of (ig_a, ig_b, _assigned_reg) tuples,
    expanded into symmetric decision interferer lists. The third element
    is just the placeholder assigned_reg used in the interferers field.
    """
    interference_edges = interference_edges or []
    simplify_order = simplify_order or [32, 33]
    coalesce_mappings = coalesce_mappings or []
    spilled_ig_idxs = spilled_ig_idxs or set()

    # Build adjacency map ig -> [(neighbor, assigned_reg), ...]
    adj: dict[int, list[tuple[int, int]]] = {}
    for a, b, reg in interference_edges:
        adj.setdefault(a, []).append((b, reg))
        adj.setdefault(b, []).append((a, reg))

    # Ensure every ig_idx in simplify_order has a colorgraph decision
    ig_idxs = sorted(set(simplify_order) | set(adj.keys()))
    decisions = []
    for iter_i, ig in enumerate(ig_idxs):
        decisions.append(_decision(
            iter_idx=iter_i,
            ig_idx=ig,
            assigned=30,
            interferers=sorted(adj.get(ig, [])),
        ))

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


def test_ra_interference_change_surfaces_in_input_diff() -> None:
    text = pcdump_for("")
    events_a = _ra_events(interference_edges=[(32, 33, 30)])
    events_b = _ra_events(interference_edges=[(32, 33, 30), (32, 34, 30)])

    report = compare_function_dumps(
        text, text, function="fn_test",
        events_a=[events_a], events_b=[events_b],
    )

    ra = next(p for p in report.passes if p.pass_name == "AFTER REGISTER COLORING")
    assert ra.ra is not None
    assert ra.ra.classification == "input-derived"

    rendered = render_text_report(report)
    assert "DIVERGENCE (input-derived)" in rendered
    assert any(
        "interference graph differs" in line for line in rendered.splitlines()
    )
    # The newly added edge should be listed.
    assert any("(32, 34)" in line for line in rendered.splitlines())
    # The unchanged-component lines should NOT appear.
    assert not any(
        "coalesce mappings differ" in line for line in rendered.splitlines()
    )
    assert not any(
        "simplify order differs" in line for line in rendered.splitlines()
    )
    assert not any(
        "spill set differs" in line for line in rendered.splitlines()
    )


def test_ra_coalesce_change_surfaces_in_input_diff() -> None:
    text = pcdump_for("")
    events_a = _ra_events(coalesce_mappings=[(35, 32)])
    events_b = _ra_events(coalesce_mappings=[(37, 32)])

    report = compare_function_dumps(
        text, text, function="fn_test",
        events_a=[events_a], events_b=[events_b],
    )

    ra = next(p for p in report.passes if p.pass_name == "AFTER REGISTER COLORING")
    assert ra.ra is not None
    assert ra.ra.classification == "input-derived"

    rendered = render_text_report(report)
    assert any(
        "coalesce mappings differ" in line for line in rendered.splitlines()
    )
    # Added and removed mappings should both appear.
    assert any("(37, 32)" in line for line in rendered.splitlines())
    assert any("(35, 32)" in line for line in rendered.splitlines())


def test_ra_simplify_order_change_surfaces_in_input_diff() -> None:
    text = pcdump_for("")
    events_a = _ra_events(simplify_order=[32, 33, 34, 35])
    events_b = _ra_events(simplify_order=[32, 33, 35, 34])

    report = compare_function_dumps(
        text, text, function="fn_test",
        events_a=[events_a], events_b=[events_b],
    )

    ra = next(p for p in report.passes if p.pass_name == "AFTER REGISTER COLORING")
    assert ra.ra is not None
    assert ra.ra.classification == "input-derived"

    rendered = render_text_report(report)
    assert any(
        "simplify order differs" in line for line in rendered.splitlines()
    )
    # First-changed position is iter 2 (index 2), with ig_idx 34 in A and
    # ig_idx 35 in B.
    assert any(
        "position: 2" in line for line in rendered.splitlines()
    )
    assert any("ig_idx 34" in line for line in rendered.splitlines())
    assert any("ig_idx 35" in line for line in rendered.splitlines())


def test_ra_spill_change_surfaces_in_input_diff() -> None:
    text = pcdump_for("")
    events_a = _ra_events(simplify_order=[32, 33, 40], spilled_ig_idxs=set())
    events_b = _ra_events(simplify_order=[32, 33, 40], spilled_ig_idxs={40})

    report = compare_function_dumps(
        text, text, function="fn_test",
        events_a=[events_a], events_b=[events_b],
    )

    ra = next(p for p in report.passes if p.pass_name == "AFTER REGISTER COLORING")
    assert ra.ra is not None
    assert ra.ra.classification == "input-derived"

    rendered = render_text_report(report)
    assert any(
        "spill set differs" in line for line in rendered.splitlines()
    )
    assert any("40" in line and "spill" in line.lower()
               for line in rendered.splitlines())


def test_ra_multiple_input_components_can_diverge_together() -> None:
    text = pcdump_for("")
    events_a = _ra_events(
        interference_edges=[(32, 33, 30)],
        simplify_order=[32, 33, 34],
        coalesce_mappings=[(35, 32)],
        spilled_ig_idxs=set(),
    )
    events_b = _ra_events(
        interference_edges=[(32, 33, 30), (32, 34, 30)],
        simplify_order=[32, 33, 34],
        coalesce_mappings=[(37, 32)],
        spilled_ig_idxs={34},
    )

    report = compare_function_dumps(
        text, text, function="fn_test",
        events_a=[events_a], events_b=[events_b],
    )

    ra = next(p for p in report.passes if p.pass_name == "AFTER REGISTER COLORING")
    assert ra.ra is not None
    assert ra.ra.classification == "input-derived"

    rendered = render_text_report(report)
    # Three components should appear (simplify order is unchanged here).
    assert any("interference graph differs" in l for l in rendered.splitlines())
    assert any("coalesce mappings differ" in l for l in rendered.splitlines())
    assert any("spill set differs" in l for l in rendered.splitlines())
    # The unchanged simplify order should NOT appear.
    assert not any("simplify order differs" in l for l in rendered.splitlines())


def test_ra_multi_class_all_components_diverge_are_all_rendered() -> None:
    """Regression test: with 3 register classes (e.g. GPR + FPR + CR)
    each diverging on all 4 input components, all 12 input lines must
    reach the rendered output. A tight renderer cap (e.g. [:8] sized
    for the realistic 2-class case, or [:4] sized for the old
    single-line-per-class output) would silently drop trailing classes.

    2-class TUs (GPR + FPR) hit exactly the [:8] boundary with zero
    headroom — fine if nothing ever changes, but fragile. 3+ classes
    already exceed it. Using 3 classes here pins the slice to a value
    with explicit headroom.
    """
    text = pcdump_for("")
    # Build two FunctionEvents, each with three classes (1, 2, 3), each
    # class diverging on all four input components.
    def _build(*, side_b: bool) -> FunctionEvents:
        events = FunctionEvents(name="fn_test")
        for class_id in (1, 2, 3):
            # Disjoint ig_idx ranges per class so the per-class diffs
            # don't accidentally collide.
            base = {1: 32, 2: 50, 3: 70}[class_id]
            interferers = [(base, base + 1, 30)]
            if side_b:
                interferers.append((base, base + 2, 30))
            adj: dict[int, list[tuple[int, int]]] = {}
            for a, b, reg in interferers:
                adj.setdefault(a, []).append((b, reg))
                adj.setdefault(b, []).append((a, reg))
            ig_idxs = sorted(set(adj.keys()))
            decisions = [
                _decision(
                    iter_idx=i,
                    ig_idx=ig,
                    assigned=30,
                    interferers=sorted(adj.get(ig, [])),
                )
                for i, ig in enumerate(ig_idxs)
            ]
            events.colorgraph_sections.append(ColorgraphSection(
                class_id=class_id,
                result=1,
                n_nodes=len(ig_idxs),
                decisions=decisions,
            ))
            # Simplify order: differ at position 2 between sides.
            order = [base, base + 1, base + 2, base + 3] if not side_b else [base, base + 1, base + 3, base + 2]
            spilled_ig = base + 3 if side_b else -1  # only B spills
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
                        flags=0x08 if ig == spilled_ig else 0,
                        spilled=ig == spilled_ig,
                    )
                    for i, ig in enumerate(order)
                ],
            ))
            # Coalesce mapping: differs between sides.
            mapping = (base + 4, base) if not side_b else (base + 5, base)
            events.coalesce_sections.append(CoalesceSection(
                class_id=class_id,
                n_virtuals=40,
                mappings=[mapping],
                distinct_roots=39,
                forced_count=0,
            ))
        return events

    events_a = _build(side_b=False)
    events_b = _build(side_b=True)

    report = compare_function_dumps(
        text, text, function="fn_test",
        events_a=[events_a], events_b=[events_b],
    )

    ra = next(p for p in report.passes if p.pass_name == "AFTER REGISTER COLORING")
    assert ra.ra is not None
    assert ra.ra.classification == "input-derived"
    # Sanity: the classifier produced 12 input lines (4 per class * 3 classes).
    assert len(ra.ra.input_changes) == 12, (
        f"expected 12 input lines, got {len(ra.ra.input_changes)}: {ra.ra.input_changes}"
    )

    rendered = render_text_report(report)
    # All 12 lines must reach the rendered output (one per class * component).
    for class_id in (1, 2, 3):
        assert any(
            f"class {class_id}: interference graph differs" in l
            for l in rendered.splitlines()
        ), f"class {class_id} interference line missing"
        assert any(
            f"class {class_id}: coalesce mappings differ" in l
            for l in rendered.splitlines()
        ), f"class {class_id} coalesce line missing"
        assert any(
            f"class {class_id}: simplify order differs" in l
            for l in rendered.splitlines()
        ), f"class {class_id} simplify line missing"
        assert any(
            f"class {class_id}: spill set differs" in l
            for l in rendered.splitlines()
        ), f"class {class_id} spill line missing"


def test_inspect_cascade_marks_downstream_snapshots() -> None:
    """When two inspect snapshots both diverge, the second one should be
    tagged as 'cascade from pass 1' rather than rendering as a fresh earliest
    divergence."""
    pcdump = pcdump_for("")
    inspect_a = (
        "FUNCTION: fn_test\n"
        "STATEMENTS\n"
        "  i = arg0 + 1\n"
        "ENODES\n"
        "  add(arg0, 1)\n"
    )
    inspect_b = (
        "FUNCTION: fn_test\n"
        "STATEMENTS\n"
        "  i = arg0 - 1\n"
        "ENODES\n"
        "  sub(arg0, 1)\n"
    )

    report = compare_function_dumps(
        pcdump,
        pcdump,
        function="fn_test",
        inspect_text_a=inspect_a,
        inspect_text_b=inspect_b,
    )

    assert report.earliest is not None
    assert report.earliest.pass_name == "Frontend: STATEMENTS"
    assert report.earliest.cascade_from is None

    # Snapshot 2 (Frontend: ENODES) should be tagged as cascading from snapshot 1.
    snap2 = report.passes[1]
    assert snap2.pass_name == "Frontend: ENODES"
    assert snap2.changed
    assert snap2.cascade_from == report.earliest.index

    rendered = render_text_report(report)
    assert f"cascade from pass {report.earliest.index}" in rendered


def test_heuristic_cause_signed_vs_unsigned_divide() -> None:
    pcdump = pcdump_for("")
    inspect_a = "FUNCTION: fn_test\nSTATEMENTS\n  divw r3, r4, r5\n"
    inspect_b = "FUNCTION: fn_test\nSTATEMENTS\n  mulhwu r3, r4, r5\n"

    report = compare_function_dumps(
        pcdump,
        pcdump,
        function="fn_test",
        inspect_text_a=inspect_a,
        inspect_text_b=inspect_b,
    )

    diverged = next(p for p in report.passes if p.changed)
    assert any("s32/u32" in cause for cause in diverged.heuristic_causes)
    rendered = render_text_report(report)
    assert "s32/u32" in rendered


def test_heuristic_cause_arithmetic_vs_logical_shift() -> None:
    pcdump = pcdump_for("")
    inspect_a = "FUNCTION: fn_test\nSTATEMENTS\n  srawi r3, r4, 5\n"
    inspect_b = "FUNCTION: fn_test\nSTATEMENTS\n  srwi r3, r4, 5\n"

    report = compare_function_dumps(
        pcdump,
        pcdump,
        function="fn_test",
        inspect_text_a=inspect_a,
        inspect_text_b=inspect_b,
    )

    diverged = next(p for p in report.passes if p.changed)
    assert any("signedness" in cause for cause in diverged.heuristic_causes)
    rendered = render_text_report(report)
    assert "signedness" in rendered


def test_heuristic_cause_volatile() -> None:
    pcdump = pcdump_for("")
    inspect_a = "FUNCTION: fn_test\nSTATEMENTS\n  load_plain a\n"
    inspect_b = "FUNCTION: fn_test\nSTATEMENTS\n  load_volatile a\n"

    report = compare_function_dumps(
        pcdump,
        pcdump,
        function="fn_test",
        inspect_text_a=inspect_a,
        inspect_text_b=inspect_b,
    )

    diverged = next(p for p in report.passes if p.changed)
    assert any("volatile" in cause for cause in diverged.heuristic_causes)
    rendered = render_text_report(report)
    assert "volatile source shape" in rendered


def test_render_reports_ra_output_changes() -> None:
    text = pcdump_for("")
    report = compare_function_dumps(
        text,
        text,
        function="fn_test",
        events_a=[_events(31, 30)],
        events_b=[_events(29, 30)],
        label_a="old.txt",
        label_b="new.txt",
    )

    rendered = render_text_report(report)

    assert "DIVERGENCE (intrinsic)" in rendered
    assert "class 1: coloring output differs" in rendered
    # The expansion should name the specific ig_idx that changed (32) and
    # show the before/after assigned register values (31 -> 29). Without the
    # per-ig_idx expansion, the user gets only the bare "differs" header and
    # has no way to know which decision actually changed.
    assert any("ig_idx 32" in line for line in rendered.splitlines())
    assert "31" in rendered and "29" in rendered


def _events_many(diff_ig_idx: int, n_decisions: int = 12) -> FunctionEvents:
    """Build a FunctionEvents with `n_decisions` colorgraph decisions
    (ig_idx 32..32+n_decisions-1), only the row at `diff_ig_idx` carrying
    a distinguishing assigned_reg.

    This lets us construct paired events where the only diff sits past the
    first 8 sorted ig_idxs, so we can verify that the diff is still
    surfaced (not silently dropped by an over-eager cap).
    """
    events = FunctionEvents(name="fn_test")
    decisions: list[ColorgraphDecision] = []
    for i in range(n_decisions):
        ig = 32 + i
        decisions.append(_decision(
            iter_idx=i,
            ig_idx=ig,
            assigned=25 if ig == diff_ig_idx else 30,
            interferers=[],
        ))
    events.colorgraph_sections.append(ColorgraphSection(
        class_id=1,
        result=1,
        n_nodes=n_decisions,
        decisions=decisions,
    ))
    return events


def test_ra_output_diff_past_first_eight_is_surfaced() -> None:
    """Regression test: when the diffing ig_idx sits past the first 8 sorted
    keys, the per-ig_idx detail must still reach the rendered report. A naive
    cap (keys[:8] before the inequality check) would silently drop the diff."""
    text = pcdump_for("")
    events_a = _events_many(diff_ig_idx=40)  # ig_idx 40 -> reg 25, others 30
    events_b = _events_many(diff_ig_idx=-1)  # all rows -> reg 30
    # Sanity: ig_idx 40 is the 9th sorted key (32..43); a flawed cap of [:8]
    # would scan only 32..39 and find no diffs.

    report = compare_function_dumps(
        text,
        text,
        function="fn_test",
        events_a=[events_a],
        events_b=[events_b],
    )
    rendered = render_text_report(report)

    assert "DIVERGENCE (intrinsic)" in rendered
    assert any("ig_idx 40" in line for line in rendered.splitlines())


def test_ra_output_diff_truncation_emits_more_marker() -> None:
    """When more than 7 ig_idxs differ, the report should surface the first
    7 plus a '...and N more' marker so users know detail was truncated."""
    text = pcdump_for("")
    # 12 differing ig_idxs (32..43): A side has every row at reg 25,
    # B side has every row at reg 30. All 12 ig_idxs differ.
    events_a = FunctionEvents(name="fn_test")
    events_a.colorgraph_sections.append(ColorgraphSection(
        class_id=1,
        result=1,
        n_nodes=12,
        decisions=[
            _decision(iter_idx=i, ig_idx=32 + i, assigned=25, interferers=[])
            for i in range(12)
        ],
    ))
    events_b = FunctionEvents(name="fn_test")
    events_b.colorgraph_sections.append(ColorgraphSection(
        class_id=1,
        result=1,
        n_nodes=12,
        decisions=[
            _decision(iter_idx=i, ig_idx=32 + i, assigned=30, interferers=[])
            for i in range(12)
        ],
    ))

    report = compare_function_dumps(
        text,
        text,
        function="fn_test",
        events_a=[events_a],
        events_b=[events_b],
    )
    rendered = render_text_report(report)

    # 7 detail lines + "...and 5 more" tail.
    assert "... and 5 more" in rendered
