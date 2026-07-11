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
from .models import AdapterResult, Confidence, EvidenceNode, Provenance

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
        report["stack_slot_bridge"] = explain_stack_slot_localizer(
            backend.pcdump_text,
            bundle.manifest.function,
            _mutable_mapping(checkdiff.stack_slot_localizer),
            source_text=source_text,
            source_file=str(bundle.artifact_paths["source"]),
        )
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
    declared = _declared_confidence(obj.get("producer_confidence", obj.get("confidence")))
    if declared is not None:
        return declared
    if obj.get("source_attribution") or obj.get("source_guess"):
        return Confidence.HEURISTIC
    symbol = obj.get("symbol")
    source_symbols = obj.get("source_symbols")
    has_symbol = isinstance(symbol, str) and bool(symbol)
    has_symbol = has_symbol or (isinstance(source_symbols, (list, tuple)) and len(source_symbols) > 0)
    if obj.get("ambiguous") is True:
        return Confidence.HEURISTIC
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
    if not isinstance(trace, Mapping) or not isinstance(trace.get("objects"), (list, tuple)):
        raise BundleInputError("frame report current frame_allocation_trace.objects must be a list")
    expected = report.get("expected")
    if expected is not None:
        if not isinstance(expected, Mapping):
            raise BundleInputError("frame report expected frame must be an object or null")
        expected_trace = expected.get("frame_allocation_trace")
        if not isinstance(expected_trace, Mapping) or not isinstance(expected_trace.get("objects"), (list, tuple)):
            raise BundleInputError("frame report expected frame_allocation_trace.objects must be a list")


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
    side_objects = {
        "expected": _trace_objects(report.get("expected")),
        "current": _trace_objects(report.get("current")),
    }
    for side, objects in side_objects.items():
        for index, obj in enumerate(objects):
            producer_confidence = _object_confidence(obj)
            attributes = dict(obj)
            attributes["side"] = side
            candidates = _bridge_candidates(report, obj) if side == "current" else ()
            if candidates:
                attributes["ownership_candidates"] = tuple(dict(item) for item in candidates)
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
                role_key=(_role_names(obj)[0] if len(_role_names(obj)) == 1 else None),
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

    expected_roles: dict[str, tuple[int, int]] = {}
    expected_counts: dict[str, int] = {}
    for obj in side_objects["expected"]:
        start, end = obj.get("start"), obj.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        for role in _role_names(obj):
            expected_counts[role] = expected_counts.get(role, 0) + 1
            expected_roles[role] = (start, end)
    expected_roles = {role: interval for role, interval in expected_roles.items() if expected_counts[role] == 1}

    current_candidates: dict[str, list[str]] = {}
    for node in nodes:
        if node.attributes.get("side") != "current":
            continue
        for role in _role_names(node.attributes):
            current_candidates.setdefault(role, []).append(node.record_id)
    current_nodes = {role: record_ids[0] for role, record_ids in current_candidates.items() if len(record_ids) == 1}
    return FrameEvidence(
        result=AdapterResult(nodes=tuple(nodes)),
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
