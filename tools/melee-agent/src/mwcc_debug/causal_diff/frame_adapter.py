"""Adapt captured or deterministically derived stack-frame reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..frame_reservations import analyze_frame_reservations
from ..stack_slot_bridge import explain_stack_slot_localizer
from .asm_adapter import CheckdiffEvidence
from .backend_adapter import BackendEvidence
from .bundles import BundleInputError, ValidatedBundle
from .models import AdapterResult, Confidence, EvidenceEdge, EvidenceNode, Provenance

_SUPPLIED_PARSER = "frame-reservations.v1"
_DERIVED_PARSER = "causal-frame-derivation.v1"


@dataclass(frozen=True, slots=True)
class FrameEvidence:
    result: AdapterResult
    expected_stack_roles: Mapping[str, tuple[int, int]]
    current_stack_nodes: Mapping[str, str]


def parse_supplied_frame_report(text: str) -> Mapping[str, object]:
    """Parse a captured JSON frame report without enriching its claims."""

    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as error:
        raise BundleInputError(f"invalid supplied frame report: {error}") from error
    if not isinstance(payload, Mapping):
        raise BundleInputError("supplied frame report must contain a JSON object")
    return payload


def derive_frame_report(
    bundle: ValidatedBundle,
    checkdiff: CheckdiffEvidence,
    backend: BackendEvidence,
) -> Mapping[str, object]:
    """Derive a frame report solely from already loaded bundle artifacts."""

    source_text = bundle.read_text("source")
    report = analyze_frame_reservations(
        backend.pcdump_text,
        bundle.manifest.function,
        expected_asm_text="\n".join(checkdiff.target_assembly),
        current_asm_text="\n".join(checkdiff.current_assembly),
        source_text=source_text,
        source_path=str(bundle.artifact_paths["source"]),
    )
    if checkdiff.stack_slot_localizer is not None:
        bridge = explain_stack_slot_localizer(
            backend.pcdump_text,
            bundle.manifest.function,
            _mutable_mapping(checkdiff.stack_slot_localizer),
            source_text=source_text,
            source_file=str(bundle.artifact_paths["source"]),
        )
        for candidate in bridge.get("candidates") or ():
            expression = candidate.get("nearest_source_expression")
            if not isinstance(expression, dict):
                continue
            producer_label = expression.get("confidence")
            expression["producer_confidence_label"] = producer_label
            expression["confidence"] = (
                producer_label if _declared_confidence(producer_label) is not None else Confidence.HEURISTIC.value
            )
        report["stack_slot_bridge"] = bridge
    return report


def _mutable_mapping(value: Mapping[str, object]) -> dict[str, object]:
    def convert(item: object) -> object:
        if isinstance(item, Mapping):
            return {str(key): convert(child) for key, child in item.items()}
        if isinstance(item, tuple):
            return [convert(child) for child in item]
        return item

    return {str(key): convert(item) for key, item in value.items()}


def _declared_confidence(value: object) -> Confidence | None:
    if value == Confidence.OBSERVED or value == Confidence.OBSERVED.value:
        return Confidence.OBSERVED
    if value == Confidence.DERIVED_UNIQUE or value == Confidence.DERIVED_UNIQUE.value:
        return Confidence.DERIVED_UNIQUE
    if value == Confidence.HEURISTIC or value == Confidence.HEURISTIC.value:
        return Confidence.HEURISTIC
    return None


def _object_confidence(obj: Mapping[str, object]) -> Confidence:
    if obj.get("ambiguous") is True or obj.get("source_attribution") or obj.get("source_guess"):
        return Confidence.HEURISTIC
    declared = _declared_confidence(obj.get("producer_confidence", obj.get("confidence")))
    if declared is not None:
        return declared
    symbol = obj.get("symbol")
    source_symbols = obj.get("source_symbols")
    has_symbol = isinstance(symbol, str) and bool(symbol)
    has_symbol = has_symbol or (isinstance(source_symbols, (list, tuple)) and len(source_symbols) > 0)
    if obj.get("origin_tag") == "symbolic-stack-home" and has_symbol:
        return Confidence.DERIVED_UNIQUE
    if not has_symbol and obj.get("symbolic_assignment_order") is not None:
        return Confidence.HEURISTIC
    return Confidence.OBSERVED


def _trace_objects(side: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(side, Mapping):
        return ()
    trace = side.get("frame_allocation_trace")
    if not isinstance(trace, Mapping):
        return ()
    objects = trace.get("objects")
    if not isinstance(objects, (list, tuple)):
        return ()
    return tuple(item for item in objects if isinstance(item, Mapping))


def _validate_frame_report(report: Mapping[str, object], function: str) -> None:
    if report.get("function") != function:
        raise BundleInputError(f"frame report function does not match manifest function {function!r}")
    current = report.get("current")
    if not isinstance(current, Mapping):
        raise BundleInputError("frame report current frame must be an object")
    trace = current.get("frame_allocation_trace")
    _validate_frame_trace(trace, side="current")
    expected = report.get("expected")
    if expected is not None:
        if not isinstance(expected, Mapping):
            raise BundleInputError("frame report expected frame must be an object or null")
        _validate_frame_trace(expected.get("frame_allocation_trace"), side="expected")
    bridge = report.get("stack_slot_bridge")
    if bridge is not None:
        _validate_stack_bridge(bridge, function=function)


def _validate_frame_trace(trace: object, *, side: str) -> None:
    if not isinstance(trace, Mapping):
        raise BundleInputError(f"frame report {side} frame_allocation_trace must be an object")
    if not isinstance(trace.get("status"), str):
        raise BundleInputError(f"frame report {side} frame_allocation_trace.status must be a string")
    objects = trace.get("objects")
    if not isinstance(objects, (list, tuple)):
        raise BundleInputError(f"frame report {side} frame_allocation_trace.objects must be a list")
    for index, obj in enumerate(objects):
        if not isinstance(obj, Mapping):
            raise BundleInputError(f"frame report {side} object {index} must be an object")
        for field in ("start", "end", "size"):
            if not isinstance(obj.get(field), int) or isinstance(obj.get(field), bool):
                raise BundleInputError(f"frame report {side} object {index}.{field} must be an integer")
        if int(obj["end"]) <= int(obj["start"]) or int(obj["size"]) != int(obj["end"]) - int(obj["start"]):
            raise BundleInputError(f"frame report {side} object {index} has an invalid interval")
        for field in ("kind", "origin_tag"):
            if not isinstance(obj.get(field), str) or not obj.get(field):
                raise BundleInputError(f"frame report {side} object {index}.{field} must be a nonempty string")
        for field in ("symbol", "source"):
            if field in obj and obj[field] is not None and not isinstance(obj[field], str):
                raise BundleInputError(f"frame report {side} object {index}.{field} must be a string or null")
        source_symbols = obj.get("source_symbols")
        if source_symbols is not None and (
            not isinstance(source_symbols, (list, tuple)) or any(not isinstance(item, str) for item in source_symbols)
        ):
            raise BundleInputError(f"frame report {side} object {index}.source_symbols must be a list of strings")
        if "ambiguous" in obj and not isinstance(obj["ambiguous"], bool):
            raise BundleInputError(f"frame report {side} object {index}.ambiguous must be a boolean")
        for field in ("producer_confidence", "confidence"):
            if field in obj and _declared_confidence(obj[field]) is None:
                raise BundleInputError(f"frame report {side} object {index}.{field} has an unsupported confidence")
        for field in ("layout_order", "symbolic_assignment_order"):
            if field in obj and (not isinstance(obj[field], int) or isinstance(obj[field], bool)):
                raise BundleInputError(f"frame report {side} object {index}.{field} must be an integer")


def _validate_stack_bridge(bridge: object, *, function: str) -> None:
    if not isinstance(bridge, Mapping):
        raise BundleInputError("frame report stack_slot_bridge must be an object")
    if not isinstance(bridge.get("status"), str):
        raise BundleInputError("frame report stack_slot_bridge.status must be a string")
    if bridge.get("function") != function:
        raise BundleInputError("frame report stack_slot_bridge.function does not match")
    candidates = bridge.get("candidates")
    if not isinstance(candidates, (list, tuple)):
        raise BundleInputError("frame report stack_slot_bridge.candidates must be a list")
    candidate_count = bridge.get("candidate_count")
    if not isinstance(candidate_count, int) or isinstance(candidate_count, bool) or candidate_count != len(candidates):
        raise BundleInputError("frame report stack_slot_bridge.candidate_count does not match candidates")
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise BundleInputError(f"frame report bridge candidate {index} must be an object")
        if not isinstance(candidate.get("current_offset"), int) or isinstance(candidate.get("current_offset"), bool):
            raise BundleInputError(f"frame report bridge candidate {index}.current_offset must be an integer")
        if not isinstance(candidate.get("opcode"), str) or not candidate.get("opcode"):
            raise BundleInputError(f"frame report bridge candidate {index}.opcode must be a nonempty string")
        for field in ("site_kind", "mapping_status"):
            if not isinstance(candidate.get(field), str) or not candidate.get(field):
                raise BundleInputError(f"frame report bridge candidate {index}.{field} must be a nonempty string")
        evidence = candidate.get("evidence")
        if (
            not isinstance(evidence, (list, tuple))
            or not evidence
            or any(not isinstance(item, str) or not item for item in evidence)
        ):
            raise BundleInputError(f"frame report bridge candidate {index}.evidence must be a nonempty list of strings")
        expression = candidate.get("nearest_source_expression")
        if expression is not None:
            if not isinstance(expression, Mapping):
                raise BundleInputError(
                    f"frame report bridge candidate {index}.nearest_source_expression must be an object"
                )
            if not isinstance(expression.get("expression"), str) or not isinstance(expression.get("confidence"), str):
                raise BundleInputError(
                    f"frame report bridge candidate {index} has malformed source expression evidence"
                )
            if _declared_confidence(expression.get("confidence")) is None:
                raise BundleInputError(f"frame report bridge candidate {index} has unsupported source confidence")
        for field in ("producer_confidence", "confidence"):
            if field in candidate and _declared_confidence(candidate[field]) is None:
                raise BundleInputError(f"frame report bridge candidate {index}.{field} has unsupported confidence")


def _artifact_digest(bundle: ValidatedBundle, name: str) -> str:
    if name == "source":
        return bundle.manifest.artifacts.source.sha256
    if name == "checkdiff":
        return bundle.manifest.artifacts.checkdiff.sha256
    if name == "frame_report" and bundle.manifest.artifacts.frame_report is not None:
        return bundle.manifest.artifacts.frame_report.sha256
    if name.startswith("backend[") and name.endswith("]"):
        index = int(name[8:-1])
        return bundle.manifest.artifacts.backend[index].sha256
    raise BundleInputError(f"unknown frame input artifact: {name}")


def _artifact_input_nodes(bundle: ValidatedBundle, names: tuple[str, ...]) -> tuple[EvidenceNode, ...]:
    return tuple(
        EvidenceNode.create(
            compile_id=bundle.compile_id,
            function=bundle.manifest.function,
            kind="frame-input-artifact",
            local_key=(name, _artifact_digest(bundle, name)),
            role_key=None,
            producer_confidence=Confidence.OBSERVED,
            adapter_confidence=Confidence.OBSERVED,
            provenance=Provenance(
                artifact_sha256=_artifact_digest(bundle, name),
                parser="frontier-bundle-artifact.v1",
                raw_start=None,
                raw_end=None,
                derivation_rule="frame-consumed-validated-artifact",
            ),
            attributes={"artifact_name": name},
        )
        for name in names
    )


def _role_names(obj: Mapping[str, object]) -> tuple[str, ...]:
    names: list[str] = []
    symbol = obj.get("symbol")
    if isinstance(symbol, str) and symbol:
        names.append(symbol)
    source_symbols = obj.get("source_symbols")
    if isinstance(source_symbols, (list, tuple)):
        names.extend(str(item) for item in source_symbols if str(item))
    return tuple(dict.fromkeys(names))


def _inferred_interval_roles(
    side_objects: Mapping[str, tuple[Mapping[str, object], ...]],
) -> tuple[Mapping[int, str], Mapping[int, str]]:
    expected = side_objects["expected"]
    current = side_objects["current"]
    current_roles: dict[int, str] = {}
    expected_roles: dict[int, str] = {}
    role_counts: dict[str, int] = {}
    for current_index, obj in enumerate(current):
        offsets = obj.get("expected_source_offsets")
        if not isinstance(offsets, Mapping):
            continue
        expected_offsets = {
            value for value in offsets.values() if isinstance(value, int) and not isinstance(value, bool)
        }
        size = obj.get("size")
        kind = obj.get("kind")
        opcodes = tuple(sorted(str(item) for item in obj.get("opcodes", ())))
        if len(expected_offsets) != 1 or not isinstance(size, int) or not isinstance(kind, str):
            continue
        expected_offset = next(iter(expected_offsets))
        matches = [
            index
            for index, candidate in enumerate(expected)
            if candidate.get("start") == expected_offset
            and candidate.get("size") == size
            and candidate.get("kind") == kind
            and tuple(sorted(str(item) for item in candidate.get("opcodes", ()))) == opcodes
        ]
        if len(matches) != 1:
            continue
        role = f"stack-interval:{expected_offset}:{size}:{kind}:{','.join(opcodes)}"
        role_counts[role] = role_counts.get(role, 0) + 1
        current_roles[current_index] = role
        expected_roles[matches[0]] = role
    unique = {role for role, count in role_counts.items() if count == 1}
    return (
        MappingProxyType({index: role for index, role in current_roles.items() if role in unique}),
        MappingProxyType({index: role for index, role in expected_roles.items() if role in unique}),
    )


def _bridge_candidates(report: Mapping[str, object], obj: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    bridge = report.get("stack_slot_bridge")
    if not isinstance(bridge, Mapping):
        return ()
    raw_candidates = bridge.get("candidates")
    if not isinstance(raw_candidates, (list, tuple)):
        return ()
    start = obj.get("start")
    end = obj.get("end")
    matches: list[Mapping[str, object]] = []
    for candidate in raw_candidates:
        if not isinstance(candidate, Mapping):
            continue
        offset = candidate.get("current_offset")
        if isinstance(start, int) and isinstance(end, int) and isinstance(offset, int):
            if start <= offset < end:
                matches.append(candidate)
    return tuple(matches)


def _bridge_access_operands(candidate: Mapping[str, object]) -> str:
    opcode = str(candidate.get("opcode") or "")
    evidence = candidate.get("evidence")
    if not opcode or not isinstance(evidence, (list, tuple)):
        return ""
    marker = f" {opcode} "
    for item in evidence:
        if isinstance(item, str) and marker in item:
            return item.split(marker, 1)[1].strip()
    return ""


def _bridge_records(
    bundle: ValidatedBundle,
    report: Mapping[str, object],
    *,
    input_nodes: tuple[EvidenceNode, ...],
) -> tuple[
    tuple[EvidenceNode, ...],
    tuple[EvidenceEdge, ...],
    Mapping[int, tuple[str, ...]],
]:
    bridge = report.get("stack_slot_bridge")
    if not isinstance(bridge, Mapping):
        return (), (), MappingProxyType({})
    candidates = bridge.get("candidates")
    if not isinstance(candidates, (list, tuple)):
        return (), (), MappingProxyType({})

    nodes: list[EvidenceNode] = []
    edges: list[EvidenceEdge] = []
    support_by_index: dict[int, tuple[str, ...]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            continue
        base_provenance = tuple(node.record_id for node in input_nodes)
        base_confidences = tuple(node.confidence for node in input_nodes)
        candidate_node = EvidenceNode.create(
            compile_id=bundle.compile_id,
            function=bundle.manifest.function,
            kind="frame-bridge-candidate",
            local_key=(index, candidate.get("current_offset"), candidate.get("virtual_token")),
            role_key=None,
            producer_confidence=Confidence.DERIVED_UNIQUE,
            adapter_confidence=Confidence.DERIVED_UNIQUE,
            provenance=Provenance(
                artifact_sha256=bundle.compile_id,
                parser="stack-slot-bridge.v1",
                raw_start=None,
                raw_end=None,
                derivation_rule="normalize-stack-slot-bridge-candidate",
                input_record_ids=base_provenance,
            ),
            input_confidences=base_confidences,
            attributes={
                key: value
                for key, value in candidate.items()
                if key not in {"nearest_source_expression", "evidence", "input_record_ids"}
            },
        )
        operands = _bridge_access_operands(candidate)
        access_node = EvidenceNode.create(
            compile_id=bundle.compile_id,
            function=bundle.manifest.function,
            kind="frame-stack-access",
            local_key=(index, candidate.get("opcode"), candidate.get("current_offset"), operands),
            role_key=None,
            producer_confidence=Confidence.OBSERVED,
            adapter_confidence=Confidence.DERIVED_UNIQUE,
            provenance=Provenance(
                artifact_sha256=bundle.compile_id,
                parser="stack-slot-bridge.v1",
                raw_start=None,
                raw_end=None,
                derivation_rule="extract-bridge-stack-access",
                input_record_ids=base_provenance,
            ),
            input_confidences=base_confidences,
            attributes={
                "opcode": candidate.get("opcode"),
                "operands": operands,
                "current_offset": candidate.get("current_offset"),
                "evidence": candidate.get("evidence", ()),
            },
        )
        local_nodes: list[EvidenceNode] = [candidate_node, access_node]
        edge_pairs: list[tuple[str, EvidenceNode, Confidence]] = [
            ("bridge-has-stack-access", access_node, Confidence.DERIVED_UNIQUE)
        ]
        expression = candidate.get("nearest_source_expression")
        if isinstance(expression, Mapping):
            hint_confidence = (
                Confidence.DERIVED_UNIQUE
                if expression.get("confidence") == Confidence.DERIVED_UNIQUE.value
                else Confidence.HEURISTIC
            )
            hint_node = EvidenceNode.create(
                compile_id=bundle.compile_id,
                function=bundle.manifest.function,
                kind="frame-bridge-source-hint",
                local_key=(index, expression.get("expression")),
                role_key=None,
                producer_confidence=hint_confidence,
                adapter_confidence=Confidence.OBSERVED,
                provenance=Provenance(
                    artifact_sha256=bundle.compile_id,
                    parser="stack-slot-bridge.v1",
                    raw_start=None,
                    raw_end=None,
                    derivation_rule="normalize-bridge-source-expression-hint",
                    input_record_ids=base_provenance,
                ),
                input_confidences=base_confidences,
                attributes=dict(expression),
            )
            local_nodes.append(hint_node)
            edge_pairs.append(("bridge-has-source-hint", hint_node, hint_confidence))
        local_edges: list[EvidenceEdge] = []
        for edge_kind, target, confidence in edge_pairs:
            edge = EvidenceEdge.create(
                compile_id=bundle.compile_id,
                function=bundle.manifest.function,
                kind=edge_kind,
                source_id=candidate_node.record_id,
                target_id=target.record_id,
                occurrence_ordinal=0,
                producer_confidence=Confidence.DERIVED_UNIQUE,
                adapter_confidence=confidence,
                provenance=Provenance(
                    artifact_sha256=bundle.compile_id,
                    parser="stack-slot-bridge.v1",
                    raw_start=None,
                    raw_end=None,
                    derivation_rule=edge_kind,
                    input_record_ids=(candidate_node.record_id, target.record_id),
                ),
                input_confidences=(candidate_node.confidence, target.confidence),
                attributes={},
            )
            local_edges.append(edge)
        nodes.extend(local_nodes)
        edges.extend(local_edges)
        support_by_index[index] = tuple(record.record_id for record in (*local_nodes, *local_edges))
    return tuple(nodes), tuple(edges), MappingProxyType(support_by_index)


def frame_evidence_from_report(
    bundle: ValidatedBundle,
    report: Mapping[str, object],
    *,
    input_artifacts: tuple[str, ...] | None = None,
) -> FrameEvidence:
    """Normalize every allocation-trace object while preserving confidence."""

    _validate_frame_report(report, bundle.manifest.function)

    supplied = bundle.manifest.artifacts.frame_report is not None
    if input_artifacts is None:
        input_artifacts = ("frame_report",) if supplied else ("backend[0]",)
    input_nodes = _artifact_input_nodes(bundle, input_artifacts)
    artifact_sha256 = bundle.manifest.artifacts.frame_report.sha256 if supplied else bundle.compile_id
    parser = _SUPPLIED_PARSER if supplied else _DERIVED_PARSER
    raw_end = len(bundle.read_text("frame_report").encode("utf-8")) if supplied else None
    nodes: list[EvidenceNode] = list(input_nodes)
    bridge_nodes, bridge_edges, bridge_support = _bridge_records(bundle, report, input_nodes=input_nodes)
    nodes.extend(bridge_nodes)
    edges: list[EvidenceEdge] = list(bridge_edges)
    bridge_nodes_by_id = {node.record_id: node for node in bridge_nodes}
    side_objects = {
        "expected": _trace_objects(report.get("expected")),
        "current": _trace_objects(report.get("current")),
    }
    current_interval_roles, expected_interval_roles = _inferred_interval_roles(side_objects)
    for side, objects in side_objects.items():
        for index, obj in enumerate(objects):
            producer_confidence = _object_confidence(obj)
            attributes = dict(obj)
            attributes["side"] = side
            candidates = _bridge_candidates(report, obj) if side == "current" else ()
            if candidates:
                bridge_candidates = report.get("stack_slot_bridge", {}).get("candidates", ())
                candidate_indexes = {
                    id(candidate): index
                    for index, candidate in enumerate(bridge_candidates)
                    if isinstance(candidate, Mapping)
                }
                attributes["ownership_candidates"] = tuple(
                    {
                        **dict(item),
                        "input_record_ids": bridge_support.get(candidate_indexes.get(id(item), -1), ()),
                    }
                    for item in candidates
                )
            node = EvidenceNode.create(
                compile_id=bundle.compile_id,
                function=bundle.manifest.function,
                kind="stack-object",
                local_key=(
                    side,
                    index,
                    obj.get("start"),
                    obj.get("end"),
                    obj.get("symbol"),
                ),
                role_key=(
                    current_interval_roles.get(index) if side == "current" else expected_interval_roles.get(index)
                )
                or (_role_names(obj)[0] if len(_role_names(obj)) == 1 else None),
                producer_confidence=producer_confidence,
                adapter_confidence=Confidence.OBSERVED,
                provenance=Provenance(
                    artifact_sha256=artifact_sha256,
                    parser=parser,
                    raw_start=0 if supplied else None,
                    raw_end=raw_end,
                    derivation_rule=(
                        "normalize-supplied-frame-allocation-object"
                        if supplied
                        else "derive-frame-allocation-object-from-loaded-artifacts"
                    ),
                    input_record_ids=tuple(input_node.record_id for input_node in input_nodes),
                ),
                input_confidences=tuple(input_node.confidence for input_node in input_nodes),
                attributes=attributes,
            )
            nodes.append(node)
            for ordinal, ownership in enumerate(attributes.get("ownership_candidates", ())):
                if not isinstance(ownership, Mapping):
                    continue
                support_ids = ownership.get("input_record_ids")
                if not isinstance(support_ids, (list, tuple)):
                    continue
                candidate_node = next(
                    (
                        bridge_nodes_by_id[record_id]
                        for record_id in support_ids
                        if record_id in bridge_nodes_by_id
                        and bridge_nodes_by_id[record_id].kind == "frame-bridge-candidate"
                    ),
                    None,
                )
                if candidate_node is None:
                    continue
                edges.append(
                    EvidenceEdge.create(
                        compile_id=bundle.compile_id,
                        function=bundle.manifest.function,
                        kind="bridge-candidate-materializes-stack-object",
                        source_id=candidate_node.record_id,
                        target_id=node.record_id,
                        occurrence_ordinal=ordinal,
                        producer_confidence=Confidence.DERIVED_UNIQUE,
                        adapter_confidence=(
                            Confidence.DERIVED_UNIQUE
                            if len(attributes["ownership_candidates"]) == 1
                            else Confidence.HEURISTIC
                        ),
                        provenance=Provenance(
                            artifact_sha256=bundle.compile_id,
                            parser="stack-slot-bridge.v1",
                            raw_start=None,
                            raw_end=None,
                            derivation_rule="join-bridge-candidate-to-containing-stack-object",
                            input_record_ids=(
                                candidate_node.record_id,
                                node.record_id,
                            ),
                        ),
                        input_confidences=(
                            candidate_node.confidence,
                            node.confidence,
                        ),
                        attributes={"current_offset": ownership.get("current_offset")},
                    )
                )

    expected_roles: dict[str, tuple[int, int]] = {}
    expected_counts: dict[str, int] = {}
    for index, obj in enumerate(side_objects["expected"]):
        start, end = obj.get("start"), obj.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        for role in (*_role_names(obj), *(filter(None, (expected_interval_roles.get(index),)))):
            expected_counts[role] = expected_counts.get(role, 0) + 1
            expected_roles[role] = (start, end)
    expected_roles = {role: interval for role, interval in expected_roles.items() if expected_counts[role] == 1}

    current_candidates: dict[str, list[str]] = {}
    for node in nodes:
        if node.attributes.get("side") != "current":
            continue
        roles = tuple(dict.fromkeys((*_role_names(node.attributes), *(filter(None, (node.role_key,))))))
        for role in roles:
            current_candidates.setdefault(role, []).append(node.record_id)
    current_nodes = {role: record_ids[0] for role, record_ids in current_candidates.items() if len(record_ids) == 1}
    return FrameEvidence(
        result=AdapterResult(nodes=tuple(nodes), edges=tuple(edges)),
        expected_stack_roles=MappingProxyType(expected_roles),
        current_stack_nodes=MappingProxyType(current_nodes),
    )


def adapt_frame(
    bundle: ValidatedBundle,
    checkdiff: CheckdiffEvidence,
    backend: BackendEvidence,
) -> FrameEvidence:
    """Adapt supplied frame facts or derive them from immutable artifacts."""

    if bundle.manifest.artifacts.frame_report is not None:
        version = bundle.manifest.producer_versions.get("frame_report")
        if version != _SUPPLIED_PARSER:
            raise BundleInputError(f"unsupported frame report producer version: {version!r}")
        report = parse_supplied_frame_report(bundle.read_text("frame_report"))
        input_artifacts = ("frame_report",)
    else:
        report = derive_frame_report(bundle, checkdiff, backend)
        backend_index = next(
            (
                index
                for index, artifact in enumerate(bundle.manifest.artifacts.backend)
                if artifact.format == "mwcc-debug-pcdump"
            ),
            0,
        )
        input_artifacts = ("source", "checkdiff", f"backend[{backend_index}]")
    return frame_evidence_from_report(bundle, report, input_artifacts=input_artifacts)


__all__ = [
    "FrameEvidence",
    "adapt_frame",
    "derive_frame_report",
    "frame_evidence_from_report",
    "parse_supplied_frame_report",
]
