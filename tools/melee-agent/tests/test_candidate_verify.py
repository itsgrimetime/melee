"""Tests for candidate verification helpers."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess

from src.mwcc_debug.candidate_verify import (
    CheckdiffResult,
    parse_checkdiff_json,
    stage_patch,
    verify_patches,
    verify_real_tree_patches,
)
from src.mwcc_debug import source_shape
from src.mwcc_debug.source_candidate_scoring import (
    ScoreSourceConfig,
    SourceCandidate,
    score_source_candidates,
)
from src.mwcc_debug.source_shape import CandidatePatch


def test_stage_patch_writes_base_c(tmp_path: Path) -> None:
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) {}\n",
        summary="introduce temp",
        touched_ranges=((1, 2),),
    )
    staged = stage_patch(tmp_path, "fn_test", patch)
    assert staged.source_path.exists()
    assert staged.source_path.name == "base.c"
    assert staged.source_path.read_text() == "void f(void) {}\n"


def test_parse_checkdiff_json_reads_match_percent_and_delta() -> None:
    payload = '{"function": "fn", "fuzzy_match_percent": 97.5, "delta": 0.25}'
    parsed = parse_checkdiff_json(payload)
    assert parsed == CheckdiffResult(match_pct=97.5, delta=0.25)


def test_verify_patches_uses_runner_and_returns_scores(tmp_path: Path) -> None:
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) {}\n",
        summary="introduce temp",
        touched_ranges=((1, 2),),
    )

    def runner(candidate: CandidatePatch, staged_source: Path) -> CheckdiffResult:
        assert candidate.candidate_id == "arg-temp-0001"
        assert staged_source.exists()
        return CheckdiffResult(match_pct=98.0, delta=0.1)

    scores = verify_patches(
        function="fn_test",
        patches=[patch],
        stage_root=tmp_path,
        checkdiff_runner=runner,
    )
    assert len(scores) == 1
    assert scores[0].candidate_id == "arg-temp-0001"
    assert scores[0].compile_ok is True
    assert scores[0].checkdiff_delta == 0.1


def test_verify_real_tree_restores_source(tmp_path: Path) -> None:
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )

    def runner(function: str) -> CheckdiffResult:
        assert function == "fn_test"
        assert "Candidate" in source_path.read_text()
        return CheckdiffResult(match_pct=90.0, delta=0.1)

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
    )
    assert scores[0].checkdiff_delta == 0.1
    assert source_path.read_text() == "void f(void) { Original(); }\n"


def test_verify_real_tree_records_runner_error_and_continues(tmp_path: Path) -> None:
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )

    def runner(function: str) -> CheckdiffResult:
        raise RuntimeError("checkdiff timed out after 5s: python tools/checkdiff.py fn")

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
        diagnostics_root=tmp_path / "diagnostics",
    )

    assert len(scores) == 1
    assert scores[0].compile_ok is False
    assert scores[0].diagnostics_path is not None
    assert "checkdiff timed out" in scores[0].diagnostics_path.read_text()
    assert source_path.read_text() == "void f(void) { Original(); }\n"


def test_verify_real_tree_computes_delta_from_baseline_result(tmp_path: Path) -> None:
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )

    def runner(function: str) -> CheckdiffResult:
        assert function == "fn_test"
        return CheckdiffResult(match_pct=97.25, delta=None)

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
        baseline_result=CheckdiffResult(match_pct=97.25, delta=None),
    )

    assert scores[0].checkdiff_baseline_pct == 97.25
    assert scores[0].checkdiff_pct == 97.25
    assert scores[0].checkdiff_delta == 0.0
    assert source_path.read_text() == "void f(void) { Original(); }\n"


def test_verify_real_tree_attaches_copy_trace_results(tmp_path: Path) -> None:
    assert hasattr(source_shape, "CandidateCopyTrace")
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )
    trace = source_shape.CandidateCopyTrace(
        from_virtual=50,
        to_virtual=110,
        status="copy-found",
        likely_cause="removed-before-coloring",
    )

    def runner(function: str) -> CheckdiffResult:
        return CheckdiffResult(match_pct=97.25, delta=0.0)

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
        copy_trace_runner=lambda candidate: [trace],
    )

    assert scores[0].copy_traces == (trace,)
    assert source_path.read_text() == "void f(void) { Original(); }\n"


def test_verify_real_tree_preserves_copy_trace_summary_counts(tmp_path: Path) -> None:
    assert hasattr(source_shape, "CandidateCopyTraceSet")
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="hidden-dirty-arg-temp-group-0004",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )
    trace = source_shape.CandidateCopyTrace(
        from_virtual=50,
        to_virtual=110,
        status="copy-found",
        likely_cause="removed-before-coloring",
        interest_reasons=("dominant-source-virtual",),
    )
    noisy_trace = source_shape.CandidateCopyTrace(
        from_virtual=70,
        to_virtual=120,
        status="copy-found",
        likely_cause="removed-before-coloring",
    )
    trace_set = source_shape.CandidateCopyTraceSet(
        traces=(trace,),
        total_count=2,
        raw_traces=(trace, noisy_trace),
    )

    def runner(function: str) -> CheckdiffResult:
        return CheckdiffResult(match_pct=97.25, delta=0.0)

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
        copy_trace_runner=lambda candidate: trace_set,
    )

    assert scores[0].copy_trace_highlights == (trace,)
    assert scores[0].copy_traces == (trace, noisy_trace)
    assert scores[0].copy_trace_total_count == 2
    assert scores[0].copy_trace_omitted_count == 1


def test_score_source_patch_candidates_write_retained_sources_and_merge_payload(
    tmp_path: Path,
) -> None:
    pcdump_path = tmp_path / "retained.pcdump.txt"
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, env, **kwargs):
        retained_source = Path(cmd[cmd.index("score-source") + 1])
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        assert retained_source.exists()
        assert "Candidate" in retained_source.read_text()
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({
                "score": 3,
                "target_score": {
                    "matched": 1,
                    "targeted": 2,
                    "virtual_distance": 1,
                },
                "expression_score": {
                    "matched": 0,
                    "targeted": 2,
                    "virtual_distance": 2,
                },
                "pcdump_path": str(pcdump_path),
                "structural_guard": {"accepted": True},
            }),
            stderr="",
        )

    config = ScoreSourceConfig(
        repo_root=tmp_path,
        function="fn_test",
        target=tmp_path / "target.json",
        cflags_from=Path("src/melee/test.c"),
        expression_source=Path("src/melee/test.c"),
        expression_baseline=None,
        expression_reg_class="fpr",
        output_dir=tmp_path / "retained",
        timeout=5.0,
    )
    rows = score_source_candidates(
        [
            SourceCandidate(
                candidate_id="local-write-0001",
                source_text="void fn_test(void) { Candidate(); }\n",
                metadata={
                    "family": "inline-local-write-helper",
                    "strategy": "block-macro",
                },
                source_hunks=({"hunk_id": "h001"},),
            )
        ],
        config,
        runner=fake_run,
    )

    row = rows[0]
    assert captured["cwd"] == tmp_path
    assert Path(row["source_retained"]).exists()
    assert row["source_file"] == row["source_retained"]
    assert row["pcdump_path"] == str(pcdump_path)
    assert row["target_matched"] == 1
    assert row["target_targeted"] == 2
    assert row["expression_virtual_distance"] == 2
    assert row["score_command"]
    assert row["terminal_safe"] is True
    assert row["source_hunks"] == [{"hunk_id": "h001"}]


def test_score_source_patch_candidate_error_row_is_preserved(
    tmp_path: Path,
) -> None:
    def fake_run(cmd, *, cwd, env, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({
                "score": 1073741824,
                "error": "function 'fn_test' not in compiled pcdump",
                "pcdump_path": str(tmp_path / "candidate-error.pcdump.txt"),
            }),
            stderr="function missing",
        )

    config = ScoreSourceConfig(
        repo_root=tmp_path,
        function="fn_test",
        target=tmp_path / "target.json",
        cflags_from=Path("src/melee/test.c"),
        expression_source=Path("src/melee/test.c"),
        expression_baseline=None,
        expression_reg_class="gpr",
        output_dir=tmp_path / "retained",
        timeout=5.0,
    )

    rows = score_source_candidates(
        [
            SourceCandidate(
                candidate_id="candidate-error",
                source_text="void other(void) {}\n",
            )
        ],
        config,
        runner=fake_run,
    )

    row = rows[0]
    assert row["candidate_id"] == "candidate-error"
    assert row["error"] == "function 'fn_test' not in compiled pcdump"
    assert row["score_error_kind"] == "candidate"
    assert row["terminal_safe"] is True
    assert any(
        blocker["reason"].startswith("score-source-error:function 'fn_test'")
        for blocker in row["blockers"]
    )


def test_retained_candidate_identity_overrides_scorer_filename_identity(
    tmp_path: Path,
) -> None:
    def fake_run(cmd, *, cwd, env, **kwargs):
        del cwd, env, kwargs
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "candidate_id": "filename-derived-id",
                    "score": 0,
                    "pcdump_path": str(tmp_path / "candidate.pcdump.txt"),
                }
            ),
            stderr="",
        )

    config = ScoreSourceConfig(
        repo_root=tmp_path,
        function="fn_test",
        target=tmp_path / "target.json",
        cflags_from=Path("src/melee/test.c"),
        expression_source=Path("src/melee/test.c"),
        expression_baseline=None,
        expression_reg_class="gpr",
        output_dir=tmp_path / "retained",
        timeout=5.0,
    )

    row = score_source_candidates(
        [SourceCandidate(candidate_id="manifest-mask-000", source_text="void fn_test(void) {}\n")],
        config,
        runner=fake_run,
    )[0]

    assert row["candidate_id"] == "manifest-mask-000"


def test_score_source_candidates_can_retain_and_score_without_target(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, *, cwd, env, **kwargs):
        retained_source = Path(cmd[cmd.index("score-source") + 1])
        captured["cmd"] = cmd
        assert "--target" not in cmd
        assert "--checkdiff-guard" in cmd
        assert retained_source.exists()
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({
                "score": 16,
                "match_percent": 95.75,
                "checkdiff_match_percent": 95.75,
                "pcdump_path": str(tmp_path / "candidate.pcdump.txt"),
                "structural_guard": {
                    "accepted": False,
                    "classification_primary": "instruction-sequence",
                    "normalized_diff_lines": 16,
                },
            }),
            stderr="",
        )

    config = ScoreSourceConfig(
        repo_root=tmp_path,
        function="fn_test",
        target=None,
        cflags_from=Path("src/melee/test.c"),
        expression_source=Path("src/melee/test.c"),
        expression_baseline=None,
        expression_reg_class="gpr",
        output_dir=tmp_path / "retained",
        timeout=5.0,
    )
    rows = score_source_candidates(
        [
            SourceCandidate(
                candidate_id="local-write-0001",
                source_text="void fn_test(void) { Candidate(); }\n",
                metadata={
                    "family": "inline-local-write-helper",
                    "strategy": "block-macro",
                },
                source_hunks=({"hunk_id": "h001"},),
            )
        ],
        config,
        runner=fake_run,
    )

    row = rows[0]
    assert Path(row["source_retained"]).is_file()
    assert row["pcdump_path"].endswith(".pcdump.txt")
    assert row["checkdiff_match_percent"] == 95.75
    assert row["structural_guard"]["normalized_diff_lines"] == 16
    assert row["terminal_safe"] is True
    assert row["source_hunks"] == [{"hunk_id": "h001"}]
