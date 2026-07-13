"""Build proof-capped, within-compile causal ownership joins."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from .asm_adapter import CheckdiffEvidence
from .backend_adapter import BackendEvidence
from .bundles import BundleInputError, ValidatedBundle
from .frame_adapter import FrameEvidence
from .models import AdapterResult, Confidence, EvidenceEdge, EvidenceNode, Provenance
from .source_adapter import SourceEvidence
from .store import EvidenceStore, InMemoryEvidenceStore

_PARSER_VERSION = "within-compile-ownership-joins.v1"
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")
_INTEGER = re.compile(r"(?<![A-Za-z_])(?:0x[0-9A-Fa-f]+|\d+)(?![A-Za-z_])")
_DISPLACEMENT_ADDRESS = re.compile(r"(?P<offset>[-+]?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*(?P<base>r\d+)\s*\)")
_KEYWORDS = frozenset({"const", "else", "false", "if", "return", "sizeof", "struct", "true", "void"})
_STACK_OPS = frozenset({"lbz", "lha", "lhz", "lwz", "stb", "sth", "stw", "lfd", "lfs", "stfd", "stfs"})
_RETAIL_SAME_RUN_PCODE_CAPABILITIES = frozenset({"pcode-to-code-range", "object-to-virtual"})
_RETAIL_SAME_RUN_PCODE_PARSER = "mwcc-retro-backend-trace.v2"


@dataclass(frozen=True, slots=True)
class FrontierGraph:
    bundle: ValidatedBundle
    store: EvidenceStore
    checkdiff: CheckdiffEvidence
    backend: BackendEvidence
    inspector: AdapterResult
    frame: FrameEvidence
    source: SourceEvidence
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Signature:
    operation: str
    consumer: str
    identifiers: tuple[str, ...]
    constants: tuple[str, ...]
    type_text: str
    order: int
    order_explicit: bool
    operator_tree: object | None = None
    scope_path: tuple[str, ...] = ()


def add_adapter_results_atomically(store: EvidenceStore, results: Iterable[AdapterResult]) -> None:
    """Preflight a batch, then ingest diagnostics, edges, and certificates."""

    normalized = tuple(results)
    nodes = tuple(node for result in normalized for node in result.nodes)
    diagnostic_nodes = tuple(node for node in nodes if node.kind != "owner-proof-certificate")
    certificate_nodes = tuple(node for node in nodes if node.kind == "owner-proof-certificate")
    edges = tuple(edge for result in normalized for edge in result.edges)

    preflight = InMemoryEvidenceStore()
    referenced_ids = {record_id for record in (*nodes, *edges) for record_id in record.provenance.input_record_ids}
    referenced_ids.update(endpoint for edge in edges for endpoint in (edge.source_id, edge.target_id))
    external_nodes = tuple(
        record for record_id in sorted(referenced_ids) if (record := store.get_node(record_id)) is not None
    )
    external_edges = tuple(
        record for record_id in sorted(referenced_ids) if (record := store.get_edge(record_id)) is not None
    )
    batch_ids = {record.record_id for record in (*nodes, *edges)}
    for certificate in certificate_nodes:
        for record_id in certificate.provenance.input_record_ids:
            if record_id not in batch_ids and store.get_node(record_id) is None and store.get_edge(record_id) is None:
                raise ValueError(f"provenance input record not found: {record_id}")

    preflight.add_nodes((*external_nodes, *diagnostic_nodes))
    preflight.add_edges((*external_edges, *edges))
    preflight.add_nodes(certificate_nodes)

    for record in (*nodes, *edges):
        existing = store.get_node(record.record_id) or store.get_edge(record.record_id)
        if existing is not None and existing != record:
            raise ValueError(f"record ID collision: {record.record_id}")

    store.add_nodes(diagnostic_nodes)
    store.add_edges(edges)
    store.add_nodes(certificate_nodes)


def _validate_compile_scope(bundle: ValidatedBundle, results: Iterable[AdapterResult]) -> None:
    for result in results:
        for record in (*result.nodes, *result.edges):
            if record.compile_id != bundle.compile_id or record.function != bundle.manifest.function:
                raise BundleInputError(f"within-compile graph received foreign evidence record: {record.record_id}")


def canonical_warnings(*items: object) -> tuple[str, ...]:
    warnings: set[str] = set()
    for item in items:
        result = item if isinstance(item, AdapterResult) else getattr(item, "result", None)
        if isinstance(result, AdapterResult):
            warnings.update(result.warnings)
    return tuple(sorted(warnings))


def _consumer(text: str) -> str:
    calls = _CALL.findall(text)
    return calls[-1] if calls else ""


def _operation_from_enode(opcode: str, expression: str) -> str:
    if _consumer(expression):
        return "call"
    normalized = opcode.upper()
    if normalized in {"EASS", "EASG"}:
        return "="
    return {
        "EADD": "+",
        "ESUB": "-",
        "EMUL": "*",
        "EDIV": "/",
        "EEQU": "==",
        "ECOMMA": ",",
    }.get(normalized, normalized.casefold())


def _operation_from_pcode(opcode: str) -> str:
    normalized = opcode.casefold()
    if normalized in {"b", "ba", "bl", "bla", "call"}:
        return "call"
    if normalized.startswith("add"):
        return "+"
    if normalized.startswith("sub"):
        return "-"
    if normalized.startswith("mul"):
        return "*"
    if normalized.startswith("div"):
        return "/"
    return normalized


def _text_identifiers(text: str, consumer: str) -> tuple[str, ...]:
    return tuple(sorted({name for name in _IDENTIFIER.findall(text) if name not in _KEYWORDS and name != consumer}))


def _source_signature(node: EvidenceNode) -> _Signature:
    attributes = node.attributes
    calls = tuple(str(item) for item in attributes.get("called_functions", ()))
    consumer = calls[-1] if calls else ""
    identifiers = tuple(sorted(str(item) for item in attributes.get("identifiers", ()) if str(item) != consumer))
    return _Signature(
        operation=str(attributes.get("operator") or attributes.get("node_type") or ""),
        consumer=consumer,
        identifiers=identifiers,
        constants=tuple(str(item) for item in attributes.get("constants", ())),
        type_text=str(attributes.get("type_text") or ""),
        order=int(attributes.get("order") or 0),
        order_explicit=isinstance(attributes.get("order"), int),
        operator_tree=attributes.get("operator_tree"),
        scope_path=tuple(str(item) for item in attributes.get("scope_path", ())),
    )


def _inspector_signature(node: EvidenceNode, order: int) -> _Signature:
    attributes = node.attributes
    expression = str(attributes.get("expression") or "")
    consumer = _consumer(expression)
    return _Signature(
        operation=_operation_from_enode(str(attributes.get("opcode") or ""), expression),
        consumer=consumer,
        identifiers=_text_identifiers(expression, consumer),
        constants=tuple(_INTEGER.findall(expression)),
        type_text=str(attributes.get("type_text") or ""),
        order=int(attributes.get("order", order)),
        order_explicit=isinstance(attributes.get("order"), int),
        operator_tree=attributes.get("operator_tree"),
        scope_path=tuple(str(item) for item in attributes.get("scope_path", ())),
    )


def _backend_signature(node: EvidenceNode, order: int) -> _Signature:
    attributes = node.attributes
    opcode = str(attributes.get("opcode") or "")
    operands = str(attributes.get("operands") or "")
    consumer = ""
    if _operation_from_pcode(opcode) == "call":
        names = _IDENTIFIER.findall(operands)
        consumer = names[-1] if names else ""
    return _Signature(
        operation=_operation_from_pcode(opcode),
        consumer=consumer,
        identifiers=(),
        constants=tuple(_INTEGER.findall(operands)),
        type_text=str(attributes.get("type_text") or ""),
        order=int(attributes.get("instruction_index", order)),
        order_explicit=isinstance(attributes.get("instruction_index"), int),
    )


def _compatible_source_inspector(source: _Signature, inspector: _Signature) -> bool:
    if source.operation != inspector.operation or source.consumer != inspector.consumer:
        return False
    if source.type_text and inspector.type_text and source.type_text != inspector.type_text:
        return False
    return source.identifiers == inspector.identifiers and source.constants == inspector.constants


def _compatible_inspector_backend(inspector: _Signature, backend: _Signature) -> bool:
    if inspector.operation != backend.operation or inspector.consumer != backend.consumer:
        return False
    if inspector.type_text and backend.type_text and inspector.type_text != backend.type_text:
        return False
    if inspector.order_explicit and backend.order_explicit and inspector.order != backend.order:
        return False
    return True


def _complete_source_inspector_signature(source: _Signature, inspector: _Signature) -> bool:
    return (
        bool(source.consumer)
        and source.consumer == inspector.consumer
        and bool(source.identifiers)
        and source.identifiers == inspector.identifiers
        and source.operator_tree is not None
        and inspector.operator_tree is not None
        and source.operator_tree == inspector.operator_tree
        and bool(source.scope_path)
        and source.scope_path == inspector.scope_path
        and bool(source.type_text)
        and source.type_text == inspector.type_text
    )


def _complete_inspector_backend_signature(inspector: _Signature, backend: _Signature) -> bool:
    return (
        bool(inspector.operation)
        and bool(inspector.consumer)
        and bool(inspector.type_text)
        and inspector.type_text == backend.type_text
        and inspector.order_explicit
        and backend.order_explicit
        and inspector.order == backend.order
    )


def _join_edge(
    bundle: ValidatedBundle,
    *,
    kind: str,
    source: EvidenceNode,
    target: EvidenceNode,
    occurrence_ordinal: int,
    confidence: Confidence,
    derivation_rule: str,
    attributes: Mapping[str, object],
    support: Iterable[EvidenceNode | EvidenceEdge] = (),
) -> EvidenceEdge:
    inputs: dict[str, EvidenceNode | EvidenceEdge] = {
        source.record_id: source,
        target.record_id: target,
    }
    for record in support:
        inputs.setdefault(record.record_id, record)
    input_records = tuple(inputs.values())
    return EvidenceEdge.create(
        compile_id=bundle.compile_id,
        function=bundle.manifest.function,
        kind=kind,
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=occurrence_ordinal,
        producer_confidence=Confidence.DERIVED_UNIQUE,
        adapter_confidence=confidence,
        provenance=Provenance(
            artifact_sha256=bundle.compile_id,
            parser=_PARSER_VERSION,
            raw_start=None,
            raw_end=None,
            derivation_rule=derivation_rule,
            input_record_ids=tuple(record.record_id for record in input_records),
        ),
        input_confidences=tuple(record.confidence for record in input_records),
        attributes=attributes,
    )


def _expression_joins(
    bundle: ValidatedBundle,
    inspector: AdapterResult,
    source: SourceEvidence,
) -> tuple[EvidenceEdge, ...]:
    source_nodes = tuple(node for node in source.result.nodes if node.kind == "source-expression")
    inspector_nodes = tuple(node for node in inspector.nodes if node.kind == "enode")
    source_signatures = {node.record_id: _source_signature(node) for node in source_nodes}
    edges: list[EvidenceEdge] = []
    for order, enode in enumerate(inspector_nodes):
        signature = _inspector_signature(enode, order)
        candidates = [
            node for node in source_nodes if _compatible_source_inspector(source_signatures[node.record_id], signature)
        ]
        for ordinal, candidate in enumerate(candidates):
            source_signature = source_signatures[candidate.record_id]
            confidence = (
                Confidence.DERIVED_UNIQUE
                if len(candidates) == 1 and _complete_source_inspector_signature(source_signature, signature)
                else Confidence.HEURISTIC
            )
            edges.append(
                _join_edge(
                    bundle,
                    kind="expression-represents-enode",
                    source=candidate,
                    target=enode,
                    occurrence_ordinal=ordinal,
                    confidence=confidence,
                    derivation_rule=(
                        "unique-normalized-source-enode-signature"
                        if confidence is Confidence.DERIVED_UNIQUE
                        else "finite-ambiguous-source-enode-signature"
                    ),
                    attributes={
                        "consumer": signature.consumer,
                        "operation": signature.operation,
                        "candidate_count": len(candidates),
                    },
                )
            )
    return tuple(edges)


def _final_pcode_nodes(backend: BackendEvidence) -> tuple[EvidenceNode, ...]:
    nodes = tuple(node for node in backend.result.nodes if node.kind == "pcode-occurrence")
    virtual_pcode_ids = {
        edge.source_id for edge in backend.result.edges if edge.kind in {"defines-virtual", "uses-virtual"}
    }
    pass_indexes = [
        int(node.attributes["pass_index"])
        for node in nodes
        if node.record_id in virtual_pcode_ids and isinstance(node.attributes.get("pass_index"), int)
    ]
    if not pass_indexes:
        return nodes
    final_index = max(pass_indexes)
    return tuple(node for node in nodes if node.attributes.get("pass_index") == final_index)


def _backend_joins(
    bundle: ValidatedBundle,
    backend: BackendEvidence,
    inspector: AdapterResult,
) -> tuple[EvidenceEdge, ...]:
    inspector_nodes = tuple(node for node in inspector.nodes if node.kind == "enode")
    backend_nodes = _final_pcode_nodes(backend)
    backend_signatures = {node.record_id: _backend_signature(node, order) for order, node in enumerate(backend_nodes)}
    backend_nodes_by_id = {node.record_id: node for node in backend.result.nodes}
    edges: list[EvidenceEdge] = []
    for order, enode in enumerate(inspector_nodes):
        signature = _inspector_signature(enode, order)
        candidates = [
            node
            for node in backend_nodes
            if _compatible_inspector_backend(signature, backend_signatures[node.record_id])
        ]
        for ordinal, candidate in enumerate(candidates):
            chain_edges = tuple(
                edge
                for edge in backend.result.edges
                if edge.kind in {"defines-virtual", "uses-virtual"}
                and candidate.record_id in {edge.source_id, edge.target_id}
            )
            chain_nodes = tuple(
                backend_nodes_by_id[endpoint]
                for edge in chain_edges
                for endpoint in (edge.source_id, edge.target_id)
                if endpoint != candidate.record_id and endpoint in backend_nodes_by_id
            )
            same_run_records = (candidate, *chain_nodes, *chain_edges)
            capture_run_ids = {str(record.attributes.get("capture_run_id") or "") for record in same_run_records}
            retail_same_run = (
                _RETAIL_SAME_RUN_PCODE_CAPABILITIES <= backend.result.verified_capabilities
                and all(record.provenance.parser == _RETAIL_SAME_RUN_PCODE_PARSER for record in same_run_records)
                and len(capture_run_ids) == 1
                and "" not in capture_run_ids
            )
            confidence = (
                Confidence.DERIVED_UNIQUE
                if len(candidates) == 1
                and bool(chain_edges)
                and _complete_inspector_backend_signature(signature, backend_signatures[candidate.record_id])
                and retail_same_run
                else Confidence.HEURISTIC
            )
            edges.append(
                _join_edge(
                    bundle,
                    kind="lowers-to",
                    source=enode,
                    target=candidate,
                    occurrence_ordinal=ordinal,
                    confidence=confidence,
                    derivation_rule=(
                        "verified-retail-same-run-enode-pcode-signature"
                        if confidence is Confidence.DERIVED_UNIQUE
                        else "diagnostic-enode-pcode-signature"
                    ),
                    attributes={
                        "consumer": signature.consumer,
                        "operation": signature.operation,
                        "candidate_count": len(candidates),
                    },
                    support=(*chain_nodes, *chain_edges),
                )
            )
    return tuple(edges)


def _stack_names(node: EvidenceNode) -> frozenset[str]:
    values: set[str] = set()
    symbol = node.attributes.get("symbol")
    if isinstance(symbol, str) and symbol:
        values.add(symbol)
    source_symbols = node.attributes.get("source_symbols")
    if isinstance(source_symbols, (tuple, list)):
        values.update(str(item) for item in source_symbols)
    return frozenset(values)


def _normalized_expression_text(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("[", "").replace("]", "")


def _stack_ownership_support(
    stack: EvidenceNode,
    name: str,
    records_by_id: Mapping[str, EvidenceNode | EvidenceEdge],
) -> tuple[EvidenceNode | EvidenceEdge, ...]:
    candidates = stack.attributes.get("ownership_candidates")
    if not isinstance(candidates, (tuple, list)):
        return ()
    qualifying_support: list[tuple[EvidenceNode | EvidenceEdge, ...]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        expression = candidate.get("nearest_source_expression")
        expression_text = str(expression.get("expression") or "") if isinstance(expression, Mapping) else ""
        expression_confidence = expression.get("confidence") if isinstance(expression, Mapping) else None
        consumer = _consumer(expression_text)
        input_record_ids = candidate.get("input_record_ids")
        if expression_confidence not in {
            Confidence.OBSERVED,
            Confidence.OBSERVED.value,
            Confidence.DERIVED_UNIQUE,
            Confidence.DERIVED_UNIQUE.value,
            Confidence.HEURISTIC,
            Confidence.HEURISTIC.value,
        }:
            continue
        if not isinstance(input_record_ids, (tuple, list)) or not input_record_ids:
            continue
        if not consumer:
            continue
        current_offset = candidate.get("current_offset")
        if not isinstance(current_offset, int):
            continue
        support = tuple(
            records_by_id[record_id]
            for record_id in input_record_ids
            if isinstance(record_id, str) and record_id in records_by_id
        )
        if len(support) != len(input_record_ids):
            continue
        normalized_hint = _normalized_expression_text(expression_text)
        source_records = tuple(
            record
            for record in records_by_id.values()
            if isinstance(record, EvidenceNode)
            and record.kind == "source-expression"
            and consumer in record.attributes.get("called_functions", ())
            and name in record.attributes.get("identifiers", ())
            and bool(record.attributes.get("type_text"))
            and normalized_hint in _normalized_expression_text(str(record.attributes.get("text") or ""))
        )
        inspector_records = tuple(
            record
            for record in records_by_id.values()
            if isinstance(record, EvidenceNode)
            and record.kind == "enode"
            and _consumer(str(record.attributes.get("expression") or "")) == consumer
            and name in _text_identifiers(str(record.attributes.get("expression") or ""), consumer)
            and bool(record.attributes.get("type_text"))
            and normalized_hint in _normalized_expression_text(str(record.attributes.get("expression") or ""))
        )
        access_records: list[EvidenceNode] = []
        for record in support:
            if not isinstance(record, EvidenceNode) or record.kind not in {
                "candidate-instruction",
                "pcode-occurrence",
                "frame-stack-access",
            }:
                continue
            if str(record.attributes.get("opcode") or "").casefold() not in _STACK_OPS:
                continue
            addresses = tuple(
                (int(match.group("offset"), 0), match.group("base").casefold())
                for match in _DISPLACEMENT_ADDRESS.finditer(str(record.attributes.get("operands") or ""))
            )
            if addresses == ((current_offset, "r1"),):
                access_records.append(record)
        matching_types = len(source_records) == len(inspector_records) == 1 and source_records[0].attributes.get(
            "type_text"
        ) == inspector_records[0].attributes.get("type_text")
        if matching_types and len(access_records) == 1:
            indexed_support = {
                record.record_id: record
                for record in (
                    *support,
                    source_records[0],
                    inspector_records[0],
                )
            }
            qualifying_support.append(tuple(indexed_support.values()))
    return qualifying_support[0] if len(qualifying_support) == 1 else ()


def _stack_joins(
    bundle: ValidatedBundle,
    frame: FrameEvidence,
    inspector: AdapterResult,
    records_by_id: Mapping[str, EvidenceNode | EvidenceEdge],
) -> tuple[EvidenceEdge, ...]:
    objects = tuple(node for node in inspector.nodes if node.kind == "objobject")
    stacks = tuple(
        node
        for node in frame.result.nodes
        if node.kind == "stack-object" and node.attributes.get("side", "current") == "current"
    )
    edges: list[EvidenceEdge] = []
    for objobject in objects:
        name = str(objobject.attributes.get("name") or "")
        if not name:
            continue
        candidates = [stack for stack in stacks if name in _stack_names(stack)]
        support = _stack_ownership_support(candidates[0], name, records_by_id) if len(candidates) == 1 else ()
        uniquely_correlated = bool(support)
        confidence = Confidence.DERIVED_UNIQUE if uniquely_correlated else Confidence.HEURISTIC
        for ordinal, candidate in enumerate(candidates):
            edges.append(
                _join_edge(
                    bundle,
                    kind="materializes-as-stack-object",
                    source=objobject,
                    target=candidate,
                    occurrence_ordinal=ordinal,
                    confidence=confidence,
                    derivation_rule=(
                        "unique-symbol-expression-consumer-stack-access"
                        if uniquely_correlated
                        else "finite-name-only-stack-candidates"
                    ),
                    attributes={
                        "symbol": name,
                        "candidate_count": len(candidates),
                        "ownership_basis": (
                            "symbol-expression-consumer-stack-access" if uniquely_correlated else "symbol-name-only"
                        ),
                    },
                    support=support,
                )
            )
    return tuple(edges)


def derive_within_compile_joins(
    bundle: ValidatedBundle,
    checkdiff: CheckdiffEvidence,
    backend: BackendEvidence,
    inspector: AdapterResult,
    frame: FrameEvidence,
    source: SourceEvidence,
) -> AdapterResult:
    """Derive only finite compile-local joins; abstain when a segment is absent."""

    results = (
        checkdiff.result,
        backend.result,
        inspector,
        frame.result,
        source.result,
    )
    records_by_id = {record.record_id: record for result in results for record in (*result.nodes, *result.edges)}
    edges = (
        *_expression_joins(bundle, inspector, source),
        *_backend_joins(bundle, backend, inspector),
        *_stack_joins(bundle, frame, inspector, records_by_id),
    )
    return AdapterResult(edges=edges)


def build_frontier_graph(
    bundle: ValidatedBundle,
    store: EvidenceStore,
    checkdiff: CheckdiffEvidence,
    backend: BackendEvidence,
    inspector: AdapterResult,
    frame: FrameEvidence,
    source: SourceEvidence,
) -> FrontierGraph:
    """Ingest adapter evidence, then add proof-capped within-compile joins."""

    adapter_results = (
        checkdiff.result,
        backend.result,
        inspector,
        frame.result,
        source.result,
    )
    _validate_compile_scope(bundle, adapter_results)
    join_result = derive_within_compile_joins(bundle, checkdiff, backend, inspector, frame, source)
    complete_results = (*adapter_results, join_result)
    staging = InMemoryEvidenceStore()
    add_adapter_results_atomically(staging, complete_results)
    add_adapter_results_atomically(store, complete_results)
    return FrontierGraph(
        bundle=bundle,
        store=store,
        checkdiff=checkdiff,
        backend=backend,
        inspector=inspector,
        frame=frame,
        source=source,
        warnings=canonical_warnings(checkdiff, backend, inspector, frame, source, join_result),
    )


__all__ = [
    "FrontierGraph",
    "add_adapter_results_atomically",
    "build_frontier_graph",
    "canonical_warnings",
    "derive_within_compile_joins",
]
