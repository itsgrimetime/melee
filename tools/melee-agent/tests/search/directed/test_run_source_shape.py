"""Tests for directed run source-shape proposal helpers."""

from src.search.directed.run import _source_shape_proposal


def test_source_shape_proposal_returns_actionable_indexed_anchor():
    src = (
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "} else {\n"
        "    if (kind != FTKIND_KIRBY) {\n"
        "        reload = false;\n"
        "    }\n"
        "}\n"
    )

    proposal = _source_shape_proposal(src, frozenset())

    assert proposal is not None
    key, anchor, meta = proposal
    assert key.startswith("flatten_nested_if@")
    assert anchor.mutator_key == "flatten_nested_if"
    assert meta == {"source_shape": True}
    assert not meta.get("non_actionable", False)


def test_source_shape_proposal_skips_tried_indexed_anchor():
    src = (
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "} else {\n"
        "    if (kind != FTKIND_KIRBY) {\n"
        "        reload = false;\n"
        "    }\n"
        "}\n"
    )

    proposal = _source_shape_proposal(src, frozenset({"flatten_nested_if@0"}))

    assert proposal is None or proposal[0] != "flatten_nested_if@0"
