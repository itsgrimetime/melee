import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_summary  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"


def test_regalloc_summary_includes_colored_and_coalesced_nodes():
    trace = json.loads(FIXTURE.read_text())
    assert backend_summary.render_regalloc_summary(trace) == (
        "schema mwcc-retro-backend-trace.v1\n"
        "\n"
        "function test_fn\n"
        "  class gpr(0)\n"
        "    ig=32 virt=r32 phys=r31 status=colored "
        "degree=1 simplify=1 select=1 blocked=33:r3\n"
        "    ig=33 virt=r33 phys=r30 status=colored "
        "degree=1 simplify=0 select=0 blocked=-\n"
        "    ig=40 virt=r40 phys=r31 status=coalesced_alias root=32 "
        "degree=0 simplify=None select=None blocked=-\n"
    )


def test_backend_summary_lists_passes_and_edges():
    trace = json.loads(FIXTURE.read_text())
    assert backend_summary.render_backend_summary(trace) == (
        "BACKEND TRACE test_fn\n"
        "pass before_register_coloring: BEFORE REGISTER COLORING\n"
        "  p0 B0 mr r32,r3\n"
        "  p1 B0 addi r33,r32,4\n"
        "regalloc class gpr(0)\n"
        "  edge 32 -- 33 observed interferencegraph\n"
    )


def test_regalloc_summary_ignores_null_and_malformed_blocked_by_entries():
    trace = {
        "schema_version": "mwcc-retro-backend-trace.v1",
        "functions": [
            {
                "name": "test_fn",
                "regalloc": {
                    "classes": [
                        {
                            "class_id": 0,
                            "class_name": "gpr",
                            "nodes": [
                                {
                                    "ig_id": 1,
                                    "virtual": {"kind": "r", "number": 1},
                                    "assigned_phys": 31,
                                    "color_status": "colored",
                                    "degree": 0,
                                    "simplify_order": 0,
                                    "select_order": 0,
                                    "color_decision_ref": "null-blocked",
                                },
                                {
                                    "ig_id": 2,
                                    "virtual": {"kind": "r", "number": 2},
                                    "assigned_phys": 30,
                                    "color_status": "colored",
                                    "degree": 0,
                                    "simplify_order": 1,
                                    "select_order": 1,
                                    "color_decision_ref": "bad-entry",
                                },
                            ],
                            "color_decisions": [
                                {"id": "null-blocked", "blocked_by": None},
                                {"id": "bad-entry", "blocked_by": ["bad"]},
                            ],
                        }
                    ]
                },
            }
        ],
    }

    assert backend_summary.render_regalloc_summary(trace) == (
        "schema mwcc-retro-backend-trace.v1\n"
        "\n"
        "function test_fn\n"
        "  class gpr(0)\n"
        "    ig=1 virt=r1 phys=r31 status=colored "
        "degree=0 simplify=0 select=0 blocked=-\n"
        "    ig=2 virt=r2 phys=r30 status=colored "
        "degree=0 simplify=1 select=1 blocked=-\n"
    )
