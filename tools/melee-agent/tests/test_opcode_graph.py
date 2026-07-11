import pytest

from src.mwcc_debug.opcode_graph import (
    OpcodeGraph,
    opcode_graph_distance,
    parse_opcode_graph,
)

EXPECTED_REGISTER_SWAP = [
    "+000: 80 7f 00 04  lwz r3, 4(r31)",
    "+004: 38 83 00 01  addi r4, r3, 1",
    "+008: 90 9f 00 04  stw r4, 4(r31)",
    "+00c: 4e 80 00 20  blr",
]

CURRENT_REGISTER_SWAP = [
    "+000: 80 9e 00 08  lwz r4, 8(r30)",
    "+004: 38 64 00 09  addi r3, r4, 9",
    "+008: 90 7e 00 08  stw r3, 8(r30)",
    "+00c: 4e 80 00 20  blr",
]

CFG_A = [
    "+000: 2c 03 00 00  cmpwi r3, 0",
    "+004: 41 82 00 08  beq <fn_80000000+0xc>",
    "+008: 4e 80 00 20  blr",
    "+00c: 4e 80 00 20  blr",
]

CFG_B = [
    "+000: 2c 04 00 01  cmpwi r4, 1",
    "+004: 41 82 00 08  beq external_label",
    "+008: 4e 80 00 20  blr",
    "+00c: 4e 80 00 20  blr",
]


def test_register_only_diff_has_zero_opcode_graph_distance() -> None:
    expected = parse_opcode_graph(EXPECTED_REGISTER_SWAP)
    current = parse_opcode_graph(CURRENT_REGISTER_SWAP)

    assert opcode_graph_distance(expected, current, structural_status="structural-match") == (0, 0)


def test_branch_edge_change_is_not_zero() -> None:
    assert opcode_graph_distance(
        parse_opcode_graph(CFG_A),
        parse_opcode_graph(CFG_B),
        structural_status="opcode-mismatch",
    ) == (0, 1)


def test_zero_graph_with_rejected_structural_gate_is_incomplete_evidence() -> None:
    with pytest.raises(ValueError, match="opcode-structural-contradiction"):
        opcode_graph_distance(
            parse_opcode_graph(CFG_A),
            parse_opcode_graph(CFG_A),
            structural_status="structural-mismatch",
        )


def test_parser_builds_conditional_unconditional_and_fallthrough_edges() -> None:
    graph = parse_opcode_graph(
        [
            "+000: 2c 03 00 00  cmpwi r3, 0",
            "+004: 41 82 00 0c  beq <fn+0x10>",
            "+008: 38 60 00 01  li r3, 1",
            "+00c: 48 00 00 08  b <fn+0x14>",
            "+010: 38 60 00 00  li r3, 0",
            "+014: 48 00 00 01  bl helper",
            "+018: 38 63 00 01  addi r3, r3, 1",
            "+01c: 4e 80 00 20  blr",
        ]
    )

    assert graph == OpcodeGraph(
        nodes=(
            ("cmpwi", "beq"),
            ("li", "b"),
            ("li",),
            ("bl", "addi", "blr"),
        ),
        edges=frozenset({(0, 1), (0, 2), (1, 3), (2, 3)}),
    )


def test_parser_handles_indirect_branches_returns_and_unreachable_blocks() -> None:
    graph = parse_opcode_graph(
        [
            "+000: 2c 03 00 00  cmpwi r3, 0",
            "+004: 4d 82 00 20  beqlr",
            "+008: 4e 80 04 21  bctrl",
            "+00c: 38 63 00 01  addi r3, r3, 1",
            "+010: 4e 80 04 20  bctr",
            "+014: 38 60 00 00  li r3, 0",
            "+018: 4c 00 00 64  rfi",
        ]
    )

    assert graph == OpcodeGraph(
        nodes=(
            ("cmpwi", "beqlr"),
            ("bctrl", "addi", "bctr"),
            ("li", "rfi"),
        ),
        edges=frozenset({(0, 1)}),
    )


def test_parser_ignores_relocations_and_malformed_lines() -> None:
    graph = parse_opcode_graph(
        [
            "<fn_80000000>:",
            "+000: 38 60 00 01  li r3, 1",
            "+002: R_PPC_ADDR16_LO symbol",
            "+002: 00 00 00 00  R_PPC_ADDR16_LO symbol",
            "+004: .reloc 2, R_PPC_ADDR16_LO, symbol",
            "+004: not enough byte columns",
            "garbage",
            "+004: 4e 80 00 20  blr",
        ]
    )

    assert graph == OpcodeGraph(nodes=(("li", "blr"),), edges=frozenset())


def test_parser_orders_nodes_by_offset_independently_of_input_order() -> None:
    ordered = [
        "+000: 2c 03 00 00  cmpwi r3, 0",
        "+004: 41 82 00 08  beq <fn+0xc>",
        "+008: 38 60 00 01  li r3, 1",
        "+00c: 4e 80 00 20  blr",
    ]

    assert parse_opcode_graph(list(reversed(ordered))) == parse_opcode_graph(ordered)
