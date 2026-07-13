import hashlib
import json
import sys
from dataclasses import fields, replace
from pathlib import Path

import pytest

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


def audit_anchor(image, address=0x00401070):
    return AuditAnchor(
        name="synthetic-audit-anchor",
        address=address,
        instruction_bytes=image.read(address, 1),
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
    assert relocation.detail == "i386-relocation-type-3"
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
