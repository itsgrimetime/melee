"""Tests for DirectedObjective builder + pre-flight validation."""

import pytest
from src.search.directed.objective import (
    DirectedObjectiveBuildError,
    preflight_objective,
    PreflightError,
    build_directed_objective,
)
from src.search.directed.contracts import DirectedObjective
from src.search.types import SourceVariant
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


def test_build_objective_aborts_on_baseline_compile_without_pcdump(tmp_path):
    unit = "melee/ft/ftdynamics"
    tu = tmp_path / "src" / "melee" / "ft" / "ftdynamics.c"
    tu.parent.mkdir(parents=True)
    tu.write_text("/// #ftCo_8009E7B4\n")

    class _Backend:
        def compile(self, variant: SourceVariant, *, want_pcdump: bool = False):
            class _Artifact:
                status = "compile_failed"
                pcdump_path = None
                compiler_stderr = "function 'ftCo_8009E7B4' not found in pcdump"

            return _Artifact()

    with pytest.raises(DirectedObjectiveBuildError) as excinfo:
        build_directed_objective(
            melee_root=tmp_path,
            search_target=None,
            function="ftCo_8009E7B4",
            unit=unit,
            proof_force_phys={58: 4},
            class_id=0,
            backend=_Backend(),
        )

    assert "baseline pcdump compile failed" in str(excinfo.value)
    assert "ftCo_8009E7B4" in str(excinfo.value)
