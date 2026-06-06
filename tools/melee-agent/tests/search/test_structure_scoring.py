from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.search.structure import StructureVariant
import src.search.structure_scoring as scoring_mod
from src.search.structure_scoring import score_structure_variants


def _write_report(path: Path, percent: float) -> None:
    path.write_text(
        json.dumps({
            "units": [
                {
                    "name": "main/melee/demo",
                    "functions": [
                        {
                            "name": "fn_80000000",
                            "fuzzy_match_percent": percent,
                        }
                    ],
                }
            ]
        })
    )


def test_structural_metrics_include_opcode_shape_preserved() -> None:
    structural = scoring_mod._structural_with_deltas(
        {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
        {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
    )

    assert structural["opcode_shape_preserved"] is True

    structural = scoring_mod._structural_with_deltas(
        {"opcode_similarity": 1.0},
        {"opcode_similarity": 0.98},
    )

    assert structural["opcode_shape_preserved"] is False


def test_structural_metrics_preserve_shape_from_current_asm_sequences() -> None:
    baseline = scoring_mod._extract_structural_metrics({
        "opcode_similarity": 1.0,
        "line_delta": 0,
        "hunk_count": 1,
        "current_asm": [
            "/* 0000 */ mr r3, r4",
            "/* 0004 */ bl helper",
        ],
    })
    same_shape_candidate = scoring_mod._extract_structural_metrics({
        "opcode_similarity": 0.98,
        "line_delta": 0,
        "hunk_count": 1,
        "current_asm": [
            "/* 0000 */ mr r5, r6",
            "/* 0004 */ bl helper",
        ],
    })

    structural = scoring_mod._structural_with_deltas(
        baseline,
        same_shape_candidate,
    )

    assert structural["opcode_shape_preserved"] is True
    assert "current_asm" not in structural
    assert "_opcode_sequence" not in structural

    changed_shape_candidate = scoring_mod._extract_structural_metrics({
        "opcode_similarity": 1.0,
        "line_delta": 0,
        "hunk_count": 1,
        "current_asm": [
            "/* 0000 */ li r3, 0",
            "/* 0004 */ bl helper",
        ],
    })

    structural = scoring_mod._structural_with_deltas(
        baseline,
        changed_shape_candidate,
    )

    assert structural["opcode_shape_preserved"] is False
    assert "_opcode_sequence" not in structural


def test_score_structure_variants_restores_files_and_sets_checkdiff_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    source_path = melee_root / "src" / "melee" / "demo.c"
    obj_path = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    report_path = melee_root / "build" / "GALE01" / "report.json"
    objdiff_path = melee_root / "build" / "tools" / "objdiff-cli"
    candidate_path = tmp_path / "candidate.c"

    source_path.parent.mkdir(parents=True)
    obj_path.parent.mkdir(parents=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    objdiff_path.parent.mkdir(parents=True)
    source_path.write_text("int fn_80000000(void) { return 0; }\n")
    obj_path.write_bytes(b"original object")
    _write_report(report_path, 12.0)
    objdiff_path.write_text("# fake objdiff\n")
    candidate_path.write_text("int fn_80000000(void) { return 1; }\n")

    original_source = source_path.read_bytes()
    original_obj = obj_path.read_bytes()
    original_report = report_path.read_bytes()
    report_percents = iter([90.0, 92.5])
    checkdiff_envs: list[dict[str, str]] = []

    def fake_run(cmd, **kwargs):
        argv = [str(part) for part in cmd]
        if argv[:2] == ["ninja", "build/GALE01/src/melee/demo.o"]:
            obj_path.write_bytes(b"candidate object")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "objdiff-cli" in argv[0]:
            _write_report(report_path, next(report_percents))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if argv[:3] == ["python", "tools/checkdiff.py", "fn_80000000"]:
            checkdiff_envs.append(kwargs["env"])
            payload = {
                "opcode_similarity": 0.95 + len(checkdiff_envs) / 100,
                "line_delta": 1,
                "hunk_count": len(checkdiff_envs),
            }
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=json.dumps(payload),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(scoring_mod, "_run_child", fake_run)

    results = score_structure_variants(
        melee_root=melee_root,
        function="fn_80000000",
        source_path=source_path,
        variants=[
            StructureVariant(
                axis="decl-order",
                operator="decl-order-swap",
                label="swap locals",
                status="unscored",
                source_retained=str(candidate_path),
            )
        ],
        timeout=5.0,
    )

    assert source_path.read_bytes() == original_source
    assert obj_path.read_bytes() == original_obj
    assert report_path.read_bytes() == original_report
    assert len(checkdiff_envs) == 2
    assert all(env["CHECKDIFF_NO_LOCK"] == "1" for env in checkdiff_envs)
    assert all(env["CHECKDIFF_NO_FINGERPRINT"] == "1" for env in checkdiff_envs)
    assert results[0].label == "swap locals"
    assert results[0].compile_status == "ok"
    assert results[0].baseline_percent == 90.0
    assert results[0].candidate_percent == 92.5
    assert results[0].structural["opcode_similarity_delta"] == 0.01
    assert results[0].structural["line_delta_delta"] == 0
    assert results[0].structural["hunk_count_delta"] == 1


def test_score_structure_variants_returns_unscored_on_compile_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    source_path = melee_root / "src" / "melee" / "demo.c"
    obj_path = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    report_path = melee_root / "build" / "GALE01" / "report.json"
    objdiff_path = melee_root / "build" / "tools" / "objdiff-cli"
    candidate_path = tmp_path / "candidate.c"

    source_path.parent.mkdir(parents=True)
    obj_path.parent.mkdir(parents=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    objdiff_path.parent.mkdir(parents=True)
    source_path.write_text("int fn_80000000(void) { return 0; }\n")
    obj_path.write_bytes(b"original object")
    _write_report(report_path, 12.0)
    objdiff_path.write_text("# fake objdiff\n")
    candidate_path.write_text("int fn_80000000(void) { return 1; }\n")

    def fake_run(cmd, **kwargs):
        argv = [str(part) for part in cmd]
        if argv[:2] == ["ninja", "build/GALE01/src/melee/demo.o"]:
            if source_path.read_text() == candidate_path.read_text():
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout="",
                    stderr="syntax error",
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "objdiff-cli" in argv[0]:
            _write_report(report_path, 90.0)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if argv[:3] == ["python", "tools/checkdiff.py", "fn_80000000"]:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=json.dumps({"opcode_similarity": 0.96}),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(scoring_mod, "_run_child", fake_run)

    results = score_structure_variants(
        melee_root=melee_root,
        function="fn_80000000",
        source_path=source_path,
        variants=[
            StructureVariant(
                axis="decl-order",
                operator="decl-order-swap",
                label="bad candidate",
                status="unscored",
                source_retained=str(candidate_path),
            )
        ],
        timeout=5.0,
    )

    assert results[0].label == "bad candidate"
    assert results[0].compile_status == "failed"
    assert results[0].unscored_reason == "candidate compile failed: syntax error"


def test_score_structure_variants_keeps_candidate_percent_when_checkdiff_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    source_path = melee_root / "src" / "melee" / "demo.c"
    obj_path = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    report_path = melee_root / "build" / "GALE01" / "report.json"
    objdiff_path = melee_root / "build" / "tools" / "objdiff-cli"
    candidate_path = tmp_path / "candidate.c"

    source_path.parent.mkdir(parents=True)
    obj_path.parent.mkdir(parents=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    objdiff_path.parent.mkdir(parents=True)
    source_path.write_text("int fn_80000000(void) { return 0; }\n")
    obj_path.write_bytes(b"original object")
    _write_report(report_path, 12.0)
    objdiff_path.write_text("# fake objdiff\n")
    candidate_path.write_text("int fn_80000000(void) { return 1; }\n")

    report_percents = iter([90.0, 91.25])
    checkdiff_calls = 0

    def fake_run(cmd, **kwargs):
        nonlocal checkdiff_calls
        argv = [str(part) for part in cmd]
        if argv[:2] == ["ninja", "build/GALE01/src/melee/demo.o"]:
            obj_path.write_bytes(b"candidate object")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "objdiff-cli" in argv[0]:
            _write_report(report_path, next(report_percents))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if argv[:3] == ["python", "tools/checkdiff.py", "fn_80000000"]:
            checkdiff_calls += 1
            if checkdiff_calls == 1:
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout=json.dumps({"opcode_similarity": 0.96}),
                    stderr="",
                )
            return subprocess.CompletedProcess(
                cmd,
                2,
                stdout="",
                stderr="checkdiff failed",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(scoring_mod, "_run_child", fake_run)

    results = score_structure_variants(
        melee_root=melee_root,
        function="fn_80000000",
        source_path=source_path,
        variants=[
            StructureVariant(
                axis="decl-order",
                operator="decl-order-swap",
                label="checkdiff fail",
                status="unscored",
                source_retained=str(candidate_path),
            )
        ],
        timeout=5.0,
    )

    assert results[0].compile_status == "ok"
    assert results[0].checkdiff_status == "failed"
    assert results[0].baseline_percent == 90.0
    assert results[0].candidate_percent == 91.25
    assert results[0].unscored_reason == "candidate checkdiff failed: checkdiff failed"


def test_score_structure_variants_marks_baseline_checkdiff_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    source_path = melee_root / "src" / "melee" / "demo.c"
    obj_path = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    report_path = melee_root / "build" / "GALE01" / "report.json"
    objdiff_path = melee_root / "build" / "tools" / "objdiff-cli"
    candidate_path = tmp_path / "candidate.c"

    source_path.parent.mkdir(parents=True)
    obj_path.parent.mkdir(parents=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    objdiff_path.parent.mkdir(parents=True)
    source_path.write_text("int fn_80000000(void) { return 0; }\n")
    obj_path.write_bytes(b"original object")
    _write_report(report_path, 12.0)
    objdiff_path.write_text("# fake objdiff\n")
    candidate_path.write_text("int fn_80000000(void) { return 1; }\n")

    report_percents = iter([90.0, 91.25])
    checkdiff_calls = 0

    def fake_run(cmd, **kwargs):
        nonlocal checkdiff_calls
        argv = [str(part) for part in cmd]
        if argv[:2] == ["ninja", "build/GALE01/src/melee/demo.o"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "objdiff-cli" in argv[0]:
            _write_report(report_path, next(report_percents))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if argv[:3] == ["python", "tools/checkdiff.py", "fn_80000000"]:
            checkdiff_calls += 1
            if checkdiff_calls == 1:
                return subprocess.CompletedProcess(
                    cmd,
                    2,
                    stdout="",
                    stderr="baseline checkdiff failed",
                )
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=json.dumps({"opcode_similarity": 0.97}),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(scoring_mod, "_run_child", fake_run)

    results = score_structure_variants(
        melee_root=melee_root,
        function="fn_80000000",
        source_path=source_path,
        variants=[
            StructureVariant(
                axis="decl-order",
                operator="decl-order-swap",
                label="baseline checkdiff fail",
                status="unscored",
                source_retained=str(candidate_path),
            )
        ],
        timeout=5.0,
    )

    assert results[0].compile_status == "ok"
    assert results[0].checkdiff_status == "failed"
    assert results[0].baseline_percent == 90.0
    assert results[0].candidate_percent == 91.25
    assert results[0].unscored_reason == (
        "baseline checkdiff failed: baseline checkdiff failed"
    )
    assert results[0].structural["opcode_similarity"] == 0.97


def test_score_structure_variants_uses_process_group_runner(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    source_path = melee_root / "src" / "melee" / "demo.c"
    obj_path = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    report_path = melee_root / "build" / "GALE01" / "report.json"
    objdiff_path = melee_root / "build" / "tools" / "objdiff-cli"
    candidate_path = tmp_path / "candidate.c"

    source_path.parent.mkdir(parents=True)
    obj_path.parent.mkdir(parents=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    objdiff_path.parent.mkdir(parents=True)
    source_path.write_text("int fn_80000000(void) { return 0; }\n")
    obj_path.write_bytes(b"original object")
    _write_report(report_path, 12.0)
    objdiff_path.write_text("# fake objdiff\n")
    candidate_path.write_text("int fn_80000000(void) { return 1; }\n")

    def fail_plain_run(*args, **kwargs):
        raise AssertionError("plain subprocess.run must not be used")

    def fake_run_child(cmd, **kwargs):
        argv = [str(part) for part in cmd]
        if argv[:2] == ["ninja", "build/GALE01/src/melee/demo.o"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "objdiff-cli" in argv[0]:
            _write_report(report_path, 90.0)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if argv[:3] == ["python", "tools/checkdiff.py", "fn_80000000"]:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=json.dumps({"opcode_similarity": 0.96}),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(scoring_mod.subprocess, "run", fail_plain_run)
    monkeypatch.setattr(scoring_mod, "_run_child", fake_run_child)

    score_structure_variants(
        melee_root=melee_root,
        function="fn_80000000",
        source_path=source_path,
        variants=[
            StructureVariant(
                axis="decl-order",
                operator="decl-order-swap",
                label="candidate",
                status="unscored",
                source_retained=str(candidate_path),
            )
        ],
        timeout=5.0,
    )


def test_score_structure_variants_restores_checkdiff_history(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    source_path = melee_root / "src" / "melee" / "demo.c"
    obj_path = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    report_path = melee_root / "build" / "GALE01" / "report.json"
    objdiff_path = melee_root / "build" / "tools" / "objdiff-cli"
    history_path = melee_root / "build" / ".checkdiff-history" / "fn_80000000.json"
    candidate_path = tmp_path / "candidate.c"

    source_path.parent.mkdir(parents=True)
    obj_path.parent.mkdir(parents=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    objdiff_path.parent.mkdir(parents=True)
    history_path.parent.mkdir(parents=True)
    source_path.write_text("int fn_80000000(void) { return 0; }\n")
    obj_path.write_bytes(b"original object")
    _write_report(report_path, 12.0)
    objdiff_path.write_text("# fake objdiff\n")
    history_path.write_text('{"fuzzy_match_percent": 12.0}')
    candidate_path.write_text("int fn_80000000(void) { return 1; }\n")
    original_history = history_path.read_bytes()

    def fake_run(cmd, **kwargs):
        argv = [str(part) for part in cmd]
        if argv[:2] == ["ninja", "build/GALE01/src/melee/demo.o"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "objdiff-cli" in argv[0]:
            _write_report(report_path, 90.0)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if argv[:3] == ["python", "tools/checkdiff.py", "fn_80000000"]:
            history_path.write_text('{"fuzzy_match_percent": 0.0}')
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=json.dumps({"opcode_similarity": 0.96}),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(scoring_mod, "_run_child", fake_run)

    score_structure_variants(
        melee_root=melee_root,
        function="fn_80000000",
        source_path=source_path,
        variants=[
            StructureVariant(
                axis="decl-order",
                operator="decl-order-swap",
                label="candidate",
                status="unscored",
                source_retained=str(candidate_path),
            )
        ],
        timeout=5.0,
    )

    assert history_path.read_bytes() == original_history
