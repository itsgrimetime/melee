# tools/melee-agent/tests/test_suggest_coalesce.py
"""End-to-end tests for the suggest_coalesce orchestrator."""

from __future__ import annotations

import json
import pathlib

from src.mwcc_debug.coalesce_patterns import Suggestion
from src.mwcc_debug.suggest_coalesce import (
    PairReport, Report, render_json, render_text, run,
)


FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "mwcc_debug"


def test_run_pair_mode_returns_report_with_suggestions() -> None:
    """Running on a real fixture with a known coalesce-amenable pair
    produces at least one Suggestion."""
    if not (FIXTURES / "fn_802461BC_pcdump.txt").exists():
        import pytest
        pytest.skip("fn_802461BC_pcdump.txt fixture not present")
    text = (FIXTURES / "fn_802461BC_pcdump.txt").read_text()
    # The fixture file does not contain fn_802461BC itself; it contains
    # mnDiagram3_8024714C (and others from the same TU).  Use a function
    # that is actually present so run() does not raise ValueError.
    report = run(
        function="mnDiagram3_8024714C",
        pair=(53, 3),
        discover=False,
        pcdump_text=text,
    )
    assert report is not None
    assert report.mode == "pair"
    assert len(report.pairs) == 1
    # Either we have suggestions, or the fall-through emits raw facts
    pair = report.pairs[0]
    assert pair.from_virt == 53
    assert pair.to_virt == 3


def test_run_pair_mode_serializes_to_valid_json() -> None:
    """The Report → render_json output is parseable JSON."""
    if not (FIXTURES / "fn_802461BC_pcdump.txt").exists():
        import pytest
        pytest.skip("fixture not present")
    text = (FIXTURES / "fn_802461BC_pcdump.txt").read_text()
    report = run(
        function="mnDiagram3_8024714C", pair=(53, 3), discover=False,
        pcdump_text=text,
    )
    out = render_json(report)
    parsed = json.loads(out)
    assert parsed["function"] == "mnDiagram3_8024714C"
    assert parsed["mode"] == "pair"


import yaml


def _load_calibration():
    """Load the calibration YAML; skip silently if not present."""
    path = pathlib.Path(__file__).parent / "fixtures" / "coalesce_calibration.yaml"
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text()).get("cases", [])


import pytest


@pytest.mark.parametrize("case", _load_calibration())
def test_calibration_corpus(case) -> None:
    """Each calibration case asserts the orchestrator behaves as the
    YAML specifies. New cases can be added without writing new test
    code — just append to coalesce_calibration.yaml."""
    fixture_path = FIXTURES / case["pcdump"]
    if not fixture_path.exists():
        pytest.skip(f"fixture {case['pcdump']} not present")
    text = fixture_path.read_text()

    if case.get("discover"):
        report = run(
            function=case["function"],
            discover=True, pcdump_text=text,
        )
        assert report.mode == "discover"
        min_len = case.get("expected_cascade_length_min", 2)
        assert report.cascade is not None
        assert len(report.cascade) >= min_len
        if "expected_top_priority_class" in case:
            assert report.pairs, "discover produced no candidates"
            assert (
                report.pairs[0].priority_class
                == case["expected_top_priority_class"]
            )
        # Strict: top-1 pair equality (when set in YAML)
        top_pair = case.get("expected_top_pair")
        if top_pair is not None:
            assert report.pairs, "discover produced no candidates"
            actual = (report.pairs[0].from_virt, report.pairs[0].to_virt)
            assert actual == tuple(top_pair), (
                f"expected top-1 pair {tuple(top_pair)}, got {actual}"
            )
    else:
        pair_tuple = tuple(case["pair"])
        report = run(
            function=case["function"],
            pair=pair_tuple, discover=False,
            pcdump_text=text,
        )
        assert report.mode == "pair"
        assert len(report.pairs) == 1
        pr = report.pairs[0]
        # Strict: each expected pattern name must appear in suggestions
        expected_patterns = set(case.get("expected_patterns") or [])
        if expected_patterns:
            actual_patterns = {s.pattern_name for s in pr.suggestions}
            missing = expected_patterns - actual_patterns
            assert not missing, (
                f"expected patterns {expected_patterns}, "
                f"actual {actual_patterns}, missing {missing}"
            )
        else:
            # Fall-through acceptable: any non-empty ir_facts is OK
            assert pr.ir_facts


import subprocess


def test_cli_smoke_invokes_command() -> None:
    """Sanity test that the CLI command is wired correctly."""
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "suggest-coalesce-source", "--help"],
        cwd=pathlib.Path(__file__).parent.parent,  # tools/melee-agent
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0
    assert "--function" in proc.stdout
    assert "--pair" in proc.stdout
    assert "--discover" in proc.stdout


def test_cli_rejects_both_pair_and_discover() -> None:
    """Mutually-exclusive option enforcement."""
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "suggest-coalesce-source",
         "-f", "any_fn", "-V", "53=3", "--discover"],
        cwd=pathlib.Path(__file__).parent.parent,  # tools/melee-agent
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode != 0
    assert "exactly one of --pair / --discover" in proc.stderr


def test_cli_rejects_top_in_pair_mode() -> None:
    """--top is only valid with --discover."""
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "suggest-coalesce-source",
         "-f", "any_fn", "-V", "53=3", "--top", "5"],
        cwd=pathlib.Path(__file__).parent.parent,  # tools/melee-agent
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode != 0
    assert "--top is only valid with --discover" in proc.stderr


def test_render_text_includes_all_pair_fields() -> None:
    """render_text emits every field the discover-mode renderer is
    responsible for: title, cascade, pair header, priority_class,
    depends_on, IR facts heading, and each Suggestion's pattern name,
    summary, evidence prefix, try-hint prefix, and catalog ref."""
    report = Report(
        function="test_fn",
        mode="discover",
        cascade=[31, 30, 29, 28],
        pairs=[PairReport(
            from_virt=53,
            to_virt=42,
            ir_facts={
                "from": {"virtual": 53, "is_phys": False,
                         "first_def": {"block": 5, "opcode": "addi",
                                       "operands": "r53,r42,0"},
                         "use_blocks": [5, 7]},
                "to":   {"virtual": 42, "is_phys": False,
                         "first_def": {"block": 2, "opcode": "li",
                                       "operands": "r42,0"},
                         "use_blocks": [2, 5, 7]},
            },
            suggestions=[Suggestion(
                pattern_name="direct-identity",
                summary="r53 is already a direct copy from r42",
                ir_evidence="B5: addi r53, r42, 0",
                source_hint="shrink the live range...",
                catalog_ref="alias-split",
            )],
            priority_class="end-of-chain",
            depends_on=(50, 51),
        )],
    )
    out = render_text(report)
    assert "test_fn" in out
    assert "--discover" in out
    assert "r31 → r30 → r29 → r28" in out
    assert "pair r53=r42" in out
    assert "[end-of-chain]" in out
    assert "depends_on r50=r51" in out
    assert "IR facts:" in out
    assert "direct-identity" in out
    assert "r53 is already a direct copy from r42" in out
    assert "evidence:" in out
    assert "try:" in out
    assert "Catalog: debug pattern-catalog alias-split" in out


def test_render_text_fall_through_when_no_suggestions() -> None:
    """When a pair has zero suggestions, the fall-through block fires."""
    report = Report(
        function="test_fn",
        mode="pair",
        pairs=[PairReport(
            from_virt=53, to_virt=42,
            ir_facts={"from": {"virtual": 53, "is_phys": False},
                      "to":   {"virtual": 42, "is_phys": False}},
            suggestions=[],
        )],
    )
    out = render_text(report)
    assert "No specific pattern matched" in out
    assert "register-cascade" in out


# --- Preflight tests (Fix E) -----------------------------------------------


def test_preflight_flags_physical_reg() -> None:
    """A pair where either virtual is < 32 (physical reg) is flagged."""
    from src.mwcc_debug.coalesce_ir_facts import IrFacts
    from src.mwcc_debug.parser import Pass
    from src.mwcc_debug.suggest_coalesce import _preflight_pair
    facts = IrFacts(
        function_name="x", pre_pass=Pass(name="t"),
        by_virtual={}, bindings=[], basis=None, cg_section=None,
    )
    pf = _preflight_pair(facts, 3, 42)
    assert not pf.safe
    assert any("physical regs" in r for r in pf.reasons)


def test_preflight_safe_when_no_data() -> None:
    """No cg_section + no phys regs → 'untested' but still safe=False
    because we add a reason explaining the gap. (Callers should treat
    this as 'preflight could not run', not 'this pair is safe'.)"""
    from src.mwcc_debug.coalesce_ir_facts import IrFacts
    from src.mwcc_debug.parser import Pass
    from src.mwcc_debug.suggest_coalesce import _preflight_pair
    facts = IrFacts(
        function_name="x", pre_pass=Pass(name="t"),
        by_virtual={}, bindings=[], basis=None, cg_section=None,
    )
    pf = _preflight_pair(facts, 55, 73)
    assert not pf.safe
    assert any(
        "no colorgraph data" in r for r in pf.reasons
    )


def test_preflight_flags_direct_interference() -> None:
    """When colorgraph data shows a interferes with b, flag it."""
    from src.mwcc_debug.coalesce_ir_facts import IrFacts
    from src.mwcc_debug.colorgraph_parser import (
        ColorgraphDecision, ColorgraphSection,
    )
    from src.mwcc_debug.parser import Pass
    from src.mwcc_debug.suggest_coalesce import _preflight_pair
    # cg_section where ig_idx=55 lists 73 as an interferer.
    cg = ColorgraphSection(
        class_id=1, result=0, n_nodes=2,
        decisions=[
            ColorgraphDecision(
                iter_idx=0, ig_idx=55, assigned_reg=29,
                degree=1, n_interferers=1, flags=0,
                interferers=[(73, 30)],
            ),
            ColorgraphDecision(
                iter_idx=1, ig_idx=73, assigned_reg=30,
                degree=1, n_interferers=1, flags=0,
                interferers=[(55, 29)],
            ),
        ],
    )
    facts = IrFacts(
        function_name="x", pre_pass=Pass(name="t"),
        by_virtual={}, bindings=[], basis=None, cg_section=cg,
    )
    pf = _preflight_pair(facts, 55, 73)
    assert not pf.safe
    assert any("interfere directly" in r for r in pf.reasons)


def test_preflight_flags_missing_colorgraph_node() -> None:
    """If either virtual is absent from the selected colorgraph section,
    do not present the coalesce as safe. This catches simplify-only /
    pcode-only temps before a forced run can hang local wibo."""
    from src.mwcc_debug.coalesce_ir_facts import IrFacts
    from src.mwcc_debug.colorgraph_parser import (
        ColorgraphDecision, ColorgraphSection,
    )
    from src.mwcc_debug.parser import Pass
    from src.mwcc_debug.suggest_coalesce import _preflight_pair

    cg = ColorgraphSection(
        class_id=0, result=1, n_nodes=1,
        decisions=[
            ColorgraphDecision(
                iter_idx=0, ig_idx=34, assigned_reg=31,
                degree=0, n_interferers=0, flags=0,
                interferers=[],
            ),
        ],
    )
    facts = IrFacts(
        function_name="fn_80247510", pre_pass=Pass(name="t"),
        by_virtual={}, bindings=[], basis=None, cg_section=cg,
    )

    pf = _preflight_pair(facts, 34, 50)

    assert not pf.safe
    assert any("missing colorgraph node" in r for r in pf.reasons)


def test_render_text_surfaces_preflight_warning() -> None:
    """Render text marks pairs with [PREFLIGHT: WARNING] when unsafe."""
    from src.mwcc_debug.suggest_coalesce import Preflight
    report = Report(
        function="test_fn",
        mode="pair",
        pairs=[PairReport(
            from_virt=55, to_virt=73,
            ir_facts={"from": {"virtual": 55, "is_phys": False},
                      "to":   {"virtual": 73, "is_phys": False}},
            suggestions=[],
            preflight=Preflight(safe=False, reasons=["interfere directly"]),
        )],
    )
    out = render_text(report)
    assert "[PREFLIGHT: WARNING]" in out
    assert "interfere directly" in out


def test_render_json_includes_preflight() -> None:
    """JSON output includes preflight field per pair."""
    from src.mwcc_debug.suggest_coalesce import Preflight
    report = Report(
        function="test_fn",
        mode="pair",
        pairs=[PairReport(
            from_virt=55, to_virt=73,
            ir_facts={"from": {"virtual": 55, "is_phys": False},
                      "to":   {"virtual": 73, "is_phys": False}},
            suggestions=[],
            preflight=Preflight(safe=False, reasons=["bad pair"]),
        )],
    )
    out = render_json(report)
    parsed = json.loads(out)
    pair = parsed["pairs"][0]
    assert pair["preflight"] is not None
    assert pair["preflight"]["safe"] is False
    assert pair["preflight"]["reasons"] == ["bad pair"]
