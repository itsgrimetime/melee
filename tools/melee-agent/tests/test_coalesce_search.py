"""Tests for coalesce-directed source-shape search ranking."""

from __future__ import annotations

import json
import pathlib
import textwrap
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app
from src.mwcc_debug import cache as pcdump_cache
from src.mwcc_debug.coalesce_search import (
    rank_coalesce_candidates,
    score_coalesce_delta,
)
from src.mwcc_debug.pressure_explorer import (
    compare_pressure_signatures,
    pressure_signature_from_pcdump,
)

runner = CliRunner()


BASELINE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x08 SPILLED
        1 40 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r25 1 1 0x00
          interferers: 40=r26
        1 40 r26 1 1 0x00
          interferers: 37=r25
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-56(r1)
        stmw r25,24(r1)
        blr
""")


COALESCED = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x00
        1 40 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r25 0 0 0x00
          interferers:
        1 40 r25 0 0 0x00
          interferers:
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r26,24(r1)
        blr
""")

FPR_COPY_SURVIVED = textwrap.dedent("""\
    Starting function fn_80000046
    BEFORE REGISTER COLORING
    fn_80000046
    B0: Succ={} Pred={} Labels={}
        fsubs f46,f45,f44
        fmr f56,f46
        fmuls f32,f34,f46
    SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=61)
      iter ig_idx degree arraySize flags notes
        0 56 1 1 0x00
        1 46 1 1 0x00
    COLORGRAPH DECISIONS (class=1, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 56 r0 1 1 0x00
          interferers: 46=r1
        1 46 r1 1 1 0x00
          interferers: 56=r0
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000046
    B0: Succ={} Pred={} Labels={}
        stwu r1,-32(r1)
        blr
""")

FPR_COPY_RELATION_CHANGED = textwrap.dedent("""\
    Starting function fn_80000046
    BEFORE REGISTER COLORING
    fn_80000046
    B0: Succ={} Pred={} Labels={}
        fsubs f46,f45,f44
        fmr f56,f46
        fmuls f32,f34,f46
    SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=61)
      iter ig_idx degree arraySize flags notes
        0 56 1 1 0x00
        1 46 1 1 0x00
    COLORGRAPH DECISIONS (class=1, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 56 r0 0 0 0x00
          interferers:
        1 46 r0 0 0 0x00
          interferers:
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000046
    B0: Succ={} Pred={} Labels={}
        stwu r1,-24(r1)
        blr
""")

GPR_COPY_SURVIVED_37_34 = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        addi r37,r52,28
        mr r34,r37
        addi r34,r34,1
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x00
        1 34 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r26 1 1 0x00
          interferers: 34=r28
        1 34 r28 1 1 0x00
          interferers: 37=r26
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        blr
""")

GPR_COPY_FORCE_PHYS_37_34 = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        addi r37,r52,28
        mr r34,r37
        addi r34,r34,1
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x00
        1 34 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r27 1 1 0x00
          interferers: 34=r25
        1 34 r25 1 1 0x00
          interferers: 37=r27
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        blr
""")

TRANSFORM_ASSIGNMENT_SOURCE = textwrap.dedent("""\
    void fn_80000000(void)
    {
        int x;
        x = 1;
        sink(x);
    }
""")


def _assert_comma_transform_probe(probe: dict) -> None:
    assert probe["operator"] == "transform-corpus:comma_operator_noop_expression_shape"
    assert probe["provenance"]["kind"] == "transform-corpus"
    assert probe["family_id"] == "comma_operator_noop_expression_shape"
    assert probe["mutator_key"] == "wrap_comma_noop_assignment_rhs"
    assert probe["probe_id"] == "comma_operator_noop_expression_shape@0"


def _delta(candidate: str):
    baseline_sig = pressure_signature_from_pcdump(
        BASELINE,
        "fn_80000000",
        pairs=[(37, 40)],
    )
    candidate_sig = pressure_signature_from_pcdump(
        candidate,
        "fn_80000000",
        pairs=[(37, 40)],
    )
    return compare_pressure_signatures(baseline_sig, candidate_sig)


def _trace_occurrence(
    opcode: str,
    operands: str,
    *,
    pass_name: str = "BEFORE REGISTER COLORING",
    instr_idx: int = 0,
) -> dict:
    return {
        "pass_name": pass_name,
        "block_idx": 0,
        "instr_idx": instr_idx,
        "opcode": opcode,
        "operands": operands,
    }


def _fpr_copy_propagation_trace(
    *,
    first_absent_pass: str | None = "AFTER COPY PROPAGATION",
    transform_category: str | None = "copy-propagation/fpr-eliminated",
    from_origin: dict | None = None,
    to_origin: dict | None = None,
) -> dict:
    from_occ = _trace_occurrence("fmadds", "f56,f35,f55,f32", instr_idx=1)
    to_occ = _trace_occurrence("fsubs", "f46,f45,f44", instr_idx=2)
    payload = {
        "function": "fn_80000046",
        "from_virtual": 56,
        "to_virtual": 46,
        "status": "copy-eliminated",
        "first_copy": _trace_occurrence(
            "fmr",
            "f46,f56",
            pass_name="BEFORE GLOBAL OPTIMIZATION",
        ),
        "last_copy": _trace_occurrence(
            "fmr",
            "f46,f56",
            pass_name="AFTER VALUE NUMBERING",
        ),
        "likely_cause": "copy-propagation",
        "first_absent_pass": first_absent_pass,
        "transform_category": transform_category,
        "from_mapping": {
            "virtual": 56,
            "class_id": 1,
            "assigned_reg": 0,
            "ig_idx": 56,
            "first_occurrence": from_occ,
            "last_occurrence": from_occ,
            "call_return_origin": from_origin,
        },
        "to_mapping": {
            "virtual": 46,
            "class_id": 1,
            "assigned_reg": 1,
            "ig_idx": 46,
            "first_occurrence": to_occ,
            "last_occurrence": to_occ,
            "call_return_origin": to_origin,
        },
    }
    if first_absent_pass is None:
        payload.pop("first_absent_pass")
    if transform_category is None:
        payload.pop("transform_category")
    return payload


def _mapped_origin(expression: str, line: int) -> dict:
    return {
        "call_symbol": "source_expr",
        "call_site": _trace_occurrence("bl", "source_expr"),
        "copy_chain": [],
        "source_file": "src/melee/mn/mndiagram.c",
        "source_line": line,
        "source_col": 12,
        "expression": expression,
    }


def test_coalesce_score_prioritizes_target_relationship_before_match_percent() -> None:
    coalesced = score_coalesce_delta(
        _delta(COALESCED),
        target_pairs=[(37, 40)],
        match_percent=12.0,
    )
    unchanged = score_coalesce_delta(
        _delta(BASELINE),
        target_pairs=[(37, 40)],
        match_percent=99.0,
    )

    ranked = rank_coalesce_candidates([
        {
            "label": "high-match-wrong-reason",
            "status": "ok",
            "objective": unchanged.to_dict(),
        },
        {
            "label": "coalesce-right-pair",
            "status": "ok",
            "objective": coalesced.to_dict(),
        },
    ])

    assert ranked[0]["label"] == "coalesce-right-pair"
    assert ranked[0]["objective"]["target_coalesced"] is True
    assert ranked[0]["objective"]["interference_removed"] is True


def test_coalesce_search_cli_ranks_candidate_pcdumps_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    coalesced = tmp_path / "coalesced.txt"
    baseline.write_text(BASELINE)
    unchanged.write_text(BASELINE)
    coalesced.write_text(COALESCED)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"high-match-wrong-reason:noop={unchanged}",
            "--candidate",
            f"coalesce-right-pair:temp-introduction={coalesced}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["target_pairs"] == [[37, 40]]
    assert payload["ranking"] == "target coalesce objective, final match percent tiebreaker"
    assert payload["variants"][0]["label"] == "coalesce-right-pair"
    assert payload["variants"][0]["objective"]["target_spill_removed"] == [37]
    assert payload["variants"][1]["label"] == "high-match-wrong-reason"


def test_coalesce_search_trace_copy_json_derives_fpr_target_and_blocker(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    unchanged.write_text(FPR_COPY_SURVIVED)
    trace_copy.write_text(json.dumps({
        "function": "fn_80000046",
        "from_virtual": 56,
        "to_virtual": 46,
        "status": "copy-survived",
        "likely_cause": "copy-survived-distinct-phys",
        "transform_category": "copy-survived/distinct-phys",
        "from_mapping": {
            "class_id": 1,
            "assigned_reg": 0,
            "ig_idx": 56,
        },
        "to_mapping": {
            "class_id": 1,
            "assigned_reg": 1,
            "ig_idx": 46,
        },
    }))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--candidate",
            f"unchanged:manual={unchanged}",
            "--no-compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["target_source"] == "trace-copy-json"
    assert payload["target_pairs"] == [[56, 46]]
    assert payload["register_class"] == "fpr"
    assert payload["baseline"]["target_pairs"][0]["colorgraph_interference"] is True
    assert payload["baseline"]["target_pairs"][0]["same_assigned_reg"] is False
    repair = payload["copy_survived_repair"]
    assert repair["status"] == "terminal-blocker"
    assert repair["register_class"] == "fpr"
    assert repair["from_virtual"] == 56
    assert repair["to_virtual"] == 46
    assert repair["from_assigned_reg"] == 0
    assert repair["to_assigned_reg"] == 1
    assert "copy-survived" in repair["terminal_blocker"]


def test_coalesce_search_trace_copy_text_renders_fpr_targets(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    unchanged.write_text(FPR_COPY_SURVIVED)
    trace_copy.write_text(json.dumps({
        "function": "fn_80000046",
        "from_virtual": 56,
        "to_virtual": 46,
        "status": "copy-survived",
        "from_mapping": {"class_id": 1, "assigned_reg": 0},
        "to_mapping": {"class_id": 1, "assigned_reg": 1},
    }))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--candidate",
            f"unchanged:manual={unchanged}",
            "--no-compile-probes",
            "--no-score-match-percent",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "target: f56/f46" in result.stdout
    assert "f46/f56:" in result.stdout
    assert "r56/r46:" not in result.stdout


def test_coalesce_search_trace_copy_after_copy_propagation_reports_unmapped_fpr_blocker(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    unchanged.write_text(FPR_COPY_SURVIVED)
    trace_copy.write_text(json.dumps(_fpr_copy_propagation_trace()))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--candidate",
            f"unchanged:manual={unchanged}",
            "--no-compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    repair = payload["copy_propagation_repair"]
    assert repair["status"] == "terminal-blocker"
    assert repair["first_absent_pass"] == "AFTER COPY PROPAGATION"
    assert repair["first_copy"]["pass_name"] == "BEFORE GLOBAL OPTIMIZATION"
    assert repair["last_copy"]["pass_name"] == "AFTER VALUE NUMBERING"
    assert repair["register_class"] == "fpr"
    assert repair["class_id"] == 1
    assert repair["target_pair"] == "f56/f46"
    operands = repair["source_operands"]
    assert operands["from"]["virtual"] == 56
    assert operands["from"]["token"] == "f56"
    assert operands["from"]["expression"] == "fmadds f56,f35,f55,f32"
    assert operands["from"]["mapped_to_source"] is False
    assert operands["from"]["first_occurrence"]["opcode"] == "fmadds"
    assert operands["to"]["virtual"] == 46
    assert operands["to"]["token"] == "f46"
    assert operands["to"]["expression"] == "fsubs f46,f45,f44"
    assert operands["to"]["mapped_to_source"] is False
    assert operands["to"]["first_occurrence"]["opcode"] == "fsubs"
    assert [entry["token"] for entry in repair["unmapped_operands"]] == [
        "f56",
        "f46",
    ]
    blocker = repair["terminal_blocker"]
    for expected in ("f56", "f46", "fmadds", "fsubs"):
        assert expected in blocker


def test_coalesce_search_trace_copy_infers_fpr_from_occurrences_without_class_id(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    unchanged.write_text(FPR_COPY_SURVIVED)
    payload = _fpr_copy_propagation_trace()
    payload["from_mapping"].pop("class_id")
    payload["to_mapping"]["class_id"] = None
    trace_copy.write_text(json.dumps(payload))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--candidate",
            f"unchanged:manual={unchanged}",
            "--no-compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["register_class"] == "fpr"
    assert payload["trace_copy"]["register_class"] == "fpr"
    assert payload["trace_copy"]["class_id"] == 1
    repair = payload["copy_propagation_repair"]
    assert repair["register_class"] == "fpr"
    assert repair["class_id"] == 1
    assert repair["target_pair"] == "f56/f46"
    assert repair["source_operands"]["from"]["token"] == "f56"
    assert repair["source_operands"]["to"]["token"] == "f46"


def test_coalesce_search_trace_copy_infers_fpr_from_top_level_copy_without_class_id(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    unchanged.write_text(FPR_COPY_SURVIVED)
    payload = _fpr_copy_propagation_trace()
    for mapping_key in ("from_mapping", "to_mapping"):
        payload[mapping_key].pop("class_id")
        payload[mapping_key].pop("first_occurrence")
        payload[mapping_key].pop("last_occurrence")
    trace_copy.write_text(json.dumps(payload))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--candidate",
            f"unchanged:manual={unchanged}",
            "--no-compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["register_class"] == "fpr"
    assert payload["copy_propagation_repair"]["target_pair"] == "f56/f46"


def test_coalesce_search_trace_copy_prefers_fpr_mapping_occurrences_over_gpr_pseudo_copy(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    unchanged.write_text(FPR_COPY_SURVIVED)
    payload = _fpr_copy_propagation_trace()
    payload["first_copy"]["opcode"] = "mr"
    payload["first_copy"]["operands"] = "r46,r56"
    payload["last_copy"]["opcode"] = "mr"
    payload["last_copy"]["operands"] = "r46,r56"
    payload["from_mapping"].pop("class_id")
    payload["to_mapping"].pop("class_id")
    trace_copy.write_text(json.dumps(payload))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--candidate",
            f"unchanged:manual={unchanged}",
            "--no-compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["register_class"] == "fpr"
    assert payload["copy_propagation_repair"]["target_pair"] == "f56/f46"


def test_coalesce_search_trace_copy_rejects_register_class_operand_conflict(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    payload = _fpr_copy_propagation_trace()
    payload["register_class"] = "gpr"
    payload["from_mapping"].pop("class_id")
    payload["to_mapping"]["class_id"] = None
    trace_copy.write_text(json.dumps(payload))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "trace-copy JSON register_class conflicts" in result.stderr


def test_coalesce_search_trace_copy_after_copy_propagation_reports_scored_source_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    baseline = tmp_path / "baseline.txt"
    source_candidate = tmp_path / "candidate.c"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    source_candidate.write_text("void fn_80000046(void) {}\n")
    trace_copy.write_text(json.dumps(_fpr_copy_propagation_trace()))
    monkeypatch.setattr(
        diff_capture,
        "compile_source_variant",
        lambda *args, **kwargs: FPR_COPY_RELATION_CHANGED,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--candidate",
            f"source-fix:repair={source_candidate}",
            "--no-compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["copy_survived_repair"]["status"] == "source-actionable"
    repair = payload["copy_propagation_repair"]
    assert repair["status"] == "source-actionable"
    best = repair["best_source_candidate"]
    assert best["label"] == "source-fix"
    assert best["operator"] == "repair"
    assert best["path"] == str(source_candidate)
    assert best["source_retained"] == str(source_candidate)
    assert best["objective"]["target_coalesced"] is True
    assert best["objective"]["interference_removed"] is True
    assert best["objective"]["frame_delta"] == -8
    assert best["objective"]["target_pairs"][0]["after_same_assigned_reg"] is True


def test_coalesce_search_trace_copy_generated_probe_retains_source_pcdump_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text(textwrap.dedent("""\
        typedef unsigned char u8;
        void fn_80000000(u8* dst)
        {
            int i;
            u8 temp;
            for (i = 0; i < 4; i++) {
                temp = 7;
                dst[i] = temp;
            }
        }
    """), encoding="utf-8")
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample", "functions": [{"name": "fn_80000000"}]},
        ],
    }), encoding="utf-8")

    baseline = tmp_path / "baseline.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(BASELINE)
    trace_copy.write_text(json.dumps({
        "function": "fn_80000000",
        "from_virtual": 37,
        "to_virtual": 40,
        "status": "copy-survived",
        "likely_cause": "copy-survived-distinct-phys",
        "transform_category": "copy-survived/distinct-phys",
        "from_mapping": {
            "class_id": 0,
            "assigned_reg": 25,
            "ig_idx": 34,
        },
        "to_mapping": {
            "class_id": 0,
            "assigned_reg": 0,
            "ig_idx": 44,
        },
    }))

    def fake_compile(*_args, **kwargs):
        label = kwargs["diff_input"].label
        return COALESCED if label == "pointer-walk-loop-induction-0" else BASELINE

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--max-probes",
            "8",
            "--no-score-match-percent",
            "--transform-force-phys",
            "34:27,44:25",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    repair = payload["copy_survived_repair"]
    assert repair["status"] == "source-actionable"
    best = repair["best_variant"]
    assert best["label"] == "pointer-walk-loop-induction-0"
    retained_source = pathlib.Path(best["source_retained"])
    retained_pcdump = pathlib.Path(best["pcdump_path"])
    assert retained_source.exists()
    assert retained_pcdump.exists()
    cache_root = melee_root / "build" / "mwcc_debug_cache" / "probes" / "coalesce_search"
    assert retained_source.is_relative_to(cache_root)
    assert retained_pcdump.is_relative_to(cache_root)
    assert "melee_coalesce_search_" not in best["source_retained"]
    assert best["path"] == best["source_retained"]
    assert best["original_path"] != best["path"]
    assert retained_pcdump.read_text(encoding="utf-8") == COALESCED
    assert best["objective"]["source_path"] == best["source_retained"]
    assert best["objective"]["pcdump_path"] == best["pcdump_path"]
    assert best["provenance"]["kind"] == "pointer-walk-loop"
    assert best["provenance"]["base"] == "dst"
    assert best["provenance"]["counter"] == "i"
    assert best["continuation"]["generated_local"] == "ll_probe_iter_0"
    assert best["continuation"]["generated_local_source"]["name"] == "ll_probe_iter_0"
    assert best["continuation"]["generated_local_source"]["initializer"] == "dst"
    route_kinds = {route["kind"] for route in best["continuation"]["routes"]}
    assert "score-retained-source" in route_kinds
    assert "node-set-split-generated-local" in route_kinds
    assert "node-set-split-pointer-base" in route_kinds
    assert "node-set-split-loop-counter" in route_kinds
    assert any("--var ll_probe_iter_0" in route["command"] for route in best["continuation"]["routes"])
    generated_route = next(
        route for route in best["continuation"]["routes"]
        if route["kind"] == "node-set-split-generated-local"
    )
    assert "--force-phys 34:27,44:25" in generated_route["command"]
    assert "--generated-local-source-json" in generated_route["command"]
    assert generated_route["force_phys"] == "34:27,44:25"
    assert generated_route["generated_local_source"]["name"] == "ll_probe_iter_0"
    assert generated_route["generated_local_source"]["initializer"] == "dst"
    assert any("--var dst" in route["command"] for route in best["continuation"]["routes"])
    assert any("--var i" in route["command"] for route in best["continuation"]["routes"])


def test_coalesce_search_trace_copy_local_pointer_reset_probes_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(GPR_COPY_SURVIVED_37_34)
    source.write_text(textwrap.dedent("""\
        typedef unsigned char u8;
        extern struct Demo {
            u8 sorted_names[0x78];
        } mnDiagram_804A076C;
        void fn_80000000(void)
        {
            int n;
            u8* tp;
            u8* dst_iter;
            u8* dst = mnDiagram_804A076C.sorted_names;
            dst_iter = dst;
            tp = dst;
            for (n = 0; n < 0x78; n++, dst_iter++, tp++) {
                *dst_iter = (u8) n;
            }
        }
    """), encoding="utf-8")
    trace_copy.write_text(json.dumps({
        "function": "fn_80000000",
        "from_virtual": 37,
        "to_virtual": 34,
        "status": "copy-survived",
        "likely_cause": "copy-survived-distinct-phys",
        "transform_category": "copy-survived/distinct-phys",
        "from_mapping": {
            "class_id": 0,
            "assigned_reg": 26,
            "ig_idx": 37,
            "source_local": "dst",
            "source_type": "u8*",
        },
        "to_mapping": {
            "class_id": 0,
            "assigned_reg": 28,
            "ig_idx": 34,
            "source_local": "dst_iter",
            "source_type": "u8*",
        },
    }))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--max-probes",
            "4",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    probes = [
        probe for probe in payload["probes"]
        if probe["operator"] == "copy-survived-pointer-reset"
    ]
    assert {probe["provenance"]["variant"] for probe in probes} >= {
        "direct-base",
        "fresh-alias",
        "for-init",
    }
    assert all(probe["provenance"]["from_local"] == "dst" for probe in probes)
    assert all(probe["provenance"]["to_local"] == "dst_iter" for probe in probes)
    assert any(
        "mnDiagram_804A076C.sorted_names" in probe["provenance"]["source_hunk"]["replacement"]
        for probe in probes
    )
    assert any(
        "ll_probe_iter_0 = dst" in probe["provenance"]["source_hunk"]["replacement"]
        for probe in probes
    )


def test_coalesce_search_trace_copy_call_return_use_shape_probes_are_retained(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text(textwrap.dedent("""\
        typedef unsigned char u8;
        char* GetNameText(u8 value);
        void fn_80000000(void)
        {
            u8 post_ceiling_j_name;
            char* post_ceiling_j_text;
            char* post_ceiling_j_text_copy;
            post_ceiling_j_text = GetNameText(post_ceiling_j_name);
            post_ceiling_j_text_copy = post_ceiling_j_text;
            if ((post_ceiling_j_text_copy != 0) &&
                (post_ceiling_j_text_copy != 0)) {
                sink();
            }
        }
    """), encoding="utf-8")

    baseline = tmp_path / "baseline.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(GPR_COPY_SURVIVED_37_34)
    origin = {
        "source_file": str(source),
        "source_line": 8,
        "expression": "GetNameText(post_ceiling_j_name)",
        "assigned_local": "post_ceiling_j_text",
    }
    trace_copy.write_text(json.dumps({
        "function": "fn_80000000",
        "from_virtual": 37,
        "to_virtual": 34,
        "status": "copy-survived",
        "likely_cause": "copy-survived-distinct-phys",
        "first_absent_pass": "AFTER COPY PROPAGATION",
        "transform_category": "copy-survived/distinct-phys",
        "from_mapping": {
            "class_id": 0,
            "assigned_reg": 26,
            "ig_idx": 37,
            "call_return_origin": origin,
        },
        "to_mapping": {
            "class_id": 0,
            "assigned_reg": 28,
            "ig_idx": 34,
            "call_return_origin": origin,
        },
    }))

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        diff_capture,
        "compile_source_variant",
        lambda *_args, **_kwargs: GPR_COPY_SURVIVED_37_34,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--max-probes",
            "5",
            "--no-score-match-percent",
            "--transform-force-phys",
            "37:27,34:25",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["trace_copy"]["source_operands"]["from"]["source_local"] == (
        "post_ceiling_j_text"
    )
    probes = [
        probe for probe in payload["probes"]
        if probe["operator"] == "call-return-use-shape"
    ]
    assert {probe["provenance"]["variant"] for probe in probes} >= {
        "direct-use",
        "duplicate-call",
        "declaration-initializer",
    }
    variants = [
        variant for variant in payload["variants"]
        if variant["operator"] == "call-return-use-shape"
        and variant["status"] == "ok"
    ]
    assert variants
    cache_root = melee_root / "build" / "mwcc_debug_cache" / "probes" / "coalesce_search"
    for variant in variants:
        retained_source = pathlib.Path(variant["source_retained"])
        retained_pcdump = pathlib.Path(variant["pcdump_path"])
        assert retained_source.exists()
        assert retained_pcdump.exists()
        assert retained_source.is_relative_to(cache_root)
        assert retained_pcdump.is_relative_to(cache_root)
        assert "melee_coalesce_search_" not in variant["path"]
        assert variant["source_retention_reason"] == "source_shape_scored"

    repair = payload["copy_propagation_repair"]
    assert repair["status"] == "terminal-blocker"
    assert repair["retained_source_shape_candidates"]
    terminal = repair["terminal_summary"]
    assert terminal["kind"] == "call-return-use-shape-no-progress"
    assert terminal["retained_candidate_count"] == len(variants)
    assert terminal["source_expression"] == "GetNameText(post_ceiling_j_name)"
    assert terminal["assigned_local"] == "post_ceiling_j_text"


def test_coalesce_search_trace_copy_call_return_failed_probe_retains_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text(textwrap.dedent("""\
        typedef unsigned char u8;
        char* GetNameText(u8 value);
        void fn_80000000(void)
        {
            u8 post_ceiling_j_name;
            char* post_ceiling_j_text;
            char* post_ceiling_j_text_copy;
            post_ceiling_j_text = GetNameText(post_ceiling_j_name);
            post_ceiling_j_text_copy = post_ceiling_j_text;
            if ((post_ceiling_j_text_copy != 0) &&
                (post_ceiling_j_text_copy != 0)) {
                sink();
            }
        }
    """), encoding="utf-8")

    baseline = tmp_path / "baseline.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(GPR_COPY_SURVIVED_37_34)
    origin = {
        "source_file": str(source),
        "source_line": 8,
        "expression": "GetNameText(post_ceiling_j_name)",
        "assigned_local": "post_ceiling_j_text",
    }
    trace_copy.write_text(json.dumps({
        "function": "fn_80000000",
        "from_virtual": 37,
        "to_virtual": 34,
        "status": "copy-survived",
        "likely_cause": "copy-survived-distinct-phys",
        "first_absent_pass": "AFTER COPY PROPAGATION",
        "from_mapping": {
            "class_id": 0,
            "assigned_reg": 26,
            "ig_idx": 37,
            "call_return_origin": origin,
        },
        "to_mapping": {
            "class_id": 0,
            "assigned_reg": 28,
            "ig_idx": 34,
            "call_return_origin": origin,
        },
    }))

    def fail_compile(*_args, **_kwargs):
        raise RuntimeError("invalid C89")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(diff_capture, "compile_source_variant", fail_compile)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--max-probes",
            "2",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    failed = [
        variant for variant in payload["variants"]
        if variant["operator"] == "call-return-use-shape"
        and variant["status"] == "failed"
    ]
    assert failed
    cache_root = melee_root / "build" / "mwcc_debug_cache" / "probes" / "coalesce_search"
    for variant in failed:
        retained_source = pathlib.Path(variant["source_retained"])
        assert retained_source.exists()
        assert retained_source.is_relative_to(cache_root)
        assert "melee_coalesce_search_" not in variant["path"]
        assert variant["source_retention_reason"] == "source_shape_failed"
        assert variant["original_path"] != variant["path"]


def test_coalesce_search_retained_full_tu_probes_compile_through_unit_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture
    import src.mwcc_debug.pressure_explorer as pressure_explorer

    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    live_source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    retained_source = tmp_path / "retained.c"
    retained_source.write_text(
        "void helper(void) {}\nvoid fn_80000000(void) { helper(); }\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE, encoding="utf-8")

    compile_paths: list[pathlib.Path] = []
    compile_unit_sources: list[pathlib.Path | None] = []
    match_full_unit_flags: list[bool] = []

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        pressure_explorer,
        "generate_lifetime_layout_probes",
        lambda *args, **kwargs: [
            pressure_explorer.LifetimeLayoutProbe(
                label="retained-full-tu-0",
                operator="decl-order",
                description="retained full TU probe",
                source_text=retained_source.read_text(encoding="utf-8"),
            )
        ],
    )

    def fake_compile(diff_input, **kwargs):
        compile_paths.append(diff_input.path)
        compile_unit_sources.append(kwargs.get("unit_source"))
        return COALESCED

    def fake_match_percent(*args, **kwargs):
        match_full_unit_flags.append(kwargs.get("full_unit_source", False))
        return 99.0, None

    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(retained_source),
            "--max-probes",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert compile_unit_sources == [live_source]
    assert compile_paths
    assert compile_paths[0].is_relative_to(
        melee_root / "build" / "mwcc_debug_cache" / "probes" / "coalesce_search"
    )
    assert match_full_unit_flags == [True]
    variant = payload["variants"][0]
    assert variant["status"] == "ok"
    assert pathlib.Path(variant["source_retained"]).is_relative_to(melee_root)
    assert pathlib.Path(variant["pcdump_path"]).is_relative_to(melee_root)


def test_coalesce_search_inside_repo_retained_source_uses_stable_full_tu_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture
    import src.mwcc_debug.pressure_explorer as pressure_explorer
    from src.mwcc_debug.diff_capture import CompileFailure

    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    live_source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    retained_source = (
        melee_root
        / "build"
        / "diagnostics"
        / "sort"
        / "scored"
        / "probes"
        / "retained.c"
    )
    retained_source.parent.mkdir(parents=True)
    retained_source.write_text(
        "void helper(void) {}\nvoid fn_80000000(void) { helper(); }\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE, encoding="utf-8")
    attempted_pcdump = tmp_path / "wrong-function.pcdump.txt"
    wrong_function_pcdump = textwrap.dedent("""\
        Starting function fn_80000001
        BEFORE REGISTER COLORING
        fn_80000001
        B0: Succ={} Pred={} Labels={}
            blr
    """)

    compile_unit_sources: list[pathlib.Path | None] = []
    compile_paths: list[pathlib.Path] = []

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        pressure_explorer,
        "generate_lifetime_layout_probes",
        lambda *args, **kwargs: [
            pressure_explorer.LifetimeLayoutProbe(
                label="retained-full-tu-0",
                operator="decl-order",
                description="retained full TU probe",
                source_text=retained_source.read_text(encoding="utf-8"),
            )
        ],
    )

    def fake_compile(diff_input, **kwargs):
        unit_source = kwargs.get("unit_source")
        compile_paths.append(diff_input.path)
        compile_unit_sources.append(unit_source)
        attempted_pcdump.write_text(wrong_function_pcdump, encoding="utf-8")
        command = [
            "melee-agent",
            "debug",
            "dump",
            "local",
            str(diff_input.path),
            "--output",
            str(attempted_pcdump),
            "--function",
            "fn_80000000",
        ]
        if unit_source is not None:
            command.extend(["--unit-source", str(unit_source)])
        raise CompileFailure(
            side=diff_input.label,
            command=command,
            stdout="",
            stderr="function 'fn_80000000' not found in pcdump",
            returncode=3,
        )

    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(retained_source),
            "--max-probes",
            "1",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "terminal-blocked"
    assert payload["terminal_blocker"] == "retained-target-function-missing-from-pcdump"
    assert compile_unit_sources == [live_source]
    variant = payload["variants"][0]
    cache_root = (
        melee_root
        / "build"
        / "mwcc_debug_cache"
        / "probes"
        / "coalesce_search"
        / "fn_80000000"
    )
    retained_path = pathlib.Path(variant["source_retained"])
    retained_pcdump = pathlib.Path(variant["pcdump_path"])
    assert retained_path.exists()
    assert retained_path.is_relative_to(cache_root)
    assert variant["path"] == variant["source_retained"]
    assert len(compile_paths) == 1
    assert compile_paths[0].is_relative_to(cache_root)
    assert "retained_full_unit_probe" in compile_paths[0].parts
    assert compile_paths[0] != live_source
    assert compile_paths[0] != retained_source
    assert "melee_coalesce_search_" in variant["original_path"]
    assert variant["source_retention_reason"] == "terminal_target_missing"
    assert retained_pcdump.exists()
    assert retained_pcdump.is_relative_to(cache_root)
    assert retained_pcdump.read_text(encoding="utf-8") == wrong_function_pcdump
    assert variant["pcdump_attempted_path"] == str(attempted_pcdump)
    assert "--unit-source" in variant["compile_command"]
    unit_source_arg = variant["compile_command"].index("--unit-source") + 1
    assert variant["compile_command"][unit_source_arg] == str(live_source)
    assert variant["compile_command"][unit_source_arg] != str(retained_source)

    terminal = payload["terminal_summary"]
    assert variant["source_retained"] in terminal["source_retained"]
    assert variant["pcdump_path"] in terminal["pcdump_path"]
    assert all(
        "melee_coalesce_search_" not in source
        for source in terminal["source_retained"]
    )


def test_coalesce_search_failed_generated_probe_without_pcdump_reports_attempt_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture
    import src.mwcc_debug.pressure_explorer as pressure_explorer
    from src.mwcc_debug.diff_capture import CompileFailure

    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    live_source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    retained_source = melee_root / "build" / "diagnostics" / "sort" / "retained.c"
    retained_source.parent.mkdir(parents=True)
    retained_source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE, encoding="utf-8")
    missing_pcdump = tmp_path / "missing.pcdump.txt"

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        pressure_explorer,
        "generate_lifetime_layout_probes",
        lambda *args, **kwargs: [
            pressure_explorer.LifetimeLayoutProbe(
                label="missing-output-0",
                operator="decl-order",
                description="missing pcdump probe",
                source_text=retained_source.read_text(encoding="utf-8"),
            )
        ],
    )

    def fake_compile(diff_input, **kwargs):
        raise CompileFailure(
            side=diff_input.label,
            command=[
                "melee-agent",
                "debug",
                "dump",
                "local",
                str(diff_input.path),
                "--output",
                str(missing_pcdump),
                "--function",
                "fn_80000000",
            ],
            stdout="compile stdout",
            stderr="function 'fn_80000000' not found in pcdump",
            returncode=3,
        )

    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(retained_source),
            "--max-probes",
            "1",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variant = payload["variants"][0]
    retained_source_path = pathlib.Path(variant["source_retained"])
    assert retained_source_path.exists()
    assert retained_source_path.is_relative_to(melee_root)
    assert "pcdump_path" not in variant
    assert variant["pcdump_missing"] is True
    assert variant["pcdump_attempted_path"] == str(missing_pcdump)
    assert variant["compile_returncode"] == 3
    assert variant["compile_stdout"] == "compile stdout"
    assert "not found in pcdump" in variant["compile_stderr"]
    assert "--output" in variant["compile_command"]

    terminal = payload["terminal_summary"]
    assert terminal["pcdump_missing_count"] == 1
    assert terminal["pcdump_attempted_path"] == [str(missing_pcdump)]
    assert terminal["compile_failures"][0]["returncode"] == 3
    assert terminal["compile_failures"][0]["label"] == "missing-output-0"


def test_coalesce_search_all_missing_function_failures_emit_terminal_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture
    import src.mwcc_debug.pressure_explorer as pressure_explorer
    from src.mwcc_debug.diff_capture import CompileFailure

    melee_root = tmp_path / "melee"
    live_source = melee_root / "src" / "melee" / "mn" / "sample.c"
    live_source.parent.mkdir(parents=True)
    live_source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    retained_source = tmp_path / "retained.c"
    retained_source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE, encoding="utf-8")
    attempted_pcdump = tmp_path / "all-missing.pcdump.txt"
    wrong_function_pcdump = textwrap.dedent("""\
        Starting function fn_80000001
        BEFORE REGISTER COLORING
        fn_80000001
        B0: Succ={} Pred={} Labels={}
            blr
    """)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        pressure_explorer,
        "generate_lifetime_layout_probes",
        lambda *args, **kwargs: [
            pressure_explorer.LifetimeLayoutProbe(
                label="retained-full-tu-0",
                operator="decl-order",
                description="retained full TU probe",
                source_text=retained_source.read_text(encoding="utf-8"),
            )
        ],
    )

    def fake_compile(diff_input, **kwargs):
        attempted_pcdump.write_text(wrong_function_pcdump, encoding="utf-8")
        raise CompileFailure(
            side=diff_input.label,
            command=[
                "melee-agent",
                "debug",
                "dump",
                "local",
                str(diff_input.path),
                "--output",
                str(attempted_pcdump),
                "--function",
                "fn_80000000",
            ],
            stdout="",
            stderr="function 'fn_80000000' not found in pcdump",
            returncode=3,
        )

    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(retained_source),
            "--max-probes",
            "1",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "terminal-blocked"
    assert payload["terminal_blocker"] == "retained-target-function-missing-from-pcdump"
    assert payload["terminal_summary"]["variant_count"] == 1
    assert "not found in pcdump" in payload["terminal_summary"]["sample_errors"][0]
    terminal = payload["terminal_summary"]
    assert terminal["source_retained"]
    assert terminal["pcdump_path"]
    assert "sample_errors" in terminal
    assert pathlib.Path(terminal["source_retained"][0]).is_relative_to(
        melee_root / "build" / "mwcc_debug_cache" / "probes" / "coalesce_search"
    )
    assert pathlib.Path(terminal["pcdump_path"][0]).is_relative_to(
        melee_root / "build" / "mwcc_debug_cache" / "probes" / "coalesce_search"
    )
    assert "melee_coalesce_search_" not in terminal["source_retained"][0]


def test_coalesce_search_trace_copy_unmapped_pointer_reset_fallback_keeps_later_reset(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(GPR_COPY_SURVIVED_37_34)
    source.write_text(textwrap.dedent("""\
        typedef unsigned char u8;
        extern struct DemoA {
            u8 sorted_fighters[0x19];
        } mnDiagram_804A0750;
        extern struct DemoB {
            u8 sorted_names[0x78];
        } mnDiagram_804A076C;
        void fn_80000000(void)
        {
            int i;
            int n;
            u8* fighter_iter;
            u8* fighter_dst = mnDiagram_804A0750.sorted_fighters;
            u8* dst_iter;
            u8* dst = mnDiagram_804A076C.sorted_names;
            fighter_iter = fighter_dst;
            for (i = 0; i < 0x19; i++, fighter_iter++) {
                *fighter_iter = (u8) i;
            }
            dst_iter = dst;
            for (n = 0; n < 0x78; n++, dst_iter++) {
                *dst_iter = (u8) n;
            }
        }
    """), encoding="utf-8")
    trace_copy.write_text(json.dumps({
        "function": "fn_80000000",
        "from_virtual": 37,
        "to_virtual": 34,
        "status": "copy-survived",
        "likely_cause": "copy-survived-distinct-phys",
        "transform_category": "copy-survived/distinct-phys",
        "from_mapping": {"class_id": 0, "assigned_reg": 26, "ig_idx": 37},
        "to_mapping": {"class_id": 0, "assigned_reg": 28, "ig_idx": 34},
    }))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--max-probes",
            "6",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    reset_probes = [
        probe for probe in payload["probes"]
        if probe["operator"] == "copy-survived-pointer-reset"
    ]
    hunk_replacements = [
        probe["provenance"]["source_hunk"]["replacement"]
        for probe in reset_probes
    ]
    assert any("mnDiagram_804A0750.sorted_fighters" in hunk for hunk in hunk_replacements)
    assert any("mnDiagram_804A076C.sorted_names" in hunk for hunk in hunk_replacements)


def test_coalesce_search_force_phys_exact_candidate_is_source_actionable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    melee_root = tmp_path / "melee"
    (melee_root / "build").mkdir(parents=True)
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(GPR_COPY_SURVIVED_37_34)
    source.write_text(textwrap.dedent("""\
        typedef unsigned char u8;
        extern struct Demo {
            u8 sorted_names[0x78];
        } mnDiagram_804A076C;
        void fn_80000000(void)
        {
            int n;
            u8* dst_iter;
            u8* dst = mnDiagram_804A076C.sorted_names;
            dst_iter = dst;
            for (n = 0; n < 0x78; n++, dst_iter++) {
                *dst_iter = (u8) n;
            }
        }
    """), encoding="utf-8")
    trace_copy.write_text(json.dumps({
        "function": "fn_80000000",
        "from_virtual": 37,
        "to_virtual": 34,
        "status": "copy-survived",
        "likely_cause": "copy-survived-distinct-phys",
        "transform_category": "copy-survived/distinct-phys",
        "from_mapping": {
            "class_id": 0,
            "assigned_reg": 26,
            "ig_idx": 37,
            "source_local": "dst",
            "source_type": "u8*",
        },
        "to_mapping": {
            "class_id": 0,
            "assigned_reg": 28,
            "ig_idx": 34,
            "source_local": "dst_iter",
            "source_type": "u8*",
        },
    }))

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        diff_capture,
        "compile_source_variant",
        lambda *args, **kwargs: GPR_COPY_FORCE_PHYS_37_34,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--max-probes",
            "4",
            "--no-score-match-percent",
            "--transform-force-phys",
            "37:27,34:25",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    repair = json.loads(result.stdout)["copy_survived_repair"]
    assert repair["status"] == "source-actionable"
    best = repair["best_variant"]
    assert best["operator"] == "copy-survived-pointer-reset"
    assert best["pcdump_path"]
    assert best["source_hunk"]
    assert best["objective"]["force_phys_satisfied"] is True
    assert best["objective"]["force_phys_assignments"]["37"]["after"] == 27
    assert best["objective"]["force_phys_assignments"]["34"]["after"] == 25


def test_coalesce_search_manual_source_candidate_keeps_existing_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    melee_root = tmp_path / "melee"
    (melee_root / "build").mkdir(parents=True)
    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.c"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(BASELINE)
    candidate.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    trace_copy.write_text(json.dumps({
        "function": "fn_80000000",
        "from_virtual": 37,
        "to_virtual": 40,
        "status": "copy-survived",
        "from_mapping": {"class_id": 0, "assigned_reg": 25, "ig_idx": 34},
        "to_mapping": {"class_id": 0, "assigned_reg": 26, "ig_idx": 40},
    }))

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        diff_capture,
        "compile_source_variant",
        lambda *args, **kwargs: COALESCED,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--candidate",
            f"manual-source:repair={candidate}",
            "--no-compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    best = json.loads(result.stdout)["copy_survived_repair"]["best_variant"]
    assert best["path"] == str(candidate)
    assert best["source_retained"] == str(candidate)
    assert "original_path" not in best
    if "pcdump_path" in best:
        assert pathlib.Path(best["pcdump_path"]).exists()


def test_coalesce_search_source_actionable_summary_includes_pcdump_path() -> None:
    summary = debug_cli._copy_repair_candidate_summary({
        "rank": 1,
        "label": "source-fix",
        "operator": "repair",
        "path": "/tmp/source-fix.c",
        "source_retained": "/tmp/source-fix.c",
        "pcdump_path": "/tmp/source-fix.pcdump.txt",
        "objective": {"target_coalesced": True},
    })

    assert summary["pcdump_path"] == "/tmp/source-fix.pcdump.txt"


def test_coalesce_search_trace_copy_source_mapped_operands_without_scored_source_candidate_stay_blocked(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    trace_copy.write_text(json.dumps(_fpr_copy_propagation_trace(
        from_origin=_mapped_origin("left_expr", 120),
        to_origin=_mapped_origin("right_expr", 121),
    )))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    repair = json.loads(result.stdout)["copy_propagation_repair"]
    assert repair["status"] == "terminal-blocker"
    assert "best_source_candidate" not in repair
    assert repair["source_operands"]["from"]["mapped_to_source"] is True
    assert repair["source_operands"]["to"]["mapped_to_source"] is True
    assert repair["ranked_source_repairs"]


def test_coalesce_search_trace_copy_raw_pcdump_candidate_is_not_source_actionable(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    coalesced = tmp_path / "coalesced.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    coalesced.write_text(FPR_COPY_RELATION_CHANGED)
    trace_copy.write_text(json.dumps(_fpr_copy_propagation_trace()))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--candidate",
            f"raw-pcdump:manual={coalesced}",
            "--no-compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["variants"][0]["objective"]["target_coalesced"] is True
    assert payload["copy_survived_repair"]["status"] != "source-actionable"
    repair = payload["copy_propagation_repair"]
    assert repair["status"] == "terminal-blocker"
    assert "best_source_candidate" not in repair


def test_coalesce_search_trace_copy_mixed_mapped_operand_names_unmapped_side(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    trace_copy.write_text(json.dumps(_fpr_copy_propagation_trace(
        from_origin=_mapped_origin("left_expr", 120),
    )))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    repair = json.loads(result.stdout)["copy_propagation_repair"]
    assert repair["status"] == "terminal-blocker"
    assert [entry["token"] for entry in repair["unmapped_operands"]] == ["f46"]
    assert "f46=fsubs f46,f45,f44" in repair["terminal_blocker"]
    assert "f56=" not in repair["terminal_blocker"]


def test_coalesce_search_trace_copy_non_copy_propagation_is_not_applicable(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    payload = _fpr_copy_propagation_trace(
        first_absent_pass="AFTER DEAD CODE ELIMINATION",
        transform_category="value-numbering",
    )
    payload["likely_cause"] = "copy-survived-distinct-phys"
    trace_copy.write_text(json.dumps(payload))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    repair = json.loads(result.stdout)["copy_propagation_repair"]
    assert repair["status"] == "not-applicable"


def test_coalesce_search_trace_copy_transform_category_copy_propagation_applies_without_first_absent(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    trace_copy.write_text(json.dumps(_fpr_copy_propagation_trace(
        first_absent_pass=None,
        transform_category="copy-propagation/fpr-eliminated",
    )))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    repair = json.loads(result.stdout)["copy_propagation_repair"]
    assert repair["status"] == "terminal-blocker"
    assert repair["target_pair"] == "f56/f46"


def test_coalesce_search_trace_copy_text_renders_copy_propagation_blocker(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    trace_copy = tmp_path / "trace-copy.json"
    baseline.write_text(FPR_COPY_SURVIVED)
    trace_copy.write_text(json.dumps(_fpr_copy_propagation_trace()))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000046",
            "--trace-copy-json",
            str(trace_copy),
            "--pcdump",
            str(baseline),
            "--no-compile-probes",
            "--no-score-match-percent",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "copy-propagation repair: terminal-blocker for f56/f46" in result.stdout
    assert "f56=fmadds f56,f35,f55,f32" in result.stdout
    assert "f46=fsubs f46,f45,f44" in result.stdout


def test_coalesce_search_requires_fresh_cached_pcdump_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(pcdump, function, melee_root=None, *, require_fresh=False):
        assert require_fresh is True
        raise typer.Exit(4)

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", fake_resolve)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 4


def test_coalesce_search_missing_function_in_pcdump_exits_cleanly(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE.replace("fn_80000000", "other_fn"))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
        ],
    )

    assert result.exit_code == 3
    assert "function 'fn_80000000' not found in pcdump" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_coalesce_search_allow_stale_pcdump_opt_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    coalesced = tmp_path / "coalesced.txt"
    baseline.write_text(BASELINE)
    coalesced.write_text(COALESCED)

    def fake_resolve(pcdump, function, melee_root=None, *, require_fresh=False):
        assert require_fresh is False
        return baseline

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", fake_resolve)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--allow-stale-pcdump",
            "--candidate",
            f"coalesce-right-pair:temp-introduction={coalesced}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr


def test_coalesce_search_scores_source_candidate_match_percent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.c"
    baseline.write_text(BASELINE)
    candidate.write_text("void fn_80000000(void) {}\n")

    monkeypatch.setattr(
        diff_capture,
        "compile_source_variant",
        lambda *args, **kwargs: COALESCED,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_match_percent",
        lambda *args, **kwargs: (88.25, None),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"source-score:temp-introduction={candidate}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["variants"][0]["objective"]["match_percent"] == 88.25


def test_coalesce_search_split_var_generates_anti_coalesce_probes_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    source = tmp_path / "demo.c"
    source.write_text(textwrap.dedent("""\
        void fn_80000000(HSD_JObj* jobj)
        {
            Prep(jobj);
            HSD_JObjSetTranslateX(jobj, 1.0f);
            HSD_JObjSetMtxDirtySub(jobj);
        }
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--split-var",
            "jobj",
            "--max-probes",
            "2",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    anti = [
        probe for probe in payload["probes"]
        if probe["operator"] == "anti-coalesce-volatile-copy"
    ]
    assert anti
    assert anti[0]["provenance"]["var"] == "jobj"


def test_coalesce_search_opt_in_lists_transform_corpus_probe_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(BASELINE)
    source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--no-compile-probes",
            "--include-transform-corpus",
            "--transform-family",
            "comma_operator_noop_expression_shape",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    probe = next(
        probe for probe in payload["probes"]
        if probe["operator"] == "transform-corpus:comma_operator_noop_expression_shape"
    )
    _assert_comma_transform_probe(probe)


def test_coalesce_search_default_excludes_transform_corpus_probe_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(BASELINE)
    source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert not any(
        probe["operator"].startswith("transform-corpus:")
        for probe in payload["probes"]
    )


def test_coalesce_search_non_json_emits_real_score_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.c"
    baseline.write_text(BASELINE)
    candidate.write_text("void fn_80000000(void) {}\n")

    monkeypatch.setattr(
        diff_capture,
        "compile_source_variant",
        lambda *args, **kwargs: COALESCED,
    )

    def fake_match_percent(*args, status=None, **kwargs):
        assert status is not None
        status("build complete; refreshing report.json")
        return 88.25, None

    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"source-score:temp-introduction={candidate}",
            "--no-compile-probes",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (
        "[coalesce-search] source-score: build complete; refreshing report.json"
        in result.stderr
    )


def test_real_tree_source_score_restores_source_and_preserves_legacy_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    melee_root = tmp_path
    unit = "melee/mn/demo"
    source_path = melee_root / "src" / f"{unit}.c"
    source_path.parent.mkdir(parents=True)
    original = textwrap.dedent("""\
        int untouched(void) { return 7; }

        void fn_80000000(void) {
            int digit_count = 0;
            (void) digit_count;
        }
    """)
    source_path.write_text(original)
    report_path = melee_root / "build" / "GALE01" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({
        "units": [
            {
                "name": unit,
                "functions": [{"name": "fn_80000000"}],
            }
        ],
    }))

    cache_path = pcdump_cache.cache_path(melee_root, unit)
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(BASELINE)
    assert pcdump_cache.lookup(melee_root, unit).fresh is True
    assert not pcdump_cache.hash_path(cache_path).exists()

    candidate = tmp_path / "candidate.c"
    candidate.write_text(textwrap.dedent("""\
        void fn_80000000(void) {
            int digit_count = 0;
            digit_count += 1;
            (void) digit_count;
        }
    """))

    monkeypatch.setattr(
        debug_cli,
        "_run_ninja_with_no_diag_retry",
        lambda *args, **kwargs: (
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            False,
        ),
    )

    def stale_refresh(*args, **kwargs):
        raise typer.Exit(4)

    monkeypatch.setattr(
        debug_cli,
        "_refresh_match_pct_after_successful_build",
        stale_refresh,
    )
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_command_with_optional_timeout",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(typer.Exit) as excinfo:
        debug_cli._score_source_candidate_real_tree(
            candidate,
            function="fn_80000000",
            melee_root=melee_root,
            timeout=1.0,
        )

    assert excinfo.value.exit_code == 4
    assert source_path.read_text() == original
    entry = pcdump_cache.lookup(melee_root, unit)
    assert entry is not None
    assert entry.fresh is True
    assert pcdump_cache.hash_path(cache_path).exists()


def test_coalesce_search_help_smoke() -> None:
    result = runner.invoke(
        app,
        ["debug", "coalesce-search", "--help"],
        env={"COLUMNS": "160"},
    )

    assert result.exit_code == 0
    assert "--target" in result.stdout
    assert "--include-transform-corpus" in result.stdout
    assert "--transform-family" in result.stdout
    assert "--transform-force-phys" in result.stdout
    assert "--directed-force-phys" in result.stdout
    assert "--trace-copy-json" in result.stdout
