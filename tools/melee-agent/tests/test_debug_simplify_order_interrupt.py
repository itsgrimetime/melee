from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.cli import debug as debug_mod
from src.mwcc_debug.simplify_search import PrecolorDistance


def _scored_candidate(*, provenance: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        variant=SimpleNamespace(provenance=provenance, text=text),
        score=SimpleNamespace(
            target_prefix=(34, 44),
            observed_prefix=(44, 34),
            common_prefix_length=0,
            baseline_common_prefix_length=0,
            assignment_distance_total=None,
            baseline_assignment_distance_total=None,
            assignment_improved_count=0,
        ),
        signature=None,
        precolor_distance=PrecolorDistance(
            ig_added=0,
            ig_removed=0,
            coalesce_added=0,
            coalesce_removed=0,
            spill_added=0,
            spill_removed=0,
        ),
    )


def test_simplify_retained_probe_interrupt_preserves_partial_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    result = SimpleNamespace(
        scored_candidates=[
            _scored_candidate(
                provenance="first-probe",
                text="void fn_test(void) {\n}\n",
            ),
            _scored_candidate(
                provenance="second-probe",
                text="void fn_test(void) {\n    int x;\n}\n",
            ),
        ],
    )
    calls: list[str] = []

    def fake_score_source_candidate_real_tree(path, **kwargs):
        calls.append(path.name)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return SimpleNamespace(
            structural_guard={"accepted": True},
            structural_guard_error=None,
            match_percent_error=None,
        )

    monkeypatch.setattr(
        debug_mod,
        "_score_source_candidate_real_tree",
        fake_score_source_candidate_real_tree,
    )

    with pytest.raises(debug_mod._SimplifyRetainInterrupted) as excinfo:
        debug_mod._simplify_retained_probe_records(
            result=result,
            function="fn_test",
            force_phys_target={},
            retain_probes=tmp_path / "probes",
            melee_root=tmp_path,
            retain_count=2,
            checkdiff_guard=True,
            timeout=1,
        )

    assert excinfo.value.abort_reason == "keyboard-interrupt"
    assert excinfo.value.last_candidate == "second-probe"
    assert len(excinfo.value.records) == 1
    assert excinfo.value.records[0]["provenance"] == "first-probe"
    assert excinfo.value.records[0]["source_retained"]
