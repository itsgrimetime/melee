from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.cli.debug.suggest import (
    _load_protected_reconcile_candidate_scores,
    _score_json_file_base,
)
from src.mwcc_debug.protected_expression_reconciliation import (
    _payload_candidate_id,
    build_anchor_requirements,
    evaluate_anchor_preservation,
    reconcile_frontiers,
)
from src.mwcc_debug.source_hunks import (
    SourceHunk,
    diff_line_hunks,
    line_ranges_overlap,
    manual_subhunks_from_source_hunks,
    source_hunk_from_mapping,
    split_hunk_conservatively,
)


runner = CliRunner()


def _anchor(
    baseline_virtual: int,
    name: str,
    *,
    expected: int,
    actual: int | None,
    candidate_virtual: int | None = None,
    matched: bool | None = None,
    status: str = "ok",
    opcode: str | None = None,
) -> dict:
    if matched is None:
        matched = actual == expected and status == "ok"
    signature = (
        {
            "kind": "first-def",
            "source_kind": "local",
            "name": name,
            "opcode": opcode,
            "operands": "<dst>,f1,f2",
        }
        if opcode is not None
        else {
            "kind": "name",
            "source_kind": "local",
            "name": name,
        }
    )
    return {
        "baseline_virtual": baseline_virtual,
        "expected": expected,
        "signature": signature,
        "baseline_source": {"kind": "local", "name": name},
        "candidate_source": {"kind": "local", "name": name},
        "candidate_virtual": (
            baseline_virtual if candidate_virtual is None else candidate_virtual
        ),
        "actual": actual,
        "matched": matched,
        "status": status,
    }


def _expression_score(*anchors: dict, false_positive_count: int = 0) -> dict:
    matched = sum(1 for anchor in anchors if anchor.get("matched") is True)
    false_hits = [
        {
            "baseline_virtual": 999,
            "expected": 26,
            "actual": 26,
            "signature": {"kind": "name", "name": "raw_virtual_false_hit"},
        }
        for _ in range(false_positive_count)
    ]
    return {
        "register_class": "fpr",
        "matched": matched,
        "targeted": len(anchors),
        "virtual_distance": len(anchors) - matched,
        "renumbered": sum(
            1
            for anchor in anchors
            if anchor.get("candidate_virtual") != anchor.get("baseline_virtual")
        ),
        "false_positive_virtual_id_hit_count": false_positive_count,
        "false_positive_virtual_id_hits": false_hits,
        "virtuals": {
            str(anchor["baseline_virtual"]): anchor
            for anchor in anchors
        },
    }


def _six_hit_score(*, normalized: int = 30, accepted: bool = False) -> dict:
    anchors = (
        _anchor(33, "fsubs_left", expected=26, actual=26, opcode="fsubs"),
        _anchor(35, "fsubs_right", expected=26, actual=26, opcode="fsubs"),
        _anchor(40, "row_product", expected=28, actual=28),
        _anchor(41, "digit_a", expected=29, actual=29),
        _anchor(42, "digit_b", expected=29, actual=29),
        _anchor(43, "digit_c", expected=29, actual=29),
    )
    return _score_payload(
        _expression_score(*anchors),
        normalized=normalized,
        accepted=accepted,
        frame_size=176 if normalized >= 30 else 168,
    )


def _four_hit_score(*, normalized: int = 20, accepted: bool = False) -> dict:
    anchors = (
        _anchor(
            33,
            "fsubs_left",
            expected=26,
            actual=None,
            matched=False,
            status="missing-expression",
            opcode="fsubs",
        ),
        _anchor(
            35,
            "fsubs_right",
            expected=26,
            actual=None,
            matched=False,
            status="missing-expression",
            opcode="fsubs",
        ),
        _anchor(40, "row_product", expected=28, actual=28),
        _anchor(41, "digit_a", expected=29, actual=29),
        _anchor(42, "digit_b", expected=29, actual=29),
        _anchor(43, "digit_c", expected=29, actual=29),
    )
    return _score_payload(
        _expression_score(*anchors),
        normalized=normalized,
        accepted=accepted,
        frame_size=168,
    )


def _score_payload(
    expression_score: dict,
    *,
    normalized: int,
    accepted: bool,
    frame_size: int = 176,
    candidate_id: str | None = None,
) -> dict:
    payload = {
        "score": 0,
        "expression_score": expression_score,
        "target_score": {"frame": {"size_actual": frame_size}},
        "structural_guard": {
            "accepted": accepted,
            "normalized_diff_lines": normalized,
            "current_frame_size": frame_size,
        },
    }
    if candidate_id is not None:
        payload["candidate_id"] = candidate_id
    return payload


def _expression_source(function: str = "mnDiagram_80241E78") -> str:
    return (
        "typedef float f32;\n"
        "extern int mn_GetDigitCount(int value);\n"
        "extern void draw_digit(f32 value);\n"
        f"void {function}(int value, int digit, f32 scale)\n"
        "{\n"
        "    f32 rowf;\n"
        "    f32 product;\n"
        "    int digit_count;\n"
        "\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    rowf = (f32) digit;\n"
        "    product = scale * rowf;\n"
        "    draw_digit(product);\n"
        "}\n"
    )


def _structural_source(function: str = "mnDiagram_80241E78") -> str:
    return (
        "typedef float f32;\n"
        "extern int mn_GetDigitCount(int value);\n"
        "extern void draw_digit(f32 value);\n"
        f"void {function}(int value, int digit, f32 scale)\n"
        "{\n"
        "    int digit_count;\n"
        "\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    draw_digit(scale * (f32) digit);\n"
        "}\n"
    )


def _row_delta_expression_source(function: str = "mnDiagram_80241E78") -> str:
    return (
        "typedef float f32;\n"
        "extern void translate_y(f32 value);\n"
        f"void {function}(f32 row_offset)\n"
        "{\n"
        "    f32 row_offset_adj;\n"
        "\n"
        "    if (row_offset > 0.0f) {\n"
        "        row_offset_adj = row_offset;\n"
        "        translate_y(row_offset_adj);\n"
        "    }\n"
        "}\n"
    )


def _row_delta_structural_source(function: str = "mnDiagram_80241E78") -> str:
    return (
        "typedef float f32;\n"
        "extern void translate_y(f32 value);\n"
        f"void {function}(f32 row_offset)\n"
        "{\n"
        "    f32 row_offset_adj;\n"
        "\n"
        "    if (row_offset >= 0.0f) {\n"
        "        row_offset_adj = row_offset - 1.0f;\n"
        "        translate_y(row_offset_adj);\n"
        "    }\n"
        "}\n"
    )


def _row_delta_source_hunks() -> list[dict]:
    return [
        {
            "hunk_id": "draw-row-delta-parent",
            "base_start": 4,
            "base_end": 8,
            "candidate_start": 4,
            "candidate_end": 8,
            "removed": [
                "    if (row_offset > 0.0f) {",
                "        row_offset_adj = row_offset;",
                "        translate_y(row_offset_adj);",
                "    }",
            ],
            "added": [
                "    if (row_offset >= 0.0f) {",
                "        row_offset_adj = row_offset - 1.0f;",
                "        translate_y(row_offset_adj);",
                "    }",
            ],
            "protected_subhunks": [
                {
                    "hunk_id": "draw-row-delta-parent-row-delta",
                    "base_start": 5,
                    "base_end": 6,
                    "candidate_start": 5,
                    "candidate_end": 6,
                    "removed": ["        row_offset_adj = row_offset;"],
                    "added": ["        row_offset_adj = row_offset - 1.0f;"],
                    "source_expression": "row_offset_adj",
                    "target_virtuals": [37],
                }
            ],
        }
    ]


def test_anchor_preservation_allows_candidate_virtual_renumbering() -> None:
    baseline = _expression_score(
        _anchor(33, "fsubs_left", expected=26, actual=26, opcode="fsubs"),
    )
    requirements, blockers = build_anchor_requirements(baseline)
    assert blockers == ()

    candidate = {
        "expression_score": _expression_score(
            _anchor(
                33,
                "fsubs_left",
                expected=26,
                actual=26,
                candidate_virtual=88,
                opcode="fsubs",
            ),
        )
    }

    preservation, preserved, lost = evaluate_anchor_preservation(
        candidate,
        requirements,
    )

    assert preserved == 1
    assert lost == ()
    assert preservation[33]["candidate_virtual"] == 88
    assert preservation[33]["renumbered"] is True


def test_anchor_preservation_rejects_missing_and_false_positive_hits() -> None:
    baseline = _expression_score(
        _anchor(33, "fsubs_left", expected=26, actual=26, opcode="fsubs"),
    )
    requirements, _blockers = build_anchor_requirements(baseline)
    candidate = {
        "expression_score": _expression_score(
            _anchor(
                33,
                "fsubs_left",
                expected=26,
                actual=None,
                matched=False,
                status="missing-expression",
                opcode="fsubs",
            ),
            false_positive_count=1,
        )
    }

    _preservation, preserved, lost = evaluate_anchor_preservation(
        candidate,
        requirements,
    )

    assert preserved == 0
    assert "protected-virtual-id-false-positive" in lost
    assert "protected-anchor-missing-expression:33" in lost


def test_source_hunk_coordinates_overlap_and_brace_control_fallback() -> None:
    insertion = diff_line_hunks("a\nb\n", "a\nx\nb\n")[0]
    assert insertion.base_start == 1
    assert insertion.base_end == 1
    assert insertion.to_dict()["base_range"] == {
        "start": 2,
        "end": 1,
        "empty": True,
    }
    assert line_ranges_overlap(1, 3, 3, 3) is True
    assert line_ranges_overlap(1, 2, 2, 3) is False

    crossing = SourceHunk(
        hunk_id="h001",
        base_start=1,
        base_end=4,
        candidate_start=1,
        candidate_end=4,
        removed=("    if (x) {", "        a();", "    }"),
        added=("    if (y) {", "        b();", "    }"),
    )
    split = split_hunk_conservatively(crossing)

    assert split.hunks == ()
    assert split.blockers[0]["blocker"] == "manual-subhunk-range-required"
    assert "control-boundary" in split.blockers[0]["reasons"]


def test_source_hunk_parser_normalizes_manual_child_shapes() -> None:
    legacy_parent = {
        "hunk_id": "draw-parent",
        "old_start": 10,
        "old_lines": ["if (x) {", "    row_offset_adj = row_offset;", "}"],
        "new_start": 10,
        "new_lines": ["if (x) {", "    row_offset_adj = row_offset - y;", "}"],
        "protected_subhunks": [
            {
                "old_start": 11,
                "old_lines": ["    row_offset_adj = row_offset;"],
                "new_start": 11,
                "new_lines": ["    row_offset_adj = row_offset - y;"],
            }
        ],
    }

    parent = source_hunk_from_mapping(legacy_parent)
    children = manual_subhunks_from_source_hunks([legacy_parent])

    assert parent.base_start == 9
    assert parent.base_end == 12
    assert children[0].base_start == 10
    assert children[0].base_end == 11
    assert children[0].parent_hunk_id == "draw-parent"
    assert "manual-protected-expression-subhunk" in children[0].blockers

    ranged = source_hunk_from_mapping({
        "hunk_id": "range-parent",
        "base_range": {"start": 5, "end": 6},
        "candidate_range": {"start": 5, "end": 6},
        "removed": ["a;", "b;"],
        "added": ["c;", "d;"],
    })
    assert (ranged.base_start, ranged.base_end) == (4, 6)

    invalid = dict(legacy_parent)
    invalid["protected_subhunks"] = [
        {
            "old_start": 20,
            "old_lines": ["row_offset_adj = row_offset;"],
            "new_start": 20,
            "new_lines": ["row_offset_adj = row_offset - y;"],
        }
    ]
    assert manual_subhunks_from_source_hunks([invalid]) == ()


def test_reconcile_uses_explicit_protected_child_subhunk() -> None:
    generated = reconcile_frontiers(
        expression_source_text=_row_delta_expression_source(),
        expression_score_payload=_score_payload(
            _expression_score(
                _anchor(37, "row_offset_adj", expected=26, actual=26),
            ),
            normalized=30,
            accepted=False,
        ),
        structural_source_text=_row_delta_structural_source(),
        structural_score_payload=_score_payload(
            _expression_score(
                _anchor(
                    37,
                    "row_offset_adj",
                    expected=26,
                    actual=None,
                    matched=False,
                    status="missing-expression",
                ),
            ),
            normalized=0,
            accepted=False,
        ),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=1,
        source_hunks=_row_delta_source_hunks(),
    )
    candidate = generated.candidates[0]
    candidate_score = _score_payload(
        _expression_score(_anchor(37, "row_offset_adj", expected=26, actual=26)),
        normalized=0,
        accepted=True,
        candidate_id=candidate.candidate_id,
    )

    scored = reconcile_frontiers(
        expression_source_text=_row_delta_expression_source(),
        expression_score_payload=_score_payload(
            _expression_score(_anchor(37, "row_offset_adj", expected=26, actual=26)),
            normalized=30,
            accepted=False,
        ),
        structural_source_text=_row_delta_structural_source(),
        structural_score_payload=_score_payload(
            _expression_score(
                _anchor(
                    37,
                    "row_offset_adj",
                    expected=26,
                    actual=None,
                    matched=False,
                    status="missing-expression",
                ),
            ),
            normalized=0,
            accepted=False,
        ),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=1,
        source_hunks=_row_delta_source_hunks(),
        candidate_score_payloads=(candidate_score,),
    )
    payload = scored.to_dict()

    assert payload["status"] == "success"
    assert payload["candidates"][0]["provenance"]["manual_subhunk"] is True
    assert payload["candidates"][0]["applied_hunks"][0]["parent_hunk_id"] == (
        "draw-row-delta-parent"
    )
    assert not any(
        blocker["blocker"] == "manual-subhunk-range-required"
        for blocker in payload["terminal_blockers"]
    )
    assert _payload_candidate_id({
        "score_json": f"/tmp/{candidate.candidate_id}.score.json"
    }) == candidate.candidate_id


def test_reconcile_keeps_manual_blocker_without_child_subhunk() -> None:
    scored = reconcile_frontiers(
        expression_source_text=_row_delta_expression_source(),
        expression_score_payload=_score_payload(
            _expression_score(_anchor(37, "row_offset_adj", expected=26, actual=26)),
            normalized=30,
            accepted=False,
        ),
        structural_source_text=_row_delta_structural_source(),
        structural_score_payload=_score_payload(
            _expression_score(
                _anchor(
                    37,
                    "row_offset_adj",
                    expected=26,
                    actual=None,
                    matched=False,
                    status="missing-expression",
                ),
                false_positive_count=1,
            ),
            normalized=0,
            accepted=False,
        ),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=1,
    )
    payload = scored.to_dict()

    assert payload["generated_count"] == 0
    assert any(
        blocker["blocker"] == "manual-subhunk-range-required"
        for blocker in payload["generation_blockers"]
    )
    assert any(
        blocker["blocker"] == "manual-subhunk-range-required"
        for blocker in payload["terminal_blockers"]
    )


def test_reconcile_generates_bounded_statement_candidates() -> None:
    report = reconcile_frontiers(
        expression_source_text=_expression_source(),
        expression_score_payload=_six_hit_score(normalized=30),
        structural_source_text=_structural_source(),
        structural_score_payload=_four_hit_score(normalized=20),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=2,
        max_candidates=8,
    )

    payload = report.to_dict(include_source=True)

    assert payload["status"] == "generated"
    assert payload["frontiers"]["target_function"] == "mnDiagram_DrawCellNumber"
    assert payload["frontiers"]["source_function"] == "mnDiagram_80241E78"
    assert payload["generated_count"] > 0
    assert any(
        "direct-callarg" in candidate["provenance"]["structural_intent"]
        for candidate in payload["candidates"]
    )
    first_hunk = payload["candidates"][0]["applied_hunks"][0]
    assert first_hunk["base_start"] == first_hunk["base_range"]["start"] - 1


def test_scored_six_of_six_at_threshold_reports_structural_ceiling() -> None:
    generated = reconcile_frontiers(
        expression_source_text=_expression_source(),
        expression_score_payload=_six_hit_score(normalized=30),
        structural_source_text=_structural_source(),
        structural_score_payload=_four_hit_score(normalized=20),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=1,
        max_candidates=1,
    )
    candidate_id = generated.candidates[0].candidate_id
    candidate_score = _six_hit_score(normalized=30, accepted=False)
    candidate_score["candidate_id"] = candidate_id

    scored = reconcile_frontiers(
        expression_source_text=_expression_source(),
        expression_score_payload=_six_hit_score(normalized=30),
        structural_source_text=_structural_source(),
        structural_score_payload=_four_hit_score(normalized=20),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=1,
        max_candidates=1,
        max_normalized_diff_lines=30,
        candidate_score_payloads=(candidate_score,),
    )

    payload = scored.to_dict()

    assert payload["status"] == "blocked"
    assert payload["best_preserving_candidate"]["normalized_diff_lines"] == 30
    assert payload["best_preserving_candidate"]["structural_improved"] is False
    assert any(
        blocker["blocker"] == "structural-ceiling-with-protected-anchors"
        for blocker in payload["terminal_blockers"]
    )


def test_scored_structural_improvement_that_loses_anchors_reports_blocker() -> None:
    generated = reconcile_frontiers(
        expression_source_text=_expression_source(),
        expression_score_payload=_six_hit_score(normalized=30),
        structural_source_text=_structural_source(),
        structural_score_payload=_four_hit_score(normalized=20),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=1,
        max_candidates=1,
    )
    candidate_id = generated.candidates[0].candidate_id
    candidate_score = _four_hit_score(normalized=20, accepted=False)
    candidate_score["candidate_id"] = candidate_id

    scored = reconcile_frontiers(
        expression_source_text=_expression_source(),
        expression_score_payload=_six_hit_score(normalized=30),
        structural_source_text=_structural_source(),
        structural_score_payload=_four_hit_score(normalized=20),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=1,
        max_candidates=1,
        candidate_score_payloads=(candidate_score,),
    )
    blockers = {
        blocker["blocker"]
        for blocker in scored.to_dict()["terminal_blockers"]
    }

    assert "all-recombines-lost-protected-anchors" in blockers
    assert "direct-callarg-anchor-incompatibility" in blockers


def test_candidate_score_payload_uses_score_json_filename_fallback() -> None:
    generated = reconcile_frontiers(
        expression_source_text=_expression_source(),
        expression_score_payload=_six_hit_score(normalized=30),
        structural_source_text=_structural_source(),
        structural_score_payload=_four_hit_score(normalized=20),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=1,
        max_candidates=1,
    )
    candidate_id = generated.candidates[0].candidate_id
    candidate_score = _six_hit_score(normalized=30, accepted=True)
    candidate_score["score_json"] = f"/tmp/{candidate_id}.score.json"

    scored = reconcile_frontiers(
        expression_source_text=_expression_source(),
        expression_score_payload=_six_hit_score(normalized=30),
        structural_source_text=_structural_source(),
        structural_score_payload=_four_hit_score(normalized=20),
        target_function="mnDiagram_DrawCellNumber",
        source_function="mnDiagram_80241E78",
        max_subhunks=1,
        max_candidates=1,
        candidate_score_payloads=(candidate_score,),
    )
    payload = scored.to_dict()

    assert payload["scored_count"] == 1
    scored_candidate = payload["candidates"][0]
    assert scored_candidate["candidate_id"] == candidate_id
    assert scored_candidate["score_payload"]["score_json"].endswith(".score.json")


def test_payload_candidate_id_uses_evidence_fields_only_as_fallback() -> None:
    assert _payload_candidate_id({
        "score_json": "/tmp/reconcile-h002.score.json",
    }) == "reconcile-h002"
    assert _payload_candidate_id({
        "path": "/tmp/reconcile-h002.pcdump.txt",
    }) == "reconcile-h002"
    assert _payload_candidate_id({
        "source_file": "/tmp/reconcile-h002.c",
    }) == "reconcile-h002"
    assert _payload_candidate_id({
        "score_json": "/tmp/reconcile-h002_score.json",
    }) == "reconcile-h002"
    assert _payload_candidate_id({
        "path": "/tmp/reconcile-h002.score",
    }) == "reconcile-h002"
    assert _payload_candidate_id({
        "source_file": "/tmp/reconcile-h002_score",
    }) == "reconcile-h002"

    assert _payload_candidate_id({
        "candidate_id": "explicit-candidate",
        "score_json": "/tmp/reconcile-h002.score.json",
    }) == "explicit-candidate"
    assert _payload_candidate_id({
        "id": "explicit-id",
        "path": "/tmp/reconcile-h002.pcdump.txt",
    }) == "explicit-id"
    assert _payload_candidate_id({
        "probe_id": "explicit-probe",
        "source_file": "/tmp/reconcile-h002.c",
    }) == "explicit-probe"


def test_cli_protected_reconcile_score_loader_normalizes_evidence_suffixes(
    tmp_path: Path,
) -> None:
    filenames = {
        "reconcile-h002.score.json": "reconcile-h002",
        "reconcile-h003_score.json": "reconcile-h003",
        "reconcile-h004.score": "reconcile-h004",
        "reconcile-h005_score": "reconcile-h005",
        "reconcile-h006.pcdump.txt": "reconcile-h006",
        "reconcile-h007.c": "reconcile-h007",
    }
    paths: list[Path] = []
    for filename in filenames:
        path = tmp_path / filename
        path.write_text(json.dumps({"score": 0}), encoding="utf-8")
        paths.append(path)

    payloads = _load_protected_reconcile_candidate_scores(
        ",".join(str(path) for path in paths)
    )

    assert [payload["candidate_id"] for payload in payloads] == [
        filenames[path.name] for path in paths
    ]
    assert [payload["score_json"] for payload in payloads] == [
        str(path.resolve()) for path in paths
    ]
    assert [
        _score_json_file_base(path) for path in paths
    ] == [filenames[path.name] for path in paths]

    explicit_path = tmp_path / "reconcile-h008.score.json"
    explicit_path.write_text(json.dumps({"id": "explicit-id"}), encoding="utf-8")
    explicit_payload = _load_protected_reconcile_candidate_scores(
        str(explicit_path)
    )[0]

    assert explicit_payload["id"] == "explicit-id"
    assert "candidate_id" not in explicit_payload


def test_cli_help_mentions_frontiers_and_source_function_aliasing() -> None:
    result = runner.invoke(
        app,
        ["debug", "suggest", "protected-expression-reconcile", "--help"],
        env={"COLUMNS": "200"},
    )

    assert result.exit_code == 0, result.output
    assert "--expression-source" in result.output
    assert "--expression-score-json" in result.output
    assert "--structural-source" in result.output
    assert "--source-function" in result.output
    assert "--source-hunks-json" in result.output


def test_cli_protected_reconcile_loads_source_hunks_json(
    tmp_path: Path,
) -> None:
    expression_source = tmp_path / "expression.c"
    expression_score = tmp_path / "expression.json"
    structural_source = tmp_path / "structural.c"
    structural_score = tmp_path / "structural.json"
    source_hunks = tmp_path / "continuation.json"
    expression_source.write_text(_row_delta_expression_source(), encoding="utf-8")
    structural_source.write_text(_row_delta_structural_source(), encoding="utf-8")
    expression_score.write_text(
        json.dumps(
            _score_payload(
                _expression_score(
                    _anchor(37, "row_offset_adj", expected=26, actual=26),
                ),
                normalized=30,
                accepted=False,
            )
        ),
        encoding="utf-8",
    )
    structural_score.write_text(
        json.dumps(
            _score_payload(
                _expression_score(
                    _anchor(
                        37,
                        "row_offset_adj",
                        expected=26,
                        actual=None,
                        matched=False,
                        status="missing-expression",
                    ),
                ),
                normalized=0,
                accepted=False,
            )
        ),
        encoding="utf-8",
    )
    source_hunks.write_text(
        json.dumps({"continuation": {"source_hunks": _row_delta_source_hunks()}}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "protected-expression-reconcile",
            "--expression-source",
            str(expression_source),
            "--expression-score-json",
            str(expression_score),
            "--structural-source",
            str(structural_source),
            "--structural-score-json",
            str(structural_score),
            "--source-hunks-json",
            str(source_hunks),
            "--function",
            "mnDiagram_DrawCellNumber",
            "--source-function",
            "mnDiagram_80241E78",
            "--max-subhunks",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["generated_count"] > 0
    assert payload["candidates"][0]["provenance"]["manual_subhunk"] is True
    assert payload["candidates"][0]["applied_hunks"][0]["parent_hunk_id"] == (
        "draw-row-delta-parent"
    )


def test_cli_generation_writes_probe_files_and_score_hints(
    tmp_path: Path,
) -> None:
    expression_source = tmp_path / "expression.c"
    expression_score = tmp_path / "expression.json"
    structural_source = tmp_path / "structural.c"
    structural_score = tmp_path / "structural.json"
    out_dir = tmp_path / "probes"
    expression_source.write_text(_expression_source(), encoding="utf-8")
    structural_source.write_text(_structural_source(), encoding="utf-8")
    expression_score.write_text(json.dumps(_six_hit_score(normalized=30)))
    structural_score.write_text(json.dumps(_four_hit_score(normalized=20)))

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "protected-expression-reconcile",
            "--expression-source",
            str(expression_source),
            "--expression-score-json",
            str(expression_score),
            "--structural-source",
            str(structural_source),
            "--structural-score-json",
            str(structural_score),
            "--function",
            "mnDiagram_DrawCellNumber",
            "--source-function",
            "mnDiagram_80241E78",
            "--cflags-from",
            "src/melee/mn/mndiagram.c",
            "--write-probes",
            str(out_dir),
            "--max-candidates",
            "2",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    candidates = payload["candidates"]
    assert candidates
    first = candidates[0]
    assert Path(first["path"]).is_file()
    assert "mnDiagram_80241E78" in Path(first["path"]).read_text()
    command = first["score_source"]["command"]
    assert "-f mnDiagram_80241E78" in command
    assert "--cflags-from src/melee/mn/mndiagram.c" in command
    assert "--target '<target.json>'" in command or "--target <target.json>" in command
    assert "--expression-reg-class fpr" in command
