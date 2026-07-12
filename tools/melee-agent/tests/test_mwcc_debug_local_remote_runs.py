from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
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
        "remote_perm_dir": (f"/home/coder/decomp-permuter/remote-runs/{job_id}/nonmatchings/{function}"),
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
    audit["candidates"].append(
        {
            "path": str(source),
            "status": "ok",
            "semantic_risk_bucket": "plausible-C-shape",
            "first_diag": None,
            "source_risks": [],
        }
    )
    _write_json(run / "candidate_audit.json", audit)
    if sidecar is not None:
        bound_sidecar = dict(sidecar)
        bound_sidecar.setdefault("candidate", str(source))
        bound_sidecar.setdefault("function", audit["function"])
        _write_json(
            source.parent / "melee-agent-candidate-status.json",
            bound_sidecar,
        )
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


def _set_remote_identity(run: Path, *, ssh: str, session: str) -> None:
    metadata_path = run / "remote-run" / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["ssh"] = ssh
    metadata["tmux_session"] = session
    _write_json(metadata_path, metadata)


def _tmux_result(
    argv: list[str],
    *sessions: str,
    returncode: int = 0,
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    stdout = "\n".join([lrr.REMOTE_SESSION_HEADER, *sessions, lrr.REMOTE_SESSION_TRAILER]) + "\n"
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def _replace_inventory_runs(
    inventory: lrr.LocalRemoteRunInventory,
    **updates: dict[str, object],
) -> lrr.LocalRemoteRunInventory:
    runs = tuple(replace(run, **updates.get(run.job_id, {})) for run in inventory.runs)
    return replace(inventory, runs=runs)


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


def test_nonmatchings_owner_symlink_is_not_traversed(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    perm_root.mkdir()
    outside = tmp_path / "outside"
    _make_run(outside, function="fn_external", job_id="external-job")
    (perm_root / "nonmatchings").symlink_to(
        outside / "nonmatchings",
        target_is_directory=True,
    )

    inventory = _inventory(perm_root)

    assert inventory.runs == ()
    assert inventory.issues == (lrr.InventoryIssue(perm_root / "nonmatchings", "owner-symlink"),)


def test_nonmatchings_owner_non_directory_is_rejected(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    perm_root.mkdir()
    (perm_root / "nonmatchings").write_text("not a directory")

    inventory = _inventory(perm_root)

    assert inventory.runs == ()
    assert inventory.issues == (lrr.InventoryIssue(perm_root / "nonmatchings", "owner-not-directory"),)


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


@pytest.mark.parametrize(
    "field,value",
    [
        ("local_perm_dir", "nonmatchings/fn_80000000"),
        (
            "remote_run_dir",
            "remote-runs/fn_80000000-coder64-20260701-120000",
        ),
        (
            "remote_perm_dir",
            "remote-runs/fn_80000000-coder64-20260701-120000/nonmatchings/fn_80000000",
        ),
    ],
)
def test_metadata_paths_must_be_absolute(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    metadata_path = run / "remote-run" / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata[field] = value
    _write_json(metadata_path, metadata)

    summary = _summary(perm_root)

    assert not summary.metadata_valid
    assert "metadata-invalid" in summary.local_reasons


def test_metadata_remote_paths_must_share_the_same_job_root(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    metadata_path = run / "remote-run" / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["remote_perm_dir"] = metadata["remote_perm_dir"].replace(
        "/home/coder/",
        "/srv/other/",
    )
    _write_json(metadata_path, metadata)

    summary = _summary(perm_root)

    assert not summary.metadata_valid
    assert "metadata-invalid" in summary.local_reasons


@pytest.mark.parametrize(
    "forged_ssh",
    [
        "-oProxyCommand=touch /tmp/pwned",
        "host other",
        "host\n-oBatchMode=no",
        "host\x00suffix",
        "host\tother",
    ],
)
def test_metadata_rejects_ssh_option_and_token_injection(
    tmp_path: Path,
    forged_ssh: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    metadata_path = run / "remote-run" / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["ssh"] = forged_ssh
    _write_json(metadata_path, metadata)

    summary = _summary(perm_root)

    assert not summary.metadata_valid
    assert "metadata-invalid" in summary.local_reasons


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
    expected_bytes = sum(path.stat().st_size for path in run.rglob("*") if path.is_file() and not path.is_symlink())

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

    tracked_path = "nonmatchings/fn_80000000/remote-runs/fn_80000000-coder64-20260701-120000/tracked.txt"

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

    _write_json(
        source.parent / "melee-agent-candidate-status.json",
        _triage_status(candidate=str(source), function="fn_80000000"),
    )
    triaged = _summary(perm_root)
    assert triaged.fully_triaged
    assert "candidate-untriaged" not in triaged.local_reasons


@pytest.mark.parametrize(
    "candidate_value,function_value",
    [
        (None, "fn_80000000"),
        ("relative/output-1-1/source.c", "fn_80000000"),
        ("{outside}", "fn_80000000"),
        ("{source}", None),
        ("{source}", "fn_other"),
    ],
)
def test_triage_sidecar_must_bind_exact_candidate_and_function(
    tmp_path: Path,
    candidate_value: str | None,
    function_value: str | None,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    source = _add_candidate(run)
    outside = tmp_path / "outside.c"
    outside.write_text("void outside(void) {}\n")
    payload = _triage_status()
    if candidate_value is not None:
        payload["candidate"] = candidate_value.format(
            source=source,
            outside=outside,
        )
    if function_value is not None:
        payload["function"] = function_value
    _write_json(source.parent / "melee-agent-candidate-status.json", payload)

    summary = _summary(perm_root)

    assert not summary.fully_triaged
    assert summary.flags.candidate_status_invalid
    assert "candidate-status-invalid" in summary.local_reasons


def test_writer_shaped_triage_sidecar_with_exact_identity_is_valid(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    source = _add_candidate(run)
    _write_json(
        source.parent / "melee-agent-candidate-status.json",
        _triage_status(candidate=str(source), function="fn_80000000"),
    )

    summary = _summary(perm_root)

    assert summary.fully_triaged
    assert not summary.flags.candidate_status_invalid


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


def test_remote_activity_probe_batches_once_per_host_and_matches_exact_sessions(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run_a = _make_run(perm_root, function="fn_a", job_id="job-a")
    run_b = _make_run(perm_root, function="fn_b", job_id="job-b")
    run_c = _make_run(perm_root, function="fn_c", job_id="job-c")
    _set_remote_identity(run_a, ssh="host-one", session="session-a")
    _set_remote_identity(run_b, ssh="host-one", session="session-b")
    _set_remote_identity(run_c, ssh="host-two", session="session-c")
    inventory = _inventory(perm_root)
    calls: list[tuple[str, float]] = []

    def runner(
        argv: list[str],
        *,
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv[2], timeout))
        sessions = ("session-a", "session-b-extra") if argv[2] == "host-one" else ()
        return _tmux_result(argv, *sessions)

    probed = lrr.probe_remote_run_activity(
        inventory,
        runner=runner,
        timeout=3.5,
        max_workers=2,
    )

    assert sorted(calls) == [("host-one", 3.5), ("host-two", 3.5)]
    assert {run.job_id: run.remote_state for run in probed.runs} == {
        "job-a": "active",
        "job-b": "stopped",
        "job-c": "stopped",
    }


def test_remote_activity_probe_accepts_explicit_empty_tmux_inventory(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    _set_remote_identity(run, ssh="empty-host", session="session-a")
    inventory = _inventory(perm_root)

    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert argv[:3] == ["ssh", "--", "empty-host"]
        assert "no server running|no sessions" in argv[3]
        assert lrr.REMOTE_TMUX_MISSING_SENTINEL in argv[3]
        return _tmux_result(argv)

    probed = lrr.probe_remote_run_activity(
        inventory,
        runner=runner,
    )

    assert probed.runs[0].remote_state == "stopped"


@pytest.mark.parametrize(
    "failure",
    ["nonzero", "timeout", "exception", "malformed", "masked"],
)
def test_remote_activity_probe_failures_are_unknown_for_entire_host(
    tmp_path: Path,
    failure: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    first = _make_run(perm_root, function="fn_a", job_id="job-a")
    second = _make_run(perm_root, function="fn_b", job_id="job-b")
    _set_remote_identity(first, ssh="bad-host", session="session-a")
    _set_remote_identity(second, ssh="bad-host", session="session-b")
    inventory = _inventory(perm_root)

    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if failure == "nonzero":
            return subprocess.CompletedProcess(argv, 255, "", "ssh failed\n" * 200)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 1.0)
        if failure == "exception":
            raise RuntimeError("runner exploded")
        if failure == "masked":
            result = _tmux_result(argv)
            return subprocess.CompletedProcess(
                argv,
                0,
                result.stdout,
                "ssh transport warning/failure",
            )
        return subprocess.CompletedProcess(argv, 0, "unexpected output\n", "")

    probed = lrr.probe_remote_run_activity(inventory, runner=runner, timeout=1.0)

    assert {run.remote_state for run in probed.runs} == {"unknown"}
    assert all(run.remote_detail for run in probed.runs)
    assert all(len(run.remote_detail) <= lrr.REMOTE_DETAIL_LIMIT for run in probed.runs)


def test_remote_activity_probe_missing_tmux_is_unknown_not_stopped(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    _set_remote_identity(run, ssh="host", session="session")
    inventory = _inventory(perm_root)

    probed = lrr.probe_remote_run_activity(
        inventory,
        runner=lambda argv, **_: subprocess.CompletedProcess(
            argv,
            127,
            "",
            lrr.REMOTE_TMUX_MISSING_SENTINEL,
        ),
    )

    assert probed.runs[0].remote_state == "unknown"
    assert "tmux" in probed.runs[0].remote_detail.lower()


def test_remote_activity_probe_missing_identity_skips_runner_and_stays_unknown(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    (run / "remote-run" / "metadata.json").write_text("not-json")
    inventory = _inventory(perm_root)

    def runner(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("missing identity must not be probed")

    probed = lrr.probe_remote_run_activity(inventory, runner=runner)

    assert probed.runs[0].remote_state == "unknown"
    assert "identity" in probed.runs[0].remote_detail


def test_remote_activity_probe_defensively_rejects_forged_identity_ssh(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    _make_run(perm_root)
    inventory = _inventory(perm_root)
    summary = inventory.runs[0]
    assert summary.identity is not None
    forged = replace(
        summary,
        identity=replace(summary.identity, ssh="-F/tmp/attacker-config"),
    )
    inventory = replace(inventory, runs=(forged,))
    called = False

    def runner(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0, "", "")

    probed = lrr.probe_remote_run_activity(inventory, runner=runner)

    assert probed.runs[0].remote_state == "unknown"
    assert "ssh" in probed.runs[0].remote_detail.lower()
    assert not called


def test_remote_activity_probe_mixed_hosts_isolates_failure(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    good = _make_run(perm_root, function="fn_a", job_id="good-job")
    bad = _make_run(perm_root, function="fn_b", job_id="bad-job")
    _set_remote_identity(good, ssh="good-host", session="good-session")
    _set_remote_identity(bad, ssh="bad-host", session="bad-session")
    inventory = _inventory(perm_root)

    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if argv[2] == "good-host":
            return _tmux_result(argv, "good-session")
        return subprocess.CompletedProcess(argv, 255, "", "ssh failed")

    probed = lrr.probe_remote_run_activity(inventory, runner=runner)

    assert {run.job_id: run.remote_state for run in probed.runs} == {
        "good-job": "active",
        "bad-job": "unknown",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_age_days": True},
        {"max_age_days": -1},
        {"max_age_days": float("inf")},
        {"max_age_days": "30"},
        {"max_total_bytes": True},
        {"max_total_bytes": -1},
        {"max_total_bytes": 1.5},
    ],
)
def test_retention_plan_rejects_invalid_nonnegative_limits(
    tmp_path: Path,
    kwargs: dict[str, object],
) -> None:
    inventory = _inventory(tmp_path / "missing")

    with pytest.raises(ValueError):
        lrr.plan_local_remote_run_retention(inventory, **kwargs)


@pytest.mark.parametrize(
    "clock",
    [
        lambda: "not a datetime",
        lambda: datetime(2026, 7, 11),
        lambda: (_ for _ in ()).throw(RuntimeError("clock failed")),
    ],
)
def test_retention_plan_rejects_invalid_or_failed_clock(
    tmp_path: Path,
    clock: object,
) -> None:
    inventory = _inventory(tmp_path / "missing")

    with pytest.raises(ValueError):
        lrr.plan_local_remote_run_retention(inventory, clock=clock)


def test_retention_plan_selects_old_runs_before_cutoff(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    _make_run(perm_root, function="fn_a", job_id="old-job")
    _make_run(perm_root, function="fn_b", job_id="new-job")
    inventory = _inventory(perm_root)
    now = datetime(2026, 7, 11, tzinfo=UTC)
    inventory = _replace_inventory_runs(
        inventory,
        **{
            "old-job": {
                "remote_state": "stopped",
                "latest_activity": now.timestamp() - 31 * 86400,
                "total_bytes": 10,
            },
            "new-job": {
                "remote_state": "stopped",
                "latest_activity": now.timestamp() - 29 * 86400,
                "total_bytes": 10,
            },
        },
    )

    plan = lrr.plan_local_remote_run_retention(
        inventory,
        max_age_days=30,
        max_total_bytes=100,
        clock=lambda: now,
    )

    assert [(item.summary.job_id, item.reasons) for item in plan.selected] == [
        ("old-job", ("age",)),
    ]
    assert plan.total_bytes == 20
    assert plan.reclaimed_bytes == 10
    assert plan.projected_total_bytes == 10
    assert plan.cap_satisfied


def test_retention_plan_selects_oldest_remaining_until_global_cap(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    for job_id in ("job-a", "job-b", "job-c"):
        _make_run(perm_root, function=f"fn_{job_id[-1]}", job_id=job_id)
    inventory = _inventory(perm_root)
    now = datetime(2026, 7, 11, tzinfo=UTC)
    updates = {
        run.job_id: {
            "remote_state": "stopped",
            "latest_activity": now.timestamp() - (3 - index) * 3600,
            "total_bytes": 10,
        }
        for index, run in enumerate(inventory.runs)
    }
    inventory = _replace_inventory_runs(inventory, **updates)

    plan = lrr.plan_local_remote_run_retention(
        inventory,
        max_age_days=365,
        max_total_bytes=15,
        clock=lambda: now,
    )

    assert [item.summary.job_id for item in plan.selected] == ["job-a", "job-b"]
    assert all(item.reasons == ("cap",) for item in plan.selected)
    assert plan.projected_total_bytes == 10
    assert plan.cap_satisfied


def test_retention_plan_age_and_cap_selection_deduplicates_runs(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    _make_run(perm_root, function="fn_a", job_id="old-job")
    _make_run(perm_root, function="fn_b", job_id="next-job")
    inventory = _inventory(perm_root)
    now = datetime(2026, 7, 11, tzinfo=UTC)
    inventory = _replace_inventory_runs(
        inventory,
        **{
            "old-job": {
                "remote_state": "stopped",
                "latest_activity": now.timestamp() - 40 * 86400,
                "total_bytes": 10,
            },
            "next-job": {
                "remote_state": "stopped",
                "latest_activity": now.timestamp() - 2 * 86400,
                "total_bytes": 10,
            },
        },
    )

    plan = lrr.plan_local_remote_run_retention(
        inventory,
        max_age_days=30,
        max_total_bytes=5,
        clock=lambda: now,
    )

    assert [(item.summary.job_id, item.reasons) for item in plan.selected] == [
        ("old-job", ("age",)),
        ("next-job", ("cap",)),
    ]
    assert len({item.summary.path for item in plan.selected}) == 2


def test_retention_plan_protected_bytes_can_make_cap_unattainable(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    _make_run(perm_root, function="fn_a", job_id="protected-job")
    _make_run(perm_root, function="fn_b", job_id="eligible-job")
    inventory = _inventory(perm_root)
    now = datetime(2026, 7, 11, tzinfo=UTC)
    inventory = _replace_inventory_runs(
        inventory,
        **{
            "protected-job": {
                "remote_state": "active",
                "total_bytes": 20,
                "latest_activity": now.timestamp() - 100 * 86400,
            },
            "eligible-job": {
                "remote_state": "stopped",
                "total_bytes": 10,
                "latest_activity": now.timestamp() - 100 * 86400,
            },
        },
    )

    plan = lrr.plan_local_remote_run_retention(
        inventory,
        max_age_days=30,
        max_total_bytes=5,
        clock=lambda: now,
    )

    assert plan.protected_bytes == 20
    assert plan.selected_bytes == 10
    assert plan.projected_total_bytes == 20
    assert not plan.cap_satisfied
    protected_item = next(item for item in plan.items if item.summary.job_id == "protected-job")
    assert protected_item.disposition == "protected"
    assert "remote-active" in protected_item.reasons


def test_retention_plan_only_zero_reason_stopped_runs_are_eligible(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    for job_id in ("stopped", "active", "unknown", "local-protected"):
        _make_run(perm_root, function=f"fn_{job_id}", job_id=job_id)
    inventory = _inventory(perm_root)
    updates = {
        "stopped": {"remote_state": "stopped", "local_reasons": ()},
        "active": {"remote_state": "active", "local_reasons": ()},
        "unknown": {"remote_state": "unknown", "local_reasons": ()},
        "local-protected": {
            "remote_state": "stopped",
            "local_reasons": ("explicitly-retained",),
        },
    }
    inventory = _replace_inventory_runs(inventory, **updates)

    plan = lrr.plan_local_remote_run_retention(
        inventory,
        max_age_days=99999,
        max_total_bytes=10**12,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert [item.summary.job_id for item in plan.eligible] == ["stopped"]
    assert {item.summary.job_id for item in plan.protected} == {
        "active",
        "unknown",
        "local-protected",
    }


def test_retention_plan_zero_byte_ties_are_deterministic_and_do_not_fake_cap(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    for job_id in ("job-b", "job-a"):
        _make_run(perm_root, function="fn_same", job_id=job_id)
    _make_run(perm_root, function="fn_protected", job_id="protected")
    inventory = _inventory(perm_root)
    timestamp = datetime(2026, 7, 11, tzinfo=UTC).timestamp()
    inventory = _replace_inventory_runs(
        inventory,
        **{
            "job-a": {
                "remote_state": "stopped",
                "local_reasons": (),
                "total_bytes": 0,
                "latest_activity": timestamp,
            },
            "job-b": {
                "remote_state": "stopped",
                "local_reasons": (),
                "total_bytes": 0,
                "latest_activity": timestamp,
            },
            "protected": {
                "remote_state": "active",
                "local_reasons": (),
                "total_bytes": 10,
                "latest_activity": timestamp,
            },
        },
    )

    first = lrr.plan_local_remote_run_retention(
        inventory,
        max_age_days=1,
        max_total_bytes=5,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )
    second = lrr.plan_local_remote_run_retention(
        inventory,
        max_age_days=1,
        max_total_bytes=5,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert first == second
    assert [item.summary.job_id for item in first.selected] == ["job-a", "job-b"]
    assert first.reclaimed_bytes == 0
    assert first.projected_total_bytes == 10
    assert not first.cap_satisfied


@pytest.mark.parametrize("issue_code", ["owner-symlink", "owner-unreadable"])
def test_retention_plan_incomplete_inventory_never_satisfies_cap(
    tmp_path: Path,
    issue_code: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    _make_run(perm_root)
    inventory = _inventory(perm_root)
    inventory = replace(
        inventory,
        issues=(lrr.InventoryIssue(perm_root / "unknown", issue_code),),
    )

    plan = lrr.plan_local_remote_run_retention(
        inventory,
        max_total_bytes=10**12,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert not plan.inventory_complete
    assert not plan.cap_satisfied


def test_unexpected_direct_remote_run_entry_makes_inventory_incomplete(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    unexpected = run.parent / "unexpected.bin"
    unexpected.write_bytes(b"unknown ownership")

    inventory = _inventory(perm_root)

    assert any(issue.path == unexpected and issue.code == "unexpected-run-entry" for issue in inventory.issues)
    plan = lrr.plan_local_remote_run_retention(
        inventory,
        max_total_bytes=10**12,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )
    assert not plan.inventory_complete
    assert not plan.cap_satisfied


def test_probe_and_plan_are_read_only(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    _set_remote_identity(run, ssh="host", session="session")
    before = {str(path.relative_to(perm_root)): path.read_bytes() for path in perm_root.rglob("*") if path.is_file()}
    inventory = _inventory(perm_root)

    probed = lrr.probe_remote_run_activity(
        inventory,
        runner=lambda argv, **_: _tmux_result(argv),
    )
    lrr.plan_local_remote_run_retention(
        probed,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )
    after = {str(path.relative_to(perm_root)): path.read_bytes() for path in perm_root.rglob("*") if path.is_file()}

    assert after == before


def test_apply_recomputes_inside_lock_and_removes_selected_run(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    calls = 0

    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _tmux_result(argv)

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_age_days=99999,
        max_total_bytes=0,
        remote_runner=runner,
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.status == "completed"
    assert result.plan is not None
    assert result.planned_count == 1
    assert result.removed_count == 1
    assert result.skipped_count == 0
    assert result.planned == result.actions
    assert result.removed == result.actions
    assert result.skipped == ()
    assert result.reclaimed_bytes == result.plan.selected_bytes
    assert result.projected_total_bytes == 0
    assert result.actions[0].original_path == run
    assert result.actions[0].status == "removed"
    assert result.actions[0].reclaimed_bytes == result.plan.selected_bytes
    assert calls == 2
    assert not run.exists()


def test_apply_with_no_selected_runs_does_not_remove_anything(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_age_days=99999,
        max_total_bytes=10**12,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.status == "completed"
    assert result.actions == ()
    assert result.reclaimed_bytes == 0
    assert result.plan is not None
    assert result.projected_total_bytes == result.plan.total_bytes
    assert run.is_dir()


def test_apply_busy_lock_fails_closed_without_probe_or_deletion(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    lock_path = perm_root / lrr.LIFECYCLE_LOCK_FILENAME
    lock_path.touch(mode=0o600)
    descriptor = os.open(lock_path, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    called = False
    try:

        def runner(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
            nonlocal called
            called = True
            return subprocess.CompletedProcess([], 0, "", "")

        result = lrr.apply_local_remote_run_retention(
            perm_root,
            remote_runner=runner,
            git_runner=_untracked_git,
        )
    finally:
        os.close(descriptor)

    assert result.status == "lock-busy"
    assert result.plan is None
    assert result.actions == ()
    assert not called
    assert run.is_dir()


def test_apply_ignores_prior_plan_and_recomputes_new_retention_marker(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    stale = _inventory(perm_root)
    stale = lrr.probe_remote_run_activity(
        stale,
        runner=lambda argv, **_: _tmux_result(argv),
    )
    stale_plan = lrr.plan_local_remote_run_retention(
        stale,
        max_total_bytes=0,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )
    assert len(stale_plan.selected) == 1
    _write_json(
        run / lrr.RETENTION_MARKER_FILENAME,
        {
            "kind": lrr.RETENTION_MARKER_KIND,
            "version": lrr.RETENTION_MARKER_VERSION,
            "job_id": run.name,
            "function": run.parent.parent.name,
            "reason": "new decision",
            "created_at": "2026-07-11T12:00:00Z",
        },
    )

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.actions == ()
    assert result.plan is not None
    assert result.plan.selected == ()
    assert run.is_dir()


@pytest.mark.parametrize("second_state", ["active", "unknown"])
def test_apply_second_probe_remote_change_skips_selected_run(
    tmp_path: Path,
    second_state: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    calls = 0

    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _tmux_result(argv)
        if second_state == "active":
            return _tmux_result(argv, _metadata(run.parent.parent, run.parent.parent.name, run.name)["tmux_session"])
        raise RuntimeError("second probe failed")

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=runner,
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert calls == 2
    assert result.removed_count == 0
    assert result.skipped_count == 1
    assert any(reason.startswith("remote-") for reason in result.actions[0].reasons)
    assert run.is_dir()


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("retained", "explicitly-retained"),
        ("winner", "winner"),
        ("untriaged", "candidate-untriaged"),
        ("tracked", "tracked-files"),
        ("symlink", "nested-symlink"),
        ("nonregular", "nonregular-entry"),
        ("replaced", "run-changed"),
        ("root-symlink", "run-changed"),
        ("root-nonregular", "filesystem-error"),
        ("owner-symlink", "ownership-changed"),
        ("git-failed", "git-check-failed"),
    ],
)
def test_apply_revalidation_skips_new_local_protection_or_replacement(
    tmp_path: Path,
    mutation: str,
    expected_reason: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    candidate = _add_candidate(run, sidecar=_triage_status())
    git_calls = 0

    def git_runner(
        argv: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal git_calls
        git_calls += 1
        if len(argv) == 5:
            if mutation == "retained":
                _write_json(
                    run / lrr.RETENTION_MARKER_FILENAME,
                    {
                        "kind": lrr.RETENTION_MARKER_KIND,
                        "version": lrr.RETENTION_MARKER_VERSION,
                        "job_id": run.name,
                        "function": run.parent.parent.name,
                        "reason": "keep now",
                        "created_at": "2026-07-11T12:00:00Z",
                    },
                )
            elif mutation == "winner":
                _write_json(
                    candidate.parent / lrr.CANDIDATE_STATUS_FILENAME,
                    _triage_status(
                        kept=True,
                        candidate=str(candidate),
                        function=run.parent.parent.name,
                    ),
                )
            elif mutation == "untriaged":
                (candidate.parent / lrr.CANDIDATE_STATUS_FILENAME).unlink()
            elif mutation == "symlink":
                (run / "new-link").symlink_to(tmp_path)
            elif mutation == "nonregular":
                os.mkfifo(run / "new-fifo")
            elif mutation == "replaced":
                moved = tmp_path / "original-run"
                run.rename(moved)
                shutil.copytree(moved, run)
            elif mutation == "root-symlink":
                moved = tmp_path / "original-run"
                run.rename(moved)
                run.symlink_to(moved, target_is_directory=True)
            elif mutation == "root-nonregular":
                moved = tmp_path / "original-run"
                run.rename(moved)
                run.write_text("replacement")
            elif mutation == "owner-symlink":
                remote_runs = run.parent
                moved = tmp_path / "moved-remote-runs"
                remote_runs.rename(moved)
                remote_runs.symlink_to(moved, target_is_directory=True)
            if mutation == "tracked":
                tracked = run.relative_to(perm_root) / "candidate_audit.json"
                return subprocess.CompletedProcess(argv, 0, f"{tracked}\0", "")
            if mutation == "git-failed":
                return subprocess.CompletedProcess(argv, 1, "", "git failed")
        return subprocess.CompletedProcess(argv, 0, "", "")

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=git_runner,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert git_calls == 2
    assert result.removed_count == 0
    assert result.skipped_count == 1
    assert expected_reason in result.actions[0].reasons
    assert run.exists()


def test_apply_unsafe_lock_path_fails_closed(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    outside = tmp_path / "outside-lock"
    outside.write_text("do not touch")
    (perm_root / lrr.LIFECYCLE_LOCK_FILENAME).symlink_to(outside)

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        remote_runner=lambda *_args, **_kwargs: pytest.fail("must not probe"),
        git_runner=_untracked_git,
    )

    assert result.status == "lock-unavailable"
    assert result.actions == ()
    assert outside.read_text() == "do not touch"
    assert run.is_dir()


def test_inventory_reports_quarantine_without_treating_it_as_run(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    quarantine = run.parent / f"{lrr.QUARANTINE_PREFIX}leftover"
    quarantine.mkdir()

    inventory = _inventory(perm_root)

    assert [summary.path for summary in inventory.runs] == [run]
    assert (
        lrr.InventoryIssue(
            quarantine,
            "quarantine-present",
            "leftover quarantine is not a deletion candidate",
        )
        in inventory.issues
    )


def test_apply_quarantine_collision_never_renames_or_overwrites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    fixed_uuid = lrr.uuid.UUID(int=0)
    quarantine = run.parent / f"{lrr.QUARANTINE_PREFIX}{fixed_uuid.hex}"
    quarantine.mkdir()
    sentinel = quarantine / "sentinel"
    sentinel.write_text("untouched")
    monkeypatch.setattr(lrr.uuid, "uuid4", lambda: fixed_uuid)

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.actions[0].reasons == ("quarantine-collision",)
    assert run.is_dir()
    assert sentinel.read_text() == "untouched"


def test_apply_rename_failure_keeps_original(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
        rename=lambda _source, _destination: (_ for _ in ()).throw(OSError("rename denied")),
    )

    assert result.actions[0].reasons[0] == "rename-failed"
    assert result.reclaimed_bytes == 0
    assert run.is_dir()


@pytest.mark.parametrize(
    ("post_rename_mutation", "expected_reason"),
    [
        ("symlink", "quarantine-nested-symlink"),
        ("marker", "quarantine-retention-marker"),
    ],
)
def test_apply_post_rename_protection_restores_original(
    tmp_path: Path,
    post_rename_mutation: str,
    expected_reason: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    first = True

    def rename(source: Path, destination: Path) -> None:
        nonlocal first
        os.rename(source, destination)
        if first:
            first = False
            if post_rename_mutation == "symlink":
                (destination / "late-link").symlink_to(tmp_path)
            else:
                (destination / lrr.RETENTION_MARKER_FILENAME).write_text("late")

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
        rename=rename,
    )

    assert expected_reason in result.actions[0].reasons
    assert "restored" in result.actions[0].reasons
    assert run.is_dir()
    assert result.actions[0].quarantine_path is not None
    assert not result.actions[0].quarantine_path.exists()


def test_apply_quarantine_identity_mismatch_is_not_restored_or_removed(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    displaced = tmp_path / "displaced-original"
    rename_calls = 0

    def rename(source: Path, destination: Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        os.rename(source, destination)
        os.rename(destination, displaced)
        destination.mkdir()

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
        rename=rename,
    )

    action = result.actions[0]
    assert "quarantine-identity-mismatch" in action.reasons
    assert "restored" not in action.reasons
    assert rename_calls == 1
    assert action.quarantine_path is not None
    assert action.quarantine_path.is_dir()
    assert displaced.is_dir()
    assert not run.exists()


def test_apply_restore_failure_leaves_visible_quarantine(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    calls = 0

    def rename(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("restore denied")
        os.rename(source, destination)
        (destination / lrr.RETENTION_MARKER_FILENAME).write_text("late")

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
        rename=rename,
    )

    action = result.actions[0]
    assert "restore-failed" in action.reasons
    assert action.quarantine_path is not None
    assert action.quarantine_path.is_dir()
    assert not run.exists()


@pytest.mark.parametrize("partial", [False, True])
def test_apply_removal_failure_reclaims_no_bytes_and_leaves_quarantine(
    tmp_path: Path,
    partial: bool,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)

    def remover(quarantine: Path) -> None:
        if partial:
            next(path for path in quarantine.rglob("*") if path.is_file()).unlink()
        raise OSError("rmtree failed")

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
        remover=remover,
    )

    action = result.actions[0]
    assert action.reasons[0] == "removal-failed"
    assert result.reclaimed_bytes == 0
    assert result.plan is not None
    assert result.projected_total_bytes == result.plan.total_bytes
    assert action.quarantine_path is not None
    assert action.quarantine_path.is_dir()


def test_apply_remover_returning_with_quarantine_present_is_incomplete(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    _make_run(perm_root)

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
        remover=lambda _quarantine: None,
    )

    assert result.actions[0].reasons == ("removal-incomplete",)
    assert result.reclaimed_bytes == 0


def test_apply_batches_two_probe_rounds_for_mixed_selected_and_active_runs(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    selected = _make_run(perm_root, function="fn_a", job_id="selected")
    active = _make_run(perm_root, function="fn_b", job_id="active")
    _set_remote_identity(selected, ssh="same-host", session="selected-session")
    _set_remote_identity(active, ssh="same-host", session="active-session")
    calls = 0

    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _tmux_result(argv, "active-session")

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=runner,
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert calls == 2
    assert result.removed_count == 1
    assert result.skipped_count == 0
    assert result.actions[0].job_id == "selected"
    assert not selected.exists()
    assert active.is_dir()
    assert not result.cap_satisfied


def test_apply_deletes_proven_run_but_reports_unrelated_inventory_issue(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    unexpected = run.parent / "unexpected.txt"
    unexpected.write_text("unknown")

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda argv, **_: _tmux_result(argv),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.removed_count == 1
    assert not result.inventory_complete
    assert not result.cap_satisfied
    assert unexpected.read_text() == "unknown"


def test_apply_initial_remote_runner_exception_protects_run(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)

    result = lrr.apply_local_remote_run_retention(
        perm_root,
        max_total_bytes=0,
        remote_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ssh exploded")),
        git_runner=_untracked_git,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.status == "completed"
    assert result.actions == ()
    assert result.reclaimed_bytes == 0
    assert run.is_dir()


def test_write_fetch_manifest_binds_identity_audit_and_utc_timestamp(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    candidate = _add_candidate(run, sidecar=_triage_status())
    summary = _summary(perm_root)
    assert summary.identity is not None
    audit = {
        "total": 1,
        "by_status": {"ok": 1},
        "by_semantic_risk_bucket": {"plausible-C-shape": 1},
        "candidates": [{"path": str(candidate)}],
    }

    result = lrr.write_local_fetch_manifest(
        run,
        identity=summary.identity,
        state="complete",
        candidate_audit=audit,
        clock=lambda: datetime(2026, 7, 11, 5, 30, tzinfo=UTC),
    )

    assert result.status == "written"
    assert result.ok
    payload = json.loads((run / lrr.FETCH_MANIFEST_FILENAME).read_text())
    assert payload == {
        "kind": lrr.FETCH_MANIFEST_KIND,
        "version": lrr.FETCH_MANIFEST_VERSION,
        **summary.identity.__dict__,
        "fetched_at": "2026-07-11T05:30:00Z",
        "state": "complete",
        "candidate_audit": {
            "total": 1,
            "by_status": {"ok": 1},
            "by_semantic_risk_bucket": {"plausible-C-shape": 1},
        },
    }
    assert lrr.read_fetch_manifest(
        run,
        identity=summary.identity,
        candidate_count=1,
    ).status == "complete"


def test_write_fetch_manifest_is_idempotent_and_can_promote_partial(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    summary = _summary(perm_root)
    assert summary.identity is not None
    audit = {"total": 0, "by_status": {}, "by_semantic_risk_bucket": {}, "candidates": []}

    first = lrr.write_local_fetch_manifest(
        run,
        identity=summary.identity,
        state="partial",
        candidate_audit=audit,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )
    same = lrr.write_local_fetch_manifest(
        run,
        identity=summary.identity,
        state="partial",
        candidate_audit=audit,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )
    promoted = lrr.write_local_fetch_manifest(
        run,
        identity=summary.identity,
        state="complete",
        candidate_audit=audit,
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert first.status == "written"
    assert same.status == "idempotent"
    assert promoted.status == "updated"
    payload = json.loads((run / lrr.FETCH_MANIFEST_FILENAME).read_text())
    assert payload["state"] == "complete"
    assert payload["fetched_at"] == "2026-07-12T00:00:00Z"


@pytest.mark.parametrize("existing_kind", ["symlink", "directory"])
def test_write_fetch_manifest_refuses_nonregular_existing_path(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    summary = _summary(perm_root)
    assert summary.identity is not None
    manifest = run / lrr.FETCH_MANIFEST_FILENAME
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    if existing_kind == "symlink":
        manifest.symlink_to(outside)
    else:
        manifest.mkdir()

    result = lrr.write_local_fetch_manifest(
        run,
        identity=summary.identity,
        state="complete",
        candidate_audit={"total": 0, "candidates": []},
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.status == "unsafe-existing"
    assert not result.ok
    assert outside.read_text() == "untouched"


def test_write_fetch_manifest_cleans_temp_when_atomic_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    summary = _summary(perm_root)
    assert summary.identity is not None
    monkeypatch.setattr(
        lrr,
        "_rename_no_replace",
        lambda _source, _destination: (_ for _ in ()).throw(OSError("collision")),
    )

    result = lrr.write_local_fetch_manifest(
        run,
        identity=summary.identity,
        state="complete",
        candidate_audit={"total": 0, "candidates": []},
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.status == "publish-failed"
    assert not (run / lrr.FETCH_MANIFEST_FILENAME).exists()
    assert not list(run.glob(".melee-agent-local-fetch.*.tmp"))


def test_write_fetch_manifest_update_restores_prior_on_post_publish_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    summary = _summary(perm_root)
    assert summary.identity is not None
    audit = {"total": 0, "by_status": {}, "by_semantic_risk_bucket": {}, "candidates": []}
    first = lrr.write_local_fetch_manifest(
        run,
        identity=summary.identity,
        state="partial",
        candidate_audit=audit,
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )
    assert first.ok
    prior = first.path.read_bytes()
    monkeypatch.setattr(
        lrr,
        "_fsync_directory",
        lambda _path: (_ for _ in ()).throw(OSError("fsync failed")),
    )

    update = lrr.write_local_fetch_manifest(
        run,
        identity=summary.identity,
        state="complete",
        candidate_audit=audit,
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert update.status == "publish-failed"
    assert first.path.read_bytes() == prior
    assert not list(run.glob(".melee-agent-local-fetch.*"))


def test_retain_local_remote_run_writes_bound_marker_and_protects_run(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)

    result = lrr.retain_local_remote_run(
        perm_root,
        run.name,
        reason="preserve investigation",
        clock=lambda: datetime(2026, 7, 11, 8, 15, tzinfo=UTC),
    )

    assert result.status == "written"
    assert result.ok
    assert result.path == run / lrr.RETENTION_MARKER_FILENAME
    assert json.loads(result.path.read_text()) == {
        "kind": lrr.RETENTION_MARKER_KIND,
        "version": lrr.RETENTION_MARKER_VERSION,
        "job_id": run.name,
        "function": run.parent.parent.name,
        "reason": "preserve investigation",
        "created_at": "2026-07-11T08:15:00Z",
    }
    assert "explicitly-retained" in _summary(perm_root).local_reasons


def test_retain_local_remote_run_is_idempotent_but_preserves_conflict(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)

    first = lrr.retain_local_remote_run(
        perm_root,
        run.name,
        reason="same reason",
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )
    before = first.path.read_bytes()
    same = lrr.retain_local_remote_run(
        perm_root,
        run.name,
        reason="same reason",
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )
    conflict = lrr.retain_local_remote_run(
        perm_root,
        run.name,
        reason="different reason",
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert first.status == "written"
    assert same.status == "idempotent"
    assert conflict.status == "conflict"
    assert first.path.read_bytes() == before


@pytest.mark.parametrize(
    ("job_id", "reason", "clock", "expected"),
    [
        ("missing", "reason", lambda: datetime(2026, 7, 11, tzinfo=UTC), "not-found"),
        ("job", "   ", lambda: datetime(2026, 7, 11, tzinfo=UTC), "invalid"),
        ("job", "reason", lambda: datetime(2026, 7, 11), "invalid"),
    ],
)
def test_retain_local_remote_run_controlled_input_failures(
    tmp_path: Path,
    job_id: str,
    reason: str,
    clock: object,
    expected: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    if job_id == "job":
        _make_run(perm_root, job_id=job_id)
    else:
        perm_root.mkdir()

    result = lrr.retain_local_remote_run(
        perm_root,
        job_id,
        reason=reason,
        clock=clock,
    )

    assert result.status == expected
    assert not result.ok


def test_retain_local_remote_run_refuses_duplicate_job_id(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    first = _make_run(perm_root, function="fn_a", job_id="duplicate")
    second = _make_run(perm_root, function="fn_b", job_id="duplicate")

    result = lrr.retain_local_remote_run(
        perm_root,
        "duplicate",
        reason="ambiguous",
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.status == "duplicate"
    assert not (first / lrr.RETENTION_MARKER_FILENAME).exists()
    assert not (second / lrr.RETENTION_MARKER_FILENAME).exists()


def test_retain_local_remote_run_uses_apply_lifecycle_lock(tmp_path: Path) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    lock_path = perm_root / lrr.LIFECYCLE_LOCK_FILENAME
    lock_path.touch(mode=0o600)
    descriptor = os.open(lock_path, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = lrr.retain_local_remote_run(
            perm_root,
            run.name,
            reason="busy",
            clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
        )
    finally:
        os.close(descriptor)

    assert result.status == "lock-busy"
    assert not (run / lrr.RETENTION_MARKER_FILENAME).exists()


@pytest.mark.parametrize("unsafe", ["metadata", "job-symlink", "marker-symlink"])
def test_retain_local_remote_run_refuses_invalid_or_symlinked_evidence(
    tmp_path: Path,
    unsafe: str,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    if unsafe == "metadata":
        (run / "remote-run" / "metadata.json").write_text("invalid")
    elif unsafe == "job-symlink":
        moved = tmp_path / "moved-run"
        run.rename(moved)
        run.symlink_to(moved, target_is_directory=True)
    else:
        marker = run / lrr.RETENTION_MARKER_FILENAME
        target = outside / "marker"
        target.write_text("untouched")
        marker.symlink_to(target)

    result = lrr.retain_local_remote_run(
        perm_root,
        run.name,
        reason="unsafe",
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.status in {"invalid", "unsafe"}
    assert not result.ok
    assert not (outside / lrr.RETENTION_MARKER_FILENAME).exists()


def test_retain_local_remote_run_publish_race_fails_without_marking_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perm_root = tmp_path / "decomp-permuter"
    run = _make_run(perm_root)
    original_rename = lrr._rename_no_replace
    moved = tmp_path / "moved-original"

    def raced_rename(source: Path, destination: Path) -> None:
        run.rename(moved)
        run.mkdir()
        original_rename(source, destination)

    monkeypatch.setattr(lrr, "_rename_no_replace", raced_rename)

    result = lrr.retain_local_remote_run(
        perm_root,
        run.name,
        reason="race",
        clock=lambda: datetime(2026, 7, 11, tzinfo=UTC),
    )

    assert result.status == "publish-failed"
    assert not (run / lrr.RETENTION_MARKER_FILENAME).exists()
    assert not (moved / lrr.RETENTION_MARKER_FILENAME).exists()
