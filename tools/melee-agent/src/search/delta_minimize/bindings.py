"""Conservative TU-local semantic bindings for source delta coupling."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Mapping, Sequence

from src.common.tree_sitter_c import get_parser, node_text

from .contracts import DeltaMinimizeError


@dataclass(frozen=True)
class CallBinding:
    callee: str
    call_span: tuple[int, int]
    argument_span: tuple[int, int]
    argument_texts: tuple[str, ...]
    callee_name_span: tuple[int, int] | None = None


@dataclass(frozen=True)
class DeclarationSignature:
    shared_prefix_span: tuple[int, int]
    declarator_span: tuple[int, int]


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


@dataclass(frozen=True)
class BindingBlocker:
    symbol: str
    reason: str
    span: tuple[int, int]


@dataclass(frozen=True)
class BindingIndex:
    functions: Mapping[str, FunctionBinding]
    blockers: tuple[BindingBlocker, ...]


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
    supported_callee_spans: set[tuple[int, int]] = set()
    for call in _walk_type(root, "call_expression"):
        callee_node = call.child_by_field_name("function")
        arguments = call.child_by_field_name("arguments")
        callee = node_text(source_bytes, callee_node).strip() if callee_node is not None else "*"
        call_span = _span(call, to_char)
        if arguments is None or callee_node is None or callee_node.type != "identifier":
            blockers.append(BindingBlocker(callee or "*", "indirect-call", call_span))
            continue
        if _has_preprocessor_ancestor(call):
            blockers.append(BindingBlocker(callee, "conditional-call", call_span))
            continue
        if callee in macro_names or (callee.isupper() and callee not in unique_nodes):
            blockers.append(BindingBlocker(callee, "macro-like-call", call_span))
            continue

        owner = _ancestor(call, "function_definition")
        local_declarations = (
            _visible_local_declarations(call, owner, source_bytes, to_char) if owner is not None else {}
        )
        if callee in local_declarations:
            blockers.append(BindingBlocker(callee, "shadowed-call", call_span))
            if callee in unique_nodes:
                blockers.extend(
                    BindingBlocker(callee, "shadowing-declaration", span) for span in local_declarations[callee]
                )
            continue
        if callee not in unique_nodes:
            blockers.append(BindingBlocker(callee, "unresolved-external-call", call_span))
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
    for name, (definition, definition_name, parameters, _) in sorted(
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
        )

    for name in declaration_nodes.keys() - functions.keys():
        blockers.extend(
            BindingBlocker(name, "unresolved-external-declaration", _span(node, to_char))
            for node, _, _, _ in declaration_nodes[name]
        )

    blockers = sorted(set(blockers), key=lambda item: (item.span, item.symbol, item.reason))
    return BindingIndex(functions=functions, blockers=tuple(blockers))


def validate_supported_bindings(
    index: BindingIndex,
    changed_names: set[str],
    changed_spans: Sequence[tuple[int, int]] | None = None,
    renamed_names: set[str] | None = None,
) -> None:
    renamed_names = renamed_names or set()
    blockers = [
        blocker
        for blocker in index.blockers
        if blocker.symbol in changed_names
        and (
            blocker.reason != "non-call-function-reference"
            or blocker.symbol in renamed_names
            or changed_spans is None
            or any(_spans_touch(change, blocker.span) for change in changed_spans)
        )
    ]
    if blockers:
        raise DeltaMinimizeError(
            "unsupported-semantic-binding",
            {"blockers": [asdict(blocker) for blocker in blockers]},
        )


def couple_semantic_atoms(left_index: BindingIndex, right_index: BindingIndex, atoms):
    """Collapse atoms that must move together to preserve known bindings."""

    groups = UnionFind(tuple(atom.atom_id for atom in atoms))
    _union_overlaps(groups, atoms)

    left_changed_spans = _changed_spans(atoms, side="left")
    right_changed_spans = _changed_spans(atoms, side="right")
    left_changed = _changed_binding_names(left_index, left_changed_spans)
    right_changed = _changed_binding_names(right_index, right_changed_spans)
    pairs = _pair_functions(left_index, right_index)
    left_renamed = {left.name for left, _, renamed in pairs if renamed}
    right_renamed = {right.name for _, right, renamed in pairs if renamed}
    validate_supported_bindings(
        left_index,
        left_changed,
        left_changed_spans,
        left_renamed,
    )
    validate_supported_bindings(
        right_index,
        right_changed,
        right_changed_spans,
        right_renamed,
    )

    semantic_labels: dict[str, list[str]] = defaultdict(list)
    reclassified: dict[tuple[str, int], str] = {}
    for left_function, right_function, renamed in pairs:
        if _has_signature_patch(atoms, left_function, right_function):
            permutation = _parameter_permutation(left_function, right_function)
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


def _pair_functions(left_index: BindingIndex, right_index: BindingIndex):
    pairs = [
        (left_index.functions[name], right_index.functions[name], False)
        for name in left_index.functions.keys() & right_index.functions.keys()
    ]
    left_only = [binding for name, binding in left_index.functions.items() if name not in right_index.functions]
    right_only = [binding for name, binding in right_index.functions.items() if name not in left_index.functions]
    if not left_only and not right_only:
        return sorted(pairs, key=lambda item: item[0].definition_span)
    if len(left_only) != len(right_only):
        raise DeltaMinimizeError("ambiguous-delta-coupling")

    candidates = {
        left.name: [right for right in right_only if sorted(left.parameter_names) == sorted(right.parameter_names)]
        for left in left_only
    }
    if any(len(options) != 1 for options in candidates.values()):
        raise DeltaMinimizeError(
            "ambiguous-delta-coupling",
            {"candidate_symbols": {name: [item.name for item in options] for name, options in candidates.items()}},
        )
    selected = [options[0] for options in candidates.values()]
    if len({item.name for item in selected}) != len(selected):
        raise DeltaMinimizeError("ambiguous-delta-coupling")
    pairs.extend((left, candidates[left.name][0], True) for left in left_only)
    return sorted(pairs, key=lambda item: item[0].definition_span)


def _parameter_permutation(left: FunctionBinding, right: FunctionBinding) -> tuple[int, ...] | None:
    if len(set(left.parameter_names)) != len(left.parameter_names):
        if left.parameter_names != right.parameter_names:
            raise DeltaMinimizeError("ambiguous-delta-coupling", {"symbol": left.name})
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


def _has_signature_patch(atoms, left: FunctionBinding, right: FunctionBinding) -> bool:
    left_spans = _signature_spans(left)
    right_spans = _signature_spans(right)
    return any(
        any(_spans_touch((patch.left_start, patch.left_end), span) for span in left_spans)
        or any(_spans_touch((patch.right_start, patch.right_end), span) for span in right_spans)
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
            touches_signature = any(_spans_touch(left_change, span) for span in left_signatures) or any(
                _spans_touch(right_change, span) for span in right_signatures
            )
            touches_parameters = any(_spans_touch(left_change, span) for span in left_parameters) or any(
                _spans_touch(right_change, span) for span in right_parameters
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
            (signature.shared_prefix_span, signature.declarator_span) for signature in function.declaration_signatures
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
            {"symbol": left.name, "left_calls": len(left.direct_calls), "right_calls": len(right.direct_calls)},
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
            {"symbol": left.name, "declaration_pairing": "count-mismatch"},
        )
    for left_signature, right_signature in zip(
        left_declaration_signatures,
        right_declaration_signatures,
        strict=True,
    ):
        if len(left_signature) != len(right_signature):
            raise DeltaMinimizeError(
                "ambiguous-delta-coupling",
                {"symbol": left.name, "declaration_pairing": "shape-mismatch"},
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
            {"symbol": left.name, "declaration_pairing": "count-mismatch"},
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
            {"symbols": [left.name, right.name]},
        )
    left_name_span = left.definition_name_span or (left.definition_span[0], left.parameter_span[0])
    right_name_span = right.definition_name_span or (right.definition_span[0], right.parameter_span[0])
    selected = list(_atoms_for_span(atoms, left_name_span, right_name_span))
    left_declaration_names = _declaration_name_spans(left)
    right_declaration_names = _declaration_name_spans(right)
    if len(left_declaration_names) != len(right_declaration_names):
        raise DeltaMinimizeError(
            "ambiguous-delta-coupling",
            {"symbols": [left.name, right.name], "declaration_pairing": "count-mismatch"},
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
            if _spans_touch((patch.left_start, patch.left_end), left_span) or _spans_touch(
                (patch.right_start, patch.right_end), right_span
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


def _changed_binding_names(index: BindingIndex, spans: Sequence[tuple[int, int]]) -> set[str]:
    names: set[str] = set()
    for name, function in index.functions.items():
        binding_spans = [
            *_signature_spans(function),
            *(call.call_span for call in function.direct_calls),
        ]
        if any(_spans_touch(change, binding) for change in spans for binding in binding_spans):
            names.add(name)
    for blocker in index.blockers:
        if any(_spans_touch(change, blocker.span) for change in spans):
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


def _parameter_names(parameter_list, source_bytes: bytes) -> tuple[str, ...] | None:
    names: list[str] = []
    for parameter in parameter_list.named_children:
        if parameter.type == "primitive_type" and node_text(source_bytes, parameter) == "void":
            continue
        if parameter.type != "parameter_declaration":
            return None
        identifier = _declarator_identifier(parameter.child_by_field_name("declarator"))
        if identifier is None:
            return None
        names.append(node_text(source_bytes, identifier))
    return tuple(names)


def _parameter_texts(parameter_list, source_bytes: bytes) -> tuple[str, ...]:
    return tuple(
        node_text(source_bytes, parameter).strip()
        for parameter in parameter_list.named_children
        if not (parameter.type == "primitive_type" and node_text(source_bytes, parameter) == "void")
    )


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
        return second[0] <= first[0] <= second[1]
    if second[0] == second[1]:
        return first[0] <= second[0] <= first[1]
    return first[0] < second[1] and second[0] < first[1]


def _spans_overlap(first: tuple[int, int], second: tuple[int, int]) -> bool:
    if first[0] == first[1] or second[0] == second[1]:
        return first == second
    return first[0] < second[1] and second[0] < first[1]
