"""Tests for live probe selection and feature discovery (Task 9)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))


def test_live_probe_selection_import():
    """LiveProbeSelection and discovery functions must be importable."""
    from tools.mwcc_retro.backend_live_probe_selection import (  # noqa: F401
        LiveProbeCandidate,
        LiveProbeSelection,
        discover_live_probe_candidates,
        select_live_probe_set,
        summarize_live_probe_features,
        validate_live_probe_selection,
        validate_live_probe_union,
    )


def test_discover_live_probe_candidates_includes_mndiagram(tmp_path):
    """Discovery must include mnDiagram_DrawFighterHeaders as complex-control."""
    from tools.mwcc_retro.backend_live_probe_selection import (
        discover_live_probe_candidates,
    )

    candidates = discover_live_probe_candidates(tmp_path)
    assert len(candidates) >= 1
    assert candidates[0].function == "mnDiagram_DrawFighterHeaders"
    assert candidates[0].category == "complex-control"


def test_select_live_probe_set_binds_candidate_table_digest(tmp_path):
    """Selection must bind the candidate table SHA-256."""
    from tools.mwcc_retro.backend_live_probe_selection import (
        select_live_probe_set,
    )

    table = tmp_path / "gc_125n.candidate.json"
    table.write_text('{"test": true}\n')

    selection = select_live_probe_set((), table)
    assert len(selection.candidate_table_sha256) == 64
    assert selection.candidates[0].category == "complex-control"


def test_validate_live_probe_union_rejects_empty_manifest(tmp_path):
    """Union validator must reject a manifest with no sites."""
    from tools.mwcc_retro.backend_live_probe_selection import (
        LiveProbeSelection,
        validate_live_probe_union,
    )

    selection = LiveProbeSelection(
        candidates=(),
        candidate_table_sha256="0" * 64,
        feature_summary_sha256s=(),
    )
    errors = validate_live_probe_union(
        selection, tmp_path, {"sites": []}, tmp_path / "table.json"
    )
    assert "manifest has no sites" in errors
