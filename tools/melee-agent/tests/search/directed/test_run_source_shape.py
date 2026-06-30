"""Tests for directed run source-shape proposal helpers."""

from pathlib import Path

from src.search.directed.anchors import Anchor
from src.search.directed.run import (
    _apply_candidate_text_or_mutator,
    _source_shape_proposal,
)
from src.search.directed.source import DirectedSource
from src.search.types import SourceSpec, TargetSpec


def _transform_fixture() -> str:
    return (
        "void target(void)\n"
        "{\n"
        "    int x;\n"
        "    x = 1;\n"
        "    x = 2;\n"
        "}\n"
    )


def test_source_shape_proposal_without_function_or_unit_returns_none():
    src = (
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "} else {\n"
        "    if (kind != FTKIND_KIRBY) {\n"
        "        reload = false;\n"
        "    }\n"
        "}\n"
    )

    assert _source_shape_proposal(src, frozenset()) is None
    assert (
        _source_shape_proposal(
            src,
            frozenset(),
            function="target",
        )
        is None
    )
    assert (
        _source_shape_proposal(
            src,
            frozenset(),
            unit="melee/test/target",
        )
        is None
    )


def test_source_shape_proposal_uses_transform_corpus_fallback():
    src = _transform_fixture()

    proposal = _source_shape_proposal(
        src,
        frozenset(),
        function="target",
        unit="melee/test/target",
        force_phys={},
    )

    assert proposal is not None
    key, anchor, meta = proposal
    assert key.startswith("transform-corpus:")
    assert anchor is None
    assert meta["source_shape"] is True
    assert meta["transform_corpus"] is True
    assert meta["proof_vector_planned"] is True
    assert meta["candidate_text"] != src
    assert meta["probe"]["probe_id"]
    assert meta["probe"]["family_id"]
    assert meta["probe"]["family_label"]
    assert meta["probe"]["mutator_key"]
    assert meta["probe"]["semantic_risk"]
    assert meta["probe"]["source_region"]
    assert meta["probe"]["expected_compiler_effect"]
    assert meta["probe"]["generated_probe_form"]
    assert isinstance(meta["probe"]["target_assignments"], list)
    assert isinstance(meta["probe"]["span"], list)
    assert isinstance(meta["probe"]["payload"], dict)
    assert not meta.get("non_actionable", False)


def test_source_shape_proposal_skips_tried_transform_key():
    src = _transform_fixture()

    first = _source_shape_proposal(
        src,
        frozenset(),
        function="target",
        unit="melee/test/target",
        force_phys={},
    )
    assert first is not None

    second = _source_shape_proposal(
        src,
        frozenset({first[0]}),
        function="target",
        unit="melee/test/target",
        force_phys={},
    )

    assert second is None or second[0] != first[0]


def test_source_shape_proposal_skips_explicit_zero_return_without_target_function():
    src = "{\n    repeated(arg0);\n}\n"

    assert _source_shape_proposal(src, frozenset()) is None


def test_source_shape_proposal_targets_explicit_zero_return_to_named_int_function():
    src = (
        "int helper(int arg0) {\n"
        "    repeated(arg0);\n"
        "}\n"
        "int target(int arg0) {\n"
        "    repeated(arg0);\n"
        "}\n"
    )

    proposal = _source_shape_proposal(
        src,
        frozenset(),
        function="target",
        unit="melee/test/target",
        force_phys={},
    )

    assert proposal is not None
    key, anchor, meta = proposal
    assert key == "transform-corpus:explicit_zero_return:0"
    assert anchor is None
    assert meta["source_shape"] is True
    assert meta["transform_corpus"] is True
    assert meta["probe"]["mutator_key"] == "add_explicit_zero_return"
    assert meta["probe"]["span"][0] > src.index("int target")
    assert meta["candidate_text"] == (
        "int helper(int arg0) {\n"
        "    repeated(arg0);\n"
        "}\n"
        "int target(int arg0) {\n"
        "    repeated(arg0);\n"
        "    return 0;\n"
        "}\n"
    )


def test_source_shape_proposal_skips_explicit_zero_return_for_named_void_function():
    src = (
        "void target(int arg0) {\n"
        "    repeated(arg0);\n"
        "}\n"
    )

    assert (
        _source_shape_proposal(
            src,
            frozenset(),
            function="target",
            unit="melee/test/target",
            force_phys={},
        )
        is None
    )


def test_apply_candidate_text_uses_transform_text_before_at_suffix_stripping():
    src = "void target(void) {}\n"
    candidate = "void target(void) { touched(); }\n"
    candidate_text_by_key = {
        "transform-corpus:demo:0@legacy": candidate,
    }

    assert (
        _apply_candidate_text_or_mutator(
            "transform-corpus:demo:0@legacy",
            None,
            src,
            candidate_text_by_key,
        )
        == candidate
    )


def test_apply_candidate_text_preserves_normal_mutator_keys():
    src = "void target(void) {\n    int x;\n    int y;\n}\n"
    anchor = Anchor(
        mutator_key="reorder_local_decls",
        span=(20, 39),
        payload={
            "first_line": "    int x;",
            "second_line": "    int y;",
        },
    )

    assert _apply_candidate_text_or_mutator(
        "reorder_local_decls@0",
        anchor,
        src,
        {},
    ) == "void target(void) {\n    int y;\n    int x;\n}\n"


def test_directed_source_transform_candidate_does_not_retry_same_probe():
    src = _transform_fixture()
    emitted: list[str] = []
    candidate_text_by_key: dict[str, str] = {}

    def propose(source_text: str, tried: frozenset):
        proposal = _source_shape_proposal(
            source_text,
            tried,
            function="target",
            unit="melee/test/target",
            force_phys={},
        )
        if proposal is None:
            return None
        key, anchor, meta = proposal
        candidate_text_by_key[key] = meta["candidate_text"]
        emitted.append(key)
        return proposal

    source = DirectedSource(
        propose=propose,
        apply=lambda key, anchor, source_text: _apply_candidate_text_or_mutator(
            key,
            anchor,
            source_text,
            candidate_text_by_key,
        ),
    )
    source.seed(
        SourceSpec(
            src,
            TargetSpec(
                function="target",
                unit="melee/test/target",
                expected_obj=Path("target.o"),
            ),
        )
    )

    first_batch = source.next_batch(1)
    second_batch = source.next_batch(1)

    assert len(first_batch) == 1
    assert second_batch
    assert first_batch[0].provenance.mutation != second_batch[0].provenance.mutation
    assert emitted[0] != emitted[1]
