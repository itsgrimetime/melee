from src.search.structure import StructureVariant, rank_structure_variants


def _v(label, pct, shape, line_delta, axis="statement-order"):
    return StructureVariant(
        axis=axis, operator="statement-order-hoist-sink", label=label,
        status="ok", match_percent=pct, final_match_percent=pct, delta=0.0,
        metadata={"structural": {"opcode_shape_preserved": shape,
                                 "line_delta": line_delta}})


def test_statement_order_ranks_shape_preserved_first():
    ranked = rank_structure_variants([_v("breaks", 84.0, False, 0),
                                      _v("clean", 84.0, True, 0)])
    assert ranked[0].label == "clean"


def test_statement_order_breaks_ties_by_smaller_line_delta():
    # same %, both shape-preserved -> smaller |line_delta| ranks first
    ranked = rank_structure_variants([_v("far", 84.0, True, -6),
                                      _v("near", 84.0, True, 0)])
    assert ranked[0].label == "near"


def test_source_lifetime_ranking_unaffected_by_line_delta():
    # line_delta participates ONLY for statement-order. Construct the DISTINGUISHING
    # case: the higher-% variant has the LARGER line_delta. If line_delta were wrongly
    # applied to source-lifetime it would rank before match% and put `b` (line_delta 0)
    # first; correct behavior ignores line_delta here, so higher-% `a` wins.
    a = _v("a", 90.0, True, 9, axis="source-lifetime")   # higher %, LARGER line_delta
    b = _v("b", 84.0, True, 0, axis="source-lifetime")   # lower %, smaller line_delta
    ranked = rank_structure_variants([b, a])             # input order must not matter
    assert [v.label for v in ranked] == ["a", "b"]


from src.search.structure import run_structure_search, StructureScoreResult

RANK_SRC = '''\
void f(int idx, float spacing)
{
    Vec3 translate;
    Vec3 pos;
    Vec3 result;
    int tag;
    int mid;
    int echo;
    pos.x = translate.x;
    pos.y = spacing;
    pos.z = translate.z;
    tag = idx;
    mid = idx;
    result.x = pos.x;
    echo = tag;
}
'''


def test_run_structure_search_ranks_statement_order_by_shape(tmp_path):
    src = tmp_path / "f.c"
    src.write_text(RANK_SRC)

    def fake_score(variants):
        # Mark the candidate that WINS the base (non-shape) tiebreak — alphabetically
        # smallest (operator, label) — as shape-breaking. Without the Task 8 shape
        # ranking, that candidate would occupy variants[0] and FAIL the assertion;
        # only shape ranking can demote it and float a shape-preserved variant to the
        # top. This makes the test a real guard, not just a production-path smoke.
        base_winner = min(range(len(variants)),
                          key=lambda i: (variants[i].operator, variants[i].label))
        results = []
        for i, v in enumerate(variants):
            preserved = (i != base_winner)
            results.append(StructureScoreResult(
                label=v.label, baseline_percent=80.0, candidate_percent=80.0,
                compile_status="ok", checkdiff_status="ok",
                structural={"opcode_shape_preserved": preserved, "line_delta": 0}))
        return results

    payload = run_structure_search(
        function="f", source_path=str(src), output_dir=str(tmp_path / "out"),
        axes=["statement-order"], baseline_percent=80.0,
        score_runner=fake_score, score_variants=True)
    variants = payload["variants"]
    if len(variants) < 2:
        import pytest; pytest.skip("need >=2 generated candidates to prove ranking")
    top = variants[0]
    assert top["metadata"]["structural"]["opcode_shape_preserved"] is True
