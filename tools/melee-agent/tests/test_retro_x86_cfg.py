import hashlib
import json
import sys
from dataclasses import fields, replace
from pathlib import Path

import capstone
import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))
from retro_pe_fixture import write_synthetic_cfg_pe  # noqa: E402
from tools.mwcc_retro import pe  # noqa: E402
from tools.mwcc_retro.x86_cfg import (  # noqa: E402
    AnalysisLimitError,
    AnalysisLimits,
    AuditAnchor,
    CfgRecoveryError,
    build_seed_inventory,
    recover_cfg,
    write_jsonl_atomic,
)


@pytest.fixture
def synthetic_cfg_image(tmp_path):
    return load_cfg_image(tmp_path)


def load_cfg_image(tmp_path, mutation=None):
    path = write_synthetic_cfg_pe(tmp_path, mutation=mutation)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pe.load(
        path,
        expected_sha256=digest,
        require_pe32_i386=True,
    )


def load_cfg_program(tmp_path, program_hex):
    path = write_synthetic_cfg_pe(tmp_path)
    data = bytearray(path.read_bytes())
    program = bytes.fromhex(program_hex)
    assert len(program) <= 0x16
    data[0x20A:0x220] = b"\x90" * 0x16
    data[0x20A : 0x20A + len(program)] = program
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    return pe.load(path, expected_sha256=digest, require_pe32_i386=True)


def decode_one(encoded):
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    return decoder, next(
        decoder.disasm(bytes.fromhex(encoded), 0x00401000, count=1)
    )


def audit_anchor(image, address=0x00401070):
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoded = next(decoder.disasm(image.read(address, 15), address, count=1))
    return AuditAnchor(
        name="synthetic-audit-anchor",
        address=address,
        instruction_bytes=bytes(decoded.bytes),
        evidence="synthetic-fixture",
    )


def inventory(image):
    return build_seed_inventory(image, (audit_anchor(image),))


def generous_limits(image):
    defaults = AnalysisLimits.for_image(image)
    return replace(
        defaults,
        max_instructions=512,
        max_blocks=512,
        max_edges=4096,
        max_functions=512,
        max_finite_targets=512,
        max_finite_values=512,
    )


def test_structural_default_limits_derive_from_executable_raw_bytes(
    synthetic_cfg_image,
):
    limits = AnalysisLimits.for_image(synthetic_cfg_image)
    assert limits.max_instructions == 0x88
    assert limits.max_blocks == 0x88
    assert limits.max_edges == 8 * 0x88
    assert limits.max_jump_tables == 65_536
    assert limits.max_jump_table_entries == 524_288
    assert limits.max_functions == 65_536
    assert limits.max_finite_targets == 65_536
    assert limits.max_finite_values == 8_192
    assert limits.max_states_per_block == 256
    assert limits.max_contexts_per_entry == 256
    assert limits.max_scc_iterations == 65_536
    assert limits.max_summary_iterations == 65_536
    assert limits.max_fixpoint_updates == 8_000_000


@pytest.mark.parametrize(
    "cap_name",
    [field.name for field in fields(AnalysisLimits)],
)
@pytest.mark.parametrize("delta", [0, 1], ids=["equal", "over"])
def test_every_analysis_cap_fails_closed_at_equality_and_over(
    synthetic_cfg_image, cap_name, delta
):
    limits = generous_limits(synthetic_cfg_image)
    configured = getattr(limits, cap_name)
    with pytest.raises(AnalysisLimitError) as raised:
        limits.check(cap_name, configured + delta)
    assert raised.value.limit_name == cap_name
    assert raised.value.configured == configured
    assert raised.value.observed == configured + delta
    assert f"configured={configured}" in str(raised.value)
    assert f"observed={configured + delta}" in str(raised.value)


def test_seed_inventory_records_every_production_category_and_bytes(
    synthetic_cfg_image,
):
    seeds = inventory(synthetic_cfg_image)
    cfg = recover_cfg(
        synthetic_cfg_image, seeds, generous_limits(synthetic_cfg_image)
    )
    categories = {row.category for row in cfg.seed_inventory.records}
    assert {
        "entrypoint",
        "export",
        "relocation-executable-pointer",
        "audit-anchor",
        "function-pointer-initializer",
        "direct-call-target",
        "direct-branch-target",
    } <= categories
    assert all(row.provenance_bytes for row in cfg.seed_inventory.records)
    relocation = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-executable-pointer"
    )
    assert relocation.address == 0x00401060
    assert relocation.provenance_address == 0x00402080
    assert relocation.provenance_bytes == "60104000"
    assert relocation.detail == "i386-relocation-type-3;width=4"
    initializer_rows = [
        row
        for row in cfg.seed_inventory.records
        if row.category == "function-pointer-initializer"
    ]
    assert {(row.address, row.provenance_address) for row in initializer_rows} == {
        (0x00401050, 0x00401011),
        (0x0040107D, 0x00401020),
    }
    assert all(row.provenance_bytes for row in initializer_rows)


def test_seed_order_cannot_change_raw_cfg(synthetic_cfg_image):
    limits = generous_limits(synthetic_cfg_image)
    a = recover_cfg(
        synthetic_cfg_image,
        (0x00401000, 0x00401040, 0x00401070),
        limits,
    )
    b = recover_cfg(
        synthetic_cfg_image,
        (0x00401070, 0x00401040, 0x00401000),
        limits,
    )
    assert a.to_dict() == b.to_dict()


def test_direct_cfg_owns_exact_instructions_blocks_edges_and_calls(
    synthetic_cfg_image,
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    assert (0x00401003, 0x00401040) in {
        (call.address, call.target) for call in cfg.direct_calls
    }
    assert (0x0040104B, 0x00401060) in {
        (call.address, call.target) for call in cfg.direct_calls
    }
    assert any(
        edge.source == 0x00401008
        and edge.target == 0x00401020
        and edge.kind == "conditional-branch"
        for edge in cfg.edges
    )
    call_block = next(block for block in cfg.blocks if block.start == 0x00401000)
    assert call_block.end == 0x00401008
    assert call_block.instruction_addresses == (
        0x00401000,
        0x00401001,
        0x00401003,
    )
    assert all(
        len(bytes.fromhex(instruction.bytes_hex)) == instruction.size
        for instruction in cfg.instructions
    )
    unresolved_indirects = [
        row for row in cfg.ownership_diagnostics if row.kind == "indirect-flow"
    ]
    assert len(unresolved_indirects) == 1
    assert unresolved_indirects[0].address == 0x0040107D


def test_embedded_e8_is_explained_as_data_not_call(synthetic_cfg_image):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    row = next(
        row for row in cfg.raw_e8_candidates if row.address == 0x00401080
    )
    assert row.target == 0x00401060
    assert row.classification == "owned-data"
    data = next(
        row
        for row in cfg.data_regions
        if row.start == 0x00401080 and row.end == 0x00401088
    )
    assert data.provenance


def test_partial_five_byte_e8_data_containment_is_unresolved(tmp_path):
    image = load_cfg_image(tmp_path, "partial_e8_data_reference")
    with pytest.raises(CfgRecoveryError, match="raw E8 candidate is unresolved"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_canonical_padding_is_owned_but_zero_gap_is_unexplained(
    synthetic_cfg_image, tmp_path
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    assert any(
        region.start <= 0x00401030 < region.end
        for region in cfg.padding_regions
    )

    image = load_cfg_image(tmp_path, "unexplained_zero_gap")
    with pytest.raises(CfgRecoveryError, match="unexplained executable bytes"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_unsupported_cross_block_initializer_fails_closed(tmp_path):
    image = load_cfg_image(tmp_path, "unsupported_cross_block_initializer")
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_unsupported_indexed_initializer_fails_closed(tmp_path):
    image = load_cfg_image(tmp_path, "unsupported_indexed_initializer")
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_instruction_interior_and_unmapped_seeds_fail_closed(
    synthetic_cfg_image,
):
    limits = generous_limits(synthetic_cfg_image)
    with pytest.raises(CfgRecoveryError, match="instruction interior"):
        recover_cfg(
            synthetic_cfg_image,
            (0x00401003, 0x00401004),
            limits,
        )
    with pytest.raises(CfgRecoveryError, match="not executable"):
        recover_cfg(synthetic_cfg_image, (0x00409999,), limits)


def test_relocation_targeting_instruction_interior_fails_closed(tmp_path):
    image = load_cfg_image(tmp_path, "relocation_to_instruction_interior")
    with pytest.raises(CfgRecoveryError, match="instruction interior"):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    ("mutation", "target", "predecessor"),
    [
        ("late_backward_target", 0x00401001, 0x00401000),
        ("late_target_inside_owned_block", 0x00401046, 0x00401040),
    ],
)
def test_late_target_split_retains_predecessor_fallthrough(
    tmp_path, mutation, target, predecessor
):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert any(block.start == target for block in cfg.blocks)
    assert any(
        edge.source == predecessor
        and edge.target == target
        and edge.kind == "fallthrough"
        for edge in cfg.edges
    )


@pytest.mark.parametrize(
    ("mutation", "forbidden_start"),
    [
        ("lea_is_not_data", 0x00401068),
        ("write_is_not_data", 0x00401068),
        ("control_operand_is_not_data", 0x004020A0),
    ],
)
def test_only_semantic_memory_reads_produce_data_evidence(
    tmp_path, mutation, forbidden_start
):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert not any(
        region.start <= forbidden_start < region.end
        for region in cfg.data_regions
    )


def test_data_evidence_cannot_overlap_instruction_or_padding(tmp_path):
    image = load_cfg_image(tmp_path, "data_overlaps_instruction")
    with pytest.raises(CfgRecoveryError, match="ownership overlap"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_partial_width_relocation_does_not_prove_executable_pointer(tmp_path):
    image = load_cfg_image(tmp_path, "partial_relocation_pointer")
    seeds = inventory(image)
    assert not any(
        row.category == "relocation-executable-pointer"
        for row in seeds.records
    )


def test_executable_highlow_exact_immediate_field_seeds_with_provenance(
    tmp_path,
):
    image = load_cfg_image(tmp_path, "exec_relocation_immediate")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    relocation = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-executable-pointer"
        and row.provenance_address == 0x0040100B
    )
    assert relocation.address == 0x00401050
    assert relocation.provenance_bytes == "50104000"
    assert "width=4" in relocation.detail
    assert not any(
        region.start < 0x0040100F and 0x0040100B < region.end
        for region in cfg.data_regions
    )


def test_executable_relocation_crossing_operand_boundary_fails(tmp_path):
    image = load_cfg_image(tmp_path, "exec_relocation_partial_field")
    with pytest.raises(CfgRecoveryError, match="relocation.*boundary"):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "exec_relocation_data_slot",
        "exec_relocation_data_slot_consistent_refs",
    ],
)
def test_executable_highlow_data_slot_always_seeds_with_provenance(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    relocation_rows = [
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-executable-pointer"
        and row.provenance_address == 0x00401080
    ]
    assert len(relocation_rows) == 1
    assert relocation_rows[0].address == 0x00401060
    assert relocation_rows[0].provenance_bytes == "60104000"
    assert "data-boundary=0x401080-0x401088" in relocation_rows[0].detail


def test_executable_highlow_conflicting_data_boundaries_fail_closed(tmp_path):
    image = load_cfg_image(
        tmp_path, "exec_relocation_data_slot_conflicting_refs"
    )
    with pytest.raises(
        CfgRecoveryError, match="data boundary is ambiguous.*attributions=2"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation", ["transformed_initializer", "cross_block_initializer_value"]
)
def test_executable_initializer_taint_never_silently_disappears(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "partial_initializer_store",
        "xchg_initializer_store",
        "push_initializer_value",
        "stos_initializer_value",
    ],
)
def test_unsupported_memory_write_of_executable_value_fails_closed(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "full_load_clobbers_initializer_value",
        "zeroing_clobbers_initializer_value",
        "call_clobbers_caller_saved_initializer_value",
    ],
)
def test_full_independent_write_or_call_clobber_kills_initializer_taint(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert not any(
        row.category == "function-pointer-initializer"
        and 0x0040100A <= row.provenance_address < 0x00401020
        for row in cfg.seed_inventory.records
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "partial_clobber_retains_initializer_taint",
        "call_preserves_callee_saved_initializer_taint",
    ],
)
def test_partial_write_and_callee_saved_call_retain_unsafe_taint(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "cross_register_lea_initializer",
        "register_xchg_initializer",
        "partial_register_copy_initializer",
        "cmov_initializer",
        "arithmetic_cross_register_initializer",
        "vector_register_initializer",
    ],
)
def test_register_transform_retains_unsafe_initializer_taint(
    tmp_path, mutation
):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_capstone_semantic_contract_is_pinned_before_recovery(
    synthetic_cfg_image, monkeypatch
):
    monkeypatch.setattr(capstone, "__version__", "5.0.7-audited-drift")
    with pytest.raises(CfgRecoveryError, match="Capstone audit contract"):
        recover_cfg(
            synthetic_cfg_image,
            inventory(synthetic_cfg_image),
            generous_limits(synthetic_cfg_image),
        )


@pytest.mark.parametrize(
    ("encoded", "instruction_id", "operand_access", "register_reads"),
    [
        ("0f f7 c1", 376, (1, 1), ("edi",)),
        ("66 0f f7 c1", 359, (1, 1), ("edi",)),
        ("c5 f9 f7 c1", 1004, (1, 1), ("edi",)),
        ("0f ae 01", 212, (2,), ()),
        ("dd 31", 204, (2,), ()),
        ("dd 19", 714, (1,), ()),
        ("0f ae 21", 1511, (2,), ("rdx", "rax")),
        ("0f 38 f6 08", 1485, (0, 0), ()),
        ("66 0f 38 f5 08", 1487, (0, 0), ()),
        ("0f 7e 00", 377, (1, 1), ()),
        ("0f 11 00", 495, (1, 1), ()),
        ("c5 fc 11 00", 1051, (1, 1), ()),
        ("c4 e2 75 2e 00", 1006, (1, 1, 1), ()),
        ("c4 e2 75 8e 00", 1230, (1, 1, 1), ()),
        ("62 f2 7d 49 a2 04 88", 1440, (1, 1, 0), ()),
        ("62 f2 7d 49 a0 04 88", 1317, (1, 1, 0), ()),
    ],
)
def test_audited_capstone_writer_metadata_contract(
    encoded, instruction_id, operand_access, register_reads
):
    decoder, decoded = decode_one(encoded)
    assert decoded.id == instruction_id
    assert tuple(operand.access for operand in decoded.operands) == operand_access
    assert tuple(decoder.reg_name(reg) for reg in decoded.regs_read) == (
        register_reads
    )


@pytest.mark.parametrize(
    "program",
    [
        # A tainted base is an address, not the loaded payload.
        "bb 50 10 40 00 81 c3 00 10 00 00 8b 03 a3 90 20 40 00 c3",
        # A tainted store address does not taint a clean payload.
        "bb 50 10 40 00 31 c0 89 03 c3",
        # STOS consumes EAX, not its EDI destination address.
        "bf 50 10 40 00 31 c0 ab c3",
        # MOVS copies a fresh memory value; ESI is only its source address.
        "be 50 10 40 00 81 c6 00 10 00 00 a5 c3",
        # LODS loads a fresh value even when its source address is tainted.
        "be 50 10 40 00 81 c6 00 10 00 00 ad a3 90 20 40 00 c3",
        # XCHG moves the clean old EAX into EBX positionally.
        "bb 50 10 40 00 31 c0 87 d8 89 1d 90 20 40 00 c3",
        # MASKMOVQ's mask operand is not the stored payload.
        "b8 50 10 40 00 0f 6e c8 0f f7 c1 c3",
        # VMASKMOVDQU's mask operand is not the stored payload.
        "b8 50 10 40 00 66 0f 6e c8 c5 f9 f7 c1 c3",
        # Masked stores do not store their mask register.
        "b8 50 10 40 00 66 0f 6e c8 c4 e2 75 2e 01 c3",
        "b8 50 10 40 00 66 0f 6e c8 c4 e2 75 8e 01 c3",
        # Scatter index registers are addresses, not payload.
        "b8 50 10 40 00 66 0f 6e c8 62 f2 7d 49 a2 04 89 c3",
        # INS consumes DX as a port selector, not a stored payload.
        "ba 50 10 40 00 6d c3",
        # MOVDIR64B consumes EAX as a destination address.
        "b8 50 10 40 00 66 0f 38 f8 00 c3",
        # OUTS targets an I/O port and gather only reads memory.
        "be 50 10 40 00 6f c3",
        "b8 50 10 40 00 66 0f 6e c8 c4 e2 6d 90 04 89 c3",
    ],
)
def test_address_mask_and_protocol_dependencies_are_not_payloads(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Implicit MASKMOV destinations.
        "b8 50 10 40 00 0f 6e c0 0f f7 c1 c3",
        "b8 50 10 40 00 66 0f 6e c0 66 0f f7 c1 c3",
        "b8 50 10 40 00 66 0f 6e c0 c5 f9 f7 c1 c3",
        # ENTER pushes the old EBP value.
        "bd 50 10 40 00 c8 00 00 00 c3",
        # State saves contain hidden MMX/x87/vector payloads.
        "b8 50 10 40 00 0f 6e c0 dd 31 c3",
        "b8 50 10 40 00 0f 6e c0 dd 19 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f ae 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f ae 21 c3",
        # CET stores have access=0 for both operands.
        "b9 50 10 40 00 31 c0 0f 38 f6 08 c3",
        "b9 50 10 40 00 31 c0 66 0f 38 f5 08 c3",
        # Representative legacy and VEX access-metadata defects.
        "b8 50 10 40 00 0f 6e c0 0f 7e 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f 11 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 c5 fc 11 01 c3",
        # Masked and scatter stores consume operand 2, not their masks/VSIB.
        "b8 50 10 40 00 66 0f 6e c0 c4 e2 75 2e 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 c4 e2 75 8e 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 62 f2 7d 49 a2 04 89 c3",
        "b8 50 10 40 00 66 0f 6e c0 62 f2 7d 49 a0 04 89 c3",
    ],
)
def test_semantic_memory_writers_reject_only_tainted_payload(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Full GPR/vector loads replace every written lane.
        "b8 50 10 40 00 8b 01 a3 90 20 40 00 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f 10 01 0f 11 01 c3",
        # Vector zero idiom clears the full destination.
        "b8 50 10 40 00 66 0f 6e c0 66 0f ef c0 0f 11 01 c3",
        # A VEX XMM write also clears the upper YMM alias lanes.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 c5 f8 10 01 "
        "c5 fc 11 01 c3",
        # FXSAVE stores XMM state, not the untouched upper YMM lanes.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 66 0f ef c0 0f ae 01 c3",
        # Register XADD places the clean old destination in its source.
        "bb 50 10 40 00 31 c0 0f c1 d8 89 1d 90 20 40 00 c3",
        # POP replaces the full destination with a fresh stack value.
        "b8 50 10 40 00 58 a3 90 20 40 00 c3",
        # A state-save address by itself is not saved payload.
        "b9 50 10 40 00 dd 31 c3",
    ],
)
def test_full_lane_replacements_and_address_only_state_are_clean(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Partial GPR/vector loads preserve untouched tainted lanes.
        "b8 50 10 40 00 8a 01 a3 90 20 40 00 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f 12 01 0f 11 01 c3",
        # A legacy XMM write preserves upper YMM lanes.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 0f 10 01 "
        "c5 fc 11 01 c3",
        # CMOV can preserve its old destination.
        "b8 50 10 40 00 31 db 85 c9 0f 45 c3 a3 90 20 40 00 c3",
        # PUSH immediate, PUSHA, and PUSHF store their real payloads.
        "68 50 10 40 00 c3",
        "bb 50 10 40 00 60 c3",
        "b8 50 10 40 00 83 c0 00 9c c3",
        # XADD/CMPXCHG memory forms conditionally store the source value.
        "b8 50 10 40 00 0f c1 01 c3",
        "b9 50 10 40 00 0f b1 0b c3",
        # XSAVE can store upper YMM/ZMM state selected at runtime.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 66 0f ef c0 0f ae 21 c3",
    ],
)
def test_partial_conditional_and_stack_payloads_remain_tainted(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_unhandled_ambiguous_form_fails_with_detailed_diagnostic(tmp_path):
    image = load_cfg_program(tmp_path, "0f b1 d8 c3")  # CMPXCHG EAX, EBX
    with pytest.raises(CfgRecoveryError) as raised:
        recover_cfg(image, inventory(image), generous_limits(image))
    diagnostic = str(raised.value)
    assert "ambiguous x86 value-flow semantics" in diagnostic
    assert "address=0x40100a" in diagnostic
    assert "bytes=0fb1d8" in diagnostic
    assert "id=" in diagnostic
    assert "mnemonic=cmpxchg" in diagnostic
    assert "overlapping CMPXCHG" in diagnostic


def test_entry_export_and_anchor_bind_to_complete_first_instruction(
    synthetic_cfg_image,
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    export = next(
        row for row in cfg.seed_inventory.records if row.category == "export"
    )
    assert export.provenance_bytes == "dd0580104000"

    prefix_anchor = AuditAnchor(
        name="prefix-anchor",
        address=0x00401001,
        instruction_bytes=synthetic_cfg_image.read(0x00401001, 1),
        evidence="synthetic-fixture",
    )
    with pytest.raises(CfgRecoveryError, match="complete instruction"):
        recover_cfg(
            synthetic_cfg_image,
            build_seed_inventory(synthetic_cfg_image, (prefix_anchor,)),
            generous_limits(synthetic_cfg_image),
        )


@pytest.mark.parametrize(
    "cap_name",
    [
        "max_instructions",
        "max_blocks",
        "max_edges",
        "max_functions",
        "max_finite_targets",
        "max_finite_values",
        "max_states_per_block",
        "max_fixpoint_updates",
    ],
)
def test_recover_cfg_enforces_every_task3_production_cap(
    synthetic_cfg_image, cap_name
):
    limits = replace(generous_limits(synthetic_cfg_image), **{cap_name: 1})
    with pytest.raises(AnalysisLimitError) as raised:
        recover_cfg(synthetic_cfg_image, inventory(synthetic_cfg_image), limits)
    assert raised.value.limit_name == cap_name
    assert raised.value.configured == 1
    assert raised.value.observed >= 1


def test_high_water_marks_cover_all_caps_and_zero_only_deferred_dimensions(
    synthetic_cfg_image,
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    high_water = {
        row.limit_name: row.observed for row in cfg.high_water_marks
    }
    assert set(high_water) == {
        field.name for field in fields(AnalysisLimits)
    }
    assert high_water["max_finite_values"] > 0
    assert high_water["max_states_per_block"] > 0
    assert high_water["max_fixpoint_updates"] > 0
    for deferred in (
        "max_jump_tables",
        "max_jump_table_entries",
        "max_contexts_per_entry",
        "max_scc_iterations",
        "max_summary_iterations",
    ):
        assert high_water[deferred] == 0


@pytest.mark.parametrize(
    "cap_name",
    [
        "max_jump_tables",
        "max_jump_table_entries",
        "max_contexts_per_entry",
        "max_scc_iterations",
        "max_summary_iterations",
    ],
)
def test_recover_cfg_rejects_zero_cap_for_unobserved_dimension(
    synthetic_cfg_image, cap_name
):
    limits = replace(generous_limits(synthetic_cfg_image), **{cap_name: 0})
    with pytest.raises(AnalysisLimitError) as raised:
        recover_cfg(synthetic_cfg_image, inventory(synthetic_cfg_image), limits)
    assert raised.value.limit_name == cap_name
    assert raised.value.configured == 0
    assert raised.value.observed == 0


@pytest.mark.parametrize("mutation", ["far_call", "far_jump"])
def test_far_control_transfer_is_unresolved_not_direct(tmp_path, mutation):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert not any(call.address == 0x00401070 for call in cfg.direct_calls)
    assert not any(
        edge.source == 0x00401070
        and edge.kind in {
            "direct-call",
            "conditional-branch",
            "unconditional-branch",
        }
        for edge in cfg.edges
    )
    assert any(
        row.address == 0x00401070 and row.kind == "unsupported-far-flow"
        for row in cfg.ownership_diagnostics
    )


def test_decode_lookahead_is_bounded_by_executable_raw_tail(
    synthetic_cfg_image,
):
    text = synthetic_cfg_image.sections[0]
    tail_address = text.va + text.raw_size - 1
    raw_tail = text.raw_offset + text.raw_size - 1
    data = bytearray(synthetic_cfg_image.data)
    data[raw_tail] = 0xC3
    tail_section = replace(
        text,
        va=tail_address,
        raw_offset=raw_tail,
        raw_size=1,
        virt_size=0x10,
    )
    tail_image = replace(
        synthetic_cfg_image,
        data=bytes(data),
        entrypoint=tail_address,
        sections=(tail_section, *synthetic_cfg_image.sections[1:]),
        exports=(),
        relocations=(),
        executable_ranges=((tail_address, tail_address + 0x10),),
    )
    cfg = recover_cfg(tail_image, (tail_address,), generous_limits(tail_image))
    assert [(row.address, row.size) for row in cfg.instructions] == [
        (tail_address, 1)
    ]


def test_padding_gap_is_partitioned_around_proven_data(tmp_path):
    image = load_cfg_image(tmp_path, "padding_partitioned_by_data")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert any(
        region.start == 0x00401068 and region.end == 0x0040106C
        for region in cfg.data_regions
    )
    assert any(
        region.start == 0x00401061 and region.end == 0x00401068
        for region in cfg.padding_regions
    )
    assert any(
        region.start == 0x0040106C and region.end == 0x00401070
        for region in cfg.padding_regions
    )


def test_audit_anchor_requires_exact_instruction_byte_provenance(
    synthetic_cfg_image,
):
    anchor = AuditAnchor(
        name="bad-anchor",
        address=0x00401070,
        instruction_bytes=b"\x90",
        evidence="synthetic-fixture",
    )
    with pytest.raises(CfgRecoveryError, match="audit anchor bytes differ"):
        build_seed_inventory(synthetic_cfg_image, (anchor,))


def test_atomic_jsonl_is_canonical_and_has_final_newline(
    synthetic_cfg_image, tmp_path
):
    limits = generous_limits(synthetic_cfg_image)
    a = recover_cfg(
        synthetic_cfg_image,
        (0x00401000, 0x00401040, 0x00401070),
        limits,
    )
    b = recover_cfg(
        synthetic_cfg_image,
        (0x00401070, 0x00401040, 0x00401000),
        limits,
    )
    path = tmp_path / "cfg.jsonl"
    write_jsonl_atomic(path, a)
    first = path.read_bytes()
    write_jsonl_atomic(path, b)
    assert path.read_bytes() == first
    assert first.endswith(b"\n")
    rows = [json.loads(line) for line in first.splitlines()]
    keys = [
        (row["address"], row["record_kind"], row.get("target", -1))
        for row in rows
    ]
    assert keys == sorted(keys)
    rendered = first.decode("utf-8")
    assert "elapsed" not in rendered
    assert "timestamp" not in rendered
    assert str(tmp_path) not in rendered
