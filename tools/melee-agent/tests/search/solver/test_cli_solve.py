import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import src.cli.debug as debugcli
from src.cli import app as cli_app
from src.mwcc_debug.tiebreak import IG, IGNode
from src.mwcc_debug.simplify_search import BaselineSignature
from src.mwcc_debug.source_shape import CandidatePatch, CandidateScore
from src.search.solver.solve import SolveResult
from src.search.solver.worksheet import (
    FilterSummary, PairEscalation, Worksheet,
)

runner = CliRunner()


def _ws():
    return Worksheet(
        function="mnDiagram_80241E78", class_id=0, g1_rate=1.0,
        force_phys_target={"42": 27}, reachable=True,
        filter_summary=FilterSummary(4, 0, 0, 0, 0),
        candidates=[{"rank": 1,
                     "perturbation": {"kind": "node-add", "target_ig": 41,
                                      "use_set": [42]},
                     "predicted_assignment_delta": {},
                     "c_realizations": [{"lever": "alias",
                                         "source_object": "data_alias",
                                         "confidence_tier": "a"}],
                     "surrogate_confidence": "high",
                     "fidelity_gate": "pending"}],
        tooling_leads=[], window_order=[],
        pair_escalation=PairEscalation(False, "actionable single exists", 0, [], []),
        enumeration_truncated=False,
        evals_per_kind={"node-add": 4, "edge": 0, "order": 0})


def _node_split_source() -> str:
    return (
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    int out;\n"
        "    holder = make();\n"
        "    out = holder + 1;\n"
        "    use(out, holder);\n"
        "}\n"
    )


def _node_split_repo(tmp_path, monkeypatch, source_text: str | None = None):
    source = tmp_path / "src" / "melee" / "mn" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(source_text or _node_split_source(), encoding="utf-8")
    (tmp_path / "build" / "GALE01").mkdir(parents=True)
    monkeypatch.setattr(debugcli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(
        debugcli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/mn/demo",
    )
    monkeypatch.setattr(debugcli, "_get_match_pct", lambda function, root: 50.0)
    monkeypatch.setattr(
        debugcli,
        "_build_and_match_with_diagnostic",
        lambda unit, function, root, **_kwargs: (50.0, None),
    )
    return source


def _sig(*, reg: int, spill_set: frozenset[int] = frozenset()):
    return BaselineSignature(
        interference_edges=frozenset(),
        coalesce_mappings=frozenset(),
        spill_set=spill_set,
        simplify_order=(40,),
        assigned_regs=frozenset({(40, reg)}),
    )


def test_solve_node_set_split_applies_verified_improving_candidate(
    monkeypatch,
    tmp_path,
):
    source = _node_split_repo(tmp_path, monkeypatch)

    def fake_compile_signature(path, **kwargs):
        label = kwargs["label"]
        if label == "baseline":
            return _sig(reg=31)
        if "alias" in label:
            return _sig(reg=30)
        return _sig(reg=31)

    def fake_score(patch, **kwargs):
        if "alias" in patch.candidate_id:
            return CandidateScore(
                patch.candidate_id,
                compile_ok=True,
                checkdiff_pct=50.4,
                checkdiff_delta=0.4,
                pcdump_score_delta=None,
                diagnostics_path=None,
            )
        return CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=49.9,
            checkdiff_delta=-0.1,
            pcdump_score_delta=None,
            diagnostics_path=None,
        )

    def fake_apply(patch, **kwargs):
        source.write_text(patch.patched_source, encoding="utf-8")
        return 50.4, None

    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        fake_score,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_apply_node_set_split_patch",
        fake_apply,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--current-reg", "r31",
        "--target-reg", "r30",
        "--var", "holder",
        "--apply-best",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "improved"
    assert payload["best_candidate_id"].startswith("node-split-alias-holder")
    assert payload["candidates"][0]["objective_status"] == "realized"
    assert "holder_split_40" in source.read_text(encoding="utf-8")


def test_solve_node_set_split_routes_field_expression_delta(
    monkeypatch,
    tmp_path,
):
    source = _node_split_repo(
        tmp_path,
        monkeypatch,
        source_text=(
            "typedef struct Entry { int stat_value; } Entry;\n"
            "void fn_test(Entry* entries, int i) {\n"
            "    int out;\n"
            "    out = entries[i].stat_value;\n"
            "    use(out);\n"
            "}\n"
        ),
    )
    delta_path = tmp_path / "node-set-delta.json"
    delta_path.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 40,
            "current_register": "r31",
            "desired_registers": ["r30"],
            "source": {
                "name": "stat_value",
                "expression": "entries[i].stat_value",
            },
        }],
    }), encoding="utf-8")

    def fake_compile_signature(path, **kwargs):
        label = kwargs["label"]
        if label == "baseline":
            return _sig(reg=31)
        if "introduce-binding" in label:
            return _sig(reg=30)
        return _sig(reg=31)

    def fake_score(patch, **kwargs):
        return CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=50.4,
            checkdiff_delta=0.4,
            pcdump_score_delta=None,
            diagnostics_path=None,
        )

    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        fake_score,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "--node-set-delta", str(delta_path),
        "--source-file", str(source),
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "improved"
    assert payload["generated_count"] > 0
    assert payload["best_candidate_id"].startswith(
        "node-split-introduce-binding-ig40-"
    )
    assert payload["request"]["source_expression"] == "entries[i].stat_value"
    assert payload["request"]["source_type"] == "int"
    assert any(
        candidate["objective_status"] == "realized"
        for candidate in payload["candidates"]
    )


def test_solve_node_set_split_skips_leading_unbindable_delta_entry(
    monkeypatch,
    tmp_path,
):
    source = _node_split_repo(
        tmp_path,
        monkeypatch,
        source_text=(
            "typedef struct Entry { int stat_value; } Entry;\n"
            "void fn_test(Entry* entries, int i) {\n"
            "    int out;\n"
            "    out = entries[i].stat_value;\n"
            "    use(out);\n"
            "}\n"
        ),
    )
    delta_path = tmp_path / "node-set-delta.json"
    delta_path.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 32,
                "current_register": "r31",
                "desired_registers": ["r29"],
                "source": {
                    "kind": "implicit-temp",
                    "expression": "add r3,r4,r5",
                },
            },
            {
                "target_ig": 37,
                "current_register": "r28",
                "desired_registers": ["r27"],
                "source": {
                    "kind": "field-load",
                    "expression": "entries[i].stat_value",
                },
            },
        ],
    }), encoding="utf-8")

    def fake_compile_signature(path, **kwargs):
        def sig_for(reg: int) -> BaselineSignature:
            return BaselineSignature(
                interference_edges=frozenset(),
                coalesce_mappings=frozenset(),
                spill_set=frozenset(),
                simplify_order=(37,),
                assigned_regs=frozenset({(37, reg)}),
            )

        label = kwargs["label"]
        if label == "baseline":
            return sig_for(28)
        if "introduce-binding-ig37" in label:
            return sig_for(27)
        return sig_for(28)

    def fake_score(patch, **kwargs):
        return CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=50.4,
            checkdiff_delta=0.4,
            pcdump_score_delta=None,
            diagnostics_path=None,
        )

    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        fake_score,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "--node-set-delta", str(delta_path),
        "--source-file", str(source),
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["request"]["target_ig"] == 37
    assert payload["best_candidate_id"].startswith(
        "node-split-introduce-binding-ig37-"
    )


def test_solve_node_set_split_routes_solve_coloring_json_wrapper_field_expression(
    monkeypatch,
    tmp_path,
):
    source = _node_split_repo(
        tmp_path,
        monkeypatch,
        source_text=(
            "typedef struct Entry { int stat_value; } Entry;\n"
            "void fn_test(Entry* entries, int i) {\n"
            "    int out;\n"
            "    out = entries[i].stat_value;\n"
            "    use(out);\n"
            "}\n"
        ),
    )
    delta_path = tmp_path / "solve-coloring.json"
    delta_path.write_text(json.dumps({
        "function": "fn_test",
        "class_id": 0,
        "exit_code": 3,
        "reason": "force-phys collision",
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "fn_test",
            "class_id": 0,
            "missing_virtuals": [{
                "target_ig": 40,
                "current_register": "r31",
                "desired_registers": ["r30"],
                "source": {
                    "name": "stat_value",
                    "expression": "entries[i].stat_value",
                },
            }],
        },
    }), encoding="utf-8")

    def fake_compile_signature(path, **kwargs):
        label = kwargs["label"]
        if label == "baseline":
            return _sig(reg=31)
        if "introduce-binding" in label:
            return _sig(reg=30)
        return _sig(reg=31)

    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        lambda patch, **_kwargs: CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=50.2,
            checkdiff_delta=0.2,
            pcdump_score_delta=None,
            diagnostics_path=None,
        ),
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "--node-set-delta", str(delta_path),
        "--source-file", str(source),
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "improved"
    assert payload["generated_count"] > 0
    assert payload["best_candidate_id"].startswith(
        "node-split-introduce-binding-ig40-"
    )
    assert "no matching missing virtual" not in (payload.get("blocked_reason") or "")


def test_solve_node_set_split_delta_infers_fpr_class_for_compile(
    monkeypatch,
    tmp_path,
):
    source = _node_split_repo(
        tmp_path,
        monkeypatch,
        source_text=(
            "typedef float f32;\n"
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 b;\n"
            "    f32 holder;\n"
            "    holder = a + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
    )
    delta_path = tmp_path / "solve-coloring-fpr.json"
    delta_path.write_text(json.dumps({
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "fn_test",
            "class_id": 1,
            "missing_virtuals": [{
                "target_ig": 33,
                "current_register": "f31",
                "desired_registers": ["f28"],
                "source": {"expression": "holder", "name": "holder"},
            }],
        },
    }), encoding="utf-8")
    compile_class_ids = []

    def fake_compile_signature(path, **kwargs):
        compile_class_ids.append(kwargs["class_id"])
        return BaselineSignature(
            interference_edges=frozenset(),
            coalesce_mappings=frozenset(),
            spill_set=frozenset(),
            simplify_order=(33,),
            assigned_regs=frozenset({(33, 31)}),
        )

    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_fresh_node_set_split_baseline_pct",
        lambda **_kwargs: (50.0, None),
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "--node-set-delta", str(delta_path),
        "--source-file", str(source),
        "--max-candidates", "1",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert payload["request"]["class_id"] == 1
    assert payload["request"]["current_reg"] == "f31"
    assert payload["request"]["target_reg"] == "f28"
    assert payload["generated_count"] > 0
    assert set(compile_class_ids) == {1}


def test_solve_node_set_split_exhausts_without_scoring_wrong_register(
    monkeypatch,
    tmp_path,
):
    source = _node_split_repo(tmp_path, monkeypatch)
    original = source.read_text(encoding="utf-8")
    score_calls = []

    def fake_compile_signature(path, **kwargs):
        return _sig(reg=31)

    def fake_score(patch, **kwargs):
        score_calls.append(patch.candidate_id)
        return CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=99.0,
            checkdiff_delta=49.0,
            pcdump_score_delta=None,
            diagnostics_path=None,
        )

    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        fake_score,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--target-reg", "r30",
        "--var", "holder",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "exhausted"
    assert payload["realized_count"] == 0
    assert score_calls == []
    assert source.read_text(encoding="utf-8") == original


def test_solve_node_set_split_coupled_reports_wrong_register_exhausted(
    monkeypatch,
    tmp_path,
):
    import src.mwcc_debug.node_set_split as node_set_split

    source = _node_split_repo(
        tmp_path,
        monkeypatch,
        source_text=(
            "void fn_test(void) {\n"
            "    int holder;\n"
            "    int other;\n"
            "    int out;\n"
            "    holder = make();\n"
            "    other = build();\n"
            "    out = holder + other;\n"
            "    use(out, holder, other);\n"
            "}\n"
        ),
    )
    delta_path = tmp_path / "node-set-delta.json"
    delta_path.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 34,
                "current_register": "r24",
                "desired_registers": ["r27"],
                "source": {"name": "holder", "expression": "holder"},
            },
            {
                "target_ig": 44,
                "current_register": "r27",
                "desired_registers": ["r25"],
                "source": {"name": "other", "expression": "other"},
            },
        ],
    }), encoding="utf-8")
    score_calls = []

    def fake_generate(source_text, function, requests, **kwargs):
        patched = source_text.replace(
            "out = holder + other;",
            "out = other + holder;",
        )
        return [
            CandidatePatch(
                "node-split-coupled-ig34+ig44-c0",
                patched,
                "coupled candidate",
                ((0, len(source_text)),),
                hunk="@@ coupled",
            )
        ]

    def fake_compile_signature(path, **kwargs):
        if kwargs["label"] == "baseline":
            return BaselineSignature(
                interference_edges=frozenset(),
                coalesce_mappings=frozenset(),
                spill_set=frozenset(),
                simplify_order=(34, 44),
                assigned_regs=frozenset({(34, 24), (44, 27)}),
            )
        return BaselineSignature(
            interference_edges=frozenset(),
            coalesce_mappings=frozenset(),
            spill_set=frozenset(),
            simplify_order=(34, 44),
            assigned_regs=frozenset({(34, 26), (44, 24)}),
        )

    def fake_score(patch, **kwargs):
        score_calls.append(patch.candidate_id)
        return CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=99.0,
            checkdiff_delta=49.0,
            pcdump_score_delta=None,
            diagnostics_path=None,
        )

    monkeypatch.setattr(
        node_set_split,
        "generate_coupled_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        fake_score,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "--coupled",
        "--node-set-delta", str(delta_path),
        "--source-file", str(source),
        "--json",
    ])

    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "exhausted"
    assert payload["objective_counts"] == {
        "wrong-register": payload["generated_count"]
    }
    assert payload["wrong_register_exhausted"] is True
    assert payload["terminal_reason"] == "all-wrong-register"
    assert payload["candidates"][0]["objective_status"] == "wrong-register"
    assert any(
        "+steer-" in row["candidate_id"] for row in payload["candidates"]
    )
    assert score_calls == []


def test_solve_node_set_split_coupled_tries_steering_after_wrong_register(
    monkeypatch,
    tmp_path,
):
    import src.mwcc_debug.node_set_split as node_set_split
    import src.search.directed.transform_corpus as transform_corpus

    source = _node_split_repo(
        tmp_path,
        monkeypatch,
        source_text=(
            "void fn_test(void) {\n"
            "    int holder;\n"
            "    int other;\n"
            "    int out;\n"
            "    holder = make();\n"
            "    other = build();\n"
            "    out = holder + other;\n"
            "    use(out, holder, other);\n"
            "}\n"
        ),
    )
    delta_path = tmp_path / "node-set-delta.json"
    delta_path.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 34,
                "current_register": "r24",
                "desired_registers": ["r27"],
                "source": {"name": "holder", "expression": "holder"},
            },
            {
                "target_ig": 44,
                "current_register": "r27",
                "desired_registers": ["r25"],
                "source": {"name": "other", "expression": "other"},
            },
        ],
    }), encoding="utf-8")
    score_calls = []
    transform_calls = []

    def fake_generate(source_text, function, requests, **kwargs):
        patched = source_text.replace(
            "out = holder + other;",
            "out = other + holder;",
        )
        return [
            CandidatePatch(
                "node-split-coupled-ig34+ig44-c0",
                patched,
                "coupled candidate",
                ((0, len(source_text)),),
                hunk="@@ coupled",
            )
        ]

    def fake_transform_probes(source_text, **kwargs):
        transform_calls.append(kwargs)
        steered = source_text.replace(
            "use(out, holder, other);",
            "out = out;\n    use(out, holder, other);",
        )
        return (
            SimpleNamespace(
                probe_id="coloring_register_steering@0",
                family_id="coloring_register_steering",
                family_label="coloring register steering",
                mutator_key="steer_rotate_local_decl_window",
                candidate_text=steered,
            ),
        )

    def fake_compile_signature(path, **kwargs):
        label = kwargs["label"]
        if label == "baseline":
            regs = {(34, 24), (44, 27)}
        elif "+steer-" in label:
            regs = {(34, 27), (44, 25)}
        else:
            regs = {(34, 26), (44, 24)}
        return BaselineSignature(
            interference_edges=frozenset(),
            coalesce_mappings=frozenset(),
            spill_set=frozenset(),
            simplify_order=(34, 44),
            assigned_regs=frozenset(regs),
        )

    def fake_score(patch, **kwargs):
        score_calls.append(patch.candidate_id)
        return CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=50.7,
            checkdiff_delta=0.7,
            pcdump_score_delta=None,
            diagnostics_path=None,
        )

    monkeypatch.setattr(
        node_set_split,
        "generate_coupled_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        transform_corpus,
        "generate_transform_probes",
        fake_transform_probes,
    )
    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        fake_score,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "--coupled",
        "--node-set-delta", str(delta_path),
        "--source-file", str(source),
        "--max-candidates", "3",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "improved"
    assert payload["objective_counts"] == {
        "wrong-register": 1,
        "realized": 1,
    }
    assert payload["best_candidate_id"].endswith(
        "+steer-coloring_register_steering@0"
    )
    assert score_calls == [payload["best_candidate_id"]]
    assert transform_calls[0]["families"] == ("coloring_register_steering",)
    assert transform_calls[0]["force_phys"] == {34: 27, 44: 25}


def test_solve_node_set_split_coupled_accepts_introducible_address_request(
    monkeypatch,
    tmp_path,
):
    import src.mwcc_debug.node_set_split as node_set_split

    source = _node_split_repo(
        tmp_path,
        monkeypatch,
        source_text=(
            "typedef struct NameEntry NameEntry;\n"
            "void fn_test(NameEntry* sorted_names, int i) {\n"
            "    int holder;\n"
            "    NameEntry* cursor;\n"
            "    holder = make();\n"
            "    cursor = &sorted_names[i];\n"
            "    use(holder, cursor);\n"
            "}\n"
        ),
    )
    delta_path = tmp_path / "node-set-delta.json"
    delta_path.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 34,
                "current_register": "r24",
                "desired_registers": ["r27"],
                "source": {"name": "holder", "expression": "holder"},
            },
            {
                "target_ig": 44,
                "current_register": "r27",
                "desired_registers": ["r25"],
                "source": {
                    "kind": "implicit-temp",
                    "expression": "&sorted_names[i]",
                },
            },
        ],
    }), encoding="utf-8")
    seen_requests = []

    def fake_generate(_source_text, _function, requests, **_kwargs):
        seen_requests.extend(requests)
        return []

    monkeypatch.setattr(
        node_set_split,
        "generate_coupled_node_set_split_patches",
        fake_generate,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "--coupled",
        "--node-set-delta", str(delta_path),
        "--source-file", str(source),
        "--json",
    ])

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["blocked_reason"].startswith("no coupled candidates generated")
    assert [request.target_ig for request in seen_requests] == [34, 44]
    assert seen_requests[0].var_name == "holder"
    assert seen_requests[1].var_name is None
    assert seen_requests[1].source_expression == "&sorted_names[i]"
    assert seen_requests[1].source_type == "NameEntry*"
    assert payload["coupled_requests"][1]["source_type"] == "NameEntry*"


def test_node_set_split_steering_children_filter_to_request_variables(monkeypatch):
    import src.search.directed.transform_corpus as transform_corpus

    source = (
        "void fn_test(void) {\n"
        "    int jobj;\n"
        "    int jobj2;\n"
        "    int holder;\n"
        "    int other;\n"
        "    use(jobj, jobj2, holder, other);\n"
        "}\n"
    )
    patch = CandidatePatch("base", source, "base candidate", (), "")
    calls = []

    def fake_transform_probes(source_text, **kwargs):
        calls.append(kwargs)
        return (
            SimpleNamespace(
                probe_id="coloring_register_steering@0",
                family_id="coloring_register_steering",
                family_label="coloring register steering",
                mutator_key="steer_reorder_local_decls",
                span=(source.index("    int jobj;"), source.index("    int holder;")),
                payload={"first_line": "    int jobj;"},
                candidate_text=source.replace(
                    "    int jobj;\n    int jobj2;",
                    "    int jobj2;\n    int jobj;",
                ),
            ),
            SimpleNamespace(
                probe_id="coloring_register_steering@1",
                family_id="coloring_register_steering",
                family_label="coloring register steering",
                mutator_key="steer_reorder_local_decls",
                span=(source.index("    int holder;"), source.index("    int other;")),
                payload={"first_line": "    int holder;"},
                candidate_text=source.replace(
                    "    int holder;\n    int other;",
                    "    int other;\n    int holder;",
                ),
            ),
        )

    monkeypatch.setattr(
        transform_corpus,
        "generate_transform_probes",
        fake_transform_probes,
    )

    children = debugcli._node_set_split_steering_children(
        patch,
        function="fn_test",
        unit="melee/mn/demo",
        coupled_requests=[
            SimpleNamespace(target_ig=34, target_reg="r27", var_name="holder"),
            SimpleNamespace(target_ig=44, target_reg="r25", var_name="other"),
        ],
        seen_sources=set(),
        max_per_family=1,
    )

    assert calls[0]["max_per_family"] > 1
    assert len(children) == 1
    assert children[0].candidate_id.endswith("+steer-coloring_register_steering@1")
    assert "int other;\n    int holder;" in children[0].patched_source


def test_node_set_split_steering_children_use_target_color_leads(monkeypatch):
    import src.mwcc_debug.pressure_explorer as pressure_explorer
    import src.search.directed.transform_corpus as transform_corpus

    source = (
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    int other;\n"
        "    use(holder, other);\n"
        "}\n"
    )
    patch = CandidatePatch("base", source, "base candidate", (), "")

    def fail_transform_probes(*_args, **_kwargs):
        raise AssertionError("target-color leads should fill the bounded child set")

    def fake_lifetime_probes(source_text, function, **kwargs):
        assert function == "fn_test"
        assert kwargs["max_probes"] >= 2
        return [
            SimpleNamespace(
                label="block-scope",
                operator="block-scope",
                source_text=source_text.replace(
                    "    int holder;\n",
                    "    { int holder_alias = holder; }\n    int holder;\n",
                ),
            ),
            SimpleNamespace(
                label="decl-swap",
                operator="decl-swap",
                source_text=source_text.replace(
                    "    int holder;\n    int other;",
                    "    int other;\n    int holder;",
                ),
            ),
        ]

    monkeypatch.setattr(
        pressure_explorer,
        "generate_lifetime_layout_probes",
        fake_lifetime_probes,
    )
    monkeypatch.setattr(
        transform_corpus,
        "generate_transform_probes",
        fail_transform_probes,
    )

    children = debugcli._node_set_split_steering_children(
        patch,
        function="fn_test",
        unit="melee/mn/demo",
        coupled_requests=[
            SimpleNamespace(target_ig=49, target_reg="r25", var_name="holder"),
        ],
        objective={
            "status": "wrong-register",
            "target_color_select_order_leads": [
                {"target_order": [38, 49], "target_reg": 26},
                {"target_order": [36, 41], "target_reg": 27},
            ],
        },
        seen_sources=set(),
        max_per_family=2,
    )

    assert len(children) == 2
    assert "+target-color-r38_r49-block-scope" in children[0].candidate_id
    assert "+target-color-r36_r41-decl-swap" in children[1].candidate_id
    assert "target-color select-order r38<r49" in children[0].summary
    assert "target-color select-order r36<r41" in children[1].summary


def test_solve_node_set_split_non_coupled_annotates_fresh_pcdump(
    monkeypatch,
    tmp_path,
):
    import src.mwcc_debug.node_set_split as node_set_split
    import src.mwcc_debug.tiebreak as tiebreak

    _node_split_repo(tmp_path, monkeypatch)
    patch = CandidatePatch(
        "cand-wrong",
        "void fn_test(void) { use(1); }\n",
        "candidate",
        (),
        "",
    )
    seen_pcdumps = []
    seen_request_sets = []

    def fake_generate(*_args, **_kwargs):
        return [patch]

    def fake_compile(path, **kwargs):
        if kwargs["label"] == "baseline":
            return _sig(reg=31), "baseline-pcdump"
        return _sig(reg=29), "candidate-pcdump"

    def fake_load_ig(pcdump_text, function, **kwargs):
        seen_pcdumps.append((pcdump_text, function, kwargs.get("class_id")))
        return None

    def fake_children(_patch, **kwargs):
        seen_request_sets.append(kwargs["coupled_requests"])
        return []

    monkeypatch.setattr(
        node_set_split,
        "generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile,
        raising=False,
    )
    monkeypatch.setattr(tiebreak, "load_ig", fake_load_ig)
    monkeypatch.setattr(debugcli, "_node_set_split_steering_children", fake_children)

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--target-reg", "r30",
        "--var", "holder",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    assert seen_pcdumps == [("candidate-pcdump", "fn_test", 0)]
    assert len(seen_request_sets) == 1
    assert [request.target_ig for request in seen_request_sets[0]] == [40]


def test_solve_node_set_split_scores_against_fresh_baseline(
    monkeypatch,
    tmp_path,
):
    _node_split_repo(tmp_path, monkeypatch)
    baseline_calls = []

    def fake_compile_signature(path, **kwargs):
        label = kwargs["label"]
        return _sig(reg=31 if label == "baseline" else 30)

    def fake_score(patch, **kwargs):
        baseline_calls.append(kwargs["baseline_pct"])
        return CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=50.4,
            checkdiff_delta=50.4 - kwargs["baseline_pct"],
            pcdump_score_delta=None,
            diagnostics_path=None,
        )

    monkeypatch.setattr(debugcli, "_get_match_pct", lambda function, root: 50.0)
    monkeypatch.setattr(
        debugcli,
        "_build_and_match_with_diagnostic",
        lambda unit, function, root, **_kwargs: (50.5, None),
    )
    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        fake_score,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--target-reg", "r30",
        "--var", "holder",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "exhausted"
    assert baseline_calls
    assert all(value == 50.5 for value in baseline_calls)


def test_solve_node_set_split_uses_repo_local_probe_dir(
    monkeypatch,
    tmp_path,
):
    _node_split_repo(tmp_path, monkeypatch)
    compiled_paths = []

    def fake_compile_signature(path, **kwargs):
        label = kwargs["label"]
        compiled_paths.append((label, path))
        return _sig(reg=31 if label == "baseline" else 30)

    def fake_score(patch, **kwargs):
        return CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=50.0,
            checkdiff_delta=0.0,
            pcdump_score_delta=None,
            diagnostics_path=None,
        )

    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        fake_score,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--target-reg", "r30",
        "--var", "holder",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    candidate_paths = [
        path for label, path in compiled_paths
        if label != "baseline"
    ]
    assert candidate_paths
    probe_root = (
        tmp_path
        / "build"
        / "mwcc_debug_cache"
        / "probes"
        / "node_set_split"
    )
    assert all(path.is_relative_to(probe_root) for path in candidate_paths)
    assert list(probe_root.glob("node_set_split_*")) == []


def test_solve_node_set_split_retains_compile_failed_candidate_source(
    monkeypatch,
    tmp_path,
):
    source = _node_split_repo(tmp_path, monkeypatch)

    def fake_compile_signature(path, **kwargs):
        if kwargs["label"] == "baseline":
            return _sig(reg=31)
        raise RuntimeError("synthetic compile failure")

    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--target-reg", "r30",
        "--var", "holder",
        "--source-file", str(source),
        "--max-candidates", "1",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    row = payload["candidates"][0]
    assert row["objective_status"] == "compile-failed"
    diagnostics_path = Path(row["diagnostics_path"])
    probe_root = (
        tmp_path
        / "build"
        / "mwcc_debug_cache"
        / "probes"
        / "node_set_split"
    )
    assert diagnostics_path.is_relative_to(probe_root / "compile_failed")
    assert diagnostics_path.exists()
    assert diagnostics_path.read_text(encoding="utf-8").startswith("void fn_test")
    assert list(probe_root.glob("node_set_split_*")) == []


def test_node_set_split_signature_compiles_same_tu_probe_via_unit_source(
    monkeypatch,
    tmp_path,
):
    import src.mwcc_debug.diff_capture as diff_capture
    import src.mwcc_debug.simplify_search as simplify_search

    melee_root = tmp_path
    unit_source = melee_root / "src" / "melee" / "mn" / "demo.c"
    unit_source.parent.mkdir(parents=True)
    unit_source.write_text(
        "void fn_test(void) {\n"
        "    use(0);\n"
        "}\n",
        encoding="utf-8",
    )
    probe = melee_root / "build" / "mwcc_debug_cache" / "probes" / "cand.c"
    probe.parent.mkdir(parents=True)
    probe.write_text(
        "void fn_test(void) {\n"
        "    use(1);\n"
        "}\n",
        encoding="utf-8",
    )
    seen = {}

    def fake_compile_source_variant(diff_input, **kwargs):
        compile_path = diff_input.path
        seen["path"] = compile_path
        seen["exists_during_compile"] = compile_path.exists()
        seen["text"] = compile_path.read_text(encoding="utf-8")
        seen["unit_source"] = kwargs["unit_source"]
        return "pcdump"

    monkeypatch.setattr(diff_capture, "compile_source_variant",
                        fake_compile_source_variant)
    monkeypatch.setattr(debugcli, "parse_hook_events", lambda _text: ["events"])
    monkeypatch.setattr(debugcli, "find_function",
                        lambda events, function: {"events": events})
    monkeypatch.setattr(simplify_search, "baseline_signature",
                        lambda events, class_id: _sig(reg=30))

    sig = debugcli._node_set_split_compile_signature(
        probe,
        label="candidate",
        function="fn_test",
        class_id=0,
        melee_root=melee_root,
        timeout=30,
        unit_source=unit_source,
    )

    assert sig.assigned_regs == frozenset({(40, 30)})
    assert seen["exists_during_compile"] is True
    assert seen["text"] == probe.read_text(encoding="utf-8")
    assert seen["unit_source"] == unit_source
    assert seen["path"] == unit_source
    assert unit_source.read_text(encoding="utf-8") == (
        "void fn_test(void) {\n"
        "    use(0);\n"
        "}\n"
    )
    assert probe.exists()


def test_solve_node_set_split_budget_zero_skips_candidate_work(
    monkeypatch,
    tmp_path,
):
    _node_split_repo(tmp_path, monkeypatch)
    patches = [
        CandidatePatch(f"cand-{idx}", "void fn_test(void) {}\n", "candidate", (), "")
        for idx in range(3)
    ]
    compile_labels = []

    def fake_generate(*_args, **_kwargs):
        return patches

    def fake_compile_signature(path, **kwargs):
        compile_labels.append(kwargs["label"])
        return _sig(reg=31)

    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split.generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--target-reg", "r30",
        "--var", "holder",
        "--budget", "0",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "exhausted"
    assert payload["stop_condition"]["kind"] == "budget-exhausted"
    assert payload["generated_count"] == 3
    assert payload["scored_count"] == 0
    assert payload["evaluated_count"] == 0
    assert payload["pending_count"] == 3
    assert payload["omitted_count"] == 3
    assert payload["exhaustive"] is False
    assert compile_labels == []


def test_solve_node_set_split_coupled_generation_honors_budget(
    monkeypatch,
    tmp_path,
):
    source = _node_split_repo(
        tmp_path,
        monkeypatch,
        source_text=(
            "void fn_test(void) {\n"
            "    int holder;\n"
            "    int other;\n"
            "    use(holder, other);\n"
            "}\n"
        ),
    )
    delta_path = tmp_path / "node-set-delta.json"
    delta_path.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 34,
                "current_register": "r24",
                "desired_registers": ["r27"],
                "source": {"name": "holder", "expression": "holder"},
            },
            {
                "target_ig": 44,
                "current_register": "r27",
                "desired_registers": ["r25"],
                "source": {"name": "other", "expression": "other"},
            },
        ],
    }), encoding="utf-8")
    clock = {"now": 100.0}
    compile_labels = []

    def fake_generate(*_args, deadline=None, **_kwargs):
        assert deadline == 101.0
        clock["now"] = 102.0
        return []

    def fake_compile_signature(path, **kwargs):
        compile_labels.append(kwargs["label"])
        return _sig(reg=31)

    monkeypatch.setattr(debugcli.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split.generate_coupled_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "--coupled",
        "--node-set-delta", str(delta_path),
        "--source-file", str(source),
        "--max-candidates", "0",
        "--budget", "1",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "exhausted"
    assert payload["stop_condition"]["kind"] == "budget-exhausted"
    assert payload["generated_count"] == 0
    assert payload["evaluated_count"] == 0
    assert compile_labels == []


def test_solve_node_set_split_max_candidates_stops_after_cap(
    monkeypatch,
    tmp_path,
):
    _node_split_repo(tmp_path, monkeypatch)
    patches = [
        CandidatePatch(
            f"cand-{idx}",
            f"void fn_test(void) {{ use({idx}); }}\n",
            "candidate",
            (),
            "",
        )
        for idx in range(3)
    ]
    compile_labels = []

    def fake_generate(*_args, **_kwargs):
        return patches

    def fake_compile_signature(path, **kwargs):
        compile_labels.append(kwargs["label"])
        return _sig(reg=31)

    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split.generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--target-reg", "r30",
        "--var", "holder",
        "--max-candidates", "1",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "exhausted"
    assert payload["stop_condition"]["kind"] == "candidate-limit"
    assert payload["generated_count"] == 3
    assert payload["scored_count"] == 1
    assert payload["evaluated_count"] == 1
    assert payload["pending_count"] == 2
    assert payload["omitted_count"] == 2
    assert payload["candidate_limit"] == 1
    assert payload["exhaustive"] is False
    assert compile_labels == ["baseline", "cand-0"]


def test_solve_node_set_split_improved_status_wins_before_candidate_cap(
    monkeypatch,
    tmp_path,
):
    _node_split_repo(tmp_path, monkeypatch)
    patches = [
        CandidatePatch(
            "cand-realized",
            "void fn_test(void) { use(1); }\n",
            "candidate",
            (),
            "",
        ),
        CandidatePatch(
            "cand-omitted",
            "void fn_test(void) { use(2); }\n",
            "candidate",
            (),
            "",
        ),
    ]

    def fake_generate(*_args, **_kwargs):
        return patches

    def fake_compile_signature(path, **kwargs):
        return _sig(reg=31 if kwargs["label"] == "baseline" else 30)

    def fake_score(patch, **kwargs):
        return CandidateScore(
            patch.candidate_id,
            compile_ok=True,
            checkdiff_pct=50.5,
            checkdiff_delta=0.5,
            pcdump_score_delta=None,
            diagnostics_path=None,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split.generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_score_node_set_split_candidate",
        fake_score,
        raising=False,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--target-reg", "r30",
        "--var", "holder",
        "--max-candidates", "1",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "improved"
    assert payload["stop_condition"]["kind"] == "candidate-limit"
    assert payload["best_candidate_id"] == "cand-realized"
    assert payload["evaluated_count"] == 1
    assert payload["omitted_count"] == 1


def test_solve_node_set_split_baseline_refresh_gets_timeout_without_budget(
    monkeypatch,
    tmp_path,
):
    _node_split_repo(tmp_path, monkeypatch)
    patches = [
        CandidatePatch(
            "cand-0",
            "void fn_test(void) { use(0); }\n",
            "candidate",
            (),
            "",
        )
    ]
    seen = {}

    def fake_generate(*_args, **_kwargs):
        return patches

    def fake_compile_signature(path, **kwargs):
        return _sig(reg=31)

    def fake_baseline_pct(**kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return 50.0, None

    monkeypatch.setattr(
        "src.mwcc_debug.node_set_split.generate_node_set_split_patches",
        fake_generate,
    )
    monkeypatch.setattr(
        debugcli,
        "_node_set_split_compile_signature_and_pcdump",
        fake_compile_signature,
        raising=False,
    )
    monkeypatch.setattr(
        debugcli,
        "_fresh_node_set_split_baseline_pct",
        fake_baseline_pct,
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "-f", "fn_test",
        "--class", "gpr",
        "--ig", "40",
        "--target-reg", "r30",
        "--var", "holder",
        "--timeout", "7",
        "--json",
    ])

    assert result.exit_code == 4, result.output
    assert seen["timeout"] == 7.0


def test_score_node_set_split_candidate_passes_deadline(
    monkeypatch,
    tmp_path,
):
    patch = CandidatePatch(
        "cand-0",
        "void fn_test(void) { use(0); }\n",
        "candidate",
        (),
        "",
    )
    seen = {}

    def fake_score_source(path, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(match_percent=50.5, match_percent_error=None)

    monkeypatch.setattr(
        debugcli,
        "_score_source_candidate_real_tree",
        fake_score_source,
    )

    score = debugcli._score_node_set_split_candidate(
        patch,
        function="fn_test",
        source_path=tmp_path / "demo.c",
        baseline_pct=50.0,
        melee_root=tmp_path,
        timeout=11.0,
        deadline=123.0,
        temp_dir=tmp_path,
    )

    assert score.compile_ok is True
    assert score.checkdiff_delta == 0.5
    assert seen["timeout"] == 11.0
    assert seen["deadline"] == 123.0


def test_apply_node_set_split_patch_reports_restore_failure(
    monkeypatch,
    tmp_path,
):
    source = _node_split_repo(tmp_path, monkeypatch)
    original = source.read_text(encoding="utf-8")
    patch = SimpleNamespace(
        candidate_id="bad-build",
        patched_source=original.replace(
            "    int holder;\n",
            "    int holder;\n    int holder_split_40_0;\n",
        ),
    )

    @contextmanager
    def noop_lock(_root):
        yield

    monkeypatch.setattr(debugcli, "_acquire_source_score_repo_lock", noop_lock)
    monkeypatch.setattr(
        debugcli,
        "_run_ninja_with_no_diag_retry",
        lambda *args, **kwargs: (
            SimpleNamespace(returncode=1, stdout="", stderr="compile failed"),
            False,
        ),
    )
    monkeypatch.setattr(
        debugcli,
        "_restore_object_report_for_unit",
        lambda **kwargs: (
            SimpleNamespace(returncode=125, stdout="", stderr="restore refused"),
            99,
        ),
    )

    pct, error = debugcli._apply_node_set_split_patch(
        patch,
        function="fn_test",
        unit="melee/mn/demo",
        source_path=source,
        melee_root=tmp_path,
        timeout=1,
    )

    assert pct is None
    assert error is not None
    assert "compile failed" in error
    assert "restore refused" in error
    assert source.read_text(encoding="utf-8") == original


def test_solve_coloring_exit0_and_json(monkeypatch):
    monkeypatch.setattr(
        debugcli, "_run_solve_coloring",
        lambda **kw: SolveResult(exit_code=0, reason="ok", worksheet=_ws()))
    result = runner.invoke(debugcli.debug_app, [
        "solve", "coloring", "-f", "mnDiagram_80241E78", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["function"] == "mnDiagram_80241E78"
    assert payload["candidates"][0]["surrogate_confidence"] == "high"


def test_solve_coloring_abstain_exit3(monkeypatch):
    monkeypatch.setattr(
        debugcli, "_run_solve_coloring",
        lambda **kw: SolveResult(exit_code=3, reason="G1 0.800 < 100%"))
    result = runner.invoke(debugcli.debug_app, ["solve", "coloring", "-f", "f"])
    assert result.exit_code == 3, result.output
    assert "G1" in result.output


def test_solve_coloring_abstain_prints_node_set_delta(monkeypatch):
    delta = {
        "kind": "node-set-delta",
        "blocker": "structurally-different-virtual",
        "missing_virtuals": [{
            "target_ig": 42,
            "desired_registers": ["r27", "r28"],
            "current_register": "r29",
            "source_action": "Introduce a named temp before line 120.",
        }],
    }
    monkeypatch.setattr(
        debugcli, "_run_solve_coloring",
        lambda **kw: SolveResult(
            exit_code=3,
            reason="force-phys collision: target coloring unreachable",
            node_set_delta=delta,
        ),
    )

    result = runner.invoke(debugcli.debug_app, ["solve", "coloring", "-f", "f"])

    assert result.exit_code == 3, result.output
    assert "node-set delta" in result.output
    assert "ig42" in result.output
    assert "r27,r28" in result.output
    assert "Introduce a named temp" in result.output


def test_solve_coloring_abstain_json_includes_node_set_delta(monkeypatch):
    delta = {
        "kind": "node-set-delta",
        "blocker": "structurally-different-virtual",
        "missing_virtuals": [{
            "target_ig": 42,
            "desired_registers": ["r27"],
            "source_action": "Introduce a named temp.",
        }],
    }
    monkeypatch.setattr(
        debugcli, "_run_solve_coloring",
        lambda **kw: SolveResult(
            exit_code=3,
            reason="force-phys collision: target coloring unreachable",
            node_set_delta=delta,
        ),
    )

    result = runner.invoke(
        debugcli.debug_app,
        ["solve", "coloring", "-f", "f", "--json"],
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.output)
    assert payload["reason"].startswith("force-phys collision")
    assert payload["node_set_delta"]["missing_virtuals"][0]["target_ig"] == 42


def test_derive_node_set_delta_payload_names_source_intro_point():
    ig = IG(
        class_id=0,
        select_order=[42],
        nodes={
            42: IGNode(
                ig_idx=42,
                neighbors={40, 41},
                precolored={},
                array_size=2,
                incomplete=False,
                observed_reg=29,
            )
        },
        decision_igs={42},
    )
    source = SimpleNamespace(
        kind="local",
        name="stat_value",
        type="int",
        source_file="src/melee/mn/mndiagram2.c",
        source_line=120,
        source_col=9,
        expression="entries[i].stat_value",
        base_virtual=None,
        base_var=None,
        field_offset=None,
        field_name=None,
        confidence="exact",
    )
    report = SimpleNamespace(
        virtuals=(
            SimpleNamespace(ig_idx=42, live_range=(18, 31), source=source),
        )
    )

    payload = debugcli._derive_node_set_delta_payload(
        function="f",
        class_id=0,
        ig=ig,
        phys_target={},
        phys_conflicts=[{
            "class_id": 0,
            "kind": "r",
            "ig_idx": 42,
            "existing_phys": 27,
            "conflicting_phys": 28,
        }],
        report=report,
    )

    entry = payload["missing_virtuals"][0]
    assert entry["target_ig"] == 42
    assert entry["current_register"] == "r29"
    assert entry["desired_registers"] == ["r27", "r28"]
    assert entry["live_range"] == [18, 31]
    assert "entries[i].stat_value" in entry["source_action"]
    assert "src/melee/mn/mndiagram2.c:120" in entry["source_action"]


def test_derive_node_set_delta_payload_uses_fpr_prefix_for_class_one():
    ig = IG(
        class_id=1,
        select_order=[33],
        nodes={
            33: IGNode(
                ig_idx=33,
                neighbors={39},
                precolored={},
                array_size=2,
                incomplete=False,
                observed_reg=31,
            )
        },
        decision_igs={33},
    )
    source = SimpleNamespace(
        kind="local",
        name="row_offset",
        type="f32",
        source_file="src/melee/mn/mndiagram.c",
        source_line=2079,
        source_col=5,
        expression="row_offset",
        base_virtual=None,
        base_var=None,
        field_offset=None,
        field_name=None,
        confidence="exact",
    )
    report = SimpleNamespace(
        virtuals=(
            SimpleNamespace(ig_idx=33, live_range=(10, 20), source=source),
        )
    )

    payload = debugcli._derive_node_set_delta_payload(
        function="mnDiagram_80241E78",
        class_id=1,
        ig=ig,
        phys_target={33: 28},
        phys_conflicts=[],
        report=report,
    )

    entry = payload["missing_virtuals"][0]
    assert payload["class_id"] == 1
    assert payload["register_prefix"] == "f"
    assert entry["current_virtual"] == "f33"
    assert entry["current_register"] == "f31"
    assert entry["desired_registers"] == ["f28"]


def test_node_set_delta_conflict_index_parser_ignores_malformed_rows():
    assert debugcli._solve_conflict_ig_idx({"ig_idx": "42"}) == 42
    assert debugcli._solve_conflict_ig_idx({"ig_idx": "not-an-int"}) is None
    assert debugcli._solve_conflict_ig_idx({"existing_phys": 27}) is None
    assert debugcli._solve_conflict_ig_idx("not-a-dict") is None


def test_solve_coloring_exit4(monkeypatch):
    monkeypatch.setattr(
        debugcli, "_run_solve_coloring",
        lambda **kw: SolveResult(exit_code=4, reason="window-order",
                                 worksheet=_ws()))
    result = runner.invoke(debugcli.debug_app, ["solve", "coloring", "-f", "f"])
    assert result.exit_code == 4, result.output


def test_solve_coloring_passes_kinds_and_catalog_default(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return SolveResult(exit_code=4, reason="x", worksheet=_ws())

    monkeypatch.setattr(debugcli, "_run_solve_coloring", fake)
    result = runner.invoke(debugcli.debug_app, ["solve", "coloring", "-f", "f"])
    assert result.exit_code == 4
    assert seen["kinds"] == ["node-add", "edge", "order"]   # advertised default
    assert str(seen["catalog_dir"]).endswith("docs/superpowers/lever-catalog")


def test_solve_coloring_defaults_to_union_only_force_vector_verify(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return SolveResult(exit_code=4, reason="x", worksheet=_ws())

    monkeypatch.setattr(debugcli, "_run_solve_coloring", fake)
    result = runner.invoke(debugcli.debug_app, ["solve", "coloring", "-f", "f"])

    assert result.exit_code == 4
    assert seen["force_vector_probes"] is False
    assert seen["force_vector_timeout"] is None


def test_solve_coloring_allows_force_vector_probe_opt_in_and_timeout(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return SolveResult(exit_code=4, reason="x", worksheet=_ws())

    monkeypatch.setattr(debugcli, "_run_solve_coloring", fake)
    result = runner.invoke(debugcli.debug_app, [
        "solve", "coloring", "-f", "f",
        "--force-vector-probes",
        "--force-vector-timeout", "45",
    ])

    assert result.exit_code == 4
    assert seen["force_vector_probes"] is True
    assert seen["force_vector_timeout"] == 45.0


def test_solve_coloring_fpr_order_emits_window_order_fallback(monkeypatch):
    seen = {}
    ws = _ws()
    ws.class_id = 1
    ws.candidates = []
    ws.tooling_leads = []
    ws.window_order = []
    ws.reachable = False

    def fake_solve(**kw):
        seen.update(kw)
        return SolveResult(exit_code=4, reason="no actionable candidate",
                           worksheet=ws)

    monkeypatch.setattr(debugcli, "_run_solve_coloring", fake_solve)
    monkeypatch.setattr(
        debugcli,
        "_register_tiebreak_window_order_fallback",
        lambda **_kw: {
            "ran": True,
            "reason": "window-order fallback leads found",
            "leads": [{
                "target_ig": 39,
                "observed_reg": 28,
                "predicted_reg": 28,
                "perturbed_reg": 26,
                "order_move": ["after", 32],
                "degree": 30,
                "move_distance": 5,
            }],
        },
    )

    result = runner.invoke(debugcli.debug_app, [
        "solve", "coloring", "-f", "mnDiagram_80241E78",
        "--class", "fpr", "--kinds", "order",
    ])

    assert result.exit_code == 0, result.output
    assert seen["allow_unreachable_order"] is True
    assert "move ig39 after ig32: f28 -> f26" in result.output
    assert "window-order fallback lead(s) found" in result.output


def test_collect_order_target_inputs_uses_package_checkdiff_for_worktree(
    monkeypatch,
    tmp_path,
):
    package_root = tmp_path / "package"
    worktree = tmp_path / "worktree"
    package_checkdiff = package_root / "tools" / "checkdiff.py"
    worktree_checkdiff = worktree / "tools" / "checkdiff.py"
    package_checkdiff.parent.mkdir(parents=True)
    worktree_checkdiff.parent.mkdir(parents=True)
    package_checkdiff.write_text("# current package checkdiff\n", encoding="utf-8")
    worktree_checkdiff.write_text("# stale worktree checkdiff\n", encoding="utf-8")
    source = worktree / "src" / "melee" / "mn" / "mndiagram.c"
    source.parent.mkdir(parents=True)
    source.write_text("void f(void) {}\n", encoding="utf-8")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "classification": {"primary": "instruction-sequence"},
                "target_asm": [],
                "current_asm": [],
            }),
            stderr="",
        )

    monkeypatch.setattr(debugcli, "_package_melee_root", lambda: package_root)
    monkeypatch.setattr(debugcli.subprocess, "run", fake_run)

    result = debugcli._collect_order_target_inputs(
        function="f",
        unit="melee/mn/mndiagram",
        class_id=0,
        melee_root=worktree,
        checkdiff_timeout=1.0,
    )

    assert result.checkdiff_primary == "instruction-sequence"
    assert calls
    argv, kwargs = calls[0]
    assert argv[1] == str(package_checkdiff)
    assert kwargs["cwd"] == worktree


def test_package_melee_root_resolves_repo_root():
    package_root = debugcli._package_melee_root()

    assert (package_root / "config" / "GALE01").is_dir()
    assert (package_root / "tools" / "checkdiff.py").is_file()


def test_run_solve_coloring_fpr_reaches_order_target_collection(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "src" / "melee" / "mn" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void f(void) {}\n", encoding="utf-8")
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text("Starting function f\n", encoding="utf-8")

    class ReachedOrderTargetCollection(Exception):
        pass

    monkeypatch.setattr(debugcli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(
        debugcli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/mn/demo",
    )
    monkeypatch.setattr(
        debugcli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root: pcdump,
    )
    monkeypatch.setattr(
        debugcli,
        "_load_checkdiff_normalized_structural_lines",
        lambda melee_root: (lambda *args, **kwargs: []),
    )

    def raise_reached(**kwargs):
        assert kwargs["class_id"] == 1
        raise ReachedOrderTargetCollection

    monkeypatch.setattr(debugcli, "_collect_order_target_inputs", raise_reached)

    with pytest.raises(ReachedOrderTargetCollection):
        debugcli._run_solve_coloring(
            function="f",
            class_id=1,
            pcdump=None,
            max_perturb=2,
            frontier=32,
            kinds=["order"],
            experimental_kinds=[],
            catalog_dir="/tmp/no-catalog",
        )


def test_collect_order_target_inputs_empty_force_vector_window_abstains(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "src" / "melee" / "mn" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void f(void) {}\n", encoding="utf-8")
    asm = tmp_path / "build" / "GALE01" / "asm" / "melee" / "mn" / "demo.s"
    asm.parent.mkdir(parents=True)
    asm.write_text("f:\n", encoding="utf-8")
    checkdiff = tmp_path / "tools" / "checkdiff.py"
    checkdiff.parent.mkdir(parents=True)
    checkdiff.write_text("# fake\n", encoding="utf-8")

    def fake_run(argv, **kwargs):
        if "debug" in argv and "dump" in argv and "local" in argv:
            output = Path(argv[argv.index("--output") + 1])
            output.write_text("pcdump", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "classification": {"primary": "register-allocation"},
                "target_asm": [],
                "current_asm": [],
            }),
            stderr="",
        )

    fn = SimpleNamespace(
        name="f",
        last_precolor_pass=lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(debugcli.subprocess, "run", fake_run)
    monkeypatch.setattr(debugcli, "_checkdiff_script_path", lambda root: checkdiff)
    monkeypatch.setattr(debugcli, "parse_pcdump", lambda text: [fn])
    monkeypatch.setattr(debugcli, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(debugcli, "find_function", lambda events, function: None)
    monkeypatch.setattr(
        debugcli,
        "_derive_force_phys_from_register_diff_lines",
        lambda *_args, **_kwargs: {
            "targets": [{
                "class_id": 0,
                "ig_idx": 40,
                "target_reg": 31,
                "target_reg_name": "r31",
                "already_target": False,
                "force_vector_runnable": True,
            }],
            "conflicts": [],
        },
    )
    monkeypatch.setattr(
        debugcli,
        "asm_extract_function",
        lambda text, function: SimpleNamespace(instructions=[]),
    )
    monkeypatch.setattr(debugcli, "asm_parse_prologue_end", lambda instructions: 0)
    monkeypatch.setattr(debugcli, "asm_find_first_def", lambda *args, **kwargs: None)

    result = debugcli._collect_order_target_inputs(
        function="f",
        unit="melee/mn/demo",
        class_id=0,
        melee_root=tmp_path,
        checkdiff_timeout=1.0,
        register_only_gate=lambda *_args: {"admitted": True},
    )

    assert result.phys_target == {40: 31}
    assert result.force_iter_first == []
    assert result.forced_class_clean is False


def test_solve_app_registered():
    assert "coloring" in [c.name for c in debugcli.solve_app.registered_commands]
    assert "node-set-split" in [
        c.name for c in debugcli.solve_app.registered_commands
    ]
    assert "solve" in [g.name for g in debugcli.debug_app.registered_groups]


def test_solve_node_set_split_registered_through_root_app():
    result = runner.invoke(cli_app, ["debug", "solve", "node-set-split", "--help"])

    assert result.exit_code == 0, result.output
    assert "Realize a solve-coloring node-set split" in result.output


# --- the live probe adapter factory (codex blocker 3: all four keys derived) ---
def test_live_probe_ctx_factory_derives_all_four_keys():
    class _FD:
        opcode = "li"
    class _SrcConst:
        name = "zero"; expression = None; first_def = _FD()
    class _SrcRuntime:
        name = "row"; expression = None; first_def = None
    class _VA:
        def __init__(self, ig_idx, source):
            self.ig_idx = ig_idx; self.source = source
    class _Report:
        virtuals = (_VA(41, _SrcConst()), _VA(42, _SrcRuntime()), _VA(43, None))

    nodes = {
        41: IGNode(41, {42, 43}, {}, 2, False, 22),
        42: IGNode(42, {41}, {}, 1, False, 21),
        43: IGNode(43, {41}, {}, 1, False, 20),
    }
    ig = IG(class_id=0, select_order=[41, 42, 43], nodes=nodes,
            decision_igs={41, 42, 43})
    from src.search.solver.types import Perturbation, PerturbationKind

    # window_residual True for this target ({41: 21} — 22->21 callee shift).
    fn = debugcli._solver_probe_ctx_factory(ig, _Report(), {41: 21})
    ctx_const = fn(Perturbation(PerturbationKind.NODE_ADD, target_ig=41,
                                use_set=(42,), new_ig=100, position="after",
                                interfere_original=True))
    assert ctx_const.is_runtime_value is False          # li-defined (L2a)
    assert ctx_const.copy_already_survives is True      # window residual (L2c)
    ctx_nosrc = fn(Perturbation(PerturbationKind.NODE_ADD, target_ig=43,
                                use_set=(41,), new_ig=101, position="after",
                                interfere_original=True))
    assert ctx_nosrc.caller_visible_source is False     # source None (L2b)
    ctx_bait = fn(Perturbation(PerturbationKind.NODE_ADD, target_ig=41,
                               use_set=(42, 43), new_ig=102, position="after",
                               interfere_original=True))
    assert ctx_bait.original_keeps_use_past_vprime is False   # all uses (L1)


# --- #705 Task 1: relabel-invariant reassociation-suspect counting ----------
def test_operand_shape_is_relabel_invariant():
    # First-occurrence canonical shape: a pure register relabel compares EQUAL.
    assert debugcli._operand_shape("f26,f26,f0") == (0, 0, 1)
    assert debugcli._operand_shape("f28,f1,f0") == (0, 1, 2)
    # The whole point: dest-aliases-src1 maps to the SAME shape regardless of
    # which physreg the relabel chose.
    assert debugcli._operand_shape("f28,f28,f30") == debugcli._operand_shape(
        "f26,f26,f30") == (0, 0, 1)
    assert debugcli._operand_shape("") == ()
    assert debugcli._operand_shape("  f1 , f1 ") == (0, 0)


def test_fpr_reassociation_suspect_count_flags_operand_structure_change():
    # fmuls f26,f26,f0 (dest aliases src1) vs fmuls f28,f1,f0 (no alias):
    # the intra-instruction aliasing STRUCTURE changed -> reassociation suspect.
    targets = [{
        "class_id": 1,
        "ig_idx": 39,
        "occurrences": [{
            "opcode": "fmuls",
            "operands": "f26,f26,f0",
            "current_asm": "+154: ef 81 00 32 \tfmuls   f28,f1,f0",
        }],
    }]
    assert debugcli._fpr_reassociation_suspect_count(targets) == 1


def test_fpr_reassociation_suspect_count_pure_relabel_is_zero():
    # CONTROL (spec review Finding 2): a clean coloring relabel
    # fadds f28,f28,f30 -> fadds f26,f26,f30 has IDENTICAL operand structure.
    # A raw-string compare would wrongly count this 1; relabel-invariance => 0.
    targets = [{
        "class_id": 1,
        "ig_idx": 37,
        "occurrences": [{
            "opcode": "fadds",
            "operands": "f28,f28,f30",
            "current_asm": "+88: ec 1c f0 2a \tfadds   f26,f26,f30",
        }],
    }]
    assert debugcli._fpr_reassociation_suspect_count(targets) == 0


def test_fpr_reassociation_suspect_count_ignores_non_arith_ops():
    # A load is not a multi-source FP arithmetic op -> never counted, even
    # though the destination register differs.
    targets = [{
        "class_id": 1,
        "ig_idx": 38,
        "occurrences": [{
            "opcode": "lfs",
            "operands": "f0,60(r24)",
            "current_asm": "+200: c0 18 00 3c \tlfs     f30,60(r24)",
        }],
    }]
    assert debugcli._fpr_reassociation_suspect_count(targets) == 0


def test_fpr_reassociation_suspect_count_is_defensive():
    # Missing keys / unparseable current_asm / empty list never raise; they
    # contribute 0.
    assert debugcli._fpr_reassociation_suspect_count([]) == 0
    assert debugcli._fpr_reassociation_suspect_count(None) == 0
    targets = [
        {"occurrences": [{}]},                       # no opcode/operands
        {"occurrences": [{"opcode": "fadds"}]},      # no operands, no asm
        {"occurrences": [{"opcode": "fmuls", "operands": "f1,f2,f3",
                          "current_asm": "<label>"}]},  # unparseable -> "" shape
        {},                                          # no occurrences key
    ]
    # fmuls f1,f2,f3 (shape (0,1,2)) vs "" (shape ()) -> differs -> counts 1;
    # the others contribute 0. Net 1 and no exception.
    assert debugcli._fpr_reassociation_suspect_count(targets) == 1


# --- #705 Task 2: node_set_delta_fallback in _collect_order_target_inputs ----
def _fpr_fallback_repo(monkeypatch, tmp_path, *, targets, conflicts,
                       bl_multiset_equal=True, gate=None):
    """Stub the subprocess/parse seams _collect_order_target_inputs touches so
    the FPR node-set fallback can be exercised without any real build. Models
    test_collect_order_target_inputs_empty_force_vector_window_abstains."""
    source = tmp_path / "src" / "melee" / "mn" / "demo.c"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("void f(void) {}\n", encoding="utf-8")
    asm = tmp_path / "build" / "GALE01" / "asm" / "melee" / "mn" / "demo.s"
    asm.parent.mkdir(parents=True, exist_ok=True)
    asm.write_text("f:\n", encoding="utf-8")
    checkdiff = tmp_path / "tools" / "checkdiff.py"
    checkdiff.parent.mkdir(parents=True, exist_ok=True)
    checkdiff.write_text("# fake\n", encoding="utf-8")

    def fake_run(argv, **kwargs):
        if "debug" in argv and "dump" in argv and "local" in argv:
            output = Path(argv[argv.index("--output") + 1])
            output.write_text("pcdump", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "classification": {"primary": "instruction-sequence"},
                "target_asm": [],
                "current_asm": [],
            }),
            stderr="",
        )

    fn = SimpleNamespace(name="f", last_precolor_pass=lambda: SimpleNamespace())
    monkeypatch.setattr(debugcli.subprocess, "run", fake_run)
    monkeypatch.setattr(debugcli, "_checkdiff_script_path", lambda root: checkdiff)
    monkeypatch.setattr(debugcli, "parse_pcdump", lambda text: [fn])
    monkeypatch.setattr(debugcli, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(debugcli, "find_function", lambda events, function: None)
    monkeypatch.setattr(
        debugcli, "_derive_force_phys_from_register_diff_lines",
        lambda *_a, **_k: {"targets": targets, "conflicts": conflicts})
    monkeypatch.setattr(
        debugcli, "asm_extract_function",
        lambda text, function: SimpleNamespace(instructions=[]))
    monkeypatch.setattr(debugcli, "asm_parse_prologue_end", lambda instructions: 0)
    monkeypatch.setattr(debugcli, "asm_find_first_def", lambda *a, **k: None)

    # Prove the costly force-vector probe is NEVER reached on the fallback.
    def _no_probe(*_a, **_k):
        raise AssertionError("force-vector probe must not run on the fallback")
    monkeypatch.setattr(debugcli, "_run_force_vector_auto_verify", _no_probe)

    if gate is None:
        gate = lambda *_a: {
            "admitted": False,
            "direct_evidence": {
                "check_i_bl_multiset_equal": bl_multiset_equal,
                "nonregister_class_lines": 22,
            },
        }
    return gate


def _fpr_target(ig_idx=39, target_reg=26, *, reassoc=False):
    occ = []
    if reassoc:
        occ = [{
            "opcode": "fmuls",
            "operands": "f26,f26,f0",
            "current_asm": "+154: ef 81 00 32 \tfmuls   f28,f1,f0",
        }]
    return {
        "class_id": 1,
        "ig_idx": ig_idx,
        "target_reg": target_reg,
        "target_reg_name": f"f{target_reg}",
        "already_target": False,
        "force_vector_runnable": True,
        "occurrences": occ,
    }


def test_collect_inputs_fpr_fallback_emits_phys_target_skipping_probe(
    monkeypatch, tmp_path,
):
    gate = _fpr_fallback_repo(
        monkeypatch, tmp_path,
        targets=[_fpr_target(reassoc=True),
                 # an other-class (GPR) target to populate coupled_residual.
                 {"class_id": 0, "ig_idx": 47, "target_reg": 26,
                  "target_reg_name": "r26", "already_target": False,
                  "force_vector_runnable": True}],
        conflicts=[])

    result = debugcli._collect_order_target_inputs(
        function="f", unit="melee/mn/demo", class_id=1,
        melee_root=tmp_path, checkdiff_timeout=1.0,
        register_only_gate=gate, node_set_delta_fallback=True)

    assert result.phys_target == {39: 26}
    assert result.phys_conflicts == []
    # Genuinely not register-only on this path.
    assert result.forced_class_clean is False
    assert result.direct_evidence_register_only is False
    cr = result.coupled_residual
    assert cr is not None
    assert cr["other_class_register_targets"] == 1
    assert cr["other_class_target_regs"] == ["r26"]
    assert cr["nonregister_class_lines"] == 22
    assert cr["reassociation_suspect_targets"] == 1


def test_collect_inputs_gpr_fallback_emits_phys_target_skipping_probe(
    monkeypatch, tmp_path,
):
    # #714: the not-register-only fallback must work for GPR (class 0) too, so
    # mnDiagram_80242C0C-class residuals emit a worksheet instead of a bare
    # abstain. Mirrors the FPR test with a class-0 target.
    gate = _fpr_fallback_repo(
        monkeypatch, tmp_path,
        targets=[{"class_id": 0, "ig_idx": 41, "target_reg": 26,
                  "target_reg_name": "r26", "already_target": False,
                  "force_vector_runnable": True}],
        conflicts=[])

    result = debugcli._collect_order_target_inputs(
        function="f", unit="melee/mn/demo", class_id=0,
        melee_root=tmp_path, checkdiff_timeout=1.0,
        register_only_gate=gate, node_set_delta_fallback=True)

    assert result.phys_target == {41: 26}
    assert result.forced_class_clean is False
    assert result.direct_evidence_register_only is False
    # coupled_residual present; no other-class targets here, structural lines noted.
    assert result.coupled_residual is not None
    assert result.coupled_residual["other_class_register_targets"] == 0
    assert result.coupled_residual["nonregister_class_lines"] == 22


def test_collect_inputs_fpr_fallback_returns_conflicts_with_coupled_residual(
    monkeypatch, tmp_path,
):
    gate = _fpr_fallback_repo(
        monkeypatch, tmp_path,
        targets=[_fpr_target()],
        conflicts=[{"class_id": 1, "ig_idx": 56, "existing_phys": 0,
                    "conflicting_phys": 30}])

    result = debugcli._collect_order_target_inputs(
        function="f", unit="melee/mn/demo", class_id=1,
        melee_root=tmp_path, checkdiff_timeout=1.0,
        register_only_gate=gate, node_set_delta_fallback=True)

    assert result.phys_target == {39: 26}
    assert result.phys_conflicts and result.phys_conflicts[0]["ig_idx"] == 56
    assert result.coupled_residual is not None
    assert result.coupled_residual["other_class_register_targets"] == 0


def test_collect_inputs_fpr_fallback_bl_parity_false_is_inert(
    monkeypatch, tmp_path,
):
    gate = _fpr_fallback_repo(
        monkeypatch, tmp_path, targets=[_fpr_target()], conflicts=[],
        bl_multiset_equal=False)

    result = debugcli._collect_order_target_inputs(
        function="f", unit="melee/mn/demo", class_id=1,
        melee_root=tmp_path, checkdiff_timeout=1.0,
        register_only_gate=gate, node_set_delta_fallback=True)

    assert result.phys_target == {}
    assert result.coupled_residual is None


def test_collect_inputs_fpr_fallback_no_class_target_is_inert(
    monkeypatch, tmp_path,
):
    # bl-parity True but the only diff target is the OTHER class -> no class-1
    # phys_target, no conflicts -> empty phys_target ("nothing to split"). The
    # downstream _derive_node_set_delta_payload returns None on an empty target,
    # so no delta is emitted regardless of any attached coupling summary.
    gate = _fpr_fallback_repo(
        monkeypatch, tmp_path,
        targets=[{"class_id": 0, "ig_idx": 47, "target_reg": 26,
                  "target_reg_name": "r26", "already_target": False,
                  "force_vector_runnable": True}],
        conflicts=[])

    result = debugcli._collect_order_target_inputs(
        function="f", unit="melee/mn/demo", class_id=1,
        melee_root=tmp_path, checkdiff_timeout=1.0,
        register_only_gate=gate, node_set_delta_fallback=True)

    assert result.phys_target == {}
    assert result.phys_conflicts == []


def test_collect_inputs_fallback_with_label_gate_none_no_nameerror(
    monkeypatch, tmp_path,
):
    # review Finding 2: register_only_gate is None + node_set_delta_fallback=True
    # must NOT NameError on gate_verdict; it falls to _inert() (label gate, not
    # admitted because primary is instruction-sequence).
    _fpr_fallback_repo(monkeypatch, tmp_path, targets=[_fpr_target()],
                       conflicts=[])

    result = debugcli._collect_order_target_inputs(
        function="f", unit="melee/mn/demo", class_id=1,
        melee_root=tmp_path, checkdiff_timeout=1.0,
        register_only_gate=None, node_set_delta_fallback=True)

    assert result.phys_target == {}
    assert result.coupled_residual is None


def test_collect_inputs_gpr_not_admitted_fallback_off_is_inert(
    monkeypatch, tmp_path,
):
    # Regression: node_set_delta_fallback defaults False -> unchanged GPR
    # behavior; not-admitted short-circuits to _inert() and the probe never runs.
    gate = _fpr_fallback_repo(
        monkeypatch, tmp_path,
        targets=[{"class_id": 0, "ig_idx": 47, "target_reg": 26,
                  "target_reg_name": "r26", "already_target": False,
                  "force_vector_runnable": True}],
        conflicts=[])

    result = debugcli._collect_order_target_inputs(
        function="f", unit="melee/mn/demo", class_id=0,
        melee_root=tmp_path, checkdiff_timeout=1.0,
        register_only_gate=gate)  # node_set_delta_fallback defaults False

    assert result.phys_target == {}
    assert result.coupled_residual is None


# --- #705 Task 4: _derive_node_set_delta_payload + _run_solve_coloring wiring -
def test_derive_node_set_delta_payload_records_coupled_residual():
    ig = IG(
        class_id=1, select_order=[33],
        nodes={33: IGNode(ig_idx=33, neighbors={39}, precolored={},
                          array_size=2, incomplete=False, observed_reg=31)},
        decision_igs={33})
    cr = {"other_class_register_targets": 1, "other_class_target_regs": ["r26"],
          "nonregister_class_lines": 22, "reassociation_suspect_targets": 1}

    payload = debugcli._derive_node_set_delta_payload(
        function="f", class_id=1, ig=ig, phys_target={33: 28},
        phys_conflicts=[], report=None, coupled_residual=cr)
    assert payload["coupled_residual"] == cr

    # Omitted when not passed (default None) -> key absent.
    payload2 = debugcli._derive_node_set_delta_payload(
        function="f", class_id=1, ig=ig, phys_target={33: 28},
        phys_conflicts=[], report=None)
    assert "coupled_residual" not in payload2


def test_derive_node_set_delta_payload_includes_next_step_recipe_command():
    # #714: solve coloring abstains with the delta but the issue author got
    # stuck because nothing pointed them at the recipe generator (they tried
    # `search directed` -> no_roles). The delta must carry an explicit next-step
    # pointing at `solve node-set-split --node-set-delta` so the two-step flow
    # is discoverable.
    ig = IG(
        class_id=0, select_order=[34],
        nodes={34: IGNode(ig_idx=34, neighbors={44}, precolored={},
                          array_size=2, incomplete=False, observed_reg=24)},
        decision_igs={34})
    payload = debugcli._derive_node_set_delta_payload(
        function="mnDiagram_8023FC28", class_id=0, ig=ig,
        phys_target={34: 27}, phys_conflicts=[], report=None)
    next_step = payload.get("next_step")
    assert next_step and "solve node-set-split" in next_step
    assert "--node-set-delta" in next_step


def test_run_solve_coloring_wires_node_set_fallback_for_gpr_and_fpr(
        monkeypatch, tmp_path):
    # #714: the node-set-delta fallback is enabled for BOTH GPR (class 0) and
    # FPR (class 1) so not-register-only structurally-different-virtual GPR
    # residuals (e.g. mnDiagram_80242C0C) emit a worksheet too. (#705 originally
    # scoped it to class 1 only.)
    seen = {}

    class _Sentinel(Exception):
        pass

    def _capture(**kw):
        seen["node_set_delta_fallback"] = kw.get("node_set_delta_fallback")
        raise _Sentinel()

    monkeypatch.setattr(debugcli, "_collect_order_target_inputs", _capture)
    monkeypatch.setattr(debugcli, "_find_unit_for_function",
                        lambda function, root: "melee/mn/demo")
    monkeypatch.setattr(debugcli, "_resolve_pcdump_path",
                        lambda pcdump, function, root: tmp_path / "x.pcdump")
    (tmp_path / "x.pcdump").write_text("pcdump", encoding="utf-8")
    monkeypatch.setattr(debugcli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debugcli, "_load_checkdiff_normalized_structural_lines",
                        lambda root: (lambda *a, **k: []))

    for class_id, expected in ((1, True), (0, True), (2, False)):
        seen.clear()
        with pytest.raises(_Sentinel):
            debugcli._run_solve_coloring(
                function="f", class_id=class_id, pcdump=None,
                max_perturb=2, frontier=32, kinds=["order"],
                experimental_kinds=[], catalog_dir=tmp_path)
        assert seen["node_set_delta_fallback"] is expected
