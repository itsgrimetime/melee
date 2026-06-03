"""Smoke test for `debug search run` CLI.

Uses --dry-compiler so no real mwcc/wibo/SSH is needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from src.search.cli import (
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
    assert root.name == "melee", root
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
