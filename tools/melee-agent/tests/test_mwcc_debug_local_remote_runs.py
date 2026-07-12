from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from src.mwcc_debug import local_remote_runs as lrr


def _untracked_git(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, 0, "", "")


def _metadata(function_dir: Path, function: str, job_id: str) -> dict[str, object]:
    return {
        "job_id": job_id,
        "function": function,
        "target": "coder64",
        "ssh": "coder.example",
        "remote_perm_dir": (
            f"/home/coder/decomp-permuter/remote-runs/{job_id}/"
            f"nonmatchings/{function}"
        ),
        "remote_run_dir": f"/home/coder/decomp-permuter/remote-runs/{job_id}",
        "local_perm_dir": str(function_dir),
        "tmux_session": f"melee-perm-{job_id}",
        "threads": 16,
        "mode": "stock",
        "created_at": "2026-07-01T12:00:00",
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _make_run(
    perm_root: Path,
    function: str = "fn_80000000",
    job_id: str = "fn_80000000-coder64-20260701-120000",
) -> Path:
    function_dir = perm_root / "nonmatchings" / function
    run = function_dir / "remote-runs" / job_id
    _write_json(
        run / "remote-run" / "metadata.json",
        _metadata(function_dir, function, job_id),
    )
    _write_json(
        run / "candidate_audit.json",
        {
            "root": str(run),
            "function": function,
            "total": 0,
            "by_status": {},
            "candidates": [],
        },
    )
    return run


def _add_candidate(
    run: Path,
    *,
    name: str = "output-1-1",
    sidecar: dict[str, object] | None = None,
) -> Path:
    source = run / name / "source.c"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("void candidate(void) {}\n")
    audit = json.loads((run / "candidate_audit.json").read_text())
    audit["total"] = int(audit["total"]) + 1
    audit["candidates"].append({
        "path": str(source),
        "status": "ok",
        "semantic_risk_bucket": "plausible-C-shape",
        "first_diag": None,
        "source_risks": [],
    })
    _write_json(run / "candidate_audit.json", audit)
    if sidecar is not None:
        _write_json(source.parent / "melee-agent-candidate-status.json", sidecar)
    return source


def _triage_status(**extra: object) -> dict[str, object]:
    return {
        "status": "ok",
        "source": "triage",
        "match_pct": None,
        "delta": None,
        **extra,
    }


def _inventory(perm_root: Path, **kwargs: object) -> lrr.LocalRemoteRunInventory:
    return lrr.inventory_local_remote_runs(
        perm_root,
        git_runner=kwargs.pop("git_runner", _untracked_git),
        **kwargs,
    )


def _summary(perm_root: Path, **kwargs: object) -> lrr.LocalRemoteRunSummary:
    inventory = _inventory(perm_root, **kwargs)
    assert len(inventory.runs) == 1
    return inventory.runs[0]


def _fetch_manifest(summary: lrr.LocalRemoteRunSummary, *, state: str = "complete") -> dict[str, object]:
    return {
        "kind": lrr.FETCH_MANIFEST_KIND,
        "version": lrr.FETCH_MANIFEST_VERSION,
        "job_id": summary.job_id,
        "function": summary.function,
        "target": summary.identity.target,
        "ssh": summary.identity.ssh,
        "remote_perm_dir": summary.identity.remote_perm_dir,
        "remote_run_dir": summary.identity.remote_run_dir,
        "local_perm_dir": summary.identity.local_perm_dir,
        "tmux_session": summary.identity.tmux_session,
        "threads": summary.identity.threads,
        "mode": summary.identity.mode,
        "created_at": summary.identity.created_at,
        "fetched_at": "2026-07-02T12:00:00Z",
        "state": state,
        "candidate_audit": {"total": summary.candidate_count},
    }


def test_inventory_discovers_only_direct_owned_runs_in_deterministic_order(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    second = _make_run(
        perm_root,
        function="fn_80000010",
        job_id="job-z",
    )
    first = _make_run(
        perm_root,
        function="fn_80000000",
        job_id="job-a",
    )
    _make_run(first, function="fn_nested", job_id="not-owned")
    outside = tmp_path / "outside"
    _make_run(outside, function="fn_external", job_id="external")
    (perm_root / "nonmatchings" / "fn_link").symlink_to(
        outside / "nonmatchings" / "fn_external",
        target_is_directory=True,
    )

    inventory = _inventory(perm_root)

    assert [(run.function, run.job_id) for run in inventory.runs] == [
        ("fn_80000000", "job-a"),
        ("fn_80000010", "job-z"),
    ]
    assert {run.path for run in inventory.runs} == {first, second}
    assert any(issue.code == "owner-symlink" for issue in inventory.issues)


def test_legacy_metadata_is_strict_and_manifest_absence_is_allowed(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)

    clean = _summary(perm_root)
    assert clean.metadata_valid
    assert clean.fetch_manifest_status == "absent"
    assert clean.legacy_fetch
    assert clean.candidate_audit_valid
    assert clean.fully_triaged
    assert clean.local_reasons == ()
    assert clean.remote_state == "unprobed"
    assert clean.protected
    assert clean.with_remote_state("stopped").protected is False

    metadata = json.loads((run / "remote-run" / "metadata.json").read_text())
    metadata["job_id"] = "different-job"
    _write_json(run / "remote-run" / "metadata.json", metadata)

    invalid = _summary(perm_root)
    assert not invalid.metadata_valid
    assert "metadata-invalid" in invalid.local_reasons


def test_fetch_manifest_version_identity_and_partial_state_fail_closed(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    legacy = _summary(perm_root)
    manifest_path = run / lrr.FETCH_MANIFEST_FILENAME

    _write_json(manifest_path, _fetch_manifest(legacy))
    complete = _summary(perm_root)
    assert complete.fetch_manifest_status == "complete"
    assert not complete.legacy_fetch
    assert "fetch-manifest-invalid" not in complete.local_reasons

    partial_payload = _fetch_manifest(complete, state="partial")
    _write_json(manifest_path, partial_payload)
    partial = _summary(perm_root)
    assert partial.fetch_manifest_status == "partial"
    assert "fetch-partial" in partial.local_reasons

    partial_payload["version"] = lrr.FETCH_MANIFEST_VERSION + 1
    _write_json(manifest_path, partial_payload)
    invalid_version = _summary(perm_root)
    assert invalid_version.fetch_manifest_status == "invalid"
    assert "fetch-manifest-invalid" in invalid_version.local_reasons

    bad_identity = _fetch_manifest(legacy)
    bad_identity["job_id"] = "other"
    _write_json(manifest_path, bad_identity)
    assert _summary(perm_root).fetch_manifest_status == "invalid"


def test_regular_file_bytes_activity_and_filesystem_identity_are_stable(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    (run / "a.bin").write_bytes(b"abc")
    (run / "nested").mkdir()
    (run / "nested" / "b.bin").write_bytes(b"12345")
    for path in [item for item in run.rglob("*") if item.is_file()]:
        os.utime(path, (100.0, 100.0))
    os.utime(run / "nested" / "b.bin", (200.0, 200.0))
    expected_bytes = sum(
        path.stat().st_size
        for path in run.rglob("*")
        if path.is_file() and not path.is_symlink()
    )

    summary = _summary(perm_root)
    stat_result = run.lstat()

    assert summary.total_bytes == expected_bytes
    assert summary.latest_activity == 200.0
    assert summary.device == stat_result.st_dev
    assert summary.inode == stat_result.st_ino


def test_nested_symlink_nonregular_and_path_escape_are_protected(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (run / "escape").symlink_to(outside)
    os.mkfifo(run / "pipe")

    summary = _summary(perm_root)

    assert summary.flags.nested_symlink
    assert summary.flags.nonregular_entry
    assert summary.flags.path_escape
    assert "nested-symlink" in summary.local_reasons
    assert "nonregular-entry" in summary.local_reasons
    assert "path-escape" in summary.local_reasons
    assert outside.stat().st_size not in {summary.total_bytes}


def test_tracked_files_and_git_failures_are_distinct_protections(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    _make_run(perm_root)

    tracked_path = (
        "nonmatchings/fn_80000000/remote-runs/"
        "fn_80000000-coder64-20260701-120000/tracked.txt"
    )

    def tracked(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, tracked_path + "\0", "")

    def failed(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 128, "", "not a repository")

    tracked_summary = _summary(perm_root, git_runner=tracked)
    failed_summary = _summary(perm_root, git_runner=failed)

    assert tracked_summary.flags.tracked_files
    assert "tracked-files" in tracked_summary.local_reasons
    assert failed_summary.flags.git_check_failed
    assert "git-check-failed" in failed_summary.local_reasons


def test_git_tracked_file_inventory_is_batched_once(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    _make_run(perm_root, function="fn_a", job_id="job-1")
    _make_run(perm_root, function="fn_b", job_id="job-2")
    calls: list[list[str]] = []

    def git_runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    inventory = _inventory(perm_root, git_runner=git_runner)

    assert len(inventory.runs) == 2
    assert calls == [["git", "ls-files", "-z", "--"]]


def test_candidate_audit_must_exactly_account_for_regular_output_sources(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    source = run / "output-1-1" / "source.c"
    source.parent.mkdir()
    source.write_text("void candidate(void) {}\n")

    missing = _summary(perm_root)
    assert not missing.candidate_audit_valid
    assert "candidate-audit-invalid" in missing.local_reasons

    _write_json(
        run / "candidate_audit.json",
        {
            "root": str(run),
            "function": "fn_80000000",
            "total": 1,
            "candidates": [{"path": str(run / "output-other" / "source.c")}],
        },
    )
    wrong = _summary(perm_root)
    assert not wrong.candidate_audit_valid


def test_full_triage_requires_every_sidecar_but_zero_candidate_audit_is_valid(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    assert _summary(perm_root).fully_triaged

    source = _add_candidate(run)
    missing = _summary(perm_root)
    assert not missing.fully_triaged
    assert "candidate-untriaged" in missing.local_reasons

    _write_json(
        source.parent / "melee-agent-candidate-status.json",
        {"status": "ok", "source": "fetch", "delta": None, "match_pct": None},
    )
    fetch_only = _summary(perm_root)
    assert not fetch_only.fully_triaged

    _write_json(source.parent / "melee-agent-candidate-status.json", _triage_status())
    triaged = _summary(perm_root)
    assert triaged.fully_triaged
    assert "candidate-untriaged" not in triaged.local_reasons


@pytest.mark.parametrize(
    "winner_field,winner_value",
    [
        ("kept", True),
        ("delta", 0.01),
        ("match_pct", 100),
    ],
)
def test_winner_status_protects_entire_run(
    tmp_path: Path,
    winner_field: str,
    winner_value: object,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    _add_candidate(run, sidecar=_triage_status(**{winner_field: winner_value}))

    summary = _summary(perm_root)

    assert summary.fully_triaged
    assert summary.winner
    assert "winner" in summary.local_reasons


@pytest.mark.parametrize(
    "field,value",
    [
        ("kept", 1),
        ("delta", True),
        ("delta", "1.0"),
        ("match_pct", False),
        ("match_pct", "100"),
    ],
)
def test_invalid_winner_field_types_fail_closed(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    _add_candidate(run, sidecar=_triage_status(**{field: value}))

    summary = _summary(perm_root)

    assert not summary.fully_triaged
    assert not summary.winner
    assert "candidate-status-invalid" in summary.local_reasons


def test_valid_retention_marker_and_invalid_marker_are_distinct(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    base = _summary(perm_root)
    marker = {
        "kind": lrr.RETENTION_MARKER_KIND,
        "version": lrr.RETENTION_MARKER_VERSION,
        "job_id": base.job_id,
        "function": base.function,
        "reason": "keep investigation evidence",
        "created_at": "2026-07-02T12:00:00Z",
    }
    _write_json(run / lrr.RETENTION_MARKER_FILENAME, marker)

    retained = _summary(perm_root)
    assert retained.retention_marker_status == "valid"
    assert "explicitly-retained" in retained.local_reasons

    marker["reason"] = ""
    _write_json(run / lrr.RETENTION_MARKER_FILENAME, marker)
    invalid = _summary(perm_root)
    assert invalid.retention_marker_status == "invalid"
    assert "retention-marker-invalid" in invalid.local_reasons
    assert "explicitly-retained" not in invalid.local_reasons


def test_fetch_warning_and_malformed_inputs_protect_legacy_runs(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    _write_json(
        run / "remote-fetch-warning.json",
        {"status": "partial", "job_id": run.name},
    )
    warned = _summary(perm_root)
    assert "fetch-warning" in warned.local_reasons
    assert "fetch-partial" in warned.local_reasons

    (run / "remote-fetch-warning.json").write_text("not-json")
    malformed_warning = _summary(perm_root)
    assert "fetch-warning-invalid" in malformed_warning.local_reasons

    (run / "candidate_audit.json").write_text("not-json")
    malformed_audit = _summary(perm_root)
    assert "candidate-audit-invalid" in malformed_audit.local_reasons


def test_inventory_summary_order_and_remote_state_hook_are_deterministic(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    _make_run(perm_root, function="fn_b", job_id="job-2")
    _make_run(perm_root, function="fn_a", job_id="job-3")
    _make_run(perm_root, function="fn_a", job_id="job-1")

    first = _inventory(perm_root)
    second = _inventory(perm_root)

    assert first.runs == second.runs
    assert [(run.function, run.job_id) for run in first.runs] == [
        ("fn_a", "job-1"),
        ("fn_a", "job-3"),
        ("fn_b", "job-2"),
    ]
    stopped = first.runs[0].with_remote_state("stopped")
    unknown = stopped.with_remote_state("unknown", "ssh timeout")
    assert stopped.remote_state == "stopped"
    assert "remote-unknown" not in stopped.reasons
    assert unknown.remote_detail == "ssh timeout"
    assert "remote-unknown" in unknown.reasons
