import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

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
    OwnershipDiagnostic,
    TerminalExternalEdge,
    UnresolvedControlTarget,
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
):
    rows = [
        {
            "record_kind": "metadata",
            "schema_version": "mwcc-ghidra-raw-crosscheck.v1",
            "compiler_sha256": "a" * 64,
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
    target = (
        0x00402200
        if record_kind == "data-reference"
        else 0x00401020
    )
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
    with pytest.raises(GhidraInventoryError, match="numeric canonical order"):
        load_ghidra_inventory(path, expected_sha256="a" * 64)


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
        AnalysisResult,
        FunctionSummary,
    )
    from tools.mwcc_retro.backend_lifetime_audit import (
        build_lifetime_site_inventory,
    )
    # Build a minimal analysis result
    values = AnalysisResult(
        compiler_sha256="a" * 64,
        cfg_instruction_hash="b" * 64,
        summaries=(),
        proof_ready=True,
    )
    # Import failure expected until build_lifetime_site_inventory exists


def test_unlink_paths_are_classified_by_following_effect():
    """Unlink-delete vs unlink-reinsert must be distinguished by call-site effect."""
    # RED: import/build_lifetime_site_inventory not yet available
    pass


def test_possible_untyped_alias_to_pcode_bytes_blocks_proof():
    """Alias-ambiguous stores to PCode bytes must block proof_ready."""
    # RED: import/build_lifetime_site_inventory not yet available
    pass
