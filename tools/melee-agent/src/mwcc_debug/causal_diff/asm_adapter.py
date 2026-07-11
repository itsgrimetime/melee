"""Normalize immutable checkdiff JSON into compile-scoped evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .bundles import BundleInputError, ValidatedBundle
from .models import AdapterResult, Confidence, EvidenceEdge, EvidenceNode, Provenance

_PARSER_VERSION = "checkdiff-json.v1"
_OFFSET_ROW = re.compile(r"^\+(?P<offset>[0-9A-Fa-f]+):\s*(?P<body>.*)$")
_BYTE_PREFIX = re.compile(r"^(?:(?:[0-9A-Fa-f]{2})\s+){4}")
_REGISTER = re.compile(r"\b([rf])(\d+)\b")


@dataclass(frozen=True, slots=True)
class CheckdiffInstruction:
    offset: int
    opcode: str
    operands: str
    regs: tuple[tuple[str, int], ...]
    raw: str


@dataclass(frozen=True, slots=True)
class CheckdiffRow:
    offset: int
    expected: CheckdiffInstruction
    current: CheckdiffInstruction


@dataclass(frozen=True, slots=True)
class CheckdiffEvidence:
    result: AdapterResult
    rows_by_offset: Mapping[int, CheckdiffRow]
    stack_slot_localizer: Mapping[str, object] | None
    target_assembly: tuple[str, ...]
    current_assembly: tuple[str, ...]
    expected_assembly_digest: str


def _immutable_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _immutable_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_immutable_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_immutable_value(item) for item in value)
    return value


def _assembly_lines(payload: object, field: str) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        raise BundleInputError("checkdiff artifact must contain a JSON object")
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(line, str) for line in value):
        raise BundleInputError(f"checkdiff artifact field {field!r} must be a list of strings")
    return tuple(value)


def _parse_instruction(line: str) -> CheckdiffInstruction | None:
    match = _OFFSET_ROW.match(line.strip())
    if match is None:
        return None
    body = match.group("body").strip()
    if body.startswith("R_") or body.startswith(".reloc") or "\t.reloc" in match.group("body"):
        return None
    instruction_text = body.split("\t", 1)[-1].strip() if "\t" in body else _BYTE_PREFIX.sub("", body).strip()
    if not instruction_text or instruction_text.startswith("R_"):
        return None
    parts = instruction_text.split(None, 1)
    opcode = parts[0]
    operands = parts[1].strip() if len(parts) == 2 else ""
    return CheckdiffInstruction(
        offset=int(match.group("offset"), 16),
        opcode=opcode,
        operands=operands,
        regs=tuple((kind, int(number)) for kind, number in _REGISTER.findall(operands)),
        raw=line,
    )


def _indexed_instructions(lines: tuple[str, ...], *, side: str) -> dict[int, CheckdiffInstruction]:
    indexed: dict[int, CheckdiffInstruction] = {}
    for line in lines:
        instruction = _parse_instruction(line)
        if instruction is None:
            continue
        if instruction.offset in indexed:
            raise BundleInputError(f"checkdiff contains duplicate {side} instruction row at +{instruction.offset:x}")
        indexed[instruction.offset] = instruction
    return indexed


def _line_spans(raw_json: str, field: str, lines: tuple[str, ...]) -> dict[int, tuple[int, int]]:
    key_start = raw_json.find(json.dumps(field))
    cursor = 0 if key_start < 0 else key_start
    spans: dict[int, tuple[int, int]] = {}
    for line in lines:
        token = json.dumps(line, ensure_ascii=False)
        start = raw_json.find(token, cursor)
        if start < 0:
            continue
        raw_start = len(raw_json[:start].encode("utf-8"))
        raw_end = raw_start + len(token.encode("utf-8"))
        instruction = _parse_instruction(line)
        if instruction is not None:
            spans[instruction.offset] = (raw_start, raw_end)
        cursor = start + len(token)
    return spans


def _provenance(
    bundle: ValidatedBundle,
    *,
    raw_start: int | None,
    raw_end: int | None,
    derivation_rule: str,
    input_record_ids: tuple[str, ...] = (),
) -> Provenance:
    return Provenance(
        artifact_sha256=bundle.manifest.artifacts.checkdiff.sha256,
        parser=_PARSER_VERSION,
        raw_start=raw_start,
        raw_end=raw_end,
        derivation_rule=derivation_rule,
        input_record_ids=input_record_ids,
    )


def _instruction_node(
    bundle: ValidatedBundle,
    instruction: CheckdiffInstruction,
    *,
    kind: str,
    span: tuple[int, int] | None,
    extra_attributes: Mapping[str, object],
) -> EvidenceNode:
    raw_start, raw_end = span if span is not None else (None, None)
    return EvidenceNode.create(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
        kind=kind,
        local_key=instruction.offset,
        role_key=f"retail-offset:{instruction.offset:x}",
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_provenance(
            bundle,
            raw_start=raw_start,
            raw_end=raw_end,
            derivation_rule=f"observed-checkdiff-{kind}",
        ),
        attributes={
            "offset": instruction.offset,
            "opcode": instruction.opcode,
            "operands": instruction.operands,
            "regs": instruction.regs,
            "raw": instruction.raw,
            **extra_attributes,
        },
    )


def _neighborhood_signatures(
    instructions: Mapping[int, CheckdiffInstruction],
) -> dict[int, tuple[str, ...]]:
    ordered = [instructions[offset] for offset in sorted(instructions)]
    normalized = [
        f"{item.opcode} {_REGISTER.sub(lambda match: match.group(1) + '#', item.operands)}".strip() for item in ordered
    ]
    return {item.offset: tuple(normalized[max(0, index - 1) : index + 2]) for index, item in enumerate(ordered)}


def adapt_checkdiff(bundle: ValidatedBundle) -> CheckdiffEvidence:
    """Parse one bundle's captured checkdiff without invoking the build."""

    try:
        raw_json = bundle.artifact_paths["checkdiff"].read_bytes().decode("utf-8")
        payload = json.loads(raw_json)
    except (OSError, UnicodeError, TypeError, json.JSONDecodeError) as error:
        raise BundleInputError(f"invalid checkdiff JSON: {error}") from error
    version = bundle.manifest.producer_versions.get("checkdiff")
    if version != _PARSER_VERSION:
        raise BundleInputError(f"unsupported checkdiff producer version: {version!r}")
    if not isinstance(payload, Mapping) or payload.get("function") != bundle.manifest.function:
        raise BundleInputError(f"checkdiff function does not match manifest function {bundle.manifest.function!r}")

    target_assembly = _assembly_lines(payload, "target_asm")
    current_assembly = _assembly_lines(payload, "current_asm")
    expected_bytes = ("\n".join(target_assembly).rstrip() + "\n").encode("utf-8")
    expected_digest = hashlib.sha256(expected_bytes).hexdigest()
    manifest_digest = bundle.manifest.compile.expected_assembly_digest
    if expected_digest != manifest_digest:
        raise BundleInputError(
            f"expected assembly digest mismatch: manifest={manifest_digest}, checkdiff={expected_digest}"
        )

    expected = _indexed_instructions(target_assembly, side="expected")
    current = _indexed_instructions(current_assembly, side="current")
    if expected.keys() != current.keys():
        missing_expected = sorted(current.keys() - expected.keys())
        missing_current = sorted(expected.keys() - current.keys())
        raise BundleInputError(
            "checkdiff instruction offsets are not uniquely paired: "
            f"expected-missing={missing_expected}, current-missing={missing_current}"
        )

    expected_spans = _line_spans(raw_json, "target_asm", target_assembly)
    current_spans = _line_spans(raw_json, "current_asm", current_assembly)
    neighborhoods = _neighborhood_signatures(expected)
    rows: dict[int, CheckdiffRow] = {}
    nodes: list[EvidenceNode] = []
    edges: list[EvidenceEdge] = []
    for offset in sorted(expected):
        row = CheckdiffRow(offset=offset, expected=expected[offset], current=current[offset])
        rows[offset] = row
        retail = _instruction_node(
            bundle,
            row.expected,
            kind="retail-instruction",
            span=expected_spans.get(offset),
            extra_attributes={"neighborhood_signature": neighborhoods[offset]},
        )
        candidate = _instruction_node(
            bundle,
            row.current,
            kind="candidate-instruction",
            span=current_spans.get(offset),
            extra_attributes={
                "aligned_retail_offset": offset,
                "retail_neighborhood_signature": neighborhoods[offset],
            },
        )
        nodes.extend((retail, candidate))
        starts = [span[0] for span in (expected_spans.get(offset), current_spans.get(offset)) if span]
        ends = [span[1] for span in (expected_spans.get(offset), current_spans.get(offset)) if span]
        edge = EvidenceEdge.create(
            compile_id=bundle.compile_id,
            function=bundle.manifest.function,
            kind="aligns-to-retail",
            source_id=candidate.record_id,
            target_id=retail.record_id,
            occurrence_ordinal=0,
            producer_confidence=Confidence.OBSERVED,
            adapter_confidence=Confidence.OBSERVED,
            provenance=_provenance(
                bundle,
                raw_start=min(starts) if starts else None,
                raw_end=max(ends) if ends else None,
                derivation_rule="paired-checkdiff-row-by-retail-byte-offset",
                input_record_ids=(candidate.record_id, retail.record_id),
            ),
            input_confidences=(candidate.confidence, retail.confidence),
            attributes={"retail_offset": offset},
        )
        edges.append(edge)

    classification = payload.get("classification") if isinstance(payload, Mapping) else None
    stack_slot_localizer = (
        classification.get("stack_slot_localizer")
        if isinstance(classification, Mapping) and isinstance(classification.get("stack_slot_localizer"), Mapping)
        else None
    )
    return CheckdiffEvidence(
        result=AdapterResult(nodes=tuple(nodes), edges=tuple(edges)),
        rows_by_offset=MappingProxyType(rows),
        stack_slot_localizer=(None if stack_slot_localizer is None else _immutable_value(stack_slot_localizer)),
        target_assembly=target_assembly,
        current_assembly=current_assembly,
        expected_assembly_digest=expected_digest,
    )


__all__ = [
    "CheckdiffEvidence",
    "CheckdiffInstruction",
    "CheckdiffRow",
    "adapt_checkdiff",
]
