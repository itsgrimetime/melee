"""Smoke test for run_directed dry path (Task 12).

No mwcc compilation occurs — the dry=True flag substitutes in-memory fakes
so this test is fast, deterministic, and safe for CI.
"""
from __future__ import annotations

import pytest


def test_run_directed_dry(tmp_path):
    """run_directed(dry=True) returns the required top-level keys and a valid
    gate reason token without any mwcc invocation."""
    from src.search.directed.run import run_directed

    res = run_directed(
        function="grIceMt_801F9ACC",
        unit="melee/gr/gricemt",
        melee_root=tmp_path,
        store_dir=tmp_path / "store",
        dry=True,
    )

    # Top-level shape
    assert "gate" in res, f"missing 'gate' key: {res}"
    assert "directed_telemetry" in res, f"missing 'directed_telemetry' key: {res}"
    assert "accounting" in res, f"missing 'accounting' key: {res}"

    # Gate sub-keys
    gate = res["gate"]
    assert "passed" in gate, f"gate missing 'passed': {gate}"
    assert "reason" in gate, f"gate missing 'reason': {gate}"
    assert "evidence" in gate, f"gate missing 'evidence': {gate}"

    # Reason must be a known token
    valid_reasons = {
        "attributable_progress",
        "no_smooth_gradient",
        "void_no_treatment",
        "unattributed_or_regressing",
        "not_preflight",
    }
    assert gate["reason"] in valid_reasons, (
        f"unexpected gate reason: {gate['reason']!r}; expected one of {valid_reasons}"
    )

    # passed must be a bool
    assert isinstance(gate["passed"], bool), f"gate['passed'] must be bool: {gate}"


def test_run_directed_dry_returns_telemetry(tmp_path):
    """Dry run should produce at least one directed_telemetry entry."""
    from src.search.directed.run import run_directed

    res = run_directed(
        function="grIceMt_801F9ACC",
        unit="melee/gr/gricemt",
        melee_root=tmp_path,
        store_dir=tmp_path / "store",
        dry=True,
    )

    telemetry = res["directed_telemetry"]
    assert isinstance(telemetry, list), "directed_telemetry must be a list"
    # Dry mode vends 2 batches → at least 1 entry
    assert len(telemetry) >= 1, (
        f"expected at least 1 telemetry entry in dry mode, got {len(telemetry)}"
    )

    # Each entry must have the DirectedMeta fields
    for entry in telemetry:
        assert "valid" in entry, f"telemetry entry missing 'valid': {entry}"
        assert "displacement" in entry, f"telemetry entry missing 'displacement': {entry}"
        assert "case" in entry, f"telemetry entry missing 'case': {entry}"


def test_run_directed_dry_accounting(tmp_path):
    """Dry run accounting dict must be present and non-empty."""
    from src.search.directed.run import run_directed

    res = run_directed(
        function="grIceMt_801F9ACC",
        unit="melee/gr/gricemt",
        melee_root=tmp_path,
        store_dir=tmp_path / "store",
        dry=True,
    )

    accounting = res["accounting"]
    assert isinstance(accounting, dict), "accounting must be a dict"
    assert "compiled" in accounting, f"accounting missing 'compiled': {accounting}"
