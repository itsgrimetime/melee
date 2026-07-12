from __future__ import annotations

import copy
import json
import struct
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro.backend_instrumentation_proof import (  # noqa: E402
    InstrumentationProof,
    proof_sha256,
)
from tools.mwcc_retro.backend_pcode_lineage import (  # noqa: E402
    AnchorVirtualBinding,
    PCodeLineageValidation,
    validate_pcode_lineage,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "retro" / "pcode_lineage"
PC_ADDRESS = 0x2000


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def _candidate_elf(
    code: bytes = bytes.fromhex("3ad50000"),
    *,
    function: str = "fn",
    function_size: int | None = None,
    duplicate_function: bool = False,
    relocation: tuple[int, int, str, int] | None = None,
) -> bytes:
    """Build a minimal ELF32/PowerPC relocatable object for validator tests."""

    shstr = b"\0.text\0.rela.text\0.symtab\0.strtab\0.shstrtab\0"
    sh_name = {name: shstr.index(name.encode()) for name in (".text", ".rela.text", ".symtab", ".strtab", ".shstrtab")}
    names = [function]
    if relocation is not None:
        names.append(relocation[2])
    strtab = b"\0"
    name_offsets: dict[str, int] = {}
    for name in names:
        if name not in name_offsets:
            name_offsets[name] = len(strtab)
            strtab += name.encode() + b"\0"

    size = len(code) if function_size is None else function_size
    symbols = [b"\0" * 16]
    symbols.append(struct.pack(">IIIBBH", name_offsets[function], 0, size, 0x12, 0, 1))
    if duplicate_function:
        symbols.append(struct.pack(">IIIBBH", name_offsets[function], 0, size, 0x12, 0, 1))
    target_index = 0
    if relocation is not None:
        target_index = len(symbols)
        symbols.append(struct.pack(">IIIBBH", name_offsets[relocation[2]], 0, 0, 0x10, 0, 0))
    symtab = b"".join(symbols)
    rela = b""
    if relocation is not None:
        offset, relocation_type, _target, addend = relocation
        rela = struct.pack(">IIi", offset, (target_index << 8) | relocation_type, addend)

    sections = [code, rela, symtab, strtab, shstr]
    offsets: list[int] = []
    cursor = 52
    for data, alignment in zip(sections, (4, 4, 4, 1, 1), strict=True):
        cursor = _align(cursor, alignment)
        offsets.append(cursor)
        cursor += len(data)
    shoff = _align(cursor, 4)
    ident = b"\x7fELF" + bytes((1, 2, 1, 0, 0)) + b"\0" * 7
    header = ident + struct.pack(">HHIIIIIHHHHHH", 1, 20, 1, 0, 0, shoff, 0, 52, 0, 0, 40, 6, 5)
    image = bytearray(header)
    for offset, data in zip(offsets, sections, strict=True):
        image.extend(b"\0" * (offset - len(image)))
        image.extend(data)
    image.extend(b"\0" * (shoff - len(image)))

    def shdr(
        name: str, kind: int, flags: int, offset: int, data: bytes, link: int, info: int, align: int, entsize: int
    ) -> bytes:
        return struct.pack(
            ">IIIIIIIIII", sh_name.get(name, 0), kind, flags, 0, offset, len(data), link, info, align, entsize
        )

    image.extend(b"\0" * 40)
    image.extend(shdr(".text", 1, 0x6, offsets[0], code, 0, 0, 4, 0))
    image.extend(shdr(".rela.text", 4, 0, offsets[1], rela, 3, 1, 4, 12))
    image.extend(shdr(".symtab", 2, 0, offsets[2], symtab, 4, 1, 4, 16))
    image.extend(shdr(".strtab", 3, 0, offsets[3], strtab, 0, 0, 1, 0))
    image.extend(shdr(".shstrtab", 3, 0, offsets[4], shstr, 0, 0, 1, 0))
    return bytes(image)


@pytest.fixture
def candidate_object(tmp_path: Path) -> Path:
    path = tmp_path / "candidate.o"
    path.write_bytes(_candidate_elf())
    return path


def proof_payload() -> dict[str, object]:
    rules: list[dict[str, object]] = []
    for operand_index, role in ((0, "def"), (1, "use")):
        rules.extend(
            [
                {
                    "opcode_id": 42,
                    "operand_index": operand_index,
                    "raw_arg_kind_id": 7,
                    "register_flags_mask": 3,
                    "register_flags_value": 0,
                    "role": role,
                    "class_id": 0,
                    "allocation_requirement": "allocator-rewrite-required",
                },
                {
                    "opcode_id": 42,
                    "operand_index": operand_index,
                    "raw_arg_kind_id": 8,
                    "register_flags_mask": 3,
                    "register_flags_value": 1,
                    "role": role,
                    "class_id": 0,
                    "allocation_requirement": "fixed-physical",
                },
            ]
        )
    rules.sort(
        key=lambda row: tuple(
            row[field]
            for field in (
                "opcode_id",
                "operand_index",
                "raw_arg_kind_id",
                "register_flags_mask",
                "register_flags_value",
            )
        )
    )
    return {
        "schema_version": "mwcc-retro-lifetime-proof.v1",
        "proof_id": "gc-1.2.5n-backend-entity-allocation-trace.v1",
        "compiler_executable_sha256": "a" * 64,
        "mode": "allocation-generation",
        "allocation_sites": [
            {
                "site_id": "pcode-alloc-1",
                "address": 0x500100,
                "entity_kind": "pcode",
                "compiler_stage": "backend-lowering",
            }
        ],
        "free_sites": [
            {
                "site_id": "pcode-free-1",
                "address": 0x500200,
                "entity_kind": "pcode",
                "compiler_stage": "backend-finalize",
            }
        ],
        "operand_rewrite_sites": [{"site_id": "rewrite-1", "address": 0x500300, "compiler_stage": "colorgraph"}],
        "operand_mutation_sites": [{"site_id": "mutation-1", "address": 0x500400, "compiler_stage": "optimizer"}],
        "code_emission_sites": [{"site_id": "emit-1", "address": 0x500500, "compiler_stage": "backend-finalize"}],
        "operand_rules": rules,
        "opcode_table": [{"opcode_id": 42, "mnemonic": "ADDI"}],
        "initialization_address": 0x401000,
        "proof_basis": "exhaustive-static-callgraph-and-disassembly",
    }


def trusted_proof() -> InstrumentationProof:
    payload = proof_payload()
    return InstrumentationProof(str(payload["proof_id"]), "a" * 64, payload, proof_sha256(payload))


def operand(
    index: int, lineage: str, kind: int, digest_char: str, parents: list[str] | None = None
) -> dict[str, object]:
    row: dict[str, object] = {
        "operand_index": index,
        "operand_lineage_id": lineage,
        "raw_arg_kind_id": kind,
        "raw_payload_sha256": digest_char * 64,
    }
    if parents is not None:
        row["parent_lineage_ids"] = parents
    return row


def state(
    operands: list[dict[str, object]],
    *,
    sequence: int = 0,
    pcode_id: str = "pc-0",
    address: int = PC_ADDRESS,
    generation: int = 1,
) -> dict[str, object]:
    return {
        "pcode_id": pcode_id,
        "runtime_address": address,
        "allocation_generation": generation,
        "lifecycle_sequence_at_capture": sequence,
        "opcode_id": 42,
        "arg_count": 3,
        "operands": operands,
    }


def parsed(
    index: int, lineage: str, role: str, *, kind: int, requirement: str, virtual: int | None, physical: int | None
) -> dict[str, object]:
    return {
        "operand_index": index,
        "role": role,
        "class_id": 0,
        "raw_arg_kind_id": kind,
        "raw_register_flags": 0 if kind == 7 else 1,
        "allocation_requirement": requirement,
        "operand_lineage_id": lineage,
        "virtual_kind": "r" if virtual is not None else None,
        "virtual": virtual,
        "physical_register": physical,
    }


def snapshot(stage: str, *, reordered: bool = False) -> dict[str, object]:
    if stage == "allocator_input":
        inventory = [operand(0, "ol-0", 7, "a"), operand(1, "ol-1", 7, "b"), operand(2, "ol-2", 1, "c")]
        registers = [
            parsed(0, "ol-0", "def", kind=7, requirement="allocator-rewrite-required", virtual=67, physical=None),
            parsed(1, "ol-1", "use", kind=7, requirement="allocator-rewrite-required", virtual=66, physical=None),
        ]
    else:
        lineages = ("ol-1", "ol-0") if reordered else ("ol-0", "ol-1")
        physicals = (21, 22) if reordered else (22, 21)
        inventory = [operand(0, lineages[0], 8, "d"), operand(1, lineages[1], 8, "e"), operand(2, "ol-2", 1, "f")]
        registers = [
            parsed(0, lineages[0], "def", kind=8, requirement="fixed-physical", virtual=None, physical=physicals[0]),
            parsed(1, lineages[1], "use", kind=8, requirement="fixed-physical", virtual=None, physical=physicals[1]),
        ]
    return {
        "stage": stage,
        "lifecycle_sequence_at_capture": 0,
        "runtime_address": PC_ADDRESS,
        "allocation_generation": 1,
        "opcode_id": 42,
        "opcode": "ADDI",
        "arg_count": 3,
        "parsed_register_operands": registers,
        "operand_lineage_inventory": inventory,
    }


def rewrite(index: int, lineage: str, role: str, virtual: int, physical: int, sequence: int) -> dict[str, object]:
    return {
        "pcode_id": "pc-0",
        "operand_index": index,
        "operand_lineage_id": lineage,
        "role": role,
        "class_id": 0,
        "class_name": "gpr",
        "virtual_kind": "r",
        "virtual": virtual,
        "ig_id": virtual,
        "allocated_physical": physical,
        "pcode_event_sequence": sequence,
        "instrumented_site_id": "rewrite-1",
        "runtime_address": PC_ADDRESS,
        "allocation_generation": 1,
        "lifecycle_sequence_at_capture": 0,
        "source_stage": "allocator_operand_rewrite",
        "confidence": "observed",
    }


def minimal_payload(*, reordered: bool = False) -> dict[str, object]:
    initial = [operand(0, "ol-0", 7, "a"), operand(1, "ol-1", 7, "b"), operand(2, "ol-2", 1, "c")]
    lineages = ("ol-1", "ol-0") if reordered else ("ol-0", "ol-1")
    physicals = (21, 22) if reordered else (22, 21)
    code_bytes = "3ab60000" if reordered else "3ad50000"
    final = [operand(0, lineages[0], 8, "d"), operand(1, lineages[1], 8, "e"), operand(2, "ol-2", 1, "f")]
    mappings = [
        {
            "instruction_offset_within_range": 0,
            "machine_operand_position": 0,
            "machine_operand_key": "def:0",
            "emission_pcode_operand_index": 0,
            "operand_lineage_id": lineages[0],
            "physical_register": physicals[0],
        },
        {
            "instruction_offset_within_range": 0,
            "machine_operand_position": 1,
            "machine_operand_key": "use:0",
            "emission_pcode_operand_index": 1,
            "operand_lineage_id": lineages[1],
            "physical_register": physicals[1],
        },
    ]
    instruction = {
        "pcode_id": "pc-0",
        "runtime_address": PC_ADDRESS,
        "allocation_generation": 1,
        "block_order": 0,
        "instruction_order": 0,
        "function_symbol": "fn",
        "section_name": ".text",
        "coordinate_space": "function-relative-bytes",
        "stage_snapshots": [snapshot("allocator_input"), snapshot("code_emission", reordered=reordered)],
        "emission_event_sequence": 3,
        "emission_site_id": "emit-1",
        "emission_runtime_address": PC_ADDRESS,
        "emission_allocation_generation": 1,
        "emission_lifecycle_sequence_at_capture": 0,
        "code_ranges": [
            {
                "start": 0,
                "end_exclusive": 4,
                "bytes": code_bytes,
                "relocations": [],
                "machine_operand_mappings": mappings,
            }
        ],
        "cross_stage_identity_confidence": "derived-unique",
    }
    mutation = {
        "pcode_event_sequence": 2,
        "instrumented_site_id": "mutation-1",
        "mutation_kind": "update",
        "inputs": [state(initial)],
        "outputs": [state(final)],
    }
    pcode_coverage = {
        "status": "complete",
        "operand_rewrite_sites_expected": 1,
        "operand_rewrite_sites_hooked": 1,
        "operand_mutation_sites_expected": 1,
        "operand_mutation_sites_hooked": 1,
        "code_emission_sites_expected": 1,
        "code_emission_sites_hooked": 1,
        "first_event_sequence": 0,
        "last_event_sequence": 3,
        "parsed_register_operands": 2,
        "allocatable_register_operands": 2,
        "fixed_physical_register_operands": 0,
        "rewrite_events": 2,
        "mutation_events": 1,
        "final_pcodes": 1,
        "emission_events": 1,
        "event_cap": 64,
        "dropped_events": 0,
        "truncated": False,
        "errors": [],
    }
    return {
        "lifecycle_events": [
            {
                "sequence": 0,
                "event": "allocate",
                "entity_kind": "pcode",
                "runtime_address": PC_ADDRESS,
                "allocation_generation": 1,
                "instrumented_site_id": "pcode-alloc-1",
                "compiler_stage": "backend-lowering",
            }
        ],
        "coverage": {
            "pcode_instrumentation": pcode_coverage,
            "pcode_instructions_seen": 1,
            "pcode_occurrences_seen": 2,
            "caps": {"max_pcode_instructions": 4, "max_pcode_operands_per_instruction": 4},
            "truncated": False,
            "errors": [],
        },
        "pcode_instructions": [instruction],
        "pcode_occurrences": [
            rewrite(0, "ol-0", "def", 67, 22, 0),
            rewrite(1, "ol-1", "use", 66, 21, 1),
        ],
        "pcode_operand_lineage_events": [mutation],
    }


def test_valid_reorder_preserves_lineage_not_operand_index(tmp_path: Path) -> None:
    candidate_object = tmp_path / "reordered.o"
    candidate_object.write_bytes(_candidate_elf(bytes.fromhex("3ab60000")))
    result = validate_pcode_lineage(minimal_payload(reordered=True), trusted_proof(), candidate_object, "fn")

    binding = result.anchor_bindings[(0, "def:0")]
    assert binding.virtual == 66
    assert binding.operand_lineage_id == "ol-1"
    assert binding.confidence == "derived-unique"
    assert result.capabilities == frozenset({"pcode-to-code-range"})
    assert result.errors == ()


def test_result_and_normalized_payload_are_deeply_immutable(candidate_object: Path) -> None:
    payload = minimal_payload()
    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")
    payload["pcode_instructions"][0]["pcode_id"] = "attacker"

    assert isinstance(result.normalized, MappingProxyType)
    assert result.normalized["pcode_instructions"][0]["pcode_id"] == "pc-0"
    with pytest.raises(TypeError):
        result.normalized["new"] = 1
    with pytest.raises(TypeError):
        result.anchor_bindings[(4, "use:0")] = next(iter(result.anchor_bindings.values()))


@pytest.mark.parametrize("hostile", [True, 1.0, 2**53, "\ud800"])
def test_noncanonical_numeric_or_text_values_fail_closed(candidate_object: Path, hostile: object) -> None:
    payload = minimal_payload()
    payload["pcode_instructions"][0]["block_order"] = hostile

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert result.capabilities == frozenset()
    assert result.errors


def test_recursive_or_mutable_shapes_never_raise(candidate_object: Path) -> None:
    payload = minimal_payload()
    payload["pcode_instructions"].append(payload)

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert result.capabilities == frozenset()
    assert any("malformed" in error or "normalization" in error for error in result.errors)


@pytest.mark.parametrize(
    ("fixture_name", "message"),
    [
        ("self_parent.json", "self-parented lineage"),
        ("fresh_clone_id.json", "clone may not define fresh lineage"),
        ("duplicate_output.json", "duplicate output pcode_id"),
        ("missing_emission.json", "final PCode has no emission event"),
        ("wrong_machine_register.json", "decoded physical register mismatch"),
    ],
)
def test_invalid_lineage_fixtures_fail_closed(fixture_name: str, message: str, candidate_object: Path) -> None:
    fixture = json.loads((FIXTURE_ROOT / fixture_name).read_text())
    payload = minimal_payload()
    event = payload["pcode_operand_lineage_events"][0]
    if fixture_name == "self_parent.json":
        event["outputs"][0]["operands"][0] = operand(0, "ol-3", 8, "d", ["ol-3"])
    elif fixture_name == "fresh_clone_id.json":
        event["mutation_kind"] = "clone"
        event["outputs"].append(copy.deepcopy(event["outputs"][0]))
        event["outputs"][0]["pcode_id"] = "pc-1"
        event["outputs"][0]["runtime_address"] = 0x3000
        event["outputs"][0]["operands"][0] = operand(0, "ol-3", 8, "d", ["ol-0"])
    elif fixture_name == "duplicate_output.json":
        event["mutation_kind"] = "clone"
        event["outputs"].append(copy.deepcopy(event["outputs"][0]))
    elif fixture_name == "missing_emission.json":
        payload["pcode_instructions"][0]["emission_event_sequence"] = None
    elif fixture_name == "wrong_machine_register.json":
        payload["pcode_instructions"][0]["code_ranges"][0]["machine_operand_mappings"][0]["physical_register"] = 20
    assert fixture["expected"] == message

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert any(message in error for error in result.errors)
    assert result.capabilities == frozenset()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["lifecycle_events"][0].update({"allocation_generation": 2}), "generation"),
        (lambda p: p["pcode_occurrences"].pop(), "exactly one rewrite"),
        (lambda p: p["pcode_occurrences"].append(copy.deepcopy(p["pcode_occurrences"][0])), "exactly one rewrite"),
        (lambda p: p["pcode_occurrences"][0].update({"instrumented_site_id": "unknown"}), "unknown rewrite site"),
        (
            lambda p: p["pcode_operand_lineage_events"][0].update({"instrumented_site_id": "unknown"}),
            "unknown mutation site",
        ),
        (lambda p: p["pcode_instructions"][0].update({"emission_site_id": "unknown"}), "unknown emission site"),
        (lambda p: p["pcode_occurrences"][0].update({"pcode_event_sequence": 4}), "PCode event sequence"),
        (
            lambda p: p["pcode_operand_lineage_events"][0]["inputs"][0]["operands"][0].update(
                {"raw_payload_sha256": "9" * 64}
            ),
            "input state disagrees",
        ),
        (
            lambda p: p["pcode_operand_lineage_events"][0]["outputs"][0]["operands"].pop(),
            "operand count does not match arg_count",
        ),
        (lambda p: p["pcode_instructions"][0]["stage_snapshots"][1].update({"opcode": "LI"}), "opcode mnemonic"),
        (
            lambda p: p["pcode_instructions"][0]["stage_snapshots"][0]["parsed_register_operands"][0].update(
                {"allocation_requirement": "fixed-physical"}
            ),
            "allocation requirement",
        ),
        (lambda p: p["coverage"]["pcode_instrumentation"].update({"status": "partial"}), "status must be complete"),
        (lambda p: p["coverage"]["pcode_instrumentation"].update({"dropped_events": 1}), "events were dropped"),
        (lambda p: p["coverage"]["pcode_instrumentation"].update({"event_cap": 4}), "event cap was reached"),
        (
            lambda p: p["coverage"]["pcode_instrumentation"].update({"rewrite_events": 99}),
            "rewrite_events does not match",
        ),
        (lambda p: p["coverage"].update({"pcode_instructions_seen": 99}), "pcode_instructions_seen does not match"),
    ],
)
def test_replay_and_coverage_negative_matrix(candidate_object: Path, mutate, message: str) -> None:
    payload = minimal_payload()
    mutate(payload)

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert any(message in error for error in result.errors), result.errors
    assert result.capabilities == frozenset()


def test_multi_parent_lineage_retains_diagnostics_but_abstains(candidate_object: Path) -> None:
    payload = minimal_payload()
    output = payload["pcode_operand_lineage_events"][0]["outputs"][0]["operands"]
    output[0] = operand(0, "ol-3", 8, "d", ["ol-0", "ol-1"])
    emission = payload["pcode_instructions"][0]["stage_snapshots"][1]
    emission["operand_lineage_inventory"][0] = operand(0, "ol-3", 8, "d")
    emission["parsed_register_operands"][0]["operand_lineage_id"] = "ol-3"
    payload["pcode_instructions"][0]["code_ranges"][0]["machine_operand_mappings"][0]["operand_lineage_id"] = "ol-3"

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert any("multiple allocator origins" in error for error in result.errors)
    assert result.anchor_bindings == {}
    assert result.capabilities == frozenset()


def test_fixed_physical_operand_needs_no_allocator_rewrite(candidate_object: Path) -> None:
    payload = minimal_payload()
    first = payload["pcode_instructions"][0]["stage_snapshots"][0]
    first["operand_lineage_inventory"][1].update({"raw_arg_kind_id": 8})
    first["parsed_register_operands"][1] = parsed(
        1,
        "ol-1",
        "use",
        kind=8,
        requirement="fixed-physical",
        virtual=None,
        physical=21,
    )
    mutation = payload["pcode_operand_lineage_events"][0]
    mutation["inputs"][0]["operands"][1].update({"raw_arg_kind_id": 8})
    payload["pcode_occurrences"].pop()
    mutation["pcode_event_sequence"] = 1
    payload["pcode_instructions"][0]["emission_event_sequence"] = 2
    coverage = payload["coverage"]["pcode_instrumentation"]
    coverage.update(
        {
            "last_event_sequence": 2,
            "allocatable_register_operands": 1,
            "fixed_physical_register_operands": 1,
            "rewrite_events": 1,
        }
    )
    payload["coverage"]["pcode_occurrences_seen"] = 1

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert result.errors == ()
    assert (0, "use:0") not in result.anchor_bindings
    assert result.capabilities == frozenset({"pcode-to-code-range"})


def test_non_emitted_deleted_pcode_may_not_claim_code_ranges(candidate_object: Path) -> None:
    payload = minimal_payload()
    instruction = payload["pcode_instructions"][0]
    instruction["stage_snapshots"].pop()
    instruction.update(
        {
            "emission_event_sequence": None,
            "emission_site_id": None,
            "emission_runtime_address": None,
            "emission_allocation_generation": None,
            "emission_lifecycle_sequence_at_capture": None,
            "cross_stage_identity_confidence": None,
        }
    )
    mutation = payload["pcode_operand_lineage_events"][0]
    mutation.update({"mutation_kind": "delete", "outputs": []})
    coverage = payload["coverage"]["pcode_instrumentation"]
    coverage.update({"last_event_sequence": 2, "final_pcodes": 0, "emission_events": 0})

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert any("non-emitted PCode must have no code ranges" in error for error in result.errors)
    assert result.capabilities == frozenset()


def test_delete_consumes_complete_state_and_allows_empty_final_set(candidate_object: Path) -> None:
    payload = minimal_payload()
    instruction = payload["pcode_instructions"][0]
    instruction["stage_snapshots"].pop()
    instruction.update(
        {
            "emission_event_sequence": None,
            "emission_site_id": None,
            "emission_runtime_address": None,
            "emission_allocation_generation": None,
            "emission_lifecycle_sequence_at_capture": None,
            "code_ranges": [],
            "cross_stage_identity_confidence": None,
        }
    )
    mutation = payload["pcode_operand_lineage_events"][0]
    mutation.update({"mutation_kind": "delete", "outputs": []})
    payload["coverage"]["pcode_instrumentation"].update(
        {"last_event_sequence": 2, "final_pcodes": 0, "emission_events": 0}
    )

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert result.errors == ()
    assert result.anchor_bindings == {}
    assert result.capabilities == frozenset({"pcode-to-code-range"})


def test_create_defines_fresh_parentless_lineages(candidate_object: Path) -> None:
    payload = minimal_payload()
    instruction = payload["pcode_instructions"][0]
    emission = copy.deepcopy(instruction["stage_snapshots"][1])
    first = copy.deepcopy(emission)
    first["stage"] = "mutation_output"
    instruction["stage_snapshots"] = [first, emission]
    instruction["emission_event_sequence"] = 1
    final_operands = copy.deepcopy(emission["operand_lineage_inventory"])
    created_operands = [{**item, "parent_lineage_ids": []} for item in final_operands]
    payload["pcode_occurrences"] = []
    payload["pcode_operand_lineage_events"] = [
        {
            "pcode_event_sequence": 0,
            "instrumented_site_id": "mutation-1",
            "mutation_kind": "create",
            "inputs": [],
            "outputs": [state(created_operands)],
        }
    ]
    payload["coverage"]["pcode_occurrences_seen"] = 0
    payload["coverage"]["pcode_instrumentation"].update(
        {
            "last_event_sequence": 1,
            "allocatable_register_operands": 0,
            "fixed_physical_register_operands": 2,
            "rewrite_events": 0,
        }
    )

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert result.errors == ()
    assert result.anchor_bindings == {}
    assert result.capabilities == frozenset({"pcode-to-code-range"})


def cloned_payload() -> dict[str, object]:
    payload = minimal_payload()
    payload["lifecycle_events"].append(
        {
            "sequence": 1,
            "event": "allocate",
            "entity_kind": "pcode",
            "runtime_address": 0x3000,
            "allocation_generation": 1,
            "instrumented_site_id": "pcode-alloc-1",
            "compiler_stage": "backend-lowering",
        }
    )
    original = payload["pcode_instructions"][0]
    clone = copy.deepcopy(original)
    clone.update(
        {
            "pcode_id": "pc-1",
            "runtime_address": 0x3000,
            "instruction_order": 1,
            "emission_event_sequence": 4,
            "emission_runtime_address": 0x3000,
            "emission_lifecycle_sequence_at_capture": 1,
        }
    )
    first = copy.deepcopy(clone["stage_snapshots"][1])
    first.update(
        {
            "stage": "mutation_output",
            "runtime_address": 0x3000,
            "lifecycle_sequence_at_capture": 1,
        }
    )
    emission = copy.deepcopy(first)
    emission["stage"] = "code_emission"
    clone["stage_snapshots"] = [first, emission]
    clone["code_ranges"][0].update({"start": 4, "end_exclusive": 8})
    original["emission_event_sequence"] = 3
    payload["pcode_instructions"].append(clone)
    mutation = payload["pcode_operand_lineage_events"][0]
    mutation.update(
        {
            "mutation_kind": "clone",
            "outputs": [
                mutation["outputs"][0],
                state(
                    copy.deepcopy(emission["operand_lineage_inventory"]),
                    sequence=1,
                    pcode_id="pc-1",
                    address=0x3000,
                ),
            ],
        }
    )
    payload["coverage"]["pcode_instructions_seen"] = 2
    payload["coverage"]["pcode_instrumentation"].update(
        {
            "last_event_sequence": 4,
            "parsed_register_operands": 4,
            "fixed_physical_register_operands": 2,
            "final_pcodes": 2,
            "emission_events": 2,
        }
    )
    return payload


def test_clone_may_preserve_input_and_reuse_lineages_in_new_output(tmp_path: Path) -> None:
    candidate = tmp_path / "clone.o"
    candidate.write_bytes(_candidate_elf(bytes.fromhex("3ad500003ad50000")))

    result = validate_pcode_lineage(cloned_payload(), trusted_proof(), candidate, "fn")

    assert result.errors == ()
    assert set(result.anchor_bindings) == {
        (0, "def:0"),
        (0, "use:0"),
        (4, "def:0"),
        (4, "use:0"),
    }
    assert result.capabilities == frozenset({"pcode-to-code-range"})


def test_replace_requires_disjoint_ids_and_consumes_input(tmp_path: Path) -> None:
    candidate = tmp_path / "replace.o"
    candidate.write_bytes(_candidate_elf(bytes.fromhex("3ad500003ad50000")))
    payload = cloned_payload()
    original = payload["pcode_instructions"][0]
    original["stage_snapshots"].pop()
    original.update(
        {
            "emission_event_sequence": None,
            "emission_site_id": None,
            "emission_runtime_address": None,
            "emission_allocation_generation": None,
            "emission_lifecycle_sequence_at_capture": None,
            "code_ranges": [],
            "cross_stage_identity_confidence": None,
        }
    )
    clone = payload["pcode_instructions"][1]
    clone["emission_event_sequence"] = 3
    mutation = payload["pcode_operand_lineage_events"][0]
    mutation.update({"mutation_kind": "replace", "outputs": [mutation["outputs"][1]]})
    payload["coverage"]["pcode_instrumentation"].update(
        {"last_event_sequence": 3, "final_pcodes": 1, "emission_events": 1}
    )

    result = validate_pcode_lineage(payload, trusted_proof(), candidate, "fn")

    assert result.errors == ()
    assert set(result.anchor_bindings) == {(4, "def:0"), (4, "use:0")}
    assert result.capabilities == frozenset({"pcode-to-code-range"})


def test_mutation_states_require_canonical_identity_order(tmp_path: Path) -> None:
    candidate = tmp_path / "clone.o"
    candidate.write_bytes(_candidate_elf(bytes.fromhex("3ad500003ad50000")))
    payload = cloned_payload()
    payload["pcode_operand_lineage_events"][0]["outputs"].reverse()

    result = validate_pcode_lineage(payload, trusted_proof(), candidate, "fn")

    assert any("outputs must be canonically ordered" in error for error in result.errors)
    assert result.capabilities == frozenset()


@pytest.mark.parametrize(
    ("elf_kwargs", "payload_mutation", "message"),
    [
        ({"function": "other"}, None, "expected one defined function symbol"),
        ({"duplicate_function": True}, None, "expected one defined function symbol"),
        ({"function_size": 0}, None, "positive size"),
        (
            {},
            lambda p: p["pcode_instructions"][0]["code_ranges"][0].update({"end_exclusive": 8}),
            "outside function extent",
        ),
        (
            {},
            lambda p: p["pcode_instructions"][0]["code_ranges"][0].update({"bytes": "60000000"}),
            "candidate object bytes disagree",
        ),
    ],
)
def test_candidate_elf_negative_matrix(
    tmp_path: Path, elf_kwargs: dict[str, object], payload_mutation, message: str
) -> None:
    path = tmp_path / "candidate.o"
    path.write_bytes(_candidate_elf(**elf_kwargs))
    payload = minimal_payload()
    if payload_mutation:
        payload_mutation(payload)

    result = validate_pcode_lineage(payload, trusted_proof(), path, "fn")

    assert any(message in error for error in result.errors), result.errors
    assert result.capabilities == frozenset()


def test_exact_relocation_tuple_is_required(tmp_path: Path) -> None:
    path = tmp_path / "candidate.o"
    path.write_bytes(_candidate_elf(relocation=(2, 6, "target", -4)))
    payload = minimal_payload()
    relocation = {
        "offset_within_range": 2,
        "relocation_type_id": 6,
        "target_symbol_table_index": 2,
        "target_symbol": "target",
        "addend": -4,
    }
    payload["pcode_instructions"][0]["code_ranges"][0]["relocations"] = [relocation]

    valid = validate_pcode_lineage(payload, trusted_proof(), path, "fn")
    assert valid.errors == ()

    payload["pcode_instructions"][0]["code_ranges"][0]["relocations"][0]["addend"] = -3
    invalid = validate_pcode_lineage(payload, trusted_proof(), path, "fn")
    assert any("relocations disagree" in error for error in invalid.errors)
    assert invalid.capabilities == frozenset()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("machine_operand_key", "use:0", "machine operand key"),
        ("machine_operand_position", 1, "exactly one mapping"),
        ("emission_pcode_operand_index", 1, "operand index or lineage"),
        ("operand_lineage_id", "ol-1", "operand index or lineage"),
        ("physical_register", 20, "decoded physical register mismatch"),
    ],
)
def test_machine_mapping_negative_matrix(candidate_object: Path, field: str, value: object, message: str) -> None:
    payload = minimal_payload()
    payload["pcode_instructions"][0]["code_ranges"][0]["machine_operand_mappings"][0][field] = value

    result = validate_pcode_lineage(payload, trusted_proof(), candidate_object, "fn")

    assert any(message in error for error in result.errors), result.errors
    assert result.capabilities == frozenset()


def test_overlapping_ranges_retain_rejected_alternatives(tmp_path: Path) -> None:
    path = tmp_path / "candidate.o"
    path.write_bytes(_candidate_elf(code=bytes.fromhex("3ad500003ad50000")))
    payload = minimal_payload()
    duplicate = copy.deepcopy(payload["pcode_instructions"][0])
    duplicate.update({"pcode_id": "pc-1", "runtime_address": 0x3000, "instruction_order": 1})
    payload["pcode_instructions"].append(duplicate)
    payload["coverage"]["pcode_instructions_seen"] = 2

    result = validate_pcode_lineage(payload, trusted_proof(), path, "fn")

    assert any("overlap" in error for error in result.errors)
    assert result.capabilities == frozenset()


def test_api_never_raises_for_bad_payload_proof_path_or_function(tmp_path: Path) -> None:
    cases = [
        (None, trusted_proof(), tmp_path / "missing.o", "fn"),
        ({}, object(), tmp_path, "fn"),
        (minimal_payload(), trusted_proof(), tmp_path / "missing.o", "\ud800"),
    ]

    for args in cases:
        result = validate_pcode_lineage(*args)
        assert isinstance(result, PCodeLineageValidation)
        assert result.capabilities == frozenset()
        assert result.errors


def test_binding_value_is_frozen() -> None:
    binding = AnchorVirtualBinding(0, "use:0", "pc-0", "ol-1", 0, 66, 21, "derived-unique")
    with pytest.raises(Exception):
        binding.virtual = 99
