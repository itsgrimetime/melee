"""Exact-retail opcode, constructor, and register-domain proof tests."""

from __future__ import annotations

import struct
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import pe
from tools.mwcc_retro.backend_instrumentation_proof import (
    expand_operand_descriptors,
    validate_proof_shape,
)
from tools.mwcc_retro.backend_opcode_layout import (
    CUSTOM_OPCODES,
    EVIDENCE_ADDRESSES,
    OPCODE_COUNT,
    OPCODE_METADATA_ROW_SIZE,
    OPCODE_METADATA_TABLE,
    RETAIL_GC125N_SHA256,
    VARIADIC_OPCODES,
    analyze_opcode_layouts,
    build_opcode_proof_tables,
)
from tools.mwcc_retro.x86_cfg import Instruction

COMPILER = REPO / "build/compilers/GC/1.2.5n/mwcceppc.exe"
pytestmark = pytest.mark.skipif(not COMPILER.exists(), reason="exact retail GC/1.2.5n compiler is unavailable")


def _exact_inputs():
    image = pe.load(
        COMPILER,
        expected_sha256=RETAIL_GC125N_SHA256,
        require_pe32_i386=True,
    )
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    instructions = []
    for address in EVIDENCE_ADDRESSES:
        decoded = next(decoder.disasm(image.read(address, 15), address))
        payload = image.read(address, decoded.size)
        instructions.append(
            Instruction(
                address=address,
                size=decoded.size,
                bytes_hex=payload.hex(),
                mnemonic=decoded.mnemonic,
                operands=decoded.op_str,
            )
        )
    return image, SimpleNamespace(
        instructions=tuple(instructions),
        direct_calls=(SimpleNamespace(address=0x004A2D17, target=0x004A3590),),
    )


def _closed_values():
    """Minimal shape of Task 5 facts used by the pseudo-op closure.

    The analyzer validates the concrete write inventory; there are no
    custom-layout/domain/variadic attestation booleans in this fixture.
    """

    return SimpleNamespace(
        compiler_sha256=RETAIL_GC125N_SHA256,
        proof_ready=True,
        unresolved=(),
        calls=(
            SimpleNamespace(
                address=0x00420000,
                target=0x004A25D0,
                function_entry=0x0041F000,
                arguments=(
                    SimpleNamespace(kind="exact", values=frozenset({1})),
                    SimpleNamespace(kind="exact", values=frozenset({49})),
                ),
            ),
            SimpleNamespace(
                address=0x00420010,
                target=0x004A2620,
                function_entry=0x0041F000,
                arguments=(
                    SimpleNamespace(kind="exact", values=frozenset({39})),
                    SimpleNamespace(kind="exact", values=frozenset({4})),
                ),
            ),
            SimpleNamespace(
                address=0x00420020,
                target=0x004A2620,
                function_entry=0x0041F000,
                arguments=(
                    SimpleNamespace(kind="exact", values=frozenset({20})),
                    SimpleNamespace(kind="exact", values=frozenset({49})),
                ),
            ),
            SimpleNamespace(
                address=0x00420030,
                target=0x004A2620,
                function_entry=0x0041F000,
                arguments=(
                    SimpleNamespace(kind="exact", values=frozenset({54})),
                    SimpleNamespace(kind="exact", values=frozenset({4})),
                ),
            ),
        ),
        memory_writes=(
            SimpleNamespace(
                address=0x004AEB14,
                width=2,
                offset=0,
                base=SimpleNamespace(pointer_type=""),
                value=SimpleNamespace(kind="exact", values=frozenset({466})),
            ),
        ),
    )


def _inventory():
    image, cfg = _exact_inputs()
    return analyze_opcode_layouts(image, cfg, _closed_values())


def _mutate_va(image, address: int, payload: bytes):
    offset = image.va_to_offset(address)
    assert offset is not None
    data = bytearray(image.data)
    data[offset : offset + len(payload)] = payload
    return replace(image, data=bytes(data))


def test_exact_468_rows_and_metadata_digest():
    inventory = _inventory()
    assert [row.opcode_id for row in inventory.opcode_rows] == list(range(OPCODE_COUNT))
    assert inventory.opcode_rows[0].mnemonic == "B"
    assert inventory.opcode_rows[-1].mnemonic == "PEXIT"
    assert len({row.mnemonic for row in inventory.opcode_rows}) == OPCODE_COUNT
    assert len({row.format_string for row in inventory.opcode_rows}) == 103
    assert inventory.metadata_sha256 == ("4dfd675154dd9085db6a08dd78c2719a0bf2a1621f71d009791020f6fb76f238")


def test_generic_constructor_mapping_and_raw_pcodearg_layout_are_proved():
    inventory = _inventory()
    row = inventory.opcode_rows[63]
    assert row.mnemonic == "ADDI"
    assert row.format_string == "=r,b,m,p"
    assert [descriptor.role for descriptor in row.operand_descriptors] == [
        "def",
        "use",
        "use",
        "use",
    ]
    assert [(descriptor.raw_arg_kind_id, descriptor.register_form) for descriptor in row.operand_descriptors] == [
        (0, "gpr"),
        (0, "gpr"),
        (4, "memory"),
        (10, "opaque"),
    ]
    layout = inventory.raw_pcode_arg_layout
    assert (layout.size, layout.kind_offset, layout.flags_offset) == (12, 0, 1)
    assert (layout.payload_offset, layout.payload_width, layout.payload_signed) == (
        2,
        2,
        False,
    )


def test_custom_layouts_are_exact_and_complete():
    inventory = _inventory()
    evidence = {row.opcode_id: row for row in inventory.custom_constructors}
    assert set(evidence) == CUSTOM_OPCODES
    expected = {
        3: [(4, "immediate", "use"), (3, "cr", "use"), (4, "immediate", "use")],
        4: [(4, "immediate", "use"), (3, "cr", "use"), (4, "immediate", "use")],
        12: [(3, "cr", "use"), (4, "immediate", "use"), (5, "branch-target", "use")],
        13: [(3, "cr", "use"), (4, "immediate", "use"), (5, "branch-target", "use")],
        15: [(3, "cr", "use"), (4, "immediate", "use"), (5, "branch-target", "use")],
        16: [(3, "cr", "use"), (4, "immediate", "use"), (5, "branch-target", "use")],
        199: [(0, "gpr", "def"), (4, "immediate", "use")],
    }
    for opcode_id, shape in expected.items():
        row = inventory.opcode_rows[opcode_id]
        assert row.constructor_kind == "custom"
        assert [(item.raw_arg_kind_id, item.register_form, item.role) for item in row.operand_descriptors] == shape
        assert evidence[opcode_id].addresses
        assert evidence[opcode_id].instruction_bytes_hex


def test_variadic_sources_model_exact_metadata_formats_and_u32_count_source():
    inventory = _inventory()
    sources = {row.opcode_id: row for row in inventory.variadic_sources}
    assert set(sources) == VARIADIC_OPCODES
    assert {
        opcode_id: inventory.opcode_rows[opcode_id].format_string
        for opcode_id in sorted(VARIADIC_OPCODES)
    } == {
        1: "#,m",
        19: "#,C",
        20: "#,L",
        39: "#,=r,b,m,=V",
        54: "#,r,b,m,V",
    }
    assert all(row.source == "first-vararg-u32-at-generic-constructor" for row in sources.values())
    assert all(source.count_width == 4 for source in sources.values())
    assert all(
        (source.constructor_count_min, source.constructor_count_max)
        == (0, 0xFFFFFFFF)
        for source in sources.values()
    )
    assert all(
        source.bound_kind == "exact-u32-constructor-load"
        for source in sources.values()
    )
    assert all(
        source.count_arithmetic
        == "u32-add-metadata-low-byte-store-low-u16"
        for source in sources.values()
    )
    assert {opcode_id: row.base_operand_count for opcode_id, row in sources.items()} == {
        1: 1,
        19: 0,
        20: 0,
        39: 3,
        54: 3,
    }
    assert {opcode_id: row.tail_expansion for opcode_id, row in sources.items()} == {
        1: "post-constructor",
        19: "unreachable",
        20: "post-constructor",
        39: "format-V",
        54: "format-V",
    }


def test_call_variadics_have_exact_post_constructor_tail_descriptors():
    inventory = _inventory()
    expected_prefix = [
        (0, "gpr", "fixed", 11),
        (1, "fpr", "fixed", 14),
        (9, "vector", "fixed", 20),
        (3, "cr", "one", 1),
        (3, "cr", "one", 1),
    ]
    for opcode_id in (1, 20):
        descriptors = inventory.opcode_rows[opcode_id].operand_descriptors
        formatted = [row for row in descriptors if row.descriptor_source == "format"]
        tail = [row for row in descriptors if row.descriptor_source == "variadic-tail"]
        assert len(formatted) == 1
        assert formatted[0].format_code in {"m", "C", "L"}
        assert [
            (
                row.raw_arg_kind_id,
                row.register_form,
                row.expansion_kind,
                row.expansion_count,
            )
            for row in tail[:5]
        ] == expected_prefix
        assert all(
            tuple(
                (rule.register_flags_mask, rule.register_flags_value, rule.role)
                for rule in row.role_rules
            )
            == ((0xFF, 2, "def"), (0xFF, 3, "use-def"))
            for row in tail[:3]
        )
        assert tail[-1].raw_arg_kind_id == 0
        assert tail[-1].role == "use"
        assert tail[-1].expansion_kind == "remaining"
        assert tail[-1].expansion_count is None
    assert _inventory().opcode_rows[20].operand_descriptors[-2].expansion_kind == (
        "optional"
    )
    assert all(
        row.descriptor_source == "format"
        for row in _inventory().opcode_rows[19].operand_descriptors
    )
    assert {
        row.opcode_id: row.reachability for row in _inventory().variadic_sources
    }[19] == "unreachable"


def test_reachable_bctrl_fails_closed_without_a_proved_tail_producer():
    image, cfg = _exact_inputs()
    values = _closed_values()
    bctrl_call = SimpleNamespace(
        address=0x00420008,
        target=0x004A2620,
        function_entry=0x0041F000,
        arguments=(
            SimpleNamespace(kind="exact", values=frozenset({19})),
            SimpleNamespace(kind="exact", values=frozenset({49})),
        ),
    )
    values.calls = (*values.calls, bctrl_call)

    inventory = analyze_opcode_layouts(image, cfg, values)

    assert not inventory.proof_ready
    assert "variadic-tail-producer-unproved:19" in inventory.unresolved
    with pytest.raises(ValueError, match="inventory is not proof-ready"):
        build_opcode_proof_tables(inventory)


def test_v_remaining_and_y_fixed_eight_expansion():
    descriptors = [descriptor for row in _inventory().opcode_rows for descriptor in row.operand_descriptors]
    remaining = [row for row in descriptors if row.format_code == "V"]
    fixed_eight = [row for row in descriptors if row.format_code == "Y"]
    assert len(remaining) == 2
    assert all(row.expansion_kind == "remaining" and row.expansion_count is None for row in remaining)
    assert len(fixed_eight) == 2
    assert all(row.expansion_kind == "fixed" and row.expansion_count == 8 for row in fixed_eight)


def test_stage_specific_register_domains_are_exact():
    domains = _inventory().register_domains
    assert {(row.register_form, row.raw_arg_kind_id, row.class_id, row.virtual_kind) for row in domains} == {
        ("gpr", 0, 0, "r"),
        ("fpr", 1, 1, "f"),
        ("vector", 9, 9, "v"),
        ("special", 2, None, None),
        ("cr", 3, None, None),
    }
    for form in ("gpr", "fpr", "vector"):
        rows = [row for row in domains if row.register_form == form]
        assert {(row.capture_stage, row.allocation_state, row.value_min, row.value_max) for row in rows} == {
            ("allocator_input", "physical", 0, 31),
            ("allocator_input", "virtual", 32, 0x7FFF),
            ("mutation_output", "physical", 0, 31),
            ("mutation_output", "virtual", 32, 0x7FFF),
            ("code_emission", "physical", 0, 31),
        }
    assert {
        (row.register_form, row.capture_stage, row.value_min, row.value_max)
        for row in domains
        if row.register_form in {"special", "cr"}
    } == {
        (form, stage, 0, maximum)
        for form, maximum in (("special", 2), ("cr", 7))
        for stage in ("allocator_input", "mutation_output", "code_emission")
    }


def test_allocator_rewrite_preserves_kind_and_flags_and_rewrites_u16_payload():
    layout = _inventory().raw_pcode_arg_layout
    assert layout.allocator_rewrite_address == 0x004CE1E7
    assert layout.allocator_rewritten_fields == ("payload",)
    assert layout.allocator_preserved_fields == ("kind", "flags")


def test_pseudo_ops_are_zero_encoding_and_cannot_reach_encoder_dispatch():
    pseudo = {row.opcode_id: row for row in _inventory().pseudo_opcodes}
    assert set(pseudo) == {466, 467}
    assert pseudo[466].mnemonic == "PENTRY" and pseudo[466].encoding == 0
    assert pseudo[467].mnemonic == "PEXIT" and pseudo[467].encoding == 0
    assert all(row.final_disposition == "eliminated-before-encoder" for row in pseudo.values())
    assert all(row.maximum_encodable_opcode == 465 for row in pseudo.values())


def test_exact_evidence_closes_inventory_without_boolean_attestations():
    inventory = _inventory()
    assert inventory.proof_ready
    assert inventory.unresolved == ()


def test_proof_table_generator_emits_closed_variadic_and_tail_schema():
    tables = build_opcode_proof_tables(_inventory())
    proof = {
        "schema_version": "mwcc-retro-lifetime-proof.v1",
        "proof_id": "test",
        "compiler_executable_sha256": RETAIL_GC125N_SHA256,
        "runtime_hook_manifest_sha256": "0" * 64,
        "mode": "allocation-generation",
        "allocation_sites": [
            {
                "site_id": "allocation",
                "address": 0x401000,
                "entity_kind": "pcode",
                "compiler_stage": "backend-lowering",
            }
        ],
        "free_sites": [
            {
                "site_id": "free",
                "address": 0x401010,
                "entity_kind": "pcode",
                "compiler_stage": "backend-finalize",
            }
        ],
        "operand_rewrite_sites": [
            {
                "site_id": "rewrite",
                "address": 0x401020,
                "compiler_stage": "colorgraph",
            }
        ],
        "operand_mutation_sites": [
            {
                "site_id": "mutation",
                "address": 0x401030,
                "compiler_stage": "optimizer",
            }
        ],
        "code_emission_sites": [
            {
                "site_id": "emission",
                "address": 0x401040,
                "compiler_stage": "backend-finalize",
            }
        ],
        "operand_rules": list(tables.operand_rules),
        "opcode_table": list(tables.opcode_table),
        "initialization_address": 0x401000,
        "proof_basis": "exhaustive-static-callgraph-and-disassembly",
    }
    assert validate_proof_shape(proof) == ()

    descriptor_proof = {"operand_rules": list(tables.operand_rules)}
    assert [
        row.descriptor_index
        for row in expand_operand_descriptors(descriptor_proof, 1, 50)
    ] == [0] + [1] * 11 + [2] * 14 + [3] * 20 + [4, 5] + [6] * 2
    assert [
        row.descriptor_index
        for row in expand_operand_descriptors(descriptor_proof, 1, 51)
    ][-1] == 7
    assert [
        expand_operand_descriptors(descriptor_proof, 20, count)[-1].descriptor_index
        for count in (49, 50, 51)
    ] == [6, 7, 8]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("compiler_sha256", "0" * 64),
        ("metadata_sha256", "0" * 64),
        ("generic_constructor_sha256", "0" * 64),
    ],
)
def test_proof_table_generator_rechecks_exact_retail_evidence(field, value):
    inventory = replace(_inventory(), **{field: value})

    with pytest.raises(ValueError, match="exact retail evidence"):
        build_opcode_proof_tables(inventory)


def test_metadata_and_binary_layout_evidence_alone_do_not_close_pseudo_ops():
    image, cfg = _exact_inputs()
    inventory = analyze_opcode_layouts(image, cfg)
    assert not inventory.proof_ready
    assert "pseudo-op-final-list-closure-unproved" in inventory.unresolved


def test_pseudo_constructor_domain_or_pcode_write_blocks():
    image, cfg = _exact_inputs()
    values = _closed_values()
    bad_calls = list(values.calls)
    bad_calls[0] = SimpleNamespace(
        **{
            **vars(bad_calls[0]),
            "arguments": (SimpleNamespace(kind="exact", values=frozenset({466})),),
        }
    )
    result = analyze_opcode_layouts(image, cfg, SimpleNamespace(**{**vars(values), "calls": tuple(bad_calls)}))
    assert not result.proof_ready
    assert any("constructor-domain-reaches-pseudo" in row for row in result.unresolved)

    bad_write = SimpleNamespace(
        **{
            **vars(values.memory_writes[0]),
            "base": SimpleNamespace(pointer_type="pcode"),
        }
    )
    result = analyze_opcode_layouts(
        image,
        cfg,
        SimpleNamespace(**{**vars(values), "memory_writes": (bad_write,)}),
    )
    assert not result.proof_ready
    assert any("pseudo-op-write-inventory-differs" in row for row in result.unresolved)


def test_missing_or_reordered_evidence_blocks():
    image, cfg = _exact_inputs()
    missing = SimpleNamespace(instructions=cfg.instructions[1:])
    result = analyze_opcode_layouts(image, missing)
    assert not result.proof_ready
    assert any("evidence" in row for row in result.unresolved)
    reordered = SimpleNamespace(instructions=tuple(reversed(cfg.instructions)))
    result = analyze_opcode_layouts(image, reordered)
    assert not result.proof_ready
    assert "evidence-address-order-differs" in result.unresolved


def test_altered_evidence_byte_blocks():
    image, cfg = _exact_inputs()
    altered = _mutate_va(image, 0x004CE1E7, b"\x90")
    result = analyze_opcode_layouts(altered, cfg, expected_sha256=altered.sha256)
    assert not result.proof_ready
    assert any("allocator-rewrite" in row for row in result.unresolved)


def test_expected_digest_override_cannot_bless_a_nonretail_compiler_identity():
    image, cfg = _exact_inputs()
    nonretail = replace(image, sha256="0" * 64)

    result = analyze_opcode_layouts(
        nonretail,
        cfg,
        _closed_values(),
        expected_sha256=nonretail.sha256,
    )

    assert not result.proof_ready
    assert any("retail-compiler-sha256" in row for row in result.unresolved)


def test_missing_final_opcode_row_blocks():
    image, cfg = _exact_inputs()
    table_offset = image.va_to_offset(OPCODE_METADATA_TABLE)
    assert table_offset is not None
    truncated = replace(
        image,
        data=image.data[: table_offset + 467 * OPCODE_METADATA_ROW_SIZE],
    )
    with pytest.raises(ValueError, match="read is not wholly mapped"):
        analyze_opcode_layouts(truncated, cfg)


def test_duplicate_mnemonic_blocks():
    image, cfg = _exact_inputs()
    first_pointer = image.read(OPCODE_METADATA_TABLE, 4)
    altered = _mutate_va(image, OPCODE_METADATA_TABLE + OPCODE_METADATA_ROW_SIZE, first_pointer)
    inventory = analyze_opcode_layouts(altered, cfg)
    assert "duplicate-mnemonic:1:B" in inventory.unresolved
    assert not inventory.proof_ready


def test_reordered_or_gapped_metadata_row_blocks():
    image, cfg = _exact_inputs()
    row0 = image.read(OPCODE_METADATA_TABLE, OPCODE_METADATA_ROW_SIZE)
    row1 = image.read(
        OPCODE_METADATA_TABLE + OPCODE_METADATA_ROW_SIZE,
        OPCODE_METADATA_ROW_SIZE,
    )
    swapped = _mutate_va(image, OPCODE_METADATA_TABLE, row1 + row0)
    inventory = analyze_opcode_layouts(swapped, cfg)
    assert not inventory.proof_ready
    assert "opcode-table-endpoints-differ" in inventory.unresolved

    mnemonic_pointer = struct.unpack("<I", row0[:4])[0]
    gapped = _mutate_va(image, mnemonic_pointer, b"\0")
    inventory = analyze_opcode_layouts(gapped, cfg)
    assert not inventory.proof_ready
    assert "empty-mnemonic:0" in inventory.unresolved


def test_unknown_format_code_blocks():
    image, cfg = _exact_inputs()
    format_pointer = struct.unpack("<I", image.read(OPCODE_METADATA_TABLE + 4, 4))[0]
    altered = _mutate_va(image, format_pointer, b"q")
    inventory = analyze_opcode_layouts(altered, cfg)
    assert "opcode 0 has non-generic format code 'q'" in inventory.unresolved
    assert not inventory.proof_ready


def test_custom_format_or_variadic_marker_gap_blocks():
    image, cfg = _exact_inputs()
    custom_format_pointer = struct.unpack("<I", image.read(OPCODE_METADATA_TABLE + 3 * 16 + 4, 4))[0]
    altered = _mutate_va(image, custom_format_pointer, b"i")
    inventory = analyze_opcode_layouts(altered, cfg)
    assert "custom-format-differs:3:i" in inventory.unresolved

    variadic_format_pointer = struct.unpack("<I", image.read(OPCODE_METADATA_TABLE + 1 * 16 + 4, 4))[0]
    altered = _mutate_va(image, variadic_format_pointer, b"m")
    inventory = analyze_opcode_layouts(altered, cfg)
    assert "variadic-marker-missing:1" in inventory.unresolved
