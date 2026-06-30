"""Smoke test for `debug search run` CLI.

Uses --dry-compiler so no real mwcc/wibo/SSH is needed.
"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from pathlib import Path

from typer.testing import CliRunner

from src.search.cli import (
    _aggregate_directed_class_results,
    _classify_retained_case_c_simplify_order_validation,
    _combine_terminal_summary,
    _compute_melee_root,
    _duplicate_declaration_diagnostics,
    _manual_source_hunks,
    _parse_manual_range,
    _parse_directed_force_phys,
    _retained_case_c_target_live_range_repair_summary,
    _retained_window_candidate_summary,
    _resolve_expected_obj,
    _stack_array_node_set_terminal_proof,
    _summarize_transform_validations,
    search_app,
)


def test_compute_melee_root_points_at_repo_root() -> None:
    """Regression guard for the parents[N] off-by-one.

    The computed root must be the melee repo root (contains configure.py and
    src/melee), NOT an ancestor like tools/ — otherwise the non-dry CLI builds
    against tools/build/... and fails for every function.
    """
    root = _compute_melee_root()
    assert (root / "configure.py").exists(), f"no configure.py under {root}"
    assert (root / "src" / "melee").is_dir(), f"no src/melee under {root}"
    # The buggy parents[3] would land on tools/, which has neither marker.
    assert not (root / "melee-agent").exists(), (
        f"{root} looks like tools/, not the repo root"
    )


def test_compute_melee_root_prefers_current_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    worktree = tmp_path / "dirty-worktree"
    (worktree / "src" / "melee").mkdir(parents=True)
    (worktree / "configure.py").write_text("# test repo marker\n")
    nested = worktree / "tools" / "melee-agent"
    nested.mkdir(parents=True)

    monkeypatch.chdir(nested)

    assert _compute_melee_root() == worktree


def test_search_run_dry(tmp_path: Path) -> None:
    runner = CliRunner()
    seed = tmp_path / "seed.c"
    seed.write_text("int MatToQuat(){return 0;}")
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "MatToQuat",
            "--unit", "quatlib",
            "--no-remote",
            "--seed", str(seed),
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "accounting" in result.stdout.lower()


def test_search_run_accepts_named_seed_id(tmp_path: Path) -> None:
    runner = CliRunner()
    seed = tmp_path / "flag-bool.c"
    seed.write_text("int MatToQuat(){return 0;}")
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "MatToQuat",
            "--unit", "quatlib",
            "--no-remote",
            "--seed", f"flag_bool={seed}",
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["seed_candidates"] == [
        {
            "candidate_id": "flag_bool",
            "path": str(seed),
            "source_hash": summary["seed_candidates"][0]["source_hash"],
        }
    ]


def test_search_run_help_documents_directed_options() -> None:
    runner = CliRunner()
    result = runner.invoke(search_app, ["run", "--help"], env={"COLUMNS": "180"})

    assert result.exit_code == 0, result.output
    assert "--directed-force-phys" in result.stdout
    assert "--directed-from-diff" in result.stdout
    assert "--directed-class" in result.stdout
    assert "ID=path" in result.stdout


def test_search_structure_help() -> None:
    runner = CliRunner()
    result = runner.invoke(search_app, ["structure", "--help"], env={"COLUMNS": "180"})

    assert result.exit_code == 0, result.output
    assert "--axis" in result.stdout
    assert "statement-order" in result.stdout
    assert "source-lifetime" in result.stdout
    assert "inline-boundary" in result.stdout
    assert "--max-candidates" in result.stdout
    assert "--pure-helper" in result.stdout
    assert "--json" in result.stdout


def test_source_model_synthesis_help_documents_score_probe_options() -> None:
    runner = CliRunner()
    result = runner.invoke(
        search_app,
        ["source-model-synthesis", "--help"],
        env={"COLUMNS": "180"},
    )

    assert result.exit_code == 0, result.output
    assert "--score-json" in result.stdout
    assert "--write-probes" in result.stdout
    assert "--checkdiff-guard" in result.stdout
    assert "--continue-after-final-source-family" in result.stdout


def test_search_structure_json_uses_injected_runner(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.search import cli as search_cli
    from src.search.structure import AxisSummary, StructureVariant

    source = tmp_path / "demo.c"
    source.write_text("int fn_80000000(void) { return 0; }\n")

    def fake_run_structure_search(**kwargs):
        return {
            "function": kwargs["function"],
            "source": str(source),
            "generated_source_dir": str(tmp_path),
            "baseline_percent": 10.0,
            "axes": [AxisSummary("case-order", "evaluated", 1).to_dict()],
            "variants": [
                StructureVariant(
                    axis="case-order",
                    operator="case-order-adjacent-swap",
                    label="case-order-adjacent-swap-0",
                    status="ok",
                    baseline_percent=10.0,
                    match_percent=20.0,
                    final_match_percent=20.0,
                    delta=10.0,
                    source_retained=str(source),
                ).to_dict()
            ],
            "future_axes": [],
            "stop_condition": {
                "kind": "improved",
                "blocker": None,
                "reason": "test",
            },
        }

    monkeypatch.setattr(search_cli, "run_structure_search", fake_run_structure_search)

    result = CliRunner().invoke(
        search_app,
        [
            "structure",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["function"] == "fn_80000000"
    assert payload["variants"][0]["axis"] == "case-order"
    assert payload["stop_condition"]["kind"] == "improved"


def test_search_structure_scores_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.search import cli as search_cli

    source = tmp_path / "demo.c"
    source.write_text("int fn_80000000(void) { return 0; }\n")
    captured: dict = {}

    def fake_score_structure_variants(**kwargs):
        return []

    def fake_run_structure_search(**kwargs):
        captured.update(kwargs)
        return {
            "function": kwargs["function"],
            "source": str(source),
            "generated_source_dir": str(tmp_path),
            "baseline_percent": None,
            "axes": [],
            "variants": [],
            "future_axes": [],
            "stop_condition": {
                "kind": "no-improvement",
                "blocker": None,
                "reason": "test",
            },
        }

    monkeypatch.setattr(
        search_cli,
        "score_structure_variants",
        fake_score_structure_variants,
    )
    monkeypatch.setattr(search_cli, "run_structure_search", fake_run_structure_search)

    result = CliRunner().invoke(
        search_app,
        [
            "structure",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--score-timeout",
            "7.5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["score_variants"] is True
    assert callable(captured["score_runner"])


def test_search_structure_passes_pure_helper_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.search import cli as search_cli

    source = tmp_path / "demo.c"
    source.write_text("int fn_80000000(void) { return 0; }\n")
    captured: dict = {}

    def fake_run_structure_search(**kwargs):
        captured.update(kwargs)
        return {
            "function": kwargs["function"],
            "source": str(source),
            "generated_source_dir": str(tmp_path),
            "baseline_percent": None,
            "axes": [],
            "variants": [],
            "future_axes": [],
            "stop_condition": {
                "kind": "no-improvement",
                "blocker": None,
                "reason": "test",
            },
        }

    monkeypatch.setattr(search_cli, "run_structure_search", fake_run_structure_search)

    result = CliRunner().invoke(
        search_app,
        [
            "structure",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--pure-helper",
            "ExternalPure=u8",
            "--pure-helper",
            "OtherPure",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["read_only_helpers"] == {
        "ExternalPure": "u8",
        "OtherPure": "s32",
    }


def test_search_structure_passes_inline_boundary_baseline_classification(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.search import cli as search_cli

    source = tmp_path / "demo.c"
    source.write_text("int fn_80000000(void) { return 0; }\n")
    classification = {
        "primary": "inline-boundary-toolchain-artifact",
        "inline_boundary_artifact": {
            "missing_ref_calls": ["<fn_80000000+0x10>"],
        },
    }
    captured: dict = {}

    def fake_run_structure_search(**kwargs):
        captured.update(kwargs)
        return {
            "function": kwargs["function"],
            "source": str(source),
            "generated_source_dir": str(tmp_path),
            "baseline_percent": None,
            "axes": [],
            "variants": [],
            "future_axes": [],
            "stop_condition": {
                "kind": "no-improvement",
                "blocker": None,
                "reason": "test",
            },
        }

    monkeypatch.setattr(
        search_cli,
        "_structure_baseline_classification",
        lambda *, function, melee_root, timeout: classification,
    )
    monkeypatch.setattr(search_cli, "run_structure_search", fake_run_structure_search)

    result = CliRunner().invoke(
        search_app,
        [
            "structure",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--axis",
            "inline-boundary",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["baseline_classification"] == classification


def test_search_structure_no_score_disables_scorer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.search import cli as search_cli

    source = tmp_path / "demo.c"
    source.write_text("int fn_80000000(void) { return 0; }\n")
    captured: dict = {}

    def fake_run_structure_search(**kwargs):
        captured.update(kwargs)
        return {
            "function": kwargs["function"],
            "source": str(source),
            "generated_source_dir": str(tmp_path),
            "baseline_percent": None,
            "axes": [],
            "variants": [],
            "future_axes": [],
            "stop_condition": {
                "kind": "no-improvement",
                "blocker": None,
                "reason": "test",
            },
        }

    monkeypatch.setattr(search_cli, "run_structure_search", fake_run_structure_search)

    result = CliRunner().invoke(
        search_app,
        [
            "structure",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--no-score",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["score_variants"] is False
    assert captured["score_runner"] is None


def test_search_structure_text_renders_top_variant(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.search import cli as search_cli

    source = tmp_path / "demo.c"
    source.write_text("int fn_80000000(void) { return 0; }\n")

    def fake_run_structure_search(**kwargs):
        return {
            "function": "fn_80000000",
            "source": str(source),
            "generated_source_dir": str(tmp_path),
            "baseline_percent": 10.0,
            "axes": [
                {
                    "axis": "case-order",
                    "status": "evaluated",
                    "candidate_count": 1,
                }
            ],
            "variants": [
                {
                    "rank": 1,
                    "axis": "case-order",
                    "operator": "case-order-adjacent-swap",
                    "label": "case-order-adjacent-swap-0",
                    "status": "ok",
                    "final_match_percent": 20.0,
                    "delta": 10.0,
                    "source_retained": str(source),
                    "command": (
                        "melee-agent debug search structure -f fn_80000000 "
                        "--axis case-order"
                    ),
                }
            ],
            "future_axes": [],
            "stop_condition": {
                "kind": "improved",
                "blocker": None,
                "reason": "test",
            },
        }

    monkeypatch.setattr(search_cli, "run_structure_search", fake_run_structure_search)

    result = CliRunner().invoke(
        search_app,
        ["structure", "-f", "fn_80000000", "--source-file", str(source)],
    )

    assert result.exit_code == 0, result.output
    assert "structure search - fn_80000000" in result.stdout
    assert "case-order / case-order-adjacent-swap" in result.stdout
    assert "delta: +10.00000" in result.stdout


def _statement_order_source() -> str:
    return (
        "int fn_80000000(int seed, unsigned char* p)\n"
        "{\n"
        "    unsigned int size;\n"
        "    size = (size << 8) | p[3];\n"
        "    return size;\n"
        "}\n"
    )


def test_search_structure_statement_order_json_smoke(tmp_path: Path) -> None:
    source = tmp_path / "demo.c"
    source.write_text(_statement_order_source())

    result = CliRunner().invoke(
        search_app,
        [
            "structure",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--axis",
            "statement-order",
            "--output-dir",
            str(tmp_path / "structure"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    axes = {axis["axis"]: axis for axis in payload["axes"]}
    assert axes["statement-order"]["status"] == "evaluated"
    assert payload["variants"][0]["axis"] == "statement-order"
    assert payload["variants"][0]["operator"] == "statement-order-split-shift-or"
    assert Path(payload["variants"][0]["source_retained"]).exists()
    assert payload["stop_condition"]["kind"] == "candidates-generated"


def test_search_structure_statement_order_text_smoke(tmp_path: Path) -> None:
    source = tmp_path / "demo.c"
    source.write_text(_statement_order_source())

    result = CliRunner().invoke(
        search_app,
        [
            "structure",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--axis",
            "statement-order",
            "--output-dir",
            str(tmp_path / "structure"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "axes: statement-order=evaluated" in result.stdout
    assert "statement-order / statement-order-split-shift-or" in result.stdout
    assert "source:" in result.stdout
    assert "stop condition: candidates-generated" in result.stdout


def test_search_plan_transforms_outputs_corpus_plan_and_probes(tmp_path: Path) -> None:
    source = tmp_path / "e7b4.c"
    source.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    if (flag) {\n"
        "        reload = 1;\n"
        "    } else {\n"
        "        if (kind != 0) {\n"
        "            reload = 0;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftcommon",
            "--force-phys", "58:4,35:29",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["plan"]["function"] == "ftCo_8009E7B4"
    assert "condition_split_merge" in {
        family["family_id"] for family in payload["plan"]["families"]
    }
    assert payload["probes"]
    assert payload["probes"][0]["candidate_path"] is None


def test_search_plan_transforms_reports_zero_probe_family_diagnostics(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef float f32;\n"
        "typedef struct HSD_JObj HSD_JObj;\n"
        "void mnDiagram_DrawCellNumber(void) {\n"
        "    f32 alpha;\n"
        "    f32 beta;\n"
        "    f32 gamma;\n"
        "    HSD_JObj* jobj;\n"
        "    use(jobj, alpha, beta, gamma);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_DrawCellNumber",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:32:28,1:33:26",
            "--source-file", str(source),
            "--max-per-family", "4",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["source_resolution"]["status"] == "resolved"
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    assert set(diagnostics) == {
        "pcode_only_fpr_fsubs_cast_owner_repair",
        "pcode_only_fpr_callarg_temp_repair",
        "coupled_fpr_coalesce_product_repair",
        "mixed_pcode_fpr_lifetime_pressure_repair",
        "callarg_local_structural_repair",
        "coloring_register_steering",
        "indexed_byte_address_temp_steering",
    }
    assert diagnostics["coloring_register_steering"]["materialized_count"] > 0
    for family_id in (
        "pcode_only_fpr_fsubs_cast_owner_repair",
        "pcode_only_fpr_callarg_temp_repair",
        "coupled_fpr_coalesce_product_repair",
        "mixed_pcode_fpr_lifetime_pressure_repair",
        "callarg_local_structural_repair",
    ):
        item = diagnostics[family_id]
        assert item["attempted"] is True
        assert item["materialized_count"] == 0
        assert item["no_probe_reason"] == "source-pattern-not-found"
        assert item["matcher_diagnostics"]

    indexed = diagnostics["indexed_byte_address_temp_steering"]
    assert indexed["attempted"] is False
    assert indexed["attempt_status"] == "skipped"
    assert indexed["materialized_count"] == 0
    assert indexed["no_probe_reason"] == "class-mismatch"
    assert indexed["matcher_diagnostics"]["requested_force_class"] == 1


def test_search_plan_transforms_recovers_retained_pcode_callarg_shape(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(HSD_JObj* jobj, HSD_JObj* joint, u8 digit) {\n"
        "    f32 base;\n"
        "    base = (f32) digit;\n"
        "    jobj = HSD_JObjLoadJoint(joint);\n"
        "    HSD_JObjAddAnimAll(jobj, a, b, c);\n"
        "    HSD_JObjReqAnimAll(jobj, base);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_DrawCellNumber",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:35:26",
            "--source-file", str(source),
            "--transform-family", "pcode_only_fpr_callarg_temp_repair",
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    callarg = diagnostics["pcode_only_fpr_callarg_temp_repair"]
    matcher = callarg["matcher_diagnostics"]
    assert callarg["materialized_count"] > 0
    assert callarg["no_probe_reason"] is None
    assert matcher["hsd_jobj_req_anim_all_calls"] == 1
    assert matcher["accepted_fpr_callarg_conversions"] == 1
    assert matcher["accepted_anchor_count"] > 0
    assert matcher["call_arg_locals"] == ["base"]
    assert matcher["call_arg_operands"] == ["digit"]


def test_search_plan_transforms_reports_pcode_fsubs_cast_owner_counts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(int col, f32 row_offset) {\n"
        "    f32 col_cast_owner_fpr;\n"
        "    f32 row_offset_adj;\n"
        "    col_cast_owner_fpr = (f32) col;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    use(col_cast_owner_fpr, row_offset_adj);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_DrawCellNumber",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:33:26,1:34:26",
            "--source-file", str(source),
            "--transform-family", "pcode_only_fpr_fsubs_cast_owner_repair",
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    fsubs = diagnostics["pcode_only_fpr_fsubs_cast_owner_repair"]
    matcher = fsubs["matcher_diagnostics"]
    assert fsubs["materialized_count"] > 0
    assert matcher["standalone_fpr_cast_owner_assignments"] == 1
    assert matcher["standalone_fpr_subtraction_assignments"] == 1
    assert matcher["accepted_anchor_count"] > 0
    assert sorted(matcher["owner_locals"]) == [
        "col_cast_owner_fpr",
        "row_offset_adj",
    ]


def test_plan_transforms_draw_fpr_select_order_writes_target_live_range_probes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef float f32;\n"
        "typedef struct HSD_JObj HSD_JObj;\n"
        "void HSD_JObjSetTranslateX(HSD_JObj*, f32);\n"
        "void HSD_JObjSetTranslateY(HSD_JObj*, f32);\n"
        "void mnDiagram_DrawCellNumber(HSD_JObj* jobj, int col, f32 row_offset) {\n"
        "    f32 col_offset_product_fpr;\n"
        "    f32 col_offset;\n"
        "    f32 row_offset_adj;\n"
        "    col_offset_product_fpr = (f32) col * 10.0f;\n"
        "    col_offset = col_offset_product_fpr;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    HSD_JObjSetTranslateX(jobj, col_offset);\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset_adj);\n"
        "}\n"
    )
    select_order = tmp_path / "draw_select_order.json"
    select_order.write_text(json.dumps({
        "function": "mnDiagram_DrawCellNumber",
        "window_order_fallback": {"leads": []},
        "window_order_source_attributions": {},
    }))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_DrawCellNumber",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:37:26,1:32:26",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_fpr_case_c_target_live_range_repair",
            "--write-probes", str(probes_dir),
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    repair = diagnostics["retained_fpr_case_c_target_live_range_repair"]
    assert repair["materialized_count"] >= 2
    assert repair["matcher_diagnostics"]["emitted_repair_probe_count"] >= 2
    summary = payload["retained_case_c_target_live_range_repair_summary"]
    assert summary["status"] == "materialized-not-scored"
    assert summary["attempted_targets"] == {"37": 26}
    assert summary["protected_targets"] == {"32": 26}
    source_expressions = {
        probe["payload"]["ranked_repair_candidate"]["source_expression"]
        for probe in payload["probes"]
        if probe["family_id"] == "retained_fpr_case_c_target_live_range_repair"
    }
    assert {"row_offset_adj", "row_offset - 0.4f"} <= source_expressions
    probe_kinds = {
        probe["payload"]["source_probe_provenance_kind"]
        for probe in payload["probes"]
        if probe["family_id"] == "retained_fpr_case_c_target_live_range_repair"
    }
    assert {
        "target-aware-scalar-interference-shape",
        "target-aware-scalar-pair-overlap",
    } <= probe_kinds
    assert any(
        "target_repair_live_range_ig37_probe = row_offset_adj;"
        in path.read_text()
        for path in probes_dir.glob("*.c")
    )
    scalar_probe_text = "\n".join(
        path.read_text() for path in probes_dir.glob("*.c")
    )
    assert "target_repair_scalar_duplicate_ig37_probe" in scalar_probe_text
    assert "target_repair_scalar_pair_ig32_probe = col_offset;" in scalar_probe_text
    assert "target_repair_scalar_pair_ig37_probe = row_offset_adj;" in (
        scalar_probe_text
    )
    col_offset_probe_text = "\n".join(path.read_text() for path in probes_dir.glob("*.c"))
    assert "target_repair_live_range_ig32_probe = col_offset;" in col_offset_probe_text
    assert (
        "HSD_JObjSetTranslateX(jobj, target_repair_live_range_ig32_probe);"
        in col_offset_probe_text
    )
    assert "target_repair_live_range_ig32_probe_product_fpr" not in col_offset_probe_text


def _write_current_owner_exhaustion(path: Path, spans: list[dict], *, attempted: dict, protected: dict) -> None:
    path.write_text(json.dumps({
        "retained_case_c_target_live_range_repair_summary": {
            "status": "blocked",
            "attempted_targets": attempted,
            "protected_targets": protected,
            "source_owner_terminal_spans": spans,
        },
    }))


def test_plan_transforms_draw_fpr_alternate_source_owner_after_current_owner_exhaustion(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef float f32;\n"
        "typedef struct HSD_JObj HSD_JObj;\n"
        "void HSD_JObjSetTranslateX(HSD_JObj*, f32);\n"
        "void HSD_JObjSetTranslateY(HSD_JObj*, f32);\n"
        "void mnDiagram_DrawCellNumber(HSD_JObj* jobj, int row, int col, f32 y_spacing) {\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 col_offset;\n"
        "    f32 row_offset_adj;\n"
        "    rowf = (f32) row;\n"
        "    row_offset = y_spacing;\n"
        "    row_offset *= rowf;\n"
        "    col_offset = y_spacing * (f32) col;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    HSD_JObjSetTranslateX(jobj, col_offset);\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset_adj);\n"
        "}\n"
    )
    exhaustion = tmp_path / "current_owner.json"
    current_spans = [
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_fpr_case_c_target_live_range_repair",
            "target_ig": 37,
            "target_phys": 26,
            "interferer_ig": 37,
            "interferer_phys": 26,
            "source_expression": "row_offset_adj",
            "paired_source_expression": "col_offset",
            "source_type": "f32",
            "status": "materialized",
            "source_owner_status": "current-source-owner-probes-exhausted",
            "next_source_owner_status": "not-discovered",
        },
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_fpr_case_c_target_live_range_repair",
            "target_ig": 37,
            "target_phys": 26,
            "interferer_ig": 37,
            "interferer_phys": 26,
            "source_expression": "row_offset - 0.4f",
            "source_type": "f32",
            "status": "materialized",
            "source_owner_status": "current-source-owner-probes-exhausted",
            "next_source_owner_status": "not-discovered",
        },
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_fpr_case_c_target_live_range_repair",
            "target_ig": 37,
            "target_phys": 26,
            "interferer_ig": 32,
            "interferer_phys": 26,
            "source_expression": "col_offset",
            "source_type": "f32",
            "status": "materialized",
            "source_owner_status": "current-source-owner-probes-exhausted",
            "next_source_owner_status": "not-discovered",
        },
    ]
    _write_current_owner_exhaustion(
        exhaustion,
        current_spans,
        attempted={"37": 26},
        protected={"32": 26},
    )
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_DrawCellNumber",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:37:26,1:32:26",
            "--source-file", str(source),
            "--current-owner-exhaustion-json", str(exhaustion),
            "--transform-family", "retained_case_c_alternate_source_owner_discovery",
            "--write-probes", str(probes_dir),
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    family = diagnostics["retained_case_c_alternate_source_owner_discovery"]
    matcher = family["matcher_diagnostics"]
    assert matcher["status"] == "materialized"
    assert set(matcher["excluded_current_owner_expressions"]) == {
        "row_offset_adj",
        "row_offset - 0.4f",
        "col_offset",
    }
    ranked = {
        item["source_expression"]
        for item in matcher["ranked_alternate_owner_candidates"]
    }
    assert {"row_offset", "rowf"} <= ranked
    assert "y_spacing" in ranked or "(f32) row" in ranked
    emitted = {
        probe["payload"]["ranked_repair_candidate"]["source_expression"]
        for probe in payload["probes"]
        if probe["family_id"] == "retained_case_c_alternate_source_owner_discovery"
    }
    assert emitted
    assert not emitted & {"row_offset_adj", "row_offset - 0.4f", "col_offset"}
    written_text = "\n".join(path.read_text() for path in probes_dir.glob("*.c"))
    assert (
        "target_repair_live_range_ig37_probe = row_offset;" in written_text
        or "target_repair_live_range_ig37_probe = rowf;" in written_text
    )
    summary = payload["retained_case_c_target_live_range_repair_summary"]
    assert {
        span["next_source_owner_status"]
        for span in summary["source_owner_terminal_spans"]
    } == {"materialized"}
    assert all(
        span.get("alternate_source_owner_probe_labels")
        for span in summary["source_owner_terminal_spans"]
    )


def test_plan_transforms_draw_fpr_alternate_source_owner_terminal_proof(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef float f32;\n"
        "typedef struct HSD_JObj HSD_JObj;\n"
        "void HSD_JObjSetTranslateY(HSD_JObj*, f32);\n"
        "void mnDiagram_DrawCellNumber(HSD_JObj* jobj) {\n"
        "    f32 row_offset_adj;\n"
        "    row_offset_adj = 1.0f;\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset_adj);\n"
        "}\n"
    )
    exhaustion = tmp_path / "current_owner.json"
    _write_current_owner_exhaustion(
        exhaustion,
        [
            {
                "kind": "target-live-range-source-owner-terminal",
                "family_id": "retained_fpr_case_c_target_live_range_repair",
                "target_ig": 37,
                "target_phys": 26,
                "interferer_ig": 37,
                "interferer_phys": 26,
                "source_expression": "row_offset_adj",
                "source_type": "f32",
                "status": "materialized",
                "source_owner_status": "current-source-owner-probes-exhausted",
                "next_source_owner_status": "not-discovered",
            },
        ],
        attempted={"37": 26},
        protected={"32": 26},
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_DrawCellNumber",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:37:26,1:32:26",
            "--source-file", str(source),
            "--current-owner-exhaustion-json", str(exhaustion),
            "--transform-family", "retained_case_c_alternate_source_owner_discovery",
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    family = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }["retained_case_c_alternate_source_owner_discovery"]
    matcher = family["matcher_diagnostics"]
    assert family["materialized_count"] == 0
    assert matcher["terminal_blocker"] == "next-source-owner-exhausted"
    assert matcher["inspected_owner_nodes"]
    assert all(
        node["status"] == "rejected" and node.get("reason")
        for node in matcher["inspected_owner_nodes"]
    )
    span = matcher["current_owner_span_updates"][0]
    assert span["next_source_owner_status"] == "terminal-next-source-owner-exhausted"


def test_search_plan_transforms_reports_gpr_address_temp_counts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "void mnDiagram_SortNamesByKOs(void) {\n"
        "    u32 sorted_names_base_probe_probe;\n"
        "    u32 totals[0x78];\n"
        "    int sorted_names_totals_idx_probe;\n"
        "    u8* sorted_names_base_probe;\n"
        "    int window_order_mnDiagram_804A076C_sorted_names_index_probe;\n"
        "    int max_idx;\n"
        "    int j;\n"
        "    max_idx = 0;\n"
        "    j = 1;\n"
        "    sorted_names_totals_idx_probe = mnDiagram_804A076C.sorted_names[(max_idx)];\n"
        "    window_order_mnDiagram_804A076C_sorted_names_index_probe = j;\n"
        "    sorted_names_base_probe = mnDiagram_804A076C.sorted_names;\n"
        "    sorted_names_base_probe_probe = sorted_names_base_probe[window_order_mnDiagram_804A076C_sorted_names_index_probe];\n"
        "    use(sorted_names_totals_idx_probe, sorted_names_base_probe_probe);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--transform-family", "pcode_only_gpr_address_temp_repair",
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    gpr = diagnostics["pcode_only_gpr_address_temp_repair"]
    matcher = gpr["matcher_diagnostics"]
    assert gpr["attempted"] is True
    assert gpr["materialized_count"] > 0
    assert gpr["no_probe_reason"] is None
    assert matcher["indexed_gpr_address_expressions"] >= 2
    assert matcher["pointer_copy_owner_chains"] == 1
    assert matcher["accepted_anchor_count"] > 0
    assert sorted(matcher["base_locals"]) == ["sorted_names_base_probe"]
    assert sorted(matcher["index_exprs"]) == [
        "(max_idx)",
        "window_order_mnDiagram_804A076C_sorted_names_index_probe",
    ]


def test_search_plan_transforms_reports_gpr_copy_product_case_c_counts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "struct Assets { u8 sorted_names[0x78]; };\n"
        "extern struct Assets mnDiagram_804A076C;\n"
        "void mnDiagram_SortNamesByKOs(void) {\n"
        "    u32 totals[0x78];\n"
        "    u8* dst_iter;\n"
        "    u8* dst = mnDiagram_804A076C.sorted_names;\n"
        "    int i;\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    dst_iter = dst;\n"
        "    {\n"
        "        u8* ll_probe_iter_0_source_34_0 = mnDiagram_804A076C.sorted_names;\n"
        "        u8* ll_probe_iter_0 = ll_probe_iter_0_source_34_0;\n"
        "        for (i = 0; i < 0x78; i++, ll_probe_iter_0++) {\n"
        "            max_idx = i;\n"
        "            for (j = i + 1; j < 0x78; j++) {\n"
        "                use(totals[mnDiagram_804A076C.sorted_names[max_idx]]);\n"
        "            }\n"
        "            if (max_idx != i) {\n"
        "                u8 temp = mnDiagram_804A076C.sorted_names[max_idx];\n"
        "                *ll_probe_iter_0 = temp;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--transform-family", "pcode_only_gpr_copy_product_case_c_repair",
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    family = diagnostics["pcode_only_gpr_copy_product_case_c_repair"]
    matcher = family["matcher_diagnostics"]
    assert family["attempted"] is True
    assert family["materialized_count"] > 0
    assert family["no_probe_reason"] is None
    assert matcher["case_c_copy_product_pairs"] == 1
    assert matcher["accepted_anchor_count"] > 0
    assert matcher["low_confidence_pointer_locals"] == ["dst_iter"]
    assert {
        "gpr-case-c-output-owner-copy-before-loop",
        "gpr-case-c-store-owner-temp",
    } <= set(matcher["generated_strategies"])
    assert all(probe["payload"].get("source_hunks") for probe in payload["probes"])
    assert all(
        "GPR indexed address temp" not in "\n".join(
            probe["payload"].get("source_regions", [])
        )
        for probe in payload["probes"]
    )


def test_search_plan_transforms_reports_retained_gpr_case_c_sensitivity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "struct Assets { u8 sorted_names[0x78]; };\n"
        "extern struct Assets mnDiagram_804A076C;\n"
        "void mnDiagram_SortNamesByKOs(void) {\n"
        "    u32 totals[0x78];\n"
        "    u8* dst_iter;\n"
        "    u8* dst = mnDiagram_804A076C.sorted_names;\n"
        "    int i;\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    dst_iter = dst;\n"
        "    {\n"
        "        u8* ll_probe_iter_0_source_34_0 = mnDiagram_804A076C.sorted_names;\n"
        "        u8* ll_probe_iter_0 = ll_probe_iter_0_source_34_0;\n"
        "        for (i = 0; i < 0x78; i++, ll_probe_iter_0++) {\n"
        "            max_idx = i;\n"
        "            for (j = i + 1; j < 0x78; j++) {\n"
        "                use(totals[mnDiagram_804A076C.sorted_names[max_idx]]);\n"
        "            }\n"
        "            if (max_idx != i) {\n"
        "                u8 temp = mnDiagram_804A076C.sorted_names[max_idx];\n"
        "                *ll_probe_iter_0 = temp;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--transform-family", "retained_gpr_case_c_sensitivity_search",
            "--max-per-family", "8",
            "--write-probes", str(tmp_path / "probes"),
            "--validate-command",
            (
                f"{sys.executable} -c \"import json; "
                "print(json.dumps({'target_score': {'total': 120.0, "
                "'matched': 0, 'targeted': 2, 'virtual_distance': 2, "
                "'virtuals': {'34': {'expected': 27, 'actual': 29, "
                "'matched': False}, '44': {'expected': 25, 'actual': 27, "
                "'matched': False}}}}))\" {{candidate_path}}"
            ),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    family = diagnostics["retained_gpr_case_c_sensitivity_search"]
    matcher = family["matcher_diagnostics"]
    assert family["attempted"] is True
    assert family["materialized_count"] >= 3
    assert matcher["case_c_copy_product_pairs"] == 1
    assert matcher["low_confidence_pointer_locals"] == ["dst_iter"]
    assert {
        "retained-gpr-case-c-store-through-low-confidence-local",
        "retained-gpr-case-c-loop-through-low-confidence-local",
        "retained-gpr-case-c-owner-init-bridge",
    } <= set(matcher["generated_strategies"])
    assert all(
        probe["payload"].get("first_divergence_objective", {}).get("case") == "C"
        for probe in payload["probes"]
    )
    summary = payload["validation_summary"]
    assert summary["stop_condition"] == "exhausted-negative-evidence"
    assert "exhausted-retained-gpr-case-c-sensitivity-search" in summary[
        "terminal_blockers"
    ]
    retained_summary = summary["retained_case_c_sensitivity_summary"]
    assert retained_summary["stop_condition_met"] is False
    assert retained_summary["ranked_by"] == [
        "target_score.virtuals",
        "first_divergence_movement",
    ]
    assert retained_summary["best_target_score"]["target_score"]["matched"] == 0


def test_bool_mask_validation_summary_terminalizes_no_hit_results() -> None:
    probe_payloads = [
        {
            "probe_id": "pcode_only_gpr_bool_mask_temp_repair@0",
            "family_id": "pcode_only_gpr_bool_mask_temp_repair",
            "payload": {
                "strategy": "gpr-bool-mask-predicate-temp",
                "source_regions": ("GPR bool/mask predicate: if (inputs & 1)",),
                "source_hunks": [
                    {
                        "kind": "gpr-bool-mask-temp-repair",
                        "strategy": "gpr-bool-mask-predicate-temp",
                        "base_start": 10,
                        "removed": ["    if (inputs & 1) {"],
                        "added": [
                            "    u64 inputs_mask_1_gpr;",
                            "    inputs_mask_1_gpr = inputs & 1;",
                            "    if (inputs_mask_1_gpr) {",
                        ],
                    }
                ],
                "force_phys_targets": {"112": 5},
                "attempted_targets": {"112": 5},
            },
        }
    ]
    validation_results = [
        {
            "probe_id": "pcode_only_gpr_bool_mask_temp_repair@0",
            "family_id": "pcode_only_gpr_bool_mask_temp_repair",
            "outcome": "negative-evidence",
            "validator_payload": {
                "source_retained": "/tmp/probe.c",
                "pcdump_path": "/tmp/probe.pcdump",
                "target_score": {
                    "matched": 0,
                    "targeted": 1,
                    "virtual_distance": 3,
                    "virtuals": {"112": {"actual": 8, "expected": 5}},
                },
            },
        }
    ]

    summary = _summarize_transform_validations(probe_payloads, validation_results)

    proof = summary["pcode_only_gpr_bool_mask_temp_repair_summary"]
    assert summary["terminal_proof"] == proof
    assert "exhausted-pcode-only-gpr-bool-mask-temp-repair" in summary[
        "terminal_blockers"
    ]
    assert proof["status"] == "terminal-blocked"
    assert proof["terminal_blocker"] == "all-candidates-no-target-hit"
    assert proof["source_level_handoff"].startswith(
        "Bind or reschedule the remaining GPR bool/mask source expression"
    )
    assert proof["best_retained_candidates"][0]["source_hunks"]
    assert proof["best_retained_candidates"][0]["pcdump_path"] == "/tmp/probe.pcdump"


def test_bool_mask_validation_summary_keeps_unscored_family_nonterminal() -> None:
    probe_payloads = [
        {
            "probe_id": "pcode_only_gpr_bool_mask_temp_repair@0",
            "family_id": "pcode_only_gpr_bool_mask_temp_repair",
            "payload": {
                "strategy": "jobj-translate-dirty-wrapper-call",
                "source_regions": (
                    "JObj translate dirty-wrapper call: "
                    "HSD_JObjSetTranslateX(jobj, x);"
                ),
                "source_hunks": [
                    {
                        "kind": "gpr-bool-mask-temp-repair",
                        "strategy": "jobj-translate-dirty-wrapper-call",
                        "base_start": 20,
                    }
                ],
            },
        }
    ]
    validation_results = [
        {
            "probe_id": "other_family@0",
            "family_id": "other_family",
            "outcome": "negative-evidence",
        }
    ]

    summary = _summarize_transform_validations(probe_payloads, validation_results)

    proof = summary["pcode_only_gpr_bool_mask_temp_repair_summary"]
    assert proof["status"] == "materialized-not-scored"
    assert proof["evaluated_probe_count"] == 0
    assert "terminal_proof" not in summary
    assert "exhausted-pcode-only-gpr-bool-mask-temp-repair" not in summary.get(
        "terminal_blockers", []
    )


def _retained_window_order_source() -> str:
    return (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "void* GetNameText(u8 value);\n"
        "void mnDiagram_SortNamesByKOs(u8* sorted_names, u32* totals, "
        "int max_idx, int j) {\n"
        "    if ((GetNameText(sorted_names[j]) != 0) &&\n"
        "        (totals[sorted_names[max_idx]] < totals[sorted_names[j]])) {\n"
        "        max_idx = j;\n"
        "    }\n"
        "}\n"
    )


def _retained_post_source_owner_source() -> str:
    return (
        "typedef unsigned char u8;\n"
        "void sink(u8 value);\n"
        "void mnDiagram_SortNamesByKOs(u8* sorted_names, int max_idx, int j) {\n"
        "    u8 current;\n"
        "    u8 alternate;\n"
        "    current = sorted_names[max_idx];\n"
        "    alternate = sorted_names[j];\n"
        "    sink(current);\n"
        "    sink(alternate);\n"
        "}\n"
    )


def _retained_post_source_owner_single_source() -> str:
    return (
        "typedef unsigned char u8;\n"
        "void sink(u8 value);\n"
        "void mnDiagram_SortNamesByKOs(u8* sorted_names, int max_idx) {\n"
        "    u8 current;\n"
        "    current = sorted_names[max_idx];\n"
        "    sink(current);\n"
        "}\n"
    )


def _retained_window_select_order_payload() -> dict:
    return {
        "window_order_fallback": {
            "ran": True,
            "leads": [{
                "target_ig": 44,
                "order_move": ["before", "force-phys"],
                "perturbed_reg": 25,
            }],
        },
        "window_order_source_attributions": {
            "44": {"kind": "implicit-temp", "expression": "addi r44,r50,28"},
            "50": {
                "kind": "copy/coalesce-product",
                "expression": "mr r50,r52",
                "base_virtual": 52,
            },
        },
        "window_order_probe_diagnostics": {"listed_source_probes": 1},
    }


def _retained_window_select_order_payload_with_ig34_copy_product() -> dict:
    payload = _retained_window_select_order_payload()
    payload["window_order_fallback"] = {
        "ran": True,
        "leads": [{
            "target_ig": 34,
            "order_move": ["after", 32],
            "perturbed_reg": 27,
        }],
    }
    payload["window_order_source_attributions"] = {
        "34": {
            "kind": "copy/coalesce-product",
            "expression": "mr r34,r44",
            "base_virtual": 44,
        },
        "44": {"kind": "implicit-temp", "expression": "addi r44,r50,28"},
        "50": {
            "kind": "copy/coalesce-product",
            "expression": "mr r50,r52",
            "base_virtual": 52,
        },
    }
    return payload


def _retained_window_select_order_payload_with_ig34_end_pointer() -> dict:
    return {
        "window_order_fallback": {
            "ran": True,
            "leads": [{
                "target_ig": 34,
                "order_move": ["before", "force-phys"],
                "perturbed_reg": 27,
            }],
        },
        "window_order_source_attributions": {
            "34": {
                "kind": "implicit-temp",
                "expression": "addi r34,r40,120",
            },
            "40": {
                "kind": "implicit-temp",
                "expression": "addi r40,r51,28",
            },
        },
        "window_order_probe_diagnostics": {"listed_source_probes": 1},
    }


def _retained_window_order_end_pointer_source() -> str:
    return (
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, u8* common_source_r39_probe) {\n"
        "    int i;\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = common_source_r39_probe;\n"
        "        u8* ll_probe_end_0 = dst + 0x78;\n"
        "        for (i = 0; ll_probe_iter_0 < ll_probe_end_0; i++, ll_probe_iter_0++) {\n"
        "            *ll_probe_iter_0 = dst[i];\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _target_live_range_repair_goal() -> dict:
    return {
        "kind": "target-aware-live-range-interference",
        "target_ig": 44,
        "target_phys": 25,
        "protected_targets": {"34": 27},
        "interferer_ig": 39,
        "interferer_phys": 25,
        "source_expression": "sorted_names[j]",
        "required_delta": 6,
    }


def _sort_target_live_range_repair_goals(payload: dict) -> list[dict]:
    return [
        probe["payload"]["repair_goal"]
        for probe in payload["probes"]
        if probe["family_id"] == "retained_gpr_case_c_target_live_range_repair"
        and isinstance(probe.get("payload"), dict)
        and isinstance(probe["payload"].get("repair_goal"), dict)
    ]


def _assert_sort_target_live_range_uses_local_source_expressions(
    payload: dict,
) -> None:
    repair_goals = _sort_target_live_range_repair_goals(payload)
    assert repair_goals
    assert {goal.get("source_expression") for goal in repair_goals} == {
        "sorted_names[j]"
    }
    assert {goal.get("address_source_expression") for goal in repair_goals} == {
        "sorted_names[(max_idx)]"
    }


def _virtual_explain_blocker_chain_payload(function="mnDiagram_SortNamesByKOs") -> dict:
    return {
        "function": function,
        "virtuals": [
            {
                "virtual": 34,
                "ig_idx": 34,
                "assigned_reg": 29,
                "live_range": [30, 92],
                "interferers": [
                    {
                        "virtual": 44,
                        "assigned_reg": 27,
                        "source": {
                            "kind": "implicit-temp",
                            "expression": "add r44,r52,r64",
                        },
                    },
                    {"virtual": 41, "assigned_reg": 25},
                ],
            },
            {
                "virtual": 44,
                "ig_idx": 44,
                "assigned_reg": 27,
                "live_range": [41, 55],
                "source": {
                    "kind": "implicit-temp",
                    "expression": "add r44,r52,r64",
                },
                "interferers": [
                    {
                        "virtual": 41,
                        "assigned_reg": 25,
                        "source": {
                            "kind": "implicit-temp",
                            "expression": "rlwinm r41,r45,0,24,31",
                        },
                    },
                    {"virtual": 34, "assigned_reg": 29},
                ],
            },
            {
                "virtual": 41,
                "ig_idx": 41,
                "assigned_reg": 25,
                "live_range": [42, 50],
                "source": {
                    "kind": "implicit-temp",
                    "expression": "rlwinm r41,r45,0,24,31",
                },
                "interferers": [
                    {"virtual": 34, "assigned_reg": 29},
                    {"virtual": 44, "assigned_reg": 27},
                ],
            },
        ],
    }


def _virtual_explain_blocker_chain_operand_payload(
    function="mnDiagram_SortNamesByKOs",
) -> dict:
    payload = _virtual_explain_blocker_chain_payload(function=function)
    payload["virtuals"].extend([
        {
            "virtual": 52,
            "ig_idx": 52,
            "assigned_reg": 24,
            "live_range": [40, 53],
            "source": {
                "kind": "local",
                "expression": "case_c_max_idx_probe",
                "type": "int",
                "confidence": "source-owner",
            },
        },
        {
            "virtual": 64,
            "ig_idx": 64,
            "assigned_reg": 28,
            "live_range": [40, 54],
            "source": {
                "kind": "local",
                "expression": "sorted_names_totals_idx_probe_2",
                "type": "u8",
                "confidence": "source-owner",
            },
        },
        {
            "virtual": 45,
            "ig_idx": 45,
            "assigned_reg": 26,
            "live_range": [41, 50],
            "source": {
                "kind": "local",
                "expression": (
                    "window_order_mnDiagram_804A076C_sorted_names_index_probe"
                ),
                "type": "int",
                "confidence": "source-owner",
            },
        },
    ])
    return payload


def _retained_window_select_order_payload_with_repair_goal() -> dict:
    payload = _retained_window_select_order_payload()
    payload["retained_case_c_repair_goals"] = [_target_live_range_repair_goal()]
    return payload


def _retained_window_select_order_payload_with_simplify_order_goal() -> dict:
    payload = _retained_window_select_order_payload()
    payload["retained_case_c_simplify_order_goals"] = [{
        "kind": "retained-case-c-simplify-order",
        "target_ig": 44,
        "target_phys": 25,
        "protected_targets": {"34": 27},
        "baseline_first_divergence": {
            "class_id": 0,
            "iter": 40,
            "ig_idx": 44,
            "case": "C",
        },
    }]
    return payload


def _retained_lower_drift_residual_source() -> str:
    return (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "void* GetNameText(u8 value);\n"
        "struct Names { u8 sorted_names[0x78]; };\n"
        "extern struct Names mnDiagram_804A076C;\n"
        "void mnDiagram_SortNamesByKOs(u32* totals) {\n"
        "    int case_c_max_idx_probe;\n"
        "    u32 sorted_names_base_probe_probe;\n"
        "    int sorted_names_totals_idx_probe;\n"
        "    u8* sorted_names_base_probe;\n"
        "    int sorted_names_totals_idx_probe_2;\n"
        "    int window_order_mnDiagram_804A076C_sorted_names_index_probe;\n"
        "    int i;\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    u8* dst_iter;\n"
        "    for (i = 0; i < 0x78; i++, dst_iter++) {\n"
        "        max_idx = i;\n"
        "        for (j = i + 1; j < 0x78; j++) {\n"
        "            case_c_max_idx_probe = max_idx;\n"
        "            sorted_names_totals_idx_probe = mnDiagram_804A076C.sorted_names[case_c_max_idx_probe];\n"
        "            sorted_names_totals_idx_probe_2 = mnDiagram_804A076C.sorted_names[j];\n"
        "            window_order_mnDiagram_804A076C_sorted_names_index_probe = j;\n"
        "            sorted_names_base_probe = mnDiagram_804A076C.sorted_names;\n"
        "            sorted_names_base_probe_probe = sorted_names_base_probe[window_order_mnDiagram_804A076C_sorted_names_index_probe];\n"
        "            if ((GetNameText(sorted_names_base_probe_probe) != 0) &&\n"
        "                ((totals[sorted_names_totals_idx_probe] < totals[sorted_names_totals_idx_probe_2]) ||\n"
        "                 ((GetNameText((0, mnDiagram_804A076C.sorted_names[case_c_max_idx_probe])) == 0) &&\n"
        "                  (GetNameText(mnDiagram_804A076C.sorted_names[(0, j)]) != 0)))) {\n"
        "                max_idx = j;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _retained_window_select_order_payload_with_ig34_residual_goal() -> dict:
    payload = _retained_window_select_order_payload()
    payload["retained_case_c_lower_drift_residual"] = {
        "kind": "retained-case-c-lower-drift-residual",
        "target_ig": 34,
        "target_phys": 27,
        "protected_targets": {"44": 26},
        "final_force_phys": {"34": 27, "44": 25},
        "baseline_pcdump_path": "build/diag/max_index_alias.pcdump.txt",
        "baseline_first_divergence": {
            "class_id": 0,
            "iter": 3,
            "ig_idx": 34,
            "case": "C",
        },
        "baseline_score": {
            "34": {"expected": 27, "actual": 28},
            "44": {"expected": 25, "actual": 26},
        },
    }
    return payload


def test_plan_transforms_select_order_json_writes_window_order_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(_retained_window_select_order_payload()))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_window_order_continuation",
            "--write-probes", str(probes_dir),
            "--max-per-family", "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    written = sorted(probes_dir.glob("*.c"))
    assert len(written) == 1
    probe = payload["probes"][0]
    assert probe["probe_id"] == "retained_gpr_case_c_window_order_continuation@0"
    assert probe["payload"]["lead_target_ig"] == 44
    assert probe["payload"]["source_attribution"]["kind"] == "implicit-temp"
    assert probe["payload"]["window_order_label"].startswith(
        "window-order-ranked-indexed-byte-ig44-"
    )
    assert probe["payload"]["ranked_indexed_byte_source_candidate"]
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    continuation = diagnostics["retained_gpr_case_c_window_order_continuation"]
    assert continuation["materialized_count"] == 1
    assert continuation["matcher_diagnostics"]["emitted_window_order_probe_count"] == 1
    assert payload["retained_case_c_window_order_continuation_summary"][
        "status"
    ] == "materialized-not-scored"


def test_plan_transforms_select_order_json_writes_ig34_copy_product_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_ig34_copy_product()
    ))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_window_order_continuation",
            "--write-probes", str(probes_dir),
            "--max-per-family", "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    written = sorted(probes_dir.glob("*.c"))
    assert len(written) == 1
    probe = payload["probes"][0]
    assert probe["probe_id"] == "retained_gpr_case_c_window_order_continuation@0"
    assert probe["payload"]["lead_target_ig"] == 34
    assert probe["payload"]["attempted_targets"] == {"34": 27}
    assert probe["payload"]["protected_targets"] == {"44": 25}
    assert probe["payload"]["source_attribution"]["kind"] == "copy/coalesce-product"
    assert probe["payload"]["window_order_label"].startswith(
        "window-order-ranked-indexed-byte-ig34-"
    )
    assert (
        probe["payload"]["synthetic_source_probe"][
            "copy_product_source_attribution"
        ]["kind"]
        == "implicit-temp"
    )
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    continuation = diagnostics["retained_gpr_case_c_window_order_continuation"]
    matcher = continuation["matcher_diagnostics"]
    assert continuation["materialized_count"] == 1
    assert matcher["emitted_window_order_probe_count"] == 1
    assert matcher["selected_window_order_targets"] == [34]
    assert matcher["attempted_targets"] == {"34": 27}
    assert matcher["protected_targets"] == {"44": 25}


def test_plan_transforms_sort_gpr_pcode_end_pointer_owner_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_end_pointer_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_ig34_end_pointer()
    ))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_window_order_continuation",
            "--write-probes", str(probes_dir),
            "--max-per-family", "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    continuation = diagnostics["retained_gpr_case_c_window_order_continuation"]
    assert continuation["materialized_count"] == 1
    assert continuation["no_probe_reason"] is None
    assert continuation["matcher_diagnostics"]["emitted_window_order_probe_count"] == 1
    assert continuation["matcher_diagnostics"].get("terminal_blocker") is None
    probe = payload["probes"][0]
    assert probe["payload"]["lead_target_ig"] == 34
    assert probe["payload"]["attempted_targets"] == {"34": 27}
    assert probe["payload"]["protected_targets"] == {"44": 25}
    assert probe["payload"]["window_order_label"].startswith(
        "window-order-ranked-end-pointer-ig34-"
    )
    assert probe["payload"]["ranked_end_pointer_source_candidate"][
        "end_local"
    ] == "ll_probe_end_0"
    assert probe["payload"]["synthetic_source_probe"][
        "ranked_end_pointer_source_candidates"
    ][0]["iter_local"] == "ll_probe_iter_0"
    written = sorted(probes_dir.glob("*.c"))
    assert len(written) == 1
    written_source = written[0].read_text()
    assert "u8* ll_probe_end_0;\n" in written_source
    assert "ll_probe_end_0 = dst + 0x78;" in written_source


def test_plan_transforms_post_source_owner_backtrack_writes_ig34_alternate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_post_source_owner_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_ig34_copy_product()
    ))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_post_source_owner_backtrack",
            "--write-probes", str(probes_dir),
            "--max-per-family", "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    written = sorted(probes_dir.glob("*.c"))
    assert len(written) == 1
    assert "alternate = sorted_names[window_order_" in written[0].read_text()
    probe = payload["probes"][0]
    assert probe["probe_id"] == "retained_gpr_case_c_post_source_owner_backtrack@0"
    assert probe["payload"]["lead_target_ig"] == 34
    assert probe["payload"]["attempted_targets"] == {"34": 27}
    assert probe["payload"]["protected_targets"] == {"44": 25}
    backtrack = probe["payload"]["post_source_owner_backtrack"]
    assert backtrack["candidate_rank"] == 2
    assert backtrack["span_text"].strip() == "alternate = sorted_names[j];"
    assert len(backtrack["skipped_current_owner_labels"]) == 1
    assert probe["payload"]["ranked_indexed_byte_source_candidate"]["rank"] == 2
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    family = diagnostics["retained_gpr_case_c_post_source_owner_backtrack"]
    matcher = family["matcher_diagnostics"]
    assert family["materialized_count"] == 1
    assert matcher["skipped_current_owner_targets"] == [34]
    assert matcher["selected_alternate_probe_count"] == 1
    assert matcher["emitted_post_source_owner_probe_count"] == 1
    summary = payload["retained_case_c_post_source_owner_backtrack_summary"]
    assert summary["status"] == "materialized-not-scored"
    assert summary["materialized_probe_count"] == 1


def test_plan_transforms_post_source_owner_backtrack_reports_no_alternate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_post_source_owner_single_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_ig34_copy_product()
    ))

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_post_source_owner_backtrack",
            "--max-per-family", "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["probes"] == []
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    family = diagnostics["retained_gpr_case_c_post_source_owner_backtrack"]
    assert family["no_probe_reason"] == "no-alternate-source-owner"
    assert family["matcher_diagnostics"]["terminal_blocker"] == (
        "no-alternate-source-owner"
    )
    summary = payload["retained_case_c_post_source_owner_backtrack_summary"]
    assert summary["status"] == "terminal-blocked"
    assert summary["terminal_blocker"] == "no-alternate-source-owner"


def test_plan_transforms_coalesce_suggest_json_writes_common_subexpr_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int i) {\n"
        "    u8* dst_iter;\n"
        "    u8* mirror_iter;\n"
        "    dst_iter = dst + i;\n"
        "    mirror_iter = dst + i;\n"
        "    use(dst_iter, mirror_iter);\n"
        "}\n"
    )
    coalesce_json = tmp_path / "suggest_coalesce.json"
    coalesce_json.write_text(json.dumps({
        "function": "mnDiagram_SortNamesByKOs",
        "mode": "discover",
        "register_class": "gpr",
        "pairs": [
            {
                "from": 34,
                "to": 40,
                "register_class": "gpr",
                "priority_class": "register-reuse",
                "ir_facts": {
                    "from": {
                        "virtual": 34,
                        "first_def": {
                            "block": 13,
                            "opcode": "addi",
                            "operands": "r34,r37,4",
                        },
                        "bridge": {"var": "dst_iter", "line": 5},
                    },
                    "to": {
                        "virtual": 40,
                        "first_def": {
                            "block": 1,
                            "opcode": "addi",
                            "operands": "r40,r37,4",
                        },
                        "bridge": {"var": "mirror_iter", "line": 6},
                    },
                },
                "suggestions": [{"pattern": "common-subexpr"}],
            }
        ],
    }))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:29,40:25",
            "--source-file", str(source),
            "--coalesce-suggest-json", str(coalesce_json),
            "--write-probes", str(probes_dir),
            "--max-per-family", "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    written = sorted(probes_dir.glob("*.c"))
    assert len(written) == 1
    assert "u8* common_subexpr_r34_r40_probe;" in written[0].read_text()
    assert "common_subexpr_r34_r40_probe = dst + i;" in written[0].read_text()
    probe = payload["probes"][0]
    assert probe["probe_id"] == "retained_gpr_common_subexpr_coalesce_source@0"
    assert probe["payload"]["attempted_targets"] == {"34": 29, "40": 25}
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    family = diagnostics["retained_gpr_common_subexpr_coalesce_source"]
    assert family["materialized_count"] == 1
    summary = payload["retained_gpr_common_subexpr_coalesce_source_summary"]
    assert summary["status"] == "materialized-not-scored"


def test_plan_transforms_coalesce_suggest_json_writes_implicit_source_owner_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int limit) {\n"
        "    u8* dst_iter;\n"
        "    int i;\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    dst_iter = dst;\n"
        "    for (i = 0; i < limit; i++, dst_iter++) {\n"
        "        use(dst_iter);\n"
        "    }\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        for (i = 0; i < limit; i++, ll_probe_iter_0++) {\n"
        "            for (j = i + 1; j < limit; j++) {\n"
        "                use(ll_probe_iter_0, max_idx);\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    coalesce_json = tmp_path / "suggest_coalesce.json"
    coalesce_json.write_text(json.dumps({
        "function": "mnDiagram_SortNamesByKOs",
        "mode": "discover",
        "register_class": "gpr",
        "pairs": [
            {
                "from": 35,
                "to": 42,
                "register_class": "gpr",
                "priority_class": "register-reuse",
                "ir_facts": {
                    "from": {
                        "virtual": 35,
                        "first_def": {
                            "block": 13,
                            "opcode": "mr",
                            "operands": "r35,r39",
                        },
                    },
                    "to": {
                        "virtual": 42,
                        "first_def": {
                            "block": 1,
                            "opcode": "mr",
                            "operands": "r42,r39",
                        },
                    },
                },
                "suggestions": [{"pattern": "common-subexpr"}],
            }
        ],
    }))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--coalesce-suggest-json", str(coalesce_json),
            "--write-probes", str(probes_dir),
            "--max-per-family", "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    written = sorted(probes_dir.glob("*.c"))
    assert len(written) == 1
    assert "u8* common_source_r39_probe;" in written[0].read_text()
    assert "common_source_r39_probe = dst;" in written[0].read_text()
    assert "dst_iter = common_source_r39_probe;" in written[0].read_text()
    assert "ll_probe_iter_0 = common_source_r39_probe;" in written[0].read_text()
    probe = payload["probes"][0]
    assert probe["probe_id"] == "retained_gpr_common_subexpr_coalesce_source@0"
    assert probe["payload"]["source_owner_origin"] == (
        "implicit-repeated-pointer-rhs"
    )
    assert probe["payload"]["protected_targets"] == {"34": 27, "44": 25}
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    family = diagnostics["retained_gpr_common_subexpr_coalesce_source"]
    assert family["materialized_count"] == 1
    matcher = family["matcher_diagnostics"]
    assert matcher["implicit_source_owner_fallback_count"] == 1
    summary = payload["retained_gpr_common_subexpr_coalesce_source_summary"]
    assert summary["status"] == "materialized-not-scored"


def test_plan_transforms_common_subexpr_validation_error_is_unscoreable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int limit) {\n"
        "    u8* dst_iter;\n"
        "    int i;\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    dst_iter = dst;\n"
        "    for (i = 0; i < limit; i++, dst_iter++) {\n"
        "        use(dst_iter);\n"
        "    }\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        for (i = 0; i < limit; i++, ll_probe_iter_0++) {\n"
        "            for (j = i + 1; j < limit; j++) {\n"
        "                use(ll_probe_iter_0, max_idx);\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    coalesce_json = tmp_path / "suggest_coalesce.json"
    coalesce_json.write_text(json.dumps({
        "function": "mnDiagram_SortNamesByKOs",
        "mode": "discover",
        "register_class": "gpr",
        "pairs": [
            {
                "from": 35,
                "to": 42,
                "register_class": "gpr",
                "priority_class": "register-reuse",
                "ir_facts": {
                    "from": {
                        "virtual": 35,
                        "first_def": {
                            "block": 13,
                            "opcode": "mr",
                            "operands": "r35,r39",
                        },
                    },
                    "to": {
                        "virtual": 42,
                        "first_def": {
                            "block": 1,
                            "opcode": "mr",
                            "operands": "r42,r39",
                        },
                    },
                },
                "suggestions": [{"pattern": "common-subexpr"}],
            }
        ],
    }))
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import json\n"
        "print(json.dumps({"
        "'status': 'blocked', "
        "'score': 1073741824, "
        "'error': \"function 'mnDiagram_SortNamesByKOs' not in compiled pcdump\", "
        "'full_unit_source': True"
        "}))\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--coalesce-suggest-json", str(coalesce_json),
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "1",
            "--validate-command",
            f"{sys.executable} {validator} {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["validation"][0]["outcome"] == "blocked"
    summary = payload["retained_gpr_common_subexpr_coalesce_source_summary"]
    assert summary["status"] == "unscoreable"
    assert summary["unscoreable_count"] == 1
    assert summary["terminal_blocker"] == (
        "common-subexpr-coalesce-source-unscoreable"
    )
    assert payload["validation_summary"]["stop_condition"] == "blocked"
    assert "common-subexpr-coalesce-source-probes-exhausted" not in (
        payload["validation_summary"].get("terminal_blockers") or []
    )


def test_plan_transforms_common_subexpr_one_hit_reports_residual(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(u8* dst, int limit) {\n"
        "    u8* dst_iter;\n"
        "    int i;\n"
        "    int j;\n"
        "    int max_idx;\n"
        "    dst_iter = dst;\n"
        "    for (i = 0; i < limit; i++, dst_iter++) {\n"
        "        use(dst_iter);\n"
        "    }\n"
        "    {\n"
        "        u8* ll_probe_iter_0 = dst;\n"
        "        for (i = 0; i < limit; i++, ll_probe_iter_0++) {\n"
        "            for (j = i + 1; j < limit; j++) {\n"
        "                use(ll_probe_iter_0, max_idx);\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    coalesce_json = tmp_path / "suggest_coalesce.json"
    coalesce_json.write_text(json.dumps({
        "function": "mnDiagram_SortNamesByKOs",
        "mode": "discover",
        "register_class": "gpr",
        "pairs": [
            {
                "from": 35,
                "to": 42,
                "register_class": "gpr",
                "priority_class": "register-reuse",
                "ir_facts": {
                    "from": {
                        "virtual": 35,
                        "first_def": {
                            "block": 13,
                            "opcode": "mr",
                            "operands": "r35,r39",
                        },
                    },
                    "to": {
                        "virtual": 42,
                        "first_def": {
                            "block": 1,
                            "opcode": "mr",
                            "operands": "r42,r39",
                        },
                    },
                },
                "suggestions": [{"pattern": "common-subexpr"}],
            }
        ],
    }))
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import json\n"
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'target_score': {"
        "  'matched': 1, "
        "  'targeted': 2, "
        "  'virtuals': {"
        "    '34': {'expected': 27, 'actual': 29, 'matched': False}, "
        "    '44': {'expected': 25, 'actual': 25, 'matched': True}"
        "  }"
        "}"
        "}))\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--coalesce-suggest-json", str(coalesce_json),
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "1",
            "--validate-command",
            f"{sys.executable} {validator} {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    summary = payload["retained_gpr_common_subexpr_coalesce_source_summary"]
    assert summary["status"] == "residual-hit"
    assert summary["protected_progress_count"] == 1
    assert summary["residual_force_phys"] == {"34": 27}
    assert summary["preserved_force_phys"] == {"44": 25}
    assert summary["stop_condition"] == (
        "common-subexpr-coalesce-source-residual-hit"
    )
    assert payload["validation_summary"]["stop_condition"] == (
        "common-subexpr-coalesce-source-residual-hit"
    )
    assert "common-subexpr-coalesce-source-probes-exhausted" not in (
        payload["validation_summary"].get("terminal_blockers") or []
    )


def test_plan_transforms_post_source_owner_backtrack_validation_reports_negative(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_post_source_owner_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_ig34_copy_product()
    ))
    validator = (
        "import json; "
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'target_score': {'matched': 1, 'targeted': 2, "
        "'virtuals': {'34': {'expected': 27, 'actual': 29, 'matched': False}, "
        "'44': {'expected': 25, 'actual': 25, 'matched': True}}}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_post_source_owner_backtrack",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "1",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    classification = payload["validation"][0][
        "retained_case_c_post_source_owner_backtrack_classification"
    ]
    assert classification["classification"] == "protected-negative"
    summary = payload["retained_case_c_post_source_owner_backtrack_summary"]
    assert summary["status"] == "scored-negative"
    assert summary["protected_negative_count"] == 1
    assert summary["terminal_blocker"] == "post-source-owner-exhausted"
    assert "post-source-owner-exhausted" in payload["validation_summary"][
        "terminal_blockers"
    ]


def test_plan_transforms_post_source_owner_backtrack_validation_reports_exact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_post_source_owner_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_ig34_copy_product()
    ))
    validator = (
        "import json; "
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'target_score': {'matched': 2, 'targeted': 2, "
        "'virtuals': {'34': {'expected': 27, 'actual': 27, 'matched': True}, "
        "'44': {'expected': 25, 'actual': 25, 'matched': True}}}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_post_source_owner_backtrack",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "1",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    classification = payload["validation"][0][
        "retained_case_c_post_source_owner_backtrack_classification"
    ]
    assert classification["classification"] == "exact"
    summary = payload["retained_case_c_post_source_owner_backtrack_summary"]
    assert summary["status"] == "scored-exact"
    assert summary["stop_condition"] == "exact-post-source-owner-backtrack"
    assert payload["validation_summary"]["stop_condition"] == (
        "exact-post-source-owner-backtrack"
    )


def test_plan_transforms_select_order_json_writes_target_live_range_probes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        _retained_window_order_source().replace(
            "sorted_names[max_idx]",
            "sorted_names[(max_idx)]",
        )
    )
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_repair_goal()
    ))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--write-probes", str(probes_dir),
            "--max-per-family", "5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    written = sorted(probes_dir.glob("*.c"))
    assert len(written) == 5
    assert {
        probe["payload"]["source_probe_provenance_kind"]
        for probe in payload["probes"]
    } == {
        "target-aware-live-range-anchor",
        "target-aware-interference-shape",
        "target-aware-implicit-index-normalize",
        "target-aware-implicit-index-alias",
        "target-aware-implicit-base-alias",
    }
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    repair = diagnostics["retained_gpr_case_c_target_live_range_repair"]
    assert repair["materialized_count"] == 5
    assert repair["matcher_diagnostics"]["emitted_repair_probe_count"] == 5
    summary = payload["retained_case_c_target_live_range_repair_summary"]
    assert summary["status"] == "materialized-not-scored"
    assert summary["materialized_probe_count"] == 5


def test_plan_transforms_default_sort_target_live_range_uses_local_expressions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        _retained_window_order_source().replace(
            "sorted_names[max_idx]",
            "sorted_names[(max_idx)]",
        )
    )
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--write-probes", str(probes_dir),
            "--max-per-family", "5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(sorted(probes_dir.glob("*.c"))) == 5
    _assert_sort_target_live_range_uses_local_source_expressions(payload)
    combined_source = "\n".join(path.read_text() for path in probes_dir.glob("*.c"))
    assert "mnDiagram_804A076C.sorted_names" not in combined_source
    summary = payload["retained_case_c_target_live_range_repair_summary"]
    assert summary["status"] == "materialized-not-scored"
    assert summary["materialized_probe_count"] == 5


def test_plan_transforms_virtual_explain_json_derives_blocker_color_chain(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        _retained_window_order_source().replace(
            "sorted_names[max_idx]",
            "sorted_names[(max_idx)]",
        )
    )
    virtual_explain = tmp_path / "explain_virtuals.json"
    virtual_explain.write_text(json.dumps(_virtual_explain_blocker_chain_payload()))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--virtual-explain-json", str(virtual_explain),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--write-probes", str(probes_dir),
            "--max-per-family", "5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(sorted(probes_dir.glob("*.c"))) == 5
    _assert_sort_target_live_range_uses_local_source_expressions(payload)
    repair_goals = [
        probe["payload"]["repair_goal"]
        for probe in payload["probes"]
        if probe["family_id"] == "retained_gpr_case_c_target_live_range_repair"
    ]
    assert repair_goals
    assert {goal["interferer_ig"] for goal in repair_goals} == {41}
    assert {goal["evidence"]["kind"] for goal in repair_goals} == {
        "blocker-color-chain"
    }
    chain = repair_goals[0]["blocker_color_chain"]
    assert [
        (edge["target_ig"], edge["target_phys"], edge["blocker_ig"])
        for edge in chain
    ] == [(34, 27, 44), (44, 25, 41)]
    summary = payload["retained_case_c_target_live_range_repair_summary"]
    assert summary["status"] == "materialized-not-scored"
    assert summary["blocker_color_chains"][0] == chain
    assert payload["source_resolution"]["target_live_range_repair"]["status"] == (
        "blocker-color-chain-goals-loaded"
    )


def test_plan_transforms_virtual_explain_json_expands_blocker_operand_sources(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_lower_drift_residual_source())
    virtual_explain = tmp_path / "explain_virtuals.json"
    virtual_explain.write_text(json.dumps(
        _virtual_explain_blocker_chain_operand_payload()
    ))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--virtual-explain-json", str(virtual_explain),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--write-probes", str(probes_dir),
            "--max-per-family", "12",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["source_resolution"]["target_live_range_repair"][
        "repair_goal_count"
    ] == 4
    repair_goals = [
        probe["payload"]["repair_goal"]
        for probe in payload["probes"]
        if probe["family_id"] == "retained_gpr_case_c_target_live_range_repair"
    ]
    chain = repair_goals[0]["blocker_color_chain"]
    operand_sources = {
        (edge["blocker_ig"], operand["operand_virtual"]): operand["source"][
            "expression"
        ]
        for edge in chain
        for operand in edge.get("blocker_operand_sources", [])
    }
    assert operand_sources == {
        (44, 52): "case_c_max_idx_probe",
        (44, 64): "sorted_names_totals_idx_probe_2",
        (41, 45): "window_order_mnDiagram_804A076C_sorted_names_index_probe",
    }
    operand_goals = [
        goal
        for goal in repair_goals
        if goal.get("evidence", {}).get("kind") == "blocker-operand-source-owner"
    ]
    assert {
        goal["operand_source_owner"]["operand_virtual"]
        for goal in operand_goals
    } == {52, 64, 45}
    assert {
        probe["payload"]["ranked_repair_candidate"]["strategy"]
        for probe in payload["probes"]
        if probe["payload"]["source_probe_provenance_kind"]
        == "target-aware-blocker-operand-source-anchor"
    } == {"blocker-operand-source-temp"}


def test_plan_transforms_sort_gpr_alternate_source_owner_resolves_pcode_operands(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_lower_drift_residual_source())
    exhaustion = tmp_path / "current_owner.json"
    _write_current_owner_exhaustion(
        exhaustion,
        [
            {
                "kind": "target-live-range-source-owner-terminal",
                "family_id": "retained_gpr_case_c_target_live_range_repair",
                "target_ig": 44,
                "target_phys": 25,
                "interferer_ig": 44,
                "interferer_phys": 25,
                "source_expression": "add r44,r52,r64",
                "source_type": "int",
                "source_owner_kind": "implicit-temp",
                "status": "materialized",
                "source_owner_status": "current-source-owner-probes-exhausted",
                "next_source_owner_status": "not-discovered",
            },
            {
                "kind": "target-live-range-source-owner-terminal",
                "family_id": "retained_gpr_case_c_target_live_range_repair",
                "target_ig": 44,
                "target_phys": 25,
                "interferer_ig": 52,
                "interferer_phys": 24,
                "source_expression": "mr r52,r54",
                "source_type": "int",
                "source_owner_kind": "copy/coalesce-product",
                "source_owner_base_virtual": 54,
                "status": "materialized",
                "source_owner_status": "current-source-owner-probes-exhausted",
                "next_source_owner_status": "not-discovered",
            },
            {
                "kind": "target-live-range-source-owner-terminal",
                "family_id": "retained_gpr_case_c_target_live_range_repair",
                "target_ig": 44,
                "target_phys": 25,
                "interferer_ig": 64,
                "interferer_phys": 28,
                "source_expression": "lwz r64,max_idx(r1)",
                "source_type": "int",
                "source_owner_kind": "load/store-address",
                "stack_symbol": "max_idx",
                "operand_virtual": 64,
                "operand_live_range": [38, 41],
                "status": "materialized",
                "source_owner_status": "current-source-owner-probes-exhausted",
                "next_source_owner_status": "not-discovered",
            },
            {
                "kind": "target-live-range-source-owner-terminal",
                "family_id": "retained_gpr_case_c_target_live_range_repair",
                "target_ig": 44,
                "target_phys": 25,
                "interferer_ig": 41,
                "interferer_phys": 25,
                "source_expression": "rlwinm r41,r45,0,24,31",
                "source_type": "u8",
                "source_owner_kind": "implicit-temp",
                "operand_virtual": 41,
                "status": "materialized",
                "source_owner_status": "current-source-owner-probes-exhausted",
                "next_source_owner_status": "not-discovered",
            },
        ],
        attempted={"44": 25},
        protected={"34": 27},
    )
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--current-owner-exhaustion-json", str(exhaustion),
            "--transform-family", "retained_case_c_alternate_source_owner_discovery",
            "--write-probes", str(probes_dir),
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    family = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }["retained_case_c_alternate_source_owner_discovery"]
    matcher = family["matcher_diagnostics"]
    assert matcher["status"] == "materialized"
    ranked = {
        item["source_expression"]
        for item in matcher["ranked_alternate_owner_candidates"]
    }
    assert "mnDiagram_804A076C.sorted_names" in ranked
    assert "max_idx" in ranked
    assert "mnDiagram_804A076C.sorted_names[j]" in ranked
    emitted = [
        probe
        for probe in payload["probes"]
        if probe["family_id"] == "retained_case_c_alternate_source_owner_discovery"
    ]
    assert emitted
    emitted_expressions = {
        probe["payload"]["ranked_repair_candidate"]["source_expression"]
        for probe in emitted
    }
    assert not any(
        expression.startswith(("add ", "mr ", "lwz ", "rlwinm "))
        for expression in emitted_expressions
    )
    assert all(
        probe["payload"]["current_owner_span"]["source_expression"].startswith(
            ("add ", "mr ", "lwz ", "rlwinm ")
        )
        for probe in emitted
    )
    assert sorted(probes_dir.glob("*.c"))


def test_plan_transforms_sort_gpr_alternate_source_owner_terminal_proof(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "void mnDiagram_SortNamesByKOs(void) {\n"
        "    u8 value;\n"
        "    value = 0;\n"
        "}\n"
    )
    exhaustion = tmp_path / "current_owner.json"
    _write_current_owner_exhaustion(
        exhaustion,
        [
            {
                "kind": "target-live-range-source-owner-terminal",
                "family_id": "retained_gpr_case_c_target_live_range_repair",
                "target_ig": 44,
                "target_phys": 25,
                "interferer_ig": 44,
                "interferer_phys": 25,
                "source_expression": "add r44,r52,r64",
                "source_type": "int",
                "source_owner_kind": "implicit-temp",
                "status": "materialized",
                "source_owner_status": "current-source-owner-probes-exhausted",
                "next_source_owner_status": "not-discovered",
            },
        ],
        attempted={"44": 25},
        protected={"34": 27},
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--current-owner-exhaustion-json", str(exhaustion),
            "--transform-family", "retained_case_c_alternate_source_owner_discovery",
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    family = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }["retained_case_c_alternate_source_owner_discovery"]
    matcher = family["matcher_diagnostics"]
    assert family["materialized_count"] == 0
    assert matcher["terminal_blocker"] == "next-source-owner-exhausted"
    assert {
        node["source_expression"] for node in matcher["inspected_owner_nodes"]
    } >= {"mnDiagram_804A076C.sorted_names[j]", "mnDiagram_804A076C.sorted_names"}
    assert all(
        node["status"] == "rejected" and node.get("reason")
        for node in matcher["inspected_owner_nodes"]
    )


def test_plan_transforms_blocker_chain_value_probes_use_distinct_temps(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        _retained_window_order_source().replace(
            "sorted_names[max_idx]",
            "sorted_names[(max_idx)]",
        )
    )
    virtual_explain = tmp_path / "explain_virtuals.json"
    virtual_explain.write_text(json.dumps(_virtual_explain_blocker_chain_payload()))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--virtual-explain-json", str(virtual_explain),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--write-probes", str(probes_dir),
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    value_probe_kinds = {
        "target-aware-value-side-temp",
        "target-aware-coupled-address-value",
    }
    value_probes = [
        probe for probe in payload["probes"]
        if probe["payload"]["source_probe_provenance_kind"] in value_probe_kinds
    ]
    assert {
        probe["payload"]["source_probe_provenance_kind"]
        for probe in value_probes
    } == value_probe_kinds

    for probe in value_probes:
        probe_source = (probes_dir / f"{probe['probe_id']}.c").read_text()
        declarations = [
            line.strip()
            for line in probe_source.splitlines()
            if line.strip().startswith("u8 target_repair_value_")
        ]
        assert len(declarations) == len(set(declarations))
        assert any("target_repair_value_ig41_j_probe_2" in line
                   for line in declarations)


def test_plan_transforms_coupled_value_probe_hoists_index_assignment(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "void* GetNameText(u8 value);\n"
        "void mnDiagram_SortNamesByKOs(u8* sorted_names, u32* totals, "
        "int max_idx, int j) {\n"
        "    int window_order_sorted_names_index_probe_2;\n"
        "    u8 sorted_names_totals_idx_probe;\n"
        "    u8 sorted_names_totals_idx_probe_2;\n"
        "    sorted_names_totals_idx_probe = sorted_names[(max_idx)];\n"
        "    window_order_sorted_names_index_probe_2 = j;\n"
        "    sorted_names_totals_idx_probe_2 = "
        "sorted_names[window_order_sorted_names_index_probe_2];\n"
        "    if ((GetNameText("
        "sorted_names[window_order_sorted_names_index_probe_2]) != 0) &&\n"
        "        (totals[sorted_names_totals_idx_probe] < "
        "totals[sorted_names_totals_idx_probe_2])) {\n"
        "        max_idx = j;\n"
        "    }\n"
        "}\n"
    )
    select_order = tmp_path / "select_order.json"
    payload = _retained_window_select_order_payload()
    payload["retained_case_c_repair_goals"] = [{
        "kind": "target-aware-live-range-interference",
        "target_ig": 44,
        "target_phys": 25,
        "protected_targets": {"34": 27},
        "interferer_ig": 41,
        "interferer_phys": 25,
        "source_expression": (
            "sorted_names[window_order_sorted_names_index_probe_2]"
        ),
        "address_index": "(max_idx)",
        "duplicate_value_ig": 41,
        "required_delta": 6,
    }]
    select_order.write_text(json.dumps(payload))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--write-probes", str(probes_dir),
            "--max-per-family", "8",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    coupled_probe = next(
        probe for probe in output["probes"]
        if probe["payload"]["source_probe_provenance_kind"]
        == "target-aware-coupled-address-value"
    )
    probe_source = (probes_dir / f"{coupled_probe['probe_id']}.c").read_text()
    index_assignment = "window_order_sorted_names_index_probe_2 = j;"
    address_assignment = (
        "target_repair_address_ig44_max_idx_probe = &sorted_names[(max_idx)];"
    )
    value_assignment = (
        "target_repair_value_ig41_window_order_sorted_names_index_probe_2_probe"
        " = sorted_names[window_order_sorted_names_index_probe_2];"
    )

    assert probe_source.count(index_assignment) == 1
    assert (
        probe_source.index(index_assignment)
        < probe_source.index(address_assignment)
        < probe_source.index(value_assignment)
    )


def test_plan_transforms_virtual_explain_json_rejects_wrong_function(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    virtual_explain = tmp_path / "explain_virtuals.json"
    virtual_explain.write_text(json.dumps(
        _virtual_explain_blocker_chain_payload(function="other_function")
    ))

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--virtual-explain-json", str(virtual_explain),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert "--virtual-explain-json function" in result.output


def test_plan_transforms_target_live_range_validation_classifies_protected_negative(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_repair_goal()
    ))
    validator = (
        "import json, pathlib, sys; "
        "p = pathlib.Path(sys.argv[1]); "
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'source_retained': str(p), "
        "'pcdump_path': str(p.with_suffix('.pcdump.txt')), "
        "'target_score': {'matched': 1, 'targeted': 2, "
        "'virtuals': {'34': {'expected': 27, 'actual': 27, 'matched': True}, "
        "'44': {'expected': 25, 'actual': 27, 'matched': False}}}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "5",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    classifications = [
        item["retained_case_c_target_live_range_classification"][
            "classification"
        ]
        for item in payload["validation"]
    ]
    assert classifications == [
        "protected-negative",
        "protected-negative",
        "protected-negative",
        "protected-negative",
        "protected-negative",
    ]
    summary = payload["retained_case_c_target_live_range_repair_summary"]
    assert summary["status"] == "blocked"
    assert summary["protected_negative_count"] == 5
    assert summary["terminal_blocker"] == (
        "target-aware-live-range-interference-probes-exhausted"
    )
    assert summary["next_source_lever_classes"] == [
        "target-aware-live-range-anchor",
        "target-aware-interference-shape",
        "target-aware-implicit-index-normalize",
        "target-aware-implicit-index-alias",
        "target-aware-implicit-base-alias",
        "target-aware-address-side-temp",
        "target-aware-value-side-temp",
        "target-aware-coupled-address-value",
    ]
    assert payload["validation_summary"].get("stop_condition") != (
        "exact-retained-target-live-range-repair"
    )


def test_plan_transforms_blocker_chain_validation_reports_terminal_blocker(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    virtual_explain = tmp_path / "explain_virtuals.json"
    virtual_explain.write_text(json.dumps(_virtual_explain_blocker_chain_payload()))
    validator = (
        "import json; "
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'target_score': {'matched': 1, 'targeted': 2, "
        "'virtuals': {'34': {'expected': 27, 'actual': 27, 'matched': True}, "
        "'44': {'expected': 25, 'actual': 27, 'matched': False}}}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--virtual-explain-json", str(virtual_explain),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "3",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    summary = payload["retained_case_c_target_live_range_repair_summary"]
    assert summary["status"] == "blocked"
    assert summary["terminal_blocker"] == (
        "blocker-color-chain-source-probes-exhausted"
    )
    assert summary["dominant_blocker"] == "blocker-color-chain-source-probes"
    assert summary["unscoreable_count"] == 0
    assert "blocker-color-chain-source-probes-exhausted" in (
        payload["validation_summary"]["terminal_blockers"]
    )


def test_target_live_range_summary_preserves_blocked_pcode_owner_terminals() -> None:
    summary = _retained_case_c_target_live_range_repair_summary(
        [
            {
                "family_id": "retained_gpr_case_c_target_live_range_repair",
                "probe_id": "retained_gpr_case_c_target_live_range_repair@0",
                "payload": {
                    "repair_goal": {
                        "protected_targets": {"34": 27},
                        "target_ig": 44,
                        "target_phys": 25,
                    },
                    "ranked_repair_candidate": {
                        "strategy": "value-side-duplicate-temp",
                        "source_expression": "sorted_names[j]",
                    },
                },
            }
        ],
        [
            {
                "family_id": "retained_gpr_case_c_target_live_range_repair",
                "probe_id": "retained_gpr_case_c_target_live_range_repair@0",
                "retained_case_c_target_live_range_classification": {
                    "classification": "lost-protected",
                },
            }
        ],
        [
            {
                "family_id": "retained_gpr_case_c_target_live_range_repair",
                "matcher_diagnostics": {
                    "repair_goal_diagnostics": [
                        {
                            "status": "blocked",
                            "terminal_blocker": (
                                "target-aware-repair-source-span-not-found"
                            ),
                            "repair_goal": {
                                "target_ig": 44,
                                "target_phys": 25,
                                "interferer_ig": 52,
                                "source_expression": "mr r52,r54",
                                "source_type": "int",
                                "operand_source_owner": {
                                    "operand_index": 1,
                                    "operand_virtual": 52,
                                    "source": {
                                        "kind": "copy/coalesce-product",
                                        "confidence": "pcode-first-def",
                                        "base_virtual": 54,
                                        "first_def": {
                                            "opcode": "mr",
                                            "operands": "r52,r54",
                                        },
                                    },
                                },
                                "evidence": {
                                    "kind": "blocker-operand-source-owner",
                                },
                            },
                            "repair_candidate_summary": {
                                "candidate_count": 10,
                                "materialized_count": 0,
                                "reasons": {
                                    "unsafe-source-expression": 1,
                                    "source-expression-not-indexed-byte": 7,
                                },
                            },
                        },
                        {
                            "status": "blocked",
                            "terminal_blocker": (
                                "target-aware-repair-source-span-not-found"
                            ),
                            "repair_goal": {
                                "target_ig": 44,
                                "target_phys": 25,
                                "interferer_ig": 64,
                                "source_expression": "lwz r64,max_idx(r1)",
                                "source_type": "int",
                                "operand_source_owner": {
                                    "operand_index": 2,
                                    "operand_virtual": 64,
                                    "operand_live_range": [38, 41],
                                    "source": {
                                        "kind": "load/store-address",
                                        "confidence": "pcode-first-def",
                                        "first_def": {
                                            "opcode": "lwz",
                                            "operands": "r64,max_idx(r1)",
                                        },
                                    },
                                },
                                "evidence": {
                                    "kind": "blocker-operand-source-owner",
                                },
                            },
                            "repair_candidate_summary": {
                                "candidate_count": 10,
                                "materialized_count": 0,
                                "reasons": {
                                    "unsafe-source-expression": 1,
                                    "source-expression-not-indexed-byte": 7,
                                },
                            },
                        },
                    ],
                },
            },
        ],
    )

    assert summary is not None
    assert summary["status"] == "blocked"
    spans = summary["source_owner_terminal_spans"]
    assert {
        (span["source_owner_kind"], span["source_expression"])
        for span in spans
    } == {
        ("copy/coalesce-product", "mr r52,r54"),
        ("load/store-address", "lwz r64,max_idx(r1)"),
    }
    assert spans[0]["source_owner_base_virtual"] == 54
    assert spans[1]["stack_symbol"] == "max_idx"
    assert spans[1]["operand_live_range"] == [38, 41]
    assert all(
        span["terminal_blocker"] == "target-aware-repair-source-span-not-found"
        for span in spans
    )


def test_target_live_range_summary_marks_exhausted_fpr_source_owners() -> None:
    summary = _retained_case_c_target_live_range_repair_summary(
        [
            {
                "family_id": "retained_fpr_case_c_target_live_range_repair",
                "probe_id": "retained_fpr_case_c_target_live_range_repair@0",
                "payload": {
                    "repair_goal": {
                        "protected_targets": {"32": 26},
                        "target_ig": 37,
                        "target_phys": 26,
                    },
                    "ranked_repair_candidate": {
                        "strategy": "scalar-duplicate-temp",
                        "source_expression": "row_offset_adj",
                    },
                },
            }
        ],
        [
            {
                "family_id": "retained_fpr_case_c_target_live_range_repair",
                "probe_id": "retained_fpr_case_c_target_live_range_repair@0",
                "retained_case_c_target_live_range_classification": {
                    "classification": "protected-negative",
                },
            }
        ],
        [
            {
                "family_id": "retained_fpr_case_c_target_live_range_repair",
                "matcher_diagnostics": {
                    "repair_goal_diagnostics": [
                        {
                            "status": "materialized",
                            "repair_goal": {
                                "target_ig": 37,
                                "target_phys": 26,
                                "interferer_ig": 37,
                                "interferer_phys": 26,
                                "source_expression": "row_offset_adj",
                                "source_type": "f32",
                                "paired_source_expression": "col_offset",
                            },
                            "repair_candidate_summary": {
                                "candidate_count": 10,
                                "materialized_count": 3,
                                "reasons": {
                                    "source-expression-not-indexed-byte": 7,
                                },
                            },
                            "materialized_probe_labels": [
                                "target-live-range-ig37-r26-interferer-ig37-0",
                                "target-live-range-ig37-r26-interferer-ig37-1",
                                "target-live-range-ig37-r26-interferer-ig37-2",
                            ],
                        },
                    ],
                },
            },
        ],
    )

    assert summary is not None
    assert summary["status"] == "blocked"
    assert summary["terminal_blocker"] == (
        "target-aware-live-range-interference-probes-exhausted"
    )
    spans = summary["source_owner_terminal_spans"]
    assert spans == [
        {
            "kind": "target-live-range-source-owner-terminal",
            "family_id": "retained_fpr_case_c_target_live_range_repair",
            "target_ig": 37,
            "target_phys": 26,
            "interferer_ig": 37,
            "interferer_phys": 26,
            "source_expression": "row_offset_adj",
            "paired_source_expression": "col_offset",
            "source_type": "f32",
            "status": "materialized",
            "terminal_blocker": (
                "target-aware-live-range-interference-probes-exhausted"
            ),
            "candidate_count": 10,
            "materialized_count": 3,
            "rejection_reasons": {
                "source-expression-not-indexed-byte": 7,
            },
            "materialized_probe_labels": [
                "target-live-range-ig37-r26-interferer-ig37-0",
                "target-live-range-ig37-r26-interferer-ig37-1",
                "target-live-range-ig37-r26-interferer-ig37-2",
            ],
            "source_owner_status": "current-source-owner-probes-exhausted",
            "next_source_owner_status": "not-discovered",
        }
    ]


def test_target_live_range_summary_converts_scored_alternate_owner_to_terminal_proof() -> None:
    summary = _retained_case_c_target_live_range_repair_summary(
        [
            {
                "family_id": "retained_case_c_alternate_source_owner_discovery",
                "probe_id": "retained_case_c_alternate_source_owner_discovery@0",
                "payload": {
                    "window_order_label": "alternate-source-owner-row_offset-0",
                    "repair_goal": {
                        "protected_targets": {"32": 26},
                        "target_ig": 37,
                        "target_phys": 26,
                    },
                    "ranked_repair_candidate": {
                        "strategy": "alternate-source-owner-temp",
                        "source_expression": "row_offset",
                    },
                },
            }
        ],
        [
            {
                "family_id": "retained_case_c_alternate_source_owner_discovery",
                "probe_id": "retained_case_c_alternate_source_owner_discovery@0",
                "retained_case_c_target_live_range_classification": {
                    "classification": "protected-negative",
                },
            }
        ],
        [
            {
                "family_id": "retained_case_c_alternate_source_owner_discovery",
                "matcher_diagnostics": {
                    "current_owner_span_updates": [
                        {
                            "kind": "target-live-range-source-owner-terminal",
                            "family_id": (
                                "retained_fpr_case_c_target_live_range_repair"
                            ),
                            "target_ig": 37,
                            "target_phys": 26,
                            "interferer_ig": 37,
                            "interferer_phys": 26,
                            "source_expression": "row_offset_adj",
                            "source_type": "f32",
                            "status": "materialized",
                            "source_owner_status": (
                                "current-source-owner-probes-exhausted"
                            ),
                            "next_source_owner_status": "materialized",
                            "alternate_source_owner_probe_labels": [
                                "alternate-source-owner-row_offset-0",
                            ],
                            "inspected_owner_nodes": [
                                {
                                    "source_expression": "row_offset",
                                    "status": "candidate",
                                }
                            ],
                        }
                    ],
                },
            },
        ],
    )

    assert summary is not None
    spans = summary["source_owner_terminal_spans"]
    assert spans[0]["next_source_owner_status"] == (
        "terminal-next-source-owner-exhausted"
    )
    assert spans[0]["terminal_blocker"] == "next-source-owner-exhausted"
    assert spans[0]["alternate_source_owner_validation"] == [
        {
            "probe_label": "alternate-source-owner-row_offset-0",
            "probe_id": "retained_case_c_alternate_source_owner_discovery@0",
            "classification": "protected-negative",
        }
    ]


def test_target_live_range_summary_keeps_lost_alternate_owner_actionable() -> None:
    summary = _retained_case_c_target_live_range_repair_summary(
        [
            {
                "family_id": "retained_case_c_alternate_source_owner_discovery",
                "probe_id": "retained_case_c_alternate_source_owner_discovery@0",
                "payload": {
                    "window_order_label": "alternate-source-owner-row_offset-0",
                    "repair_goal": {
                        "protected_targets": {"32": 26},
                        "target_ig": 37,
                        "target_phys": 26,
                    },
                    "ranked_repair_candidate": {
                        "strategy": "alternate-source-owner-temp",
                        "source_expression": "row_offset",
                    },
                },
            }
        ],
        [
            {
                "family_id": "retained_case_c_alternate_source_owner_discovery",
                "probe_id": "retained_case_c_alternate_source_owner_discovery@0",
                "retained_case_c_target_live_range_classification": {
                    "classification": "lost-protected",
                },
            }
        ],
        [
            {
                "family_id": "retained_case_c_alternate_source_owner_discovery",
                "matcher_diagnostics": {
                    "current_owner_span_updates": [
                        {
                            "kind": "target-live-range-source-owner-terminal",
                            "family_id": (
                                "retained_fpr_case_c_target_live_range_repair"
                            ),
                            "target_ig": 37,
                            "target_phys": 26,
                            "interferer_ig": 37,
                            "interferer_phys": 26,
                            "source_expression": "row_offset_adj",
                            "source_type": "f32",
                            "status": "materialized",
                            "source_owner_status": (
                                "current-source-owner-probes-exhausted"
                            ),
                            "next_source_owner_status": "materialized",
                            "alternate_source_owner_probe_labels": [
                                "alternate-source-owner-row_offset-0",
                            ],
                            "inspected_owner_nodes": [
                                {
                                    "source_expression": "row_offset",
                                    "status": "candidate",
                                }
                            ],
                        }
                    ],
                },
            },
        ],
    )

    assert summary is not None
    span = summary["source_owner_terminal_spans"][0]
    assert span["next_source_owner_status"] == "materialized"
    assert "terminal_blocker" not in span
    assert span["alternate_source_owner_validation"] == [
        {
            "probe_label": "alternate-source-owner-row_offset-0",
            "probe_id": "retained_case_c_alternate_source_owner_discovery@0",
            "classification": "lost-protected",
        }
    ]


def test_plan_transforms_target_live_range_exact_hit_stops(tmp_path: Path) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_repair_goal()
    ))
    validator = (
        "import json; "
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'target_score': {'matched': 2, 'targeted': 2, "
        "'virtuals': {'34': {'expected': 27, 'actual': 27, 'matched': True}, "
        "'44': {'expected': 25, 'actual': 25, 'matched': True}}}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_target_live_range_repair",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "2",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["validation"]) == 1
    summary = payload["retained_case_c_target_live_range_repair_summary"]
    assert summary["status"] == "exact"
    assert summary["stop_condition"] == "exact-retained-target-live-range-repair"
    assert payload["validation_summary"]["stop_condition"] == (
        "exact-retained-target-live-range-repair"
    )


def test_plan_transforms_select_order_json_validation_classifies_protected_negative(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(_retained_window_select_order_payload()))
    validator = (
        "import json, pathlib, sys; "
        "p = pathlib.Path(sys.argv[1]); "
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'source_retained': str(p), "
        "'pcdump_path': str(p.with_suffix('.pcdump.txt')), "
        "'target_score': {'matched': 1, 'targeted': 2, "
        "'virtuals': {'34': {'expected': 27, 'actual': 27, 'matched': True}, "
        "'44': {'expected': 25, 'actual': 27, 'matched': False}}}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_window_order_continuation",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "1",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    classification = payload["validation"][0][
        "retained_case_c_window_order_classification"
    ]
    assert classification["classification"] == "protected-negative"
    summary = payload["retained_case_c_window_order_continuation_summary"]
    assert summary["status"] == "blocked"
    assert summary["protected_negative_count"] == 1
    target_score = summary["best_retained_candidates"][0]["target_score"]
    assert target_score["virtuals"]["34"]["actual"] == 27
    assert target_score["virtuals"]["44"]["actual"] == 27


def test_retained_window_candidate_summary_preserves_source_hunks() -> None:
    source_hunks = [{"hunk_id": "field-load001", "base_start": 2}]
    summary = _retained_window_candidate_summary(
        {
            "probe_id": "retained_gpr_case_c_window_order_continuation@0",
            "validator_payload": {
                "source_retained": "/tmp/candidate.c",
                "pcdump_path": "/tmp/candidate.pcdump.txt",
            },
            "target_score": {
                "virtuals": {
                    "66": {"expected": 30, "actual": 28, "matched": False}
                }
            },
        },
        {
            "payload": {
                "source_hunks": source_hunks,
                "source_probe_provenance_kind": (
                    "copy-coalesce-source-field-load-source-order"
                ),
                "field_load_source_candidate": {"field_name": "user_data"},
                "ranked_end_pointer_source_candidate": {
                    "end_local": "ll_probe_end_0"
                },
                "ranked_li_constant_source_candidate": {
                    "owner_local": "threshold",
                    "literal_text": "0x18",
                },
                "ranked_pointer_walk_add_source_candidate": {
                    "base_expression": "user_data",
                    "index_expr": "i",
                },
                "source_attribution": {"kind": "copy/coalesce-source"},
            }
        },
    )

    assert summary["source_hunks"] == source_hunks
    assert summary["source_probe_provenance_kind"] == (
        "copy-coalesce-source-field-load-source-order"
    )
    assert summary["field_load_source_candidate"] == {"field_name": "user_data"}
    assert summary["ranked_end_pointer_source_candidate"] == {
        "end_local": "ll_probe_end_0"
    }
    assert summary["ranked_li_constant_source_candidate"] == {
        "owner_local": "threshold",
        "literal_text": "0x18",
    }
    assert summary["ranked_pointer_walk_add_source_candidate"] == {
        "base_expression": "user_data",
        "index_expr": "i",
    }
    assert summary["source_attribution_kind"] == "copy/coalesce-source"
    assert summary["pcdump_path"] == "/tmp/candidate.pcdump.txt"
    assert summary["target_score"]["virtuals"]["66"]["actual"] == 28


def test_retained_window_candidate_summary_preserves_call_return_scored_proof(
) -> None:
    source_hunks = [{"hunk_id": "call-return001", "base_start": 935}]
    target_score = {
        "matched": 0,
        "targeted": 1,
        "virtuals": {
            "40": {
                "expected": 29,
                "actual": 26,
                "baseline_actual": 0,
                "matched": False,
            }
        },
    }
    summary = _retained_window_candidate_summary(
        {
            "probe_id": "retained_gpr_case_c_window_order_continuation@0",
            "validator_payload": {
                "source_retained": "/tmp/issue1128.c",
                "pcdump_path": "/tmp/issue1128.pcdump.txt",
                "target_score": target_score,
            },
            "target_score": target_score,
            "retained_case_c_window_order_classification": {
                "classification": "lost-protected",
                "attempted_targets": {"40": 29},
                "attempted_hits": {"40": False},
            },
        },
        {
            "payload": {
                "source_hunks": source_hunks,
                "source_probe_provenance_kind": (
                    "window-order-call-return-source-order"
                ),
                "source_attribution": {"kind": "call-return"},
                "call_return_source_probe": {
                    "handler": "call-return-owner-split",
                    "assigned_local": "cursor_gobj",
                    "call_symbol": "GObj_Create",
                },
            }
        },
    )

    assert summary["source_retained"] == "/tmp/issue1128.c"
    assert summary["pcdump_path"] == "/tmp/issue1128.pcdump.txt"
    assert summary["target_score"] == target_score
    assert summary["source_hunks"] == source_hunks
    assert summary["source_probe_provenance_kind"] == (
        "window-order-call-return-source-order"
    )
    assert summary["source_attribution_kind"] == "call-return"
    assert summary["call_return_source_probe"]["assigned_local"] == "cursor_gobj"
    assert summary["classification"]["classification"] == "lost-protected"


def test_plan_transforms_select_order_json_exact_hit_stops(tmp_path: Path) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(_retained_window_select_order_payload()))
    validator = (
        "import json; "
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'target_score': {'matched': 2, 'targeted': 2, "
        "'virtuals': {'34': {'expected': 27, 'actual': 27, 'matched': True}, "
        "'44': {'expected': 25, 'actual': 25, 'matched': True}}}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_window_order_continuation",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "1",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["validation"][0][
        "retained_case_c_window_order_classification"
    ]["classification"] == "exact"
    assert payload["validation_summary"]["stop_condition"] == (
        "exact-retained-window-order-continuation"
    )
    summary = payload["retained_case_c_window_order_continuation_summary"]
    assert summary["status"] == "exact"
    assert "terminal_blocker" not in summary


def test_plan_transforms_simplify_order_validation_reports_protected_noop(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_simplify_order_goal()
    ))
    validator = (
        "import json, pathlib, sys; "
        "p = pathlib.Path(sys.argv[1]); "
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'source_retained': str(p), "
        "'pcdump_path': str(p.with_suffix('.pcdump.txt')), "
        "'target_score': {'matched': 1, 'targeted': 2, "
        "'virtuals': {'34': {'expected': 27, 'actual': 27, 'matched': True}, "
        "'44': {'expected': 25, 'actual': 27, 'matched': False}}}, "
        "'first_divergence': {'class_id': 0, 'iter': 40, 'ig_idx': 44, "
        "'case': 'C'}, "
        "'first_divergence_movement': {'status': 'flat'}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_simplify_order_continuation",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "4",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    classifications = [
        item["retained_case_c_simplify_order_classification"]["classification"]
        for item in payload["validation"]
    ]
    assert classifications == [
        "protected-negative",
        "protected-negative",
        "protected-negative",
        "protected-negative",
    ]
    summary = payload["retained_case_c_simplify_order_continuation_summary"]
    assert summary["status"] == "exhausted"
    assert summary["protected_negative_count"] == 4
    assert summary["protected_noop_count"] == 4
    assert summary["first_divergence_moved_count"] == 0
    assert summary["terminal_blocker"] == (
        "bounded-remote-scored-exhaustion-no-simplify-order-movement"
    )
    best = summary["best_retained_candidates"][0]
    assert best["source_retained"].endswith(".c")
    assert best["pcdump_path"].endswith(".pcdump.txt")
    assert best["first_divergence"]["ig_idx"] == 44
    probe_texts = [
        path.read_text() for path in (tmp_path / "probes").glob("*.c")
    ]
    assert probe_texts
    assert all("mnDiagram_804A076C" not in text for text in probe_texts)
    assert any(
        "case_c_max_name_probe = sorted_names[max_idx];" in text
        for text in probe_texts
    )


def test_plan_transforms_lower_drift_residual_goal_writes_ig34_probes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_lower_drift_residual_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_ig34_residual_goal()
    ))

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_simplify_order_continuation",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["probes"]) == 5
    probe_payloads = [probe["payload"] for probe in payload["probes"]]
    assert {probe["attempted_targets"]["34"] for probe in probe_payloads} == {27}
    assert {probe["protected_targets"]["44"] for probe in probe_payloads} == {26}
    assert {probe["final_force_phys"]["44"] for probe in probe_payloads} == {25}
    assert {
        probe["source_probe_provenance_kind"] for probe in probe_payloads
    } == {"retained-case-c-lower-drift-residual"}
    diagnostics = {
        item["family_id"]: item for item in payload["family_diagnostics"]
    }
    simplify = diagnostics["retained_gpr_case_c_simplify_order_continuation"]
    assert simplify["matcher_diagnostics"]["attempted_targets"] == {"34": 27}
    assert simplify["matcher_diagnostics"]["protected_targets"] == {"44": 26}
    summary = payload["retained_case_c_simplify_order_continuation_summary"]
    assert summary["status"] == "materialized-not-scored"
    assert summary["kind"] == "retained-source-case-c-lower-drift-residual"


def test_plan_transforms_lower_drift_residual_validation_ranks_candidates(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_lower_drift_residual_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_ig34_residual_goal()
    ))
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import json, pathlib, sys\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "idx = int(p.stem.rsplit('@', 1)[1])\n"
        "scores = {\n"
        "  0: {'34': (27, True), '44': (26, False)},\n"
        "  1: {'34': (28, False), '44': (26, False)},\n"
        "  2: {'34': (27, True), '44': (27, False)},\n"
        "  4: {'34': (27, True), '44': (25, True)},\n"
        "}\n"
        "if idx == 3:\n"
        "    print(json.dumps({'status': 'failed'}))\n"
        "    raise SystemExit\n"
        "virtuals = {\n"
        "  ig: {'expected': 27 if ig == '34' else 25, 'actual': actual, 'matched': matched}\n"
        "  for ig, (actual, matched) in scores[idx].items()\n"
        "}\n"
        "payload = {\n"
        "  'status': 'negative-evidence',\n"
        "  'source_retained': str(p),\n"
        "  'pcdump_path': str(p.with_suffix('.pcdump.txt')),\n"
        "  'remote_fallback': {'used': True, 'host': 'test'},\n"
        "  'target_score': {'matched': sum(1 for row in virtuals.values() if row['matched']), 'targeted': 2, 'virtuals': virtuals},\n"
        "  'first_divergence': {'class_id': 0, 'iter': 4 if idx == 0 else 3, 'ig_idx': 34, 'case': 'C'},\n"
        "}\n"
        "print(json.dumps(payload))\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_simplify_order_continuation",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "5",
            "--validate-command",
            f"{sys.executable} {validator} {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    classifications = [
        item["retained_case_c_simplify_order_classification"]["classification"]
        for item in payload["validation"]
    ]
    assert classifications == [
        "residual-hit-protected-lower-drift",
        "protected-negative",
        "lost-lower-drift-progress",
        "unscoreable",
        "exact",
    ]
    summary = payload["retained_case_c_simplify_order_continuation_summary"]
    assert summary["status"] == "exact"
    assert summary["kind"] == "retained-source-case-c-lower-drift-residual"
    assert summary["residual_hit_count"] == 1
    assert summary["protected_negative_count"] == 1
    assert summary["lost_lower_drift_count"] == 1
    assert summary["unscoreable_count"] == 1
    assert summary["first_divergence_moved_count"] == 1
    best = summary["best_retained_candidates"]
    assert best[0]["classification"]["classification"] == "exact"
    assert best[1]["classification"]["classification"] == (
        "residual-hit-protected-lower-drift"
    )
    assert best[1]["remote_fallback"] == {"used": True, "host": "test"}
    assert best[1]["source_retained"].endswith(".c")
    assert best[1]["pcdump_path"].endswith(".pcdump.txt")
    assert payload["validation_summary"]["stop_condition"] == (
        "exact-retained-case-c-simplify-order"
    )


def test_lower_drift_residual_classifies_frontier_against_goal_baseline() -> None:
    probe = {
        "family_id": "retained_gpr_case_c_simplify_order_continuation",
        "payload": {
            "goal_kind": "retained-case-c-lower-drift-residual",
            "attempted_targets": {"34": 27},
            "protected_targets": {"44": 26},
            "final_force_phys": {"34": 27, "44": 25},
            "baseline_first_divergence": {
                "class_id": 0,
                "iter": 3,
                "ig_idx": 34,
            },
            "baseline_score": {
                "target_score": {
                    "virtuals": {
                        "34": {"expected": 27, "actual": 29},
                        "44": {"expected": 25, "actual": 26},
                    },
                },
            },
        },
    }
    result = {
        "validator_payload": {
            "target_score": {
                "virtuals": {
                    "34": {"expected": 27, "actual": 28, "matched": False},
                    "44": {"expected": 25, "actual": 26, "matched": False},
                },
            },
            "first_divergence": {"class_id": 0, "iter": 4, "ig_idx": 34},
        },
    }

    classification = _classify_retained_case_c_simplify_order_validation(
        probe,
        result,
    )

    assert classification is not None
    assert classification["classification"] == "lower-drift-frontier"
    assert classification["first_divergence_moved_from_goal"] is True


def test_plan_transforms_simplify_order_exact_hit_stops(tmp_path: Path) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_simplify_order_goal()
    ))
    validator = (
        "import json; "
        "print(json.dumps({"
        "'status': 'negative-evidence', "
        "'target_score': {'matched': 2, 'targeted': 2, "
        "'virtuals': {'34': {'expected': 27, 'actual': 27, 'matched': True}, "
        "'44': {'expected': 25, 'actual': 25, 'matched': True}}}, "
        "'first_divergence_movement': {'status': 'improved'}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_simplify_order_continuation",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "3",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["validation"]) == 1
    assert payload["validation"][0][
        "retained_case_c_simplify_order_classification"
    ]["classification"] == "exact"
    summary = payload["retained_case_c_simplify_order_continuation_summary"]
    assert summary["status"] == "exact"
    assert summary["stop_condition"] == "exact-retained-case-c-simplify-order"
    assert payload["validation_summary"]["stop_condition"] == (
        "exact-retained-case-c-simplify-order"
    )


def test_plan_transforms_simplify_order_unscoreable_is_not_lost_protected(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_retained_window_order_source())
    select_order = tmp_path / "select_order.json"
    select_order.write_text(json.dumps(
        _retained_window_select_order_payload_with_simplify_order_goal()
    ))
    validator = "import json; print(json.dumps({'status': 'failed'}))"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_SortNamesByKOs",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "34:27,44:25",
            "--source-file", str(source),
            "--select-order-json", str(select_order),
            "--transform-family", "retained_gpr_case_c_simplify_order_continuation",
            "--write-probes", str(tmp_path / "probes"),
            "--max-per-family", "1",
            "--validate-command",
            f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    classification = payload["validation"][0][
        "retained_case_c_simplify_order_classification"
    ]
    assert classification["classification"] == "unscoreable"
    summary = payload["retained_case_c_simplify_order_continuation_summary"]
    assert summary["unscoreable_count"] == 1
    assert summary["lost_protected_count"] == 0
    assert summary["terminal_blocker"] == "remote-retained-source-unscoreable"


def _ranked_cursor_iv_source() -> str:
    return (
        "typedef unsigned long long u64;\n"
        "typedef unsigned char u8;\n"
        "typedef struct Entry { u8 name; u64 value; } Entry;\n"
        "u8 mnDiagram2_GetRankedFighter(u8 rank) {\n"
        "    Entry entries[25];\n"
        "    u64 baseVal;\n"
        "    Entry* base;\n"
        "    Entry* ptr;\n"
        "    Entry* curr;\n"
        "    int i;\n"
        "    int k;\n"
        "    int maxIdx;\n"
        "    int neg1;\n"
        "    base = entries;\n"
        "    i = 0;\n"
        "    neg1 = -1;\n"
        "    do {\n"
        "        k = i + 1;\n"
        "        curr = &entries[k];\n"
        "        maxIdx = i;\n"
        "        baseVal = base->value;\n"
        "        while (k < 25) {\n"
        "            if (curr->value != (u64) neg1) {\n"
        "                if (curr->value > entries[maxIdx].value ||\n"
        "                    baseVal == (u64) neg1)\n"
        "                {\n"
        "                    maxIdx = k;\n"
        "                }\n"
        "            }\n"
        "            curr++;\n"
        "            k++;\n"
        "        }\n"
        "        base++;\n"
        "        i++;\n"
        "    } while (i < 25);\n"
        "    ptr = &entries[rank];\n"
        "    if (ptr->value == (u64) -1) {\n"
        "        return 25;\n"
        "    }\n"
        "    return entries[rank].name;\n"
        "}\n"
    )


def test_search_plan_transforms_writes_ranked_cursor_probes_without_force_phys(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(_ranked_cursor_iv_source())
    probes_dir = tmp_path / "ranked-cursor-probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_GetRankedFighter",
            "--unit", "melee/mn/mndiagram2",
            "--source-file", str(source),
            "--max-per-family", "4",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    ranked = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "ranked_cursor_iv_unification"
    ]
    assert [probe["mutator_key"] for probe in ranked] == [
        "unify_ranked_cursor_value_accumulator",
        "reuse_rank_pointer_return_field",
    ]
    assert all(Path(probe["candidate_path"]).is_file() for probe in ranked)


def test_search_plan_transforms_writes_callarg_local_structural_repair_candidate_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(HSD_JObj* jobj, f32 y_spacing, f32 y_offset, "
        "u8 value, u8 row) {\n"
        "    int i;\n"
        "    int digit;\n"
        "    int digit_count;\n"
        "    f32 col_offset;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 rowf;\n"
        "    f32 col_cast_owner_fpr;\n"
        "    f32 col_offset_product_fpr;\n"
        "    f32 row_offset_adj_owner_fpr;\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    col_offset_product_fpr = y_spacing * col_cast_owner_fpr;\n"
        "    col_offset = col_offset_product_fpr;\n"
        "    rowf = (f32) row;\n"
        "    row_offset *= rowf;\n"
        "    row_offset_adj_owner_fpr = row_offset - 0.4f;\n"
        "    row_offset_adj = row_offset_adj_owner_fpr;\n"
        "    for (i = 0; i < digit_count; i++) {\n"
        "        digit = mn_GetDigitAt(value, i);\n"
        "        rowf = (f32) digit;\n"
        "        HSD_JObjReqAnimAll(jobj, (f32) digit);\n"
        "        HSD_JObjAnimAll(jobj);\n"
        "    }\n"
        "}\n"
    )
    probes_dir = tmp_path / "callarg-probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_DrawCellNumber",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:33:26,1:35:26,1:40:28",
            "--source-file", str(source),
            "--transform-family", "callarg_local_structural_repair",
            "--max-per-family", "8",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    probes = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "callarg_local_structural_repair"
    ]
    assert probes
    assert all(Path(probe["candidate_path"]).is_file() for probe in probes)
    assert all("score_source" not in probe for probe in probes)
    candidates = [
        Path(probe["candidate_path"]).read_text(encoding="utf-8")
        for probe in probes
    ]
    assert any("HSD_JObjReqAnimAll(jobj, rowf);" in candidate for candidate in candidates)
    assert any("digit_frame_fpr" in candidate for candidate in candidates)


def test_search_plan_transforms_writes_fresh_callarg_local_structural_repair_candidate_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram-fresh.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_DrawCellNumber(HSD_JObj* jobj, f32 y_spacing, f32 y_offset, "
        "u8 value, u8 row) {\n"
        "    int i;\n"
        "    int digit;\n"
        "    int digit_count;\n"
        "    f32 rowf;\n"
        "    f32 digitf;\n"
        "    f32 col_offset;\n"
        "    f32 col_offset_product_fpr;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 row_offset_adj_owner_fpr;\n"
        "    f32 col_cast_owner_fpr;\n"
        "    col_offset_product_fpr = y_spacing * col_cast_owner_fpr;\n"
        "    col_offset = col_offset_product_fpr;\n"
        "    digit_count = mn_GetDigitCount(value);\n"
        "    rowf = (f32) row;\n"
        "    row_offset *= rowf;\n"
        "    row_offset_adj_owner_fpr = row_offset - 0.4f;\n"
        "    row_offset_adj = row_offset_adj_owner_fpr;\n"
        "    for (i = 0; i < digit_count; i++) {\n"
        "        digit = mn_GetDigitAt(value, i);\n"
        "        digitf = (f32) digit;\n"
        "        HSD_JObjReqAnimAll(jobj, digitf);\n"
        "        HSD_JObjAnimAll(jobj);\n"
        "    }\n"
        "    HSD_JObjSetTranslateY(jobj, row_offset_adj);\n"
        "}\n"
    )
    probes_dir = tmp_path / "fresh-callarg-probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_DrawCellNumber",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:33:26,1:35:26,1:40:28,1:41:29,1:42:29,1:43:29",
            "--source-file", str(source),
            "--transform-family", "callarg_local_structural_repair",
            "--max-per-family", "8",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    probes = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "callarg_local_structural_repair"
    ]
    assert probes
    assert all(Path(probe["candidate_path"]).is_file() for probe in probes)


def test_search_plan_transforms_generic_target_without_force_phys_errors(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generic.c"
    source.write_text("void target(void) { use(); }\n")

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "target",
            "--unit", "melee/test/generic",
            "--source-file", str(source),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "--directed-force-phys did not contain any entries" in result.output


def test_search_plan_transforms_writes_scheduler_order_probes(tmp_path: Path) -> None:
    source = tmp_path / "mndiagram3.c"
    source.write_text(
        "typedef float f32;\n"
        "void mnDiagram3_8024714C(int scroll, int limit, f32 bias, f32* values) {\n"
        "    int stat_idx;\n"
        "    int i;\n"
        "    stat_idx = scroll;\n"
        "    i = 0;\n"
        "    do {\n"
        "        f32 fi = (f32) i;\n"
        "        values[i] = fi + bias;\n"
        "        i++;\n"
        "    } while (i < limit);\n"
        "}\n"
    )
    target = tmp_path / "scheduler-target.json"
    target.write_text(json.dumps({
        "kind": "scheduler-order-target",
        "function": "mnDiagram3_8024714C",
        "target_first": {
            "opcode": "mr",
            "operands_contains": "r30,r31",
            "code_offset": "0x124",
        },
        "target_second": {
            "opcode": "lfd",
            "operands_contains": "mnDiagram3_804DC000",
            "code_offset": "0x120",
        },
        "source_region": {
            "contains": [
                "stat_idx = scroll;",
                "i = 0;",
                "do {",
                "f32 fi = (f32) i;",
            ],
        },
    }))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram3_8024714C",
            "--unit", "melee/mn/mndiagram3",
            "--source-file", str(source),
            "--scheduler-order-target", str(target),
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    scheduler_probes = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "scheduler_order_source_realizer"
    ]
    assert [probe["mutator_key"] for probe in scheduler_probes] == [
        "scheduler_anchor_iv_init_before_bias",
        "scheduler_split_float_cast_temp",
        "scheduler_empty_barrier_before_float_cast",
    ]
    assert {probe["family_id"] for probe in payload["probes"]} == {
        "scheduler_order_source_realizer"
    }
    assert scheduler_probes[0]["family_label"] == "scheduler-order source realizer"
    assert scheduler_probes[0]["target_assignments"] == ["mr before lfd"]
    assert all(Path(probe["candidate_path"]).is_file() for probe in scheduler_probes)


def test_search_plan_transforms_writes_function_codegen_pragma_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pragma_target.c"
    source.write_text(
        "void helper(void);\n"
        "\n"
        "int target(int x)\n"
        "{\n"
        "    helper();\n"
        "    return x + 1;\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "target",
            "--unit", "melee/test/target",
            "--force-phys", "1:3",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    pragma_probes = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "function_codegen_pragma_shape"
    ]
    assert len(pragma_probes) == 1
    assert pragma_probes[0]["mutator_key"] == "add_dont_inline_pragma_pair"
    candidate_path = Path(pragma_probes[0]["candidate_path"])
    assert candidate_path.is_file()
    candidate = candidate_path.read_text()
    assert "#pragma push\n#pragma dont_inline on\n" in candidate
    assert candidate.rstrip().endswith("#pragma pop")


def test_search_plan_transforms_writes_global_float_literal_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "float_target.c"
    source.write_text(
        "typedef float f32;\n"
        "static const f32 lbl_804D8000 = 0.5f;\n"
        "void target(void)\n"
        "{\n"
        "    set_scale(0.5f);\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "target",
            "--unit", "melee/test/target",
            "--force-phys", "1:3",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    float_probes = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "global_float_literal_shape"
    ]
    assert len(float_probes) == 1
    assert (
        float_probes[0]["mutator_key"]
        == "replace_float_literal_with_global_constant"
    )
    candidate_path = Path(float_probes[0]["candidate_path"])
    assert candidate_path.is_file()
    assert "set_scale(lbl_804D8000);" in candidate_path.read_text()


def test_search_plan_transforms_writes_fp_subtraction_reassociation_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fp_sub_target.c"
    source.write_text(
        "void target(void)\n"
        "{\n"
        "    draw_text(ctx, -spEC.y - 0.9f, scale);\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "target",
            "--unit", "melee/test/target",
            "--force-phys", "1:3",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    subtraction_probes = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "fp_subtraction_operand_reassociation"
    ]
    assert len(subtraction_probes) == 1
    assert subtraction_probes[0]["mutator_key"] == (
        "reassociate_fp_subtraction_operands"
    )
    candidate_path = Path(subtraction_probes[0]["candidate_path"])
    assert candidate_path.is_file()
    assert "draw_text(ctx, -0.9f - spEC.y, scale);" in candidate_path.read_text()


def test_search_plan_transforms_writes_type_cast_compatibility_probes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "type_cast_target.c"
    source.write_text(
        "typedef float f32;\n"
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
        "typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;\n"
        "void use_gobj(HSD_GObj* gobj);\n"
        "void register_cb(HSD_GObj* gobj, void (*cb)(HSD_GObj*));\n"
        "void callback(HSD_GObj* gobj);\n"
        "void target(void)\n"
        "{\n"
        "    HSD_GObj* gobj;\n"
        "    HSD_GObj* alias;\n"
        "    Point3d pos;\n"
        "    use_gobj((HSD_GObj*) gobj);\n"
        "    alias = (HSD_GObj*) gobj;\n"
        "    register_cb(gobj, (void (*)(HSD_GObj*)) callback);\n"
        "    consume_vec(pos);\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "target",
            "--unit", "melee/test/target",
            "--force-phys", "1:3",
            "--source-file", str(source),
            "--max-per-family", "6",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    by_family = {probe["family_id"]: probe for probe in payload["probes"]}
    assert {
        "redundant_pointer_cast_elision",
        "callback_cast_elision",
        "vector_alias_type_shape",
    } <= set(by_family)
    pointer_candidate = Path(
        by_family["redundant_pointer_cast_elision"]["candidate_path"]
    ).read_text()
    callback_candidate = Path(
        by_family["callback_cast_elision"]["candidate_path"]
    ).read_text()
    vector_candidate = Path(by_family["vector_alias_type_shape"]["candidate_path"]).read_text()
    assert "use_gobj(gobj);" in pointer_candidate or "alias = gobj;" in pointer_candidate
    assert "register_cb(gobj, callback);" in callback_candidate
    assert "    Vec3 pos;" in vector_candidate


def test_search_plan_transforms_resolves_unit_source_when_source_file_omitted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "test" / "target.c"
    source.parent.mkdir(parents=True)
    (repo / "configure.py").write_text("# marker\n")
    source.write_text(
        "void target(void) {\n"
        "    if (flag == 0) {\n"
        "        use_status();\n"
        "    }\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"
    monkeypatch.chdir(repo)
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "target",
            "--unit", "main/melee/test/target",
            "--force-phys", "1:3",
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Materialized probes: 0" not in result.stdout
    assert "Materialized probes:" in result.stdout
    written = list(probes_dir.glob("*.c"))
    assert written
    assert any("if (!flag)" in path.read_text() for path in written)


def test_search_plan_transforms_writes_independent_statement_order_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "order.c"
    source.write_text(
        "void target(void) {\n"
        "    s32 a;\n"
        "    s32 b;\n"
        "    s32 x;\n"
        "    s32 y;\n"
        "    a = x + 1;\n"
        "    b = y + 2;\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "target",
            "--unit", "melee/test/order",
            "--force-phys", "1:3",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    statement_probes = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "independent_statement_order"
    ]
    assert statement_probes
    candidate_path = Path(statement_probes[0]["candidate_path"])
    assert candidate_path.is_file()
    assert "    b = y + 2;\n    a = x + 1;\n" in candidate_path.read_text()


def test_search_plan_transforms_writes_concrete_coloring_register_steering_probes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "void mnDiagram2_Create(s32* a, s32 seed) {\n"
        "    s32 temp;\n"
        "    s32 rank;\n"
        "    HSD_GObj* gobj;\n"
        "    f32 y_offset;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    int j;\n"
        "    int i;\n"
        "    row_offset = y_offset * (f32) seed;\n"
        "    row_offset_adj = row_offset - 1.0f;\n"
        "    rank = seed + 1;\n"
        "    temp = rank;\n"
        "    use(gobj, temp, row_offset, row_offset_adj);\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(a[i]);\n"
        "    }\n"
        "    j = 0;\n"
        "    do {\n"
        "        sink(j, temp, gobj);\n"
        "        j++;\n"
        "    } while (j < 2);\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "58:4,35:29",
            "--source-file", str(source),
            "--max-per-family", "6",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    steering = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "coloring_register_steering"
    ]
    assert {
        "steer_fpr_dependent_product_reuse_temp",
        "steer_fpr_dependent_local_temp_split",
        "steer_rotate_local_decl_window",
        "steer_demote_local_decl_to_first_use",
    } <= {probe["mutator_key"] for probe in steering}
    assert [probe["mutator_key"] for probe in steering[:6]] == [
        "steer_fpr_dependent_product_recompute",
        "steer_fpr_dependent_product_reuse_temp",
        "steer_fpr_dependent_local_temp_split",
        "steer_fpr_dependent_product_recompute",
        "steer_rotate_local_decl_window",
        "steer_demote_local_decl_to_first_use",
    ]
    for probe in steering:
        candidate_path = Path(probe["candidate_path"])
        assert candidate_path.is_file()


def test_search_plan_transforms_writes_named_zero_local_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mncount.c"
    source.write_text(
        "typedef struct HSD_Text HSD_Text;\n"
        "void target(void) {\n"
        "    int i;\n"
        "    HSD_Text* labels[3];\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        if (labels[i] != NULL) {\n"
        "            free_text(labels[i]);\n"
        "            labels[i] = NULL;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "target",
            "--unit", "melee/mn/mncount",
            "--force-phys", "1:3",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    named_zero = [
        probe for probe in payload["probes"]
        if probe["family_id"] == "named_zero_local_shape"
    ]
    assert named_zero
    candidate_text = Path(named_zero[0]["candidate_path"]).read_text()
    assert "    HSD_Text* labels_null = NULL;\n    int i;" in candidate_text
    assert "if (labels[i] != NULL)" in candidate_text
    assert "labels[i] = labels_null;" in candidate_text


def test_search_plan_transforms_accepts_node_set_delta_and_writes_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Data { int selected; int is_name_mode; } Data;\n"
        "void mnDiagram2_Create(HSD_GObj* gobj, Data* data) {\n"
        "    int selected;\n"
        "    selected = data->selected;\n"
        "    sink(gobj, selected);\n"
        "}\n"
    )
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "mnDiagram2_Create",
            "class_id": 0,
            "missing_virtuals": [
                {
                    "target_ig": 36,
                    "current_register": "r25",
                    "desired_registers": ["r27"],
                    "source": {"expression": "gobj", "name": "gobj"},
                }
            ],
        }
    }))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "36:27",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "2",
            "--write-probes", str(probes_dir),
            "--validate-command",
            f"{sys.executable} -c \"print('match=false')\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["node_set_delta_summary"]["provided"] is True
    assert payload["node_set_delta_summary"]["bindable_count"] == 1
    probes = [
        probe for probe in payload["probes"]
        if probe["mutator_key"] == "steer_node_set_delta_split"
    ]
    assert probes
    assert Path(probes[0]["candidate_path"]).is_file()
    assert payload["validation_summary"]["stop_condition"] == (
        "exhausted-negative-evidence"
    )


def test_search_plan_transforms_stack_array_node_set_terminal_proof(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "typedef struct Entry {\n"
        "    /* +0 */ int pad0;\n"
        "    /* +4 */ int pad4;\n"
        "    /* +8 */ int x8;\n"
        "    /* +C */ int xC;\n"
        "} Entry;\n"
        "void mnDiagram2_GetRankedFighter(int k) {\n"
        "    Entry entries[25];\n"
        "    Entry* base;\n"
        "    Entry* ptr;\n"
        "    int out;\n"
        "    ptr = entries;\n"
        "    base = ptr;\n"
        "    out = entries[k].x8;\n"
        "    out = entries[k].xC;\n"
        "    use(base, out);\n"
        "}\n"
    )
    delta = tmp_path / "delta-stack-array.json"
    delta.write_text(json.dumps({
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "mnDiagram2_GetRankedFighter",
            "class_id": 0,
            "missing_virtuals": [
                {
                    "target_ig": 40,
                    "current_register": "r40",
                    "desired_registers": ["r25"],
                    "source": {
                        "kind": "implicit-temp",
                        "expression": "addi r40,r1,entries",
                    },
                },
                {
                    "target_ig": 45,
                    "current_register": "r45",
                    "desired_registers": ["r12"],
                    "source": {
                        "kind": "load/store-address",
                        "expression": "lwz r45,8(r40)",
                        "base_virtual": 40,
                        "field_offset": 8,
                    },
                },
                {
                    "target_ig": 46,
                    "current_register": "r46",
                    "desired_registers": ["r11"],
                    "source": {
                        "kind": "load/store-address",
                        "expression": "lwz r46,12(r40)",
                        "base_virtual": 40,
                        "field_offset": 12,
                    },
                },
            ],
        }
    }))
    pcdump = tmp_path / "candidate.pcdump.txt"
    pcdump.write_text("pcdump", encoding="utf-8")
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import json, sys\n"
        "print(json.dumps({\n"
        "  'target_score': {\n"
        "    'hits': 0,\n"
        "    'virtuals': {\n"
        "      '40': {'expected': 25, 'actual': 31, 'matched': False},\n"
        "      '45': {'expected': 12, 'actual': 26, 'matched': False},\n"
        "      '46': {'expected': 11, 'actual': 12, 'matched': False},\n"
        "    },\n"
        "  },\n"
        "  'source_retained': sys.argv[1],\n"
        f"  'pcdump_path': {str(pcdump)!r},\n"
        "}))\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_GetRankedFighter",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "40:25,45:12,46:11",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "3",
            "--write-probes", str(tmp_path / "probes"),
            "--validate-command",
            f"{sys.executable} {validator} {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    stack_probes = [
        probe for probe in payload["probes"]
        if probe["mutator_key"] == "steer_node_set_delta_stack_array_base_split"
    ]
    assert stack_probes
    assert stack_probes[0]["payload"]["source_hunks"]
    proof = payload["validation_summary"]["terminal_proof"]
    assert proof["terminal_reason"] == "stack-array-base-targets-not-realized"
    assert proof["target_registers"] == {
        "40": "r25",
        "45": "r12",
        "46": "r11",
    }
    assert proof["candidates"][0]["source_hunks"]
    assert proof["candidates"][0]["source_retained"].endswith(".c")
    assert proof["candidates"][0]["pcdump_path"] == str(pcdump)
    assert "stack-array-base-targets-not-realized" in (
        payload["validation_summary"].get("terminal_blockers") or []
    )


def test_stack_array_node_set_terminal_proof_requires_target_score() -> None:
    probe_payloads = [{
        "probe_id": "coloring_register_steering@0",
        "family_id": "coloring_register_steering",
        "candidate_path": "candidate.c",
        "payload": {
            "source_hunks": [{"hunk_id": "c0", "unified_diff": "@@ c0"}],
            "node_set_delta": {
                "requests": [{
                    "target_ig": 40,
                    "target_reg": "r25",
                    "source_kind": "stack-array-base",
                    "source_expression": "entries",
                }],
                "hunk": "@@ c0",
            },
        },
    }]
    validation_results = [{
        "probe_id": "coloring_register_steering@0",
        "family_id": "coloring_register_steering",
        "outcome": "blocked",
        "validator_payload": {"source_retained": "candidate.c"},
    }]

    assert _stack_array_node_set_terminal_proof(
        probe_payloads,
        validation_results,
    ) is None


def test_search_plan_transforms_accepts_fpr_node_set_delta_and_writes_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef float f32;\n"
        "void mnDiagram_80241E78(void) {\n"
        "    f32 x_spacing;\n"
        "    f32 col_offset;\n"
        "    f32 digit_offset;\n"
        "    digit_offset = x_spacing + col_offset;\n"
        "    use(digit_offset);\n"
        "}\n"
    )
    delta = tmp_path / "delta-fpr.json"
    delta.write_text(json.dumps({
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "mnDiagram_80241E78",
            "class_id": 1,
            "missing_virtuals": [
                {
                    "target_ig": 33,
                    "current_register": "f31",
                    "desired_registers": ["f28"],
                    "source": {
                        "expression": "digit_offset",
                        "name": "digit_offset",
                    },
                }
            ],
        }
    }))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_80241E78",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:33:28",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "10",
            "--write-probes", str(probes_dir),
            "--validate-command",
            f"{sys.executable} -c \"print('match=false')\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["node_set_delta_summary"]["provided"] is True
    assert payload["node_set_delta_summary"]["bindable_count"] == 1
    probes = [
        probe for probe in payload["probes"]
        if probe["mutator_key"] == "steer_node_set_delta_split"
    ]
    assert probes
    request = probes[0]["payload"]["node_set_delta"]["requests"][0]
    assert request["class_id"] == 1
    assert request["current_reg"] == "f31"
    assert request["target_reg"] == "f28"
    candidates = [
        Path(probe["candidate_path"]).read_text(encoding="utf-8")
        for probe in probes
    ]
    assert any(
        "digit_offset = col_offset + x_spacing;" in candidate
        for candidate in candidates
    )


def test_search_plan_transforms_node_set_delta_reports_bounded_stop_condition(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "void mnDiagram2_Create(void) {\n"
        "    int first;\n"
        "    int second;\n"
        "    int out;\n"
        "    first = make();\n"
        "    second = make();\n"
        "    out = first + second;\n"
        "    sink(out);\n"
        "}\n"
    )
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 41,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {"expression": "first", "name": "first"},
            },
            {
                "target_ig": 42,
                "current_register": "r30",
                "desired_registers": ["r28"],
                "source": {"expression": "second", "name": "second"},
            },
        ],
    }))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "41:27,42:28",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    node_set_probes = [
        probe for probe in payload["probes"]
        if probe["mutator_key"].startswith("steer_node_set_delta")
    ]
    assert len(node_set_probes) == 1
    assert Path(node_set_probes[0]["candidate_path"]).is_file()
    assert payload["planning_summary"] == {
        "stop_condition": "node-set-delta-budget-filled",
        "node_set_probe_count": 1,
        "max_per_family": 1,
    }


def test_search_plan_transforms_reports_all_unbindable_node_set_delta(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text("void mnDiagram2_Create(void) { sink(); }\n")
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 51,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {"kind": "implicit-temp", "expression": "add r51,r45,r63"},
            }
        ],
    }))

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "51:27",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "2",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    summary = payload["node_set_delta_summary"]
    assert summary["provided"] is True
    assert summary["bindable_count"] == 0
    assert summary["skipped_count"] == 1
    assert summary["skipped_missing_virtuals"][0]["target_ig"] == 51


def test_search_plan_transforms_writes_introduce_binding_node_set_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void mnDiagram2_Create(Entry* entries, int i) {\n"
        "    int out;\n"
        "    out = entries[i].stat_value;\n"
        "    sink(out);\n"
        "}\n"
    )
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 42,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {
                    "kind": "field-load",
                    "expression": "entries[i].stat_value",
                },
                "source_action": "Hoist field load before use.",
            }
        ],
    }))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "42:27",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "4",
            "--write-probes", str(probes_dir),
            "--validate-command",
            f"{sys.executable} -c \"print('match=false')\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    summary = payload["node_set_delta_summary"]
    assert summary["provided"] is True
    assert summary["bindable_count"] == 0
    assert summary["introducible_count"] == 1
    assert summary["skipped_count"] == 0
    probes = [
        probe for probe in payload["probes"]
        if probe["mutator_key"] == "steer_node_set_delta_introduce_binding_split"
    ]
    assert probes
    request = probes[0]["payload"]["node_set_delta"]["requests"][0]
    assert request["target_ig"] == 42
    assert request["source_expression"] == "entries[i].stat_value"
    assert request["raw_missing_virtual"]["source_action"] == (
        "Hoist field load before use."
    )
    candidate = Path(probes[0]["candidate_path"]).read_text(encoding="utf-8")
    assert "int stat_value_bind_42_0;" in candidate
    assert "stat_value_bind_42_0 = entries[i].stat_value;" in candidate
    assert "out = stat_value_bind_42_0;" in candidate
    replacement_text = probes[0]["payload"]["replacement_text"]
    assert replacement_text == candidate
    assert "sink(out);" in replacement_text


def test_search_plan_transforms_dedupes_mixed_node_set_delta_skips(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "typedef struct HSD_GObj HSD_GObj;\n"
        "void mnDiagram2_Create(HSD_GObj* gobj) {\n"
        "    sink(gobj);\n"
        "}\n"
    )
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 36,
                "current_register": "r25",
                "desired_registers": ["r27"],
                "source": {"expression": "gobj", "name": "gobj"},
            },
            {
                "target_ig": 51,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {"kind": "implicit-temp", "expression": "add r51,r45,r63"},
            },
        ],
    }))

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "36:27,51:27",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "2",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    summary = payload["node_set_delta_summary"]
    assert summary["missing_count"] == 2
    assert summary["bindable_count"] == 1
    assert summary["skipped_count"] == 1
    assert [
        entry["target_ig"]
        for entry in summary["skipped_missing_virtuals"]
    ] == [51]


def test_search_plan_transforms_reports_bindable_node_set_delta_without_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "typedef struct HSD_GObj HSD_GObj;\n"
        "void mnDiagram2_Create(HSD_GObj* gobj) {\n"
        "    sink(gobj);\n"
        "}\n"
    )
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 36,
                "current_register": "r25",
                "desired_registers": ["r27"],
                "source": {"expression": "gobj", "name": "gobj"},
            }
        ],
    }))

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "36:27",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert not [
        probe for probe in payload["probes"]
        if probe["mutator_key"].startswith("steer_node_set_delta")
    ]
    summary = payload["node_set_delta_summary"]
    assert summary["provided"] is True
    assert summary["bindable_count"] == 1
    assert summary["skipped_count"] == 0
    assert summary["skipped_missing_virtuals"] == []
    assert summary["omitted_count"] == 1
    assert summary["omitted_missing_virtuals"][0]["target_ig"] == 36
    assert summary["omitted_missing_virtuals"][0]["omitted_reason"] == (
        "no node-set probe materialized"
    )


def test_search_plan_transforms_writes_raw_index_struct_field_and_data_table_indirection_probes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "indexed_tables.c"
    source.write_text(
        "typedef unsigned char u8;\n"
        "typedef int s32;\n"
        "typedef struct Entry {\n"
        "    u8 pad0[0x10];\n"
        "    s32 voice_id;\n"
        "    s32 entity;\n"
        "} Entry;\n"
        "extern s32 table_a[];\n"
        "extern s32 table_b[];\n"
        "extern s32 table_c[];\n"
        "static s32* const sOuterTable[] = { table_a, table_b, table_c };\n"
        "\n"
        "void target(Entry* entries, s32 i, s32 idx, s32 value) {\n"
        "    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n"
        "    *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x14) = value;\n"
        "    value = table_b[idx];\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "target",
            "--unit", "melee/test/target",
            "--force-phys", "1:3",
            "--source-file", str(source),
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    by_family = {probe["family_id"]: probe for probe in payload["probes"]}
    for family_id in (
        "raw_index_struct_field_shape",
        "data_table_indirection_shape",
    ):
        assert family_id in by_family
        candidate_path = Path(by_family[family_id]["candidate_path"])
        assert candidate_path.is_file()


def test_search_plan_transforms_can_record_no_probe_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "placeholder.c"
    source.write_text(
        "void helper(void) {\n"
        "    if (a) {\n"
        "        x = 1;\n"
        "    } else if (b) {\n"
        "        x = 2;\n"
        "    }\n"
        "}\n"
        "/// #ftCo_8009E7B4\n"
    )
    ledger = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--force-phys", "58:4,35:29",
            "--source-file", str(source),
            "--record-ledger",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ledger_record"]["outcome"] == "blocked"
    data = json.loads(ledger.read_text())
    attempt = data["functions"]["ftCo_8009E7B4"]["attempts"][0]
    assert attempt["outcome"] == "blocked"
    assert attempt["classification"] == "transform-corpus"
    assert "no materialized probes" in attempt["blocker"]
    assert "early_flag_reload" in attempt["note"]


def test_search_plan_transforms_validates_generated_probes(tmp_path: Path) -> None:
    source = tmp_path / "e7b4.c"
    source.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    if (flag) {\n"
        "        reload = 1;\n"
        "    } else {\n"
        "        if (kind != 0) {\n"
        "            reload = 0;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    probes_dir = tmp_path / "probes"
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftcommon",
            "--force-phys", "58:4,35:29",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
            "--validate-command",
            (
                f"{sys.executable} -c \"import pathlib,sys; "
                "p=pathlib.Path(sys.argv[1]); print('match=true' if p.exists() else 'missing')\" "
                "{candidate_path}"
            ),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["validation"]
    first = payload["validation"][0]
    assert first["outcome"] == "retained-source-improvement"
    assert first["returncode"] == 0
    assert first["probe_id"] == payload["probes"][0]["probe_id"]


def test_search_plan_transforms_records_retained_validation_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "e7b4.c"
    source.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    if (flag) {\n"
        "        reload = 1;\n"
        "    } else {\n"
        "        if (kind != 0) {\n"
        "            reload = 0;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    ledger = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftcommon",
            "--force-phys", "58:4,35:29",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(tmp_path / "probes"),
            "--validate-command",
            (
                f"{sys.executable} -c \"import pathlib,sys; "
                "p=pathlib.Path(sys.argv[1]); print('match=true' if p.exists() else 'missing')\" "
                "{candidate_path}"
            ),
            "--record-ledger",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ledger_record"]["outcome"] == "improved"
    data = json.loads(ledger.read_text())
    attempt = data["functions"]["ftCo_8009E7B4"]["attempts"][0]
    assert attempt["outcome"] == "improved"
    assert attempt["retained"] is True
    assert "retained-source-improvement" in attempt["note"]


def test_search_plan_transforms_captures_structured_validation_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "e7b4.c"
    source.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    if (flag) {\n"
        "        reload = 1;\n"
        "    } else {\n"
        "        if (kind != 0) {\n"
        "            reload = 0;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    ledger = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftcommon",
            "--force-phys", "58:4,35:29",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(tmp_path / "probes"),
            "--validate-command",
            (
                f"{sys.executable} -c \"import json; "
                "print(json.dumps({'match': True, 'match_percent': 96.25, "
                "'target_assignment_movement': {'ig58->r4': 'satisfied'}}))\" "
                "{candidate_path}"
            ),
            "--record-ledger",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    first = payload["validation"][0]
    assert first["outcome"] == "retained-source-improvement"
    assert first["match_percent"] == 96.25
    assert first["target_assignment_movement"] == {"ig58->r4": "satisfied"}
    assert first["evidence"] == {
        "probe_id": first["probe_id"],
        "family_id": first["family_id"],
        "family_label": payload["probes"][0]["family_label"],
        "outcome": "retained-source-improvement",
        "semantic_risk": payload["probes"][0]["semantic_risk"],
        "source_region": payload["probes"][0]["source_region"],
        "target_assignments": list(payload["probes"][0]["target_assignments"]),
        "expected_compiler_effect": payload["probes"][0]["expected_compiler_effect"],
        "match_percent": 96.25,
        "target_assignment_movement": {"ig58->r4": "satisfied"},
        "recommendation": None,
        "source_regions": None,
        "uncovered_transform_classes": None,
    }
    assert payload["validation_summary"]["evidence_counts"] == {
        "retained-source-improvement": len(payload["validation"])
    }
    assert payload["ledger_record"]["match_percent"] == 96.25
    data = json.loads(ledger.read_text())
    attempt = data["functions"]["ftCo_8009E7B4"]["attempts"][0]
    assert attempt["match_percent"] == 96.2
    assert "movement=ig58->r4:satisfied" in attempt["note"]


def test_search_plan_transforms_validation_evidence_preserves_target_score(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Data { int selected; int is_name_mode; } Data;\n"
        "void mnDiagram2_Create(HSD_GObj* gobj, Data* data) {\n"
        "    int selected;\n"
        "    selected = data->selected;\n"
        "    sink(gobj, selected);\n"
        "}\n"
    )
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "mnDiagram2_Create",
            "class_id": 0,
            "missing_virtuals": [{
                "target_ig": 36,
                "current_register": "r25",
                "desired_registers": ["r27"],
                "source": {"expression": "gobj", "name": "gobj"},
            }],
        }
    }))
    probes_dir = tmp_path / "probes"
    validator = (
        "import json; "
        "print(json.dumps({"
        "'status':'negative-evidence',"
        "'target_score':{'matched':4,'targeted':6,'virtuals':{'46':{'expected':26,'actual':1,'matched':False}}}"
        "}))"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "36:27",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(probes_dir),
            "--validate-command", f"{sys.executable} -c \"{validator}\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    evidence = payload["validation"][0]["evidence"]
    assert evidence["target_score"]["matched"] == 4
    assert evidence["target_score"]["virtuals"]["46"]["actual"] == 1


def test_search_plan_transforms_records_larger_refactor_recommendation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "e7b4.c"
    source.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    if (flag) {\n"
        "        reload = 1;\n"
        "    } else {\n"
        "        if (kind != 0) {\n"
        "            reload = 0;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    ledger = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftcommon",
            "--force-phys", "58:4,35:29",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(tmp_path / "probes"),
            "--validate-command",
            (
                f"{sys.executable} -c \"import json; "
                "print(json.dumps({'outcome': 'larger-refactor', "
                "'source_regions': ['early flag/reload block'], "
                "'uncovered_transform_classes': ['helper_shape']}))\" "
                "{candidate_path}"
            ),
            "--record-ledger",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["validation"][0]["outcome"] == "larger-refactor-recommended"
    record = payload["ledger_record"]
    assert record["outcome"] == "blocked"
    assert "larger refactor" in record["blocker"]
    data = json.loads(ledger.read_text())
    attempt = data["functions"]["ftCo_8009E7B4"]["attempts"][0]
    assert "source_regions=early flag/reload block" in attempt["note"]
    assert "uncovered=helper_shape" in attempt["note"]


def test_search_plan_transforms_can_stop_after_retained_probe(tmp_path: Path) -> None:
    source = tmp_path / "e7b4.c"
    source.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    if (flag) {\n"
        "        reload = 1;\n"
        "    } else {\n"
        "        if (kind != 0) {\n"
        "            reload = 0;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftcommon",
            "--force-phys", "58:4,35:29",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(tmp_path / "probes"),
            "--validate-command",
            f"{sys.executable} -c \"print('match=true')\" {{candidate_path}}",
            "--stop-on-retained",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["probes"]) > 1
    assert len(payload["validation"]) == 1
    assert payload["validation_summary"]["stop_condition"] == "retained-source-improvement"
    assert payload["validation_summary"]["evaluated_probes"] == 1
    assert payload["validation_summary"]["remaining_probe_ids"]


def test_search_plan_transforms_summarizes_exhausted_negative_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "e7b4.c"
    source.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    if (flag) {\n"
        "        reload = 1;\n"
        "    } else {\n"
        "        if (kind != 0) {\n"
        "            reload = 0;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    runner = CliRunner()

    result = runner.invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftcommon",
            "--force-phys", "58:4,35:29",
            "--source-file", str(source),
            "--max-per-family", "1",
            "--write-probes", str(tmp_path / "probes"),
            "--validate-command",
            f"{sys.executable} -c \"print('match=false')\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["validation"]
    assert payload["validation_summary"]["stop_condition"] == "exhausted-negative-evidence"
    assert payload["validation_summary"]["remaining_probe_ids"] == []


def test_search_triage_clusters_source_deltas_and_scores_candidates(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    int flag = fp->x594_b4;\n"
        "    for (int i = 0; i < count; i++) {\n"
        "        if (flag) sink(tree);\n"
        "    }\n"
        "}\n"
    )
    natural = tmp_path / "naturalized.c"
    natural.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    int reload = fp->x594_b4;\n"
        "    int flag = reload != 0;\n"
        "    for (int i = 0; i < count; i++) {\n"
        "        if (flag) sink(tree);\n"
        "    }\n"
        "}\n"
    )
    late = tmp_path / "late.c"
    late.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "#line 99 \"generated\"\n"
        "    int var_42 = fp->x594_b3;\n"
        "    goto generated_label;\n"
        "generated_label:\n"
        "    for (int idx = count; idx != 0; --idx) sink(tree->next);\n"
        "}\n"
    )
    telemetry = tmp_path / "telemetry.json"
    telemetry.write_text(json.dumps({
        "directed_telemetry": [
            {
                "candidate_id": "naturalized",
                "byte_score": 2036,
                "proof_assignments": {
                    "satisfied": [
                        {"original_ig": 42, "desired_phys": 3, "assigned_phys": 3},
                        {"original_ig": 44, "desired_phys": 4, "assigned_phys": 4},
                    ],
                    "blocked": [
                        {"original_ig": 35, "desired_phys": 30, "assigned_phys": 29},
                    ],
                    "abstained": [],
                },
            },
            {
                "candidate_id": "late",
                "byte_score": 2036,
                "proof_assignments": {
                    "satisfied": [
                        {"original_ig": 35, "desired_phys": 30, "assigned_phys": 30},
                    ],
                    "blocked": [],
                    "abstained": [
                        {"original_ig": 56, "desired_phys": 29, "reason": "not_reanchored"},
                    ],
                },
            },
        ]
    }))
    score_script = tmp_path / "score_candidate.py"
    score_script.write_text(
        "import json, sys\n"
        "print(json.dumps({'candidate': sys.argv[1], 'byte_score': 2036}))\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "triage",
            "--base", str(base),
            "--candidate", f"naturalized={natural}",
            "--candidate", f"late={late}",
            "--telemetry", str(telemetry),
            "--score-command", f"{sys.executable} {score_script} {{candidate}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    naturalized = payload["candidates"][0]
    assert naturalized["candidate_id"] == "naturalized"
    assert naturalized["assignment_progress"]["satisfied"] == [
        "ig42->r3",
        "ig44->r4",
    ]
    assert "early flag/reload temps" in naturalized["assignment_clusters"]
    assert any(
        delta["kind"] == "field-bit/predicate-shape"
        for delta in naturalized["source_deltas"]
    )
    assert naturalized["score_result"]["parsed_json"]["byte_score"] == 2036

    late_payload = payload["candidates"][1]
    assert "late x594_b4/x594_b3 loop IV/tree-pointer swaps" in late_payload[
        "assignment_clusters"
    ]
    assert "preprocessor-line-marker" in late_payload["generated_artifacts"]
    assert "unnatural-goto-label" in late_payload["generated_artifacts"]
    assert any(
        "Remove generated control-flow scaffolding" in suggestion
        for suggestion in late_payload["naturalization_suggestions"]
    )


def test_search_combine_recombines_complementary_candidate_deltas(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    int flag = fp->x594_b4;\n"
        "    sink(flag);\n"
        "    for (int i = 0; i < count; i++) {\n"
        "        sink(tree);\n"
        "    }\n"
        "}\n"
    )
    early = tmp_path / "early.c"
    early.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    int reload = fp->x594_b4;\n"
        "    int flag = reload != 0;\n"
        "    sink(flag);\n"
        "    for (int i = 0; i < count; i++) {\n"
        "        sink(tree);\n"
        "    }\n"
        "}\n"
    )
    late = tmp_path / "late.c"
    late.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    int flag = fp->x594_b4;\n"
        "    sink(flag);\n"
        "    for (int idx = count; idx != 0; --idx) {\n"
        "        sink(tree->next);\n"
        "    }\n"
        "}\n"
    )
    telemetry = tmp_path / "telemetry.json"
    telemetry.write_text(json.dumps({
        "directed_telemetry": [
            {
                "candidate_id": "early",
                "byte_score": 2036,
                "proof_assignments": {
                    "satisfied": [
                        {"original_ig": 42, "desired_phys": 3, "assigned_phys": 3},
                        {"original_ig": 44, "desired_phys": 4, "assigned_phys": 4},
                    ],
                    "blocked": [],
                    "abstained": [],
                },
            },
            {
                "candidate_id": "late",
                "byte_score": 2036,
                "proof_assignments": {
                    "satisfied": [
                        {"original_ig": 35, "desired_phys": 30, "assigned_phys": 30},
                    ],
                    "blocked": [],
                    "abstained": [],
                },
            },
        ]
    }))
    score_script = tmp_path / "score_candidate.py"
    score_script.write_text(
        "import json, pathlib, sys\n"
        "text = pathlib.Path(sys.argv[1]).read_text()\n"
        "print(json.dumps({\n"
        "  'score': 7,\n"
        "  'target_score': {'matched': 2, 'targeted': 3},\n"
        "  'pcdump_path': sys.argv[1] + '.pcdump.txt',\n"
        "  'structural_guard': {'accepted': True},\n"
        "  'function': 'ftCo_8009E7B4',\n"
        "  'target': 'target-spec.json',\n"
        "  'cflags_unit': 'src/melee/ft/ftcommon.c',\n"
        "  'byte_score': 2028,\n"
        "  'opcode_preservation': 'unknown',\n"
        "  'has_early': 'reload != 0' in text,\n"
        "  'has_late': 'tree->next' in text,\n"
        "}))\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"early={early}",
            "--candidate", f"late={late}",
            "--telemetry", str(telemetry),
            "--out-dir", str(tmp_path / "combined"),
            "--score-command", f"{sys.executable} {score_script} {{candidate}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "terminal_summary" not in payload
    assert payload["combinations"][0]["parents"] == ["early", "late"]
    assert payload["combinations"][0]["merge_strategy"] == "non-overlap"
    assert payload["combinations"][0]["attribution"] == "multi-cluster interaction"
    assert payload["combinations"][0]["assignment_union"]["satisfied"] == [
        "ig35->r30",
        "ig42->r3",
        "ig44->r4",
    ]
    assert "early flag/reload temps" in payload["combinations"][0]["clusters"]
    assert (
        "late x594_b4/x594_b3 loop IV/tree-pointer swaps"
        in payload["combinations"][0]["clusters"]
    )
    combined_path = Path(payload["combinations"][0]["path"])
    combined_text = combined_path.read_text()
    assert "int flag = reload != 0;" in combined_text
    assert "sink(tree->next);" in combined_text
    assert payload["combinations"][0]["score_result"]["parsed_json"] == {
        "score": 7,
        "target_score": {"matched": 2, "targeted": 3},
        "pcdump_path": str(combined_path) + ".pcdump.txt",
        "structural_guard": {"accepted": True},
        "function": "ftCo_8009E7B4",
        "target": "target-spec.json",
        "cflags_unit": "src/melee/ft/ftcommon.c",
        "byte_score": 2028,
        "opcode_preservation": "unknown",
        "has_early": True,
        "has_late": True,
    }
    combo = payload["combinations"][0]
    assert combo["score"] == 7
    assert combo["target_score"] == {"matched": 2, "targeted": 3}
    assert combo["pcdump_path"] == str(combined_path) + ".pcdump.txt"
    assert combo["structural_guard"] == {"accepted": True}
    continuation = combo["continuation"]
    assert continuation["kind"] == "score-retained-source"
    assert continuation["source_retained"] == str(combined_path)
    assert continuation["pcdump_path"] == str(combined_path) + ".pcdump.txt"
    assert "--retain-pcdump" in continuation["score_command"]
    assert "debug target score-source" in continuation["score_command"]
    assert str(combined_path) in continuation["score_command"]


def test_search_combine_reports_protected_structural_synthesis_terminal(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int a = A();\n"
        "    int b = B();\n"
        "    int c = C();\n"
        "    sink(a, b, c);\n"
        "}\n"
    )
    lower = tmp_path / "lower.c"
    lower.write_text(
        "void demo(void) {\n"
        "    int a = A_lower();\n"
        "    int b = B();\n"
        "    int c = C();\n"
        "    sink(a, b, c);\n"
        "}\n"
    )
    preserve = tmp_path / "preserve.c"
    preserve.write_text(
        "void demo(void) {\n"
        "    int a = A();\n"
        "    int b = B();\n"
        "    int c = C_preserve();\n"
        "    sink(a, b, c);\n"
        "}\n"
    )
    type_variant = tmp_path / "type.c"
    type_variant.write_text(
        "void demo(void) {\n"
        "    int a = A();\n"
        "    int b = B_type();\n"
        "    int c = C();\n"
        "    sink(a, b, c);\n"
        "}\n"
    )
    score_script = tmp_path / "score.py"
    score_script.write_text(
        "import json, pathlib, sys\n"
        "text = pathlib.Path(sys.argv[1]).read_text()\n"
        "lost = 'A_lower' in text\n"
        "ndiff = 52 if lost else 53\n"
        "satisfied = [] if lost else [\n"
        "  {'original_ig': 34, 'desired_phys': 27, 'assigned_phys': 27},\n"
        "  {'original_ig': 44, 'desired_phys': 25, 'assigned_phys': 25},\n"
        "]\n"
        "actual34 = 29 if lost else 27\n"
        "actual44 = 27 if lost else 25\n"
        "print(json.dumps({\n"
        "  'proof_assignments': {'satisfied': satisfied},\n"
        "  'target_score': {\n"
        "    'total': 120.0 if lost else 0.0,\n"
        "    'virtuals': {\n"
        "      '34': {'expected': 27, 'actual': actual34, 'matched': not lost},\n"
        "      '44': {'expected': 25, 'actual': actual44, 'matched': not lost},\n"
        "    },\n"
        "  },\n"
        "  'structural_guard': {\n"
        "    'accepted': False,\n"
        "    'normalized_diff_lines': ndiff,\n"
        "    'opcode_similarity': 0.72,\n"
        "  },\n"
        "}))\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"lower={lower}",
            "--candidate", f"preserve={preserve}",
            "--candidate", f"type={type_variant}",
            "--out-dir", str(tmp_path / "combined"),
            "--score-command", f"{sys.executable} {score_script} {{candidate}}",
            "--protect-assignment", "34:27",
            "--protect-assignment", "44:25",
            "--max-normalized-diff-lines", "52",
            "--source-component", "pointer-walk-store",
            "--source-component", "condition-temp-owner-split",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    synthesis = payload["protected_structural_synthesis"]
    assert synthesis["status"] == "terminal-component-subset-exhausted"
    assert synthesis["terminal_blocker"] == (
        "protected-structural-synthesis-exhausted"
    )
    assert synthesis["required_assignments"] == {"34": 27, "44": 25}
    assert synthesis["max_normalized_diff_lines"] == 52
    assert synthesis["source_components"] == [
        "pointer-walk-store",
        "condition-temp-owner-split",
    ]
    assert synthesis["best_preserving_candidate"]["normalized_diff_lines"] == 53
    assert synthesis["lower_drift_lost_protected_candidates"][0][
        "normalized_diff_lines"
    ] == 52
    assert "lower-drift-candidates-lost-protected-assignments" in synthesis[
        "terminal_blockers"
    ]
    assert "preserving-candidates-did-not-beat-structural-target" in synthesis[
        "terminal_blockers"
    ]


def test_search_combine_reports_protected_structural_synthesis_candidate_found(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int a = A();\n"
        "    int b = B();\n"
        "    sink(a, b);\n"
        "}\n"
    )
    left = tmp_path / "left.c"
    left.write_text(
        "void demo(void) {\n"
        "    int a = A_left();\n"
        "    int b = B();\n"
        "    sink(a, b);\n"
        "}\n"
    )
    right = tmp_path / "right.c"
    right.write_text(
        "void demo(void) {\n"
        "    int a = A();\n"
        "    int b = B_right();\n"
        "    sink(a, b);\n"
        "}\n"
    )
    score_script = tmp_path / "score.py"
    score_script.write_text(
        "import json\n"
        "print(json.dumps({\n"
        "  'proof_assignments': {'satisfied': []},\n"
        "  'target_score': {\n"
        "    'total': 0.0,\n"
        "    'virtuals': {\n"
        "      '34': {'expected': 27, 'actual': 27, 'hit': True},\n"
        "      '44': {'expected': 25, 'actual': 25, 'hit': True},\n"
        "    },\n"
        "  },\n"
        "  'structural_guard': {'normalized_diff_lines': 52},\n"
        "}))\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"left={left}",
            "--candidate", f"right={right}",
            "--out-dir", str(tmp_path / "combined"),
            "--score-command", f"{sys.executable} {score_script} {{candidate}}",
            "--protect-assignment", "34:27",
            "--protect-assignment", "44:25",
            "--max-normalized-diff-lines", "52",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    synthesis = payload["protected_structural_synthesis"]
    assert synthesis["status"] == "candidate-found"
    assert synthesis["best_candidate"]["protected_assignments_satisfied"] is True
    assert synthesis["best_candidate"]["normalized_diff_lines"] == 52


def test_search_combine_keeps_protected_synthesis_nonterminal_without_scores(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int a = A();\n"
        "    int b = B();\n"
        "    sink(a, b);\n"
        "}\n"
    )
    left = tmp_path / "left.c"
    left.write_text(
        "void demo(void) {\n"
        "    int a = A_left();\n"
        "    int b = B();\n"
        "    sink(a, b);\n"
        "}\n"
    )
    right = tmp_path / "right.c"
    right.write_text(
        "void demo(void) {\n"
        "    int a = A();\n"
        "    int b = B_right();\n"
        "    sink(a, b);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"left={left}",
            "--candidate", f"right={right}",
            "--out-dir", str(tmp_path / "combined"),
            "--protect-assignment", "34:27",
            "--max-normalized-diff-lines", "52",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    synthesis = payload["protected_structural_synthesis"]
    assert synthesis["status"] == "incomplete-score-coverage"
    assert synthesis["terminal_blocker"] == "incomplete-score-coverage"
    assert synthesis["score_coverage"]["evaluable_combinations"] == 0
    assert synthesis["score_coverage"]["unevaluable_combinations"] == 1


def test_search_combine_merges_overlapping_local_introductions(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    left = get_left();\n"
        "    right = get_right();\n"
        "    out = left + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    left_candidate = tmp_path / "left.c"
    left_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    int left_bind_38_0;\n"
        "    left = get_left();\n"
        "    right = get_right();\n"
        "    left_bind_38_0 = left;\n"
        "    out = left_bind_38_0 + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    right_candidate = tmp_path / "right.c"
    right_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    int right_bind_46_0;\n"
        "    left = get_left();\n"
        "    right = get_right();\n"
        "    right_bind_46_0 = right;\n"
        "    out = left + right_bind_46_0;\n"
        "    sink(out);\n"
        "}\n"
    )
    score_script = tmp_path / "score_candidate.py"
    score_script.write_text(
        "import json, pathlib, sys\n"
        "text = pathlib.Path(sys.argv[1]).read_text()\n"
        "print(json.dumps({\n"
        "  'has_left_decl': 'int left_bind_38_0;' in text,\n"
        "  'has_right_decl': 'int right_bind_46_0;' in text,\n"
        "  'has_left_bind': 'left_bind_38_0 = left;' in text,\n"
        "  'has_right_bind': 'right_bind_46_0 = right;' in text,\n"
        "  'has_composed_assignment': 'out = left_bind_38_0 + right_bind_46_0;' in text,\n"
        "}))\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"left={left_candidate}",
            "--candidate", f"right={right_candidate}",
            "--out-dir", str(tmp_path / "combined"),
            "--score-command", f"{sys.executable} {score_script} {{candidate}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    combo = payload["combinations"][0]
    assert combo["status"] == "ok"
    assert combo["merge_strategy"] == "compatible-overlap"
    merged_text = Path(combo["path"]).read_text()
    assert "    int left_bind_38_0;\n" in merged_text
    assert "    int right_bind_46_0;\n" in merged_text
    assert "    left_bind_38_0 = left;\n" in merged_text
    assert "    right_bind_46_0 = right;\n" in merged_text
    assert merged_text.count("    out = left_bind_38_0 + right_bind_46_0;\n") == 1
    assert combo["score_result"]["parsed_json"] == {
        "has_left_decl": True,
        "has_right_decl": True,
        "has_left_bind": True,
        "has_right_bind": True,
        "has_composed_assignment": True,
    }


def test_search_combine_still_skips_incompatible_overlaps(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    minus_candidate = tmp_path / "minus.c"
    minus_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left - right;\n"
        "    sink(out);\n"
        "}\n"
    )
    multiply_candidate = tmp_path / "multiply.c"
    multiply_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left * right;\n"
        "    sink(out);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"minus={minus_candidate}",
            "--candidate", f"multiply={multiply_candidate}",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    combo = payload["combinations"][0]
    assert combo["status"] == "skipped"
    assert combo["reason"] == "overlapping-source-hunks"


def test_search_combine_reports_all_overlap_terminal_summary(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    minus_candidate = tmp_path / "minus.c"
    minus_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left - right;\n"
        "    sink(out);\n"
        "}\n"
    )
    multiply_candidate = tmp_path / "multiply.c"
    multiply_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left * right;\n"
        "    sink(out);\n"
        "}\n"
    )
    xor_candidate = tmp_path / "xor.c"
    xor_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left ^ right;\n"
        "    sink(out);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"minus={minus_candidate}",
            "--candidate", f"multiply={multiply_candidate}",
            "--candidate", f"xor={xor_candidate}",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    summary = payload["terminal_summary"]
    assert summary["status"] == "blocked"
    assert summary["dominant_blocker"] == "recombine-overlapping-source-hunks"
    assert summary["terminal_blocker"] == "manual-subhunk-recombine-required"
    assert summary["skipped_count"] == 3
    assert sorted(tuple(pair) for pair in summary["skipped_parent_pairs"]) == [
        ("minus", "multiply"),
        ("minus", "xor"),
        ("multiply", "xor"),
    ]
    assert "--range" in summary["manual_range_hint"]
    assert summary["next_actions"][0]["kind"] == "manual-subhunk-recombine"
    assert "debug search combine" in summary["next_actions"][0]["command_hint"]
    assert "--range" in summary["next_actions"][0]["command_hint"]
    spans_by_parent = {
        entry["candidate_id"]: entry["hunk_spans"]
        for entry in summary["parent_hunk_spans"]
    }
    assert set(spans_by_parent) == {"minus", "multiply", "xor"}
    assert all(
        "base_start" in span and "base_end" in span
        for spans in spans_by_parent.values()
        for span in spans
    )


def test_search_combine_terminal_summary_zero_width_hunks_round_trip_as_insertions() -> None:
    summary = _combine_terminal_summary(
        [{
            "parents": ["insert", "replace"],
            "status": "skipped",
            "reason": "overlapping-source-hunks",
        }],
        [
            {
                "candidate_id": "insert",
                "path": Path("/tmp/insert.c"),
                "hunks": [{
                    "hunk": 1,
                    "kind": "local-introduction",
                    "base_start": 2,
                    "base_end": 2,
                    "candidate_start": 2,
                    "candidate_end": 3,
                }],
            },
            {
                "candidate_id": "replace",
                "path": Path("/tmp/replace.c"),
                "hunks": [{
                    "hunk": 1,
                    "kind": "expression-shape",
                    "base_start": 2,
                    "base_end": 3,
                    "candidate_start": 2,
                    "candidate_end": 3,
                }],
            },
        ],
    )

    insert_span = summary["parent_hunk_spans"][0]["hunk_spans"][0]
    assert insert_span["base_end"] == insert_span["base_start"] - 1
    assert insert_span["candidate_start"] <= insert_span["candidate_end"]
    manual_range = _parse_manual_range(
        "insert:"
        f"{insert_span['base_start']}-{insert_span['base_end']}="
        f"{insert_span['candidate_start']}-{insert_span['candidate_end']}"
    )
    hunks = _manual_source_hunks(
        base_text="a\nb\nc\n",
        candidate_text="a\nb\ninserted\nc\n",
        candidate_id="insert",
        manual_ranges=[manual_range],
    )
    assert hunks[0]["removed"] == []
    assert hunks[0]["added"] == ["inserted"]


def test_search_combine_manual_ranges_skip_structurally_invalid_subhunk(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void)\n"
        "{\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left + right;\n"
        "}\n"
    )
    insert_candidate = tmp_path / "insert.c"
    insert_candidate.write_text(
        "void demo(void)\n"
        "{\n"
        "    int injected;\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left + right;\n"
        "}\n"
    )
    expr_candidate = tmp_path / "expr.c"
    expr_candidate.write_text(
        "void demo(void)\n"
        "{\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left - right;\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"insert={insert_candidate}",
            "--candidate", f"expr={expr_candidate}",
            "--range", "insert:2-2=3-3",
            "--range", "expr:6-6=6-6",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    combo = payload["combinations"][0]
    assert combo["status"] == "skipped"
    assert combo["reason"] == "invalid-manual-subhunk-source"
    assert "path" not in combo
    assert combo["validation_diagnostics"][0]["kind"] == (
        "manual-range-crosses-structural-boundary"
    )
    assert combo["validation_diagnostics"][0]["hunk"]["parent"] == "insert"
    assert combo["validation_diagnostics"][0]["hunk"]["base_lines"] == [2, 2]
    summary = payload["terminal_summary"]
    assert summary["dominant_blocker"] == "manual-subhunk-range-invalid"
    assert summary["terminal_blocker"] == "incompatible-manual-subhunk-range"


def test_search_combine_duplicate_declaration_validation_respects_function_scope() -> None:
    diagnostics = _duplicate_declaration_diagnostics(
        "int first(void)\n"
        "{\n"
        "    int i;\n"
        "    return i;\n"
        "}\n"
        "\n"
        "int second(void)\n"
        "{\n"
        "    int i;\n"
        "    return i;\n"
        "}\n",
        [],
    )

    assert diagnostics == []


def test_search_combine_duplicate_declaration_validation_catches_same_scope() -> None:
    diagnostics = _duplicate_declaration_diagnostics(
        "int demo(void)\n"
        "{\n"
        "    int i;\n"
        "    int i;\n"
        "    return i;\n"
        "}\n",
        [],
    )

    assert [diagnostic["kind"] for diagnostic in diagnostics] == [
        "duplicate-local-declaration"
    ]
    assert diagnostics[0]["name"] == "i"


def test_search_combine_rejects_member_name_overlap_substitution(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "typedef struct Demo Demo;\n"
        "struct Demo { int left; int right; };\n"
        "void demo(Demo* fp) {\n"
        "    int out;\n"
        "    out = fp->left + fp->right;\n"
        "    sink(out);\n"
        "}\n"
    )
    left_candidate = tmp_path / "left.c"
    left_candidate.write_text(
        "typedef struct Demo Demo;\n"
        "struct Demo { int left; int right; };\n"
        "void demo(Demo* fp) {\n"
        "    int out;\n"
        "    int left_bind_38_0;\n"
        "    left_bind_38_0 = left;\n"
        "    out = fp->left_bind_38_0 + fp->right;\n"
        "    sink(out);\n"
        "}\n"
    )
    right_candidate = tmp_path / "right.c"
    right_candidate.write_text(
        "typedef struct Demo Demo;\n"
        "struct Demo { int left; int right; };\n"
        "void demo(Demo* fp) {\n"
        "    int out;\n"
        "    int right_bind_46_0;\n"
        "    right_bind_46_0 = right;\n"
        "    out = fp->left + fp->right_bind_46_0;\n"
        "    sink(out);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"left={left_candidate}",
            "--candidate", f"right={right_candidate}",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    combo = json.loads(result.stdout)["combinations"][0]
    assert combo["status"] == "skipped"
    assert combo["reason"] == "overlapping-source-hunks"


def test_search_combine_rejects_expression_statement_as_overlap_declaration(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    left_candidate = tmp_path / "left.c"
    left_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    left * right;\n"
        "    left_bind_38_0 = left;\n"
        "    out = left_bind_38_0 + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    right_candidate = tmp_path / "right.c"
    right_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    right_bind_46_0 = right;\n"
        "    out = left + right_bind_46_0;\n"
        "    sink(out);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"left={left_candidate}",
            "--candidate", f"right={right_candidate}",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    combo = json.loads(result.stdout)["combinations"][0]
    assert combo["status"] == "skipped"
    assert combo["reason"] == "overlapping-source-hunks"


def test_search_combine_rejects_expression_statement_matching_binding_name(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    left_candidate = tmp_path / "left.c"
    left_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    left * left_bind_38_0;\n"
        "    left_bind_38_0 = left;\n"
        "    out = left_bind_38_0 + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    right_candidate = tmp_path / "right.c"
    right_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    right_bind_46_0 = right;\n"
        "    out = left + right_bind_46_0;\n"
        "    sink(out);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"left={left_candidate}",
            "--candidate", f"right={right_candidate}",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    combo = json.loads(result.stdout)["combinations"][0]
    assert combo["status"] == "skipped"
    assert combo["reason"] == "overlapping-source-hunks"


def test_search_combine_rejects_typedef_like_expression_statement(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    out = left + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    left_candidate = tmp_path / "left.c"
    left_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    LEFT * left_bind_38_0;\n"
        "    left_bind_38_0 = left;\n"
        "    out = left_bind_38_0 + right;\n"
        "    sink(out);\n"
        "}\n"
    )
    right_candidate = tmp_path / "right.c"
    right_candidate.write_text(
        "void demo(void) {\n"
        "    int left;\n"
        "    int right;\n"
        "    int out;\n"
        "    right_bind_46_0 = right;\n"
        "    out = left + right_bind_46_0;\n"
        "    sink(out);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"left={left_candidate}",
            "--candidate", f"right={right_candidate}",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    combo = json.loads(result.stdout)["combinations"][0]
    assert combo["status"] == "skipped"
    assert combo["reason"] == "overlapping-source-hunks"


def test_search_combine_rejects_conflicting_same_position_declarations(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void demo(void) {\n"
        "    int out;\n"
        "    out = 1;\n"
        "    sink(out);\n"
        "}\n"
    )
    int_candidate = tmp_path / "int.c"
    int_candidate.write_text(
        "void demo(void) {\n"
        "    int tmp;\n"
        "    int out;\n"
        "    out = 1;\n"
        "    sink(out);\n"
        "}\n"
    )
    float_candidate = tmp_path / "float.c"
    float_candidate.write_text(
        "void demo(void) {\n"
        "    float tmp;\n"
        "    int out;\n"
        "    out = 1;\n"
        "    sink(out);\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"int={int_candidate}",
            "--candidate", f"float={float_candidate}",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    combo = json.loads(result.stdout)["combinations"][0]
    assert combo["status"] == "skipped"
    assert combo["reason"] == "overlapping-source-hunks"


def test_search_combine_manual_ranges_recombine_broad_generated_candidates(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    int flag = fp->x594_b4;\n"
        "    sink(flag);\n"
        "    for (int i = 0; i < count; i++) {\n"
        "        sink(tree);\n"
        "    }\n"
        "}\n"
    )
    early = tmp_path / "early-generated.c"
    early.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    /* generated */ int reload = fp->x594_b4;\n"
        "    /* generated */ int flag = reload != 0;\n"
        "    /* generated */ sink(flag);\n"
        "    /* generated */ for (int i = 0; i < count; i++) {\n"
        "    /* generated */     sink(tree);\n"
        "    /* generated */ }\n"
        "}\n"
    )
    late = tmp_path / "late-generated.c"
    late.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    /* generated */ int flag = fp->x594_b4;\n"
        "    /* generated */ sink(flag);\n"
        "    /* generated */ for (int idx = count; idx != 0; --idx) {\n"
        "    /* generated */     sink(tree->next);\n"
        "    /* generated */ }\n"
        "}\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "combine",
            "--base", str(base),
            "--candidate", f"early={early}",
            "--candidate", f"late={late}",
            "--range", "early:2-2=2-3",
            "--range", "late:4-6=4-6",
            "--out-dir", str(tmp_path / "combined"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    combo = payload["combinations"][0]
    assert combo["status"] == "ok"
    assert combo["merge_strategy"] == "non-overlap"
    assert combo["applied_hunks"] == [
        {
            "parent": "early",
            "kind": "manual-subhunk",
            "base_lines": [2, 2],
        },
        {
            "parent": "late",
            "kind": "manual-subhunk",
            "base_lines": [4, 6],
        },
    ]
    combined_text = Path(combo["path"]).read_text()
    assert "int flag = reload != 0;" in combined_text
    assert "sink(tree->next);" in combined_text


def test_search_minimize_removes_unneeded_subhunks_while_preserving_assignments(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    base.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    int flag = fp->x594_b4;\n"
        "    sink(flag);\n"
        "    for (int i = 0; i < count; i++) {\n"
        "        sink(tree);\n"
        "    }\n"
        "}\n"
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text(
        "void ftCo_8009E7B4(void) {\n"
        "    int reload = fp->x594_b4;\n"
        "    int flag = reload != 0;\n"
        "    int generated_noise = 0;\n"
        "    sink(flag);\n"
        "    for (int idx = count; idx != 0; --idx) {\n"
        "        sink(tree->next);\n"
        "    }\n"
        "}\n"
    )
    score_script = tmp_path / "score.py"
    score_script.write_text(
        "import json, pathlib, sys\n"
        "text = pathlib.Path(sys.argv[1]).read_text()\n"
        "satisfied = []\n"
        "if 'reload != 0' in text:\n"
        "    satisfied.extend([\n"
        "        {'original_ig': 42, 'desired_phys': 3, 'assigned_phys': 3},\n"
        "        {'original_ig': 44, 'desired_phys': 4, 'assigned_phys': 4},\n"
        "    ])\n"
        "if 'tree->next' in text:\n"
        "    satisfied.append({'original_ig': 35, 'desired_phys': 30, 'assigned_phys': 30})\n"
        "print(json.dumps({'byte_score': 2006, 'proof_assignments': {'satisfied': satisfied}}))\n"
    )

    result = CliRunner().invoke(
        search_app,
        [
            "minimize",
            "--base", str(base),
            "--candidate", f"candidate={candidate}",
            "--range", "candidate:2-2=2-3",
            "--range", "candidate:3-3=4-5",
            "--range", "candidate:4-6=6-8",
            "--preserve-assignment", "42:3",
            "--preserve-assignment", "35:30",
            "--max-byte-score", "2006",
            "--score-command", f"{sys.executable} {score_script} {{candidate}}",
            "--out", str(tmp_path / "minimized.c"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert len(payload["removed_hunks"]) == 1
    assert payload["removed_hunks"][0]["base_lines"] == [3, 3]
    minimized_text = Path(payload["path"]).read_text()
    assert "generated_noise" not in minimized_text
    assert "reload != 0" in minimized_text
    assert "tree->next" in minimized_text
    assert payload["score_result"]["parsed_json"]["proof_assignments"]["satisfied"] == [
        {"original_ig": 42, "desired_phys": 3, "assigned_phys": 3},
        {"original_ig": 44, "desired_phys": 4, "assigned_phys": 4},
        {"original_ig": 35, "desired_phys": 30, "assigned_phys": 30},
    ]


def test_parse_directed_force_phys_accepts_scoped_csv_and_force_vector() -> None:
    force_phys, class_id = _parse_directed_force_phys(
        "0:58:4,class0:ig44:phys=r4,42:3",
        default_class_id=0,
    )

    assert class_id == 0
    assert force_phys == {58: 4, 44: 4, 42: 3}


def test_parse_directed_force_phys_groups_mixed_classes() -> None:
    from src.search.cli import _parse_directed_force_phys_groups

    groups = _parse_directed_force_phys_groups(
        "0:58:4,class1:ig7:phys=f2,ig42:3",
        default_class_id=0,
    )

    assert groups == {0: {58: 4, 42: 3}, 1: {7: 2}}


def test_search_run_directed_force_phys_emits_objective_and_telemetry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dataclasses import replace

    from src.search.artifact import CandidateArtifact, CompileSpec, Provenance
    from src.search.directed.contracts import DirectedMeta, DirectedObjective

    runner = CliRunner()
    repo = tmp_path / "repo"
    (repo / "src" / "melee" / "ft").mkdir(parents=True)
    (repo / "src" / "melee" / "ft" / "ftdynamics.c").write_text(
        "int ftCo_8009E7B4(void){return 0;}\n"
    )
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/ft/ftdynamics",'
        '"functions":[{"name":"ftCo_8009E7B4"}]}]}'
    )
    seed = tmp_path / "seed.c"
    seed.write_text("int ftCo_8009E7B4(void){return 1;}\n")
    objective_sources = []

    class _Roles:
        function = "ftCo_8009E7B4"
        roles = [object()]

    def fake_objective(**kwargs):
        objective_sources.append(kwargs["baseline_source_text"])
        return DirectedObjective(
            search_target=kwargs["search_target"],
            role_target=_Roles(),
            baseline_compile=object(),
            baseline_pcdump_path=tmp_path / "baseline.pcdump.txt",
            baseline_source_hash="baseline",
            class_id=kwargs["class_id"],
            objective_iter_by_original_ig={58: 1},
            proof_force_phys=kwargs["proof_force_phys"],
        )

    class _FakePcdumpBackend:
        def __init__(
            self,
            *,
            melee_root,
            unit,
            target,
            store,
            compile_spec_factory,
            runner=None,
            timeout=120,
        ):
            self._store = store
            self._compile_spec_factory = compile_spec_factory

        def compile(self, variant, *, want_pcdump=False):
            source_blob = self._store.put_source(variant.source_text)
            obj = tmp_path / "candidate.o"
            obj.write_bytes(b"OBJ")
            pcdump = tmp_path / "candidate.pcdump.txt"
            pcdump.write_text("PCDUMP")
            spec = self._compile_spec_factory(variant)
            return CandidateArtifact(
                candidate_id="directed-candidate",
                source_hash="source-hash",
                source_blob=source_blob,
                compile_spec=spec,
                object_path=obj,
                producer_score=None,
                byte_score=None,
                directed_score=None,
                pcdump_path=pcdump,
                compiler_stderr="",
                provenance=variant.provenance
                or Provenance("seed", None, None, "base", {}),
                status="ok",
            )

    class _FakeDirectedScorer:
        def __init__(self, *args, **kwargs):
            pass

        def score_directed(self, art, call):
            meta = DirectedMeta(
                candidate_id=art.candidate_id,
                source_hash=art.source_hash,
                iteration=1,
                parent_id=None,
                parent_state_id=call.parent_state.state_id,
                valid=True,
                invalid_reason=None,
                case="select_order",
                label="improving",
                order_distance=1,
                displacement=7.0,
                displacement_delta=7.0,
                reanchor_matched=1,
                reanchor_total=1,
                diagnosis_chars=12,
                applied_mutator=None,
                directed_scalar=7.0,
            )
            return replace(
                art,
                directed_score=7.0,
                directed_meta=meta,
                status="ok",
            )

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: repo)
    monkeypatch.setattr(
        "src.search.directed.objective.build_directed_objective",
        fake_objective,
    )
    monkeypatch.setattr(
        "src.search.directed.objective.preflight_objective",
        lambda obj: None,
    )
    monkeypatch.setattr(
        "src.search.directed.pcdump_backend.PcdumpLocalBackend",
        _FakePcdumpBackend,
    )
    monkeypatch.setattr(
        "src.search.directed.scorer.DirectedScorePipeline",
        _FakeDirectedScorer,
    )

    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--no-remote",
            "--seed", str(seed),
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
            "--directed-force-phys", "0:58:4,0:44:4",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["directed"]["enabled"] is True
    assert summary["directed"]["class_id"] == 0
    assert summary["directed"]["proof_force_phys"] == {"44": 4, "58": 4}
    assert summary["best_directed_score"] == 7.0
    assert summary["directed_telemetry"][0]["candidate_id"] == "directed-candidate"
    assert objective_sources == [
        (repo / "src" / "melee" / "ft" / "ftdynamics.c").read_text()
    ]


def test_search_run_directed_force_phys_emits_transform_corpus_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dataclasses import replace

    from src.search.artifact import CandidateArtifact, CompileSpec, Provenance
    from src.search.directed.contracts import DirectedMeta, DirectedObjective

    runner = CliRunner()
    repo = tmp_path / "repo"
    source_path = repo / "src" / "melee" / "test" / "mined.c"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "typedef double f64;\n"
        "typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;\n"
        "typedef struct Gp { u8 pad[0xE0]; Vec3 scroll; } Gp;\n"
        "typedef struct State { int field; int other; } State;\n"
        "typedef struct Item Item;\n"
        "void it_8026F790(HSD_GObj* gobj, f32 angle);\n"
        "State lbl_80472D28;\n"
        "s32 fn_8017F0A0(Item* it);\n"
        "static struct { char report_format[32]; } grIm_803E4800 = { \"loaded stage %d\\n\" };\n"
        "static void mined(Gp* gp, Item* it) {\n"
        "    item = HSD_GObj_Entities->items;\n"
        "    if (item != NULL) {\n"
        "        use(item);\n"
        "    }\n"
        "    jobj = (HSD_JObj*) HSD_GObjGetHSDObj(gobj);\n"
        "    process(cur);\n"
        "    update(cur);\n"
        "    it_8026F790(gobj, (f32) angle);\n"
        "    switch (kind) {\n"
        "    case 7:\n"
        "        b();\n"
        "        break;\n"
        "    case 9:\n"
        "        c();\n"
        "        break;\n"
        "    }\n"
        "    if (archive == NULL)\n"
        "        __assert(\"mined.c\", 0x617, \"0\");\n"
        "    OSReport(\"loaded stage %d\\n\", id);\n"
        "    lbl_80472D28.field = x;\n"
        "    use(lbl_80472D28.other);\n"
        "    *(Vec3*) ((u8*) gp + 0xE0) = scroll;\n"
        "    fn_8017F0A0(it);\n"
        "}\n"
    )
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/test/mined",'
        '"functions":[{"name":"mined"}]}]}'
    )
    seen_mutations: list[str | None] = []

    class _Roles:
        function = "mined"
        roles = [object()]

    def fake_objective(**kwargs):
        return DirectedObjective(
            search_target=kwargs["search_target"],
            role_target=_Roles(),
            baseline_compile=object(),
            baseline_pcdump_path=tmp_path / "baseline.pcdump.txt",
            baseline_source_hash="baseline",
            class_id=kwargs["class_id"],
            objective_iter_by_original_ig={58: 1},
            proof_force_phys=kwargs["proof_force_phys"],
        )

    class _FakePcdumpBackend:
        def __init__(
            self,
            *,
            melee_root,
            unit,
            target,
            store,
            compile_spec_factory,
            runner=None,
            timeout=120,
        ):
            self._store = store
            self._compile_spec_factory = compile_spec_factory

        def compile(self, variant, *, want_pcdump=False):
            source_blob = self._store.put_source(variant.source_text)
            mutation = (
                variant.provenance.mutation
                if variant.provenance is not None else None
            )
            seen_mutations.append(mutation)
            safe_id = (mutation or "diagnosis-probe").replace(":", "_")
            obj = tmp_path / f"{safe_id}.o"
            obj.write_bytes(b"OBJ")
            pcdump = tmp_path / f"{safe_id}.pcdump.txt"
            pcdump.write_text("invalid pcdump fixture")
            spec = self._compile_spec_factory(variant)
            return CandidateArtifact(
                candidate_id=mutation or "diagnosis-probe",
                source_hash=safe_id,
                source_blob=source_blob,
                compile_spec=spec,
                object_path=obj,
                producer_score=None,
                byte_score=None,
                directed_score=None,
                pcdump_path=pcdump,
                compiler_stderr="",
                provenance=variant.provenance
                or Provenance("directed", None, None, "base", {}),
                status="ok",
            )

    class _FakeDirectedScorer:
        def __init__(self, *args, **kwargs):
            pass

        def score_directed(self, art, call):
            mutation = art.provenance.mutation
            meta = DirectedMeta(
                candidate_id=art.candidate_id,
                source_hash=art.source_hash,
                iteration=1,
                parent_id=None,
                parent_state_id=call.parent_state.state_id,
                valid=True,
                invalid_reason=None,
                case="force_phys_assignment",
                label="transform",
                order_distance=0,
                displacement=2.0,
                displacement_delta=2.0,
                reanchor_matched=1,
                reanchor_total=1,
                diagnosis_chars=18,
                applied_mutator=mutation,
                directed_scalar=2.0,
            )
            return replace(
                art,
                directed_score=2.0,
                directed_meta=meta,
                status="ok",
            )

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: repo)
    monkeypatch.setattr(
        "src.search.directed.objective.build_directed_objective",
        fake_objective,
    )
    monkeypatch.setattr(
        "src.search.directed.objective.preflight_objective",
        lambda obj: None,
    )
    monkeypatch.setattr(
        "src.search.directed.pcdump_backend.PcdumpLocalBackend",
        _FakePcdumpBackend,
    )
    monkeypatch.setattr(
        "src.search.directed.scorer.DirectedScorePipeline",
        _FakeDirectedScorer,
    )

    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "mined",
            "--unit", "melee/test/mined",
            "--no-remote",
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
            "--directed-force-phys", "0:1:3",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    transform_meta = [
        meta for meta in summary["directed_telemetry"]
        if str(meta["applied_mutator"]).startswith("transform-corpus:")
    ]
    assert transform_meta
    assert any(
        mutation and mutation.startswith("transform-corpus:")
        for mutation in seen_mutations
    )
    assert seen_mutations.count(None) == 1


def test_search_run_directed_force_phys_emits_coloring_register_steering_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dataclasses import replace

    from src.search.artifact import CandidateArtifact, CompileSpec, Provenance
    from src.search.directed.contracts import DirectedMeta, DirectedObjective

    runner = CliRunner()
    repo = tmp_path / "repo"
    source_path = repo / "src" / "melee" / "mn" / "mndiagram2.c"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "typedef int s32;\n"
        "typedef struct HSD_GObj HSD_GObj;\n"
        "void mnDiagram2_Create(void) {\n"
        "    s32 did;\n"
        "    HSD_GObj* mgobj;\n"
        "    did = 0;\n"
        "    sink(did, mgobj);\n"
        "}\n"
    )
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/mn/mndiagram2",'
        '"functions":[{"name":"mnDiagram2_Create"}]}]}'
    )
    seen_mutations: list[str | None] = []

    class _Roles:
        function = "mnDiagram2_Create"
        roles = [object()]

    def fake_objective(**kwargs):
        return DirectedObjective(
            search_target=kwargs["search_target"],
            role_target=_Roles(),
            baseline_compile=object(),
            baseline_pcdump_path=tmp_path / "baseline.pcdump.txt",
            baseline_source_hash="baseline",
            class_id=kwargs["class_id"],
            objective_iter_by_original_ig={58: 1},
            proof_force_phys=kwargs["proof_force_phys"],
        )

    class _FakePcdumpBackend:
        def __init__(
            self,
            *,
            melee_root,
            unit,
            target,
            store,
            compile_spec_factory,
            runner=None,
            timeout=120,
        ):
            self._store = store
            self._compile_spec_factory = compile_spec_factory

        def compile(self, variant, *, want_pcdump=False):
            mutation = (
                variant.provenance.mutation
                if variant.provenance is not None else None
            )
            seen_mutations.append(mutation)
            safe_id = (mutation or "diagnosis-probe").replace(":", "_")
            source_blob = self._store.put_source(variant.source_text)
            obj = tmp_path / f"{safe_id}.o"
            obj.write_bytes(b"OBJ")
            pcdump = tmp_path / f"{safe_id}.pcdump.txt"
            pcdump.write_text("invalid pcdump fixture")
            spec = self._compile_spec_factory(variant)
            return CandidateArtifact(
                candidate_id=mutation or "diagnosis-probe",
                source_hash=safe_id,
                source_blob=source_blob,
                compile_spec=spec,
                object_path=obj,
                producer_score=None,
                byte_score=None,
                directed_score=None,
                pcdump_path=pcdump,
                compiler_stderr="",
                provenance=variant.provenance
                or Provenance("directed", None, None, "base", {}),
                status="ok",
            )

    class _FakeDirectedScorer:
        def __init__(self, *args, **kwargs):
            pass

        def score_directed(self, art, call):
            mutation = art.provenance.mutation
            meta = DirectedMeta(
                candidate_id=art.candidate_id,
                source_hash=art.source_hash,
                iteration=1,
                parent_id=None,
                parent_state_id=call.parent_state.state_id,
                valid=True,
                invalid_reason=None,
                case="force_phys_assignment",
                label="transform",
                order_distance=0,
                displacement=2.0,
                displacement_delta=2.0,
                reanchor_matched=1,
                reanchor_total=1,
                diagnosis_chars=18,
                applied_mutator=mutation,
                directed_scalar=2.0,
            )
            return replace(
                art,
                directed_score=2.0,
                directed_meta=meta,
                status="ok",
            )

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: repo)
    monkeypatch.setattr(
        "src.search.directed.objective.build_directed_objective",
        fake_objective,
    )
    monkeypatch.setattr(
        "src.search.directed.objective.preflight_objective",
        lambda obj: None,
    )
    monkeypatch.setattr(
        "src.search.directed.pcdump_backend.PcdumpLocalBackend",
        _FakePcdumpBackend,
    )
    monkeypatch.setattr(
        "src.search.directed.scorer.DirectedScorePipeline",
        _FakeDirectedScorer,
    )

    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--no-remote",
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
            "--directed-force-phys", "0:58:4,0:35:29",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    transform_meta = [
        meta for meta in summary["directed_telemetry"]
        if str(meta["applied_mutator"]).startswith(
            "transform-corpus:coloring_register_steering:"
        )
    ]
    assert transform_meta
    assert any(
        mutation
        and mutation.startswith("transform-corpus:coloring_register_steering:")
        for mutation in seen_mutations
    )
    assert seen_mutations.count(None) == 1


def test_search_run_directed_summary_reports_byte_best_not_directed_best(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from src.search.artifact import CandidateArtifact, CompileSpec, Provenance
    from src.search.types import SearchResult

    runner = CliRunner()
    repo = tmp_path / "repo"
    (repo / "src" / "melee" / "ft").mkdir(parents=True)
    (repo / "src" / "melee" / "ft" / "ftdynamics.c").write_text(
        "int ftCo_8009E7B4(void){return 0;}\n"
    )
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/ft/ftdynamics",'
        '"functions":[{"name":"ftCo_8009E7B4"}]}]}'
    )
    seed = tmp_path / "seed.c"
    seed.write_text("int ftCo_8009E7B4(void){return 1;}\n")

    spec = CompileSpec(
        target_id="ftCo_8009E7B4@melee/ft/ftdynamics",
        cflags_hash="cflags",
        base_context_hash="base",
        toolchain_fingerprint="mwcc",
        backend_mode="plain-local",
        manifest_path=tmp_path / "manifest.json",
    )
    provenance = Provenance("seed", None, None, "base", {})

    def artifact(candidate_id: str, byte_score: int, directed_score: float):
        source_blob = tmp_path / f"{candidate_id}.c"
        source_blob.write_text("int ftCo_8009E7B4(void){return 1;}\n")
        obj = tmp_path / f"{candidate_id}.o"
        obj.write_bytes(b"OBJ")
        return CandidateArtifact(
            candidate_id=candidate_id,
            source_hash=f"{candidate_id}-hash",
            source_blob=source_blob,
            compile_spec=spec,
            object_path=obj,
            producer_score=None,
            byte_score=byte_score,
            directed_score=directed_score,
            pcdump_path=None,
            compiler_stderr="",
            provenance=provenance,
            status="ok",
            directed_meta={
                "candidate_id": candidate_id,
                "valid": True,
                "displacement": directed_score,
                "byte_score": byte_score,
            },
        )

    directed_best = artifact("directed-best", 2036, 6.0)
    byte_best = artifact("byte-best", 2006, 2.0)

    class _Objective:
        search_target = object()
        role_target = object()
        baseline_compile = object()
        baseline_pcdump_path = tmp_path / "baseline.pcdump.txt"
        baseline_source_hash = "baseline"
        class_id = 0
        objective_iter_by_original_ig = {58: 1}
        proof_force_phys = {58: 4}

    class _PcdumpBackend:
        def __init__(self, *args, **kwargs):
            pass

    class _DirectedScorePipeline:
        def __init__(self, *args, **kwargs):
            pass

    class _Scheduler:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, **kwargs):
            assert kwargs["directed"] is not None
            return SearchResult(
                best=[directed_best, byte_best],
                matched=None,
                accounting={"iters_done": 1},
                directed_telemetry=[
                    directed_best.directed_meta,
                    byte_best.directed_meta,
                ],
            )

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: repo)
    monkeypatch.setattr(
        "src.search.directed.objective.build_directed_objective",
        lambda **kwargs: _Objective(),
    )
    monkeypatch.setattr(
        "src.search.directed.objective.preflight_objective",
        lambda objective: None,
    )
    monkeypatch.setattr(
        "src.search.directed.pcdump_backend.PcdumpLocalBackend",
        _PcdumpBackend,
    )
    monkeypatch.setattr(
        "src.search.directed.scorer.DirectedScorePipeline",
        _DirectedScorePipeline,
    )
    monkeypatch.setattr("src.search.scheduler.DefaultScheduler", _Scheduler)

    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--no-remote",
            "--seed", str(seed),
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
            "--directed-force-phys", "0:58:4",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["best_directed_meta"]["candidate_id"] == "directed-best"
    assert summary["best_byte_score"] == 2006


def test_search_run_directed_force_phys_continues_after_abstained_preflight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dataclasses import replace

    from src.search.artifact import CandidateArtifact, CompileSpec, Provenance
    from src.search.directed.contracts import DirectedMeta, DirectedObjective
    from src.search.directed.objective import PreflightError

    repo = tmp_path / "repo"
    (repo / "src" / "melee" / "ft").mkdir(parents=True)
    (repo / "src" / "melee" / "ft" / "ftdynamics.c").write_text(
        "int ftCo_8009E7B4(void){return 0;}\n"
    )
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/ft/ftdynamics",'
        '"functions":[{"name":"ftCo_8009E7B4"}]}]}'
    )
    seed = tmp_path / "seed.c"
    seed.write_text("int ftCo_8009E7B4(void){return 1;}\n")

    class _Roles:
        function = "ftCo_8009E7B4"
        roles = [object()]

    def fake_objective(**kwargs):
        return DirectedObjective(
            search_target=kwargs["search_target"],
            role_target=_Roles(),
            baseline_compile=object(),
            baseline_pcdump_path=tmp_path / "baseline.pcdump.txt",
            baseline_source_hash="baseline",
            class_id=kwargs["class_id"],
            objective_iter_by_original_ig={58: 1},
            proof_force_phys=kwargs["proof_force_phys"],
        )

    class _FakePcdumpBackend:
        def __init__(
            self,
            *,
            melee_root,
            unit,
            target,
            store,
            compile_spec_factory,
            runner=None,
            timeout=120,
        ):
            self._store = store
            self._compile_spec_factory = compile_spec_factory

        def compile(self, variant, *, want_pcdump=False):
            source_blob = self._store.put_source(variant.source_text)
            obj = tmp_path / "candidate.o"
            obj.write_bytes(b"OBJ")
            pcdump = tmp_path / "candidate.pcdump.txt"
            pcdump.write_text("PCDUMP")
            spec = self._compile_spec_factory(variant)
            return CandidateArtifact(
                candidate_id="directed-candidate",
                source_hash="source-hash",
                source_blob=source_blob,
                compile_spec=spec,
                object_path=obj,
                producer_score=None,
                byte_score=None,
                directed_score=None,
                pcdump_path=pcdump,
                compiler_stderr="",
                provenance=variant.provenance
                or Provenance("seed", None, None, "base", {}),
                status="ok",
            )

    class _FakeDirectedScorer:
        def __init__(self, *args, **kwargs):
            pass

        def score_directed(self, art, call):
            meta = DirectedMeta(
                candidate_id=art.candidate_id,
                source_hash=art.source_hash,
                iteration=1,
                parent_id=None,
                parent_state_id=call.parent_state.state_id,
                valid=True,
                invalid_reason=None,
                case="force_phys_assignment",
                label="assignment_fallback",
                order_distance=0,
                displacement=1.0,
                displacement_delta=1.0,
                reanchor_matched=1,
                reanchor_total=1,
                diagnosis_chars=20,
                applied_mutator="seed",
                directed_scalar=1.0,
            )
            return replace(
                art,
                directed_score=1.0,
                directed_meta=meta,
                status="ok",
            )

    def abstain_preflight(_objective):
        raise PreflightError("case_abstained")

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: repo)
    monkeypatch.setattr(
        "src.search.directed.objective.build_directed_objective",
        fake_objective,
    )
    monkeypatch.setattr(
        "src.search.directed.objective.preflight_objective",
        abstain_preflight,
    )
    monkeypatch.setattr(
        "src.search.directed.pcdump_backend.PcdumpLocalBackend",
        _FakePcdumpBackend,
    )
    monkeypatch.setattr(
        "src.search.directed.scorer.DirectedScorePipeline",
        _FakeDirectedScorer,
    )

    result = CliRunner().invoke(
        search_app,
        [
            "run",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--no-remote",
            "--seed", str(seed),
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
            "--directed-force-phys", "0:58:4",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["directed"]["preflight"] == "fallback:case_abstained"
    assert summary["directed"]["preflight_ok"] is False
    assert summary["directed_telemetry"][0]["case"] == "force_phys_assignment"


def test_search_directed_command_accepts_force_phys_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def fake_run_directed(**kwargs):
        calls.append(kwargs)
        return {
            "gate": {"passed": True, "reason": "attributable_progress"},
            "directed_telemetry": [],
            "accounting": {},
        }

    monkeypatch.setattr(
        "src.search.cli._compute_melee_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "src.search.directed.run.run_directed",
        fake_run_directed,
    )

    result = CliRunner().invoke(
        search_app,
        [
            "directed",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--store", str(tmp_path / "store"),
            "--directed-force-phys", "0:58:4,0:44:4",
            "--directed-class", "0",
            "--max-iters", "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[0]["proof_force_phys"] == {58: 4, 44: 4}
    assert calls[0]["class_id"] == 0


def test_search_directed_command_splits_mixed_force_phys_classes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def fake_run_directed(**kwargs):
        calls.append(kwargs)
        class_id = kwargs["class_id"]
        return {
            "function": kwargs["function"],
            "unit": kwargs["unit"],
            "gate": {
                "passed": False,
                "reason": "no_smooth_gradient",
                "evidence": {"class_id": class_id},
            },
            "directed_telemetry": [
                {
                    "valid": True,
                    "applied_mutator": "transform-corpus:test:0",
                    "checkdiff_gate": "byte_mismatch",
                    "proof_assignments": {
                        "satisfied": [],
                        "blocked": [
                            {
                                "original_ig": class_id + 10,
                                "new_ig": class_id + 10,
                                "desired_phys": class_id + 3,
                                "assigned_phys": class_id + 4,
                            }
                        ],
                        "abstained": [],
                    },
                }
            ],
            "accounting": {
                "compiled": 1,
                "source_shape_drained": True,
                "budget_exhausted": False,
            },
        }

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        "src.search.directed.run.run_directed",
        fake_run_directed,
    )

    result = CliRunner().invoke(
        search_app,
        [
            "directed",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--store", str(tmp_path / "store"),
            "--directed-force-phys", "0:58:4,1:7:2",
            "--max-iters", "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert [(call["class_id"], call["proof_force_phys"]) for call in calls] == [
        (0, {58: 4}),
        (1, {7: 2}),
    ]
    payload = json.loads(result.stdout)
    assert payload["multi_class"] is True
    assert payload["class_ids"] == [0, 1]
    assert payload["gate"]["reason"] == "no_smooth_gradient"
    assert payload["accounting"]["source_shape_drained"] is True
    assert [row["class_id"] for row in payload["directed_telemetry"]] == [0, 1]
    assert [entry["class_id"] for entry in payload["classes"]] == [0, 1]


def test_search_directed_from_diff_splits_mixed_force_phys_classes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def fake_run_directed(**kwargs):
        calls.append(kwargs)
        return {
            "function": kwargs["function"],
            "unit": kwargs["unit"],
            "gate": {"passed": False, "reason": "no_smooth_gradient"},
            "directed_telemetry": [],
            "accounting": {
                "compiled": 1,
                "source_shape_drained": True,
                "budget_exhausted": False,
            },
        }

    def fake_subprocess_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "force_phys_csv": "0:58:4,1:7:2",
                "force_vector_verify": {
                    "ran": True,
                    "union": {"match": True},
                },
            }),
            stderr="",
        )

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr("src.search.cli.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr(
        "src.search.directed.run.run_directed",
        fake_run_directed,
    )

    result = CliRunner().invoke(
        search_app,
        [
            "directed",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--store", str(tmp_path / "store"),
            "--directed-from-diff",
            "--max-iters", "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert [(call["class_id"], call["proof_force_phys"]) for call in calls] == [
        (0, {58: 4}),
        (1, {7: 2}),
    ]
    payload = json.loads(result.stdout)
    assert payload["multi_class"] is True
    assert payload["proof_force_phys_csv"] == "0:58:4,1:7:2"


def test_search_directed_multi_class_payload_feeds_allocator_ceiling() -> None:
    from src.mwcc_debug.allocator_ceiling import classify_allocator_ceiling

    payload = _aggregate_directed_class_results(
        function="fn_test",
        unit="melee/test",
        groups={0: {58: 4}, 1: {7: 2}},
        results=[
            (
                0,
                {
                    "function": "fn_test",
                    "unit": "melee/test",
                    "gate": {"passed": False, "reason": "no_smooth_gradient"},
                    "directed_telemetry": [
                        {
                            "valid": True,
                            "applied_mutator": "transform-corpus:test:0",
                            "checkdiff_gate": "byte_mismatch",
                            "proof_assignments": {
                                "satisfied": [],
                                "blocked": [
                                    {
                                        "original_ig": 58,
                                        "new_ig": 58,
                                        "desired_phys": 4,
                                        "assigned_phys": 5,
                                    }
                                ],
                                "abstained": [],
                            },
                        }
                    ],
                    "accounting": {
                        "compiled": 1,
                        "source_shape_drained": True,
                        "budget_exhausted": False,
                    },
                },
            ),
            (
                1,
                {
                    "function": "fn_test",
                    "unit": "melee/test",
                    "gate": {"passed": False, "reason": "no_smooth_gradient"},
                    "directed_telemetry": [
                        {
                            "valid": True,
                            "applied_mutator": "transform-corpus:test:1",
                            "checkdiff_gate": "byte_mismatch",
                            "proof_assignments": {
                                "satisfied": [],
                                "blocked": [
                                    {
                                        "original_ig": 7,
                                        "new_ig": 7,
                                        "desired_phys": 2,
                                        "assigned_phys": 3,
                                    }
                                ],
                                "abstained": [],
                            },
                        }
                    ],
                    "accounting": {
                        "compiled": 1,
                        "source_shape_drained": True,
                        "budget_exhausted": False,
                    },
                },
            ),
        ],
    )

    result = classify_allocator_ceiling([payload], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "directed-source-exhausted"
    assert len(result["backend_blockers"]) == 2


def test_search_directed_multi_class_payload_preserves_bounded_stop_reason() -> None:
    from src.mwcc_debug.allocator_ceiling import classify_allocator_ceiling

    payload = _aggregate_directed_class_results(
        function="fn_test",
        unit="melee/test",
        groups={0: {7: 2}, 1: {7: 2}},
        results=[
            (
                0,
                {
                    "function": "fn_test",
                    "unit": "melee/test",
                    "gate": {"passed": False, "reason": "no_smooth_gradient"},
                    "directed_telemetry": [
                        {
                            "class_id": 0,
                            "valid": True,
                            "applied_mutator": "transform-corpus:gpr",
                            "checkdiff_gate": "byte_mismatch",
                            "proof_assignments": {
                                "satisfied": [],
                                "blocked": [
                                    {
                                        "original_ig": 7,
                                        "new_ig": 7,
                                        "desired_phys": 2,
                                        "assigned_phys": 3,
                                    }
                                ],
                                "abstained": [],
                            },
                        }
                    ],
                    "accounting": {
                        "compiled": 1,
                        "source_shape_drained": True,
                        "budget_exhausted": False,
                    },
                },
            ),
            (
                1,
                {
                    "function": "fn_test",
                    "unit": "melee/test",
                    "gate": {"passed": False, "reason": "no_smooth_gradient"},
                    "directed_telemetry": [
                        {
                            "class_id": 1,
                            "valid": True,
                            "applied_mutator": "transform-corpus:fpr",
                            "checkdiff_gate": "byte_mismatch",
                            "proof_assignments": {
                                "satisfied": [],
                                "blocked": [
                                    {
                                        "original_ig": 7,
                                        "new_ig": 7,
                                        "desired_phys": 2,
                                        "assigned_phys": 3,
                                    }
                                ],
                                "abstained": [],
                            },
                        }
                    ],
                    "accounting": {
                        "compiled": 1,
                        "source_shape_drained": True,
                        "budget_exhausted": False,
                        "stop_reason": "candidate-limit",
                    },
                },
            ),
        ],
    )

    result = classify_allocator_ceiling([payload], function="fn_test")

    assert payload["accounting"]["stop_reason"] == "candidate-limit"
    assert result["status"] == "bounded"
    assert "directed search candidate-limit" in result["bounded_reasons"]


def test_search_directed_command_accepts_seed_source_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    source = tmp_path / "dirty.c"
    source.write_text("int ftCo_8009E7B4(void){return 7;}\n")

    def fake_run_directed(**kwargs):
        calls.append(kwargs)
        return {
            "gate": {"passed": False, "reason": "no_smooth_gradient"},
            "directed_telemetry": [],
            "accounting": {},
        }

    monkeypatch.setattr(
        "src.search.cli._compute_melee_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "src.search.directed.run.run_directed",
        fake_run_directed,
    )

    result = CliRunner().invoke(
        search_app,
        [
            "directed",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--store", str(tmp_path / "store"),
            "--seed", str(source),
            "--directed-force-phys", "0:58:4",
            "--max-iters", "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[0]["source_file"] == source


def test_search_directed_command_accepts_pcdump_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def fake_run_directed(**kwargs):
        calls.append(kwargs)
        return {
            "gate": {"passed": False, "reason": "no_smooth_gradient"},
            "directed_telemetry": [],
            "accounting": {},
        }

    monkeypatch.setattr(
        "src.search.cli._compute_melee_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "src.search.directed.run.run_directed",
        fake_run_directed,
    )

    result = CliRunner().invoke(
        search_app,
        [
            "directed",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--store", str(tmp_path / "store"),
            "--directed-force-phys", "0:58:4",
            "--directed-pcdump-timeout", "17",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[0]["pcdump_timeout"] == 17


def test_expected_obj_resolves_original_obj_not_current_build_obj(tmp_path: Path) -> None:
    """The scorer must compare candidates against the target/original object.

    build/GALE01/src/<unit>.o is overwritten by the local candidate compile;
    using it as the expected object makes the baseline score as an exact match.
    """

    report = tmp_path / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/ft/ftdynamics",'
        '"functions":[{"name":"ftCo_8009E7B4"}]}]}'
    )

    resolved = _resolve_expected_obj(
        tmp_path,
        "ftCo_8009E7B4",
        "melee/ft/ftdynamics",
    )

    assert resolved == tmp_path / "build" / "GALE01" / "obj" / "melee" / "ft" / "ftdynamics.o"


def test_expected_obj_fallback_uses_original_obj_tree(tmp_path: Path) -> None:
    resolved = _resolve_expected_obj(
        tmp_path,
        "ftCo_8009E7B4",
        "melee/ft/ftdynamics",
    )

    assert resolved == tmp_path / "build" / "GALE01" / "obj" / "melee" / "ft" / "ftdynamics.o"


def test_search_run_missing_permuter_dir_degrades_to_local_only(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--perm-root", str(tmp_path / "missing-decomp-permuter"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "remote producers disabled" in result.stderr
    assert "function dir, compile.sh, settings.toml, target.o" in result.stderr


def test_search_run_remote_progress_goes_to_stderr(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    repo = tmp_path / "repo"
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/u","functions":[{"name":"f"}]}]}'
    )
    perm_dir = tmp_path / "perm" / "nonmatchings" / "f"
    perm_dir.mkdir(parents=True)
    (perm_dir / "base.c").write_text("int f(void){return 1;}\n")
    (perm_dir / "compile.sh").write_text("#!/bin/sh\nexit 0\n")
    (perm_dir / "settings.toml").write_text("base = \"base.c\"\n")
    (perm_dir / "target.o").write_bytes(b"target")

    class _QuietRemote:
        def __init__(self, melee_root):
            self.stopped = []

        def submit(self, base_dir, function, remote):
            return f"{function}-{remote}-job"

        def fetch(self, job_id):
            return []

        def status(self, job_id):
            return "running"

        def stop(self, job_id):
            self.stopped.append(job_id)

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: repo)
    monkeypatch.setattr(
        "src.search.adapters.RealRemotePermuterClient",
        _QuietRemote,
    )

    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "f",
            "--unit", "u",
            "--store", str(tmp_path / "store"),
            "--perm-root", str(tmp_path / "perm"),
            "--remotes", "coder3",
            "--max-iters", "2",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["accounting"]["producer_polls"] == 2
    assert summary["accounting"]["budget_exhausted"] is True
    assert "producer-started" in result.stderr
    assert "job=f-coder3-job" in result.stderr
    assert "producer-poll" in result.stderr
    assert "state=running" in result.stderr
    assert "harvested=0" in result.stderr


def test_search_run_partial_remote_start_failure_keeps_healthy_remote(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    repo = tmp_path / "repo"
    report = repo / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/u","functions":[{"name":"f"}]}]}'
    )
    perm_dir = tmp_path / "perm" / "nonmatchings" / "f"
    perm_dir.mkdir(parents=True)
    (perm_dir / "base.c").write_text("int f(void){return 1;}\n")
    (perm_dir / "compile.sh").write_text("#!/bin/sh\nexit 0\n")
    (perm_dir / "settings.toml").write_text("base = \"base.c\"\n")
    (perm_dir / "target.o").write_bytes(b"target")

    class _PartialRemote:
        def __init__(self, melee_root):
            self.stopped = []

        def submit(self, base_dir, function, remote):
            if remote == "coder1":
                raise RuntimeError("remote preflight failed for coder1: missing toml")
            return f"{function}-{remote}-job"

        def fetch(self, job_id):
            return []

        def status(self, job_id):
            return "running"

        def stop(self, job_id):
            self.stopped.append(job_id)

    monkeypatch.setattr("src.search.cli._compute_melee_root", lambda: repo)
    monkeypatch.setattr(
        "src.search.adapters.RealRemotePermuterClient",
        _PartialRemote,
    )

    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "f",
            "--unit", "u",
            "--store", str(tmp_path / "store"),
            "--perm-root", str(tmp_path / "perm"),
            "--remotes", "coder1,coder3",
            "--max-iters", "1",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["accounting"]["producer_started"] == 1
    assert summary["accounting"]["producer_failed"] == 1
    assert summary["accounting"]["producer_failures"] == [
        {
            "producer": "permuter-job",
            "jobs": [],
            "remote": "coder1",
            "detail": "remote preflight failed for coder1: missing toml",
        }
    ]
    assert "producer-start-failed" in result.stderr
    assert "remote=coder1" in result.stderr
    assert "job=f-coder3-job" in result.stderr
