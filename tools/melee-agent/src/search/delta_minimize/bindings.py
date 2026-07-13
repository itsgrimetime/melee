"""Conservative TU-local semantic bindings for source delta coupling."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import zip_longest
from typing import Mapping, Sequence

from src.common.tree_sitter_c import get_parser, node_text

from .contracts import DeltaMinimizeError

_LEXICAL_TRIVIA_RE = re.compile(
    r"(?:\s+|//[^\r\n]*(?:\r?\n|\r|$)|/\*.*?\*/)*\Z",
    re.DOTALL,
)

_CHANGE_LOCAL_BLOCKER_REASONS = {
    "unresolved-external-call",
    "unresolved-external-declaration",
}


@dataclass(frozen=True)
class CallBinding:
    callee: str
    call_span: tuple[int, int]
    argument_span: tuple[int, int]
    argument_texts: tuple[str, ...]
    callee_name_span: tuple[int, int] | None = None


@dataclass(frozen=True)
class FunctionSpan:
    name: str
    span: tuple[int, int]


@dataclass(frozen=True)
class CallEdge:
    caller: str
    callee: str
    call_span: tuple[int, int]


@dataclass(frozen=True)
class DeclarationSignature:
    shared_prefix_span: tuple[int, int]
    declarator_span: tuple[int, int]
    shared_prefix_owned_span: tuple[int, int] | None = None


@dataclass(frozen=True)
class FunctionBinding:
    name: str
    definition_span: tuple[int, int]
    parameter_names: tuple[str, ...]
    parameter_span: tuple[int, int]
    direct_calls: tuple[CallBinding, ...]
    parameter_texts: tuple[str, ...] = ()
    declaration_spans: tuple[tuple[int, int], ...] = ()
    declaration_parameter_spans: tuple[tuple[int, int], ...] = ()
    definition_signature_span: tuple[int, int] | None = None
    declaration_signature_spans: tuple[tuple[int, int], ...] = ()
    definition_name_span: tuple[int, int] | None = None
    declaration_name_spans: tuple[tuple[int, int], ...] = ()
    declaration_signatures: tuple[DeclarationSignature, ...] = ()
    type_shapes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BindingBlocker:
    symbol: str
    reason: str
    span: tuple[int, int]
    owned_span: tuple[int, int] | None = None


@dataclass(frozen=True)
class LocalBinding:
    function: str
    name: str
    declaration_span: tuple[int, int]
    use_spans: tuple[tuple[int, int], ...]
    scope_span: tuple[int, int]
    scope_is_compound: bool


@dataclass(frozen=True)
class BindingIndex:
    functions: Mapping[str, FunctionBinding]
    blockers: tuple[BindingBlocker, ...]
    locals: tuple[LocalBinding, ...] = ()
    function_spans: tuple[FunctionSpan, ...] = ()
    call_edges: tuple[CallEdge, ...] = ()
    definition_counts: Mapping[str, int] | None = None
    source: str = ""


class UnionFind:
    def __init__(self, values: Sequence[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def build_binding_index(source: str) -> BindingIndex:
    """Index only direct, unshadowed calls to unique TU-local definitions."""

    source_bytes = source.encode("utf-8")
    root = get_parser().parse(source_bytes).root_node
    to_char = _byte_to_char_offsets(source)
    function_nodes: dict[str, list[tuple[object, object, object, object]]] = defaultdict(list)
    declaration_nodes: dict[str, list[tuple[object, object, object, object]]] = defaultdict(list)
    macro_names: set[str] = set()
    blockers: list[BindingBlocker] = []
    type_identifier_nodes: dict[str, list[object]] = defaultdict(list)

    for node in _walk_type(root, "type_identifier"):
        type_identifier_nodes[node_text(source_bytes, node)].append(node)

    for node in _walk(root):
        if node.type == "ERROR":
            blockers.append(BindingBlocker("*", "parse-error", _span(node, to_char)))
        elif (
            node.type.startswith("preproc_")
            and node.type not in {"preproc_def", "preproc_function_def"}
            and not _has_preprocessor_ancestor(node)
        ):
            reason = (
                "conditional-compilation" if node.type in {"preproc_if", "preproc_ifdef"} else "preprocessor-directive"
            )
            blockers.append(BindingBlocker("*", reason, _span(node, to_char)))

    for node in root.named_children:
        if node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            parts = _function_declaration_parts(declarator)
            if parts is None:
                name_node = _declarator_identifier(declarator)
                symbol = node_text(source_bytes, name_node) if name_node is not None else "*"
                blockers.append(BindingBlocker(symbol, "k-and-r-or-unresolved-definition", _span(node, to_char)))
                continue
            name_node, parameters = parts
            name = node_text(source_bytes, name_node)
            function_nodes[name].append((node, name_node, parameters, declarator))
        elif node.type == "declaration":
            for declarator in node.named_children:
                parts = _function_declaration_parts(declarator)
                if parts is None:
                    continue
                name_node, parameters = parts
                name = node_text(source_bytes, name_node)
                declaration_nodes[name].append((node, name_node, parameters, declarator))
        elif node.type in {"preproc_def", "preproc_function_def"}:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = node_text(source_bytes, name_node)
                macro_names.add(name)
                blockers.append(BindingBlocker(name, "macro-definition", _span(node, to_char)))

    for declaration in _walk_type(root, "declaration"):
        declarators = tuple(_declaration_declarators(declaration))
        if not declarators:
            continue
        shared_prefix_span = (
            to_char[declaration.start_byte],
            to_char[declarators[0].start_byte],
        )
        shared_prefix_owned_span = _declaration_shared_prefix_owned_span(
            declaration,
            declarators[0],
            to_char,
        )
        for declarator in declarators:
            name_node = _function_pointer_object_identifier(declarator)
            if name_node is not None:
                symbol = node_text(source_bytes, name_node)
                blockers.extend(
                    (
                        BindingBlocker(
                            symbol,
                            "function-pointer-object-declaration",
                            shared_prefix_span,
                            shared_prefix_owned_span,
                        ),
                        BindingBlocker(
                            symbol,
                            "function-pointer-object-declaration",
                            _span(declarator, to_char),
                        ),
                    )
                )

    unique_nodes: dict[str, tuple[object, object, object, object]] = {}
    for name, definitions in sorted(function_nodes.items()):
        if len(definitions) != 1:
            blockers.extend(
                BindingBlocker(name, "duplicate-definition", _span(node, to_char)) for node, _, _, _ in definitions
            )
            continue
        unique_nodes[name] = definitions[0]

    calls_by_name: dict[str, list[CallBinding]] = defaultdict(list)
    call_edges: list[CallEdge] = []
    definition_names_by_span = {
        (node.start_byte, node.end_byte): name
        for name, definitions in function_nodes.items()
        for node, _, _, _ in definitions
    }
    supported_callee_spans: set[tuple[int, int]] = set()
    for call in _walk_type(root, "call_expression"):
        callee_node = call.child_by_field_name("function")
        arguments = call.child_by_field_name("arguments")
        callee = node_text(source_bytes, callee_node).strip() if callee_node is not None else "*"
        call_span = _span(call, to_char)
        owner = _ancestor(call, "function_definition")
        local_declarations = (
            _visible_local_declarations(call, owner, source_bytes, to_char) if owner is not None else {}
        )
        if arguments is None or callee_node is None:
            blockers.append(BindingBlocker(callee or "*", "indirect-call", call_span))
            continue
        if _is_parenthesized_known_type_cast(
            call,
            callee_node,
            owner,
            type_identifier_nodes,
            local_declarations,
            source_bytes,
        ):
            continue
        if callee_node.type != "identifier":
            blockers.append(BindingBlocker(callee or "*", "indirect-call", call_span))
            continue
        if _has_preprocessor_ancestor(call):
            blockers.append(BindingBlocker(callee, "conditional-call", call_span))
            continue
        if callee in macro_names or (callee.isupper() and callee not in unique_nodes):
            blockers.append(BindingBlocker(callee, "macro-like-call", call_span))
            continue

        if callee in local_declarations:
            blockers.append(BindingBlocker(callee, "shadowed-call", call_span))
            if callee in unique_nodes:
                blockers.extend(
                    BindingBlocker(callee, "shadowing-declaration", span) for span in local_declarations[callee]
                )
            continue
        if callee not in function_nodes:
            blockers.append(
                BindingBlocker(
                    callee,
                    "unresolved-external-call",
                    call_span,
                    _span(callee_node, to_char),
                )
            )
            continue

        if owner is not None:
            caller = definition_names_by_span.get((owner.start_byte, owner.end_byte))
            if caller is not None:
                call_edges.append(CallEdge(caller, callee, call_span))
        if callee not in unique_nodes:
            blockers.append(BindingBlocker(callee, "duplicate-definition-call", call_span))
            continue

        calls_by_name[callee].append(
            CallBinding(
                callee=callee,
                call_span=call_span,
                argument_span=_span(arguments, to_char),
                argument_texts=tuple(
                    node_text(source_bytes, argument).strip() for argument in arguments.named_children
                ),
                callee_name_span=_span(callee_node, to_char),
            )
        )
        supported_callee_spans.add((callee_node.start_byte, callee_node.end_byte))

    declaration_name_spans = _declaration_name_byte_spans(root)
    function_name_spans = {
        (name_node.start_byte, name_node.end_byte)
        for definitions in function_nodes.values()
        for _, name_node, _, _ in definitions
    } | {
        (name_node.start_byte, name_node.end_byte)
        for declarations in declaration_nodes.values()
        for _, name_node, _, _ in declarations
    }
    for identifier in _walk_type(root, "identifier"):
        name = node_text(source_bytes, identifier)
        if name not in unique_nodes:
            continue
        identifier_span = (identifier.start_byte, identifier.end_byte)
        if identifier_span in function_name_spans | declaration_name_spans | supported_callee_spans:
            continue
        owner = _ancestor(identifier, "function_definition")
        if owner is not None and name in _visible_local_declarations(
            identifier,
            owner,
            source_bytes,
            to_char,
        ):
            continue
        blockers.append(
            BindingBlocker(
                name,
                "non-call-function-reference",
                _span(_non_call_reference_node(identifier), to_char),
            )
        )

    functions: dict[str, FunctionBinding] = {}
    for name, (definition, definition_name, parameters, definition_declarator) in sorted(
        unique_nodes.items(),
        key=lambda item: item[1][0].start_byte,
    ):
        parameter_names = _parameter_names(parameters, source_bytes)
        if parameter_names is None:
            blockers.append(BindingBlocker(name, "k-and-r-or-unnamed-parameters", _span(parameters, to_char)))
            parameter_names = ()
        functions[name] = FunctionBinding(
            name=name,
            definition_span=_span(definition, to_char),
            parameter_names=parameter_names,
            parameter_span=_span(parameters, to_char),
            direct_calls=tuple(sorted(calls_by_name[name], key=lambda item: item.call_span)),
            parameter_texts=_parameter_texts(parameters, source_bytes),
            declaration_spans=tuple(
                _span(declaration, to_char) for declaration, _, _, _ in declaration_nodes.get(name, ())
            ),
            declaration_parameter_spans=tuple(
                _span(declaration_parameters, to_char)
                for _, _, declaration_parameters, _ in declaration_nodes.get(name, ())
            ),
            definition_signature_span=_definition_signature_span(definition, to_char),
            definition_name_span=_span(definition_name, to_char),
            declaration_name_spans=tuple(
                _span(declaration_name, to_char) for _, declaration_name, _, _ in declaration_nodes.get(name, ())
            ),
            declaration_signatures=tuple(
                _declaration_signature(declaration, declaration_declarator, to_char)
                for declaration, _, _, declaration_declarator in declaration_nodes.get(name, ())
            ),
            type_shapes=(
                _normalized_function_type_shape(
                    definition,
                    definition_declarator,
                    definition_name,
                    parameters,
                    source_bytes,
                ),
                *(
                    _normalized_function_type_shape(
                        declaration,
                        declaration_declarator,
                        declaration_name,
                        declaration_parameters,
                        source_bytes,
                    )
                    for declaration, declaration_name, declaration_parameters, declaration_declarator in declaration_nodes.get(
                        name, ()
                    )
                ),
            ),
        )

    for name in declaration_nodes.keys() - functions.keys():
        blockers.extend(
            BindingBlocker(name, "unresolved-external-declaration", _span(node, to_char))
            for node, _, _, _ in declaration_nodes[name]
        )

    local_bindings = _build_local_bindings(
        unique_nodes,
        source_bytes,
        to_char,
    )
    blockers = sorted(set(blockers), key=lambda item: (item.span, item.symbol, item.reason))
    return BindingIndex(
        functions=functions,
        blockers=tuple(blockers),
        locals=local_bindings,
        function_spans=tuple(
            FunctionSpan(name, _span(node, to_char))
            for name, definitions in sorted(function_nodes.items())
            for node, _, _, _ in definitions
        ),
        call_edges=tuple(sorted(call_edges, key=lambda edge: (edge.call_span, edge.caller, edge.callee))),
        definition_counts={name: len(definitions) for name, definitions in function_nodes.items()},
        source=source,
    )


def validate_target_definition(index: BindingIndex, target: str, *, side: str) -> None:
    """Require one target definition before deriving a call closure."""

    counts = index.definition_counts or {
        name: sum(span.name == name for span in index.function_spans)
        for name in {span.name for span in index.function_spans}
    }
    count = counts.get(target, 0)
    if count == 1:
        return
    raise DeltaMinimizeError(
        "ambiguous-delta-scope",
        {
            "target": target,
            "side": side,
            "definition_count": count,
            "reason": "missing-target-definition" if count == 0 else "duplicate-target-definition",
        },
    )


def reachable_functions(index: BindingIndex, target: str, *, side: str | None = None) -> frozenset[str]:
    """Return the TU-local caller-to-callee closure rooted at ``target``."""

    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in index.call_edges:
        outgoing[edge.caller].add(edge.callee)
    seen: set[str] = set()
    pending = [target]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        count = (index.definition_counts or {}).get(current, 1 if current in index.functions else 0)
        if count != 1:
            raise DeltaMinimizeError(
                "ambiguous-delta-scope",
                {
                    "target": target,
                    "side": side or "unknown",
                    "symbol": current,
                    "definition_count": count,
                    "reason": (
                        "missing-reachable-definition" if count == 0 else "duplicate-reachable-definition"
                    ),
                },
            )
        seen.add(current)
        pending.extend(sorted(outgoing.get(current, ()), reverse=True))
    return frozenset(seen)


def lexical_owners(index: BindingIndex, span: tuple[int, int]) -> tuple[str, ...]:
    """Return every function definition that conservatively owns ``span``."""

    start, end = span
    if start == end:
        owners = {
            item.name
            for item in index.function_spans
            if item.span[0] < start < item.span[1]
        }
    else:
        owners = {
            item.name
            for item in index.function_spans
            if item.span[0] <= start and end <= item.span[1]
        }
        if not owners and index.source:
            overlaps = [
                item
                for item in index.function_spans
                if start < item.span[1] and item.span[0] < end
            ]
            if len(overlaps) == 1:
                owner = overlaps[0]
                if _span_belongs_to_function_binding(index, owner.name, (start, end)):
                    owners = {owner.name}
    return tuple(sorted(owners))


def overlapping_functions(index: BindingIndex, span: tuple[int, int]) -> tuple[str, ...]:
    """Return functions touched by a non-empty span, including partial overlaps."""

    start, end = span
    if start == end:
        return ()
    return tuple(
        sorted(
            {
                item.name
                for item in index.function_spans
                if start < item.span[1] and item.span[0] < end
            }
        )
    )


def _is_lexical_trivia(text: str) -> bool:
    return bool(_LEXICAL_TRIVIA_RE.fullmatch(text))


def _span_belongs_to_function_binding(
    index: BindingIndex,
    name: str,
    span: tuple[int, int],
) -> bool:
    """Allow declaration/definition fragments joined only by lexical trivia."""

    function = index.functions.get(name)
    if function is None:
        return False
    start, end = span
    cursor = start
    binding_spans = sorted((function.definition_span, *function.declaration_spans))
    for owned_start, owned_end in binding_spans:
        if owned_end <= cursor or owned_start >= end:
            continue
        gap_end = min(owned_start, end)
        if cursor < gap_end and not _is_lexical_trivia(index.source[cursor:gap_end]):
            return False
        cursor = max(cursor, min(owned_end, end))
        if cursor == end:
            return True
    return _is_lexical_trivia(index.source[cursor:end])


def validate_supported_bindings(
    index: BindingIndex,
    changed_names: set[str],
    changed_spans: Sequence[tuple[int, int]] | None = None,
    renamed_names: set[str] | None = None,
    type_unchanged_names: set[str] | None = None,
    atomic_external_call_spans: Sequence[tuple[int, int]] = (),
) -> None:
    renamed_names = renamed_names or set()
    type_unchanged_names = type_unchanged_names or set()
    atomic_external_calls = set(atomic_external_call_spans)
    blockers = [
        blocker
        for blocker in index.blockers
        if blocker.symbol in changed_names
        and not (
            blocker.reason == "unresolved-external-call"
            and blocker.span in atomic_external_calls
        )
        and (
            blocker.reason not in _CHANGE_LOCAL_BLOCKER_REASONS
            or changed_spans is None
            or any(
                _spans_touch(change, blocker.owned_span or blocker.span)
                for change in changed_spans
            )
        )
        and (
            blocker.reason != "non-call-function-reference"
            or blocker.symbol in renamed_names
            or blocker.symbol not in type_unchanged_names
            or changed_spans is None
            or any(_spans_touch(change, blocker.owned_span or blocker.span) for change in changed_spans)
        )
    ]
    if blockers:
        raise DeltaMinimizeError(
            "unsupported-semantic-binding",
            {
                "blockers": [
                    {
                        "symbol": blocker.symbol,
                        "reason": blocker.reason,
                        "span": blocker.span,
                    }
                    for blocker in blockers
                ]
            },
        )


def couple_semantic_atoms(
    left_index: BindingIndex,
    right_index: BindingIndex,
    atoms,
    *,
    seed_atom_ids: set[str] | frozenset[str] | None = None,
    scope_functions: set[str] | frozenset[str] | None = None,
    left_scope_functions: set[str] | frozenset[str] | None = None,
    right_scope_functions: set[str] | frozenset[str] | None = None,
):
    """Collapse atoms that must move together to preserve known bindings."""

    groups = UnionFind(tuple(atom.atom_id for atom in atoms))
    _union_overlaps(groups, atoms)

    scoped_atoms = (
        tuple(atom for atom in atoms if atom.atom_id in seed_atom_ids)
        if seed_atom_ids is not None
        else atoms
    )
    left_changed_spans = _changed_spans(scoped_atoms, side="left")
    right_changed_spans = _changed_spans(scoped_atoms, side="right")
    left_atomic_external_calls = _one_sided_external_calls_by_atom(
        left_index,
        scoped_atoms,
        side="left",
    )
    right_atomic_external_calls = _one_sided_external_calls_by_atom(
        right_index,
        scoped_atoms,
        side="right",
    )
    left_atomic_external_call_spans = _safe_atomic_external_call_spans(
        left_atomic_external_calls,
        right_atomic_external_calls,
    )
    right_atomic_external_call_spans = _safe_atomic_external_call_spans(
        right_atomic_external_calls,
        left_atomic_external_calls,
    )
    left_changed = _changed_binding_names(left_index, left_changed_spans)
    right_changed = _changed_binding_names(right_index, right_changed_spans)
    pairs = _pair_functions(
        left_index,
        right_index,
        atoms=atoms,
        selected_names=scope_functions,
        left_selected_names=left_scope_functions,
        right_selected_names=right_scope_functions,
    )
    for left_function, right_function, _ in pairs:
        if left_function.name in left_changed or right_function.name in right_changed:
            left_changed.add(left_function.name)
            right_changed.add(right_function.name)
    left_renamed = {left.name for left, _, renamed in pairs if renamed}
    right_renamed = {right.name for _, right, renamed in pairs if renamed}
    left_type_unchanged = {
        left.name for left, right, renamed in pairs if not renamed and _function_type_is_proven_unchanged(left, right)
    }
    right_type_unchanged = {
        right.name for left, right, renamed in pairs if not renamed and _function_type_is_proven_unchanged(left, right)
    }
    validate_supported_bindings(
        left_index,
        left_changed,
        left_changed_spans,
        left_renamed,
        left_type_unchanged,
        left_atomic_external_call_spans,
    )
    validate_supported_bindings(
        right_index,
        right_changed,
        right_changed_spans,
        right_renamed,
        right_type_unchanged,
        right_atomic_external_call_spans,
    )

    semantic_labels: dict[str, list[str]] = defaultdict(list)
    reclassified: dict[tuple[str, int], str] = {}
    for left_function, right_function, renamed in pairs:
        if _has_signature_patch(atoms, left_function, right_function):
            permutation = _parameter_permutation(
                left_function,
                right_function,
                atoms,
            )
            parameter_only = _signature_change_is_parameter_only(
                atoms,
                left_function,
                right_function,
            )
            coupled = _couple_signature_change(
                groups,
                atoms,
                left_function,
                right_function,
                reclassified,
            )
            if coupled:
                change = "parameter reorder" if permutation is not None and parameter_only else "signature change"
                semantic_labels[coupled[0]].append(f"{right_function.name} {change}")
        if renamed:
            coupled = _couple_rename(
                groups,
                atoms,
                left_function,
                right_function,
            )
            if coupled:
                semantic_labels[coupled[0]].append(f"{left_function.name} to {right_function.name} rename")

    _couple_one_sided_functions(
        groups,
        atoms,
        left_index,
        right_index,
        pairs,
        semantic_labels,
        left_scope_functions=left_scope_functions,
        right_scope_functions=right_scope_functions,
    )

    _couple_structural_delimiters(
        groups,
        atoms,
        semantic_labels,
    )
    _couple_local_binding_changes(
        groups,
        atoms,
        left_index,
        right_index,
        semantic_labels,
        selected_functions=scope_functions,
    )
    _union_dependency_cycles(groups, atoms)

    # Semantic unions can change roots, so attach labels to their final roots.
    labels_by_root: dict[str, list[str]] = defaultdict(list)
    for atom_id, labels in semantic_labels.items():
        labels_by_root[groups.find(atom_id)].extend(labels)
    return _materialize_composite_atoms(
        groups,
        atoms,
        labels_by_root,
        reclassified,
    )


def _couple_one_sided_functions(
    groups: UnionFind,
    atoms,
    left_index: BindingIndex,
    right_index: BindingIndex,
    pairs,
    semantic_labels: dict[str, list[str]],
    *,
    left_scope_functions: set[str] | frozenset[str] | None,
    right_scope_functions: set[str] | frozenset[str] | None,
) -> None:
    """Keep a reachable helper's one-sided binding graph syntactically whole."""

    paired_left = {left.name for left, _, _ in pairs}
    paired_right = {right.name for _, right, _ in pairs}
    for side, index, other, selected, paired in (
        ("left", left_index, right_index, left_scope_functions, paired_left),
        ("right", right_index, left_index, right_scope_functions, paired_right),
    ):
        reachable = set(selected or ())
        for name in sorted(index.functions.keys() - other.functions.keys()):
            if name not in reachable or name in paired:
                continue
            function = index.functions[name]
            spans = [
                function.definition_span,
                *function.declaration_spans,
                *(call.call_span for call in function.direct_calls),
            ]
            selected_atoms = _atoms_for_directional_spans(atoms, spans, side=side)
            _union_ids(groups, selected_atoms)
            if selected_atoms:
                semantic_labels[selected_atoms[0]].append(
                    f"{name} function {'removal' if side == 'left' else 'introduction'}"
                )


def _couple_structural_delimiters(
    groups: UnionFind,
    atoms,
    semantic_labels: dict[str, list[str]],
) -> None:
    """Keep the two boundaries of an introduced/removed compound together."""
    boundaries: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: {"open": [], "close": []})
    streams: dict[tuple[str, str], list[tuple[int, str, bool, bool]]] = defaultdict(list)
    for atom in atoms:
        for patch in atom.patches:
            anchor = patch.anchor_symbol
            if not isinstance(anchor, str) or "|" not in anchor:
                continue
            left_anchor, right_anchor = anchor.split("|", 1)
            left_parts = left_anchor.split(":", 2)
            if len(left_parts) != 3:
                continue
            function = left_parts[0]
            candidates = (
                (
                    "right",
                    right_anchor,
                    patch.right_text,
                    patch.left_start == patch.left_end,
                    patch.right_start,
                ),
                (
                    "left",
                    left_parts[2],
                    patch.left_text,
                    patch.right_start == patch.right_end,
                    patch.left_start,
                ),
            )
            for side, path, text, opposite_empty, position in candidates:
                if not opposite_empty or not path.endswith("/compound_statement"):
                    continue
                stripped = text.strip()
                opens = stripped.startswith("{")
                closes = stripped.endswith("}")
                if opens:
                    boundaries[(side, path)]["open"].append(atom.atom_id)
                if closes:
                    boundaries[(side, path)]["close"].append(atom.atom_id)
                if opens or closes:
                    streams[(side, function)].append((position, atom.atom_id, opens, closes))

    for (side, path), sides in sorted(boundaries.items()):
        selected = tuple(dict.fromkeys((*sides["open"], *sides["close"])))
        if not sides["open"] or not sides["close"] or len(selected) < 2:
            continue
        _union_ids(groups, selected)
        semantic_labels[selected[0]].append(f"{side} compound wrapper {path}")

    # Tree differencing may anchor a closing brace to the final nested
    # statement rather than to the compound opened by an earlier patch.  A
    # lexical balance over compound-boundary patches supplies the missing
    # relationship without coupling unrelated expression braces.
    for (side, function), events in sorted(streams.items()):
        stack: list[str] = []
        for _position, atom_id, opens, closes in sorted(events):
            if opens:
                stack.append(atom_id)
            if closes and stack:
                opening = stack.pop()
                if opening != atom_id:
                    _union_ids(groups, (opening, atom_id))
                    semantic_labels[opening].append(f"{side} compound wrapper {function}")


def _pair_functions(
    left_index: BindingIndex,
    right_index: BindingIndex,
    *,
    selected_names: set[str] | frozenset[str] | None = None,
    left_selected_names: set[str] | frozenset[str] | None = None,
    right_selected_names: set[str] | frozenset[str] | None = None,
    atoms=None,
):
    selected = None if selected_names is None else set(selected_names)
    pairs = [
        (left_index.functions[name], right_index.functions[name], False)
        for name in left_index.functions.keys() & right_index.functions.keys()
        if selected is None or name in selected
    ]
    left_only = [
        binding
        for name, binding in left_index.functions.items()
        if name not in right_index.functions and (selected is None or name in selected)
    ]
    right_only = [
        binding
        for name, binding in right_index.functions.items()
        if name not in left_index.functions and (selected is None or name in selected)
    ]
    if not left_only or not right_only:
        return sorted(pairs, key=lambda item: item[0].definition_span)

    left_reachable = set(left_selected_names or selected or ())
    right_reachable = set(right_selected_names or selected or ())
    left_only = [binding for binding in left_only if binding.name in left_reachable]
    right_only = [binding for binding in right_only if binding.name in right_reachable]
    if not left_only or not right_only:
        return sorted(pairs, key=lambda item: item[0].definition_span)

    candidates = {
        left.name: [
            right
            for right in right_only
            if sorted(left.parameter_names) == sorted(right.parameter_names)
            and _has_rename_pair_evidence(atoms or (), left, right)
        ]
        for left in left_only
    }
    ambiguous = {name: options for name, options in candidates.items() if len(options) > 1}
    if ambiguous:
        alternatives = [
            _rename_coupling_alternative(left, right, atoms or ())
            for left in left_only
            for right in ambiguous.get(left.name, ())
        ]
        raise DeltaMinimizeError(
            "ambiguous-delta-coupling",
            {
                "candidate_symbols": {
                    name: [item.name for item in options]
                    for name, options in ambiguous.items()
                },
                "alternatives": sorted(
                    alternatives,
                    key=lambda item: item["label"],
                ),
            },
        )
    selected_pairs = [(left, candidates[left.name][0]) for left in left_only if len(candidates[left.name]) == 1]
    by_right: dict[str, list[tuple[FunctionBinding, FunctionBinding]]] = defaultdict(list)
    for left, right in selected_pairs:
        by_right[right.name].append((left, right))
    duplicate_rights = {
        right_name: pairings
        for right_name, pairings in by_right.items()
        if len(pairings) > 1
    }
    if duplicate_rights:
        raise DeltaMinimizeError(
            "ambiguous-delta-coupling",
            {
                "duplicate_right_candidates": {
                    right_name: [left.name for left, _right in pairings]
                    for right_name, pairings in duplicate_rights.items()
                },
                "alternatives": [
                    _rename_coupling_alternative(left, right, atoms or ())
                    for pairings in duplicate_rights.values()
                    for left, right in pairings
                ],
            },
        )
    pairs.extend((left, right, True) for left, right in selected_pairs)
    return sorted(pairs, key=lambda item: item[0].definition_span)


def _rename_coupling_alternative(
    left: FunctionBinding,
    right: FunctionBinding,
    atoms,
) -> dict[str, object]:
    """Describe one possible rename without granting authority to select it."""

    left_spans = tuple(
        dict.fromkeys(
            (
                left.definition_name_span or left.definition_span,
                *_declaration_name_spans(left),
                *(
                    call.callee_name_span or call.call_span
                    for call in left.direct_calls
                ),
            )
        )
    )
    right_spans = tuple(
        dict.fromkeys(
            (
                right.definition_name_span or right.definition_span,
                *_declaration_name_spans(right),
                *(
                    call.callee_name_span or call.call_span
                    for call in right.direct_calls
                ),
            )
        )
    )
    atom_ids = tuple(
        dict.fromkeys(
            (
                *_atoms_for_directional_spans(atoms, left_spans, side="left"),
                *_atoms_for_directional_spans(
                    atoms,
                    right_spans,
                    side="right",
                ),
            )
        )
    )
    return {
        "label": f"{left.name} -> {right.name}",
        "reason": "competing-function-rename",
        "symbols": [left.name, right.name],
        "atom_ids": list(atom_ids),
        "left_spans": [list(span) for span in left_spans],
        "right_spans": [list(span) for span in right_spans],
    }


def _coupling_evidence(
    *,
    label: str,
    reason: str,
    symbols: Sequence[str],
    atoms,
    left_spans: Sequence[tuple[int, int]],
    right_spans: Sequence[tuple[int, int]],
) -> dict[str, object]:
    """Describe factual bilateral binding evidence without choosing it."""

    left_spans = tuple(dict.fromkeys(left_spans))
    right_spans = tuple(dict.fromkeys(right_spans))
    atom_ids = tuple(
        dict.fromkeys(
            (
                *_atoms_for_directional_spans(atoms, left_spans, side="left"),
                *_atoms_for_directional_spans(
                    atoms,
                    right_spans,
                    side="right",
                ),
            )
        )
    )
    return {
        "label": label,
        "reason": reason,
        "symbols": list(dict.fromkeys(symbols)),
        "atom_ids": list(atom_ids),
        "left_spans": [list(span) for span in left_spans],
        "right_spans": [list(span) for span in right_spans],
    }


def _call_pairing_alternatives(
    left: FunctionBinding,
    right: FunctionBinding,
    atoms,
) -> list[dict[str, object]]:
    symbols = tuple(dict.fromkeys((left.name, right.name)))
    if left.direct_calls and right.direct_calls:
        pairings = [
            _coupling_evidence(
                label=(
                    f"{right.name} direct call left[{left_index}] "
                    f"-> right[{right_index}]"
                ),
                reason="competing-direct-call-pairing",
                symbols=symbols,
                atoms=atoms,
                left_spans=(left_call.call_span,),
                right_spans=(right_call.call_span,),
            )
            for left_index, left_call in enumerate(left.direct_calls)
            for right_index, right_call in enumerate(right.direct_calls)
        ]
        return [pairing for pairing in pairings if pairing["atom_ids"]]
    left_anchor = left.definition_name_span or left.definition_span
    right_anchor = right.definition_name_span or right.definition_span
    return [
        _coupling_evidence(
            label=f"{right.name} unpaired direct-call evidence",
            reason="conflicting-unpaired-direct-call-set",
            symbols=symbols,
            atoms=atoms,
            left_spans=tuple(call.call_span for call in left.direct_calls)
            or (left_anchor,),
            right_spans=tuple(call.call_span for call in right.direct_calls)
            or (right_anchor,),
        )
    ]


def _signature_evidence_spans(
    function: FunctionBinding,
) -> tuple[tuple[int, int], ...]:
    definition = function.definition_signature_span or function.parameter_span
    return (definition, *function.declaration_spans)


def _has_rename_pair_evidence(atoms, left: FunctionBinding, right: FunctionBinding) -> bool:
    """Require paired definition and direct-call name edits before inferring a rename."""

    left_definition = left.definition_name_span
    right_definition = right.definition_name_span
    if left_definition is None or right_definition is None:
        return False
    definition_changed = bool(_atoms_for_span(atoms, left_definition, right_definition))
    if not definition_changed or len(left.direct_calls) != len(right.direct_calls):
        return False
    return bool(left.direct_calls) and all(
        _atoms_for_span(
            atoms,
            left_call.callee_name_span or left_call.call_span,
            right_call.callee_name_span or right_call.call_span,
        )
        for left_call, right_call in zip(left.direct_calls, right.direct_calls, strict=True)
    )


def _parameter_permutation(
    left: FunctionBinding,
    right: FunctionBinding,
    atoms,
) -> tuple[int, ...] | None:
    has_duplicate_names = (
        len(set(left.parameter_names)) != len(left.parameter_names)
        or len(set(right.parameter_names)) != len(right.parameter_names)
    )
    if has_duplicate_names:
        if left.parameter_names != right.parameter_names:
            raise DeltaMinimizeError(
                "ambiguous-delta-coupling",
                {
                    "symbol": left.name,
                    "parameter_pairing": "duplicate-name",
                    "left_parameters": list(left.parameter_names),
                    "right_parameters": list(right.parameter_names),
                    "alternatives": [
                        _coupling_evidence(
                            label=f"{left.name} parameter-name evidence",
                            reason="conflicting-parameter-name-evidence",
                            symbols=(left.name,),
                            atoms=atoms,
                            left_spans=(left.parameter_span,),
                            right_spans=(right.parameter_span,),
                        )
                    ],
                },
            )
        return None
    if sorted(left.parameter_names) != sorted(right.parameter_names):
        return None
    order = tuple(left.parameter_names.index(name) for name in right.parameter_names)
    identity = tuple(range(len(order)))
    if order == identity:
        return None
    if left.parameter_texts and right.parameter_texts:
        reordered = tuple(left.parameter_texts[index] for index in order)
        if reordered != right.parameter_texts:
            return None
    return order


def _function_type_is_proven_unchanged(left: FunctionBinding, right: FunctionBinding) -> bool:
    return bool(left.type_shapes and right.type_shapes and left.type_shapes == right.type_shapes)


def _has_signature_patch(atoms, left: FunctionBinding, right: FunctionBinding) -> bool:
    left_spans = _signature_spans(left)
    right_spans = _signature_spans(right)
    return any(
        any(
            _patch_pair_intersects_owned_spans(
                (patch.left_start, patch.left_end),
                (patch.right_start, patch.right_end),
                left_span,
                right_span,
            )
            for left_span, right_span in zip_longest(left_spans, right_spans)
        )
        for atom in atoms
        for patch in atom.patches
    )


def _signature_change_is_parameter_only(atoms, left: FunctionBinding, right: FunctionBinding) -> bool:
    left_signatures = _signature_spans(left)
    right_signatures = _signature_spans(right)
    left_parameters = (left.parameter_span, *left.declaration_parameter_spans)
    right_parameters = (right.parameter_span, *right.declaration_parameter_spans)
    for atom in atoms:
        for patch in atom.patches:
            left_change = (patch.left_start, patch.left_end)
            right_change = (patch.right_start, patch.right_end)
            touches_signature = any(
                _patch_pair_intersects_owned_spans(
                    left_change,
                    right_change,
                    left_span,
                    right_span,
                )
                for left_span, right_span in zip_longest(left_signatures, right_signatures)
            )
            touches_parameters = any(
                _patch_pair_intersects_owned_spans(
                    left_change,
                    right_change,
                    left_span,
                    right_span,
                )
                for left_span, right_span in zip_longest(left_parameters, right_parameters)
            )
            if touches_signature and not touches_parameters:
                return False
    return True


def _signature_spans(function: FunctionBinding) -> tuple[tuple[int, int], ...]:
    definition = function.definition_signature_span or function.parameter_span
    declarations = tuple(span for signature in _declaration_signature_parts(function) for span in signature)
    return (definition, *declarations)


def _declaration_signature_parts(
    function: FunctionBinding,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    if function.declaration_signatures:
        return tuple(
            (
                signature.shared_prefix_owned_span or signature.shared_prefix_span,
                signature.declarator_span,
            )
            for signature in function.declaration_signatures
        )
    spans = function.declaration_signature_spans or function.declaration_parameter_spans
    return tuple((span,) for span in spans)


def _couple_signature_change(
    groups: UnionFind,
    atoms,
    left: FunctionBinding,
    right: FunctionBinding,
    reclassified: dict[tuple[str, int], str],
) -> tuple[str, ...]:
    if len(left.direct_calls) != len(right.direct_calls):
        raise DeltaMinimizeError(
            "ambiguous-delta-coupling",
            {
                "symbol": left.name,
                "left_calls": len(left.direct_calls),
                "right_calls": len(right.direct_calls),
                "left_call_spans": [
                    list(call.call_span) for call in left.direct_calls
                ],
                "right_call_spans": [
                    list(call.call_span) for call in right.direct_calls
                ],
                "alternatives": _call_pairing_alternatives(
                    left,
                    right,
                    atoms,
                ),
            },
        )
    selected: list[str] = []
    selected.extend(
        _atoms_for_span(
            atoms,
            left.definition_signature_span or left.parameter_span,
            right.definition_signature_span or right.parameter_span,
            reclassified,
            "function_signature",
        )
    )
    left_declaration_signatures = _declaration_signature_parts(left)
    right_declaration_signatures = _declaration_signature_parts(right)
    if len(left_declaration_signatures) != len(right_declaration_signatures):
        raise DeltaMinimizeError(
            "ambiguous-delta-coupling",
            {
                "symbol": left.name,
                "declaration_pairing": "count-mismatch",
                "left_declarations": len(left_declaration_signatures),
                "right_declarations": len(right_declaration_signatures),
                "alternatives": [
                    _coupling_evidence(
                        label=f"{left.name} declaration signature evidence",
                        reason="conflicting-declaration-signature-count",
                        symbols=(left.name,),
                        atoms=atoms,
                        left_spans=_signature_evidence_spans(left),
                        right_spans=_signature_evidence_spans(right),
                    )
                ],
            },
        )
    for declaration_index, (left_signature, right_signature) in enumerate(
        zip(
            left_declaration_signatures,
            right_declaration_signatures,
            strict=True,
        )
    ):
        if len(left_signature) != len(right_signature):
            raise DeltaMinimizeError(
                "ambiguous-delta-coupling",
                {
                    "symbol": left.name,
                    "declaration_pairing": "shape-mismatch",
                    "declaration_index": declaration_index,
                    "left_parts": len(left_signature),
                    "right_parts": len(right_signature),
                    "alternatives": [
                        _coupling_evidence(
                            label=(
                                f"{left.name} declaration[{declaration_index}] "
                                "signature evidence"
                            ),
                            reason="conflicting-declaration-signature-shape",
                            symbols=(left.name,),
                            atoms=atoms,
                            left_spans=left_signature,
                            right_spans=right_signature,
                        )
                    ],
                },
            )
        for left_span, right_span in zip(left_signature, right_signature, strict=True):
            selected.extend(
                _atoms_for_span(
                    atoms,
                    left_span,
                    right_span,
                    reclassified,
                    "function_signature",
                )
            )
    selected.extend(_atoms_for_span(atoms, left.parameter_span, right.parameter_span, reclassified, "parameter_list"))
    if len(left.declaration_parameter_spans) != len(right.declaration_parameter_spans):
        raise DeltaMinimizeError(
            "ambiguous-delta-coupling",
            {
                "symbol": left.name,
                "declaration_pairing": "parameter-count-mismatch",
                "left_declarations": len(left.declaration_parameter_spans),
                "right_declarations": len(right.declaration_parameter_spans),
                "alternatives": [
                    _coupling_evidence(
                        label=f"{left.name} declaration parameter evidence",
                        reason="conflicting-declaration-parameter-count",
                        symbols=(left.name,),
                        atoms=atoms,
                        left_spans=(
                            left.parameter_span,
                            *left.declaration_parameter_spans,
                        ),
                        right_spans=(
                            right.parameter_span,
                            *right.declaration_parameter_spans,
                        ),
                    )
                ],
            },
        )
    for left_span, right_span in zip(
        left.declaration_parameter_spans,
        right.declaration_parameter_spans,
        strict=True,
    ):
        selected.extend(
            _atoms_for_span(
                atoms,
                left_span,
                right_span,
                reclassified,
                "parameter_list",
            )
        )
    for left_call, right_call in zip(left.direct_calls, right.direct_calls, strict=True):
        selected.extend(
            _atoms_for_span(
                atoms,
                left_call.argument_span,
                right_call.argument_span,
                reclassified,
                "argument_list",
            )
        )
    _union_ids(groups, selected)
    return tuple(dict.fromkeys(selected))


def _couple_rename(
    groups: UnionFind,
    atoms,
    left: FunctionBinding,
    right: FunctionBinding,
) -> tuple[str, ...]:
    if len(left.direct_calls) != len(right.direct_calls):
        raise DeltaMinimizeError(
            "ambiguous-delta-coupling",
            {
                "symbols": [left.name, right.name],
                "rename_pairing": "call-count-mismatch",
                "left_calls": len(left.direct_calls),
                "right_calls": len(right.direct_calls),
                "left_call_spans": [
                    list(call.call_span) for call in left.direct_calls
                ],
                "right_call_spans": [
                    list(call.call_span) for call in right.direct_calls
                ],
                "alternatives": _call_pairing_alternatives(
                    left,
                    right,
                    atoms,
                ),
            },
        )
    left_name_span = left.definition_name_span or (left.definition_span[0], left.parameter_span[0])
    right_name_span = right.definition_name_span or (right.definition_span[0], right.parameter_span[0])
    selected = list(_atoms_for_span(atoms, left_name_span, right_name_span))
    left_declaration_names = _declaration_name_spans(left)
    right_declaration_names = _declaration_name_spans(right)
    if len(left_declaration_names) != len(right_declaration_names):
        raise DeltaMinimizeError(
            "ambiguous-delta-coupling",
            {
                "symbols": [left.name, right.name],
                "declaration_pairing": "count-mismatch",
                "left_declarations": len(left_declaration_names),
                "right_declarations": len(right_declaration_names),
                "alternatives": [
                    _coupling_evidence(
                        label=(
                            f"{left.name} -> {right.name} declaration-name "
                            "evidence"
                        ),
                        reason="conflicting-rename-declaration-count",
                        symbols=(left.name, right.name),
                        atoms=atoms,
                        left_spans=(left_name_span, *left_declaration_names),
                        right_spans=(right_name_span, *right_declaration_names),
                    )
                ],
            },
        )
    for left_span, right_span in zip(
        left_declaration_names,
        right_declaration_names,
        strict=True,
    ):
        selected.extend(_atoms_for_span(atoms, left_span, right_span))
    for left_call, right_call in zip(left.direct_calls, right.direct_calls, strict=True):
        selected.extend(
            _atoms_for_span(
                atoms,
                left_call.callee_name_span or (left_call.call_span[0], left_call.argument_span[0]),
                right_call.callee_name_span or (right_call.call_span[0], right_call.argument_span[0]),
            )
        )
    _union_ids(groups, selected)
    return tuple(dict.fromkeys(selected))


def _declaration_name_spans(function: FunctionBinding) -> tuple[tuple[int, int], ...]:
    if function.declaration_name_spans:
        return function.declaration_name_spans
    return tuple(
        (declaration[0], parameters[0])
        for declaration, parameters in zip(
            function.declaration_spans,
            function.declaration_parameter_spans,
            strict=True,
        )
    )


def _atoms_for_span(
    atoms,
    left_span: tuple[int, int],
    right_span: tuple[int, int],
    reclassified: dict[tuple[str, int], str] | None = None,
    anchor_kind: str | None = None,
) -> tuple[str, ...]:
    selected: list[str] = []
    for atom in atoms:
        for index, patch in enumerate(atom.patches):
            if _patch_pair_intersects_owned_spans(
                (patch.left_start, patch.left_end),
                (patch.right_start, patch.right_end),
                left_span,
                right_span,
            ):
                selected.append(atom.atom_id)
                if reclassified is not None and anchor_kind is not None:
                    reclassified[(atom.atom_id, index)] = anchor_kind
    return tuple(dict.fromkeys(selected))


def _changed_spans(atoms, *, side: str) -> tuple[tuple[int, int], ...]:
    return tuple(
        ((patch.left_start, patch.left_end) if side == "left" else (patch.right_start, patch.right_end))
        for atom in atoms
        for patch in atom.patches
    )


def _one_sided_external_calls_by_atom(
    index: BindingIndex,
    atoms,
    *,
    side: str,
) -> dict[str, tuple[tuple[int, int], ...]]:
    calls_by_atom: dict[str, list[tuple[int, int]]] = defaultdict(list)
    external_calls = tuple(
        blocker.span
        for blocker in index.blockers
        if blocker.reason == "unresolved-external-call"
    )
    for atom in atoms:
        for patch in atom.patches:
            left_span = (patch.left_start, patch.left_end)
            right_span = (patch.right_start, patch.right_end)
            if side == "left":
                selected, opposite = left_span, right_span
            else:
                selected, opposite = right_span, left_span
            if selected[0] != selected[1] and opposite[0] == opposite[1]:
                calls_by_atom[atom.atom_id].extend(
                    call_span
                    for call_span in external_calls
                    if _span_contains(selected, call_span)
                )
    return {
        atom_id: tuple(dict.fromkeys(call_spans))
        for atom_id, call_spans in calls_by_atom.items()
        if call_spans
    }


def _safe_atomic_external_call_spans(
    selected: Mapping[str, Sequence[tuple[int, int]]],
    opposite: Mapping[str, Sequence[tuple[int, int]]],
) -> tuple[tuple[int, int], ...]:
    eligible_atoms = selected.keys() if not opposite else selected.keys() & opposite.keys()
    return tuple(
        span
        for atom_id in sorted(eligible_atoms)
        for span in selected[atom_id]
    )


def _changed_binding_names(index: BindingIndex, spans: Sequence[tuple[int, int]]) -> set[str]:
    nonempty_spans = tuple(span for span in spans if span[0] != span[1])
    names: set[str] = set()
    for name, function in index.functions.items():
        binding_spans = [
            *_signature_spans(function),
            *(call.call_span for call in function.direct_calls),
        ]
        if any(_spans_touch(change, binding) for change in nonempty_spans for binding in binding_spans):
            names.add(name)
    for blocker in index.blockers:
        if any(_spans_touch(change, blocker.owned_span or blocker.span) for change in nonempty_spans):
            names.add(blocker.symbol)
    return names


def _materialize_composite_atoms(groups, atoms, labels_by_root, reclassified):
    from .delta import DeltaAtom

    by_root: dict[str, list] = defaultdict(list)
    for atom in atoms:
        by_root[groups.find(atom.atom_id)].append(atom)
    for group in by_root.values():
        group.sort(key=lambda atom: atom.atom_id)
    ordered_groups = sorted(
        by_root.values(),
        key=lambda group: min(
            (patch.left_start, patch.right_start, atom.atom_id) for atom in group for patch in atom.patches
        )
        if any(atom.patches for atom in group)
        else (0, 0, min(atom.atom_id for atom in group)),
    )
    composite_ids = {
        groups.find(atom.atom_id): _stable_composite_id(group) for group in ordered_groups for atom in group
    }
    result = []
    for group in ordered_groups:
        root = groups.find(group[0].atom_id)
        member_ids = {atom.atom_id for atom in group}
        patches = []
        for atom in group:
            for index, patch in enumerate(atom.patches):
                kind = reclassified.get((atom.atom_id, index))
                patches.append(replace(patch, anchor_kind=kind) if kind else patch)
        requires = {
            composite_ids[groups.find(required)]
            for atom in group
            for required in atom.requires
            if required not in member_ids
        }
        labels = list(dict.fromkeys(labels_by_root.get(root, ())))
        summaries = labels + [atom.summary for atom in group if atom.summary]
        result.append(
            DeltaAtom(
                atom_id=composite_ids[root],
                kind="semantic-composite" if len(group) > 1 else group[0].kind,
                patches=tuple(sorted(patches, key=lambda patch: (patch.left_start, patch.right_start))),
                requires=tuple(sorted(requires)),
                affected_functions=tuple(sorted({name for atom in group for name in atom.affected_functions})),
                summary="; ".join(dict.fromkeys(summaries)),
            )
        )
    return tuple(result)


def _build_local_bindings(
    functions,
    source_bytes: bytes,
    to_char: list[int],
) -> tuple[LocalBinding, ...]:
    result: list[LocalBinding] = []
    for function, (definition, _name, _parameters, _declarator) in functions.items():
        body = definition.child_by_field_name("body")
        if body is None:
            continue
        declaration_names = {
            (identifier.start_byte, identifier.end_byte)
            for declaration in _walk_type(body, "declaration")
            for identifier, _scope_start in _local_declaration_entries(declaration)
        }
        for declaration in _walk_type(body, "declaration"):
            scope = _local_declaration_scope(declaration)
            if scope is None:
                continue
            for identifier, _scope_start in _local_declaration_entries(declaration):
                name = node_text(source_bytes, identifier)
                uses = tuple(
                    _span(candidate, to_char)
                    for candidate in _walk_type(scope, "identifier")
                    if node_text(source_bytes, candidate) == name
                    and (candidate.start_byte, candidate.end_byte) not in declaration_names
                    and candidate.start_byte >= identifier.end_byte
                )
                result.append(
                    LocalBinding(
                        function=function,
                        name=name,
                        declaration_span=_span(declaration, to_char),
                        use_spans=uses,
                        scope_span=_span(scope, to_char),
                        scope_is_compound=scope.type == "compound_statement",
                    )
                )
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.function,
                item.declaration_span,
                item.name,
            ),
        )
    )


def _couple_local_binding_changes(
    groups: UnionFind,
    atoms,
    left_index: BindingIndex,
    right_index: BindingIndex,
    semantic_labels: dict[str, list[str]],
    selected_functions: set[str] | frozenset[str] | None = None,
) -> None:
    left_groups = _group_local_bindings(left_index.locals)
    right_groups = _group_local_bindings(right_index.locals)
    ambiguous: list[dict[str, object]] = []
    for key in sorted(left_groups.keys() | right_groups.keys()):
        if selected_functions is not None and key[0] not in selected_functions:
            continue
        left_values = left_groups.get(key, ())
        right_values = right_groups.get(key, ())
        if max(len(left_values), len(right_values)) < 2:
            continue
        left_spans = [span for binding in left_values for span in (binding.declaration_span, *binding.use_spans)]
        right_spans = [span for binding in right_values for span in (binding.declaration_span, *binding.use_spans)]
        touched = bool(
            _atoms_for_directional_spans(atoms, left_spans, side="left")
            or _atoms_for_directional_spans(atoms, right_spans, side="right")
        )
        if len(left_values) != len(right_values) or touched:
            function, name = key
            spans = [binding.declaration_span for binding in (*left_values, *right_values)]
            ambiguous.append(
                {
                    "symbol": name,
                    "function": function,
                    "reason": "ambiguous-local-binding",
                    "span": min(spans) if spans else (0, 0),
                }
            )
    if ambiguous:
        raise DeltaMinimizeError("unsupported-semantic-binding", {"blockers": ambiguous})

    left = _unique_local_bindings(left_index.locals)
    right = _unique_local_bindings(right_index.locals)
    for side, bindings, other in (
        ("left", left, right),
        ("right", right, left),
    ):
        for key in sorted(bindings.keys() - other.keys()):
            if selected_functions is not None and key[0] not in selected_functions:
                continue
            binding = bindings[key]
            spans = [binding.declaration_span, *binding.use_spans]
            if binding.scope_is_compound:
                start, end = binding.scope_span
                if start < end:
                    spans.extend(((start, start + 1), (end - 1, end)))
            selected = _atoms_for_directional_spans(
                atoms,
                spans,
                side=side,
            )
            _union_ids(groups, selected)
            if selected:
                semantic_labels[selected[0]].append(
                    f"{binding.function} local {binding.name} {'removal' if side == 'left' else 'introduction'}"
                )


def _unique_local_bindings(
    bindings: Sequence[LocalBinding],
) -> dict[tuple[str, str], LocalBinding]:
    grouped = _group_local_bindings(bindings)
    return {key: values[0] for key, values in grouped.items() if len(values) == 1}


def _group_local_bindings(
    bindings: Sequence[LocalBinding],
) -> dict[tuple[str, str], tuple[LocalBinding, ...]]:
    grouped: dict[tuple[str, str], list[LocalBinding]] = defaultdict(list)
    for binding in bindings:
        grouped[(binding.function, binding.name)].append(binding)
    return {key: tuple(values) for key, values in grouped.items()}


def _atoms_for_directional_spans(
    atoms,
    spans: Sequence[tuple[int, int]],
    *,
    side: str,
) -> tuple[str, ...]:
    selected: list[str] = []
    for atom in atoms:
        if any(
            _spans_touch(
                ((patch.left_start, patch.left_end) if side == "left" else (patch.right_start, patch.right_end)),
                span,
            )
            for patch in atom.patches
            for span in spans
        ):
            selected.append(atom.atom_id)
    return tuple(dict.fromkeys(selected))


def _stable_composite_id(group) -> str:
    raw = "\0".join(sorted(atom.atom_id for atom in group)).encode()
    return "delta-" + hashlib.sha256(raw).hexdigest()[:16]


def _union_overlaps(groups: UnionFind, atoms) -> None:
    for index, left in enumerate(atoms):
        for right in atoms[index + 1 :]:
            if any(
                _spans_overlap((a.left_start, a.left_end), (b.left_start, b.left_end))
                or _spans_overlap((a.right_start, a.right_end), (b.right_start, b.right_end))
                for a in left.patches
                for b in right.patches
            ):
                groups.union(left.atom_id, right.atom_id)


def _union_dependency_cycles(groups: UnionFind, atoms) -> None:
    while True:
        graph: dict[str, set[str]] = defaultdict(set)
        for atom in atoms:
            source = groups.find(atom.atom_id)
            graph[source]
            for required in atom.requires:
                if required not in groups.parent:
                    continue
                target = groups.find(required)
                if source != target:
                    graph[source].add(target)

        reachable: dict[str, set[str]] = {}
        for start in graph:
            seen: set[str] = set()
            stack = list(graph[start])
            while stack:
                current = stack.pop()
                if current in seen or current not in graph:
                    continue
                seen.add(current)
                stack.extend(graph[current])
            reachable[start] = seen

        changed = False
        for left in sorted(graph):
            for right in sorted(reachable[left]):
                if left in reachable.get(right, set()) and groups.find(left) != groups.find(right):
                    groups.union(left, right)
                    changed = True
        if not changed:
            return


def _union_ids(groups: UnionFind, atom_ids: Sequence[str]) -> None:
    if atom_ids:
        first = atom_ids[0]
        for atom_id in atom_ids[1:]:
            groups.union(first, atom_id)


def _is_explicit_void_parameter_list(parameter_list, source_bytes: bytes) -> bool:
    parameters = tuple(parameter_list.named_children)
    if len(parameters) != 1:
        return False
    parameter = parameters[0]
    if parameter.type != "parameter_declaration":
        return False
    if parameter.child_by_field_name("declarator") is not None:
        return False
    type_node = parameter.child_by_field_name("type")
    return (
        type_node is not None
        and type_node.type == "primitive_type"
        and node_text(source_bytes, type_node).strip() == "void"
        and node_text(source_bytes, parameter).strip() == "void"
    )


def _parameter_names(parameter_list, source_bytes: bytes) -> tuple[str, ...] | None:
    if _is_explicit_void_parameter_list(parameter_list, source_bytes):
        return ()
    names: list[str] = []
    for parameter in parameter_list.named_children:
        if parameter.type != "parameter_declaration":
            return None
        identifier = _declarator_identifier(parameter.child_by_field_name("declarator"))
        if identifier is None:
            return None
        names.append(node_text(source_bytes, identifier))
    return tuple(names)


def _parameter_texts(parameter_list, source_bytes: bytes) -> tuple[str, ...]:
    if _is_explicit_void_parameter_list(parameter_list, source_bytes):
        return ()
    return tuple(
        node_text(source_bytes, parameter).strip()
        for parameter in parameter_list.named_children
    )


def _normalized_function_type_shape(
    container,
    declarator,
    name_node,
    parameters,
    source_bytes: bytes,
) -> str:
    first_declarator = next(_declaration_declarators(container))
    replaced_spans = [(name_node.start_byte, name_node.end_byte)]
    for parameter in parameters.named_children:
        identifier = _declarator_identifier(parameter.child_by_field_name("declarator"))
        if identifier is not None:
            replaced_spans.append((identifier.start_byte, identifier.end_byte))

    def normalized_part(start: int, end: int) -> bytes:
        chunks: list[bytes] = []
        cursor = start
        for replacement_start, replacement_end in sorted(replaced_spans):
            if replacement_start < start or replacement_end > end:
                continue
            chunks.append(source_bytes[cursor:replacement_start])
            chunks.append(b"$")
            cursor = replacement_end
        chunks.append(source_bytes[cursor:end])
        return b"".join(chunks)

    spelling = normalized_part(container.start_byte, first_declarator.start_byte) + normalized_part(
        declarator.start_byte,
        declarator.end_byte,
    )
    return b"".join(spelling.split()).decode("utf-8")


def _visible_local_declarations(
    reference,
    definition,
    source_bytes: bytes,
    to_char: list[int],
) -> dict[str, tuple[tuple[int, int], ...]]:
    """Return declarations whose lexical scope contains ``reference``."""

    spans_by_name: dict[str, list[tuple[int, int]]] = defaultdict(list)
    declarator = definition.child_by_field_name("declarator")
    parts = _function_declaration_parts(declarator)
    if parts is not None:
        _, parameters = parts
        for parameter in parameters.named_children:
            complete_declarator = parameter.child_by_field_name("declarator")
            identifier = _declarator_identifier(complete_declarator)
            if (
                identifier is not None
                and complete_declarator is not None
                and complete_declarator.end_byte <= reference.start_byte
            ):
                spans_by_name[node_text(source_bytes, identifier)].append(_span(parameter, to_char))
    body = definition.child_by_field_name("body")
    if body is not None:
        for declaration in _walk_type(body, "declaration"):
            scope = _local_declaration_scope(declaration)
            if scope is None or not _contains_node(scope, reference):
                continue
            for identifier, scope_start in _local_declaration_entries(declaration):
                if scope_start <= reference.start_byte:
                    spans_by_name[node_text(source_bytes, identifier)].append(_span(declaration, to_char))
    return {name: tuple(dict.fromkeys(spans)) for name, spans in spans_by_name.items()}


def _is_parenthesized_known_type_cast(
    call,
    callee,
    owner,
    type_identifier_nodes: Mapping[str, Sequence[object]],
    local_declarations: Mapping[str, Sequence[tuple[int, int]]],
    source_bytes: bytes,
) -> bool:
    """Recognize typedef casts that tree-sitter parses as call expressions."""

    current = callee
    saw_parentheses = False
    while current.type == "parenthesized_expression":
        children = tuple(current.named_children)
        if len(children) != 1:
            return False
        saw_parentheses = True
        current = children[0]
    if not saw_parentheses or current.type != "identifier":
        return False

    name = node_text(source_bytes, current)
    if name in local_declarations:
        return False
    for type_node in type_identifier_nodes.get(name, ()):
        if type_node.start_byte >= call.start_byte:
            continue
        type_owner = _ancestor(type_node, "function_definition")
        if type_owner is None:
            return True
        if (
            owner is not None
            and type_owner.start_byte == owner.start_byte
            and type_owner.end_byte == owner.end_byte
        ):
            type_scope = _ancestor(type_node, "compound_statement")
            if type_scope is None or _contains_node(type_scope, call):
                return True
    return False


def _local_declaration_entries(declaration):
    for child in _declaration_declarators(declaration):
        complete_declarator = child.child_by_field_name("declarator") if child.type == "init_declarator" else child
        identifier = _declarator_identifier(complete_declarator)
        if identifier is not None and complete_declarator is not None:
            yield identifier, complete_declarator.end_byte


def _declaration_declarators(declaration):
    for index, child in enumerate(declaration.children):
        if child.is_named and declaration.field_name_for_child(index) == "declarator":
            yield child


def _declaration_name_byte_spans(root) -> set[tuple[int, int]]:
    spans = {
        (identifier.start_byte, identifier.end_byte)
        for declaration in _walk_type(root, "declaration")
        for identifier, _ in _local_declaration_entries(declaration)
    }
    for parameter in _walk_type(root, "parameter_declaration"):
        identifier = _declarator_identifier(parameter.child_by_field_name("declarator"))
        if identifier is not None:
            spans.add((identifier.start_byte, identifier.end_byte))
    return spans


def _non_call_reference_node(identifier):
    parent = identifier.parent
    while parent is not None and parent.type == "parenthesized_expression":
        parent = parent.parent
    if parent is not None and parent.type in {
        "assignment_expression",
        "binary_expression",
        "cast_expression",
        "conditional_expression",
        "subscript_expression",
        "unary_expression",
    }:
        return parent
    return identifier


def _local_declaration_scope(declaration):
    parent = declaration.parent
    if parent is not None and parent.type == "for_statement":
        return parent
    return _ancestor(declaration, "compound_statement")


def _contains_node(container, node) -> bool:
    return container.start_byte <= node.start_byte and node.end_byte <= container.end_byte


def _declarator_identifier(node):
    current = node
    while current is not None and current.type != "identifier":
        inner = current.child_by_field_name("declarator")
        if inner is None and current.type == "parenthesized_declarator":
            inner = next((child for child in current.named_children), None)
        if inner is None:
            return None
        current = inner
    return current


def _function_declaration_parts(node):
    current = node
    while current is not None:
        if current.type == "function_declarator":
            parameters = current.child_by_field_name("parameters")
            name = _declared_function_identifier(current.child_by_field_name("declarator"))
            if name is not None and parameters is not None:
                return name, parameters
        inner = current.child_by_field_name("declarator")
        if inner is None and current.type == "parenthesized_declarator":
            inner = next(iter(current.named_children), None)
        current = inner
    return None


def _definition_signature_span(definition, to_char: list[int]) -> tuple[int, int]:
    body = definition.child_by_field_name("body")
    end_byte = body.start_byte if body is not None else definition.end_byte
    return to_char[definition.start_byte], to_char[end_byte]


def _declaration_signature(declaration, declarator, to_char: list[int]) -> DeclarationSignature:
    first_declarator = next(_declaration_declarators(declaration))
    return DeclarationSignature(
        shared_prefix_span=(
            to_char[declaration.start_byte],
            to_char[first_declarator.start_byte],
        ),
        declarator_span=_span(declarator, to_char),
        shared_prefix_owned_span=_declaration_shared_prefix_owned_span(
            declaration,
            first_declarator,
            to_char,
        ),
    )


def _declaration_shared_prefix_owned_span(
    declaration,
    first_declarator,
    to_char: list[int],
) -> tuple[int, int]:
    prefix_end_byte = max(
        (child.end_byte for child in declaration.named_children if child.end_byte <= first_declarator.start_byte),
        default=declaration.start_byte,
    )
    return (
        to_char[declaration.start_byte],
        to_char[prefix_end_byte],
    )


def _function_pointer_object_identifier(node):
    if _function_declaration_parts(node) is not None:
        return None
    current = node
    while current is not None:
        if current.type == "function_declarator":
            declarator = current.child_by_field_name("declarator")
            return _declarator_identifier(declarator)
        current = current.child_by_field_name("declarator")
    return None


def _declared_function_identifier(node):
    current = node
    while current is not None:
        if current.type == "identifier":
            return current
        if current.type == "pointer_declarator":
            return None
        if current.type == "parenthesized_declarator":
            current = next(iter(current.named_children), None)
        else:
            current = current.child_by_field_name("declarator")
    return None


def _walk_type(root, node_type: str):
    for node in _walk(root):
        if node.type == node_type:
            yield node


def _walk(root):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.named_children))


def _ancestor(node, node_type: str):
    current = node.parent
    while current is not None:
        if current.type == node_type:
            return current
        current = current.parent
    return None


def _has_preprocessor_ancestor(node) -> bool:
    current = node.parent
    while current is not None:
        if current.type.startswith("preproc_"):
            return True
        current = current.parent
    return False


def _byte_to_char_offsets(source: str) -> list[int]:
    offsets = [0]
    chars = 0
    for byte in source.encode("utf-8"):
        if byte & 0xC0 != 0x80:
            chars += 1
        offsets.append(chars)
    return offsets


def _span(node, to_char: list[int]) -> tuple[int, int]:
    return to_char[node.start_byte], to_char[node.end_byte]


def _spans_touch(first: tuple[int, int], second: tuple[int, int]) -> bool:
    if first[0] == first[1]:
        return second[0] <= first[0] < second[1]
    if second[0] == second[1]:
        return first[0] <= second[0] < first[1]
    return first[0] < second[1] and second[0] < first[1]


def _span_contains(
    container: tuple[int, int],
    contained: tuple[int, int],
) -> bool:
    return (
        container[0] != container[1]
        and container[0] <= contained[0]
        and contained[1] <= container[1]
    )


def _patch_pair_intersects_owned_spans(
    left_change: tuple[int, int],
    right_change: tuple[int, int],
    left_owned_span: tuple[int, int] | None,
    right_owned_span: tuple[int, int] | None,
) -> bool:
    """Test a paired directional delta against paired semantic ownership spans."""

    left_empty = left_change[0] == left_change[1]
    right_empty = right_change[0] == right_change[1]
    if left_empty and right_empty:
        return False
    if left_empty:
        return right_owned_span is not None and _spans_touch(right_change, right_owned_span)
    if right_empty:
        return left_owned_span is not None and _spans_touch(left_change, left_owned_span)
    return (
        left_owned_span is not None
        and _spans_touch(left_change, left_owned_span)
        or right_owned_span is not None
        and _spans_touch(right_change, right_owned_span)
    )


def _spans_overlap(first: tuple[int, int], second: tuple[int, int]) -> bool:
    if first[0] == first[1] or second[0] == second[1]:
        return first == second
    return first[0] < second[1] and second[0] < first[1]
