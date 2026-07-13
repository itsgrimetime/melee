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
from retro_pe_fixture import (  # noqa: E402
    write_synthetic_cfg_pe,
    write_synthetic_dispatch_pe,
)
from tools.mwcc_retro import pe  # noqa: E402
from tools.mwcc_retro.x86_cfg import (  # noqa: E402
    AnalysisLimitError,
    AnalysisLimits,
    AuditAnchor,
    CfgRecoveryError,
    DirectCall,
    JumpTable,
    _RelocationEntryCandidate,
    _select_relocation_entry_candidates,
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


def load_dispatch_image(tmp_path, *, entry_count=2, mode="absolute-jump"):
    path = write_synthetic_dispatch_pe(
        tmp_path, entry_count=entry_count, mode=mode
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pe.load(path, expected_sha256=digest, require_pe32_i386=True)


def dispatch_cfg(tmp_path, *, entry_count=2, mode="absolute-jump"):
    image = load_dispatch_image(
        tmp_path, entry_count=entry_count, mode=mode
    )
    return recover_cfg(
        image, build_seed_inventory(image, ()), generous_limits(image)
    )


def test_guarded_absolute_jump_table_records_complete_provenance(tmp_path):
    cfg = dispatch_cfg(tmp_path)
    table = cfg.jump_table_at(0x0040100B)
    assert isinstance(table, JumpTable)
    assert (
        table.guard_address,
        table.guard_operator,
        table.guard_bound,
        table.base,
        table.entry_width,
        table.index_min,
        table.index_max,
    ) == (0x00401000, "ja", 1, 0x00402200, 4, 0, 1)
    assert table.raw_entries == (0x00401020, 0x00401060)
    assert table.targets == (0x00401020, 0x00401060)
    assert {row.category for row in cfg.seed_inventory.records} >= {
        "jump-table-entry"
    }
    assert not [
        row
        for row in cfg.ownership_diagnostics
        if row.address == table.address and row.kind == "indirect-flow"
    ]


def test_guarded_base_plus_index_jump_table_is_recovered(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="base-index-jump")
    table = cfg.jump_table_at(0x00401010)
    assert table.base == 0x00402200
    assert table.targets == (0x00401020, 0x00401060)


def test_relocated_dispatch_after_owned_return_proves_aligned_entry(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="unowned-relocated-dispatch")
    table = cfg.jump_table_at(0x0040103B)
    assert table.targets == (0x00401020, 0x00401060)
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-computed-transfer"
    )
    assert record.address == 0x00401030
    assert record.provenance_address == 0x0040103E
    assert "zero-alignment=0x40102f-0x401030" in record.detail


def test_relocated_dispatch_allows_fallthrough_calls_in_function_prefix(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="unowned-called-function-dispatch")
    table = cfg.jump_table_at(0x00401040)
    assert table.targets == (0x00401020, 0x00401060)
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-computed-transfer"
    )
    assert record.address == 0x00401030
    assert record.provenance_address == 0x00401043
    assert any(call.address == 0x00401030 for call in cfg.direct_calls)


def test_relocated_dispatch_after_owned_terminal_jump_proves_entry(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="unowned-terminal-jump-dispatch")
    table = cfg.jump_table_at(0x0040103B)
    assert table.targets == (0x00401020, 0x00401060)
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-computed-transfer"
    )
    assert record.address == 0x00401030
    assert "zero-alignment=0x401030-0x401030" in record.detail
    assert "owned-terminal=0x40102b:jmp" in record.detail


def test_relocated_internal_dispatch_proves_branched_aligned_function(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="unowned-branched-function-dispatch")
    table = cfg.jump_table_at(0x00401081)
    assert table.targets == (0x00401020, 0x004010A0)
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-computed-transfer"
    )
    assert record.address == 0x00401040
    assert record.provenance_address == 0x00401084
    assert "zero-alignment=0x401037-0x401040" in record.detail


def test_relocated_dispatch_accepts_distant_explicit_post_return_rejoin(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="unowned-long-guard-branch-dispatch")
    table = cfg.jump_table_at(0x00401070)
    assert table.targets == (0x00401020, 0x004010A0)
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-computed-transfer"
    )
    assert record.address == 0x00401030
    assert record.provenance_address == 0x00401073
    assert any(
        edge.source == 0x00401032
        and edge.target == 0x00401040
        and edge.kind == "conditional-branch"
        for edge in cfg.edges
    )


def test_relocation_discovery_is_independent_of_relocation_order(tmp_path):
    image = load_dispatch_image(tmp_path, mode="two-unowned-relocations")
    reversed_image = replace(image, relocations=tuple(reversed(image.relocations)))
    original = recover_cfg(
        image, build_seed_inventory(image, ()), generous_limits(image)
    )
    reversed_cfg = recover_cfg(
        reversed_image,
        build_seed_inventory(reversed_image, ()),
        generous_limits(reversed_image),
    )
    assert original.to_dict() == reversed_cfg.to_dict()
    assert {
        (row.category, row.address)
        for row in original.seed_inventory.records
        if row.category.startswith("relocation-")
    } >= {
        ("relocation-computed-transfer", 0x00401030),
        ("relocation-aligned-entry", 0x004010B0),
    }


def test_zero_aligned_entry_allows_control_flow_before_relocation(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="aligned-branched-relocation")
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-aligned-entry"
    )
    assert record.address == 0x004010B0
    assert record.provenance_address == 0x004010BD
    assert "zero-alignment=0x4010ab-0x4010b0" in record.detail
    instructions = {row.address: row for row in cfg.instructions}
    assert instructions[0x004010B1].mnemonic == "call"
    assert instructions[0x004010B8].mnemonic == "jne"
    assert instructions[0x004010BC].mnemonic == "mov"


def test_relocation_inside_terminal_inline_data_seeds_aligned_successor(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="relocation-inline-data")
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-inline-data-successor"
    )
    assert record.address == 0x00401050
    assert record.provenance_address == 0x00401040
    assert "terminal-inline-data=0x401033-0x401050" in record.detail
    assert "printable-prefix=28" in record.detail
    assert "trailing-control-bytes=1" in record.detail
    assert any(
        row.start == 0x00401033 and row.end == 0x00401050
        for row in cfg.data_regions
    )
    instructions = {row.address: row for row in cfg.instructions}
    assert instructions[0x00401050].mnemonic == "call"


def test_zero_gap_inside_self_lea_is_not_an_aligned_entry(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="self-lea-zero-suffix")
    aligned_entries = {
        row.address
        for row in cfg.seed_inventory.records
        if row.category == "relocation-aligned-entry"
    }
    assert 0x00401030 in aligned_entries
    assert 0x00401040 not in aligned_entries
    instructions = {row.address: row for row in cfg.instructions}
    assert instructions[0x0040103A].mnemonic == "lea"
    assert instructions[0x00401040].mnemonic == "and"
    assert not any(
        row.start < 0x00401040 and 0x0040103A < row.end
        for row in cfg.data_regions
    )


def test_self_lea_after_return_is_valid_dispatch_padding(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="self-lea-padding-dispatch")
    table = cfg.jump_table_at(0x0040103B)
    assert table.targets == (0x00401020, 0x00401060)
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-computed-transfer"
    )
    assert record.address == 0x00401030
    assert "zero-alignment=0x40102a-0x401030" in record.detail
    assert any(
        row.start == 0x0040102A and row.end == 0x00401030
        for row in cfg.data_regions
    )


def test_owned_computed_transfer_still_discovers_unowned_prologue(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="owned-dispatch-interior")
    table = cfg.jump_table_at(0x00401041)
    assert table.targets == (0x00401020, 0x00401060)
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-computed-transfer"
    )
    assert record.address == 0x00401030
    assert record.provenance_address == 0x00401044
    assert DirectCall(address=0x00401031, target=0x00401020) in set(
        cfg.direct_calls
    )
    raw_call = next(
        row for row in cfg.raw_e8_candidates if row.address == 0x00401031
    )
    assert raw_call.classification == "owned-call"


def test_owned_relocation_operand_still_discovers_unowned_prologue(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="owned-relocation-interior")
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-aligned-entry"
    )
    assert record.address == 0x00401030
    assert record.provenance_address == 0x00401036
    instructions = {row.address: row for row in cfg.instructions}
    assert instructions[0x00401030].mnemonic == "xor"
    assert instructions[0x00401032].mnemonic == "xor"
    assert instructions[0x00401034].mnemonic == "cmp"


def _entry_candidate(
    relocation_va: int, entry: int, span_end: int
) -> _RelocationEntryCandidate:
    return _RelocationEntryCandidate(
        relocation_va=relocation_va,
        category="relocation-computed-transfer",
        entry=entry,
        gap_start=entry - 4,
        evidence_address=span_end - 2,
        evidence_bytes="ffe0",
        boundary_evidence=f"zero-alignment={entry - 4:#x}-{entry:#x}",
        span_end=span_end,
    )


def test_relocation_candidate_selection_is_canonical_and_order_independent():
    candidates = (
        _entry_candidate(0x401010, 0x401100, 0x401200),
        _entry_candidate(0x401010, 0x401300, 0x401400),
        _entry_candidate(0x401020, 0x401180, 0x401280),
    )
    expected = _select_relocation_entry_candidates(candidates)
    observed = _select_relocation_entry_candidates(tuple(reversed(candidates)))
    assert expected == observed
    assert tuple(row.entry for row in expected) == (0x401300, 0x401180)


def test_relocation_candidate_overlap_conflict_fails_closed():
    candidates = (
        _entry_candidate(0x401010, 0x401100, 0x401200),
        _entry_candidate(0x401020, 0x401180, 0x401280),
    )
    with pytest.raises(CfgRecoveryError, match="overlap conflict"):
        _select_relocation_entry_candidates(candidates)


def test_relocation_candidate_prefers_outer_proof_over_internal_branch_entry():
    outer = replace(
        _entry_candidate(0x401010, 0x401100, 0x401200),
        internal_branch_targets=(0x401180,),
    )
    internal = _entry_candidate(0x401010, 0x401180, 0x401200)
    assert _select_relocation_entry_candidates((internal, outer)) == (outer,)


def test_guarded_callback_table_adds_finite_function_seeds(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="callback-table")
    table = cfg.jump_table_at(0x0040100B)
    assert table.flow_kind == "call"
    assert {(edge.target, edge.kind) for edge in cfg.edges if edge.source == table.address} >= {
        (0x00401020, "indirect-call-table"),
        (0x00401060, "indirect-call-table"),
    }
    callback_seeds = [
        row
        for row in cfg.seed_inventory.records
        if row.category == "callback-table-entry"
    ]
    assert {row.address for row in callback_seeds} == {
        0x00401020,
        0x00401060,
    }


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("missing-guard", "finite dominating guard"),
        ("conflicting-width", "entry width conflicts"),
        ("unmapped-entry", "jump-table entry is not wholly mapped"),
        ("target-outside-text", "jump-table target is not executable"),
    ],
)
def test_computed_table_failures_remain_explicit_blockers(
    tmp_path, mode, message
):
    image = load_dispatch_image(tmp_path, mode=mode)
    cfg = recover_cfg(
        image, build_seed_inventory(image, ()), generous_limits(image)
    )
    assert any(
        row.kind == "computed-flow-blocker" and message in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_guarded_468_way_dispatch_is_recovered(tmp_path):
    cfg = dispatch_cfg(tmp_path, entry_count=468)
    table = cfg.jump_table_at(0x0040100B)
    assert table.index_min == 0
    assert table.index_max == 467
    assert len(table.raw_entries) == 468
    assert len(table.targets) == 468
    assert table.base == 0x00402200


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


def test_interior_e8_crossing_owned_instructions_is_explained(tmp_path):
    image = load_cfg_image(tmp_path, "interior_e8_crosses_owned_instructions")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    row = next(
        row for row in cfg.raw_e8_candidates if row.address == 0x00401071
    )
    assert row.target == 0x00401076
    assert row.classification == "owned-instruction-bytes"
    instructions = {row.address: row for row in cfg.instructions}
    assert instructions[0x00401070].mnemonic == "add"
    assert instructions[0x00401072].mnemonic == "add"
    assert instructions[0x00401074].mnemonic == "add"


def test_interior_e8_crossing_proven_zero_function_alignment_is_explained(
    tmp_path,
):
    image = load_cfg_image(
        tmp_path, "interior_e8_crosses_zero_function_alignment"
    )
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    row = next(
        row for row in cfg.raw_e8_candidates if row.address == 0x00401071
    )
    assert row.target == 0x00401139
    assert row.classification == "owned-instruction-and-data"
    assert any(
        region.start == 0x00401073
        and region.end == 0x00401080
        and "terminal-zero-alignment" in region.provenance
        for region in cfg.data_regions
    )


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


def test_retail_mwcc_nop_encodings_are_owned_as_padding(tmp_path):
    image = load_cfg_image(tmp_path, "mwcc_padding_encodings")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert any(
        region.start == 0x00401061 and region.end == 0x00401070
        for region in cfg.padding_regions
    )


def test_closed_unreachable_island_after_owned_terminal_is_recovered(tmp_path):
    image = load_cfg_image(tmp_path, "closed_unreachable_island")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "closed-executable-island"
    )
    assert record.address == 0x00401061
    assert record.provenance_address == 0x00401060
    assert any(
        edge.source == 0x00401063
        and edge.target == 0x00401070
        and edge.kind == "unconditional-branch"
        for edge in cfg.edges
    )


def test_closed_unreferenced_aligned_function_after_zero_prefix_is_recovered(
    tmp_path,
):
    image = load_cfg_image(tmp_path, "closed_unreferenced_aligned_function")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "closed-aligned-function"
    )
    assert record.address == 0x00401030
    assert record.provenance_address == 0x0040102A
    assert any(
        region.start == 0x0040102B and region.end == 0x00401030
        for region in cfg.data_regions
    )
    assert any(
        edge.source == 0x00401033
        and edge.target == 0x00401038
        and edge.kind == "conditional-branch"
        for edge in cfg.edges
    )


def test_closed_aligned_function_may_merge_into_owned_right_boundary(tmp_path):
    image = load_cfg_image(tmp_path, "closed_aligned_function_owned_merge")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "closed-aligned-function"
    )
    assert record.address == 0x00401030
    assert "closed-terminal=0x401040:owned-merge" in record.detail


def test_one_byte_terminal_separator_that_cannot_decode_is_data(
    synthetic_cfg_image,
):
    text = synthetic_cfg_image.sections[0]
    data = bytearray(synthetic_cfg_image.data)
    data[text.raw_offset : text.raw_offset + 4] = bytes.fromhex("eb 01 14 c3")
    tiny_section = replace(text, raw_size=4, virt_size=4)
    image = replace(
        synthetic_cfg_image,
        data=bytes(data),
        entrypoint=text.va,
        sections=(tiny_section, *synthetic_cfg_image.sections[1:]),
        exports=(),
        relocations=(),
        executable_ranges=((text.va, text.va + 4),),
    )
    cfg = recover_cfg(image, (text.va,), generous_limits(image))
    assert any(
        region.start == text.va + 2
        and region.end == text.va + 3
        and "terminal-noninstruction-separator" in region.provenance
        for region in cfg.data_regions
    )


def test_pure_zero_fill_after_terminal_owns_executable_raw_tail(
    synthetic_cfg_image,
):
    text = synthetic_cfg_image.sections[0]
    data = bytearray(synthetic_cfg_image.data)
    data[text.raw_offset : text.raw_offset + 0x10] = b"\xc3" + b"\0" * 15
    tail_section = replace(text, raw_size=0x10, virt_size=0x10)
    image = replace(
        synthetic_cfg_image,
        data=bytes(data),
        entrypoint=text.va,
        sections=(tail_section, *synthetic_cfg_image.sections[1:]),
        exports=(),
        relocations=(),
        executable_ranges=((text.va, text.va + 0x10),),
    )
    cfg = recover_cfg(image, (text.va,), generous_limits(image))
    assert any(
        region.start == text.va + 1 and region.end == text.va + 0x10
        for region in cfg.padding_regions
    )


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


def test_executable_relocation_proves_aligned_branch_free_prologue(tmp_path):
    image = load_cfg_image(tmp_path, "exec_relocation_aligned_prologue")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    record = next(
        row
        for row in cfg.seed_inventory.records
        if row.category == "relocation-aligned-entry"
    )
    assert record.address == 0x00401030
    assert record.provenance_address == 0x00401035
    assert "zero-alignment=0x40102b-0x401030" in record.detail
    instructions = {row.address: row for row in cfg.instructions}
    assert instructions[0x00401030].mnemonic == "push"
    assert instructions[0x00401033].mnemonic == "mov"


def test_executable_relocation_rejects_return_before_relocation(tmp_path):
    image = load_cfg_image(tmp_path, "exec_relocation_branched_prologue")
    with pytest.raises(CfgRecoveryError, match="relocation.*boundary"):
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


def test_shrd_implicit_cl_read_preserves_initializer_taint(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "bb 50 10 40 00 0f ad fb 89 1d 90 20 40 00 c3",
    )
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
    (
        "encoded",
        "instruction_id",
        "mnemonic",
        "operand_registers",
        "operand_access",
        "register_reads",
        "register_writes",
    ),
    [
        ("d9 c1", 331, "fld", ("st(1)",), (1,), (), ("fpsw",)),
        (
            "d9 c9",
            1494,
            "fxch",
            ("st(0)", "st(1)"),
            (1, 0),
            (),
            ("fpsw",),
        ),
        ("dd d1", 713, "fst", ("st(1)",), (1,), (), ("fpsw",)),
        ("dd d9", 714, "fstp", ("st(1)",), (2,), (), ("fpsw",)),
        ("d8 c1", 15, "fadd", ("st(1)",), (1,), (), ()),
        ("de c1", 15, "faddp", ("st(1)",), (1,), (), ()),
    ],
)
def test_audited_capstone_hidden_x87_stack_metadata_contract(
    encoded,
    instruction_id,
    mnemonic,
    operand_registers,
    operand_access,
    register_reads,
    register_writes,
):
    decoder, decoded = decode_one(encoded)
    assert decoded.id == instruction_id
    assert decoded.mnemonic == mnemonic
    assert tuple(decoder.reg_name(op.reg) for op in decoded.operands) == (
        operand_registers
    )
    assert tuple(op.access for op in decoded.operands) == operand_access
    assert tuple(decoder.reg_name(reg) for reg in decoded.regs_read) == (
        register_reads
    )
    assert tuple(decoder.reg_name(reg) for reg in decoded.regs_write) == (
        register_writes
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


def test_wide_cmpxchg_failure_arm_preserves_accumulator_taint(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f c7 0f a3 90 20 40 00 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize("instruction", ["87 c0", "0f c1 c0"])
def test_aliased_exchange_outputs_retain_old_accumulator_taint(
    tmp_path, instruction
):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 {instruction} a3 90 20 40 00 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_cmpxchg_destination_aliasing_accumulator_uses_source_value(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 31 db 0f b1 d8 a3 90 20 40 00 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Source aliases the accumulator: either architectural arm can retain it.
        "b8 50 10 40 00 31 db 0f b1 c3 a3 90 20 40 00 c3",
        # Source aliases the destination: the destination remains unchanged.
        "bb 50 10 40 00 31 c0 0f b1 db 89 1d 90 20 40 00 c3",
        # The high-byte source partially aliases the implicit AL accumulator.
        "b8 50 10 40 00 31 db 0f b0 e3 89 1d 90 20 40 00 c3",
    ],
)
def test_cmpxchg_source_destination_and_partial_aliases_join_taint(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize("fld", ["d9 c1", "66 d9 c1", "2e d9 c1"])
def test_fld_register_pushes_hidden_x87_stack_value(tmp_path, fld):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 0f 6e c8 {fld} dd 19 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # FXCH moves the tainted ST(1) value to the memory-visible top.
        "b8 50 10 40 00 0f 6e c8 d9 c9 dd 19 c3",
        # FST copies ST(0) into ST(1) even though Capstone marks it read-only.
        "b8 50 10 40 00 0f 6e c0 dd d1 dd c0 d9 c9 dd 19 c3",
        # FLD shifts a tainted ST(1) to ST(2), then arithmetic consumes it.
        "b8 50 10 40 00 0f 6e c8 d9 e8 d8 c2 dd 19 c3",
        # FADDP writes its hidden destination before popping the x87 stack.
        "b8 50 10 40 00 0f 6e c0 d9 e8 de c1 dd 19 c3",
        # The implicit ST(0) arithmetic input is not reported as an operand.
        "b8 50 10 40 00 0f 6e c0 de c1 dd 19 c3",
    ],
)
def test_x87_swap_store_and_arithmetic_stack_forms_preserve_taint(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_clean_fstp_register_copy_and_pop_is_fully_modeled(tmp_path):
    image = load_cfg_program(tmp_path, "d9 e8 dd d9 dd 19 c3")
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # FLDENV changes control/TOP state but does not overwrite data registers.
        "b8 50 10 40 00 0f 6e c0 d9 21 0f 7e c0 a3 90 20 40 00 c3",
        # EMMS changes tags; the aliased MMX payload remains architecturally present.
        "b8 50 10 40 00 0f 6e c0 0f 77 0f 7e c0 a3 90 20 40 00 c3",
        # FFREE changes a tag; it does not erase the aliased physical payload.
        "b8 50 10 40 00 0f 6e c0 dd c0 0f 7e c0 a3 90 20 40 00 c3",
        # An x87 push into physical slot 7 cannot erase unrelated MM6.
        "b8 50 10 40 00 0f 6e f0 d9 e8 0f 7e f0 a3 90 20 40 00 c3",
    ],
)
def test_x87_stack_and_tag_updates_preserve_mmx_physical_alias_taint(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_fldenv_top_ambiguity_cannot_hide_physical_mmx_taint(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 d9 21 dd 19 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_tainted_x87_mutation_with_unknown_top_has_canonical_diagnostic(
    tmp_path,
):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 d9 21 d9 e8 c3",
    )
    with pytest.raises(
        CfgRecoveryError,
        match=(
            r"address=0x401014;bytes=d9e8;id=330;mnemonic=fld1;"
            r"operands=;reason=ambiguous x87 TOP with tainted physical "
            r"payload: effect=push;top-mask=0xff;valid-must=0x00;"
            r"valid-may=0xff"
        ),
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_fst_logical_destination_does_not_clear_unrelated_physical_mmx(
    tmp_path,
):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 0f 77 d9 e8 dd d1 "
        "0f 7e c8 89 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_clean_fld1_fstp_does_not_store_stale_physical_mmx_payload(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 0f 77 d9 e8 dd 19 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_ffree_empty_logical_value_does_not_erase_physical_mmx_payload(
    tmp_path,
):
    clean_logical_store = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 dd c0 d9 e8 dd 19 c3",
    )
    recover_cfg(
        clean_logical_store,
        inventory(clean_logical_store),
        generous_limits(clean_logical_store),
    )

    physical_read = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 dd c0 d9 e8 dd 19 "
        "0f 7e c0 89 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(
            physical_read,
            inventory(physical_read),
            generous_limits(physical_read),
        )


@pytest.mark.parametrize("restore", ["dd 21", "0f ae 09"])
def test_fresh_x87_state_restore_clears_physical_payload_taint(
    tmp_path, restore
):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 0f 6e c0 {restore} dd 19 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_fxrstor_replaces_low_xmm_lanes_but_not_upper_vector_lanes(tmp_path):
    restored_xmm = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 66 0f 6e c0 0f ae 09 0f 11 02 c3",
    )
    recover_cfg(
        restored_xmm,
        inventory(restored_xmm),
        generous_limits(restored_xmm),
    )

    retained_upper_ymm = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 62 f2 7d 28 7c c0 0f ae 09 c5 fc 11 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(
            retained_upper_ymm,
            inventory(retained_upper_ymm),
            generous_limits(retained_upper_ymm),
        )


@pytest.mark.parametrize("restore", ["dd 21", "0f ae 29"])
def test_other_state_restores_do_not_overclear_vector_state(tmp_path, restore):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 66 0f 6e c0 {restore} 0f 11 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_full_mmx_replacement_overwrites_aliased_x87_sign_exponent(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 d8 c0 0f ef c0 0f ae 01 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_full_mmx_replacement_propagates_tainted_low_payload(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 d8 c0 0f 6e c0 0f ae 01 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_x87_state_save_sinks_stale_physical_payload_after_emms(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 0f 77 dd 31 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_fldenv_with_clean_physical_state_keeps_logical_stores_clean(tmp_path):
    image = load_cfg_program(tmp_path, "d9 21 d9 e8 dd 19 c3")
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # One predecessor increments TOP, so ST(0) can resolve physical MM1.
        "b8 50 10 40 00 0f 6e c8 85 c0 74 02 d9 f7 dd 19 c3",
        # One predecessor empties tags while the other keeps MM0 valid.
        "b8 50 10 40 00 0f 6e c0 85 c0 74 02 0f 77 dd 19 c3",
    ],
)
def test_cfg_join_unions_top_and_may_tags_for_relevant_taint(
    tmp_path, program
):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_cfg_join_with_differing_clean_top_and_tags_is_not_a_pointer_blocker(
    tmp_path,
):
    image = load_cfg_program(
        tmp_path,
        "31 c0 85 c0 74 02 d9 f7 d9 e8 dd 19 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_call_retains_physical_taint_and_invalidates_logical_control(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 e8 04 00 00 00 dd 19 c3 90 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_finit_resets_top_and_tags_but_retains_physical_payload(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 db e3 d9 e8 dd 19 "
        "0f 7e c0 89 02 c3",
    )
    with pytest.raises(
        CfgRecoveryError, match="unresolved function-pointer initializer"
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_unknown_hidden_x87_stack_form_blocks_only_relevant_taint(tmp_path):
    tainted = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 d9 f8 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unmodeled x87 stack effect"):
        recover_cfg(tainted, inventory(tainted), generous_limits(tainted))

    clean = load_cfg_program(tmp_path, "d9 f8 c3")
    recover_cfg(clean, inventory(clean), generous_limits(clean))


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
    assert high_water["max_states_per_block"] == 8
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
