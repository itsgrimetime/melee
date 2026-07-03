import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_summary  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"


def test_regalloc_summary_includes_colored_and_coalesced_nodes():
    trace = json.loads(FIXTURE.read_text())
    text = backend_summary.render_regalloc_summary(trace)
    assert "function test_fn" in text
    assert "class gpr(0)" in text
    assert "ig=32 virt=r32 phys=r31 status=colored" in text
    assert "ig=40 virt=r40 phys=r31 status=coalesced_alias root=32" in text
    assert "blocked=33:r3" in text


def test_backend_summary_lists_passes_and_edges():
    trace = json.loads(FIXTURE.read_text())
    text = backend_summary.render_backend_summary(trace)
    assert "BACKEND TRACE test_fn" in text
    assert "BEFORE REGISTER COLORING" in text
    assert "edge 32 -- 33" in text
