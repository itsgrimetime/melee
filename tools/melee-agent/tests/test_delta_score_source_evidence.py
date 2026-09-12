from __future__ import annotations

from types import SimpleNamespace

from src.cli.debug.target import _apply_score_source_checkdiff_guard
from src.mwcc_debug.source_candidate_scoring import source_row_to_candidate_score


def test_score_source_json_includes_full_checkdiff_evidence(tmp_path) -> None:
    payload: dict[str, object] = {}
    checkdiff = {
        "function": "f",
        "match": False,
        "target_asm": ["+000: 38 60 00 00 li r3,0"],
        "current_asm": ["+000: 38 80 00 00 li r4,0"],
    }

    _apply_score_source_checkdiff_guard(
        payload,
        c_file=str(tmp_path / "candidate.c"),
        source_rel="candidate.c",
        melee_root=tmp_path,
        function="f",
        timeout=1.0,
        deadline=None,
        full_unit_source=True,
        score_real_tree=lambda *_args, **_kwargs: SimpleNamespace(
            match_percent=99.0,
            match_percent_error=None,
            structural_guard={"accepted": False},
            structural_guard_error=None,
            checkdiff_payload=checkdiff,
        ),
    )

    assert payload["checkdiff_evidence"] == checkdiff
    assert payload["checkdiff_evidence"]["target_asm"][0].endswith("li r3,0")


def test_candidate_score_preserves_checkdiff_evidence() -> None:
    checkdiff = {"function": "f", "match": True, "target_asm": [], "current_asm": []}

    score = source_row_to_candidate_score(
        {
            "candidate_id": "candidate",
            "checkdiff_evidence": checkdiff,
            "pcdump_path": "/tmp/candidate.pcdump",
        }
    )

    assert score.checkdiff_evidence == checkdiff
