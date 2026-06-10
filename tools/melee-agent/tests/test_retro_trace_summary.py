import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from tools.mwcc_retro import trace_summary as ts  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures/retro/iro_trace_sample.txt"
REAL_FIXTURE = Path(__file__).parent / "fixtures/retro/iro_trace_real_sample.txt"


def test_parses_real_retail_trace():
    # Real output captured from retrowin32-driven retail GC/1.2.5n (mnVibration).
    text = REAL_FIXTURE.read_text(errors="replace")
    phases = ts.parse_phases(text)
    assert len(phases) >= 3
    assert phases[0].phase == "IRO_BuildflowGraph"
    # every parsed phase has a non-empty body of flowgraph/IR lines
    assert all(p.body for p in phases)
    summary = ts.build_summary(text)
    assert "IRO pass sequence" in summary


def test_slug_rule():
    assert ts.slug("IRO_CommonSubs") == "iro-commonsubs"
    assert ts.slug("IRO_RemoveLabels()") == "iro-removelabels"
    assert ts.slug("Second pass:A, B, C") == "second-pass-a-b-c"
    assert len(ts.slug("x" * 100)) == 60


def test_parse_phases():
    text = FIXTURE.read_text()
    phases = ts.parse_phases(text)
    names = [p.phase for p in phases]
    assert names == ["IRO_BuildflowGraph", "IRO_CommonSubs", "IRO_RemoveLabels()"]
    assert phases[0].pass_iter is None
    assert phases[1].pass_iter == 0 and phases[2].pass_iter == 0


def test_split_files(tmp_path):
    text = FIXTURE.read_text()
    written = ts.split_phase_files(text, tmp_path)
    assert (tmp_path / "iro-00-iro-buildflowgraph.txt").exists()
    assert (tmp_path / "iro-01-iro-commonsubs.txt").exists()
    assert len(written) == 3


def test_summary_temp_ledger(tmp_path):
    text = FIXTURE.read_text()
    summary = ts.build_summary(text)
    assert "after IRO_CommonSubs" in summary
    assert "removed" in summary.lower()
