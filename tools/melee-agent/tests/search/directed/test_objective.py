"""Tests for DirectedObjective builder + pre-flight validation."""

import pytest
from src.search.directed.objective import preflight_objective, PreflightError
from src.search.directed.contracts import DirectedObjective
from src.mwcc_debug.first_divergence import DivergenceCase


class _Fact:
    def __init__(self, case):
        self.case = case
        self.ig_idx = 1


class _State:
    def __init__(self, case):
        self.fact = _Fact(case)


class _Re:
    def __init__(self, matched):
        self.matched = matched


def _obj(roles):
    class _RT:
        pass

    rt = _RT()
    rt.roles = roles
    rt.function = "grIceMt_801F9ACC"
    return DirectedObjective(
        search_target=None,
        role_target=rt,
        baseline_compile=object(),
        baseline_pcdump_path=None,
        baseline_source_hash="h",
        class_id=0,
        objective_iter_by_original_ig={},
        proof_force_phys={},
    )


def test_preflight_aborts_on_empty_roles():
    with pytest.raises(PreflightError):
        preflight_objective(
            _obj([]),
            analyze=lambda t, c, class_id=0: (
                _State(DivergenceCase.B_TARGET_HIGHER),
                object(),
                _Re({1: 37}),
            ),
        )


def test_preflight_aborts_on_enum_case_none():
    with pytest.raises(PreflightError):
        preflight_objective(
            _obj([object()]),
            analyze=lambda t, c, class_id=0: (
                _State(DivergenceCase.NONE),
                object(),
                _Re({1: 37}),
            ),
        )


def test_preflight_aborts_on_enum_case_abstained():
    with pytest.raises(PreflightError):
        preflight_objective(
            _obj([object()]),
            analyze=lambda t, c, class_id=0: (
                _State(DivergenceCase.ABSTAINED),
                object(),
                _Re({1: 37}),
            ),
        )


def test_preflight_aborts_on_none_report():
    with pytest.raises(PreflightError):
        preflight_objective(
            _obj([object()]),
            analyze=lambda t, c, class_id=0: (
                _State(DivergenceCase.B_TARGET_HIGHER),
                None,
                _Re({1: 37}),
            ),
        )


def test_preflight_passes_on_valid():
    preflight_objective(
        _obj([object(), object()]),
        analyze=lambda t, c, class_id=0: (
            _State(DivergenceCase.B_TARGET_HIGHER),
            object(),
            _Re({1: 37, 2: 34}),
        ),
    )
