"""Check 2 (acceptance gate 2): the analyzer mechanically reproduces the
first-divergence allocator fact for gm and lbDvd on their real (same-source)
pcdumps.

NOTE on ig-index drift (an empirically-confirmed instance of the spec's "raw
ig_idx lies" caveat): the 2026-05-25 gm campaign recorded the coalesced cluster
as ig 42/38. In the current gm_16F1.c compile those nodes are 43/46 (the source
drifted, shifting the indices). We validate the *phenomenon* gm exhibits — a
cluster of loop-NULL-store virtuals coalescing into root 3 [r3] — using the
current indices, not the stale ones. lbDvd's source did not drift, so its
historical force-proof (44->r10, 46->r12) still applies verbatim.
"""
import pathlib

import pytest

from src.mwcc_debug.colorgraph_parser import parse_hook_events, find_function
from src.mwcc_debug import first_divergence as fd

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "mwcc_debug"


def _load(fname, fn):
    p = FIXTURES / fname
    if not p.exists():
        pytest.skip(f"{fname} not present")
    fev = find_function(parse_hook_events(p.read_text()), fn)
    if fev is None:
        pytest.skip(f"{fn} not in {fname}")
    return fev


def test_gm_first_divergence_is_case_d():
    """GATE 2a: gm's loop-NULL-store cluster coalesces into root 3 [r3].
    Requesting two of those nodes as targets must surface Case D ("prevent the
    coalesce"). Indices are current-compile (43/46); see module docstring re drift.
    """
    fev = _load("gm_80173EEC_pcdump.txt", "gm_80173EEC")
    target = fd.TargetColoring(class_id=0, force_phys={43: 28, 46: 28})
    report = fd.analyze_first_divergence(fev, target)
    assert report.fact.case == fd.DivergenceCase.D_COALESCED
    assert {43, 46}.issubset(set(report.fact.coalesced_nodes))
    assert report.fact.coalesced_root == 3
    assert report.fact.coalesced_root_phys == 3
    assert "prevent the coalesce" in report.fact.local_target
    assert report.source is None  # gated layer only; advisory is opt-in


def test_lbdvd_first_divergence_is_register_choice():
    """GATE 2b: lbDvd's nodes 44/46 carry the wrong r10<->r12 polarity (baseline
    44->r12, 46->r10; the force-proof wants 44->r10, 46->r12). The first
    divergence (by iteration, node 46) is a register-choice case in the B family
    with the r10<->r12 swap."""
    fev = _load("lbDvd_80018A2C_pcdump.txt", "lbDvd_80018A2C")
    target = fd.TargetColoring(class_id=0, force_phys={44: 10, 46: 12})
    report = fd.analyze_first_divergence(fev, target)
    f = report.fact
    assert f.case in (fd.DivergenceCase.B_TARGET_HIGHER, fd.DivergenceCase.B_INVERSE)
    assert f.ig_idx in (44, 46)
    assert {f.baseline_reg, f.target_reg} <= {10, 12}
    assert f.baseline_reg != f.target_reg
