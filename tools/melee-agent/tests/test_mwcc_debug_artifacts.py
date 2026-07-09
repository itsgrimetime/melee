import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.mwcc_debug.artifacts import (
    ArtifactRun,
    create_run,
    prune_runs,
    report_runs,
)


def test_completed_run_keeps_evidence_and_removes_transient(tmp_path: Path) -> None:
    run = create_run(tmp_path, command=["debug", "target", "score-source"])
    source = run.retain_text("source/candidate.c", "void fn(void) {}\n")
    transient = run.transient_path("compiler/discard.o")
    transient.parent.mkdir(parents=True)
    transient.write_bytes(b"object")

    manifest = run.finalize("completed", result={"score": 0})

    assert source.read_text() == "void fn(void) {}\n"
    assert not run.transient_dir.exists()
    assert manifest["state"] == "completed"
    assert manifest["evidence"]["source/candidate.c"] == len(source.read_bytes())


def test_failed_run_retains_existing_pcdump_and_score(tmp_path: Path) -> None:
    run = create_run(tmp_path, command=["debug", "target", "score-source"])
    run.retain_text("pcdump/candidate.txt", "Starting function fn\n")
    run.retain_json("score.json", {"score": 1 << 30, "error": "pcdump missing"})

    run.finalize("failed")

    assert (run.evidence_dir / "pcdump/candidate.txt").exists()
    assert json.loads((run.evidence_dir / "score.json").read_text())["error"] == "pcdump missing"


def _completed_run(
    root: Path,
    name: str,
    *,
    age_days: int = 0,
    evidence_bytes: int = 0,
) -> ArtifactRun:
    run = create_run(root, command=["test", name])
    run.retain_text("source/candidate.c", "x" * evidence_bytes)
    run.finalize("completed")
    manifest = json.loads(run.manifest_path.read_text())
    manifest["finished_at"] = (
        datetime.now(UTC) - timedelta(days=age_days)
    ).isoformat()
    run.manifest_path.write_text(json.dumps(manifest))
    return run


def test_report_and_dry_run_leave_completed_runs_intact(tmp_path: Path) -> None:
    old = _completed_run(tmp_path, "old", age_days=31, evidence_bytes=8)

    report = report_runs(tmp_path)
    plan = prune_runs(tmp_path, max_age_days=30, max_total_bytes=1024, apply=False)

    assert report.completed_runs == 1
    assert plan.removed_run_dirs == ()
    assert plan.planned_run_dirs == (old.run_dir,)
    assert old.run_dir.exists()


def test_prune_removes_whole_oldest_terminal_bundle_only(tmp_path: Path) -> None:
    oldest = _completed_run(tmp_path, "oldest", age_days=1, evidence_bytes=8)
    newest = _completed_run(tmp_path, "newest", age_days=0, evidence_bytes=8)

    plan = prune_runs(tmp_path, max_age_days=100, max_total_bytes=8, apply=True)

    assert plan.removed_run_dirs == (oldest.run_dir,)
    assert not oldest.run_dir.exists()
    assert newest.run_dir.exists()


def test_prune_skips_active_malformed_and_symlinked_entries(tmp_path: Path) -> None:
    active = create_run(tmp_path, command=["debug"])
    malformed = tmp_path / "build/diagnostics/runs/not-a-run"
    malformed.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "build/diagnostics/runs/linked").symlink_to(outside)

    plan = prune_runs(tmp_path, max_age_days=0, max_total_bytes=0, apply=True)

    assert active.run_dir.exists()
    assert malformed.exists()
    assert outside.exists()
    assert {item.reason for item in plan.skipped} >= {
        "active",
        "missing-manifest",
        "symlink",
    }
