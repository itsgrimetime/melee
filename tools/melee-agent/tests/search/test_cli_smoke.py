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
    _compute_melee_root,
    _parse_directed_force_phys,
    _resolve_expected_obj,
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
    assert "--json" in result.stdout


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
            "--max-per-family", "3",
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
            "--max-per-family", "3",
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
    assert [probe["mutator_key"] for probe in steering] == [
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
    assert payload["combinations"][0]["parents"] == ["early", "late"]
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
        "byte_score": 2028,
        "opcode_preservation": "unknown",
        "has_early": True,
        "has_late": True,
    }


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
