"""AST-anchored primitive source deltas and exact binary-mask enumeration."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path

from src.common.tree_sitter_c import get_parser

from .contracts import DeltaMinimizeError


@dataclass(frozen=True)
class DeltaPatch:
    left_start: int
    left_end: int
    left_text: str
    right_start: int
    right_end: int
    right_text: str
    anchor_kind: str
    anchor_symbol: str


@dataclass(frozen=True)
class DeltaAtom:
    atom_id: str
    kind: str
    patches: tuple[DeltaPatch, ...]
    requires: tuple[str, ...] = ()
    affected_functions: tuple[str, ...] = ()
    summary: str = ""


@dataclass(frozen=True)
class DeltaManifest:
    schema_version: str
    function: str
    left_hash: str
    right_hash: str
    atoms: tuple[DeltaAtom, ...]


@dataclass(frozen=True)
class MaterializedCandidate:
    candidate_id: str
    mask: int
    source_hash: str
    source_path: Path
    applied_atom_ids: tuple[str, ...]


@dataclass(frozen=True)
class _Change:
    left_start: int
    left_end: int
    right_start: int
    right_end: int


@dataclass(frozen=True)
class _Anchor:
    kind: str
    path: str


def extract_primitive_manifest(
    left: str,
    right: str,
    *,
    function: str,
) -> DeltaManifest:
    """Extract only textual replacements observed between two source parents."""

    left_bytes = left.encode("utf-8")
    right_bytes = right.encode("utf-8")
    parser = get_parser()
    left_root = parser.parse(left_bytes).root_node
    right_root = parser.parse(right_bytes).root_node

    opcodes = SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
    changes, merged_overlap = _normalize_changes(opcodes, left, right)
    if _apply_changes(left, right, changes) != right:
        reason = "unmergeable-overlapping-delta" if merged_overlap else "endpoint-reproduction-failed"
        raise DeltaMinimizeError(reason)

    grouped: dict[tuple[str, str], list[DeltaPatch]] = {}
    for change in changes:
        left_text = left[change.left_start : change.left_end]
        right_text = right[change.right_start : change.right_end]
        if _is_presentation_only(left_text, right_text):
            kind = "presentation-only"
            symbol = f"{function}:presentation"
        else:
            left_anchor = _anchor_for_span(
                left_root,
                left,
                change.left_start,
                change.left_end,
            )
            right_anchor = _anchor_for_span(
                right_root,
                right,
                change.right_start,
                change.right_end,
            )
            if left_anchor is None and right_anchor is None:
                raise DeltaMinimizeError(
                    "unsupported-delta-anchor",
                    {
                        "left_span": [change.left_start, change.left_end],
                        "right_span": [change.right_start, change.right_end],
                    },
                )
            kind = left_anchor.kind if left_anchor is not None else right_anchor.kind
            left_path = "none" if left_anchor is None else left_anchor.path
            right_path = "none" if right_anchor is None else right_anchor.path
            symbol = f"{function}:{kind}:{left_path}|{right_path}"

        patch = DeltaPatch(
            left_start=change.left_start,
            left_end=change.left_end,
            left_text=left_text,
            right_start=change.right_start,
            right_end=change.right_end,
            right_text=right_text,
            anchor_kind=kind,
            anchor_symbol=symbol,
        )
        grouped.setdefault((kind, symbol), []).append(patch)

    atoms = tuple(
        _make_atom(kind, patches, function=function)
        for (kind, _), patches in sorted(
            grouped.items(),
            key=lambda item: _patch_order_key(item[1]),
        )
    )
    manifest = DeltaManifest(
        schema_version="delta-manifest.v1",
        function=function,
        left_hash=_source_hash(left),
        right_hash=_source_hash(right),
        atoms=atoms,
    )
    _validate_manifest(manifest)

    full_mask = (1 << len(atoms)) - 1
    if not _mask_is_legal(manifest, 0) or not _mask_is_legal(manifest, full_mask):
        raise DeltaMinimizeError("endpoint-reproduction-failed")
    if materialize_mask(left, manifest, 0) != left:
        raise DeltaMinimizeError("endpoint-reproduction-failed", {"endpoint": "left"})
    if materialize_mask(left, manifest, full_mask) != right:
        raise DeltaMinimizeError("endpoint-reproduction-failed", {"endpoint": "right"})
    return manifest


def extract_delta_manifest(
    left: str,
    right: str,
    *,
    function: str,
) -> DeltaManifest:
    """Extract primitive deltas, then couple semantically linked bindings."""

    from .bindings import build_binding_index, couple_semantic_atoms

    primitive = extract_primitive_manifest(left, right, function=function)
    atoms = couple_semantic_atoms(
        build_binding_index(left),
        build_binding_index(right),
        primitive.atoms,
    )
    manifest = DeltaManifest(
        schema_version=primitive.schema_version,
        function=primitive.function,
        left_hash=primitive.left_hash,
        right_hash=primitive.right_hash,
        atoms=atoms,
    )
    _validate_manifest(manifest)
    full_mask = (1 << len(atoms)) - 1
    if not _mask_is_legal(manifest, 0) or not _mask_is_legal(manifest, full_mask):
        raise DeltaMinimizeError("endpoint-reproduction-failed")
    if materialize_mask(left, manifest, 0) != left:
        raise DeltaMinimizeError("endpoint-reproduction-failed", {"endpoint": "left"})
    if materialize_mask(left, manifest, full_mask) != right:
        raise DeltaMinimizeError("endpoint-reproduction-failed", {"endpoint": "right"})
    return manifest


def enumerate_legal_masks(
    manifest: DeltaManifest,
    *,
    max_candidates: int,
) -> tuple[int, ...]:
    """Count and return every dependency-closed mask in stable numeric order."""

    atom_count = len(manifest.atoms)
    if atom_count > 20:
        raise DeltaMinimizeError("atom-space-too-large", {"atom_count": atom_count})
    ids = _validate_manifest(manifest)

    legal: list[int] = []
    for mask in range(1 << atom_count):
        if _mask_is_legal(manifest, mask, ids=ids):
            legal.append(mask)

    required = len(legal)
    if required > max_candidates:
        raise DeltaMinimizeError(
            "candidate-budget-exceeded",
            {"required": required, "limit": max_candidates},
        )
    return tuple(legal)


def materialize_mask(left: str, manifest: DeltaManifest, mask: int) -> str:
    """Apply one legal atom mask to the canonical left source."""

    full_mask = (1 << len(manifest.atoms)) - 1
    if type(mask) is not int or mask < 0 or mask > full_mask:
        raise DeltaMinimizeError(
            "invalid-delta-mask",
            {"mask": mask, "atom_count": len(manifest.atoms)},
        )
    ids = _validate_manifest(manifest)
    if not _mask_is_legal(manifest, mask, ids=ids):
        raise DeltaMinimizeError("invalid-delta-mask", {"mask": mask})

    selected = [patch for index, atom in enumerate(manifest.atoms) if mask & (1 << index) for patch in atom.patches]
    _validate_nonoverlapping_patches(selected)

    out = left
    for patch in sorted(
        selected,
        key=lambda item: (item.left_start, item.left_end),
        reverse=True,
    ):
        if (
            patch.left_start < 0
            or patch.left_end < patch.left_start
            or patch.left_end > len(out)
            or out[patch.left_start : patch.left_end] != patch.left_text
        ):
            raise DeltaMinimizeError(
                "invalid-materialized-anchor",
                {"atom": patch.anchor_symbol},
            )
        out = out[: patch.left_start] + patch.right_text + out[patch.left_end :]
    return out


def _normalize_changes(opcodes, left: str, right: str) -> tuple[tuple[_Change, ...], bool]:
    changes: list[_Change] = []
    for tag, left_start, left_end, right_start, right_end in opcodes:
        if tag == "equal":
            continue
        if (
            tag not in {"replace", "delete", "insert"}
            or not _valid_span(
                left_start,
                left_end,
                len(left),
            )
            or not _valid_span(right_start, right_end, len(right))
        ):
            raise DeltaMinimizeError("invalid-delta-opcode")
        changes.append(_Change(left_start, left_end, right_start, right_end))

    if not changes:
        return (), False

    components: list[list[_Change]] = []
    for change in changes:
        hits = [
            index
            for index, component in enumerate(components)
            if any(_changes_overlap(change, other) for other in component)
        ]
        if not hits:
            components.append([change])
            continue
        merged = [change]
        for index in reversed(hits):
            merged.extend(components.pop(index))
        components.append(merged)

    had_overlap = any(len(component) > 1 for component in components)
    normalized = tuple(
        sorted(
            (_merge_change_component(component) for component in components),
            key=lambda item: (item.left_start, item.right_start),
        )
    )
    if _has_overlapping_changes(normalized):
        raise DeltaMinimizeError("unmergeable-overlapping-delta")
    if had_overlap and _apply_changes(left, right, normalized) != right:
        raise DeltaMinimizeError("unmergeable-overlapping-delta")
    return normalized, had_overlap


def _merge_change_component(component: list[_Change]) -> _Change:
    return _Change(
        min(change.left_start for change in component),
        max(change.left_end for change in component),
        min(change.right_start for change in component),
        max(change.right_end for change in component),
    )


def _changes_overlap(first: _Change, second: _Change) -> bool:
    return _spans_overlap(
        first.left_start,
        first.left_end,
        second.left_start,
        second.left_end,
    ) or _spans_overlap(
        first.right_start,
        first.right_end,
        second.right_start,
        second.right_end,
    )


def _spans_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    if start_a == end_a and start_b == end_b:
        return start_a == start_b
    if start_a == end_a:
        return start_b < start_a < end_b
    if start_b == end_b:
        return start_a < start_b < end_a
    return start_a < end_b and start_b < end_a


def _has_overlapping_changes(changes: tuple[_Change, ...]) -> bool:
    return any(
        _changes_overlap(first, second) for index, first in enumerate(changes) for second in changes[index + 1 :]
    )


def _apply_changes(left: str, right: str, changes: tuple[_Change, ...]) -> str:
    out = left
    for change in sorted(changes, key=lambda item: item.left_start, reverse=True):
        out = out[: change.left_start] + right[change.right_start : change.right_end] + out[change.left_end :]
    return out


def _anchor_for_span(root, source: str, start: int, end: int) -> _Anchor | None:
    byte_start = len(source[:start].encode("utf-8"))
    byte_end = len(source[:end].encode("utf-8"))
    candidates = []
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if not _node_contains(node, byte_start, byte_end):
            continue
        candidates.append((node.end_byte - node.start_byte, -depth, node))
        stack.extend((child, depth + 1) for child in node.children)

    for _, _, node in sorted(candidates, key=lambda item: (item[0], item[1])):
        current = node
        while current is not None:
            kind = _supported_kind(current.type)
            if kind is not None:
                return _Anchor(kind, _node_path(current))
            current = current.parent
    return None


def _node_contains(node, start: int, end: int) -> bool:
    if start == end:
        return node.start_byte <= start <= node.end_byte
    return node.start_byte <= start and end <= node.end_byte


def _supported_kind(node_type: str) -> str | None:
    if node_type == "parameter_list":
        return "parameter-list"
    if node_type == "call_expression":
        return "call-expression"
    if node_type in {"function_declarator", "function_definition"}:
        return "function-signature"
    if node_type in {
        "declaration",
        "field_declaration",
        "parameter_declaration",
        "type_definition",
    } or node_type.startswith("preproc_"):
        return "declaration"
    if node_type.endswith("_statement"):
        return "statement"
    if node_type.endswith("_expression") or node_type in {
        "identifier",
        "field_identifier",
        "number_literal",
        "char_literal",
        "string_literal",
        "true",
        "false",
        "null",
    }:
        return "expression"
    return None


def _node_path(node) -> str:
    parts = [node.type]
    current = node
    while current.parent is not None:
        parent = current.parent
        siblings = parent.named_children
        try:
            index = next(i for i, sibling in enumerate(siblings) if sibling == current)
        except StopIteration:
            index = next(i for i, sibling in enumerate(parent.children) if sibling == current)
        parts.append(f"{parent.type}[{index}]")
        current = parent
    return "/".join(reversed(parts))


def _is_presentation_only(left_text: str, right_text: str) -> bool:
    return not left_text.strip() and not right_text.strip()


def _make_atom(kind: str, patches: list[DeltaPatch], *, function: str) -> DeltaAtom:
    ordered = tuple(sorted(patches, key=lambda patch: (patch.left_start, patch.right_start)))
    identity = "\0".join(
        [
            kind,
            *(f"{patch.anchor_symbol}\0{patch.left_text}\0{patch.right_text}" for patch in ordered),
        ]
    )
    atom_id = f"atom-{sha256(identity.encode('utf-8')).hexdigest()}"
    return DeltaAtom(
        atom_id=atom_id,
        kind=kind,
        patches=ordered,
        affected_functions=(function,),
        summary=f"{kind} delta ({len(ordered)} patch{'es' if len(ordered) != 1 else ''})",
    )


def _patch_order_key(patches: list[DeltaPatch]) -> tuple[int, int, str]:
    first = min(patches, key=lambda patch: (patch.left_start, patch.right_start))
    return first.left_start, first.right_start, first.anchor_symbol


def _validate_manifest(manifest: DeltaManifest) -> dict[str, int]:
    ids: dict[str, int] = {}
    for index, atom in enumerate(manifest.atoms):
        if not atom.atom_id or atom.atom_id in ids:
            raise DeltaMinimizeError("invalid-delta-atom-id", {"atom_id": atom.atom_id})
        ids[atom.atom_id] = index
    for atom in manifest.atoms:
        missing = [required for required in atom.requires if required not in ids]
        if missing:
            raise DeltaMinimizeError(
                "invalid-delta-dependency",
                {"atom_id": atom.atom_id, "missing": missing},
            )
    return ids


def _mask_is_legal(
    manifest: DeltaManifest,
    mask: int,
    *,
    ids: dict[str, int] | None = None,
) -> bool:
    ids = _validate_manifest(manifest) if ids is None else ids
    return all(
        not (mask & (1 << index)) or all(mask & (1 << ids[required]) for required in atom.requires)
        for index, atom in enumerate(manifest.atoms)
    )


def _validate_nonoverlapping_patches(patches: list[DeltaPatch]) -> None:
    ordered = sorted(patches, key=lambda patch: (patch.left_start, patch.left_end))
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if second.left_start > first.left_end:
                break
            if _spans_overlap(
                first.left_start,
                first.left_end,
                second.left_start,
                second.left_end,
            ):
                raise DeltaMinimizeError(
                    "unmergeable-overlapping-delta",
                    {"atoms": [first.anchor_symbol, second.anchor_symbol]},
                )


def _valid_span(start: int, end: int, length: int) -> bool:
    return 0 <= start <= end <= length


def _source_hash(source: str) -> str:
    return sha256(source.encode("utf-8")).hexdigest()
