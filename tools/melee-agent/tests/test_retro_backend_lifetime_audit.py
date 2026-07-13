import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))

from retro_pe_fixture import write_synthetic_dispatch_pe  # noqa: E402
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
        '"function-pointer-reference"',
        '"retained-body-call"',
    ):
        assert required in source
