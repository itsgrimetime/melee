"""Collect compile-local source expressions and direct-inline scopes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from src.common import tree_sitter_c
from src.common.tree_sitter_c import find_function_definition, node_text

from ..source_patch import find_function_definitions
from .bundles import BundleInputError, ValidatedBundle
from .canonical import stable_id
from .models import AdapterResult, Confidence, EvidenceNode, Provenance

_PARSER_VERSION = "tree-sitter-c-source-expressions.v1"
_EXPRESSION_TYPES = frozenset(
    {
        "assignment_expression",
        "binary_expression",
        "call_expression",
        "cast_expression",
        "comma_expression",
        "conditional_expression",
        "field_expression",
        "parenthesized_expression",
        "pointer_expression",
        "sizeof_expression",
        "subscript_expression",
        "unary_expression",
        "update_expression",
    }
)
_CONSTANT_TYPES = frozenset(
    {"char_literal", "concatenated_string", "false", "number_literal", "string_literal", "true"}
)
_IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    result: AdapterResult
    expressions_by_signature: Mapping[str, tuple[str, ...]]
    inline_scopes_by_callee: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _Expression:
    owner: str
    node: Any
    node_type: str
    operator: str
    operator_tree: tuple[object, ...]
    identifiers: tuple[str, ...]
    called_functions: tuple[str, ...]
    constants: tuple[str, ...]
    scope_path: tuple[str, ...]
    type_text: str
    text: str
    order: int
    signature: str


def _walk(node: Any) -> tuple[Any, ...]:
    pending = [node]
    found: list[Any] = []
    while pending:
        item = pending.pop()
        found.append(item)
        pending.extend(reversed(item.children))
    return tuple(found)


def _function_calls(node: Any, source_bytes: bytes) -> tuple[str, ...]:
    names: list[str] = []
    for item in _walk(node):
        if item.type != "call_expression":
            continue
        function = item.child_by_field_name("function")
        if function is not None:
            name = node_text(source_bytes, function).strip()
            if _IDENTIFIER.fullmatch(name):
                names.append(name)
    return tuple(sorted(set(names)))


def _identifiers(node: Any, source_bytes: bytes) -> tuple[str, ...]:
    return tuple(sorted({node_text(source_bytes, item).strip() for item in _walk(node) if item.type == "identifier"}))


def _constants(node: Any, source_bytes: bytes) -> tuple[str, ...]:
    return tuple(sorted(node_text(source_bytes, item).strip() for item in _walk(node) if item.type in _CONSTANT_TYPES))


def _operator(node: Any, source_bytes: bytes) -> str:
    if node.type == "call_expression":
        return "call"
    operator = node.child_by_field_name("operator")
    if operator is not None:
        return node_text(source_bytes, operator).strip()
    punctuation = [
        node_text(source_bytes, child).strip()
        for child in node.children
        if not child.is_named and node_text(source_bytes, child).strip() not in {"(", ")", "[", "]"}
    ]
    return punctuation[0] if punctuation else node.type


def _operator_tree(node: Any, source_bytes: bytes) -> tuple[object, ...]:
    if node.type == "identifier":
        return ("identifier", node_text(source_bytes, node).strip())
    if node.type in _CONSTANT_TYPES:
        return (node.type, node_text(source_bytes, node).strip())
    children = tuple(
        _operator_tree(child, source_bytes)
        for child in node.children
        if child.is_named
        and (
            child.type in _EXPRESSION_TYPES
            or child.type in _CONSTANT_TYPES
            or child.type in {"argument_list", "identifier"}
        )
    )
    if node.type in _EXPRESSION_TYPES:
        return (node.type, _operator(node, source_bytes), children)
    return (node.type, children)


def _scope_path(node: Any, owner: str) -> tuple[str, ...]:
    compounds: list[str] = []
    parent = node.parent
    while parent is not None and parent.type != "function_definition":
        if parent.type == "compound_statement":
            row, column = parent.start_point
            compounds.append(f"block@l{row + 1}c{column}")
        parent = parent.parent
    compounds.reverse()
    return (owner, *compounds)


def _type_text(node: Any, source_bytes: bytes) -> str:
    if node.type != "cast_expression":
        return ""
    type_node = node.child_by_field_name("type")
    return "" if type_node is None else node_text(source_bytes, type_node).strip()


def _signature(
    *,
    node_type: str,
    operator: str,
    operator_tree: tuple[object, ...],
    identifiers: tuple[str, ...],
    called_functions: tuple[str, ...],
    constants: tuple[str, ...],
    scope_path: tuple[str, ...],
    type_text: str,
) -> str:
    return stable_id(
        "source-expression-signature.v1",
        "normalized-source-expression",
        (
            node_type,
            operator,
            operator_tree,
            identifiers,
            called_functions,
            constants,
            scope_path,
            type_text,
        ),
    )


def _is_static_inline(source: str, signature_start: int, body_open: int) -> bool:
    header = source[signature_start:body_open]
    return bool(re.search(r"\bstatic\b", header) and re.search(r"\binline\b", header))


def adapt_source(bundle: ValidatedBundle) -> SourceEvidence:
    """Collect target expressions and one directly called static-inline level."""

    try:
        source_bytes = bundle.artifact_paths["source"].read_bytes()
        source = source_bytes.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise BundleInputError(f"invalid source artifact: {error}") from error

    definitions = {span.name: span for span in find_function_definitions(source)}
    try:
        tree = tree_sitter_c.get_parser().parse(source_bytes)
    except tree_sitter_c.TreeSitterUnavailableError:
        return SourceEvidence(
            result=AdapterResult(warnings=("tree-sitter-c unavailable for source evidence",)),
            expressions_by_signature=MappingProxyType({}),
            inline_scopes_by_callee=MappingProxyType({}),
        )

    target_name = bundle.manifest.function
    target = find_function_definition(tree.root_node, source_bytes, target_name)
    if target is None:
        return SourceEvidence(
            result=AdapterResult(warnings=(f"source function not found: {target_name}",)),
            expressions_by_signature=MappingProxyType({}),
            inline_scopes_by_callee=MappingProxyType({}),
        )

    direct_callees = set(_function_calls(target, source_bytes))
    selected: list[tuple[str, Any]] = [(target_name, target)]
    inline_scopes: dict[str, tuple[str, ...]] = {}
    for callee in sorted(direct_callees):
        span = definitions.get(callee)
        if span is None or not _is_static_inline(source, span.sig_start, span.body_open):
            continue
        function_node = find_function_definition(tree.root_node, source_bytes, callee)
        if function_node is None:
            continue
        selected.append((callee, function_node))
        inline_scopes[callee] = (callee,)

    expressions: list[_Expression] = []
    for owner, function_node in selected:
        order = 0
        for item in _walk(function_node):
            if item.type not in _EXPRESSION_TYPES:
                continue
            identifiers = _identifiers(item, source_bytes)
            calls = _function_calls(item, source_bytes)
            constants = _constants(item, source_bytes)
            scope_path = _scope_path(item, owner)
            operator = _operator(item, source_bytes)
            operator_tree = _operator_tree(item, source_bytes)
            type_text = _type_text(item, source_bytes)
            signature = _signature(
                node_type=item.type,
                operator=operator,
                operator_tree=operator_tree,
                identifiers=identifiers,
                called_functions=calls,
                constants=constants,
                scope_path=scope_path,
                type_text=type_text,
            )
            expressions.append(
                _Expression(
                    owner=owner,
                    node=item,
                    node_type=item.type,
                    operator=operator,
                    operator_tree=operator_tree,
                    identifiers=identifiers,
                    called_functions=calls,
                    constants=constants,
                    scope_path=scope_path,
                    type_text=type_text,
                    text=node_text(source_bytes, item).strip(),
                    order=order,
                    signature=signature,
                )
            )
            order += 1

    signature_counts: dict[str, int] = {}
    for expression in expressions:
        signature_counts[expression.signature] = signature_counts.get(expression.signature, 0) + 1

    nodes: list[EvidenceNode] = []
    by_signature: dict[str, list[str]] = {}
    for expression in expressions:
        confidence = Confidence.DERIVED_UNIQUE if signature_counts[expression.signature] == 1 else Confidence.HEURISTIC
        node = EvidenceNode.create(
            compile_id=bundle.compile_id,
            function=target_name,
            kind="source-expression",
            local_key=(expression.node.start_byte, expression.node.end_byte, expression.node_type),
            role_key=None,
            producer_confidence=Confidence.OBSERVED,
            adapter_confidence=confidence,
            provenance=Provenance(
                artifact_sha256=bundle.manifest.artifacts.source.sha256,
                parser=_PARSER_VERSION,
                raw_start=expression.node.start_byte,
                raw_end=expression.node.end_byte,
                derivation_rule=(
                    "unique-normalized-source-expression"
                    if confidence is Confidence.DERIVED_UNIQUE
                    else "ambiguous-normalized-source-expression"
                ),
            ),
            attributes={
                "owner_function": expression.owner,
                "node_type": expression.node_type,
                "operator": expression.operator,
                "operator_tree": expression.operator_tree,
                "identifiers": expression.identifiers,
                "called_functions": expression.called_functions,
                "constants": expression.constants,
                "scope_path": expression.scope_path,
                "type_text": expression.type_text,
                "text": expression.text,
                "order": expression.order,
                "signature": expression.signature,
                "source_span": (expression.node.start_byte, expression.node.end_byte),
            },
        )
        nodes.append(node)
        by_signature.setdefault(expression.signature, []).append(node.record_id)

    return SourceEvidence(
        result=AdapterResult(nodes=tuple(nodes)),
        expressions_by_signature=MappingProxyType(
            {signature: tuple(record_ids) for signature, record_ids in sorted(by_signature.items())}
        ),
        inline_scopes_by_callee=MappingProxyType(inline_scopes),
    )


__all__ = ["SourceEvidence", "adapt_source"]
