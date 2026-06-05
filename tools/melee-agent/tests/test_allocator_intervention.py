"""Tests for backend-backed allocator intervention reporting."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli import app
from src.cli import debug as debug_cli
from src.mwcc_debug.allocator_intervention import (
    CoalesceInterventionSpec,
    analyze_coalesce_intervention,
    render_coalesce_intervention_text,
)


runner = CliRunner()


def _pcdump(*, forced: bool = False) -> str:
    force_lines = ""
    aliases = "  43 -> 40 [r25]\n" if not forced else ""
    assigned_43 = "r26" if forced else "r25"
    forced_count = 1 if forced else 0
    if forced:
        force_lines = "[FORCE_COALESCE] alias[43]: 40 -> 43\n"
    return f"""\
Starting function fn_80000000

BEFORE REGISTER COLORING
fn_80000000
B0: Succ={{}} Pred={{}} Labels={{}}
    mr r43,r40

[COALESCE] enter class=0 n_virtuals=64
[COALESCE] natural mappings (virt -> root):
  43 -> 40
{force_lines}[COALESCE] exit class=0 n_virtuals=64 distinct_roots=64 forced={forced_count}

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=64)
iter ig_idx degree array_size flags
0    40     1      1          0x0
1    43     1      1          0x0

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=64)
iter  ig_idx  reg  degree  nIntfr  flags
0     40      r25  1       1       0x00
      interferers: 43={assigned_43}
1     43      {assigned_43}  1       1       0x00
      interferers: 40=r25

COALESCED ALIASES (alias_idx -> root_idx [root_phys]):
{aliases}
AFTER REGISTER COLORING
fn_80000000
B0: Succ={{}} Pred={{}} Labels={{}}
    mr r3,r25

FINAL CODE AFTER INSTRUCTION SCHEDULING
fn_80000000
B0: Succ={{}} Pred={{}} Labels={{}}
    mr r3,r25
"""


def test_block_coalesce_report_reaches_backend_target_and_renders_changes() -> None:
    spec = CoalesceInterventionSpec(action="block", virt=43, root=40)

    report = analyze_coalesce_intervention(
        _pcdump(forced=False),
        _pcdump(forced=True),
        function="fn_80000000",
        spec=spec,
        baseline_match_percent=95.0,
        intervention_match_percent=96.25,
    )

    assert report.backend_env == {"MWCC_DEBUG_FORCE_COALESCE": "43=43"}
    assert report.backend_applied is True
    assert report.target_reached is True
    assert report.baseline_pair_root == 40
    assert report.intervention_pair_root is None
    assert report.final_allocation_changed is True
    assert report.coalesce_mappings_changed is True
    assert report.simplify_order_changed is False
    assert report.spill_set_changed is False
    assert report.match_score_changed is True

    text = render_coalesce_intervention_text(report)
    assert "hook: block r43 -> r40" in text
    assert "backend env: MWCC_DEBUG_FORCE_COALESCE=43=43" in text
    assert "target reached: yes" in text
    assert "coalesce mappings changed: yes" in text
    assert "real match score changed: yes (95.00000 -> 96.25000)" in text


def test_intervene_coalesce_local_invokes_dump_with_force_coalesce_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n")
    output_dir = tmp_path / "runs"
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        cmd = [str(part) for part in cmd]
        calls.append(cmd)
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_pcdump(forced="--force-coalesce" in cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "intervene",
            "coalesce",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--block",
            "r43=r40",
            "--mode",
            "local",
            "--output-dir",
            str(output_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(calls) == 2
    baseline_cmd, intervention_cmd = calls
    assert "--force-coalesce" not in baseline_cmd
    assert "--force-coalesce" in intervention_cmd
    assert intervention_cmd[intervention_cmd.index("--force-coalesce") + 1] == "43=43"
    assert "--force-coalesce-fn" in intervention_cmd
    assert intervention_cmd[intervention_cmd.index("--force-coalesce-fn") + 1] == "fn_80000000"
    assert "--no-cache-sync" in intervention_cmd
    assert "--timeout" not in intervention_cmd
    payload = json.loads(result.stdout)
    assert payload["target_reached"] is True
    assert payload["backend_env"]["MWCC_DEBUG_FORCE_COALESCE"] == "43=43"


def test_intervene_coalesce_resolves_relative_source_before_child_cwd(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n")
    output_dir = tmp_path / "runs"
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        cmd = [str(part) for part in cmd]
        calls.append(cmd)
        assert Path(cmd[6]).is_absolute()
        assert Path(cmd[6]) == source
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_pcdump(forced="--force-coalesce" in cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.chdir(melee_root)
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "intervene",
            "coalesce",
            "-f",
            "fn_80000000",
            "--source-file",
            "src/melee/mn/sample.c",
            "--block",
            "r43=r40",
            "--mode",
            "local",
            "--output-dir",
            str(output_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(calls) == 2


def test_intervene_coalesce_remote_invokes_remote_dump_with_force_coalesce_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        cmd = [str(part) for part in cmd]
        calls.append(cmd)
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_pcdump(forced="--force-coalesce" in cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "intervene",
            "coalesce",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--force",
            "r43=r40",
            "--mode",
            "remote",
            "--host",
            "nzxt-local",
            "--no-pull",
            "--output-dir",
            str(tmp_path / "runs"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    _, intervention_cmd = calls
    assert intervention_cmd[:6] == ["python", "-m", "src.cli", "debug", "dump", "remote"]
    assert "--host" in intervention_cmd
    assert intervention_cmd[intervention_cmd.index("--host") + 1] == "nzxt-local"
    assert "--no-pull" in intervention_cmd
    assert "--no-cache-sync" not in intervention_cmd
    assert intervention_cmd[intervention_cmd.index("--force-coalesce") + 1] == "43=40"
    assert intervention_cmd[intervention_cmd.index("--force-coalesce-fn") + 1] == "fn_80000000"
    payload = json.loads(result.stdout)
    assert payload["backend_env"]["MWCC_DEBUG_FORCE_COALESCE"] == "43=40"


def test_intervene_coalesce_reports_compile_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_run(cmd, **kwargs):
        cmd = [str(part) for part in cmd]
        if "--force-coalesce" not in cmd:
            out_path = Path(cmd[cmd.index("--output") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(_pcdump(forced=False))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=7, stdout="", stderr="forced compile failed")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "intervene",
            "coalesce",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--block",
            "r43=r40",
            "--output-dir",
            str(tmp_path / "runs"),
        ],
    )

    assert result.exit_code == 7
    assert "intervention compile failed" in result.stderr
    assert "MWCC_DEBUG_FORCE_COALESCE=43=43" in result.stderr
    assert "forced compile failed" in result.stderr


def test_intervene_coalesce_reports_missing_function_events(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(_pcdump(forced=False).replace("fn_80000000", "other_fn"))

    result = runner.invoke(
        app,
        [
            "debug",
            "intervene",
            "coalesce",
            "-f",
            "fn_80000000",
            "--baseline-pcdump",
            str(pcdump),
            "--intervention-pcdump",
            str(pcdump),
            "--block",
            "r43=r40",
        ],
    )

    assert result.exit_code == 2
    assert "baseline pcdump has no hook events for fn_80000000" in result.stderr
