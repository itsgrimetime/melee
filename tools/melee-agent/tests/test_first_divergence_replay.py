import pathlib
import pytest
from src.mwcc_debug.colorgraph_parser import parse_hook_events, find_function
from src.mwcc_debug import first_divergence as fd

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "mwcc_debug"
FIXTURE_FILE = "fn_80247510_pcdump.txt"
FIXTURE_FN = "fn_80247510"


def _load():
    p = FIXTURES / FIXTURE_FILE
    if not p.exists():
        pytest.skip(f"{FIXTURE_FILE} not present")
    fev = find_function(parse_hook_events(p.read_text()), FIXTURE_FN)
    if fev is None:
        pytest.skip(f"{FIXTURE_FN} not in {FIXTURE_FILE}")
    return fev


def _validated_steps(fev):
    """(view, step) pairs the model is responsible for: real IG nodes that got a
    register, excluding documented model boundaries (ig=-1, spill, cap-hit,
    unreliable, recorded-r0)."""
    sec = fd.select_class_section(fev, 0)
    views = fd.decision_views(sec, fev)
    steps_by_iter = {s.iter_idx: s for s in fd.replay_decisions(views)}
    out = []
    for v in views:
        s = steps_by_iter[v.iter_idx]
        if (v.ig_idx == -1 or v.spilled or s.cap_hit or s.unreliable
                or v.assigned_reg == 0):
            continue
        out.append((v, s))
    return out


def test_fixture_exercises_dispense_and_reuse():
    """Guard: the gate is meaningless on a fixture with no callee-save reuse."""
    fev = _load()
    sec = fd.select_class_section(fev, 0)
    views = fd.decision_views(sec, fev)
    steps = fd.replay_decisions(views)
    dispenses = [s for s in steps if s.dispensed]
    reuses = [s for s in steps if not s.dispensed and 13 <= s.predicted_reg <= 31]
    assert len(dispenses) >= 1, "fixture never dispenses a callee-save"
    assert len(reuses) >= 1, "fixture never reuses a dispensed callee-save (won't validate C2)"


def test_replay_reproduces_recorded_coloring():
    """ACCEPTANCE GATE 1: predicted == recorded at every validated class-0
    decision. Oracle = recorded assigned_reg (ground truth), NOT `simulate`
    (which approximates iteration order). r0 / ig=-1 / spill / cap-hit /
    unreliable are documented model boundaries and are excluded."""
    fev = _load()
    validated = _validated_steps(fev)
    assert len(validated) >= 50, f"gate near-vacuous: only {len(validated)} validated decisions"
    mismatches = [(v.ig_idx, v.iter_idx, v.assigned_reg, s.predicted_reg)
                  for (v, s) in validated if s.predicted_reg != v.assigned_reg]
    assert not mismatches, f"replay diverged from recorded coloring: {mismatches}"
