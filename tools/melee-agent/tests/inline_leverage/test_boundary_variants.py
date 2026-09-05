import re

from src.inline_leverage.boundary_variants import (
    DIMENSIONS,
    FAMILY_ID,
    VOID_DIMENSIONS,
    build_terminal_proof,
    generate_boundary_candidates,
    parse_target_map,
    rank_score_payloads,
)


SOURCE = """
static inline int mnDiagram_SumNameKOs(u8 field_index)
{
    int total;
    int j;
    total = 0;
    for (j = total; j < 0x78; j++) {
        if (GetNameText(j & 0xFF)) {
            total += GetPersistentNameData(field_index)->vs_kos[(u8) j];
        }
    }
    return total;
}

void mnDiagram_SortNamesByKOs(void)
{
    u8* dst_iter;
    u32 totals[0x78];
    u32* tp;
    int n;

    dst_iter = mnDiagram_804A076C.sorted_names;
    tp = totals;
    for (n = 0; n < 0x78; n++, dst_iter++, tp++) {
        *dst_iter = (u8) n;
        *tp = mnDiagram_SumNameKOs(n & 0xFF);
    }
}
"""


RECORD = {
    "run_id": "test-run",
    "function": "mnDiagram_SortNamesByKOs",
    "unit": "src/melee/mn/mndiagram.c",
    "inline_name": "mnDiagram_SumNameKOs",
    "verdict": "lever",
    "expansion_form": "scalar_assignment_splice",
    "shape_return": "scalar",
    "shape_body": "multi_statement",
    "shape_args": ["expression"],
    "evidence": {"score": "score.json"},
}


VOID_SOURCE = """
static inline void HSD_JObjSetTranslateY_Fake(HSD_JObj* jobj, f32 y)
{
    jobj->translate.y = y;
    HSD_JObjSetMtxDirtySub(jobj);
}

void mnDiagram3_8024714C(HSD_JObj* popup_jobj, HSD_JObj* row0, f32 row_spacing, int k)
{
    HSD_JObjSetTranslateY_Fake(
        popup_jobj,
        HSD_JObjGetTranslationY(row0) + (row_spacing * k));
}
"""


VOID_RECORD = {
    "run_id": "void-test-run",
    "function": "mnDiagram3_8024714C",
    "unit": "src/melee/mn/mndiagram3.c",
    "inline_name": "HSD_JObjSetTranslateY_Fake",
    "verdict": "lever",
    "expansion_form": "statement_splice",
    "shape_return": "void",
    "shape_body": "multi_statement",
    "shape_args": ["plain_id", "expression"],
}


def _candidates() -> list[dict]:
    result = generate_boundary_candidates(
        SOURCE,
        RECORD,
        "mnDiagram_SortNamesByKOs",
    )
    assert result["status"] == "ok"
    return result["candidates"]


def _by_dimension(candidates: list[dict]) -> dict[str, dict]:
    return {candidate["dimension_id"]: candidate for candidate in candidates}


def _flat_score(candidate: dict, distance: int = 2) -> dict:
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_order": candidate["candidate_order"],
        "target_score": {
            "matched": 0,
            "targeted": 2,
            "virtual_distance": distance,
            "virtuals": {
                "34": {"expected": 27, "actual": 29, "matched": False},
                "44": {"expected": 25, "actual": 27, "matched": False},
            },
        },
    }


def _void_flat_score(candidate: dict, distance: int = 0) -> dict:
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_order": candidate["candidate_order"],
        "target_score": {
            "matched": 0,
            "targeted": 0,
            "virtual_distance": distance,
            "virtuals": {},
        },
    }


def _void_checkdiff_score(candidate: dict, percent: float = 97.5) -> dict:
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_order": candidate["candidate_order"],
        "checkdiff": {
            "match": False,
            "fuzzy_match_percent": percent,
            "baseline_fuzzy_match_percent": 97.5,
            "classification": {"primary": "signature-type-mismatch"},
        },
    }


def test_generates_all_six_dimensions_with_stable_unique_ids() -> None:
    first = _candidates()
    second = _candidates()

    assert [candidate["candidate_id"] for candidate in first] == [
        candidate["candidate_id"] for candidate in second
    ]
    assert {candidate["dimension_id"] for candidate in first} == set(DIMENSIONS)
    assert len(first) == len(DIMENSIONS)
    assert len({candidate["candidate_id"] for candidate in first}) == len(first)
    assert len({candidate["source_text"] for candidate in first}) == len(first)

    for candidate in first:
        assert candidate["family_id"] == FAMILY_ID
        assert candidate["variant"]
        assert candidate["dimension_id"] in candidate["candidate_id"]
        assert candidate["variant"] in candidate["candidate_id"]
        assert candidate["source_sha256"][:16] in candidate["candidate_id"]
        definitions = re.findall(
            r"\bstatic\s+inline\s+\w+\s+mnDiagram_SumNameKOs\s*\(",
            candidate["source_text"],
        )
        assert len(definitions) == 1
        assert "*tp = *tp =" not in candidate["source_text"]
        assert candidate["source_hunks"]


def test_dimension_variants_are_narrow_source_mutations() -> None:
    by_dimension = _by_dimension(_candidates())

    assert "mnDiagram_SumNameKOs(int field_index)" in (
        by_dimension["signature"]["source_text"]
    )
    assert "    int j;\n    int total;\n" in (
        by_dimension["local_declarations"]["source_text"]
    )
    assert "for (j = 0; j < 0x78; j++)" in (
        by_dimension["loop_init"]["source_text"]
    )
    assert "*tp = mnDiagram_SumNameKOs((u8) n);" in (
        by_dimension["call_argument"]["source_text"]
    )
    assert "    int result;\n" in (
        by_dimension["return_local_materialization"]["source_text"]
    )
    assert "    result = total;\n    return result;" in (
        by_dimension["return_local_materialization"]["source_text"]
    )

    splice_source = by_dimension["scalar_assignment_splice_boundary"]["source_text"]
    assert "GetPersistentNameData(n & 0xFF)->vs_kos[(u8) j]" in splice_source
    assert "*tp = total;" in splice_source
    assert "*tp = mnDiagram_SumNameKOs(n & 0xFF);" not in splice_source


def test_void_statement_splice_generates_bounded_helper_boundary_candidates() -> None:
    result = generate_boundary_candidates(
        VOID_SOURCE,
        VOID_RECORD,
        "mnDiagram3_8024714C",
    )

    assert result["status"] == "ok"
    assert result["dimensions"] == list(VOID_DIMENSIONS)
    assert {candidate["dimension_id"] for candidate in result["candidates"]} == set(
        VOID_DIMENSIONS
    )

    by_dimension = _by_dimension(result["candidates"])
    splice = by_dimension["void_statement_splice_boundary"]["source_text"]
    assert "popup_jobj->translate.y = HSD_JObjGetTranslationY(row0) + (row_spacing * k);" in splice
    assert "HSD_JObjSetMtxDirtySub(popup_jobj);" in splice
    assert "HSD_JObjSetTranslateY_Fake(" not in splice.split(
        "void mnDiagram3_8024714C", 1
    )[1]

    value_temp = by_dimension["void_value_argument_temp"]["source_text"]
    assert "f32 inline_y_arg = HSD_JObjGetTranslationY(row0) + (row_spacing * k);" in value_temp
    assert "HSD_JObjSetTranslateY_Fake(popup_jobj, inline_y_arg);" in value_temp

    direct = by_dimension["void_direct_helper_call"]["source_text"]
    assert "HSD_JObjSetTranslateY(\n        popup_jobj," in direct

    for candidate in result["candidates"]:
        assert candidate["source_hunks"]


def test_blocked_diagnostics_name_skipped_dimension_for_missing_and_ambiguous() -> None:
    missing_inline = SOURCE.replace(
        "static inline int mnDiagram_SumNameKOs",
        "static inline int mnDiagram_OtherSumNameKOs",
        1,
    )
    result = generate_boundary_candidates(
        missing_inline,
        RECORD,
        "mnDiagram_SortNamesByKOs",
    )
    assert result["status"] == "blocked"
    assert result["candidates"] == []
    assert {row["dimension_id"] for row in result["blocked_diagnostics"]} == set(
        DIMENSIONS
    )
    assert all(
        "missing inline definition" in row["reason"]
        for row in result["blocked_diagnostics"]
    )

    duplicate_call = SOURCE.replace(
        "        *tp = mnDiagram_SumNameKOs(n & 0xFF);\n",
        (
            "        *tp = mnDiagram_SumNameKOs(n & 0xFF);\n"
            "        *tp = mnDiagram_SumNameKOs(n & 0xFF);\n"
        ),
    )
    result = generate_boundary_candidates(
        duplicate_call,
        RECORD,
        "mnDiagram_SortNamesByKOs",
    )
    assert result["status"] == "blocked"
    assert {row["dimension_id"] for row in result["blocked_diagnostics"]} == set(
        DIMENSIONS
    )
    assert all(
        "ambiguous call site" in row["reason"]
        for row in result["blocked_diagnostics"]
    )


def test_void_blocked_diagnostics_use_void_dimensions() -> None:
    result = generate_boundary_candidates(
        VOID_SOURCE.replace("HSD_JObjSetTranslateY_Fake", "MissingTranslateY_Fake", 1),
        VOID_RECORD,
        "mnDiagram3_8024714C",
    )

    assert result["status"] == "blocked"
    assert result["candidates"] == []
    assert {row["dimension_id"] for row in result["blocked_diagnostics"]} == set(
        VOID_DIMENSIONS
    )


def test_target_map_defaults_and_parsing() -> None:
    assert parse_target_map(None, function="mnDiagram_SortNamesByKOs") == {
        "34": 27,
        "44": 25,
    }
    assert parse_target_map("34:r27,44:25") == {"34": 27, "44": 25}
    assert parse_target_map('{"34": "27", "44": 25}') == {"34": 27, "44": 25}


def test_ranking_prefers_ig34_ig44_progress_then_distance_and_order() -> None:
    candidates = _candidates()
    flat = _flat_score(candidates[0], distance=2)
    farther_flat = _flat_score(candidates[1], distance=4)
    improving = {
        "candidate_id": candidates[2]["candidate_id"],
        "candidate_order": candidates[2]["candidate_order"],
        "target_score": {
            "matched": 1,
            "targeted": 2,
            "virtual_distance": 1,
            "virtuals": {
                "34": {"expected": 27, "actual": 29, "matched": False},
                "44": {"expected": 25, "actual": 25, "matched": True},
            },
        },
    }

    ranked = rank_score_payloads(
        [farther_flat, improving, flat],
        target_map={"34": 27, "44": 25},
        candidates=candidates,
    )

    assert ranked[0]["candidate_id"] == improving["candidate_id"]
    assert ranked[0]["rank_score"]["target_matched"] == 1
    assert ranked[1]["candidate_id"] == flat["candidate_id"]
    assert ranked[2]["candidate_id"] == farther_flat["candidate_id"]


def test_terminal_proof_names_all_exhausted_dimensions() -> None:
    candidates = _candidates()
    scores = [_flat_score(candidate) for candidate in candidates]

    proof = build_terminal_proof(
        function="mnDiagram_SortNamesByKOs",
        record=RECORD,
        candidates=candidates,
        score_payloads=scores,
    )

    assert proof is not None
    assert proof["family_id"] == FAMILY_ID
    assert proof["status"] == "terminal"
    assert proof["terminal_reason"] == (
        "inline-leverage-helper-boundary-exhausted/no-ig34-ig44-progress"
    )
    assert proof["candidate_count"] == len(DIMENSIONS)
    assert proof["scored_count"] == len(DIMENSIONS)
    assert {row["dimension_id"] for row in proof["exhausted_dimensions"]} == set(
        DIMENSIONS
    )

    improved = list(scores)
    improved[0] = {
        **improved[0],
        "target_score": {
            **improved[0]["target_score"],
            "matched": 1,
            "virtuals": {
                "34": {"expected": 27, "actual": 27, "matched": True},
                "44": {"expected": 25, "actual": 27, "matched": False},
            },
        },
    }
    assert build_terminal_proof(
        function="mnDiagram_SortNamesByKOs",
        record=RECORD,
        candidates=candidates,
        score_payloads=improved,
    ) is None


def test_void_terminal_proof_names_bounded_void_dimensions() -> None:
    result = generate_boundary_candidates(
        VOID_SOURCE,
        VOID_RECORD,
        "mnDiagram3_8024714C",
    )
    candidates = result["candidates"]
    scores = [_void_flat_score(candidate) for candidate in candidates]

    proof = build_terminal_proof(
        function="mnDiagram3_8024714C",
        record=VOID_RECORD,
        candidates=candidates,
        score_payloads=scores,
    )

    assert proof is not None
    assert proof["terminal_reason"] == (
        "inline-leverage-helper-boundary-exhausted/no-target-progress"
    )
    assert proof["candidate_count"] == len(VOID_DIMENSIONS)
    assert proof["scored_count"] == len(VOID_DIMENSIONS)
    assert {row["dimension_id"] for row in proof["exhausted_dimensions"]} == set(
        VOID_DIMENSIONS
    )
    assert {row["exhaustion_reason"] for row in proof["exhausted_dimensions"]} == {
        "no-target-progress"
    }


def test_void_terminal_proof_accepts_checkdiff_evidence() -> None:
    result = generate_boundary_candidates(
        VOID_SOURCE,
        VOID_RECORD,
        "mnDiagram3_8024714C",
    )
    candidates = result["candidates"]
    scores = [
        _void_checkdiff_score(candidate, percent=90.0 + index)
        for index, candidate in enumerate(candidates)
    ]

    proof = build_terminal_proof(
        function="mnDiagram3_8024714C",
        record=VOID_RECORD,
        candidates=candidates,
        score_payloads=scores,
    )

    assert proof is not None
    assert proof["terminal_reason"] == (
        "inline-leverage-helper-boundary-exhausted/no-target-progress"
    )
    assert {
        row["dimension_id"] for row in proof["exhausted_dimensions"]
    } == set(VOID_DIMENSIONS)
    assert max(
        row["best_checkdiff_fuzzy_match_percent"]
        for row in proof["exhausted_dimensions"]
    ) == 92.0
    assert proof["ranked_candidates"][0]["checkdiff"]["fuzzy_match_percent"] == 90.0

    improved = list(scores)
    improved[0] = _void_checkdiff_score(candidates[0], percent=98.0)
    assert build_terminal_proof(
        function="mnDiagram3_8024714C",
        record=VOID_RECORD,
        candidates=candidates,
        score_payloads=improved,
    ) is None
