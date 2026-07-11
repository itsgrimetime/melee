from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Callable

import pytest

from src.mwcc_debug.causal_diff.asm_adapter import adapt_checkdiff
from src.mwcc_debug.causal_diff.backend_adapter import _confidence, _operand_roles, adapt_backends
from src.mwcc_debug.causal_diff.bundles import (
    CORE_BACKEND_CAPABILITIES,
    BundleInputError,
    ValidatedBundle,
    load_bundle,
    validate_capability_union,
)
from src.mwcc_debug.causal_diff.canonical import canonical_bytes
from src.mwcc_debug.causal_diff.models import Confidence
from src.mwcc_debug.parser import Instruction

FIXTURES = Path(__file__).parent / "fixtures"
FUNCTION = "mnDiagram_DrawFighterHeaders"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compile_id(
    *,
    function: str,
    flags_digest: str,
    environment_digest: str,
    source_digest: str,
) -> str:
    return _sha256(
        canonical_bytes(
            {
                "function": function,
                "compiler": "mwcc_233_163n",
                "target_build": "GALE01",
                "flags_digest": flags_digest,
                "environment_digest": environment_digest,
                "source_digest": source_digest,
            }
        )
    )


def _direct_pcdump() -> str:
    text = (FIXTURES / "mwcc_debug" / "gm_80173EEC_pcdump.txt").read_text()
    text = text.replace("gm_80173EEC", FUNCTION)
    text, replacements = re.subn(
        r"(?m)^28\s+62\s+r29\s+13\s+16\s+0x02$",
        "28    66      r21        13      16      0x02",
        text,
    )
    assert replacements == 1
    return text


def _checkdiff_payload() -> dict[str, object]:
    return {
        "function": FUNCTION,
        "classification": {
            "stack_slot_localizer": {
                "mismatch_count": 1,
                "mismatches": [{"expected_offset": 56, "current_offset": 60}],
            }
        },
        "target_asm": [
            f"<{FUNCTION}>",
            "+230: 80 61 00 08 \tlwz     r3,8(r1)",
            "+234: 3a d5 00 01 \taddi    r22,r21,1",
            "+238: 48 00 00 01 \tbl      <helper>",
            "+238: \t.reloc *, R_PPC_REL24, helper",
        ],
        "current_asm": [
            f"<{FUNCTION}>",
            "+230: 80 61 00 08 \tlwz     r3,8(r1)",
            "+234: 3a 93 00 01 \taddi    r20,r19,1",
            "+238: 48 00 00 01 \tbl      <helper>",
            "+238: \t.reloc *, R_PPC_REL24, helper",
        ],
    }


@pytest.fixture
def validated_bundle(tmp_path: Path) -> Callable[[str], ValidatedBundle]:
    def build(kind: str) -> ValidatedBundle:
        directory = tmp_path / kind
        directory.mkdir()
        if kind.startswith("direct"):
            function = FUNCTION
            source = f"void {FUNCTION}(void) {{}}\n"
            backend_text = _direct_pcdump()
            if kind == "direct-unknown-role":
                backend_text, replacements = re.subn(
                    r"(?m)^    add     (r\d+,r\d+,r\d+)$",
                    r"    unknown \1",
                    backend_text,
                    count=1,
                )
                assert replacements == 1
            elif kind == "direct-prefix-near-miss":
                backend_text, replacements = re.subn(
                    r"(?m)^    addi    (r\d+,r\d+,[^\n]+)$",
                    r"    addi_fake \1",
                    backend_text,
                    count=1,
                )
                assert replacements == 1
            backend_format = "mwcc-debug-pcdump"
            capabilities = sorted(CORE_BACKEND_CAPABILITIES)
            checkdiff = _checkdiff_payload()
            if kind == "direct-wrong-function":
                checkdiff["function"] = "other_function"
        else:
            function = "test_fn"
            source = "void test_fn(void) {}\n"
            backend_text = (FIXTURES / "retro" / "backend_trace_v1_minimal.json").read_text()
            if kind == "malformed-trace":
                backend_text = "{}"
            elif kind == "malformed-edge-trace":
                backend_payload = json.loads(backend_text)
                backend_payload["functions"][0]["regalloc"]["classes"][0]["edges"][0].pop("a")
                backend_text = json.dumps(backend_payload)
            elif kind == "trace-missing-edge-confidence":
                backend_payload = json.loads(backend_text)
                backend_payload["functions"][0]["regalloc"]["classes"][0]["edges"][0].pop("confidence")
                backend_text = json.dumps(backend_payload)
            backend_format = "backend-trace.v1"
            capabilities = ["allocator-decisions", "interference-edges"]
            checkdiff = {
                "function": function,
                "classification": {},
                "target_asm": ["<test_fn>", "+000: 4e 80 00 20 \tblr"],
                "current_asm": ["<test_fn>", "+000: 4e 80 00 20 \tblr"],
            }

        checkdiff_json = json.dumps(checkdiff, indent=2 if kind == "direct-crlf" else None) + "\n"
        if kind == "direct-crlf":
            checkdiff_json = checkdiff_json.replace("\n", "\r\n")
        artifacts = {
            "source": ("candidate.c", source.encode()),
            "checkdiff": ("checkdiff.json", checkdiff_json.encode()),
            "backend": ("backend.txt", backend_text.encode()),
            "inspector": ("inspector.txt", f"Function: {function}\n".encode()),
        }
        digests: dict[str, str] = {}
        for name, (filename, data) in artifacts.items():
            (directory / filename).write_bytes(data)
            digests[name] = _sha256(data)

        target_assembly = checkdiff["target_asm"]
        assert isinstance(target_assembly, list)
        expected_assembly = ("\n".join(target_assembly).rstrip() + "\n").encode()
        flags_digest = _sha256(b"-O4,p -proc gekko")
        environment_digest = _sha256(b"causal-adapter-test-env")
        compile_id = _compile_id(
            function=function,
            flags_digest=flags_digest,
            environment_digest=environment_digest,
            source_digest=digests["source"],
        )
        payload = {
            "schema_version": "causal-frontier-bundle.v1",
            "label": kind,
            "function": function,
            "compile": {
                "id": compile_id,
                "compiler": "mwcc_233_163n",
                "target_build": "GALE01",
                "flags_digest": flags_digest,
                "environment_digest": environment_digest,
                "source_digest": digests["source"],
                "expected_assembly_digest": _sha256(expected_assembly),
            },
            "artifacts": {
                "source": {"path": artifacts["source"][0], "sha256": digests["source"]},
                "checkdiff": {"path": artifacts["checkdiff"][0], "sha256": digests["checkdiff"]},
                "backend": [
                    {
                        "path": artifacts["backend"][0],
                        "sha256": digests["backend"],
                        "format": backend_format,
                        "capabilities": capabilities,
                    }
                ],
                "inspector": {"path": artifacts["inspector"][0], "sha256": digests["inspector"]},
            },
            "producer_versions": {
                "checkdiff": "checkdiff-json.v1",
                "mwcc_debug": "mwcc-debug-pcdump.v1",
                "backend_trace": "backend-trace.v1",
            },
        }
        manifest = directory / "bundle.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        return load_bundle(manifest, cli_label=kind, function=function)

    return build


def test_checkdiff_adapter_indexes_retail_offsets(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    evidence = adapt_checkdiff(validated_bundle("direct"))
    row = evidence.rows_by_offset[0x234]
    assert row.expected.opcode == "addi"
    assert row.expected.regs == (("r", 22), ("r", 21))
    assert row.current.regs == (("r", 20), ("r", 19))
    retail = next(
        node
        for node in evidence.result.nodes
        if node.kind == "retail-instruction" and node.attributes["offset"] == 0x234
    )
    candidate = next(
        node
        for node in evidence.result.nodes
        if node.kind == "candidate-instruction" and node.attributes["offset"] == 0x234
    )
    assert retail.attributes["neighborhood_signature"]
    assert candidate.attributes["aligned_retail_offset"] == 0x234


def test_checkdiff_adapter_deep_freezes_stack_localizer(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    evidence = adapt_checkdiff(validated_bundle("direct"))
    assert evidence.stack_slot_localizer is not None
    mismatches = evidence.stack_slot_localizer["mismatches"]
    with pytest.raises(TypeError):
        mismatches[0]["expected_offset"] = 0


def test_checkdiff_adapter_provenance_uses_original_crlf_byte_offsets(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    bundle = validated_bundle("direct-crlf")
    evidence = adapt_checkdiff(bundle)
    node = next(
        node
        for node in evidence.result.nodes
        if node.kind == "retail-instruction" and node.attributes["offset"] == 0x234
    )
    raw = bundle.artifact_paths["checkdiff"].read_bytes()
    assert node.provenance.raw_start is not None
    assert node.provenance.raw_end is not None
    assert json.dumps(node.attributes["raw"]).encode() == raw[node.provenance.raw_start : node.provenance.raw_end]


def test_checkdiff_adapter_rejects_wrong_function_and_version(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    with pytest.raises(BundleInputError, match="checkdiff function"):
        adapt_checkdiff(validated_bundle("direct-wrong-function"))

    bundle = validated_bundle("direct")
    manifest = bundle.manifest.model_copy(
        update={"producer_versions": {**bundle.manifest.producer_versions, "checkdiff": "unknown.v2"}}
    )
    with pytest.raises(BundleInputError, match="producer version"):
        adapt_checkdiff(replace(bundle, manifest=manifest))


def test_backend_adapter_verifies_all_pcdump_capabilities(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    bundle = validated_bundle("direct")
    evidence = adapt_backends(bundle)
    assert evidence.verified_capabilities == CORE_BACKEND_CAPABILITIES
    node = next(
        node for node in evidence.result.nodes if node.kind == "allocator-node" and node.attributes["ig_id"] == 66
    )
    assert node.attributes["assigned_phys"] == 21
    assert node.attributes["first_def_signature"] == "mr r#,r#"
    assert node.provenance.raw_start == 0
    assert node.provenance.raw_end == len(bundle.artifact_paths["backend[0]"].read_bytes())
    assert evidence.role_compile.name == FUNCTION


def test_pcdump_role_chain_records_are_diagnostic(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    evidence = adapt_backends(validated_bundle("direct"))
    pcode = next(
        node for node in evidence.result.nodes if node.kind == "pcode-occurrence" and node.attributes.get("regs")
    )
    use_def = next(
        edge
        for edge in evidence.result.edges
        if edge.source_id == pcode.record_id and edge.kind in {"uses-virtual", "defines-virtual"}
    )
    mapping = next(
        edge
        for edge in evidence.result.edges
        if edge.kind == "maps-to-allocator-node" and edge.source_id == use_def.target_id
    )

    assert pcode.provenance.parser == "mwcc-debug-pcdump.v1"
    assert pcode.confidence is Confidence.HEURISTIC
    assert use_def.confidence is Confidence.HEURISTIC
    assert mapping.confidence is Confidence.HEURISTIC


def test_pcode_operand_roles_handle_update_and_read_modify_write() -> None:
    stwu = Instruction("stwu", "r32,-32(r33)", [], [("r", 32), ("r", 33)])
    stwux = Instruction("stwux", "r32,r33,r34", [], [("r", 32), ("r", 33), ("r", 34)])
    rlwimi = Instruction("rlwimi", "r34,r35,8,0,23", [], [("r", 34), ("r", 35)])
    fcmpu = Instruction("fcmpu", "cr0,f36,f37", [], [("f", 36), ("f", 37)])
    unknown = Instruction("unknown", "r36,r37", [], [("r", 36), ("r", 37)])

    assert _operand_roles(stwu, "mwcc-debug-pcdump.v1") == (
        (frozenset({"use"}), frozenset({"use", "def"})),
        Confidence.OBSERVED,
    )
    assert _operand_roles(stwux, "mwcc-debug-pcdump.v1") == (
        (frozenset({"use"}), frozenset({"use", "def"}), frozenset({"use"})),
        Confidence.OBSERVED,
    )
    assert _operand_roles(rlwimi, "mwcc-debug-pcdump.v1") == (
        (frozenset({"use", "def"}), frozenset({"use"})),
        Confidence.OBSERVED,
    )
    assert _operand_roles(fcmpu, "mwcc-debug-pcdump.v1") == (
        (frozenset({"use"}), frozenset({"use"})),
        Confidence.OBSERVED,
    )
    assert _operand_roles(unknown, "mwcc-debug-pcdump.v1")[1] is Confidence.HEURISTIC
    assert _confidence("observed") is Confidence.OBSERVED
    assert _confidence("high") is Confidence.HEURISTIC
    assert _confidence("exact") is Confidence.HEURISTIC


@pytest.mark.parametrize(
    ("opcode", "operands", "regs", "expected"),
    [
        ("cmp", "cr0,r32,r33", [("r", 32), ("r", 33)], ({"use"}, {"use"})),
        ("fmuls", "f32,f33,f34", [("f", 32), ("f", 33), ("f", 34)], ({"def"}, {"use"}, {"use"})),
        ("fsubs", "f32,f33,f34", [("f", 32), ("f", 33), ("f", 34)], ({"def"}, {"use"}, {"use"})),
        ("lbz", "r32,0(r33)", [("r", 32), ("r", 33)], ({"def"}, {"use"})),
        ("lbzx", "r32,(r33,r34)", [("r", 32), ("r", 33), ("r", 34)], ({"def"}, {"use"}, {"use"})),
        ("lfd", "f32,0(r33)", [("f", 32), ("r", 33)], ({"def"}, {"use"})),
        ("lfs", "f32,0(r33)", [("f", 32), ("r", 33)], ({"def"}, {"use"})),
        ("lis", "r32,17200", [("r", 32)], ({"def"},)),
        ("stfs", "f32,0(r33)", [("f", 32), ("r", 33)], ({"use"}, {"use"})),
        ("stw", "r32,0(r33)", [("r", 32), ("r", 33)], ({"use"}, {"use"})),
        ("xoris", "r32,r33,0x8000", [("r", 32), ("r", 33)], ({"def"}, {"use"})),
    ],
)
def test_pcode_operand_roles_cover_common_ppc_forms(
    opcode: str,
    operands: str,
    regs: list[tuple[str, int]],
    expected: tuple[set[str], ...],
) -> None:
    roles, confidence = _operand_roles(
        Instruction(opcode, operands, [], regs),
        "mwcc-debug-pcdump.v1",
    )
    assert roles == tuple(frozenset(role) for role in expected)
    assert confidence is Confidence.OBSERVED


def test_pcode_operand_role_contract_rejects_prefix_near_misses_and_unknown_versions() -> None:
    near_miss = Instruction("addi_fake", "r32,r33,1", [], [("r", 32), ("r", 33)])
    supported = Instruction("addi", "r32,r33,1", [], [("r", 32), ("r", 33)])

    assert _operand_roles(supported, "mwcc-debug-pcdump.v1")[1] is Confidence.OBSERVED
    assert _operand_roles(near_miss, "mwcc-debug-pcdump.v1")[1] is Confidence.HEURISTIC
    assert _operand_roles(supported, "mwcc-debug-pcdump.v2")[1] is Confidence.HEURISTIC


def test_unknown_pcode_role_does_not_verify_use_def_capability(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    evidence = adapt_backends(validated_bundle("direct-unknown-role"))
    assert "virtual-use-def" not in evidence.verified_capabilities
    occurrence = next(node for node in evidence.result.nodes if node.attributes.get("opcode") == "unknown")
    assert occurrence.confidence is Confidence.HEURISTIC
    virtual_ids = {
        edge.target_id
        for edge in evidence.result.edges
        if edge.source_id == occurrence.record_id and edge.kind in {"uses-virtual", "defines-virtual"}
    }
    assert virtual_ids
    assert all(
        node.confidence is Confidence.HEURISTIC for node in evidence.result.nodes if node.record_id in virtual_ids
    )

    near_miss = adapt_backends(validated_bundle("direct-prefix-near-miss"))
    assert "virtual-use-def" not in near_miss.verified_capabilities
    occurrence = next(node for node in near_miss.result.nodes if node.attributes.get("opcode") == "addi_fake")
    assert occurrence.confidence is Confidence.HEURISTIC


def test_allocator_only_trace_fails_core_capability_gate(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    bundle = validated_bundle("allocator-only")
    evidence = adapt_backends(bundle)
    with pytest.raises(BundleInputError, match="pcode-occurrences"):
        validate_capability_union(bundle, evidence.verified_capabilities)


def test_backend_trace_preserves_coalesce_and_omits_unknown_use_def_counts(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    evidence = adapt_backends(validated_bundle("allocator-only"))
    virtual = next(
        node for node in evidence.result.nodes if node.kind == "virtual-register" and node.attributes["virtual"] == 40
    )
    assert "definitions" not in virtual.attributes
    assert "uses" not in virtual.attributes
    coalesce = next(edge for edge in evidence.result.edges if edge.kind == "coalesces-with")
    assert coalesce.producer_confidence is Confidence.OBSERVED
    assert coalesce.attributes["producer_provenance"] == "coalesce_alias"


def test_backend_trace_missing_interference_confidence_is_heuristic(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    evidence = adapt_backends(validated_bundle("trace-missing-edge-confidence"))
    interference = next(edge for edge in evidence.result.edges if edge.kind == "interferes-with")
    assert interference.producer_confidence is Confidence.HEURISTIC


def test_backend_adapter_rejects_unknown_version_and_overlapping_artifacts(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    bundle = validated_bundle("direct")
    bad_manifest = bundle.manifest.model_copy(
        update={"producer_versions": {**bundle.manifest.producer_versions, "mwcc_debug": "unknown.v2"}}
    )
    with pytest.raises(BundleInputError, match="producer version"):
        adapt_backends(replace(bundle, manifest=bad_manifest))

    artifacts = bundle.manifest.artifacts.model_copy(
        update={"backend": (*bundle.manifest.artifacts.backend, bundle.manifest.artifacts.backend[0])}
    )
    manifest = bundle.manifest.model_copy(update={"artifacts": artifacts})
    paths = MappingProxyType({**bundle.artifact_paths, "backend[1]": bundle.artifact_paths["backend[0]"]})
    with pytest.raises(BundleInputError, match="overlapping backend evidence"):
        adapt_backends(replace(bundle, manifest=manifest, artifact_paths=paths))


def test_backend_adapter_wraps_malformed_fact_parser_errors(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    with pytest.raises(BundleInputError, match=r"invalid backend artifact 0 \(backend-trace.v1"):
        adapt_backends(validated_bundle("malformed-trace"))
    with pytest.raises(BundleInputError, match=r"invalid backend artifact 0 \(backend-trace.v1"):
        adapt_backends(validated_bundle("malformed-edge-trace"))


def test_backend_adapter_wraps_invalid_source_encoding(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    bundle = validated_bundle("direct")
    bundle.artifact_paths["source"].write_bytes(b"\xff")
    with pytest.raises(BundleInputError, match="invalid source artifact"):
        adapt_backends(bundle)


def test_backend_adapter_wraps_missing_backend_artifact_read(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    bundle = validated_bundle("direct")
    bundle.artifact_paths["backend[0]"].unlink()
    with pytest.raises(BundleInputError, match="cannot read backend artifact 0"):
        adapt_backends(bundle)


def test_alignment_edge_uses_input_provenance_without_synthetic_raw_span(
    validated_bundle: Callable[[str], ValidatedBundle],
) -> None:
    evidence = adapt_checkdiff(validated_bundle("direct"))
    alignment = next(edge for edge in evidence.result.edges if edge.kind == "aligns-to-retail")
    assert alignment.provenance.raw_start is None
    assert alignment.provenance.raw_end is None
    assert len(alignment.provenance.input_record_ids) == 2
