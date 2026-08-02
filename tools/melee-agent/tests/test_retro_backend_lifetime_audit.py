import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))

from retro_pe_fixture import write_synthetic_dispatch_pe  # noqa: E402
from tools.mwcc_retro import backend_lifetime_audit as audit  # noqa: E402
from tools.mwcc_retro import pe  # noqa: E402
from tools.mwcc_retro.backend_lifetime_audit import (  # noqa: E402
    GhidraInventoryError,
    _build_range_contains,
    _instruction_reaches,
    compare_ghidra_inventory,
    load_ghidra_inventory,
    write_crosscheck_atomic,
)
from tools.mwcc_retro.x86_cfg import (  # noqa: E402
    AnalysisLimits,
    ExecutableResidueInterval,
    OwnershipDiagnostic,
    RawE8Candidate,
    RelocationDisposition,
    TerminalExternalEdge,
    UnreachableExecutableResidue,
    UnresolvedControlTarget,
    _PublicationProvisionalExecutableSource,
    _PublicationReferenceReconciliationObligation,
    _PublicationReferenceRow,
    build_seed_inventory,
    canonical_jsonl_bytes,
    recover_cfg,
)


def raw_cfg(tmp_path):
    path = write_synthetic_dispatch_pe(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    image = pe.load(path, expected_sha256=digest, require_pe32_i386=True)
    return recover_cfg(image, (image.entrypoint,), AnalysisLimits.for_image(image))


def test_instruction_reachability_includes_implicit_basic_block_fallthrough(
    tmp_path,
):
    cfg = raw_cfg(tmp_path)
    assert _instruction_reaches(cfg, 0x00401000, 0x00401005)


def test_range_membership_index_handles_boundaries_gaps_and_overlaps():
    contains = _build_range_contains(((0x20, 0x30), (0x10, 0x25), (0x40, 0x40)))
    assert contains(0x10)
    assert contains(0x2F)
    assert contains(0x30)
    assert not contains(0x31)
    assert contains(0x40)


def test_historical_control_rows_are_exhaustively_classified_not_seeded(
    tmp_path,
):
    cfg = raw_cfg(tmp_path)
    finite = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.flow_kind.startswith("indirect-")
    )
    terminal_address = 0x00401081
    blocker_address = 0x00401082
    cfg = replace(
        cfg,
        control_targets=replace(
            cfg.control_targets,
            terminal_external_edges=(
                TerminalExternalEdge(
                    source=terminal_address,
                    flow_kind="indirect-call-import",
                    iat_va=0x00402080,
                    dll="KERNEL32.dll",
                    name="ExitProcess",
                    ordinal=None,
                    provenance="fixture",
                ),
            ),
            unresolved=(
                UnresolvedControlTarget(
                    address=blocker_address,
                    kind="indirect-flow",
                    detail="fixture blocker",
                ),
            ),
        ),
    )
    historical = [
        {"address": finite.source, "kind": "old", "detail": "finite"},
        {"address": terminal_address, "kind": "old", "detail": "import"},
        {"address": blocker_address, "kind": "old", "detail": "blocked"},
        {"address": 0x00401083, "kind": "old", "detail": "deleted"},
    ]
    manifest = audit.classify_historical_control_diagnostics(
        cfg, historical, expected_count=4
    )
    assert [row.classification for row in manifest.rows] == [
        "resolved-internal",
        "terminal-external",
        "current-blocker",
        "deleted-unsound-or-unreachable",
    ]
    assert len(manifest.canonical_sha256) == 64
    assert cfg.seed_inventory == raw_cfg(tmp_path).seed_inventory


def test_historical_control_classifier_rejects_count_and_duplicate_rows(
    tmp_path,
):
    cfg = raw_cfg(tmp_path)
    row = {"address": 1, "kind": "old", "detail": "same"}
    with pytest.raises(GhidraInventoryError, match="count differs"):
        audit.classify_historical_control_diagnostics(
            cfg, [row], expected_count=2
        )
    with pytest.raises(GhidraInventoryError, match="duplicate"):
        audit.classify_historical_control_diagnostics(cfg, [row, row])


def write_inventory(
    path,
    cfg,
    *,
    own_dispatch=True,
    corrupt_bytes=False,
    extra_call=False,
    extra_rows=(),
    compiler_sha256="a" * 64,
):
    rows = [
        {
            "record_kind": "metadata",
            "schema_version": "mwcc-ghidra-raw-crosscheck.v1",
            "compiler_sha256": compiler_sha256,
        },
        {
            "record_kind": "function",
            "address": 0x00401000 if own_dispatch else 0x00401020,
            "name": "dispatch" if own_dispatch else "target",
        },
        {
            "record_kind": "function-body-range",
            "address": 0x00401000 if own_dispatch else 0x00401020,
            "function_entry": 0x00401000 if own_dispatch else 0x00401020,
            "end": 0x0040101F if own_dispatch else 0x00401020,
        },
    ]
    for instruction in cfg.instructions:
        bytes_hex = instruction.bytes_hex
        if corrupt_bytes and instruction.address == 0x00401000:
            bytes_hex = "90" * instruction.size
        rows.append(
            {
                "record_kind": "instruction",
                "address": instruction.address,
                "size": instruction.size,
                "bytes_hex": bytes_hex,
            }
        )
    if extra_call:
        rows.append(
            {
                "record_kind": "call",
                "address": 0x00401000,
                "target": 0x00441F20,
                "computed": False,
            }
        )
    rows.extend(extra_rows)
    rows.sort(
        key=lambda row: (
            -1 if row["record_kind"] == "metadata" else row["address"],
            row["record_kind"],
            json.dumps(row, sort_keys=True, separators=(",", ":")),
        )
    )
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def test_missing_ghidra_owner_is_delta_not_raw_failure(tmp_path):
    cfg = raw_cfg(tmp_path)
    path = tmp_path / "inventory.jsonl"
    write_inventory(path, cfg, own_dispatch=False)
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    assert 0x00401000 in report.raw_only_functions
    assert report.ownership_mismatches
    assert not report.unresolved_raw_addresses
    assert not report.byte_mismatches


def test_retained_body_counts_use_occurrences_and_union_only_on_union_side(tmp_path):
    cfg = raw_cfg(tmp_path)
    path = tmp_path / "inventory.jsonl"
    write_inventory(path, cfg, extra_call=True)
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    assertions = {
        row.name: row for row in report.retained_regression_assertions
    }
    functions = assertions["ghidra-functions-and-direct-calls-in-bodies"]
    arena = assertions[
        "raw-ghidra-union-arena-calls-vs-ghidra-bodies"
    ]
    assert functions.ghidra_body_count == 0
    assert arena.raw_or_union_count == 1
    assert arena.ghidra_body_count == 0


def test_retained_whole_pe_counts_use_classified_raw_e8_candidates(tmp_path):
    cfg = replace(
        raw_cfg(tmp_path),
        direct_calls=(),
        raw_e8_candidates=(
            RawE8Candidate(
                0x00401100,
                0x00441F20,
                "unreachable-executable-residue",
            ),
            RawE8Candidate(
                0x00401110,
                0x0049CF90,
                "unreachable-executable-residue",
            ),
            RawE8Candidate(
                0x00401120,
                0x0049D010,
                "unreachable-executable-residue",
            ),
        ),
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(path, cfg)
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    assertions = {
        row.name: row for row in report.retained_regression_assertions
    }

    assert assertions[
        "raw-ghidra-union-arena-calls-vs-ghidra-bodies"
    ].raw_or_union_count == 1
    assert assertions[
        "raw-selected-pcode-helper-calls-vs-ghidra-bodies"
    ].raw_or_union_count == 2
    assert assertions[
        "raw-unlink-helper-calls-vs-ghidra-bodies"
    ].raw_or_union_count == 1


def test_retained_occurrences_preserve_overlap_and_stop_before_disjoint_body(
    tmp_path,
):
    cfg = raw_cfg(tmp_path)
    path = tmp_path / "inventory.jsonl"
    arena_target = 0x00441F20
    disjoint_target = 0x0049CF90
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": "function",
                "address": 0x00401002,
                "name": "overlap",
            },
            {
                "record_kind": "function-body-range",
                "address": 0x00401002,
                "function_entry": 0x00401002,
                "end": 0x0040101F,
            },
            {
                "record_kind": "function-body-range",
                "address": 0x00401030,
                "function_entry": 0x00401000,
                "end": 0x0040103F,
            },
            {
                "record_kind": "call",
                "address": 0x00401005,
                "target": arena_target,
                "computed": False,
            },
            {
                "record_kind": "call",
                "address": 0x00401030,
                "target": disjoint_target,
                "computed": False,
            },
            {
                "record_kind": "retained-body-call",
                "address": 0x00401005,
                "function_entry": 0x00401000,
                "target": arena_target,
                "computed": False,
            },
            {
                "record_kind": "retained-body-call",
                "address": 0x00401005,
                "function_entry": 0x00401002,
                "target": arena_target,
                "computed": False,
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    assert len(inventory.calls) == 2
    assert [row.address for row in inventory.retained_body_calls] == [
        0x00401005,
        0x00401005,
    ]

    report = compare_ghidra_inventory(cfg, inventory)
    assertions = {
        row.name: row for row in report.retained_regression_assertions
    }
    functions = assertions["ghidra-functions-and-direct-calls-in-bodies"]
    arena = assertions[
        "raw-ghidra-union-arena-calls-vs-ghidra-bodies"
    ]
    assert (functions.raw_or_union_count, functions.ghidra_body_count) == (2, 2)
    assert arena.ghidra_body_count == 2


def test_ghidra_byte_conflict_is_blocking_without_erasing_raw_fact(tmp_path):
    cfg = raw_cfg(tmp_path)
    path = tmp_path / "inventory.jsonl"
    write_inventory(path, cfg, corrupt_bytes=True)
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    assert report.byte_mismatches[0].address == 0x00401000
    with pytest.raises(GhidraInventoryError, match="raw decode conflict"):
        report.require_no_raw_decode_conflicts()
    assert cfg.instructions[0].bytes_hex != ""


def test_every_current_raw_control_blocker_prevents_publication(tmp_path):
    cfg = raw_cfg(tmp_path)
    cfg = replace(
        cfg,
        ownership_diagnostics=(
            *cfg.ownership_diagnostics,
            OwnershipDiagnostic(
                kind="indirect-flow",
                address=0x00401020,
                detail="unresolved indirect call: call eax",
            ),
        ),
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(path, cfg)
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    assert report.unresolved_raw_addresses == (0x00401020,)
    with pytest.raises(GhidraInventoryError, match="unresolved raw control"):
        report.require_publishable()


def test_invalidated_object_callback_table_prevents_publication(tmp_path):
    cfg = raw_cfg(tmp_path)
    cfg = replace(
        cfg,
        ownership_diagnostics=(
            *cfg.ownership_diagnostics,
            OwnershipDiagnostic(
                kind="object-callback-table-blocker",
                address=0x00401020,
                detail="late receiver write invalidated the hypothesis",
            ),
        ),
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(path, cfg)
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    assert report.unresolved_raw_addresses == (0x00401020,)
    with pytest.raises(GhidraInventoryError, match="unresolved raw control"):
        report.require_publishable()


def _with_fixture_residue(cfg, *, start=0x00401100, payload=b"\x90\xc3"):
    return replace(
        cfg,
        provisional_unreachable_residue=UnreachableExecutableResidue(
            intervals=(
                ExecutableResidueInterval(
                    start=start,
                    end=start + len(payload),
                    bytes_hex=payload.hex(),
                    bytes_sha256=hashlib.sha256(payload).hexdigest(),
                ),
            ),
            reachable_ownership_sha256="1" * 64,
            executable_partition_sha256="2" * 64,
        ),
    )


def _with_publication_reference_obligation(cfg):
    reference_start = 0x00401100
    publication_slot = 0x00403000
    payload = publication_slot.to_bytes(4, "little")
    cfg = _with_fixture_residue(
        cfg,
        start=reference_start,
        payload=payload,
    )
    source = _PublicationProvisionalExecutableSource(
        kind="provisional-unowned-executable",
        interval_start=reference_start,
        interval_end=reference_start + len(payload),
        bytes_sha256=hashlib.sha256(payload).hexdigest(),
        current_ownership_sha256="3" * 64,
    )
    reference = _PublicationReferenceRow(
        reference_start=reference_start,
        reference_end=reference_start + len(payload),
        bytes_hex=payload.hex(),
        relocation_type=3,
        reference_class="type-3-relocation",
        source=source,
        target_slot=publication_slot,
    )
    obligation = _PublicationReferenceReconciliationObligation(
        certificate_sha256="4" * 64,
        reference=reference,
        fixed_point_ownership_sha256=source.current_ownership_sha256,
    )
    return replace(
        cfg,
        publication_reference_obligations=(obligation,),
    ), obligation


def test_publication_reference_obligation_reconciles_exact_provisional_row(
    tmp_path,
):
    cfg, obligation = _with_publication_reference_obligation(
        raw_cfg(tmp_path)
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": "data-reference",
                "address": obligation.reference.reference_start,
                "target": obligation.reference.target_slot,
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)

    report = compare_ghidra_inventory(cfg, inventory)

    assert len(report.publication_reference_reconciliations) == 1
    assert report.publication_reference_reconciliations[0].status == "passed"
    assert report.publication_obligation_set_sha256 is not None
    report.require_publishable()
    accepted = audit.accept_reconciled_residue(cfg, report)
    assert accepted.provisional_unreachable_residue.accepted


def test_publication_reference_obligation_accepts_final_certificate_audit(
    tmp_path,
):
    from test_retro_x86_cfg import (
        generous_limits,
        return_path_publication_lifecycle_image,
    )

    fixture = return_path_publication_lifecycle_image(
        mutation="outside-residue-slot-reference"
    )
    cfg = recover_cfg(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        compiler_sha256=fixture.image.sha256,
        extra_rows=tuple(
            {
                "record_kind": "data-reference",
                "address": obligation.reference.reference_start,
                "target": obligation.reference.target_slot,
            }
            for obligation in cfg.publication_reference_obligations
        ),
    )
    inventory = load_ghidra_inventory(
        path,
        expected_sha256=fixture.image.sha256,
    )

    report = compare_ghidra_inventory(cfg, inventory)
    accepted = audit.accept_reconciled_residue(cfg, report)
    publication_rows = [
        json.loads(line)
        for line in canonical_jsonl_bytes(accepted).splitlines()
        if json.loads(line)["record_kind"]
        == "return-path-publication-noninterference"
    ]

    assert len(publication_rows) == 1
    assert publication_rows[0]["obligation_set_sha256"] == (
        report.publication_obligation_set_sha256
    )
    assert publication_rows[0]["external_reconciliation_sha256"] == (
        report.residue_reconciliation_sha256
    )


def test_definitive_publication_certificate_requires_exact_obligation_union(
    tmp_path,
):
    from test_retro_x86_cfg import (
        generous_limits,
        return_path_publication_lifecycle_image,
    )

    fixture = return_path_publication_lifecycle_image(
        mutation="outside-residue-slot-reference"
    )
    cfg = recover_cfg(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )
    missing = replace(cfg, publication_reference_obligations=())
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        missing,
        compiler_sha256=fixture.image.sha256,
    )
    inventory = load_ghidra_inventory(
        path,
        expected_sha256=fixture.image.sha256,
    )

    report = compare_ghidra_inventory(missing, inventory)

    assert any(
        row.status == "missing-obligation"
        for row in report.publication_reference_reconciliations
    )
    with pytest.raises(
        GhidraInventoryError,
        match="publication reference obligation",
    ):
        report.require_publishable()


@pytest.mark.parametrize(
    "mutation", ("missing", "extra", "overlapping-ownership")
)
def test_publication_reference_obligation_blocks_final_reconciliation_failure(
    tmp_path,
    mutation,
):
    cfg, obligation = _with_publication_reference_obligation(
        raw_cfg(tmp_path)
    )
    extra_rows = []
    if mutation == "overlapping-ownership":
        extra_rows.extend(
            (
                {
                    "record_kind": "function",
                    "address": obligation.reference.reference_start,
                    "name": "claimed_publication_reference",
                },
                {
                    "record_kind": "function-body-range",
                    "address": obligation.reference.reference_start,
                    "function_entry": obligation.reference.reference_start,
                    "end": obligation.reference.reference_end - 1,
                },
            )
        )
    if mutation != "missing":
        extra_rows.append(
            {
                "record_kind": "data-reference",
                "address": obligation.reference.reference_start,
                "target": obligation.reference.target_slot,
            }
        )
    if mutation == "extra":
        extra_rows.append(
            {
                "record_kind": "data-reference",
                "address": obligation.reference.reference_start + 1,
                "target": obligation.reference.target_slot,
            }
        )
    path = tmp_path / "inventory.jsonl"
    write_inventory(path, cfg, extra_rows=tuple(extra_rows))
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)

    report = compare_ghidra_inventory(cfg, inventory)

    assert any(
        row.status != "passed"
        for row in report.publication_reference_reconciliations
    )
    with pytest.raises(
        GhidraInventoryError,
        match="publication reference obligation|provisional residue",
    ):
        report.require_publishable()


def test_exact_decoded_residue_is_reported_and_reconciled(tmp_path):
    cfg = _with_fixture_residue(raw_cfg(tmp_path))
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": "function",
                "address": 0x00401100,
                "name": "unreachable_island",
            },
            {
                "record_kind": "function-body-range",
                "address": 0x00401100,
                "function_entry": 0x00401100,
                "end": 0x00401101,
            },
            {
                "record_kind": "instruction",
                "address": 0x00401100,
                "size": 1,
                "bytes_hex": "90",
            },
            {
                "record_kind": "instruction",
                "address": 0x00401101,
                "size": 1,
                "bytes_hex": "c3",
            },
            {
                "record_kind": "typed-flow",
                "address": 0x00401100,
                "target": 0x00401101,
                "flow_kind": "fallthrough",
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)

    assert not report.residue_conflicts
    assert {
        (row.address, row.fact_kind, row.classification)
        for row in report.residue_dispositions
    } >= {
        (0x00401100, "instruction", "closed-unreachable-exact-decode"),
        (0x00401100, "function", "closed-unreachable-exact-decode"),
        (0x00401100, "typed-flow", "closed-unreachable-exact-decode"),
    }
    assert not any(
        row.address == 0x00401100
        and row.flow_kind == "fallthrough"
        for row in report.flow_mismatches
    )
    assert report.residue_reconciliation_sha256 is not None
    report.require_publishable()


def test_residue_instruction_requires_exact_pe_bytes_and_decode(tmp_path):
    cfg = _with_fixture_residue(raw_cfg(tmp_path))
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": "instruction",
                "address": 0x00401100,
                "size": 1,
                "bytes_hex": "cc",
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)

    assert report.residue_conflicts == (
        audit.ResidueConflict(
            0x00401100,
            "instruction",
            "exact residue bytes differ: raw=90;ghidra=cc",
        ),
    )
    assert report.residue_reconciliation_sha256 is None


def test_incoming_ghidra_flow_to_residue_blocks_reconciliation(tmp_path):
    cfg = _with_fixture_residue(raw_cfg(tmp_path))
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": "instruction",
                "address": 0x00401100,
                "size": 1,
                "bytes_hex": "90",
            },
            {
                "record_kind": "typed-flow",
                "address": 0x00401000,
                "target": 0x00401100,
                "flow_kind": "unconditional-branch",
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)

    assert any(
        row.address == 0x00401000
        and row.fact_kind == "typed-flow"
        and row.detail == "incoming target=0x401100"
        for row in report.residue_conflicts
    )
    assert report.residue_reconciliation_sha256 is None


def test_ghidra_residue_label_without_exact_instruction_is_not_a_root(tmp_path):
    cfg = _with_fixture_residue(raw_cfg(tmp_path))
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": "function",
                "address": 0x00401100,
                "name": "label_only",
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)

    assert report.residue_conflicts == (
        audit.ResidueConflict(
            0x00401100,
            "function",
            "no exact independently decoded instruction boundary",
        ),
    )
    assert report.residue_reconciliation_sha256 is None


def test_exact_residue_instruction_reconciles_relocation_obligation(tmp_path):
    source = 0x00401101
    target = 0x00401100
    payload = b"\x68\x00\x11\x40\x00\xc3"
    cfg = _with_fixture_residue(
        raw_cfg(tmp_path), start=0x00401100, payload=payload
    )
    cfg = replace(
        cfg,
        ownership_diagnostics=(
            *cfg.ownership_diagnostics,
            OwnershipDiagnostic(
                "unresolved-relocation-obligation",
                source,
                "fixture residue relocation",
            ),
        ),
        control_targets=replace(
            cfg.control_targets,
            unresolved=(
                *cfg.control_targets.unresolved,
                UnresolvedControlTarget(
                    source,
                    "unresolved-relocation-obligation",
                    "fixture residue relocation",
                ),
            ),
        ),
        relocation_dispositions=(
            RelocationDisposition(
                source,
                target.to_bytes(4, "little").hex(),
                "residue",
                None,
                target,
                ".text",
                None,
                "unresolved-exec-pointer",
                "no-final-owner-or-typed-data-boundary",
            ),
        ),
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": "instruction",
                "address": 0x00401100,
                "size": 5,
                "bytes_hex": payload[:5].hex(),
            },
            {
                "record_kind": "instruction",
                "address": 0x00401105,
                "size": 1,
                "bytes_hex": "c3",
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)

    assert source not in report.unresolved_raw_addresses
    assert any(
        row.address == source
        and row.fact_kind == "relocation"
        and row.classification == "closed-unreachable-exact-decode"
        for row in report.residue_dispositions
    )
    report.require_publishable()
    accepted = audit.accept_reconciled_residue(cfg, report)
    assert not accepted.control_targets.unresolved
    assert not accepted.ownership_diagnostics
    assert accepted.relocation_dispositions[0].status == (
        "reconciled-unreachable-residue-code"
    )


def test_exact_retail_marker_reconciles_stale_relocation_without_decode(tmp_path):
    marker_start = 0x00506523
    marker = b"Hacked by Ninji 2023-07-15 $"
    source = 0x0050652F
    cfg = _with_fixture_residue(
        raw_cfg(tmp_path), start=marker_start, payload=marker
    )
    cfg = replace(
        cfg,
        ownership_diagnostics=(
            OwnershipDiagnostic(
                "unresolved-relocation-obligation",
                source,
                "fixture stale marker relocation",
            ),
        ),
        control_targets=replace(
            cfg.control_targets,
            unresolved=(
                UnresolvedControlTarget(
                    source,
                    "unresolved-relocation-obligation",
                    "fixture stale marker relocation",
                ),
            ),
        ),
        relocation_dispositions=(
            RelocationDisposition(
                source,
                marker[source - marker_start : source - marker_start + 4].hex(),
                "residue",
                None,
                0x20696A6E,
                None,
                None,
                "unmapped-anomaly",
                "no-final-owner-or-typed-data-boundary",
            ),
        ),
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        compiler_sha256=audit._RETAIL_SHA256,
    )
    inventory = load_ghidra_inventory(
        path, expected_sha256=audit._RETAIL_SHA256
    )
    report = compare_ghidra_inventory(cfg, inventory)

    assert source not in report.unresolved_raw_addresses
    assert any(
        row.address == source
        and row.fact_kind == "relocation"
        and row.classification == "exact-retail-noncode-marker"
        for row in report.residue_dispositions
    )
    accepted = audit.accept_reconciled_residue(cfg, report)
    assert accepted.relocation_dispositions[0].status == (
        "reconciled-retail-noncode-marker"
    )


def test_exact_retail_six_relocation_obligations_have_final_dispositions(
    tmp_path,
):
    code_relocations = (
        (0x00401D37, 0x00401A60),
        (0x00401D97, 0x00401A70),
        (0x00425B27, 0x00425B00),
        (0x004E0AE7, 0x004E0B20),
        (0x0050F5B3, 0x0050F5E0),
    )
    marker_start = 0x00506523
    marker_source = 0x0050652F
    marker = b"Hacked by Ninji 2023-07-15 $"
    base_cfg = raw_cfg(tmp_path)
    intervals = tuple(
        ExecutableResidueInterval(
            start=source - 1,
            end=source + 4,
            bytes_hex=(b"\x68" + target.to_bytes(4, "little")).hex(),
            bytes_sha256=hashlib.sha256(
                b"\x68" + target.to_bytes(4, "little")
            ).hexdigest(),
        )
        for source, target in code_relocations
    ) + (
        ExecutableResidueInterval(
            start=marker_start,
            end=marker_start + len(marker),
            bytes_hex=marker.hex(),
            bytes_sha256=hashlib.sha256(marker).hexdigest(),
        ),
    )
    obligations = (*code_relocations, (marker_source, 0x20696A6E))
    cfg = replace(
        base_cfg,
        provisional_unreachable_residue=UnreachableExecutableResidue(
            intervals=intervals,
            reachable_ownership_sha256="1" * 64,
            executable_partition_sha256="2" * 64,
        ),
        ownership_diagnostics=tuple(
            OwnershipDiagnostic(
                "unresolved-relocation-obligation",
                source,
                "exact retail relocation fixture",
            )
            for source, _ in obligations
        ),
        control_targets=replace(
            base_cfg.control_targets,
            unresolved=tuple(
                UnresolvedControlTarget(
                    source,
                    "unresolved-relocation-obligation",
                    "exact retail relocation fixture",
                )
                for source, _ in obligations
            ),
        ),
        relocation_dispositions=tuple(
            RelocationDisposition(
                source,
                (
                    marker[source - marker_start : source - marker_start + 4]
                    if source == marker_source
                    else target.to_bytes(4, "little")
                ).hex(),
                "residue",
                None,
                target,
                None if source == marker_source else ".text",
                None,
                (
                    "unmapped-anomaly"
                    if source == marker_source
                    else "unresolved-exec-pointer"
                ),
                "no-final-owner-or-typed-data-boundary",
            )
            for source, target in obligations
        ),
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        compiler_sha256=audit._RETAIL_SHA256,
        extra_rows=tuple(
            {
                "record_kind": "instruction",
                "address": source - 1,
                "size": 5,
                "bytes_hex": (b"\x68" + target.to_bytes(4, "little")).hex(),
            }
            for source, target in code_relocations
        ),
    )
    inventory = load_ghidra_inventory(
        path, expected_sha256=audit._RETAIL_SHA256
    )

    report = compare_ghidra_inventory(cfg, inventory)
    report.require_publishable()
    accepted = audit.accept_reconciled_residue(cfg, report)

    assert {
        row.address: row.classification
        for row in report.residue_dispositions
        if row.fact_kind == "relocation"
    } == {
        **{
            source: "closed-unreachable-exact-decode"
            for source, _ in code_relocations
        },
        marker_source: "exact-retail-noncode-marker",
    }
    assert {
        row.source_address: row.status
        for row in accepted.relocation_dispositions
    } == {
        **{
            source: "reconciled-unreachable-residue-code"
            for source, _ in code_relocations
        },
        marker_source: "reconciled-retail-noncode-marker",
    }
    assert not accepted.control_targets.unresolved
    assert not accepted.ownership_diagnostics


def test_mutated_retail_marker_does_not_reconcile_relocation(tmp_path):
    marker_start = 0x00506523
    marker = b"Hacked by Ninji 2023-07-15 !"
    source = 0x0050652F
    cfg = _with_fixture_residue(
        raw_cfg(tmp_path), start=marker_start, payload=marker
    )
    cfg = replace(
        cfg,
        ownership_diagnostics=(
            OwnershipDiagnostic(
                "unresolved-relocation-obligation",
                source,
                "fixture stale marker relocation",
            ),
        ),
        relocation_dispositions=(
            RelocationDisposition(
                source,
                marker[source - marker_start : source - marker_start + 4].hex(),
                "residue",
                None,
                0x20696A6E,
                None,
                None,
                "unmapped-anomaly",
                "no-final-owner-or-typed-data-boundary",
            ),
        ),
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        compiler_sha256=audit._RETAIL_SHA256,
    )
    inventory = load_ghidra_inventory(
        path, expected_sha256=audit._RETAIL_SHA256
    )
    report = compare_ghidra_inventory(cfg, inventory)

    assert source in report.unresolved_raw_addresses
    assert report.residue_reconciliation_sha256 is None


@pytest.mark.parametrize(
    "record_kind",
    (
        "computed-transfer",
        "data-reference",
        "function-pointer-reference",
    ),
)
def test_ghidra_only_shared_source_reference_is_semantic_blocker(
    tmp_path, record_kind
):
    cfg = raw_cfg(tmp_path)
    path = tmp_path / "inventory.jsonl"
    target = {
        "computed-transfer": 0,
        "data-reference": 0x00402200,
        "function-pointer-reference": 0x00401020,
    }[record_kind]
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": record_kind,
                "address": 0x00401000,
                "target": target,
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    assert any(
        row.address == 0x00401000
        and row.target == target
        and row.side == "ghidra-only"
        and row.flow_kind == record_kind
        for row in report.flow_mismatches
    )
    with pytest.raises(GhidraInventoryError, match="Ghidra-only"):
        report.require_publishable()


def test_crosscheck_compares_implicit_intra_block_fallthrough(tmp_path):
    cfg = raw_cfg(tmp_path)
    block = next(row for row in cfg.blocks if len(row.instruction_addresses) >= 2)
    source, target = block.instruction_addresses[:2]
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": "typed-flow",
                "address": source,
                "target": target,
                "flow_kind": "fallthrough",
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    assert not any(
        row.address == source
        and row.target == target
        and row.flow_kind == "fallthrough"
        for row in report.flow_mismatches
    )


def test_crosscheck_computed_transfer_is_a_source_marker(tmp_path):
    cfg = raw_cfg(tmp_path)
    finite = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.flow_kind.startswith("indirect-")
    )
    path = tmp_path / "inventory.jsonl"
    write_inventory(
        path,
        cfg,
        extra_rows=(
            {
                "record_kind": "computed-transfer",
                "address": finite.source,
                "target": 0,
            },
        ),
    )
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    assert not any(
        row.address == finite.source
        and row.flow_kind == "computed-transfer"
        for row in report.flow_mismatches
    )


def test_inventory_requires_exact_hash_numeric_order_and_canonical_digest(
    tmp_path,
):
    cfg = raw_cfg(tmp_path)
    path = tmp_path / "inventory.jsonl"
    write_inventory(path, cfg)
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    assert len(inventory.canonical_sha256) == 64
    with pytest.raises(GhidraInventoryError, match="compiler SHA-256 differs"):
        load_ghidra_inventory(path, expected_sha256="b" * 64)

    rows = path.read_text().splitlines()
    path.write_text("\n".join([rows[0], rows[-1], *rows[1:-1]]) + "\n")
    # Auto-sort should produce the same canonical digest
    inventory2 = load_ghidra_inventory(path, expected_sha256="a" * 64)
    assert inventory2.canonical_sha256 == inventory.canonical_sha256


def test_crosscheck_publication_binds_transient_inventory_digest(tmp_path):
    cfg = raw_cfg(tmp_path)
    path = tmp_path / "inventory.jsonl"
    write_inventory(path, cfg)
    inventory = load_ghidra_inventory(path, expected_sha256="a" * 64)
    report = compare_ghidra_inventory(cfg, inventory)
    output = tmp_path / "raw-ghidra-crosscheck.v1.json"
    write_crosscheck_atomic(output, report)
    payload = json.loads(output.read_text())
    assert payload["schema_version"] == "mwcc-retro-raw-ghidra-crosscheck.v1"
    assert payload["ghidra_inventory_sha256"] == inventory.canonical_sha256
    assert str(path) not in output.read_text()


def _static_members(tag):
    return {
        "raw-pe-cfg.v1.jsonl": f"cfg-{tag}\n".encode(),
        "raw-ghidra-crosscheck.v1.json": f"crosscheck-{tag}\n".encode(),
        "backend-map-candidates.json": f"candidates-{tag}\n".encode(),
    }


def test_static_bundle_publication_is_all_or_none_across_injected_failures(
    tmp_path,
):
    first = audit.publish_static_backend_bundle(
        tmp_path,
        _static_members("old"),
        compiler_sha256="a" * 64,
    )
    assert first.read_bytes("backend-map-candidates.json") == b"candidates-old\n"

    observed_events = []

    def enumerate_events(event):
        observed_events.append(event)

    audit.publish_static_backend_bundle(
        tmp_path,
        _static_members("probe"),
        compiler_sha256="a" * 64,
        failure_injector=enumerate_events,
    )

    for event in observed_events:
        audit.publish_static_backend_bundle(
            tmp_path,
            _static_members("old"),
            compiler_sha256="a" * 64,
        )

        def fail(selected):
            if selected == event:
                raise OSError(f"injected {event}")

        with pytest.raises(OSError, match="injected"):
            audit.publish_static_backend_bundle(
                tmp_path,
                _static_members("new"),
                compiler_sha256="a" * 64,
                failure_injector=fail,
            )
        resolved = audit.resolve_static_backend_bundle(tmp_path)
        assert resolved.read_bytes("backend-map-candidates.json") in {
            b"candidates-old\n",
            b"candidates-new\n",
        }
        payloads = {
            resolved.read_bytes(name).decode().split("-", 1)[1].strip()
            for name in _static_members("ignored")
        }
        assert len(payloads) == 1


def test_static_bundle_resolver_rejects_hash_symlink_and_hostile_current(
    tmp_path,
):
    bundle = audit.publish_static_backend_bundle(
        tmp_path,
        _static_members("safe"),
        compiler_sha256="a" * 64,
    )
    member = bundle.path("raw-pe-cfg.v1.jsonl")
    member.write_bytes(b"tampered\n")
    with pytest.raises(audit.StaticBundleError, match="member hash differs"):
        audit.resolve_static_backend_bundle(tmp_path)

    audit.publish_static_backend_bundle(
        tmp_path,
        _static_members("safe-2"),
        compiler_sha256="a" * 64,
    )
    current = tmp_path / "CURRENT"
    current.write_text(
        '{"schema_version":"mwcc-retro-static-current.v1",'
        '"generation":"../escape","manifest_sha256":"' + "0" * 64 + '"}\n'
    )
    with pytest.raises(audit.StaticBundleError, match="generation name"):
        audit.resolve_static_backend_bundle(tmp_path)

    current.unlink()
    current.symlink_to(tmp_path / "outside")
    with pytest.raises(audit.StaticBundleError, match="CURRENT.*regular"):
        audit.resolve_static_backend_bundle(tmp_path)


def test_java_exporter_rechecks_hash_and_exports_global_numeric_facts():
    source = (
        REPO / "tools/mwcc_debug/scripts/ExportMwccRawCrosscheck.java"
    ).read_text()
    for required in (
        "currentProgram.getExecutableSHA256()",
        "getListing().getInstructions(true)",
        "getFunctionManager().getFunctions(true)",
        "getAddressRanges(true)",
        "getInstructionAt(function.getEntryPoint())",
        "function.getBody().contains(retainedInstruction.getAddress())",
        "retainedInstruction = retainedInstruction.getNext()",
        "instruction.getReferencesFrom()",
        "currentProgram.getMemory().contains(reference.getToAddress())",
        "currentProgram.getMemory().getBlock(reference.getToAddress()).isExecute()",
        "getReferencesTo(function.getEntryPoint())",
        "StandardOpenOption.CREATE_NEW",
        '"computed-transfer"',
        '"typed-flow"',
        '"function-pointer-reference"',
        '"retained-body-call"',
    ):
        assert required in source


# ── Task 6: Lifetime site inventory RED tests ───────────────────────────


def test_build_lifetime_site_inventory_import():
    """LifetimeSiteInventory and audit entry points must be importable."""
    from tools.mwcc_retro.backend_lifetime_audit import (  # noqa: F401
        LifetimeSiteInventory,
        build_lifetime_site_inventory,
    )


def test_six_pcode_allocation_sites_are_proven_or_expanded(tmp_path):
    """The six known PCode allocation candidates must be classified."""
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
        MemoryWriteFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )
    from tools.mwcc_retro.x86_cfg import DirectCall

    pcode_sites = (
        0x004636DE,
        0x0046374D,
        0x00463770,
        0x0049D29A,
        0x0049D2AF,
        0x004A26CF,
    )
    objobject_site = 0x00402000
    other_site = 0x00402020
    direct_calls = tuple(
        DirectCall(address, 0x00441FA0)
        for address in (*pcode_sites, objobject_site, other_site)
    )
    calls = tuple(
        CallFact(
            address,
            0x00441FA0,
            0x00401000,
            (
                AbstractValue(
                    kind="affine",
                    affine_base=0x28,
                    affine_stride=0x0C,
                    affine_symbol="arg_count",
                    affine_terms=(("arg_count", 0x0C),),
                ),
            ),
            AbstractValue(
                kind="pointer",
                pointer_type="pcode",
                allocation_site=address,
            ),
        )
        for address in pcode_sites
    ) + (
        CallFact(
            objobject_site,
            0x00441FA0,
            0x00401000,
            (AbstractValue(kind="exact", values=frozenset({0x36})),),
            AbstractValue(
                kind="pointer",
                pointer_type="arena-allocation",
                allocation_site=objobject_site,
            ),
        ),
        CallFact(
            other_site,
            0x00441FA0,
            0x00401000,
            (AbstractValue(kind="exact", values=frozenset({0x10})),),
            AbstractValue(
                kind="pointer",
                pointer_type="arena-allocation",
                allocation_site=other_site,
            ),
        ),
    )
    values = AnalysisResult(
        compiler_sha256="a" * 64,
        cfg_instruction_hash="b" * 64,
        summaries=(),
        calls=calls,
        memory_writes=(
            MemoryWriteFact(
                address=objobject_site + 5,
                function_entry=0x00401000,
                width=1,
                base=AbstractValue(
                    kind="pointer",
                    pointer_type="objobject",
                    allocation_site=objobject_site,
                ),
                offset=0,
                value=AbstractValue(kind="exact", values=frozenset({5})),
                operation="mov",
            ),
        ),
        proof_ready=True,
    )
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=direct_calls,
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        values,
    )
    assert [inventory.allocation_at(row).classification for row in pcode_sites] == [
        "pcode",
    ] * 6
    assert inventory.allocation_at(objobject_site).classification == "objobject"
    assert inventory.allocation_at(other_site).classification == "arena-other"


def test_reviewed_retail_objobject_site_requires_initializer_and_typed_use():
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    exact_size = AbstractValue(kind="exact", values=frozenset({0x36}))
    wrong_size = AbstractValue(kind="exact", values=frozenset({0x35}))
    assert (
        audit._classify_allocation(
            0x00437CD8,
            exact_size,
            "arena-allocation",
            (),
            audit._RETAIL_SHA256,
        )
        == "arena-other"
    )
    assert (
        audit._classify_allocation(
            0x00437CD8,
            exact_size,
            "arena-allocation",
            (0x00437CE0,),
            audit._RETAIL_SHA256,
            ("objobject:typed-use:0x437cf0",),
        )
        == "objobject"
    )
    assert (
        audit._classify_allocation(
            0x00437CD8,
            wrong_size,
            "arena-allocation",
            (0x00437CE0,),
            audit._RETAIL_SHA256,
            ("objobject:typed-use:0x437cf0",),
        )
        == "arena-other"
    )


def test_new_affine_pcode_shape_expands_and_blocks_retail_review():
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    affine = AbstractValue(
        kind="affine",
        affine_base=0x28,
        affine_terms=(("dynamic-count", 0x0C),),
    )
    symbolic = AbstractValue(
        kind="symbolic",
        affine_symbol="add(scale(dynamic-count,12),40)",
    )
    for size in (affine, symbolic):
        assert (
            audit._classify_allocation(
                0x00402000,
                size,
                    "arena-allocation",
                    (),
                    audit._RETAIL_SHA256,
                    ("pcode:typed-use",),
                )
                == "pcode-expanded"
        )


def test_reviewed_pcode_address_alone_does_not_prove_allocation_shape():
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    assert (
        audit._classify_allocation(
            0x004636DE,
            AbstractValue(kind="exact", values=frozenset({0x10})),
            "pcode",
            (),
            audit._RETAIL_SHA256,
            ("pcode:return-type",),
        )
        == "arena-other"
    )


def test_tag_like_write_with_wrong_exact_size_is_not_objobject():
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    assert (
        audit._classify_allocation(
            0x00402000,
            AbstractValue(kind="exact", values=frozenset({0x2E})),
            "arena-allocation",
            (0x00402010,),
            audit._RETAIL_SHA256,
        )
        == "arena-other"
    )


def test_unlink_paths_are_classified_by_pointer_specific_following_effect():
    """Unlink-delete vs unlink-reinsert must be distinguished by call-site effect."""
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory
    from tools.mwcc_retro.x86_cfg import BasicBlock, CfgEdge, DirectCall, Instruction

    unlink = 0x0049D010
    insert = 0x0049CF90
    create = 0x004A2620
    append = 0x0049D060
    delete_call, move_call, replace_call = 0x401000, 0x401100, 0x401200
    ret_addresses = {delete_call + 5, move_call + 10, replace_call + 15}
    instructions = tuple(
        Instruction(
            address,
            1,
            "c3" if address in ret_addresses else "90",
            "ret" if address in ret_addresses else "nop",
            "",
        )
        for address in (
            delete_call,
            delete_call + 5,
            move_call,
            move_call + 5,
            move_call + 10,
            replace_call,
            replace_call + 5,
            replace_call + 10,
            replace_call + 15,
        )
    )
    blocks = tuple(
        BasicBlock(address, address + 1, (address,))
        for address in (row.address for row in instructions)
    )
    edges = (
        CfgEdge(delete_call, delete_call + 5, "call-fallthrough"),
        CfgEdge(move_call, move_call + 5, "call-fallthrough"),
        CfgEdge(move_call + 5, move_call + 10, "call-fallthrough"),
        CfgEdge(replace_call, replace_call + 5, "call-fallthrough"),
        CfgEdge(replace_call + 5, replace_call + 10, "call-fallthrough"),
        CfgEdge(replace_call + 10, replace_call + 15, "call-fallthrough"),
    )
    direct_calls = (
        DirectCall(delete_call, unlink),
        DirectCall(move_call, unlink),
        DirectCall(move_call + 5, insert),
        DirectCall(replace_call, unlink),
        DirectCall(replace_call + 5, create),
        DirectCall(replace_call + 10, append),
    )
    old_delete = AbstractValue(
        kind="pointer", pointer_type="pcode", pointer_base=1
    )
    old_move = replace(old_delete, pointer_base=2)
    old_replace = replace(old_delete, pointer_base=3)
    position = replace(old_delete, pointer_base=4)
    block = AbstractValue(kind="pointer", pointer_type="pcode-block", pointer_base=5)
    replacement = AbstractValue(
        kind="pointer",
        pointer_type="pcode",
        pointer_base=replace_call + 5,
        allocation_site=replace_call + 5,
    )
    bottom = AbstractValue()
    calls = (
        CallFact(delete_call, unlink, 0x401000, (old_delete,), bottom),
        CallFact(move_call, unlink, 0x401100, (old_move,), bottom),
        CallFact(move_call + 5, insert, 0x401100, (position, old_move), bottom),
        CallFact(replace_call, unlink, 0x401200, (old_replace,), bottom),
        CallFact(replace_call + 5, create, 0x401200, (), replacement),
        CallFact(
            replace_call + 10,
            append,
            0x401200,
            (block, replacement),
            bottom,
        ),
    )
    values = AnalysisResult(
        compiler_sha256="a" * 64,
        cfg_instruction_hash="b" * 64,
        summaries=(),
        calls=calls,
    )
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=direct_calls,
            instructions=instructions,
            blocks=blocks,
            edges=edges,
            function_entries=(),
        ),
        values,
    )
    assert inventory.unlink_at(delete_call).classification == "delete"
    assert inventory.unlink_at(move_call).classification == "move-reinsert"
    assert inventory.unlink_at(replace_call).classification == "replace"


def test_symbolic_loop_phi_aliases_match_across_adjacent_blocks():
    from tools.mwcc_retro.backend_abstract_values import AbstractValue

    before = AbstractValue(
        kind="symbolic",
        affine_symbol="memory[add(loop-phi[0x401000:register=21],12)]:u32",
    )
    after = replace(
        before,
        affine_symbol="memory[add(loop-phi[0x401020:register=21],12)]:u32",
    )
    assert audit._alias_relation(before, after) == "same"


def test_insert_before_unlink_is_a_replacement():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )
    from tools.mwcc_retro.x86_cfg import BasicBlock, CfgEdge, DirectCall, Instruction

    create_call, insert_call, unlink_call, ret = (
        0x401000,
        0x401005,
        0x40100A,
        0x40100F,
    )
    bottom = AbstractValue()
    old = AbstractValue(kind="symbolic", affine_symbol="old-pcode")
    new = AbstractValue(
        kind="pointer",
        pointer_type="pcode",
        pointer_base=create_call,
        allocation_site=create_call,
    )
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(
                DirectCall(create_call, 0x004A2620),
                DirectCall(insert_call, 0x0049CF90),
                DirectCall(unlink_call, 0x0049D010),
            ),
            instructions=(
                Instruction(create_call, 1, "90", "nop", ""),
                Instruction(insert_call, 1, "90", "nop", ""),
                Instruction(unlink_call, 1, "90", "nop", ""),
                Instruction(ret, 1, "c3", "ret", ""),
            ),
            blocks=(
                BasicBlock(
                    create_call,
                    unlink_call + 1,
                    (create_call, insert_call, unlink_call),
                ),
                BasicBlock(ret, ret + 1, (ret,)),
            ),
            edges=(CfgEdge(unlink_call, ret, "call-fallthrough"),),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            calls=(
                CallFact(
                    create_call,
                    0x004A2620,
                    create_call,
                    (),
                    new,
                ),
                CallFact(
                    insert_call,
                    0x0049CF90,
                    insert_call,
                    (old, new),
                    bottom,
                ),
                CallFact(
                    unlink_call,
                    0x0049D010,
                    insert_call,
                    (old,),
                    bottom,
                ),
            ),
        ),
    )
    assert inventory.unlink_at(unlink_call).classification == "replace"


def test_unknown_unlink_argument_can_still_prove_delete_from_control_flow():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )
    from tools.mwcc_retro.x86_cfg import BasicBlock, CfgEdge, DirectCall, Instruction

    unlink_call, ret = 0x401000, 0x401005
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(DirectCall(unlink_call, 0x0049D010),),
            instructions=(
                Instruction(unlink_call, 1, "90", "nop", ""),
                Instruction(ret, 1, "c3", "ret", ""),
            ),
            blocks=(
                BasicBlock(unlink_call, unlink_call + 1, (unlink_call,)),
                BasicBlock(ret, ret + 1, (ret,)),
            ),
            edges=(CfgEdge(unlink_call, ret, "call-fallthrough"),),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            calls=(
                CallFact(
                    unlink_call,
                    0x0049D010,
                    unlink_call,
                    (AbstractValue(kind="unknown", origin="lost-source"),),
                    AbstractValue(),
                ),
            ),
        ),
    )
    assert inventory.unlink_at(unlink_call).classification == "delete"
    assert inventory.proof_ready


def test_unrelated_insert_after_unlink_does_not_count_as_reinsert():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory
    from tools.mwcc_retro.x86_cfg import BasicBlock, CfgEdge, DirectCall, Instruction

    unlink_call, insert_call, ret = 0x401000, 0x401005, 0x40100A
    node = AbstractValue(
        kind="pointer", pointer_type="pcode", pointer_base=1, allocation_site=1
    )
    unrelated = replace(node, pointer_base=2, allocation_site=2)
    bottom = AbstractValue()
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(
                DirectCall(unlink_call, 0x0049D010),
                DirectCall(insert_call, 0x0049CF90),
            ),
            instructions=(
                Instruction(unlink_call, 1, "90", "nop", ""),
                Instruction(insert_call, 1, "90", "nop", ""),
                Instruction(ret, 1, "c3", "ret", ""),
            ),
            blocks=tuple(
                BasicBlock(address, address + 1, (address,))
                for address in (unlink_call, insert_call, ret)
            ),
            edges=(
                CfgEdge(unlink_call, insert_call, "call-fallthrough"),
                CfgEdge(insert_call, ret, "call-fallthrough"),
            ),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            calls=(
                CallFact(unlink_call, 0x0049D010, unlink_call, (node,), bottom),
                CallFact(
                    insert_call,
                    0x0049CF90,
                    unlink_call,
                    (unrelated, unrelated),
                    bottom,
                ),
            ),
        ),
    )
    assert inventory.unlink_at(unlink_call).classification == "delete"
    assert inventory.proof_ready


def test_unlink_path_without_owned_fallthrough_block_is_not_called_delete():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )
    from tools.mwcc_retro.x86_cfg import BasicBlock, CfgEdge, DirectCall, Instruction

    unlink_call, missing = 0x401000, 0x401005
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(DirectCall(unlink_call, 0x0049D010),),
            instructions=(Instruction(unlink_call, 1, "90", "nop", ""),),
            blocks=(BasicBlock(unlink_call, unlink_call + 1, (unlink_call,)),),
            edges=(CfgEdge(unlink_call, missing, "call-fallthrough"),),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            calls=(
                CallFact(
                    unlink_call,
                    0x0049D010,
                    unlink_call,
                    (
                        AbstractValue(
                            kind="pointer", pointer_type="pcode", pointer_base=1
                        ),
                    ),
                    AbstractValue(),
                ),
            ),
        ),
    )

    assert inventory.unlink_at(unlink_call).classification == "unresolved"
    assert not inventory.proof_ready


def test_possible_untyped_alias_to_pcode_bytes_blocks_proof():
    """Alias-ambiguous stores to PCode bytes must block proof_ready."""
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        MemoryWriteFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory

    values = AnalysisResult(
        compiler_sha256="a" * 64,
        cfg_instruction_hash="b" * 64,
        summaries=(),
        memory_writes=(
            MemoryWriteFact(
                address=0x00402000,
                function_entry=0x00401000,
                width=4,
                base=AbstractValue(kind="unknown", origin="join:pcode,pointer"),
                offset=0x1C,
                value=AbstractValue(kind="exact", values=frozenset({1})),
                operation="mov",
            ),
        ),
    )
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(), instructions=(), blocks=(), edges=(), function_entries=()
        ),
        values,
    )
    assert not inventory.proof_ready
    assert inventory.unresolved[0].kind == "possible-untyped-pcode-write"


def test_one_instruction_with_multiple_typed_field_semantics_blocks_proof():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        MemoryWriteFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    address = 0x00402000
    base = AbstractValue(kind="pointer", pointer_type="pcode", pointer_base=1)
    value = AbstractValue(kind="exact", values=frozenset({1}))
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(),
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            memory_writes=(
                MemoryWriteFact(address, 0x401000, 4, base, 0, value, "mov"),
                MemoryWriteFact(address, 0x401000, 4, base, 4, value, "mov"),
            ),
        ),
    )

    assert any(
        row.address == address
        and row.kind == "ambiguous-typed-field-write-semantics"
        for row in inventory.unresolved
    )


def test_unknown_arena_size_blocks_lifetime_proof():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory
    from tools.mwcc_retro.x86_cfg import DirectCall

    address = 0x00402000
    call = DirectCall(address, 0x00441FA0)
    values = AnalysisResult(
        compiler_sha256="a" * 64,
        cfg_instruction_hash="b" * 64,
        summaries=(),
        calls=(
            CallFact(
                address,
                call.target,
                0x00401000,
                (AbstractValue(kind="unknown", origin="unsupported-size"),),
                AbstractValue(kind="pointer", pointer_type="arena-allocation"),
            ),
        ),
    )
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(call,),
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        values,
    )
    assert not inventory.proof_ready
    assert inventory.unresolved[0].kind == "unknown-allocation-size"


def test_unknown_size_in_any_arena_blocks_complete_allocation_inventory():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory
    from tools.mwcc_retro.x86_cfg import DirectCall

    address = 0x00402000
    call = DirectCall(address, 0x00441F20)
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(call,),
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            calls=(
                CallFact(
                    address,
                    call.target,
                    0x00401000,
                    (AbstractValue(kind="unknown", origin="dynamic-size"),),
                    AbstractValue(
                        kind="pointer", pointer_type="arena-allocation"
                    ),
                ),
            ),
        ),
    )
    assert inventory.allocation_at(address).classification == "arena-other"
    assert not inventory.proof_ready
    assert any(
        row.address == address and row.kind == "unknown-allocation-size"
        for row in inventory.unresolved
    )


def test_accepted_residue_arena_candidate_is_classified_without_runtime_hook():
    from tools.mwcc_retro.backend_abstract_values import AnalysisResult
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory

    address = 0x00402020
    interval = ExecutableResidueInterval(
        start=address - 2,
        end=address + 5,
        bytes_hex=(b"\x6a\x10\xe8\x00\x00\x00\x00").hex(),
        bytes_sha256=hashlib.sha256(
            b"\x6a\x10\xe8\x00\x00\x00\x00"
        ).hexdigest(),
    )
    image_bytes = {address - 5: b"\x90\x90\x90\x6a\x10"}
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(
            sha256="a" * 64,
            read=lambda start, size: image_bytes[start][-size:],
        ),
        SimpleNamespace(
            direct_calls=(),
            raw_e8_candidates=(
                RawE8Candidate(
                    address,
                    0x00441FA0,
                    "unreachable-executable-residue",
                ),
            ),
            provisional_unreachable_residue=UnreachableExecutableResidue(
                intervals=(interval,),
                reachable_ownership_sha256="b" * 64,
                executable_partition_sha256="c" * 64,
                accepted=True,
                reconciliation_sha256="d" * 64,
            ),
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
        ),
    )

    allocation = inventory.allocation_at(address)
    assert allocation.classification == "unreachable-residue-candidate"
    assert allocation.ownership == "accepted-unreachable-residue"
    assert allocation.raw_e8_classification == "unreachable-executable-residue"
    assert allocation.size.exact_value == 0x10
    assert not any(row.address == address for row in inventory.hook_capture_facts)
    assert inventory.proof_ready


def test_unaccepted_residue_arena_candidate_blocks_lifetime_proof():
    from tools.mwcc_retro.backend_abstract_values import AnalysisResult
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory

    address = 0x00402020
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(),
            raw_e8_candidates=(
                RawE8Candidate(
                    address,
                    0x00441FA0,
                    "unreachable-executable-residue",
                ),
            ),
            provisional_unreachable_residue=UnreachableExecutableResidue(
                intervals=(),
                reachable_ownership_sha256="b" * 64,
                executable_partition_sha256="c" * 64,
            ),
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
        ),
    )

    assert not inventory.proof_ready
    assert any(
        row.address == address and row.kind == "uncertified-residue-arena-call"
        for row in inventory.unresolved
    )


def test_typed_pcode_fields_have_closed_layout_names():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        MemoryWriteFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory

    base = AbstractValue(kind="pointer", pointer_type="pcode", pointer_base=1)
    writes = tuple(
        MemoryWriteFact(
            address=0x00402000 + index,
            function_entry=0x00401000,
            width=width,
            base=base,
            offset=offset,
            value=AbstractValue(kind="exact", values=frozenset({index + 1})),
            operation="mov",
        )
        for index, (offset, width) in enumerate(
            (
                (0, 4),
                (4, 4),
                (0x14, 2),
                (0x16, 4),
                (0x1A, 2),
                (0x1C, 1),
                (0x1D, 1),
                (0x1E, 4),
            )
        )
    )
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(), instructions=(), blocks=(), edges=(), function_entries=()
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            memory_writes=writes,
        ),
    )
    assert [row.field for row in inventory.field_writes] == [
        "next-link",
        "previous-link",
        "opcode",
        "flags",
        "operand-count",
        "operand[0].kind",
        "operand[0].flags",
        "operand[0].payload",
    ]
    assert inventory.proof_ready


def test_reviewed_retail_unlink_anchor_never_overrides_computed_effect():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )
    from tools.mwcc_retro.x86_cfg import (
        BasicBlock,
        CfgEdge,
        DirectCall,
        Instruction,
    )

    unlink_call = 0x004C61E2
    ret = unlink_call + 5
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256=audit._RETAIL_SHA256),
        SimpleNamespace(
            direct_calls=(DirectCall(unlink_call, 0x0049D010),),
            instructions=(
                Instruction(unlink_call, 1, "90", "nop", ""),
                Instruction(ret, 1, "c3", "ret", ""),
            ),
            blocks=(
                BasicBlock(unlink_call, unlink_call + 1, (unlink_call,)),
                BasicBlock(ret, ret + 1, (ret,)),
            ),
            edges=(CfgEdge(unlink_call, ret, "call-fallthrough"),),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256=audit._RETAIL_SHA256,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            calls=(
                CallFact(
                    unlink_call,
                    0x0049D010,
                    unlink_call,
                    (
                        AbstractValue(
                            kind="pointer",
                            pointer_type="pcode",
                            pointer_base=1,
                        ),
                    ),
                    AbstractValue(),
                ),
            ),
        ),
    )

    assert inventory.unlink_at(unlink_call).classification == "delete"
    assert any(
        row.address == unlink_call
        and row.kind == "reviewed-retail-unlink-regression-differs"
        for row in inventory.unresolved
    )


def test_address_presence_alone_does_not_create_semantic_lifecycle_sites():
    from tools.mwcc_retro.backend_abstract_values import AnalysisResult
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )
    from tools.mwcc_retro.x86_cfg import Instruction

    anchors = tuple(
        sorted(
            set(audit._REUSE_TRANSITIONS)
            | set(audit._MUTATION_SITES)
            | set(audit._EMISSION_SITES)
        )
    )
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(),
            instructions=tuple(
                Instruction(address, 1, "90", "nop", "")
                for address in anchors
            ),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
        ),
    )

    assert not inventory.reuses
    assert not inventory.mutation_sites
    assert not inventory.emission_sites


def test_typed_field_writes_expand_mutation_and_rewrite_inventory():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        MemoryWriteFact,
    )
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    address = 0x00402000
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(),
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            memory_writes=(
                MemoryWriteFact(
                    address=address,
                    function_entry=0x00401000,
                    width=2,
                    base=AbstractValue(
                        kind="pointer", pointer_type="pcode", pointer_base=1
                    ),
                    offset=0x1E,
                    value=AbstractValue(
                        kind="exact", values=frozenset({0x1234})
                    ),
                    operation="mov",
                ),
            ),
        ),
    )

    assert [(row.address, row.classification) for row in inventory.mutation_sites] == [
        (address, "pcode-field-write:operand[0].payload"),
    ]
    assert inventory.rewrite_sites == inventory.mutation_sites


def test_exact_retail_requires_task5_lifetime_closure_certificates():
    from tools.mwcc_retro.backend_abstract_values import AnalysisResult
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256=audit._RETAIL_SHA256),
        SimpleNamespace(
            direct_calls=(),
            raw_e8_candidates=(),
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256=audit._RETAIL_SHA256,
            cfg_instruction_hash="b" * 64,
            summaries=(),
        ),
    )

    assert {
        row.kind for row in inventory.unresolved
    } >= {
        "missing-task5-alias-write-closure-certificate",
        "missing-task5-lifecycle-effect-closure-certificate",
        "missing-task5-final-emission-closure-certificate",
    }


def _exactify_task5_fixture(image, values):
    return (
        replace(image, sha256=audit._RETAIL_SHA256),
        replace(
            values,
            compiler_sha256=audit._RETAIL_SHA256,
            alias_write_closure=replace(
                values.alias_write_closure,
                compiler_sha256=audit._RETAIL_SHA256,
            ),
            lifecycle_effect_closure=replace(
                values.lifecycle_effect_closure,
                compiler_sha256=audit._RETAIL_SHA256,
            ),
            final_emission_closure=replace(
                values.final_emission_closure,
                compiler_sha256=audit._RETAIL_SHA256,
            ),
        ),
    )


def test_exact_task6_consumes_structured_task5_gaps_not_boolean_shortcuts():
    from test_retro_backend_abstract_values import _limits, _minimal_pe, _recover
    from tools.mwcc_retro.backend_abstract_values import analyze_values
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    image, cfg = _recover(_minimal_pe(bytes.fromhex("87 03 c3")))
    values = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    image, values = _exactify_task5_fixture(image, values)
    inventory = build_lifetime_site_inventory(image, cfg, values)
    kinds = {row.kind for row in inventory.unresolved}

    assert "missing-task5-alias-write-closure-certificate" not in kinds
    assert "task5-alias-write-gap:unmodelled-memory-write" in kinds
    assert "task5-final-emission-gap:missing-pseudo-op-disposition-evidence" in kinds


@pytest.mark.parametrize(
    "mutation", ("missing", "duplicate", "malformed", "tampered-hash", "cap-hit")
)
def test_exact_task6_rederives_alias_certificate_and_rejects_tampering(mutation):
    from test_retro_backend_abstract_values import _limits, _minimal_pe, _recover
    from tools.mwcc_retro.backend_abstract_values import analyze_values
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    image, cfg = _recover(_minimal_pe(bytes.fromhex("89 04 24 c3")))
    values = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    image, values = _exactify_task5_fixture(image, values)
    certificate = values.alias_write_closure
    assert certificate is not None
    if mutation == "missing":
        certificate = replace(certificate, sites=())
        expected = "task5-alias-write-certificate-missing-site"
    elif mutation == "duplicate":
        certificate = replace(certificate, sites=(*certificate.sites, certificate.sites[0]))
        expected = "task5-alias-write-certificate-duplicate-site"
    elif mutation == "malformed":
        certificate = replace(certificate, sites=(object(),))
        expected = "task5-alias-write-certificate-malformed"
    elif mutation == "tampered-hash":
        certificate = replace(certificate, cfg_instruction_hash="0" * 64)
        expected = "task5-alias-write-certificate-differs"
    else:
        certificate = replace(certificate, cap_hits=("max_memory_write_operands",))
        expected = "task5-alias-write-certificate-cap-hit"
    inventory = build_lifetime_site_inventory(
        image, cfg, replace(values, alias_write_closure=certificate)
    )
    assert expected in {row.kind for row in inventory.unresolved}


def test_exact_task6_rejects_duplicate_lifecycle_helper_evidence():
    from test_retro_backend_abstract_values import _limits, _minimal_pe, _recover
    from tools.mwcc_retro.backend_abstract_values import analyze_values
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    image, cfg = _recover(
        _minimal_pe(bytes.fromhex("e8 01 00 00 00 c3 c3"))
    )
    values = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    image, values = _exactify_task5_fixture(image, values)
    certificate = values.lifecycle_effect_closure
    assert certificate is not None
    certificate = replace(
        certificate, sites=(*certificate.sites, certificate.sites[0])
    )
    inventory = build_lifetime_site_inventory(
        image, cfg, replace(values, lifecycle_effect_closure=certificate)
    )
    assert "task5-lifecycle-effect-certificate-duplicate-site" in {
        row.kind for row in inventory.unresolved
    }


def test_exact_task6_rejects_fabricated_final_emission_closure():
    from test_retro_backend_abstract_values import _limits, _minimal_pe, _recover
    from tools.mwcc_retro.backend_abstract_values import analyze_values
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    image, cfg = _recover(_minimal_pe(bytes.fromhex("c3")))
    values = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    image, values = _exactify_task5_fixture(image, values)
    certificate = values.final_emission_closure
    assert certificate is not None
    certificate = replace(certificate, gaps=())
    inventory = build_lifetime_site_inventory(
        image, cfg, replace(values, final_emission_closure=certificate)
    )
    kinds = {row.kind for row in inventory.unresolved}
    assert "task5-final-emission-certificate-differs" in kinds
    assert (
        "task5-final-emission-gap:missing-machine-field-derivation-evidence"
        in kinds
    )


def test_exact_known_encoder_address_cannot_create_emission_evidence():
    from test_retro_backend_abstract_values import _limits, _minimal_pe, _recover
    from tools.mwcc_retro.backend_abstract_values import analyze_values
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    payload = bytearray(b"\x90" * 0x891)
    payload[0x17:0x1D] = bytes.fromhex("e8 74 08 00 00 c3")
    payload[0x890] = 0xC3
    image, cfg = _recover(_minimal_pe(bytes(payload), text_va=0x004A2D00))
    values = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    image, values = _exactify_task5_fixture(image, values)

    inventory = build_lifetime_site_inventory(image, cfg, values)
    assert not inventory.emission_sites
    assert any(
        row.kind.startswith("task5-final-emission-gap:")
        for row in inventory.unresolved
    )


def test_exact_known_generation_target_cannot_create_release_evidence():
    from test_retro_backend_abstract_values import _limits, _minimal_pe, _recover
    from tools.mwcc_retro.backend_abstract_values import analyze_values
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    payload = bytearray(b"\x90" * 0x21)
    payload[:6] = bytes.fromhex("e8 1b 00 00 00 c3")
    payload[0x20] = 0xC3
    image, cfg = _recover(_minimal_pe(bytes(payload), text_va=0x00441E80))
    values = analyze_values(image, cfg, cfg.control_targets, (), _limits(image))
    image, values = _exactify_task5_fixture(image, values)

    inventory = build_lifetime_site_inventory(image, cfg, values)
    assert not inventory.releases


def test_accepted_residue_unlink_candidate_is_not_a_runtime_unlink():
    from tools.mwcc_retro.backend_abstract_values import AnalysisResult
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )

    address = 0x00402020
    payload = b"\xe8\x00\x00\x00\x00"
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(),
            raw_e8_candidates=(
                RawE8Candidate(
                    address,
                    0x0049D010,
                    "unreachable-executable-residue",
                ),
            ),
            provisional_unreachable_residue=UnreachableExecutableResidue(
                intervals=(
                    ExecutableResidueInterval(
                        start=address,
                        end=address + len(payload),
                        bytes_hex=payload.hex(),
                        bytes_sha256=hashlib.sha256(payload).hexdigest(),
                    ),
                ),
                reachable_ownership_sha256="b" * 64,
                executable_partition_sha256="c" * 64,
                accepted=True,
                reconciliation_sha256="d" * 64,
            ),
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
        ),
    )

    unlink = inventory.unlink_at(address)
    assert unlink.classification == "unreachable-residue-candidate"
    assert unlink.ownership == "accepted-unreachable-residue"
    assert not any(
        row.address == address and row.event == "unlink"
        for row in inventory.hook_capture_facts
    )


def test_generation_reuse_mutation_and_emission_sites_are_closed():
    from tools.mwcc_retro.backend_abstract_values import (
        AbstractValue,
        AnalysisResult,
        CallFact,
        MemoryWriteFact,
        PseudoOpDispositionEvidence,
        ValueDependency,
    )
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory
    from tools.mwcc_retro.x86_cfg import DirectCall, Instruction

    reuse_sites = (0x004356B5, 0x00435857, 0x00435AD3, 0x00437CC1)
    mutation_sites = (
        0x004CE1E7,
        0x004CE20B,
        0x00530BA6,
        0x00531254,
        0x005311BD,
        0x004A32E0,
        0x00531800,
        0x0049D270,
    )
    emission_sites = (
        0x004A2B70,
        0x004A2D17,
        0x004A2D2B,
        0x004A2D5F,
        0x004A3590,
    )
    instructions = tuple(
        Instruction(address, 1, "90", "nop", "")
        for address in (*reuse_sites, *mutation_sites, *emission_sites)
    )
    direct_calls = (
        DirectCall(0x00480000, 0x00441EA0),
        DirectCall(0x00480010, 0x00442020),
        DirectCall(0x00480020, 0x00442050),
        DirectCall(0x004A2D17, 0x004A3590),
    )
    encoder_result = AbstractValue(
        kind="symbolic",
        affine_symbol="encoded-machine-word",
        origin="encoder-return",
        dependencies=(
            ValueDependency(
                kind="memory-read",
                address=0x004A3600,
                width=2,
                pointer_type="pcode",
                pointer_offset=0x1E,
            ),
        ),
    )
    relocation_value = AbstractValue(
        kind="symbolic",
        affine_symbol="relocation-symbol",
        origin="encoder-output",
        dependencies=(
            ValueDependency(
                kind="helper-output",
                address=0x004A2D17,
                source_address=0x004A3610,
                width=4,
                pointer_type="stack",
                pointer_offset=-8,
            ),
            ValueDependency(
                kind="helper-output",
                address=0x004A2D17,
                source_address=0x004A3614,
                width=4,
                pointer_type="stack",
                pointer_offset=-4,
            ),
        ),
    )
    buffer_write = MemoryWriteFact(
        address=0x004A2D2B,
        function_entry=0x004A2B70,
        width=4,
        base=AbstractValue(kind="pointer", pointer_type="image"),
        offset=0,
        value=encoder_result,
        operation="mov",
    )
    reuse_writes = tuple(
        MemoryWriteFact(
            address=address,
            function_entry=0x00435000,
            width=1,
            base=AbstractValue(
                kind="pointer",
                pointer_type="objobject",
                pointer_base=address,
            ),
            offset=0x2A,
            value=AbstractValue(
                kind="exact", values=frozenset({index & 1})
            ),
            operation="mov",
        )
        for index, address in enumerate(reuse_sites)
    )
    mutation_writes = tuple(
        MemoryWriteFact(
            address=address,
            function_entry=address & ~0xFF,
            width=4,
            base=AbstractValue(
                kind="pointer", pointer_type="pcode", pointer_base=address
            ),
            offset=0 if index >= len(mutation_sites) - 2 else 0x1E,
            value=AbstractValue(
                kind="exact", values=frozenset({address})
            ),
            operation="mov",
        )
        for index, address in enumerate(mutation_sites)
    )
    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=direct_calls,
            instructions=instructions,
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
            calls=(
                    CallFact(
                        0x004A2D17,
                        0x004A3590,
                        0x004A2B70,
                        (
                            AbstractValue(
                                kind="pointer", pointer_type="pcode"
                            ),
                        ),
                        encoder_result,
                    ),
                    CallFact(
                        0x004A2D5F,
                        0x004889B0,
                        0x004A2B70,
                        (
                            relocation_value,
                            relocation_value,
                            relocation_value,
                        ),
                        AbstractValue(),
                    ),
                ),
                memory_writes=(*reuse_writes, *mutation_writes, buffer_write),
                limits=AnalysisLimits(
                    max_instructions=100,
                    max_blocks=100,
                    max_edges=100,
                ),
                pseudo_op_dispositions=(
                    PseudoOpDispositionEvidence(
                        opcode_ids=(466, 467),
                        classification="removed-before-final-walker",
                        walker_address=0x004A2B70,
                        disposition_sites=(0x004A2D00,),
                        provenance=("exhaustive synthetic list transition",),
                    ),
                ),
            ),
    )
    assert len(inventory.reuses) == 4
    assert [row.classification for row in inventory.releases] == [
        "temporary-arena-rewind",
        "persistent-arena-release",
        "all-compiler-arenas-release",
    ]
    assert {row.address for row in inventory.mutation_sites} == set(mutation_sites)
    assert {row.address for row in inventory.rewrite_sites} < set(mutation_sites)
    assert {row.address for row in inventory.emission_sites} == set(emission_sites)
    assert inventory.proof_ready
    assert not inventory.unresolved


def test_known_encoder_address_without_semantic_flow_is_only_an_anchor():
    from tools.mwcc_retro.backend_abstract_values import AnalysisResult
    from tools.mwcc_retro.backend_lifetime_audit import build_lifetime_site_inventory
    from tools.mwcc_retro.x86_cfg import DirectCall

    inventory = build_lifetime_site_inventory(
        SimpleNamespace(sha256="a" * 64),
        SimpleNamespace(
            direct_calls=(DirectCall(0x00402000, 0x004A3590),),
            instructions=(),
            blocks=(),
            edges=(),
            function_entries=(),
        ),
        AnalysisResult(
            compiler_sha256="a" * 64,
            cfg_instruction_hash="b" * 64,
            summaries=(),
        ),
    )
    assert inventory.proof_ready
    assert not inventory.emission_sites
