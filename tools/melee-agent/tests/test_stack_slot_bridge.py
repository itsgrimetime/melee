"""Tests for mapping stack-slot checkdiff hints back to MWCC allocator roots."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.stack_slot_bridge import explain_stack_slot_localizer


PCDUMP = textwrap.dedent(
    """\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        bl      sqrtf__Ff
        frsp    f50,f1
        stfs    f50,0x30(r1)
        lfs     f51,0x30(r1)
        stfs    f60,0x38(r1)
    [COALESCE] enter class=1 n_virtuals=61
    [COALESCE] natural mappings (virt -> root):
      51 -> 50
    [COALESCE] exit class=1 n_virtuals=61 distinct_roots=60 forced=0
    IG CONSTRUCTED (class=1, n_nodes=61)
    SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=61)
      iter ig_idx degree arraySize flags notes
        0 50 2 2 0x08 SPILLED
        1 51 1 1 0x00
        2 60 0 0 0x00
    COLORGRAPH DECISIONS (class=1, result=1, n_nodes=61)
      iter ig_idx phys degree nIntfr flags
        0 50 r1 2 2 0x08
          interferers: 51=r2 60=r3
        1 51 r2 1 1 0x00
          interferers: 50=r1
        2 60 r3 0 0 0x00
          interferers:
    COALESCED ALIASES (alias_idx -> root_idx [root_phys]):
        51 -> 50 [r1]
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu    r1,-168(r1)
        bl      sqrtf__Ff
        frsp    f1,f1
        stfs    f1,0x30(r1)
        lfs     f2,0x30(r1)
        blr
    """
)


SOURCE = textwrap.dedent(
    """\
    void fn_80000000(float dx, float dy)
    {
        float dist;
        dist = sqrtf(dx * dx + dy * dy);
        sink(dist);
    }
    """
)


def test_stack_slot_bridge_maps_fpr_slot_to_spill_root_and_source() -> None:
    localizer = {
        "frame_size": 168,
        "mismatch_count": 1,
        "deltas": [4],
        "mismatches": [
            {
                "opcode": "stfs",
                "expected_offset": 0x34,
                "current_offset": 0x30,
                "delta": 4,
            }
        ],
    }

    report = explain_stack_slot_localizer(
        PCDUMP,
        "fn_80000000",
        localizer,
        source_text=SOURCE,
        source_file="src/melee/pl/plbonuslib.c",
    )

    assert report["status"] == "ok"
    assert report["candidate_count"] == 1
    candidate = report["candidates"][0]
    assert candidate["spill_root"] == "r50"
    assert candidate["virtual_token"] == "f50"
    assert candidate["register_class"] == 1
    assert candidate["ig_idx"] == 50
    assert candidate["assigned_reg"] == "f1"
    assert candidate["simplify"]["spilled"] is True
    assert candidate["coalesced_aliases"] == [
        {"alias": 51, "root": 50, "root_phys": "f1"}
    ]
    assert candidate["natural_coalesce_aliases"] == [{"alias": 51, "root": 50}]
    assert candidate["nearest_source_expression"] == {
        "expression": "sqrtf(dx * dx + dy * dy)",
        "confidence": "source-call-heuristic",
        "source_file": "src/melee/pl/plbonuslib.c",
        "source_line": 4,
        "source_col": 12,
    }
    assert candidate["stack_home_order"][:2] == [
        {
            "offset": 0x30,
            "virtual": 50,
            "virtual_token": "f50",
            "opcodes": ["lfs", "stfs"],
        },
        {
            "offset": 0x38,
            "virtual": 60,
            "virtual_token": "f60",
            "opcodes": ["stfs"],
        },
    ]
    assert any("BEFORE REGISTER COLORING" in item for item in candidate["evidence"])
