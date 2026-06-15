import json

from typer.testing import CliRunner

import src.cli.debug as debugcli
from src.mwcc_debug.order_target_derive import DeriveInputs
from src.search.directed.order_target import OrderTarget, Routing

runner = CliRunner()


def _directed_inputs():
    return DeriveInputs(
        function="mnDiagram_OnFrame", unit="melee/mn/mndiagram", class_id=0,
        checkdiff_primary="operand-register-or-offset",
        phys_target={28: 29, 29: 28}, phys_conflicts=[],
        force_iter_first=[46, 28, 29],
        applied_positions={46: 0, 28: 1, 29: 2},
        forced_class_clean=True,
        forced_ranks={46: 1, 28: 2, 29: 3},
        baseline_ig_set={46, 28, 29}, forced_ig_set={46, 28, 29},
        self_reanchored_roles={28, 29}, unscored_roles=[],
        forced_decisions_sha256=["h", "h"],
        baseline_source_sha256="s", baseline_pcdump_sha256="p",
        force_cap_exceeded=False,
    )


def _conflict_inputs():
    inp = _directed_inputs()
    inp.phys_conflicts = [{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}]
    return inp


def test_order_target_directed_writes_yaml_exit_0(tmp_path, monkeypatch):
    out = tmp_path / "OnFrame.yaml"
    monkeypatch.setattr(debugcli, "_collect_order_target_inputs",
                        lambda **kw: _directed_inputs())
    result = runner.invoke(debugcli.debug_app, [
        "target", "order-target", "-f", "mnDiagram_OnFrame",
        "-u", "melee/mn/mndiagram", "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    loaded = OrderTarget.load_yaml(out)
    assert loaded.routing == Routing.DIRECTED.value
    assert loaded.target_roles == [28, 29]
    assert loaded.order_target == {28: 2, 29: 3}


def test_order_target_not_order_class_exit_4_no_yaml(tmp_path, monkeypatch):
    out = tmp_path / "OnFrame.yaml"
    monkeypatch.setattr(debugcli, "_collect_order_target_inputs",
                        lambda **kw: _conflict_inputs())
    result = runner.invoke(debugcli.debug_app, [
        "target", "order-target", "-f", "mnDiagram_OnFrame",
        "-u", "melee/mn/mndiagram", "--out", str(out),
    ])
    assert result.exit_code == 4, result.output
    assert "not_order_class" in result.output
    assert not out.exists()


def test_order_target_json_emits_full_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(debugcli, "_collect_order_target_inputs",
                        lambda **kw: _directed_inputs())
    result = runner.invoke(debugcli.debug_app, [
        "target", "order-target", "-f", "mnDiagram_OnFrame",
        "-u", "melee/mn/mndiagram", "--json",
        "--out", str(tmp_path / "OnFrame.yaml"),
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["routing"] == "directed"
    assert payload["order_target"] == {"28": 2, "29": 3}
