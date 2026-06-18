"""Helpers for realizing solve-coloring node-set split requests."""
from __future__ import annotations

import difflib
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from hashlib import sha1
from typing import Any, Mapping

from .mutators import (
    MutationUnsupported,
    mutate_insert_alias_before_use,
    mutate_preserve_lifetime_after_use,
)
from .simplify_search import BaselineSignature
from .source_patch import (
    _strip_c_comments,
    build_decl_order_candidates_for_scope,
    explain_decl_reorder_skip,
    find_function,
    get_decl_names_by_scope,
    reorder_decls_in_function_scope,
)
from .source_spans import StatementSpan, list_statement_spans
from .source_shape import CandidatePatch, CandidateScore
from .symbol_bridge import _extract_function_text, _parse_params, walk_local_decls

_SIMPLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
_INTEGER_LITERAL_RE = re.compile(r"^(?:0[xX][0-9A-Fa-f]+|[0-9]+)[uUlL]*$")
_REGISTER_RE = re.compile(r"^[rf](?P<num>\d+)$", re.IGNORECASE)
_IDENT_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
_FLOATING_SCALAR_TYPES = {"float", "f32", "double", "f64"}
_SAFE_BINDING_TYPE_RE = re.compile(
    r"^(?:(?:const|volatile|register|static)\s+)*"
    r"(?:struct\s+)?[A-Za-z_][A-Za-z_0-9]*"
    r"(?:\s+[A-Za-z_][A-Za-z_0-9]*)*"
    r"(?:\s*\*+\s*)?$"
)
_INTRO_ASSIGNMENT_RE = re.compile(
    r"^\s*(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)\s*=\s*(?P<rhs>.+);\s*$",
    re.DOTALL,
)
_SIMPLE_DECL_LINE_RE = re.compile(
    r"^\s*"
    r"(?P<type>"
    r"(?:(?:const|volatile|register|static)\s+)*"
    r"[A-Za-z_][A-Za-z_0-9]*"
    r"(?:\s+[A-Za-z_][A-Za-z_0-9]*)*"
    r")"
    r"\s+"
    r"(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"\s*(?:=[^;]*)?;\s*$"
)
_NODE_SET_PRIORITY_FAMILIES = (
    "combo",
    "prologue-reorder",
    "assignment-chain",
    "operand-alias",
    "block-scope",
)
_NODE_SET_COMBO_FAMILIES = (
    "prologue-reorder",
    "assignment-chain",
    "operand-alias",
    "block-scope",
)
_NODE_SET_SCALAR_DECL_RE = re.compile(
    r"^\s*(?P<type>.+?)(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"\s*(?:=[^;]*)?;\s*$",
    re.DOTALL,
)
_NODE_SET_SIMPLE_ASSIGNMENT_RE = re.compile(
    r"^\s*(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)\s*=\s*(?P<rhs>.+);\s*$",
)
_NODE_SET_SCALAR_CAST_RE = re.compile(
    r"\(\s*"
    r"(?P<type>[A-Za-z_][A-Za-z_0-9]*(?:\s+[A-Za-z_][A-Za-z_0-9]*)*)"
    r"\s*\)"
)
_NODE_SET_NUMERIC_LITERAL_RE = re.compile(
    r"\b(?:"
    r"0[xX][0-9A-Fa-f]+"
    r"|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?"
    r")[fFlLuU]*\b"
)
_NODE_SET_CONTROL_WORDS = (
    "if",
    "for",
    "while",
    "switch",
    "else",
    "do",
    "return",
    "goto",
    "break",
    "continue",
)
_NODE_SET_ALLOWED_GPR_TYPES = {
    "s8",
    "s16",
    "s32",
    "s64",
    "u8",
    "u16",
    "u32",
    "u64",
    "ptr",
}
_NODE_SET_ALLOWED_FPR_TYPES = {"f32", "f64"}
_NODE_SET_KNOWN_SCALAR_CALLS = {
    "HSD_JObjGetTranslationX",
    "HSD_JObjGetTranslationY",
    "HSD_JObjGetTranslationZ",
}


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


@dataclass(frozen=True)
class NodeSetSplitRequest:
    function: str
    class_id: int
    target_ig: int
    current_reg: str | None = None
    target_reg: str | None = None
    var_name: str | None = None
    blocked_reason: str | None = None
    source_expression: str | None = None
    source_type: str | None = None
    source_kind: str | None = None
    target_regs: tuple[str, ...] = ()
    source_scope_path: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        regs = tuple(
            reg for reg in (self.target_regs or ()) if isinstance(reg, str) and reg
        )
        if regs != self.target_regs:
            object.__setattr__(self, "target_regs", regs)
        if not regs and self.target_reg:
            object.__setattr__(self, "target_regs", (self.target_reg,))
        elif regs and self.target_reg is None:
            object.__setattr__(self, "target_reg", regs[0])


@dataclass(frozen=True)
class TargetColorSelectOrderLead:
    target_ig: int
    assigned_reg: int | None
    target_regs: tuple[int, ...]
    target_reg: int
    anchor_ig: int
    direction: str
    target_order: tuple[int, int]
    distance: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_ig": self.target_ig,
            "assigned_reg": self.assigned_reg,
            "target_regs": list(self.target_regs),
            "target_reg": self.target_reg,
            "anchor_ig": self.anchor_ig,
            "direction": self.direction,
            "target_order": list(self.target_order),
            "distance": self.distance,
            "description": self.description,
        }


@dataclass(frozen=True)
class _LoopSpan:
    loop_start: int
    header_start: int
    header_end: int
    body_open: int
    body_close: int
    body_inner_start: int
    body_inner_end: int


@dataclass(frozen=True)
class _IntroduceBindingSite:
    statement: StatementSpan
    occurrence_start: int
    occurrence_end: int
    binding_type: str
    mode: str


@dataclass(frozen=True)
class _SimpleAssignmentRecord:
    lhs: str
    rhs: str
    start: int
    end: int
    line_end: int
    line: str
    block_id: int
    reads: tuple[str, ...]
    lhs_type: str


@dataclass(frozen=True)
class _NodeSetScalarBinding:
    source_type: str
    normalized_type: str


def request_from_node_set_delta(
    delta: dict[str, Any],
    target_ig: int | None = None,
    source_text: str | None = None,
) -> NodeSetSplitRequest | None:
    """Build a split request from a solve-coloring node_set_delta payload.

    When no `target_ig` is supplied, the first bindable missing virtual wins.
    If every matching entry is unbindable, return the first blocked request so
    callers can surface the reason instead of silently doing nothing.
    """
    delta = _normalize_node_set_delta_payload(delta)
    missing_virtuals = delta.get("missing_virtuals")
    if not isinstance(missing_virtuals, list):
        return None

    requests: list[NodeSetSplitRequest] = []
    for entry in missing_virtuals:
        if not isinstance(entry, Mapping):
            continue
        parsed_target_ig = _as_int(entry.get("target_ig"))
        if parsed_target_ig is None:
            continue
        if target_ig is not None and parsed_target_ig != target_ig:
            continue
        request = _request_from_missing_virtual(
            delta,
            entry,
            parsed_target_ig=parsed_target_ig,
            source_text=source_text,
        )
        if target_ig is not None:
            return request
        requests.append(request)

    if not requests:
        return None
    for request in requests:
        if request.var_name is not None and request.blocked_reason is None:
            return request
    for request in requests:
        if is_node_set_request_introducible(request):
            return request
    return requests[0]


def requests_from_node_set_delta(
    delta: dict[str, Any],
    source_text: str | None = None,
    max_requests: int = 4,
    *,
    include_introducible: bool = False,
) -> list[NodeSetSplitRequest]:
    """Build the full *coupled* move-set from a node_set_delta payload.

    Returns every bindable missing virtual (payload order), deduped by
    ``target_ig`` (first bindable occurrence wins), capped at ``max_requests``.
    Only entries with a bound ``var_name`` and no ``blocked_reason`` survive by
    default; when ``include_introducible`` is true, typed source expressions
    that can be hoisted to a named local also survive. When ``source_text`` is
    supplied, entries whose variable is not declared in the function are
    dropped (via ``_request_from_missing_virtual``). This is the coupled
    analogue of :func:`request_from_node_set_delta`, which returns a single
    request.
    """
    if not isinstance(delta, Mapping):
        return []
    delta = _normalize_node_set_delta_payload(delta)
    missing_virtuals = delta.get("missing_virtuals")
    if not isinstance(missing_virtuals, list):
        return []

    requests: list[NodeSetSplitRequest] = []
    seen_igs: set[int] = set()
    for entry in missing_virtuals:
        if not isinstance(entry, Mapping):
            continue
        parsed_target_ig = _as_int(entry.get("target_ig"))
        if parsed_target_ig is None or parsed_target_ig in seen_igs:
            continue
        request = _request_from_missing_virtual(
            delta,
            entry,
            parsed_target_ig=parsed_target_ig,
            source_text=source_text,
        )
        if (
            request.var_name is None or request.blocked_reason is not None
        ) and not (
            include_introducible and is_node_set_request_introducible(request)
        ):
            continue
        seen_igs.add(parsed_target_ig)
        requests.append(request)
        if max_requests and len(requests) >= max_requests:
            break
    return requests


def _normalize_node_set_delta_payload(delta: dict[str, Any]) -> dict[str, Any]:
    """Accept either a bare node_set_delta or solve-coloring JSON wrapper."""
    nested = delta.get("node_set_delta")
    if not isinstance(nested, dict):
        return delta
    merged = dict(nested)
    for key in ("function", "class_id"):
        if key not in merged and key in delta:
            merged[key] = delta[key]
    return merged


def is_node_set_request_introducible(request: NodeSetSplitRequest | None) -> bool:
    """True when a request can bind an unbindable expression to a typed local."""
    if (
        request is None
        or request.var_name is not None
        or request.source_expression is None
        or request.source_type is None
    ):
        return False
    return _source_expression_is_safe_to_bind(request.source_expression)


def generate_node_set_split_patches(
    source: str,
    function: str,
    request: NodeSetSplitRequest,
    *,
    max_read_sites: int = 4,
    include_combos: bool = True,
) -> list[CandidatePatch]:
    """Generate bounded alias and lifetime source candidates for a request."""
    if request.var_name is None or request.blocked_reason is not None:
        return []

    var_name = request.var_name
    target_ig = request.target_ig
    fn_name = function or request.function
    patches: list[CandidatePatch] = []
    seen_sources: set[str] = set()
    scope_paths = _source_scope_paths_for_name(source, fn_name, var_name)
    ambiguous_scope_paths = scope_paths if len(scope_paths) > 1 else ()
    if request.source_scope_path is not None:
        alias_scope_paths: tuple[tuple[str, ...] | None, ...] = (
            request.source_scope_path,
        )
    elif ambiguous_scope_paths:
        alias_scope_paths = tuple(ambiguous_scope_paths)
    else:
        alias_scope_paths = (None,)

    for scope_idx, scope_path in enumerate(alias_scope_paths):
        scope_suffix = (
            f"-scope{scope_idx}" if scope_path is not None and len(alias_scope_paths) > 1
            else ""
        )
        for read_idx in range(max(0, max_read_sites)):
            alias_id = (
                f"node-split-alias-{var_name}-ig{target_ig}"
                f"{scope_suffix}-use{read_idx}"
            )
            try:
                alias_source = mutate_insert_alias_before_use(
                    source,
                    fn_name,
                    var_name,
                    at_stmt_index=read_idx,
                    new_name=f"{var_name}_split_{target_ig}_{read_idx}",
                    scope_filter=scope_path,
                )
            except MutationUnsupported:
                alias_source = None
            alias_name = f"{var_name}_split_{target_ig}_{read_idx}"
            if (
                alias_source is not None
                and _synthetic_local_uses_within_decl_scope(alias_source, alias_name)
            ):
                _append_unique_patch(
                    patches,
                    seen_sources,
                    source,
                    alias_source,
                    candidate_id=alias_id,
                    summary=(
                        f"Introduce alias for {var_name} before read site "
                        f"{read_idx} targeting ig{target_ig}."
                    ),
                )

            lifetime_id = (
                f"node-split-lifetime-{var_name}-ig{target_ig}"
                f"{scope_suffix}-use{read_idx}"
            )
            try:
                lifetime_source = mutate_preserve_lifetime_after_use(
                    source,
                    fn_name,
                    var_name,
                    at_stmt_index=read_idx,
                    sink_name=f"{var_name}_split_sink_{target_ig}_{read_idx}",
                    scope_filter=scope_path,
                )
            except MutationUnsupported:
                lifetime_source = None
            sink_name = f"{var_name}_split_sink_{target_ig}_{read_idx}"
            if (
                lifetime_source is not None
                and _synthetic_local_uses_within_decl_scope(lifetime_source, sink_name)
            ):
                _append_unique_patch(
                    patches,
                    seen_sources,
                    source,
                    lifetime_source,
                    candidate_id=lifetime_id,
                    summary=(
                        f"Preserve {var_name} lifetime after read site "
                        f"{read_idx} targeting ig{target_ig}."
                    ),
                )

    if ambiguous_scope_paths:
        return _order_node_set_patches_for_search(patches)

    _append_decl_order_patches(
        patches,
        seen_sources,
        source,
        fn_name,
        var_name,
        target_ig,
    )
    _append_per_loop_rename_patches(
        patches,
        seen_sources,
        source,
        fn_name,
        var_name,
        target_ig,
    )
    _append_reassociation_patches(
        patches,
        seen_sources,
        source,
        fn_name,
        var_name,
        target_ig,
        request.class_id,
    )
    _append_prologue_reorder_patches(
        patches,
        seen_sources,
        source,
        fn_name,
        var_name,
        target_ig,
        request.class_id,
    )
    _append_assignment_chain_patches(
        patches,
        seen_sources,
        source,
        fn_name,
        var_name,
        target_ig,
        request.class_id,
    )
    _append_operand_alias_patches(
        patches,
        seen_sources,
        source,
        fn_name,
        var_name,
        target_ig,
        request.class_id,
    )
    _append_block_scope_patches(
        patches,
        seen_sources,
        source,
        fn_name,
        var_name,
        target_ig,
        request.class_id,
    )
    if include_combos:
        _append_combo_patches(
            patches,
            seen_sources,
            source,
            fn_name,
            request,
        )

    return _order_node_set_patches_for_search(patches)


def generate_node_set_introduce_binding_patches(
    source: str,
    function: str,
    request: NodeSetSplitRequest | None,
    *,
    max_bind_sites: int = 4,
    max_read_sites: int = 4,
    include_split_combos: bool = True,
) -> list[CandidatePatch]:
    """Generate candidates that bind an unbindable expression to a local."""
    if not is_node_set_request_introducible(request):
        return []
    assert request is not None
    expression = request.source_expression
    binding_type = request.source_type
    if expression is None or binding_type is None:
        return []
    if not _source_expression_is_safe_to_bind(expression):
        return []

    fn_name = function or request.function
    sites = _introduce_binding_sites(
        source,
        fn_name,
        expression,
        binding_type,
        max_bind_sites=max_bind_sites,
    )
    if not sites:
        return []

    patches: list[CandidatePatch] = []
    seen_sources: set[str] = set()
    for site_idx, site in enumerate(sites):
        binding_name = _unique_binding_name(
            source,
            _binding_name_prefix(expression, request.target_ig, site_idx),
        )
        bound_source = _build_introduce_binding_source(
            source,
            expression=expression,
            binding_name=binding_name,
            site=site,
        )
        bind_id = (
            f"node-split-introduce-binding-ig{request.target_ig}-"
            f"{_candidate_id_fragment(binding_name)}-bind-site{site_idx}"
        )
        _append_unique_patch(
            patches,
            seen_sources,
            source,
            bound_source,
            candidate_id=bind_id,
            summary=(
                f"Introduce typed binding {binding_name} for "
                f"{expression!r} targeting ig{request.target_ig}."
            ),
        )

        bound_request = replace(
            request,
            var_name=binding_name,
            blocked_reason=None,
        )
        for split_patch in generate_node_set_split_patches(
            bound_source,
            fn_name,
            bound_request,
            max_read_sites=max_read_sites,
            include_combos=include_split_combos,
        ):
            candidate_id = (
                f"node-split-introduce-binding-ig{request.target_ig}-"
                f"{_candidate_id_fragment(binding_name)}-"
                f"{split_patch.candidate_id}"
            )
            _append_unique_patch(
                patches,
                seen_sources,
                source,
                split_patch.patched_source,
                candidate_id=candidate_id,
                summary=(
                    f"Introduce typed binding {binding_name} for "
                    f"{expression!r}, then {split_patch.summary}"
                ),
            )
    return patches


def _synthetic_local_uses_within_decl_scope(source: str, local_name: str) -> bool:
    """Return false when a generated local is referenced outside its block.

    The node-set mutators generate unique synthetic locals. A source candidate
    is invalid if such a local is declared inside a nested block but a rewrite
    references it after that block closes.
    """
    if not _SIMPLE_IDENTIFIER_RE.match(local_name):
        return False
    stripped = _strip_c_comments(source)
    decl_match = re.search(
        r"(?m)^[ \t]*(?:volatile[ \t]+)?"
        r"(?:[A-Za-z_][A-Za-z_0-9]*[ \t]*\**[ \t]+)+"
        + re.escape(local_name)
        + r"\s*(?:=[^;]*)?;",
        stripped,
    )
    if decl_match is None:
        return False

    block_open = _innermost_open_brace_before(stripped, decl_match.start())
    if block_open is None:
        block_start = 0
        block_end = len(stripped)
    else:
        block_close = _find_matching_token(
            stripped,
            block_open,
            "{",
            "}",
            len(stripped),
        )
        if block_close is None:
            return False
        block_start = block_open
        block_end = block_close + 1

    for offset in _iter_name_offsets(stripped, local_name, 0, len(stripped)):
        if offset < decl_match.start():
            return False
        if offset < block_start or offset >= block_end:
            return False
    return True


def _innermost_open_brace_before(text: str, offset: int) -> int | None:
    stack: list[int] = []
    for index, ch in enumerate(text[:offset]):
        if ch == "{":
            stack.append(index)
        elif ch == "}" and stack:
            stack.pop()
    return stack[-1] if stack else None


def generate_coupled_node_set_split_patches(
    source: str,
    function: str,
    requests: list[NodeSetSplitRequest],
    *,
    max_read_sites: int = 4,
    max_per_ig: int = 12,
    max_candidates: int = 24,
    deadline: float | None = None,
) -> list[CandidatePatch]:
    """Compose per-ig single edits into *simultaneous* multi-ig candidates.

    Coupled rotations (N igs that must move to N target registers at once)
    cannot be realized one ig at a time. This composes the existing single-ig
    generators across the request set via a bounded sequential frontier: each
    request expands every surviving source by re-running
    :func:`generate_node_set_split_patches` on it (so each later edit is
    re-parsed and re-validated against the already-edited text), keeping only
    branches that produced an edit for *every* request.

    Safety: each per-ig edit is individually behavior-preserving, so composing
    edits on distinct source vars preserves behavior. When two requests share a
    var, an earlier whole-var edit can rename it away and the later request
    simply prunes its branch — yielding fewer or zero candidates, never a wrong
    edit.
    """
    if not requests or _deadline_expired(deadline):
        return []
    fn_name = function or requests[0].function

    # frontier elements: (current_source, [fragment ids], [summaries])
    frontier: list[tuple[str, list[str], list[str]]] = [(source, [], [])]
    for request in requests:
        if _deadline_expired(deadline):
            return []
        if (
            request.var_name is None or request.blocked_reason is not None
        ) and not is_node_set_request_introducible(request):
            return []
        next_frontier: list[tuple[str, list[str], list[str]]] = []
        for cur_source, ids, summaries in frontier:
            if _deadline_expired(deadline):
                return []
            singles = _generate_node_set_request_patches(
                cur_source,
                fn_name,
                request,
                max_read_sites=max_read_sites,
            )
            if _deadline_expired(deadline):
                return []
            ordered_singles = _order_node_set_patches_for_search(
                singles,
                cap=max_per_ig if max_per_ig else None,
            )
            for patch in ordered_singles:
                if _deadline_expired(deadline):
                    return []
                if patch.patched_source == cur_source:
                    continue
                next_frontier.append((
                    patch.patched_source,
                    ids + [patch.candidate_id],
                    summaries + [patch.summary],
                ))
        if not next_frontier:
            # Some ig produced no edit on any branch: the coupled rotation
            # cannot be realized as a composition of these single edits.
            return []
        if max_candidates:
            next_frontier = next_frontier[:max_candidates]
        frontier = next_frontier

    igs = "+".join(f"ig{request.target_ig}" for request in requests)
    patches: list[CandidatePatch] = []
    seen_sources: set[str] = set()
    for final_source, _ids, summaries in frontier:
        if _deadline_expired(deadline):
            break
        if final_source == source or final_source in seen_sources:
            continue
        seen_sources.add(final_source)
        candidate_id = f"node-split-coupled-{igs}-c{len(patches)}"
        patches.append(CandidatePatch(
            candidate_id=candidate_id,
            patched_source=final_source,
            summary=f"Coupled multi-ig move ({igs}): " + "; ".join(summaries),
            touched_ranges=((0, len(source)),),
            hunk=_patch_hunk(source, final_source, candidate_id),
        ))
        if max_candidates and len(patches) >= max_candidates:
            break
    return patches


def _generate_node_set_request_patches(
    source: str,
    function: str,
    request: NodeSetSplitRequest,
    *,
    max_read_sites: int,
) -> list[CandidatePatch]:
    if request.var_name is not None and request.blocked_reason is None:
        return generate_node_set_split_patches(
            source,
            function,
            request,
            max_read_sites=max_read_sites,
            include_combos=False,
        )
    return generate_node_set_introduce_binding_patches(
        source,
        function,
        request,
        max_bind_sites=max_read_sites,
        max_read_sites=max_read_sites,
        include_split_combos=False,
    )


def _append_combo_patches(
    patches: list[CandidatePatch],
    seen_sources: set[str],
    source: str,
    function: str,
    request: NodeSetSplitRequest,
    *,
    max_depth: int = 3,
    max_per_family_per_layer: int = 2,
    max_outputs: int = 24,
) -> None:
    if (
        request.var_name is None
        or request.blocked_reason is not None
        or request.class_id not in {0, 1}
    ):
        return

    patch_count = len(patches)
    seen_sources_snapshot = set(seen_sources)
    try:
        frontier: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
            (source, (), ())
        ]
        combo_idx = 0
        for _depth in range(max_depth):
            layer_counts: dict[str, int] = defaultdict(int)
            next_frontier: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
            for cur_source, family_chain, summaries in frontier:
                for family in _NODE_SET_COMBO_FAMILIES:
                    if family in family_chain:
                        continue
                    if (
                        max_per_family_per_layer
                        and layer_counts[family] >= max_per_family_per_layer
                    ):
                        continue
                    family_patches = _generate_node_set_family_patches(
                        cur_source,
                        function,
                        request,
                        family=family,
                    )
                    if not family_patches:
                        continue
                    for family_patch in family_patches:
                        if (
                            max_per_family_per_layer
                            and layer_counts[family] >= max_per_family_per_layer
                        ):
                            break
                        if family_patch.patched_source == cur_source:
                            continue
                        layer_counts[family] += 1
                        next_family_chain = family_chain + (family,)
                        next_summaries = summaries + (family_patch.summary,)
                        next_frontier.append((
                            family_patch.patched_source,
                            next_family_chain,
                            next_summaries,
                        ))
                        if len(next_family_chain) < 2:
                            continue
                        digest = sha1(
                            (
                                "|".join(next_family_chain)
                                + "\0"
                                + family_patch.patched_source
                            ).encode("utf-8")
                        ).hexdigest()[:6]
                        candidate_id = (
                            f"node-split-combo-{request.var_name}-"
                            f"ig{request.target_ig}-"
                            f"{'+'.join(next_family_chain)}-"
                            f"c{combo_idx}-{digest}"
                        )
                        before_count = len(patches)
                        _append_unique_patch(
                            patches,
                            seen_sources,
                            source,
                            family_patch.patched_source,
                            candidate_id=candidate_id,
                            summary=(
                                "Compose node-set split families "
                                f"{' + '.join(next_family_chain)} "
                                f"targeting ig{request.target_ig}: "
                                + "; ".join(next_summaries)
                            ),
                        )
                        if len(patches) > before_count:
                            combo_idx += 1
                            if max_outputs and combo_idx >= max_outputs:
                                return
            if not next_frontier:
                return
            frontier = next_frontier
    except Exception:
        del patches[patch_count:]
        seen_sources.clear()
        seen_sources.update(seen_sources_snapshot)
        return


def _generate_node_set_family_patches(
    source: str,
    function: str,
    request: NodeSetSplitRequest,
    *,
    family: str,
) -> list[CandidatePatch]:
    if request.var_name is None or request.blocked_reason is not None:
        return []
    patches: list[CandidatePatch] = []
    seen_sources: set[str] = set()
    var_name = request.var_name
    target_ig = request.target_ig
    class_id = request.class_id
    if family == "prologue-reorder":
        _append_prologue_reorder_patches(
            patches,
            seen_sources,
            source,
            function,
            var_name,
            target_ig,
            class_id,
        )
    elif family == "assignment-chain":
        _append_assignment_chain_patches(
            patches,
            seen_sources,
            source,
            function,
            var_name,
            target_ig,
            class_id,
        )
    elif family == "operand-alias":
        _append_operand_alias_patches(
            patches,
            seen_sources,
            source,
            function,
            var_name,
            target_ig,
            class_id,
        )
    elif family == "block-scope":
        _append_block_scope_patches(
            patches,
            seen_sources,
            source,
            function,
            var_name,
            target_ig,
            class_id,
        )
    else:
        return []
    return _order_node_set_patches_for_search(patches)


def _node_set_candidate_family(candidate_id: str) -> str:
    if candidate_id.startswith("node-split-combo-"):
        return "combo"
    prefix = "node-split-"
    if not candidate_id.startswith(prefix):
        return "other"
    remainder = candidate_id[len(prefix):]
    for family in (
        "prologue-reorder",
        "assignment-chain",
        "operand-alias",
        "block-scope",
        "decl-order",
        "loop-rename",
        "reassoc",
        "introduce-binding",
        "alias",
        "lifetime",
    ):
        if remainder.startswith(f"{family}-"):
            return family
    return remainder.split("-", 1)[0] if remainder else "other"


def _order_node_set_patches_for_search(
    patches: list[CandidatePatch],
    *,
    cap: int | None = None,
    priority_families: tuple[str, ...] = _NODE_SET_PRIORITY_FAMILIES,
) -> list[CandidatePatch]:
    by_family: dict[str, list[CandidatePatch]] = defaultdict(list)
    family_order: list[str] = []
    for patch in patches:
        family = _node_set_candidate_family(patch.candidate_id)
        if family not in by_family:
            family_order.append(family)
        by_family[family].append(patch)

    ordered: list[CandidatePatch] = []
    round_families = [
        family for family in priority_families if family in by_family
    ] + [
        family for family in family_order if family not in priority_families
    ]
    while round_families:
        next_round: list[str] = []
        for family in round_families:
            bucket = by_family[family]
            if not bucket:
                continue
            ordered.append(bucket.pop(0))
            if cap is not None and len(ordered) >= cap:
                return ordered
            if bucket:
                next_round.append(family)
        round_families = next_round
    return ordered


def _simple_assignment_records(
    source: str,
    function: str,
    class_id: int,
) -> list[_SimpleAssignmentRecord]:
    span = find_function(source, function)
    if span is None:
        return []

    stripped = _strip_c_comments(source)
    body_start = span.body_open + 1
    body_end = span.body_close
    if _node_set_region_has_comment(source, body_start, body_end):
        return []
    if _node_set_region_has_global_unsafe_tokens(stripped, body_start, body_end):
        return []

    param_types = _node_set_param_scalar_types(source, function)
    all_declared_types = dict(param_types)
    for stmt_start, stmt_end, _block_id in _iter_node_set_statement_ranges(
        stripped,
        body_start,
        body_end,
    ):
        decl_parts = _parse_node_set_scalar_decl_parts(
            stripped[stmt_start:stmt_end]
        )
        if decl_parts is not None:
            name, type_name, _initializer = decl_parts
            if name in all_declared_types and all_declared_types[name] != type_name:
                return []
            all_declared_types[name] = type_name

    if _node_set_region_takes_address_of_name(
        stripped,
        set(all_declared_types),
        body_start,
        body_end,
    ):
        return []

    records: list[_SimpleAssignmentRecord] = []
    scope_types: list[dict[str, str]] = [dict(param_types)]
    scope_invalid: list[set[str]] = [set()]
    for event in _iter_node_set_scan_events(
        stripped,
        body_start,
        body_end,
    ):
        event_kind = event[0]
        if event_kind == "enter":
            scope_types.append({})
            scope_invalid.append(set())
            continue
        if event_kind == "exit":
            if len(scope_types) > 1:
                scope_types.pop()
                scope_invalid.pop()
            continue

        _kind, stmt_start, stmt_end, block_id = event
        stmt_text = stripped[stmt_start:stmt_end]
        decl_parts = _parse_node_set_scalar_decl_parts(stmt_text)
        if decl_parts is not None:
            name, type_name, initializer = decl_parts
            if name in scope_types[-1] and scope_types[-1][name] != type_name:
                return []
            visible_before_decl = _node_set_visible_types(scope_types)
            invalid_before_decl = _node_set_visible_invalid_names(
                scope_types,
                scope_invalid,
            )
            scope_types[-1][name] = type_name
            if initializer is None:
                scope_invalid[-1].discard(name)
            else:
                rhs_status, _reads = _node_set_safe_rhs_reads(
                    initializer,
                    visible_before_decl,
                    invalid_before_decl,
                )
                if rhs_status == "safe" or not _node_set_assignment_invalidates_lhs(
                    initializer,
                    rhs_status,
                    visible_before_decl,
                    invalid_before_decl,
                ):
                    scope_invalid[-1].discard(name)
                else:
                    scope_invalid[-1].add(name)
            continue

        assignment = _parse_node_set_simple_assignment(stmt_text)
        if assignment is None:
            compound_update = _parse_node_set_compound_update(stmt_text)
            if compound_update is not None:
                lhs, rhs = compound_update
                lhs_type = _node_set_lookup_visible_type(scope_types, lhs)
                visible_types = _node_set_visible_types(scope_types)
                invalid_names = _node_set_visible_invalid_names(
                    scope_types,
                    scope_invalid,
                )
                rhs_status, _reads = _node_set_safe_rhs_reads(
                    rhs,
                    visible_types,
                    invalid_names,
                )
                if (
                    lhs_type in _NODE_SET_ALLOWED_FPR_TYPES
                    and rhs_status == "safe"
                    and lhs not in invalid_names
                ):
                    _node_set_mark_valid(scope_types, scope_invalid, lhs)
                else:
                    _node_set_mark_invalid(scope_types, scope_invalid, lhs)
                continue

            for name in _node_set_statement_invalidated_names(stmt_text):
                _node_set_mark_invalid(scope_types, scope_invalid, name)
            continue

        lhs, rhs = assignment
        lhs_type = _node_set_lookup_visible_type(scope_types, lhs)
        if lhs_type is None:
            continue
        visible_types = _node_set_visible_types(scope_types)
        invalid_names = _node_set_visible_invalid_names(scope_types, scope_invalid)
        rhs_status, reads = _node_set_safe_rhs_reads(
            rhs,
            visible_types,
            invalid_names,
        )
        if rhs_status != "safe":
            if _node_set_assignment_invalidates_lhs(
                rhs,
                rhs_status,
                visible_types,
                invalid_names,
            ):
                _node_set_mark_invalid(scope_types, scope_invalid, lhs)
            else:
                _node_set_mark_valid(scope_types, scope_invalid, lhs)
            continue

        _node_set_mark_valid(scope_types, scope_invalid, lhs)
        if not _node_set_type_allowed_for_class(lhs_type, class_id):
            continue
        line_start = source.rfind("\n", 0, stmt_start) + 1
        next_line = source.find("\n", stmt_end)
        line_end = len(source) if next_line < 0 else next_line + 1
        records.append(_SimpleAssignmentRecord(
            lhs=lhs,
            rhs=rhs.strip(),
            start=stmt_start,
            end=stmt_end,
            line_end=line_end,
            line=source[line_start:line_end],
            block_id=block_id,
            reads=reads,
            lhs_type=lhs_type,
        ))
    return records


def _node_set_region_has_comment(source: str, start: int, end: int) -> bool:
    i = start
    while i < end:
        ch = source[i]
        if ch in {'"', "'"}:
            quote = ch
            i += 1
            while i < end:
                if source[i] == "\\" and i + 1 < end:
                    i += 2
                    continue
                if source[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "/" and i + 1 < end and source[i + 1] in {"/", "*"}:
            return True
        i += 1
    return False


def _node_set_region_has_global_unsafe_tokens(
    stripped: str,
    start: int,
    end: int,
) -> bool:
    text = stripped[start:end]
    if re.search(r"(?m)^\s*#", text) is not None:
        return True
    if re.search(r"\bvolatile\b", text) is not None:
        return True
    if re.search(r"\b(?:case|default)\b[^;{}]*:", text) is not None:
        return True
    if re.search(r"(?:^|[;{}])\s*[A-Za-z_][A-Za-z_0-9]*\s*:", text) is not None:
        return True
    return False


def _iter_node_set_statement_ranges(
    stripped: str,
    start: int,
    end: int,
):
    for event in _iter_node_set_scan_events(stripped, start, end):
        if event[0] == "stmt":
            _kind, stmt_start, stmt_end, block_id = event
            yield stmt_start, stmt_end, block_id


def _iter_node_set_scan_events(
    stripped: str,
    start: int,
    end: int,
):
    block_stack = [0]
    next_block_id = 1
    cursor = start
    while cursor < end:
        while cursor < end and stripped[cursor].isspace():
            cursor += 1
        if cursor >= end:
            return
        if stripped[cursor] == "{":
            block_id = next_block_id
            block_stack.append(block_id)
            next_block_id += 1
            yield "enter", block_id
            cursor += 1
            continue
        if stripped[cursor] == "}":
            if len(block_stack) > 1:
                block_stack.pop()
                yield "exit", block_stack[-1]
            cursor += 1
            continue
        if _node_set_control_starts_at(stripped, cursor):
            cursor = _skip_node_set_control_statement(stripped, cursor, end)
            continue

        statement_end = _find_statement_semicolon(stripped, cursor, end)
        if statement_end is None:
            return
        if stripped[statement_end] != ";":
            cursor = statement_end + 1
            continue
        yield "stmt", cursor, statement_end + 1, block_stack[-1]
        cursor = statement_end + 1


def _node_set_control_starts_at(stripped: str, offset: int) -> bool:
    return any(
        _keyword_at(stripped, offset, keyword)
        for keyword in _NODE_SET_CONTROL_WORDS
    )


def _skip_node_set_control_statement(
    stripped: str,
    start: int,
    end: int,
) -> int:
    boundary = _find_statement_semicolon(stripped, start, end)
    if boundary is None:
        return end
    if stripped[boundary] == "{":
        return _skip_balanced_node_set_block(stripped, boundary, end)
    return boundary + 1


def _skip_balanced_node_set_block(stripped: str, open_brace: int, end: int) -> int:
    depth = 0
    cursor = open_brace
    while cursor < end:
        ch = stripped[cursor]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cursor + 1
        cursor += 1
    return end


def _node_set_param_scalar_types(source: str, function: str) -> dict[str, str]:
    extracted = _extract_function_text(source, function)
    if extracted is None:
        return {}
    params_text, _body_text, _line = extracted
    types: dict[str, str] = {}
    for decl in _parse_params(params_text):
        type_name = _normalize_node_set_scalar_type(decl.type_str)
        if type_name is not None:
            types[decl.name] = type_name
    return types


def _parse_node_set_scalar_decl(statement: str) -> tuple[str, str] | None:
    parts = _parse_node_set_scalar_decl_parts(statement)
    if parts is None:
        return None
    name, type_name, _initializer = parts
    return name, type_name


def _parse_node_set_scalar_decl_parts(
    statement: str,
) -> tuple[str, str, str | None] | None:
    text = statement.strip()
    if not text.endswith(";"):
        return None
    text = text[:-1]
    left, sep, initializer = text.partition("=")
    if any(ch in left for ch in "[]{}(),"):
        return None
    match = _NODE_SET_SCALAR_DECL_RE.match(left + ";")
    if match is None:
        return None
    type_part = match.group("type")
    if not type_part or (
        not type_part[-1].isspace() and type_part[-1] != "*"
    ):
        return None
    type_name = _normalize_node_set_scalar_type(type_part)
    if type_name is None:
        return None
    return match.group("name"), type_name, initializer.strip() if sep else None


def _parse_node_set_simple_assignment(statement: str) -> tuple[str, str] | None:
    if "\n" in statement.strip():
        return None
    match = _NODE_SET_SIMPLE_ASSIGNMENT_RE.match(statement)
    if match is None:
        return None
    return match.group("lhs"), match.group("rhs")


def _parse_node_set_compound_update(statement: str) -> tuple[str, str] | None:
    if "\n" in statement.strip():
        return None
    match = re.match(
        r"^\s*(?P<lhs>[A-Za-z_][A-Za-z_0-9]*)\s*"
        r"(?P<op>[+\-*/%&|^]|<<|>>)=\s*(?P<rhs>.+);\s*$",
        statement,
    )
    if match is None:
        return None
    return match.group("lhs"), match.group("rhs")


def _node_set_statement_is_barrier(statement: str) -> bool:
    text = statement.strip()
    if not text:
        return False
    if "=" in text:
        return True
    if any(token in text for token in ("[", "]", ".", "->", "?", ":", ",")):
        return True
    if any(op in text for op in ("++", "--", "&&", "||")):
        return True
    if re.search(r"\b[A-Za-z_][A-Za-z_0-9]*\s*\(", text) is not None:
        return True
    if "&" in text or re.search(r"(^|[^A-Za-z_0-9])\*", text) is not None:
        return True
    return any(
        re.search(rf"\b{keyword}\b", text) is not None
        for keyword in _NODE_SET_CONTROL_WORDS
    )


def _node_set_safe_rhs_reads(
    rhs: str,
    visible_types: Mapping[str, str],
    invalid_names: set[str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    invalid_names = invalid_names or set()
    text = _node_set_strip_scalar_casts(rhs).strip()
    if not text:
        return "unsafe", ()
    token_text = _node_set_strip_numeric_literals(text)
    if '"' in text or "'" in text:
        return "unsafe", ()
    if _node_set_rhs_has_call(token_text):
        return "call", ()
    if any(token in token_text for token in ("[", "]", ".", "->", "?", ":", ",")):
        return "unsafe", ()
    if any(op in token_text for op in ("++", "--", "&&", "||")):
        return "unsafe", ()
    if re.search(r"<<=|>>=|[+\-*/%&|^]=", token_text) is not None:
        return "unsafe", ()
    if re.search(r"(?<![=!<>])=(?!=)", token_text) is not None:
        return "unsafe", ()
    if "&" in token_text or "|" in token_text or "^" in token_text:
        return "unsafe", ()
    if _node_set_rhs_has_unary_deref(token_text):
        return "unsafe", ()
    if any(
        re.search(rf"\b{keyword}\b", token_text) is not None
        for keyword in _NODE_SET_CONTROL_WORDS
    ):
        return "unsafe", ()

    reads = tuple(dict.fromkeys(_node_set_identifier_reads(token_text)))
    if any(name not in visible_types for name in reads):
        return "unsafe", ()
    if any(name in invalid_names for name in reads):
        return "unsafe", ()
    return "safe", reads


def _node_set_strip_scalar_casts(text: str) -> str:
    def replace_cast(match: re.Match[str]) -> str:
        type_name = match.group("type")
        if _normalize_node_set_scalar_type(type_name) is None:
            return match.group(0)
        return " "

    return _NODE_SET_SCALAR_CAST_RE.sub(replace_cast, text)


def _node_set_strip_numeric_literals(text: str) -> str:
    return _NODE_SET_NUMERIC_LITERAL_RE.sub(" ", text)


def _node_set_rhs_is_arithmetic_chainable(rhs: str) -> bool:
    text = _node_set_strip_numeric_literals(
        _node_set_strip_scalar_casts(rhs)
    )
    if re.search(r"<<|>>|<=|>=|==|!=|&&|\|\|", text) is not None:
        return False
    if any(ch in text for ch in "<>&|^~!?[]{}."):
        return False
    return re.fullmatch(r"[\sA-Za-z_0-9()+\-*/%]+", text) is not None


def _node_set_assignment_invalidates_lhs(
    rhs: str,
    rhs_status: str,
    visible_types: Mapping[str, str],
    invalid_names: set[str],
) -> bool:
    if rhs_status == "safe":
        return False
    if rhs_status != "call":
        return True
    return not _node_set_known_scalar_call_rhs_is_valid(
        rhs,
        visible_types,
        invalid_names,
    )


def _node_set_known_scalar_call_rhs_is_valid(
    rhs: str,
    visible_types: Mapping[str, str],
    invalid_names: set[str],
) -> bool:
    text = _node_set_strip_scalar_casts(rhs).strip()
    call_names = re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)\s*\(", text)
    if not call_names or any(name not in _NODE_SET_KNOWN_SCALAR_CALLS for name in call_names):
        return False

    without_calls = text
    for name in call_names:
        without_calls = re.sub(
            rf"\b{re.escape(name)}\s*\([^()]*\)",
            " ",
            without_calls,
        )
    read_text = _node_set_strip_numeric_literals(without_calls)
    reads = tuple(dict.fromkeys(_node_set_identifier_reads(read_text)))
    return all(
        name in visible_types and name not in invalid_names
        for name in reads
    )


def _node_set_rhs_has_call(text: str) -> bool:
    return re.search(r"\b[A-Za-z_][A-Za-z_0-9]*\s*\(", text) is not None


def _node_set_rhs_has_unary_deref(text: str) -> bool:
    for match in re.finditer(r"\*", text):
        offset = match.start()
        prev = _previous_nonspace_offset(text, offset - 1)
        next_offset = offset + 1
        while next_offset < len(text) and text[next_offset].isspace():
            next_offset += 1
        if next_offset >= len(text):
            continue
        if prev is None or text[prev] in "(,+-/%&|^!~?:=":
            return True
    return False


def _node_set_identifier_reads(text: str) -> list[str]:
    return re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", text)


def _node_set_visible_types(scope_types: list[dict[str, str]]) -> dict[str, str]:
    visible: dict[str, str] = {}
    for scope in scope_types:
        visible.update(scope)
    return visible


def _node_set_visible_invalid_names(
    scope_types: list[dict[str, str]],
    scope_invalid: list[set[str]],
) -> set[str]:
    invalid: set[str] = set()
    visible_names = set(_node_set_visible_types(scope_types))
    for name in visible_names:
        scope_idx = _node_set_lookup_scope_index(scope_types, name)
        if scope_idx is not None and name in scope_invalid[scope_idx]:
            invalid.add(name)
    return invalid


def _node_set_lookup_visible_type(
    scope_types: list[dict[str, str]],
    name: str,
) -> str | None:
    scope_idx = _node_set_lookup_scope_index(scope_types, name)
    if scope_idx is None:
        return None
    return scope_types[scope_idx][name]


def _node_set_lookup_scope_index(
    scope_types: list[dict[str, str]],
    name: str,
) -> int | None:
    for idx in range(len(scope_types) - 1, -1, -1):
        if name in scope_types[idx]:
            return idx
    return None


def _node_set_mark_invalid(
    scope_types: list[dict[str, str]],
    scope_invalid: list[set[str]],
    name: str,
) -> None:
    scope_idx = _node_set_lookup_scope_index(scope_types, name)
    if scope_idx is not None:
        scope_invalid[scope_idx].add(name)


def _node_set_mark_valid(
    scope_types: list[dict[str, str]],
    scope_invalid: list[set[str]],
    name: str,
) -> None:
    scope_idx = _node_set_lookup_scope_index(scope_types, name)
    if scope_idx is not None:
        scope_invalid[scope_idx].discard(name)


def _node_set_statement_invalidated_names(statement: str) -> tuple[str, ...]:
    text = statement.strip()
    names: list[str] = []
    for pattern in (
        r"^\s*(?P<name>[A-Za-z_][A-Za-z_0-9]*)\s*(?:\+\+|--)\s*;",
        r"^\s*(?:\+\+|--)\s*(?P<name>[A-Za-z_][A-Za-z_0-9]*)\s*;",
        r"^\s*(?P<name>[A-Za-z_][A-Za-z_0-9]*)\s*(?:<<|>>|[+\-*/%&|^])=",
    ):
        match = re.match(pattern, text)
        if match is not None:
            names.append(match.group("name"))
    return tuple(dict.fromkeys(names))


def _node_set_region_takes_address_of_name(
    stripped: str,
    names: set[str],
    start: int,
    end: int,
) -> bool:
    if not names:
        return False
    cursor = start
    while cursor < end:
        ampersand = stripped.find("&", cursor, end)
        if ampersand < 0:
            return False
        cursor = ampersand + 1
        if ampersand > start and stripped[ampersand - 1] == "&":
            continue
        if cursor < end and stripped[cursor] == "&":
            cursor += 1
            continue
        probe = cursor
        while probe < end and stripped[probe].isspace():
            probe += 1
        while probe < end and stripped[probe] == "(":
            probe += 1
            while probe < end and stripped[probe].isspace():
                probe += 1
        for name in names:
            if _name_at(stripped, name, probe):
                return True
    return False


def _node_set_type_allowed_for_class(type_name: str, class_id: int) -> bool:
    if class_id == 1:
        return type_name in _NODE_SET_ALLOWED_FPR_TYPES
    if class_id == 0:
        return type_name in _NODE_SET_ALLOWED_GPR_TYPES
    return type_name in _NODE_SET_ALLOWED_FPR_TYPES | _NODE_SET_ALLOWED_GPR_TYPES


def _same_safe_scalar_type_class(type_a: str, type_b: str, class_id: int) -> bool:
    norm_a = _canonical_node_set_scalar_type(type_a)
    norm_b = _canonical_node_set_scalar_type(type_b)
    if norm_a is None or norm_b is None:
        return False
    if class_id == 1:
        return norm_a == norm_b and norm_a in {"f32", "f64"}
    if class_id == 0:
        return norm_a == norm_b and norm_a in {
            "s8",
            "s16",
            "s32",
            "s64",
            "u8",
            "u16",
            "u32",
            "u64",
            "ptr",
        }
    return False


def _canonical_node_set_scalar_type(type_str: str | None) -> str | None:
    if type_str in _NODE_SET_ALLOWED_FPR_TYPES | _NODE_SET_ALLOWED_GPR_TYPES:
        return type_str
    return _normalize_node_set_scalar_type(type_str)


def _normalize_node_set_scalar_type(type_str: str | None) -> str | None:
    if type_str is None:
        return None
    normalized = " ".join(type_str.replace("*", " * ").split())
    if not normalized or any(ch in normalized for ch in "[]{}();,="):
        return None
    tokens = normalized.split()
    if "volatile" in tokens:
        return None
    if "*" in tokens:
        return "ptr"
    tokens = [
        token for token in tokens
        if token not in {"const", "register", "static"}
    ]
    if not tokens:
        return None
    compact = " ".join(tokens)
    aliases = {
        "f32": "f32",
        "float": "f32",
        "f64": "f64",
        "double": "f64",
        "s8": "s8",
        "signed char": "s8",
        "char": "s8",
        "s16": "s16",
        "short": "s16",
        "short int": "s16",
        "signed short": "s16",
        "signed short int": "s16",
        "s32": "s32",
        "int": "s32",
        "signed": "s32",
        "signed int": "s32",
        "long": "s32",
        "long int": "s32",
        "signed long": "s32",
        "signed long int": "s32",
        "BOOL": "s32",
        "bool": "s32",
        "s64": "s64",
        "long long": "s64",
        "long long int": "s64",
        "signed long long": "s64",
        "signed long long int": "s64",
        "u8": "u8",
        "unsigned char": "u8",
        "u16": "u16",
        "unsigned short": "u16",
        "unsigned short int": "u16",
        "u32": "u32",
        "unsigned": "u32",
        "unsigned int": "u32",
        "unsigned long": "u32",
        "unsigned long int": "u32",
        "u64": "u64",
        "unsigned long long": "u64",
        "unsigned long long int": "u64",
    }
    return aliases.get(compact)


def _node_set_short_digest(text: str) -> str:
    return sha1(text.encode("utf-8")).hexdigest()[:8]


def evaluate_node_set_split_signature(
    baseline: BaselineSignature,
    candidate: BaselineSignature,
    request: NodeSetSplitRequest,
) -> dict[str, Any]:
    """Evaluate whether a candidate pcdump realizes the split objective."""
    assigned = dict(candidate.assigned_regs)
    assigned_reg = assigned.get(request.target_ig)
    target_reg_nums = _target_reg_numbers(request)
    target_reg_num = target_reg_nums[0] if target_reg_nums else None
    new_spills = sorted(candidate.spill_set - baseline.spill_set)
    target_reg_hit = (
        bool(target_reg_nums)
        and assigned_reg is not None
        and assigned_reg in target_reg_nums
    )

    if assigned_reg is None or not target_reg_nums:
        status = "missing-target"
    elif new_spills:
        status = "spill-regression"
    elif target_reg_hit:
        status = "realized"
    else:
        status = "wrong-register"

    return {
        "function": request.function,
        "class_id": request.class_id,
        "target_ig": request.target_ig,
        "target_reg": request.target_reg,
        "target_regs": list(_target_reg_names(request)),
        "target_reg_num": target_reg_num,
        "target_reg_nums": list(target_reg_nums),
        "assigned_reg": assigned_reg,
        "target_reg_hit": target_reg_hit,
        "new_spills": new_spills,
        "status": status,
    }


def evaluate_coupled_node_set_split_signature(
    baseline: BaselineSignature,
    candidate: BaselineSignature,
    requests: list[NodeSetSplitRequest],
) -> dict[str, Any]:
    """Evaluate a candidate against a *coupled* multi-ig objective.

    The objective is realized only when **every** request's ``target_ig`` is
    assigned its ``target_reg`` and no new spill appears. Status precedence
    mirrors the single-ig evaluator: ``missing-target`` (any ig/reg unresolved)
    > ``spill-regression`` > ``realized`` (all hit) > ``wrong-register``. The
    return dict carries an aggregate plus a ``per_ig`` breakdown; downstream
    ``_score_row`` reads only ``status``.
    """
    assigned = dict(candidate.assigned_regs)
    new_spills = sorted(candidate.spill_set - baseline.spill_set)

    per_ig: list[dict[str, Any]] = []
    any_missing = False
    all_hit = bool(requests)
    for request in requests:
        assigned_reg = assigned.get(request.target_ig)
        target_reg_nums = _target_reg_numbers(request)
        target_reg_num = target_reg_nums[0] if target_reg_nums else None
        hit = (
            bool(target_reg_nums)
            and assigned_reg is not None
            and assigned_reg in target_reg_nums
        )
        if assigned_reg is None or not target_reg_nums:
            any_missing = True
        if not hit:
            all_hit = False
        per_ig.append({
            "target_ig": request.target_ig,
            "target_reg": request.target_reg,
            "target_regs": list(_target_reg_names(request)),
            "target_reg_num": target_reg_num,
            "target_reg_nums": list(target_reg_nums),
            "assigned_reg": assigned_reg,
            "target_reg_hit": hit,
        })

    if any_missing or not requests:
        status = "missing-target"
    elif new_spills:
        status = "spill-regression"
    elif all_hit:
        status = "realized"
    else:
        status = "wrong-register"

    return {
        "function": requests[0].function if requests else "",
        "class_id": requests[0].class_id if requests else None,
        "target_igs": [request.target_ig for request in requests],
        "target_reg_hit": all_hit,
        "new_spills": new_spills,
        "status": status,
        "per_ig": per_ig,
    }


def derive_target_color_select_order_leads(
    ig: Any,
    requests: list[NodeSetSplitRequest],
    *,
    max_per_request: int = 2,
) -> list[TargetColorSelectOrderLead]:
    """Derive select-order objectives that would force missed target colors.

    The tiebreak surrogate can answer a narrow but useful question after a
    split candidate compiles: "If this virtual were selected just before/after
    another virtual in the candidate COLORGRAPH, would it receive one of its
    desired physical registers?"  The returned leads are source objectives for
    the existing select-order search layer; they are not treated as proof until
    a real source candidate compiles and passes the node-set objective.
    """
    if not requests or ig is None:
        return []

    from . import tiebreak as tb

    order = [int(item) for item in getattr(ig, "select_order", ()) or ()]
    nodes = getattr(ig, "nodes", {}) or {}
    if not order or not nodes:
        return []
    try:
        assigned = tb.predict_assignments(ig)
    except Exception:
        return []
    order_index = {ig_idx: index for index, ig_idx in enumerate(order)}

    leads: list[TargetColorSelectOrderLead] = []
    for request in requests:
        target_ig = int(request.target_ig)
        allowed = _target_reg_numbers(request)
        if not allowed or target_ig not in order_index or target_ig not in nodes:
            continue
        node = nodes.get(target_ig)
        if getattr(node, "incomplete", False):
            continue
        assigned_reg = assigned.get(target_ig)
        if assigned_reg in allowed:
            continue

        request_leads: list[TargetColorSelectOrderLead] = []
        for anchor_ig in order:
            if anchor_ig == target_ig:
                continue
            request_leads.extend(
                _target_color_leads_for_anchor(
                    ig,
                    order=order,
                    order_index=order_index,
                    target_ig=target_ig,
                    assigned_reg=assigned_reg,
                    allowed=allowed,
                    anchor_ig=anchor_ig,
                )
            )
        request_leads.sort(
            key=lambda lead: (
                lead.distance,
                lead.direction,
                lead.anchor_ig,
                lead.target_reg,
            )
        )
        if max_per_request:
            request_leads = request_leads[:max_per_request]
        leads.extend(request_leads)
    return leads


def annotate_target_color_select_order_leads(
    objective: Mapping[str, Any],
    ig: Any,
    requests: list[NodeSetSplitRequest],
    *,
    max_per_request: int = 2,
) -> dict[str, Any]:
    """Attach tiebreak-derived target-color select-order leads to an objective."""
    annotated = dict(objective)
    leads = derive_target_color_select_order_leads(
        ig,
        requests,
        max_per_request=max_per_request,
    )
    if leads:
        annotated["target_color_select_order_leads"] = [
            lead.to_dict() for lead in leads
        ]
    return annotated


def _target_color_leads_for_anchor(
    ig: Any,
    *,
    order: list[int],
    order_index: dict[int, int],
    target_ig: int,
    assigned_reg: int | None,
    allowed: tuple[int, ...],
    anchor_ig: int,
) -> list[TargetColorSelectOrderLead]:
    from . import tiebreak as tb

    leads: list[TargetColorSelectOrderLead] = []
    for direction in ("before", "after"):
        moved_order = _move_select_order(
            order,
            target_ig,
            anchor_ig=anchor_ig,
            direction=direction,
        )
        if moved_order == order:
            continue
        try:
            what_if = (
                tb.what_if(ig, target_ig, move_before=anchor_ig)
                if direction == "before"
                else tb.what_if(ig, target_ig, move_after=anchor_ig)
            )
        except Exception:
            continue
        if what_if.perturbed_reg not in allowed:
            continue
        target_order = (
            (target_ig, anchor_ig)
            if direction == "before"
            else (anchor_ig, target_ig)
        )
        distance = abs(order_index[target_ig] - order_index[anchor_ig])
        leads.append(TargetColorSelectOrderLead(
            target_ig=target_ig,
            assigned_reg=assigned_reg,
            target_regs=allowed,
            target_reg=what_if.perturbed_reg,
            anchor_ig=anchor_ig,
            direction=direction,
            target_order=target_order,
            distance=distance,
            description=(
                f"move ig{target_ig} {direction} ig{anchor_ig} "
                f"to select {what_if.perturbed_reg}"
            ),
        ))
    return leads


def _move_select_order(
    order: list[int],
    target_ig: int,
    *,
    anchor_ig: int,
    direction: str,
) -> list[int]:
    moved = list(order)
    if target_ig not in moved or anchor_ig not in moved:
        return moved
    moved.remove(target_ig)
    anchor_index = moved.index(anchor_ig)
    if direction == "after":
        anchor_index += 1
    moved.insert(anchor_index, target_ig)
    return moved


def summarize_node_set_split_scores(
    function: str,
    request: NodeSetSplitRequest,
    patches: list[CandidatePatch],
    scored_candidates: list[Any],
    threshold: float,
    *,
    stop_reason: str | None = None,
    candidate_limit: int | None = None,
    budget_seconds: float | None = None,
    elapsed_seconds: float | None = None,
    coupled_requests: list[NodeSetSplitRequest] | None = None,
) -> dict[str, Any]:
    """Summarize split-search results from objective status and checkdiff.

    `CandidateScore.status` is intentionally ignored. A candidate improves only
    when its node-set objective is realized and its numeric checkdiff delta is
    at least `threshold`.

    When ``coupled_requests`` is supplied (coupled multi-ig mode), the summary
    gains a ``coupled_requests`` list and a ``shared_source_var`` field (the var
    name shared by two or more requests, else ``None``). The default ``None``
    keeps single-ig summaries byte-for-byte unchanged.
    """
    rows = [_score_row(entry) for entry in scored_candidates]
    improved = [
        row for row in rows
        if row["objective_status"] == "realized"
        and row["compile_ok"] is not False
        and row["checkdiff_delta"] is not None
        and row["checkdiff_delta"] >= threshold
    ]
    improved.sort(
        key=lambda row: (
            -(row["checkdiff_delta"] if row["checkdiff_delta"] is not None else -9999),
            row["candidate_id"] or "",
        )
    )

    if stop_reason == "budget-exhausted":
        status = "exhausted"
    elif not patches:
        status = "blocked"
    elif improved:
        status = "improved"
    else:
        status = "exhausted"

    best = improved[0] if improved else None
    pending_count = max(0, len(patches) - len(rows))
    checkdiff_scored_count = sum(
        1 for row in rows
        if row.get("checkdiff_pct") is not None
        or row.get("checkdiff_delta") is not None
    )
    objective_counts: dict[str, int] = {}
    for row in rows:
        objective_status = row.get("objective_status")
        if objective_status is None:
            continue
        objective_counts[objective_status] = (
            objective_counts.get(objective_status, 0) + 1
        )
    wrong_register_count = objective_counts.get("wrong-register", 0)
    compile_failed_count = objective_counts.get("compile-failed", 0)
    wrong_register_exhausted = (
        bool(patches)
        and bool(rows)
        and stop_reason is None
        and pending_count == 0
        and wrong_register_count == len(rows)
        and all(row.get("compile_ok") is True for row in rows)
    )
    wrong_register_or_compile_failed_exhausted = (
        bool(patches)
        and bool(rows)
        and stop_reason is None
        and pending_count == 0
        and wrong_register_count > 0
        and wrong_register_count + compile_failed_count == len(rows)
    )
    stop_condition = None
    if stop_reason is not None:
        stop_condition = {
            "kind": stop_reason,
            "candidate_limit": candidate_limit,
            "budget_seconds": budget_seconds,
            "elapsed_seconds": elapsed_seconds,
        }
    summary = {
        "status": status,
        "function": function,
        "request": asdict(request),
        "threshold": threshold,
        "generated_count": len(patches),
        "scored_count": len(rows),
        "evaluated_count": len(rows),
        "checkdiff_scored_count": checkdiff_scored_count,
        "pending_count": pending_count,
        "omitted_count": pending_count,
        "objective_counts": objective_counts,
        "wrong_register_count": wrong_register_count,
        "wrong_register_exhausted": wrong_register_exhausted,
        "wrong_register_or_compile_failed_exhausted": (
            wrong_register_or_compile_failed_exhausted
        ),
        "terminal_reason": (
            "all-wrong-register"
            if wrong_register_exhausted
            else "wrong-register-or-compile-failed"
            if wrong_register_or_compile_failed_exhausted
            else None
        ),
        "realized_count": sum(
            1 for row in rows if row["objective_status"] == "realized"
        ),
        "best_candidate_id": best["candidate_id"] if best is not None else None,
        "best_checkdiff_delta": (
            best["checkdiff_delta"] if best is not None else None
        ),
        "blocked_reason": request.blocked_reason if status == "blocked" else None,
        "stop_reason": stop_reason,
        "stop_condition": stop_condition,
        "candidate_limit": candidate_limit,
        "budget_seconds": budget_seconds,
        "elapsed_seconds": elapsed_seconds,
        "exhaustive": stop_reason is None and status != "blocked",
        "next_steps": _node_set_split_next_steps(
            function=function,
            status=status,
            stop_reason=stop_reason,
            candidate_limit=candidate_limit,
            budget_seconds=budget_seconds,
            wrong_register_exhausted=(
                wrong_register_exhausted
                or wrong_register_or_compile_failed_exhausted
            ),
            coupled=coupled_requests is not None,
        ),
        "candidates": rows,
    }
    if coupled_requests is not None:
        seen_vars: set[str] = set()
        shared_source_var: str | None = None
        for coupled_request in coupled_requests:
            name = coupled_request.var_name
            if name is not None and name in seen_vars and shared_source_var is None:
                shared_source_var = name
            if name is not None:
                seen_vars.add(name)
        summary["coupled_requests"] = [asdict(r) for r in coupled_requests]
        summary["shared_source_var"] = shared_source_var
        in_place_recolor = _in_place_recolor_classification(
            status=status,
            request=request,
            patches=patches,
            rows=rows,
            coupled_requests=coupled_requests,
            wrong_register_exhausted=(
                wrong_register_exhausted
                or wrong_register_or_compile_failed_exhausted
            ),
            stop_reason=stop_reason,
            pending_count=pending_count,
            candidate_limit=candidate_limit,
            budget_seconds=budget_seconds,
        )
        if in_place_recolor is not None:
            summary["in_place_recolor"] = in_place_recolor
    return summary


def _in_place_recolor_classification(
    *,
    status: str,
    request: NodeSetSplitRequest,
    patches: list[CandidatePatch],
    rows: list[dict[str, Any]],
    coupled_requests: list[NodeSetSplitRequest] | None,
    wrong_register_exhausted: bool,
    stop_reason: str | None,
    pending_count: int,
    candidate_limit: int | None,
    budget_seconds: float | None,
) -> dict[str, Any] | None:
    if coupled_requests is None:
        return None

    wrong_register_count = sum(
        1 for row in rows if row.get("objective_status") == "wrong-register"
    )
    evidence = {
        "generated_count": len(patches),
        "scored_count": len(rows),
        "pending_count": pending_count,
        "wrong_register_count": wrong_register_count,
        "stop_reason": stop_reason,
        "candidate_limit": candidate_limit,
        "budget_seconds": budget_seconds,
    }

    candidate_cap_may_have_truncated = (
        candidate_limit is not None and len(patches) >= candidate_limit
    )

    if wrong_register_exhausted and not candidate_cap_may_have_truncated:
        class_status = "no-shippable-mutator"
        terminal = True
        recommendation = (
            "do not rerun node-set-split with the same delta; classify this "
            "as a practical ceiling for source-shape in-place recolor and move "
            "to backend/coalescer control or a new mutator family"
        )
    elif status == "blocked" and len(coupled_requests) < 2:
        class_status = "insufficient-source-bindings"
        terminal = False
        recommendation = (
            request.blocked_reason
            or "coupled mode needs at least two source-bindable requests"
        )
    elif stop_reason == "candidate-limit" or candidate_cap_may_have_truncated:
        class_status = "incomplete"
        terminal = False
        recommendation = (
            "rerun with a larger --max-candidates value, or use "
            "--max-candidates 0 for an exhaustive source-shape search"
        )
    elif stop_reason == "budget-exhausted":
        class_status = "incomplete"
        terminal = False
        recommendation = "rerun with a larger --budget value"
    else:
        class_status = "search-active"
        terminal = False
        recommendation = (
            "continue only if a broader source mutator family is available"
        )

    return {
        "kind": "coupled-same-class-in-place-recolor",
        "status": class_status,
        "terminal": terminal,
        "function": request.function,
        "class_id": request.class_id,
        "target_igs": [req.target_ig for req in coupled_requests],
        "evidence": evidence,
        "recommendation": recommendation,
    }


def _node_set_split_next_steps(
    *,
    function: str,
    status: str,
    stop_reason: str | None,
    candidate_limit: int | None,
    budget_seconds: float | None,
    wrong_register_exhausted: bool = False,
    coupled: bool = False,
) -> list[str]:
    steps: list[str] = []
    if wrong_register_exhausted:
        steps.append(
            "do not rerun node-set-split with the same delta: this source-shape "
            "family was exhaustively compiled and every objective stayed "
            "wrong-register"
        )
        if coupled:
            steps.append(
                "for coupled rotations, inspect each per_ig assigned_reg and "
                "switch to coloring-register steering or a different source "
                "lever instead of composing more node-set-split edits"
            )
    if stop_reason == "candidate-limit":
        if candidate_limit is None:
            steps.append("rerun without --max-candidates to make the candidate search exhaustive")
        else:
            steps.append(
                "rerun with a larger --max-candidates value, or use "
                "--max-candidates 0 for an exhaustive source-shape search"
            )
    if stop_reason == "budget-exhausted":
        if budget_seconds is None:
            steps.append("rerun with a larger --budget value to continue the search")
        else:
            steps.append(
                "rerun with a larger --budget value to continue the "
                "source-shape search"
            )
    if stop_reason is not None or status == "exhausted":
        steps.append(
            "for suspected target-only allocator splits, first run "
            f"`melee-agent debug inspect trace-copy -f {function} --list-copies`; "
            "copy-not-found means coalesce/block-copy probes are the wrong layer"
        )
    return steps


def _request_from_missing_virtual(
    delta: Mapping[str, Any],
    entry: Mapping[str, Any],
    *,
    parsed_target_ig: int,
    source_text: str | None,
) -> NodeSetSplitRequest:
    function = str(entry.get("function") or delta.get("function") or "")
    class_id = _as_int(delta.get("class_id"))
    if class_id is None:
        class_id = _as_int(entry.get("class_id")) or 0
    source = entry.get("source")
    source_map = source if isinstance(source, Mapping) else {}
    var_name = _bindable_source_name(source_map)
    source_expression = _optional_str(source_map.get("expression"))
    source_kind = _optional_str(source_map.get("kind"))
    source_line = _as_int(source_map.get("source_line"))
    source_scope_path = (
        _source_scope_path_for_name(
            source_text,
            function,
            var_name,
            source_line=source_line,
        )
        if source_text is not None and var_name is not None and function
        else None
    )
    source_type = _source_binding_type(
        source_map,
        source_text=source_text,
        function=function,
        expression=source_expression,
    )
    blocked_reason = None
    if var_name is None:
        blocked_reason = (
            f"no bindable source variable for ig{parsed_target_ig}"
        )
    elif source_text is not None and not _source_declares_name(
        source_text, function, var_name
    ):
        blocked_reason = (
            f"no bindable source variable {var_name!r} in {function}"
        )
        var_name = None

    return NodeSetSplitRequest(
        function=function,
        class_id=class_id,
        target_ig=parsed_target_ig,
        current_reg=_optional_str(
            entry.get("current_register") or entry.get("current_reg")
        ),
        target_reg=_target_register(entry),
        var_name=var_name,
        blocked_reason=blocked_reason,
        source_expression=source_expression,
        source_type=source_type,
        source_kind=source_kind,
        target_regs=_target_registers(entry),
        source_scope_path=source_scope_path,
    )


def _bindable_source_name(source: Mapping[str, Any]) -> str | None:
    expression = _optional_str(source.get("expression"))
    base_var = _optional_str(source.get("base_var"))
    name = _optional_str(source.get("name"))

    if _is_simple_identifier(expression):
        return expression
    if _is_simple_identifier(base_var):
        return base_var
    if _is_simple_identifier(name) and not _is_field_expression(expression):
        return name
    return None


def _source_declares_name(source_text: str, function: str, var_name: str) -> bool:
    extracted = _extract_function_text(source_text, function)
    if extracted is None:
        return False
    params_text, body_text, _line = extracted
    names = {decl.name for decl in _parse_params(params_text)}
    names.update(decl.name for decl in walk_local_decls(body_text))
    try:
        from . import ast_walker

        names.update(
            decl.name
            for decl in ast_walker.walk_function(source_text, function, path=None)
        )
    except Exception:
        pass
    return var_name in names


def _source_scope_path_for_name(
    source_text: str | None,
    function: str,
    var_name: str | None,
    *,
    source_line: int | None,
) -> tuple[str, ...] | None:
    if not source_text or not function or not var_name:
        return None
    try:
        from . import ast_walker

        decls = [
            decl for decl in ast_walker.walk_function(source_text, function, path=None)
            if decl.name == var_name
        ]
    except Exception:
        return None
    if not decls:
        return None
    if source_line is not None:
        containing = [
            decl for decl in decls
            if decl.line_no == source_line
            or (
                decl.scope_byte_range[0]
                <= _line_start_byte(source_text, source_line)
                < decl.scope_byte_range[1]
            )
        ]
        if len(containing) == 1:
            return containing[0].scope_path
        if containing:
            containing.sort(
                key=lambda decl: (
                    decl.line_no != source_line,
                    -len(decl.scope_path),
                )
            )
            return containing[0].scope_path
    if len(decls) == 1:
        return decls[0].scope_path
    return None


def _source_scope_paths_for_name(
    source_text: str | None,
    function: str,
    var_name: str | None,
) -> tuple[tuple[str, ...], ...]:
    if not source_text or not function or not var_name:
        return ()
    try:
        from . import ast_walker

        decls = [
            decl for decl in ast_walker.walk_function(source_text, function, path=None)
            if decl.name == var_name
        ]
    except Exception:
        return ()
    seen: set[tuple[str, ...]] = set()
    paths: list[tuple[str, ...]] = []
    for decl in decls:
        if decl.scope_path in seen:
            continue
        seen.add(decl.scope_path)
        paths.append(decl.scope_path)
    return tuple(paths)


def _line_start_byte(source_text: str, line_no: int) -> int:
    if line_no <= 1:
        return 0
    line = 1
    for idx, ch in enumerate(source_text):
        if ch == "\n":
            line += 1
            if line == line_no:
                return len(source_text[:idx + 1].encode("utf-8"))
    return len(source_text.encode("utf-8"))


def _source_binding_type(
    source: Mapping[str, Any],
    *,
    source_text: str | None,
    function: str,
    expression: str | None,
) -> str | None:
    explicit = _normalize_safe_binding_type(_optional_str(source.get("type")))
    if explicit is not None:
        return explicit
    if source_text is None or expression is None or not function:
        return None
    if not _source_expression_is_safe_to_bind(expression):
        return None
    return _infer_binding_type_from_source(source_text, function, expression)


def _infer_binding_type_from_source(
    source: str,
    function: str,
    expression: str,
) -> str | None:
    try:
        statements = list_statement_spans(source, function)
    except Exception:
        return None
    for span in statements:
        context = _binding_context_for_span(
            source,
            function,
            span,
            expression,
            fallback_type=None,
        )
        if context is not None:
            _mode, binding_type = context
            return binding_type
    return None


def _introduce_binding_sites(
    source: str,
    function: str,
    expression: str,
    binding_type: str,
    *,
    max_bind_sites: int,
) -> list[_IntroduceBindingSite]:
    try:
        statements = list_statement_spans(source, function)
    except Exception:
        return []
    sites: list[_IntroduceBindingSite] = []
    for span in statements:
        context = _binding_context_for_span(
            source,
            function,
            span,
            expression,
            fallback_type=binding_type,
        )
        if context is None:
            continue
        mode, site_type = context
        statement_text = source[span.byte_range[0]:span.byte_range[1]]
        for rel_start in _iter_expression_offsets(statement_text, expression):
            abs_start = span.byte_range[0] + rel_start
            abs_end = abs_start + len(expression)
            if not _expression_occurrence_is_rewritable(
                source,
                expression,
                abs_start,
                abs_end,
            ):
                continue
            sites.append(_IntroduceBindingSite(
                statement=span,
                occurrence_start=abs_start,
                occurrence_end=abs_end,
                binding_type=site_type,
                mode=mode,
            ))
            if max_bind_sites and len(sites) >= max_bind_sites:
                return sites
    return sites


def _binding_context_for_span(
    source: str,
    function: str,
    span: StatementSpan,
    expression: str,
    *,
    fallback_type: str | None,
) -> tuple[str, str] | None:
    if not _statement_span_starts_on_plain_line(source, span):
        return None
    stripped_text = _strip_c_comments(span.text).strip()
    if span.kind == "declaration":
        parsed_decl = _parse_intro_decl_initializer(stripped_text)
        if parsed_decl is None:
            return None
        decl_type, _decl_name, rhs = parsed_decl
        if expression not in rhs:
            return None
        if not _rhs_context_allows_unconditional_binding(rhs, expression):
            return None
        binding_type = (
            _normalize_safe_binding_type(decl_type)
            or _normalize_safe_binding_type(fallback_type)
        )
        if binding_type is None:
            return None
        return "declaration", binding_type

    if span.kind != "expression_statement":
        return None
    match = _INTRO_ASSIGNMENT_RE.match(stripped_text)
    if match is None:
        return None
    rhs = match.group("rhs")
    if expression not in rhs:
        return None
    if not _rhs_context_allows_unconditional_binding(rhs, expression):
        return None
    visible_types = _visible_binding_types_for_function(source, function)
    binding_type = (
        visible_types.get(match.group("lhs"))
        or _normalize_safe_binding_type(fallback_type)
    )
    if binding_type is None:
        return None
    return "assignment", binding_type


def _statement_span_starts_on_plain_line(source: str, span: StatementSpan) -> bool:
    line_start = source.rfind("\n", 0, span.byte_range[0]) + 1
    return not source[line_start:span.byte_range[0]].strip()


def _rhs_context_allows_unconditional_binding(rhs: str, expression: str) -> bool:
    text = _strip_c_comments(rhs).strip()
    if expression not in text:
        return False
    if re.search(r"\|\||&&|\?|:", text):
        return False
    if re.search(r"\+\+|--|(?<![=!<>])=(?!=)|<<=|>>=|[+\-*/%&|^]=", text):
        return False
    return "," not in text


def _parse_intro_decl_initializer(text: str) -> tuple[str, str, str] | None:
    if not text.endswith(";") or "=" not in text:
        return None
    left, rhs = text[:-1].split("=", 1)
    left = left.strip()
    rhs = rhs.strip()
    if not left or not rhs or "," in left:
        return None
    match = re.match(r"^(?P<type>.+?)(?P<name>[A-Za-z_][A-Za-z_0-9]*)$", left)
    if match is None:
        return None
    type_part = match.group("type")
    if not type_part or (not type_part[-1].isspace() and type_part[-1] != "*"):
        return None
    decl_type = type_part.strip()
    if decl_type.endswith("*"):
        decl_type = decl_type.rstrip()
    return decl_type, match.group("name"), rhs


def _visible_binding_types_for_function(
    source: str,
    function: str,
) -> dict[str, str]:
    extracted = _extract_function_text(source, function)
    if extracted is None:
        return {}
    params_text, body_text, _line = extracted
    counts: dict[str, int] = {}
    types: dict[str, str] = {}

    def add_decl(name: str, type_str: str) -> None:
        safe_type = _normalize_safe_binding_type(type_str)
        if safe_type is None:
            return
        counts[name] = counts.get(name, 0) + 1
        types[name] = safe_type

    for decl in _parse_params(params_text):
        add_decl(decl.name, decl.type_str)
    for decl in walk_local_decls(body_text):
        add_decl(decl.name, decl.type_str)
    return {
        name: type_str
        for name, type_str in types.items()
        if counts.get(name) == 1
    }


def _normalize_safe_binding_type(type_str: str | None) -> str | None:
    if type_str is None:
        return None
    normalized = " ".join(type_str.strip().split())
    normalized = re.sub(r"\s*\*\s*", "*", normalized)
    if not normalized:
        return None
    if any(ch in normalized for ch in "[]{}();,="):
        return None
    if _SAFE_BINDING_TYPE_RE.fullmatch(normalized) is None:
        return None
    return normalized


def _source_expression_is_safe_to_bind(expression: str) -> bool:
    text = expression.strip()
    if not text:
        return False
    if text.startswith("("):
        return False
    if re.search(r"\b[A-Za-z_][A-Za-z_0-9]*\s*\(", text):
        return False
    if re.search(r"\+\+|--|(?<![=!<>])=(?!=)|<<=|>>=|,", text):
        return False
    return re.search(r"\b[A-Za-z_][A-Za-z_0-9]*\b", text) is not None


def _iter_expression_offsets(statement_text: str, expression: str):
    stripped = _strip_c_comments(statement_text)
    start = 0
    while True:
        offset = stripped.find(expression, start)
        if offset < 0:
            return
        end = offset + len(expression)
        before = stripped[offset - 1] if offset > 0 else ""
        after = stripped[end] if end < len(stripped) else ""
        if before not in _IDENT_CHARS and after not in _IDENT_CHARS:
            yield offset
        start = max(end, offset + 1)


def _expression_occurrence_is_rewritable(
    source: str,
    expression: str,
    start: int,
    end: int,
) -> bool:
    if not _source_expression_is_safe_to_bind(expression):
        return False
    cursor = start - 1
    while cursor >= 0 and source[cursor].isspace():
        cursor -= 1
    if (
        cursor >= 0
        and source[cursor] == "&"
        and not expression.lstrip().startswith("&")
    ):
        return False

    cursor = end
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    while cursor < len(source) and source[cursor] == ")":
        cursor += 1
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1
    tail = source[cursor:cursor + 3]
    return not (
        tail.startswith(("++", "--"))
        or re.match(r"(?:[+\-*/%&|^]=|<<=|>>=|=(?!=))", tail) is not None
    )


def _binding_name_prefix(expression: str, target_ig: int, site_idx: int) -> str:
    base = _binding_base_name(expression)
    return f"{base}_bind_{target_ig}_{site_idx}"


def _binding_base_name(expression: str) -> str:
    text = expression.strip()
    field_match = re.search(r"(?:->|\.)\s*([A-Za-z_][A-Za-z_0-9]*)\s*$", text)
    if field_match is not None:
        return field_match.group(1)
    address_match = re.search(r"&\s*([A-Za-z_][A-Za-z_0-9]*)", text)
    if address_match is not None:
        return address_match.group(1)
    identifiers = re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", text)
    return identifiers[0] if identifiers else "value"


def _unique_binding_name(source: str, prefix: str) -> str:
    name = prefix
    suffix = 1
    while re.search(rf"\b{re.escape(name)}\b", source):
        name = f"{prefix}_{suffix}"
        suffix += 1
    return name


def _build_introduce_binding_source(
    source: str,
    *,
    expression: str,
    binding_name: str,
    site: _IntroduceBindingSite,
) -> str:
    statement_start, statement_end = site.statement.byte_range
    target_text = source[statement_start:statement_end]
    rel_start = site.occurrence_start - statement_start
    rel_end = site.occurrence_end - statement_start
    rewritten = target_text[:rel_start] + binding_name + target_text[rel_end:]
    line_start = source.rfind("\n", 0, statement_start) + 1
    indent = source[line_start:statement_start]
    if indent.strip():
        indent = ""

    if site.mode == "declaration":
        replacement = (
            f"{indent}{site.binding_type} {binding_name} = {expression};\n"
            f"{indent}{rewritten}"
        )
        return source[:line_start] + replacement + source[statement_end:]

    decl_insert = _block_top_insert_pos(source, site.statement.scope_byte_range)
    decl_line = f"{indent}{site.binding_type} {binding_name};\n"
    assign_line = f"{indent}{binding_name} = {expression};\n"
    edits = [
        (statement_start, statement_end, rewritten),
        (line_start, line_start, assign_line),
        (decl_insert, decl_insert, decl_line),
    ]
    patched = source
    for edit_start, edit_end, replacement in sorted(
        edits, key=lambda item: item[0], reverse=True
    ):
        patched = patched[:edit_start] + replacement + patched[edit_end:]
    return patched


def _block_top_insert_pos(source: str, scope_byte_range: tuple[int, int]) -> int:
    start, end = scope_byte_range
    open_brace = source.find("{", start, end)
    if open_brace < 0:
        return start
    pos = open_brace + 1
    while pos < end and source[pos] in " \t\r":
        pos += 1
    if pos < end and source[pos] == "\n":
        pos += 1
    return pos


def _append_unique_patch(
    patches: list[CandidatePatch],
    seen_sources: set[str],
    source: str,
    patched_source: str,
    *,
    candidate_id: str,
    summary: str,
) -> None:
    if patched_source == source or patched_source in seen_sources:
        return
    seen_sources.add(patched_source)
    patches.append(CandidatePatch(
        candidate_id=candidate_id,
        patched_source=patched_source,
        summary=summary,
        touched_ranges=((0, len(source)),),
        hunk=_patch_hunk(source, patched_source, candidate_id),
    ))


def _append_decl_order_patches(
    patches: list[CandidatePatch],
    seen_sources: set[str],
    source: str,
    function: str,
    var_name: str,
    target_ig: int,
) -> None:
    patch_count = len(patches)
    seen_sources_snapshot = set(seen_sources)
    try:
        scope_map = get_decl_names_by_scope(source, function)
        matching_scopes = [
            scope_path
            for scope_path, names in scope_map.items()
            if var_name in names
        ]

        for scope_idx, scope_path in enumerate(matching_scopes):
            scope_names = scope_map[scope_path]
            candidates = build_decl_order_candidates_for_scope(
                source,
                function,
                scope_path,
                strategy="all",
            )
            for candidate_idx, candidate in enumerate(candidates):
                # Intentional bound: try orders whose helper label names the
                # requested var, plus deduped group/pair orders that move it.
                if not _decl_order_candidate_involves_var(
                    candidate.label,
                    candidate.order,
                    scope_names,
                    var_name,
                ):
                    continue
                skip_reason = explain_decl_reorder_skip(
                    source,
                    function,
                    scope_path,
                    candidate.order,
                )
                if skip_reason:
                    continue
                patched_source = reorder_decls_in_function_scope(
                    source,
                    function,
                    scope_path,
                    candidate.order,
                )
                if patched_source is None:
                    continue
                candidate_id = (
                    f"node-split-decl-order-{var_name}-ig{target_ig}-"
                    f"s{scope_idx}-c{candidate_idx}-"
                    f"{_candidate_id_fragment(candidate.label)}"
                )
                _append_unique_patch(
                    patches,
                    seen_sources,
                    source,
                    patched_source,
                    candidate_id=candidate_id,
                    summary=(
                        f"Reorder {function} declarations in scope "
                        f"{'/'.join(scope_path)} using {candidate.label!r} "
                        f"for {var_name} targeting ig{target_ig}."
                    ),
                )
    except Exception:
        del patches[patch_count:]
        seen_sources.clear()
        seen_sources.update(seen_sources_snapshot)
        return


def _append_per_loop_rename_patches(
    patches: list[CandidatePatch],
    seen_sources: set[str],
    source: str,
    function: str,
    var_name: str,
    target_ig: int,
) -> None:
    patch_count = len(patches)
    seen_sources_snapshot = set(seen_sources)
    try:
        patched_source = _build_per_loop_rename_source(
            source,
            function,
            var_name,
            target_ig,
        )
        if patched_source is None:
            return
        candidate_id = (
            f"node-split-loop-rename-{var_name}-ig{target_ig}-"
            f"{_candidate_id_fragment(function)}"
        )
        _append_unique_patch(
            patches,
            seen_sources,
            source,
            patched_source,
            candidate_id=candidate_id,
            summary=(
                f"Split {var_name} into loop-local names targeting "
                f"ig{target_ig}."
            ),
        )
    except Exception:
        del patches[patch_count:]
        seen_sources.clear()
        seen_sources.update(seen_sources_snapshot)
        return


def _append_reassociation_patches(
    patches: list[CandidatePatch],
    seen_sources: set[str],
    source: str,
    function: str,
    var_name: str,
    target_ig: int,
    class_id: int,
) -> None:
    if class_id not in {0, 1}:
        return
    floating_names = (
        _floating_decl_names_for_function(source, function)
        if class_id == 1 else None
    )
    patch_count = len(patches)
    seen_sources_snapshot = set(seen_sources)
    try:
        stripped = _strip_c_comments(source)
        for assignment_idx, assignment in enumerate(
            _iter_reassociation_assignments(stripped, source, function, var_name)
        ):
            expr_start, expr_end, left_operand, right_operand = assignment
            if class_id == 1 and not _fpr_reassociation_allowed(
                floating_names,
                var_name,
                left_operand,
                right_operand,
            ):
                continue
            patched_source = (
                source[:expr_start]
                + f"{right_operand} + {left_operand}"
                + source[expr_end:]
            )
            candidate_id = (
                f"node-split-reassoc-{var_name}-ig{target_ig}-"
                f"stmt{assignment_idx}"
            )
            _append_unique_patch(
                patches,
                seen_sources,
                source,
                patched_source,
                candidate_id=candidate_id,
                summary=(
                    f"Swap simple addition operands assigned to {var_name} "
                    f"targeting ig{target_ig}."
                ),
            )
    except Exception:
        del patches[patch_count:]
        seen_sources.clear()
        seen_sources.update(seen_sources_snapshot)
        return


def _append_prologue_reorder_patches(
    patches: list[CandidatePatch],
    seen_sources: set[str],
    source: str,
    function: str,
    var_name: str,
    target_ig: int,
    class_id: int,
) -> None:
    patch_count = len(patches)
    seen_sources_snapshot = set(seen_sources)
    try:
        records = _simple_assignment_records(source, function, class_id)
        for first, second in _node_set_prologue_reorder_pairs(
            source,
            records,
            var_name,
        ):
            patched_source = _swap_node_set_assignment_lines(source, first, second)
            if patched_source is None:
                continue
            candidate_id = (
                f"node-split-prologue-reorder-{var_name}-ig{target_ig}-"
                f"b{first.block_id}-s{first.start}-t{second.start}"
            )
            _append_unique_patch(
                patches,
                seen_sources,
                source,
                patched_source,
                candidate_id=candidate_id,
                summary=(
                    f"Swap adjacent simple assignments around {var_name} "
                    f"targeting ig{target_ig}."
                ),
            )
    except Exception:
        del patches[patch_count:]
        seen_sources.clear()
        seen_sources.update(seen_sources_snapshot)
        return


def _append_assignment_chain_patches(
    patches: list[CandidatePatch],
    seen_sources: set[str],
    source: str,
    function: str,
    var_name: str,
    target_ig: int,
    class_id: int,
) -> None:
    if class_id not in {0, 1}:
        return

    patch_count = len(patches)
    seen_sources_snapshot = set(seen_sources)
    try:
        records = _simple_assignment_records(source, function, class_id)
        type_map = _node_set_scalar_type_map(source, function)
        for earlier_idx, earlier in enumerate(records):
            if not _node_set_record_uses_same_safe_scalar_type_class(
                earlier,
                type_map,
                class_id,
            ):
                continue
            for later in records[earlier_idx + 1:]:
                if later.lhs != var_name:
                    continue
                if earlier.block_id != later.block_id:
                    continue
                if not _same_safe_scalar_type_class(
                    earlier.lhs_type,
                    later.lhs_type,
                    class_id,
                ):
                    continue
                if not _node_set_record_uses_same_safe_scalar_type_class(
                    later,
                    type_map,
                    class_id,
                ):
                    continue
                watched_names = {earlier.lhs, *earlier.reads}
                if _node_set_has_intervening_write(
                    source,
                    earlier.end,
                    later.start,
                    watched_names,
                ):
                    continue
                for occurrence_idx, (occ_start, occ_end) in enumerate(
                    _node_set_assignment_chain_occurrences(source, earlier, later)
                ):
                    patched_source = (
                        source[:occ_start]
                        + earlier.lhs
                        + source[occ_end:]
                    )
                    candidate_id = (
                        f"node-split-assignment-chain-{var_name}-"
                        f"ig{target_ig}-b{earlier.block_id}-"
                        f"s{earlier.start}-t{later.start}-o{occurrence_idx}"
                    )
                    _append_unique_patch(
                        patches,
                        seen_sources,
                        source,
                        patched_source,
                        candidate_id=candidate_id,
                        summary=(
                            f"Rewrite {later.lhs} RHS to reuse {earlier.lhs} "
                            f"targeting ig{target_ig}."
                        ),
                    )
    except Exception:
        del patches[patch_count:]
        seen_sources.clear()
        seen_sources.update(seen_sources_snapshot)
        return


def _append_operand_alias_patches(
    patches: list[CandidatePatch],
    seen_sources: set[str],
    source: str,
    function: str,
    var_name: str,
    target_ig: int,
    class_id: int,
) -> None:
    if class_id not in {0, 1}:
        return

    patch_count = len(patches)
    seen_sources_snapshot = set(seen_sources)
    try:
        records = _simple_assignment_records(source, function, class_id)
        scalar_bindings = _node_set_unique_scalar_bindings(source, function)
        for record in records:
            if record.lhs != var_name:
                continue
            if not _node_set_record_starts_on_plain_line(source, record):
                continue
            decl_insert = _node_set_block_declaration_insert_pos(
                source,
                function,
                record.block_id,
                record.start,
            )
            if decl_insert is None:
                continue

            for occurrence_idx, occurrence in enumerate(
                _node_set_operand_alias_occurrences(source, record)
            ):
                operand, occ_start, occ_end = occurrence
                binding = scalar_bindings.get(operand)
                if binding is None:
                    continue
                if not _same_safe_scalar_type_class(
                    record.lhs_type,
                    binding.normalized_type,
                    class_id,
                ):
                    continue

                alias_name = _unique_binding_name(
                    source,
                    f"{operand}_alias_{target_ig}_{occurrence_idx}",
                )
                patched_source = _build_node_set_operand_alias_source(
                    source,
                    record,
                    decl_insert=decl_insert,
                    operand=operand,
                    operand_start=occ_start,
                    operand_end=occ_end,
                    operand_type=binding.source_type,
                    alias_name=alias_name,
                )
                if patched_source is None:
                    continue
                candidate_id = (
                    f"node-split-operand-alias-{var_name}-ig{target_ig}-"
                    f"b{record.block_id}-s{record.start}-"
                    f"op{_candidate_id_fragment(operand)}-o{occurrence_idx}"
                )
                _append_unique_patch(
                    patches,
                    seen_sources,
                    source,
                    patched_source,
                    candidate_id=candidate_id,
                    summary=(
                        f"Alias operand {operand} in the assignment to "
                        f"{var_name} targeting ig{target_ig}."
                    ),
                )
    except Exception:
        del patches[patch_count:]
        seen_sources.clear()
        seen_sources.update(seen_sources_snapshot)
        return


def _node_set_unique_scalar_bindings(
    source: str,
    function: str,
) -> dict[str, _NodeSetScalarBinding]:
    span = find_function(source, function)
    if span is None:
        return {}

    bindings: dict[str, _NodeSetScalarBinding] = {}
    counts: dict[str, int] = {}

    def add_binding(name: str, type_str: str) -> None:
        source_type = _node_set_alias_source_type(type_str)
        normalized_type = _normalize_node_set_scalar_type(source_type)
        if source_type is None or normalized_type is None:
            return
        counts[name] = counts.get(name, 0) + 1
        bindings[name] = _NodeSetScalarBinding(
            source_type=source_type,
            normalized_type=normalized_type,
        )

    extracted = _extract_function_text(source, function)
    if extracted is None:
        return {}
    params_text, _body_text, _line = extracted
    for decl in _parse_params(params_text):
        add_binding(decl.name, decl.type_str)

    stripped = _strip_c_comments(source)
    for stmt_start, stmt_end, _block_id in _iter_node_set_statement_ranges(
        stripped,
        span.body_open + 1,
        span.body_close,
    ):
        decl_parts = _parse_node_set_scalar_decl_source_parts(
            source[stmt_start:stmt_end]
        )
        if decl_parts is None:
            continue
        name, source_type, normalized_type = decl_parts
        counts[name] = counts.get(name, 0) + 1
        bindings[name] = _NodeSetScalarBinding(
            source_type=source_type,
            normalized_type=normalized_type,
        )

    return {
        name: binding
        for name, binding in bindings.items()
        if counts.get(name) == 1
    }


def _parse_node_set_scalar_decl_source_parts(
    statement: str,
) -> tuple[str, str, str] | None:
    text = statement.strip()
    if not text.endswith(";"):
        return None
    left, _sep, _initializer = text[:-1].partition("=")
    if any(ch in left for ch in "[]{}(),"):
        return None
    match = _NODE_SET_SCALAR_DECL_RE.match(left + ";")
    if match is None:
        return None
    source_type = _node_set_alias_source_type(match.group("type"))
    normalized_type = _normalize_node_set_scalar_type(source_type)
    if source_type is None or normalized_type is None:
        return None
    return match.group("name"), source_type, normalized_type


def _node_set_alias_source_type(type_str: str | None) -> str | None:
    source_type = _normalize_alias_binding_type(type_str)
    if source_type is None:
        return None
    tokens = source_type.split()
    if "volatile" in tokens:
        return None
    normalized_type = _normalize_node_set_scalar_type(source_type)
    if normalized_type is None:
        return None
    if normalized_type == "ptr":
        source_type = re.sub(r"\b(?:register|static)\s+", "", source_type)
        source_type = re.sub(r"(?<=\*)\s*const\s*$", "", source_type)
        return source_type.strip() or None
    source_type = " ".join(
        token
        for token in tokens
        if token not in {"const", "register", "static"}
    )
    return source_type or None


def _normalize_alias_binding_type(type_str: str | None) -> str | None:
    source_type = _normalize_safe_binding_type(type_str)
    if source_type is not None:
        return source_type
    if type_str is None:
        return None
    compact = " ".join(type_str.strip().split())
    compact = re.sub(r"\s*\*\s*", "*", compact)
    compact = re.sub(r"(?<=\*)\s*const\s*$", "", compact)
    if compact == type_str:
        return None
    return _normalize_safe_binding_type(compact)


def _node_set_block_declaration_insert_pos(
    source: str,
    function: str,
    block_id: int,
    target_start: int,
) -> int | None:
    span = find_function(source, function)
    if span is None:
        return None

    stripped = _strip_c_comments(source)
    body_start = span.body_open + 1
    body_end = span.body_close
    block_opens = _node_set_block_open_offsets(
        stripped,
        body_start,
        body_end,
        root_open=span.body_open,
    )
    block_open = block_opens.get(block_id)
    if block_open is None:
        return None

    decl_insert = _node_set_block_body_insert_pos(source, block_open)
    saw_statement = False
    target_seen = False
    for stmt_start, stmt_end, stmt_block_id in _iter_node_set_statement_ranges(
        stripped,
        body_start,
        body_end,
    ):
        if stmt_block_id != block_id:
            continue
        decl_parts = _parse_node_set_scalar_decl_parts(
            stripped[stmt_start:stmt_end]
        )
        if decl_parts is not None:
            if saw_statement:
                return None
            if not _node_set_statement_is_full_plain_line(
                source,
                stmt_start,
                stmt_end,
            ):
                return None
            decl_insert = _node_set_line_end(source, stmt_end)
            continue

        saw_statement = True
        if stmt_start == target_start:
            target_seen = True

    if not target_seen:
        return None
    if _node_set_line_start(source, target_start) < decl_insert:
        return None
    return decl_insert


def _node_set_block_open_offsets(
    stripped: str,
    start: int,
    end: int,
    *,
    root_open: int,
) -> dict[int, int]:
    block_stack = [0]
    block_opens = {0: root_open}
    next_block_id = 1
    cursor = start
    while cursor < end:
        while cursor < end and stripped[cursor].isspace():
            cursor += 1
        if cursor >= end:
            break
        if stripped[cursor] == "{":
            block_id = next_block_id
            block_stack.append(block_id)
            block_opens[block_id] = cursor
            next_block_id += 1
            cursor += 1
            continue
        if stripped[cursor] == "}":
            if len(block_stack) > 1:
                block_stack.pop()
            cursor += 1
            continue
        if _node_set_control_starts_at(stripped, cursor):
            cursor = _skip_node_set_control_statement(stripped, cursor, end)
            continue

        statement_end = _find_statement_semicolon(stripped, cursor, end)
        if statement_end is None:
            break
        cursor = statement_end + 1
    return block_opens


def _node_set_block_body_insert_pos(source: str, open_brace: int) -> int:
    pos = open_brace + 1
    while pos < len(source) and source[pos] in " \t\r":
        pos += 1
    if pos < len(source) and source[pos] == "\n":
        pos += 1
    return pos


def _node_set_operand_alias_occurrences(
    source: str,
    record: _SimpleAssignmentRecord,
):
    rhs_span = _node_set_assignment_rhs_span(source, record)
    if rhs_span is None:
        return
    rhs_start, rhs_end = rhs_span
    stripped_rhs = _strip_c_comments(source[rhs_start:rhs_end])
    read_names = set(record.reads)
    for match in re.finditer(r"\b[A-Za-z_][A-Za-z_0-9]*\b", stripped_rhs):
        operand = match.group(0)
        if operand not in read_names:
            continue
        yield operand, rhs_start + match.start(), rhs_start + match.end()


def _build_node_set_operand_alias_source(
    source: str,
    record: _SimpleAssignmentRecord,
    *,
    decl_insert: int,
    operand: str,
    operand_start: int,
    operand_end: int,
    operand_type: str,
    alias_name: str,
) -> str | None:
    if not _node_set_record_starts_on_plain_line(source, record):
        return None
    line_start = _node_set_record_line_start(source, record)
    indent = source[line_start:record.start]
    if indent.strip():
        return None

    decl_line = f"{indent}{operand_type} {alias_name};\n"
    assign_line = f"{indent}{alias_name} = {operand};\n"
    edits = [
        (operand_start, operand_end, alias_name),
        (line_start, line_start, assign_line),
        (decl_insert, decl_insert, decl_line),
    ]
    patched = source
    for edit_start, edit_end, replacement in sorted(
        edits,
        key=lambda item: item[0],
        reverse=True,
    ):
        patched = patched[:edit_start] + replacement + patched[edit_end:]
    return patched


def _node_set_statement_is_full_plain_line(
    source: str,
    start: int,
    end: int,
) -> bool:
    line_start = _node_set_line_start(source, start)
    line_end = _node_set_line_end(source, end)
    return (
        source[line_start:start].strip() == ""
        and source[end:line_end].strip() == ""
    )


def _node_set_line_start(source: str, offset: int) -> int:
    return source.rfind("\n", 0, offset) + 1


def _node_set_line_end(source: str, offset: int) -> int:
    next_line = source.find("\n", offset)
    return len(source) if next_line < 0 else next_line + 1


def _node_set_scalar_type_map(source: str, function: str) -> dict[str, str]:
    span = find_function(source, function)
    if span is None:
        return {}

    types = _node_set_param_scalar_types(source, function)
    stripped = _strip_c_comments(source)
    for stmt_start, stmt_end, _block_id in _iter_node_set_statement_ranges(
        stripped,
        span.body_open + 1,
        span.body_close,
    ):
        decl_parts = _parse_node_set_scalar_decl_parts(
            stripped[stmt_start:stmt_end]
        )
        if decl_parts is None:
            continue
        name, type_name, _initializer = decl_parts
        existing = types.get(name)
        if existing is not None and existing != type_name:
            return {}
        types[name] = type_name
    return types


def _node_set_record_uses_same_safe_scalar_type_class(
    record: _SimpleAssignmentRecord,
    type_map: Mapping[str, str],
    class_id: int,
) -> bool:
    for read_name in record.reads:
        read_type = type_map.get(read_name)
        if read_type is None:
            return False
        if not _same_safe_scalar_type_class(record.lhs_type, read_type, class_id):
            return False
    return True


def _node_set_has_intervening_write(
    source: str,
    start: int,
    end: int,
    names: set[str],
) -> bool:
    if not names or start >= end:
        return False
    stripped = _strip_c_comments(source)
    if _node_set_text_writes_any_name(stripped[start:end], names):
        return True
    for stmt_start, stmt_end, _block_id in _iter_node_set_statement_ranges(
        stripped,
        start,
        end,
    ):
        stmt_text = stripped[stmt_start:stmt_end]
        assignment = _parse_node_set_simple_assignment(stmt_text)
        if assignment is not None and assignment[0] in names:
            return True
        compound_update = _parse_node_set_compound_update(stmt_text)
        if compound_update is not None and compound_update[0] in names:
            return True
        decl_parts = _parse_node_set_scalar_decl_parts(stmt_text)
        if decl_parts is not None:
            name, _type_name, _initializer = decl_parts
            if name in names:
                return True
        if any(
            invalidated_name in names
            for invalidated_name in _node_set_statement_invalidated_names(stmt_text)
        ):
            return True
    return False


def _node_set_text_writes_any_name(text: str, names: set[str]) -> bool:
    if not names:
        return False
    for name in names:
        pattern = re.escape(name)
        watched_lvalue = (
            rf"(?:\(\s*)*"
            rf"(?<![A-Za-z_0-9]){pattern}(?![A-Za-z_0-9])"
            rf"(?:\s*\))*"
        )
        if re.search(
            rf"{watched_lvalue}\s*(?:[+\-*/%&|^]|<<|>>)?=(?!=)",
            text,
        ) is not None:
            return True
        if re.search(
            rf"(?:\+\+|--)\s*{watched_lvalue}",
            text,
        ) is not None:
            return True
        if re.search(
            rf"{watched_lvalue}\s*(?:\+\+|--)",
            text,
        ) is not None:
            return True
        if re.search(
            rf"(?<![A-Za-z_0-9])"
            rf"(?:const\s+|register\s+|static\s+)*"
            rf"(?:struct\s+)?[A-Za-z_][A-Za-z_0-9]*"
            rf"(?:\s+[A-Za-z_][A-Za-z_0-9]*)*"
            rf"(?:\s*\*+\s*)?"
            rf"\s+{pattern}(?![A-Za-z_0-9])"
            rf"\s*(?:[;=,\[])",
            text,
        ) is not None:
            return True
    return False


def _node_set_assignment_chain_occurrences(
    source: str,
    earlier: _SimpleAssignmentRecord,
    later: _SimpleAssignmentRecord,
):
    if not earlier.rhs:
        return
    if not _node_set_rhs_is_arithmetic_chainable(earlier.rhs):
        return
    rhs_span = _node_set_assignment_rhs_span(source, later)
    if rhs_span is None:
        return
    rhs_start, rhs_end = rhs_span
    stripped_rhs = _strip_c_comments(source[rhs_start:rhs_end])
    search_start = 0
    while True:
        rel_start = stripped_rhs.find(earlier.rhs, search_start)
        if rel_start < 0:
            return
        rel_end = rel_start + len(earlier.rhs)
        if _node_set_rhs_occurrence_is_rewritable(
            stripped_rhs,
            rel_start,
            rel_end,
            earlier_rhs=earlier.rhs,
        ):
            yield rhs_start + rel_start, rhs_start + rel_end
        search_start = max(rel_end, rel_start + 1)


def _node_set_assignment_rhs_span(
    source: str,
    record: _SimpleAssignmentRecord,
) -> tuple[int, int] | None:
    equals = source.find("=", record.start + len(record.lhs), record.end)
    semicolon = source.rfind(";", record.start, record.end)
    if equals < 0 or semicolon < 0 or equals >= semicolon:
        return None
    return _trim_span(source, equals + 1, semicolon)


def _node_set_rhs_occurrence_is_rewritable(
    rhs: str,
    start: int,
    end: int,
    *,
    earlier_rhs: str,
) -> bool:
    before_idx = _previous_nonspace_offset(rhs, start - 1)
    after_idx = end
    while after_idx < len(rhs) and rhs[after_idx].isspace():
        after_idx += 1

    if before_idx is not None and rhs[before_idx] in _IDENT_CHARS + ".":
        return False
    if after_idx < len(rhs) and rhs[after_idx] in _IDENT_CHARS + ".":
        return False
    return (
        _node_set_assignment_chain_before_boundary_is_safe(
            rhs,
            before_idx,
            earlier_rhs=earlier_rhs,
        )
        and _node_set_assignment_chain_after_boundary_is_safe(
            rhs, after_idx if after_idx < len(rhs) else None
        )
    )


def _node_set_assignment_chain_before_boundary_is_safe(
    rhs: str,
    boundary: int | None,
    *,
    earlier_rhs: str,
) -> bool:
    if boundary is None:
        return True
    if rhs[boundary] != "+":
        return False
    if _node_set_rhs_has_top_level_additive_operator(earlier_rhs):
        return False
    return _node_set_paren_depth_at(rhs, boundary) == 0


def _node_set_assignment_chain_after_boundary_is_safe(
    rhs: str,
    boundary: int | None,
) -> bool:
    if boundary is None:
        return True
    if rhs[boundary] not in "+-":
        return False
    return _node_set_paren_depth_at(rhs, boundary) == 0


def _node_set_rhs_has_top_level_additive_operator(rhs: str) -> bool:
    for idx, ch in enumerate(rhs):
        if ch in "+-" and _node_set_paren_depth_at(rhs, idx) == 0:
            return True
    return False


def _node_set_paren_depth_at(text: str, offset: int) -> int:
    depth = 0
    for ch in text[:offset]:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
    return depth


def _node_set_prologue_reorder_pairs(
    source: str,
    records: list[_SimpleAssignmentRecord],
    var_name: str,
) -> list[tuple[_SimpleAssignmentRecord, _SimpleAssignmentRecord]]:
    pairs: list[tuple[_SimpleAssignmentRecord, _SimpleAssignmentRecord]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for target_idx, target in enumerate(records):
        if target.lhs != var_name:
            continue
        start_idx = target_idx
        while (
            start_idx > 0
            and _node_set_records_are_adjacent_lines(
                source,
                records[start_idx - 1],
                records[start_idx],
            )
            and records[start_idx - 1].block_id == target.block_id
        ):
            start_idx -= 1
        end_idx = target_idx
        while (
            end_idx + 1 < len(records)
            and _node_set_records_are_adjacent_lines(
                source,
                records[end_idx],
                records[end_idx + 1],
            )
            and records[end_idx + 1].block_id == target.block_id
        ):
            end_idx += 1

        for record_idx in range(start_idx, end_idx):
            first = records[record_idx]
            second = records[record_idx + 1]
            pair_key = (first.start, second.start)
            if pair_key in seen_pairs:
                continue
            if first.block_id != second.block_id:
                continue
            if not _node_set_can_swap_adjacent_assignments(first, second):
                continue
            pairs.append((first, second))
            seen_pairs.add(pair_key)
    return pairs


def _append_block_scope_patches(
    patches: list[CandidatePatch],
    seen_sources: set[str],
    source: str,
    function: str,
    var_name: str,
    target_ig: int,
    class_id: int,
) -> None:
    patch_count = len(patches)
    seen_sources_snapshot = set(seen_sources)
    try:
        records = _simple_assignment_records(source, function, class_id)
        windows = _shortest_node_set_block_scope_windows(
            source,
            records,
            var_name,
        )
        for window_idx, (start_idx, end_idx) in enumerate(windows):
            first = records[start_idx]
            last = records[end_idx]
            patched_source = _wrap_node_set_assignment_window(
                source,
                first,
                last,
            )
            if patched_source is None:
                continue
            candidate_id = (
                f"node-split-block-scope-{var_name}-ig{target_ig}-"
                f"b{first.block_id}-s{first.start}-w{end_idx - start_idx + 1}-"
                f"c{window_idx}"
            )
            _append_unique_patch(
                patches,
                seen_sources,
                source,
                patched_source,
                candidate_id=candidate_id,
                summary=(
                    f"Wrap adjacent simple assignments using {var_name} "
                    f"in a block targeting ig{target_ig}."
                ),
            )
    except Exception:
        del patches[patch_count:]
        seen_sources.clear()
        seen_sources.update(seen_sources_snapshot)
        return


def _node_set_can_swap_adjacent_assignments(
    first: _SimpleAssignmentRecord,
    second: _SimpleAssignmentRecord,
) -> bool:
    if first.lhs == second.lhs:
        return False
    return first.lhs not in second.reads and second.lhs not in first.reads


def _shortest_node_set_block_scope_windows(
    source: str,
    records: list[_SimpleAssignmentRecord],
    var_name: str,
) -> list[tuple[int, int]]:
    best_len: int | None = None
    windows: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for target_idx, target in enumerate(records):
        if target.lhs != var_name:
            continue
        for read_idx, read_record in enumerate(records):
            if read_idx == target_idx or var_name not in read_record.reads:
                continue
            start_idx = min(target_idx, read_idx)
            end_idx = max(target_idx, read_idx)
            window_len = end_idx - start_idx + 1
            if best_len is not None and window_len > best_len:
                continue
            if not _node_set_assignment_window_is_adjacent(
                source,
                records[start_idx:end_idx + 1],
            ):
                continue
            window = (start_idx, end_idx)
            if window in seen:
                continue
            if best_len is None or window_len < best_len:
                best_len = window_len
                windows = []
                seen.clear()
            windows.append(window)
            seen.add(window)
    return windows


def _node_set_assignment_window_is_adjacent(
    source: str,
    records: list[_SimpleAssignmentRecord],
) -> bool:
    if not records:
        return False
    block_id = records[0].block_id
    if any(record.block_id != block_id for record in records):
        return False
    return all(
        _node_set_records_are_adjacent_lines(source, first, second)
        for first, second in zip(records, records[1:])
    )


def _node_set_records_are_adjacent_lines(
    source: str,
    first: _SimpleAssignmentRecord,
    second: _SimpleAssignmentRecord,
) -> bool:
    if not (
        _node_set_record_starts_on_plain_line(source, first)
        and _node_set_record_starts_on_plain_line(source, second)
    ):
        return False
    first_line_start = _node_set_record_line_start(source, first)
    second_line_start = _node_set_record_line_start(source, second)
    if first_line_start == second_line_start:
        return False
    if first.line_end > second_line_start:
        return False
    return source[first.line_end:second_line_start].strip() == ""


def _swap_node_set_assignment_lines(
    source: str,
    first: _SimpleAssignmentRecord,
    second: _SimpleAssignmentRecord,
) -> str | None:
    first_line_start = _node_set_record_line_start(source, first)
    second_line_start = _node_set_record_line_start(source, second)
    if first_line_start == second_line_start or first.line_end > second_line_start:
        return None
    return (
        source[:first_line_start]
        + source[second_line_start:second.line_end]
        + source[first.line_end:second_line_start]
        + source[first_line_start:first.line_end]
        + source[second.line_end:]
    )


def _wrap_node_set_assignment_window(
    source: str,
    first: _SimpleAssignmentRecord,
    last: _SimpleAssignmentRecord,
) -> str | None:
    if not (
        _node_set_record_starts_on_plain_line(source, first)
        and _node_set_record_starts_on_plain_line(source, last)
    ):
        return None
    line_start = _node_set_record_line_start(source, first)
    if line_start > last.line_end:
        return None
    indent = source[line_start:first.start]
    window_source = source[line_start:last.line_end]
    return (
        source[:line_start]
        + indent
        + "{\n"
        + window_source
        + "}\n"
        + source[last.line_end:]
    )


def _node_set_record_line_start(
    source: str,
    record: _SimpleAssignmentRecord,
) -> int:
    return source.rfind("\n", 0, record.start) + 1


def _node_set_record_starts_on_plain_line(
    source: str,
    record: _SimpleAssignmentRecord,
) -> bool:
    line_start = _node_set_record_line_start(source, record)
    return (
        source[line_start:record.start].strip() == ""
        and source[record.end:record.line_end].strip() == ""
    )


def _iter_reassociation_assignments(
    stripped: str,
    source: str,
    function: str,
    var_name: str,
):
    span = find_function(source, function)
    if span is None:
        return
    body_start = span.body_open + 1
    body_end = span.body_close
    for offset in _iter_name_offsets(stripped, var_name, body_start, body_end):
        if _is_member_access_name(stripped, offset):
            continue
        if not _is_plain_assignment_to_name(stripped, var_name, offset, body_start):
            continue
        cursor = offset + len(var_name)
        while cursor < body_end and stripped[cursor].isspace():
            cursor += 1
        if cursor >= body_end or stripped[cursor] != "=":
            continue
        statement_end = _find_statement_semicolon(stripped, cursor + 1, body_end)
        if statement_end is None:
            continue
        split = _split_simple_addition_expression(
            stripped,
            cursor + 1,
            statement_end,
        )
        if split is None:
            continue
        left_span, right_span = split
        left_operand = source[left_span[0]:left_span[1]].strip()
        right_operand = source[right_span[0]:right_span[1]].strip()
        if not left_operand or not right_operand:
            continue
        yield left_span[0], right_span[1], left_operand, right_operand


def _floating_decl_names_for_function(
    source: str,
    function: str,
) -> set[str] | None:
    extracted = _extract_function_text(source, function)
    if extracted is None:
        return None
    params_text, body_text, _line = extracted
    counts: dict[str, int] = {}
    floating: set[str] = set()

    def add_decl(name: str, type_str: str) -> None:
        counts[name] = counts.get(name, 0) + 1
        if _is_floating_scalar_type(type_str):
            floating.add(name)

    for decl in _parse_params(params_text):
        add_decl(decl.name, decl.type_str)
    for type_str, name in _iter_simple_decl_line_types(body_text):
        add_decl(name, type_str)

    ambiguous = {name for name, count in counts.items() if count != 1}
    return {name for name in floating if name not in ambiguous}


def _iter_simple_decl_line_types(body_text: str):
    stripped = _strip_c_comments(body_text)
    for line in stripped.splitlines():
        if any(ch in line for ch in "*[]{},"):
            continue
        match = _SIMPLE_DECL_LINE_RE.match(line)
        if match is None:
            continue
        yield match.group("type"), match.group("name")


def _is_floating_scalar_type(type_str: str) -> bool:
    normalized = " ".join(type_str.replace("*", " * ").split())
    if "*" in normalized:
        return False
    tokens = [
        token for token in normalized.split()
        if token not in {"const", "volatile", "register", "static"}
    ]
    return len(tokens) == 1 and tokens[0] in _FLOATING_SCALAR_TYPES


def _fpr_reassociation_allowed(
    floating_names: set[str] | None,
    var_name: str,
    left_operand: str,
    right_operand: str,
) -> bool:
    if floating_names is None:
        return False
    if _SIMPLE_IDENTIFIER_RE.fullmatch(left_operand) is None:
        return False
    if _SIMPLE_IDENTIFIER_RE.fullmatch(right_operand) is None:
        return False
    return {var_name, left_operand, right_operand}.issubset(floating_names)


def _split_simple_addition_expression(
    stripped: str,
    start: int,
    end: int,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    plus_offsets: list[int] = []
    paren_depth = 0
    bracket_depth = 0
    i = start
    while i < end:
        ch = stripped[i]
        if ch == "(":
            paren_depth += 1
        elif ch == ")" and paren_depth > 0:
            paren_depth -= 1
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]" and bracket_depth > 0:
            bracket_depth -= 1
        elif ch == "+" and paren_depth == 0 and bracket_depth == 0:
            plus_offsets.append(i)
        i += 1

    if len(plus_offsets) != 1:
        return None
    plus = plus_offsets[0]
    left = _trim_span(stripped, start, plus)
    right = _trim_span(stripped, plus + 1, end)
    if left is None or right is None:
        return None
    if not _is_simple_reassociation_operand(stripped[left[0]:left[1]]):
        return None
    if not _is_simple_reassociation_operand(stripped[right[0]:right[1]]):
        return None
    return left, right


def _trim_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    trimmed_start = start
    while trimmed_start < end and text[trimmed_start].isspace():
        trimmed_start += 1
    trimmed_end = end
    while trimmed_end > trimmed_start and text[trimmed_end - 1].isspace():
        trimmed_end -= 1
    if trimmed_start >= trimmed_end:
        return None
    return trimmed_start, trimmed_end


def _is_simple_reassociation_operand(operand: str) -> bool:
    return (
        _SIMPLE_IDENTIFIER_RE.fullmatch(operand) is not None
        or _INTEGER_LITERAL_RE.fullmatch(operand) is not None
    )


def _build_per_loop_rename_source(
    source: str,
    function: str,
    var_name: str,
    target_ig: int,
) -> str | None:
    span = find_function(source, function)
    if span is None:
        return None

    stripped = _strip_c_comments(source)
    body_start = span.body_open + 1
    body_end = span.body_close
    if _takes_address_of_name(stripped, var_name, span.body_open, span.body_close):
        return None
    if _any_loop_control_mentions_name(stripped, var_name, body_start, body_end):
        return None
    if _has_top_level_unbraced_control_statement(stripped, body_start, body_end):
        return None

    accepted_loops: list[_LoopSpan] = []
    for loop in _iter_top_level_loops(stripped, body_start, body_end):
        if not _range_mentions_name(stripped, var_name, loop.body_inner_start, loop.body_inner_end):
            continue
        if _loop_body_has_member_name_mention(
            stripped,
            var_name,
            loop.body_inner_start,
            loop.body_inner_end,
        ):
            return None
        if _loop_body_has_control_flow_name_mention(
            stripped,
            var_name,
            loop.body_inner_start,
            loop.body_inner_end,
        ):
            return None
        if _loop_body_has_nested_name_mention(
            stripped,
            var_name,
            loop.body_inner_start,
            loop.body_inner_end,
        ):
            return None
        first_mention = next(
            _iter_name_offsets(
                stripped,
                var_name,
                loop.body_inner_start,
                loop.body_inner_end,
            ),
            None,
        )
        if first_mention is None:
            continue
        if not _is_plain_assignment_to_name(
            stripped,
            var_name,
            first_mention,
            loop.body_inner_start,
        ):
            return None
        if _assignment_rhs_mentions_name(
            stripped,
            var_name,
            first_mention,
            loop.body_inner_end,
        ):
            return None
        accepted_loops.append(loop)

    if len(accepted_loops) < 2:
        return None

    for previous_loop, next_loop in zip(accepted_loops, accepted_loops[1:]):
        if _range_has_read_of_name(
            stripped,
            var_name,
            previous_loop.body_close + 1,
            next_loop.loop_start,
        ):
            return None

    last_loop_end = accepted_loops[-1].body_close + 1
    if _range_has_read_of_name(stripped, var_name, last_loop_end, body_end):
        return None

    decl = _find_simple_local_decl_for_name(source, function, span, var_name)
    if decl is None:
        return None
    type_str, indent, insert_at = decl

    edits: list[tuple[int, int, str]] = []
    new_decl_lines = []
    for loop_idx, _loop in enumerate(accepted_loops):
        new_decl_lines.append(
            f"{indent}{type_str} {var_name}_loop_{target_ig}_{loop_idx};\n"
        )
    edits.append((insert_at, insert_at, "".join(new_decl_lines)))

    for loop_idx, loop in enumerate(accepted_loops):
        new_name = f"{var_name}_loop_{target_ig}_{loop_idx}"
        for offset in _iter_name_offsets(
            stripped,
            var_name,
            loop.body_inner_start,
            loop.body_inner_end,
        ):
            edits.append((offset, offset + len(var_name), new_name))

    patched = source
    for start, end, replacement in sorted(edits, reverse=True):
        patched = patched[:start] + replacement + patched[end:]
    return patched


def _find_simple_local_decl_for_name(
    source: str,
    function: str,
    span: Any,
    var_name: str,
) -> tuple[str, str, int] | None:
    extracted = _extract_function_text(source, function)
    if extracted is None:
        return None
    _params_text, body_text, _line = extracted
    decls = [decl for decl in walk_local_decls(body_text) if decl.name == var_name]
    if not decls:
        return None
    type_str = decls[0].type_str

    body_start = span.body_open + 1
    body_end = span.body_close
    pos = body_start
    for line in source[body_start:body_end].splitlines(keepends=True):
        line_end = pos + len(line)
        if _line_is_simple_decl_for_name(line, var_name):
            indent = line[: len(line) - len(line.lstrip(" \t"))]
            return type_str, indent, line_end
        pos = line_end
    return None


def _line_is_simple_decl_for_name(line: str, var_name: str) -> bool:
    text = line.strip()
    if not text.endswith(";") or "," in text:
        return False
    if re.match(r"^(?:if|for|while|switch|return)\b", text):
        return False
    return re.match(
        rf"^[A-Za-z_][A-Za-z_0-9\s\*]*\s+\**"
        rf"{re.escape(var_name)}\s*(?:=[^;]*)?;$",
        text,
    ) is not None


def _iter_top_level_loops(
    stripped: str,
    start: int,
    end: int,
) -> list[_LoopSpan]:
    loops: list[_LoopSpan] = []
    depth = 0
    i = start
    while i < end:
        ch = stripped[i]
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and _keyword_at(stripped, i, "for"):
            loop = _parse_for_loop_at(stripped, i, end)
            if loop is not None:
                loops.append(loop)
                i = loop.body_close + 1
                continue
        if depth == 0 and _keyword_at(stripped, i, "while"):
            loop = _parse_while_loop_at(stripped, i, end)
            if loop is not None:
                loops.append(loop)
                i = loop.body_close + 1
                continue
        i += 1
    return loops


def _parse_for_loop_at(stripped: str, start: int, end: int) -> _LoopSpan | None:
    i = start + len("for")
    while i < end and stripped[i].isspace():
        i += 1
    if i >= end or stripped[i] != "(":
        return None
    paren_close = _find_matching_token(stripped, i, "(", ")", end)
    if paren_close is None:
        return None
    body_open = paren_close + 1
    while body_open < end and stripped[body_open].isspace():
        body_open += 1
    if body_open >= end or stripped[body_open] != "{":
        return None
    body_close = _find_matching_token(stripped, body_open, "{", "}", end)
    if body_close is None:
        return None
    return _LoopSpan(
        loop_start=start,
        header_start=i + 1,
        header_end=paren_close,
        body_open=body_open,
        body_close=body_close,
        body_inner_start=body_open + 1,
        body_inner_end=body_close,
    )


def _parse_while_loop_at(stripped: str, start: int, end: int) -> _LoopSpan | None:
    condition = _parse_parenthesized_condition_at(
        stripped,
        start + len("while"),
        end,
    )
    if condition is None:
        return None
    condition_start, condition_end = condition
    body_open = condition_end + 1
    while body_open < end and stripped[body_open].isspace():
        body_open += 1
    if body_open >= end or stripped[body_open] != "{":
        return None
    body_close = _find_matching_token(stripped, body_open, "{", "}", end)
    if body_close is None:
        return None
    return _LoopSpan(
        loop_start=start,
        header_start=condition_start,
        header_end=condition_end,
        body_open=body_open,
        body_close=body_close,
        body_inner_start=body_open + 1,
        body_inner_end=body_close,
    )


def _find_matching_token(
    text: str,
    start: int,
    open_ch: str,
    close_ch: str,
    end: int,
) -> int | None:
    depth = 1
    i = start + 1
    while i < end:
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _keyword_at(text: str, offset: int, keyword: str) -> bool:
    if not text.startswith(keyword, offset):
        return False
    before = text[offset - 1] if offset > 0 else ""
    after_offset = offset + len(keyword)
    after = text[after_offset] if after_offset < len(text) else ""
    return before not in _IDENT_CHARS and after not in _IDENT_CHARS


def _any_loop_control_mentions_name(
    stripped: str,
    var_name: str,
    start: int,
    end: int,
) -> bool:
    i = start
    while i < end:
        if _keyword_at(stripped, i, "for"):
            header = _parse_for_header_at(stripped, i, end)
            if header is not None:
                header_start, header_end = header
                if _range_mentions_name(
                    stripped,
                    var_name,
                    header_start,
                    header_end,
                ):
                    return True
                i = header_end + 1
                continue
        if _keyword_at(stripped, i, "while"):
            condition = _parse_parenthesized_condition_at(
                stripped,
                i + len("while"),
                end,
            )
            if condition is not None:
                condition_start, condition_end = condition
                if _range_mentions_name(
                    stripped,
                    var_name,
                    condition_start,
                    condition_end,
                ):
                    return True
                i = condition_end + 1
                continue
        i += 1
    return False


def _has_top_level_unbraced_control_statement(
    stripped: str,
    start: int,
    end: int,
) -> bool:
    depth = 0
    i = start
    while i < end:
        ch = stripped[i]
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth != 0:
            i += 1
            continue

        control_body_start = _top_level_control_body_start(stripped, i, end)
        if control_body_start is not None:
            if _controlled_statement_is_unbraced(stripped, control_body_start, end):
                return True
            i = control_body_start
            continue
        i += 1
    return False


def _top_level_control_body_start(
    stripped: str,
    offset: int,
    end: int,
) -> int | None:
    if _keyword_at(stripped, offset, "if"):
        condition = _parse_parenthesized_condition_at(
            stripped,
            offset + len("if"),
            end,
        )
        return None if condition is None else condition[1] + 1

    if _keyword_at(stripped, offset, "else"):
        return offset + len("else")

    if _keyword_at(stripped, offset, "for"):
        header = _parse_for_header_at(stripped, offset, end)
        return None if header is None else header[1] + 1

    if _keyword_at(stripped, offset, "while"):
        condition = _parse_parenthesized_condition_at(
            stripped,
            offset + len("while"),
            end,
        )
        return None if condition is None else condition[1] + 1

    if _keyword_at(stripped, offset, "switch"):
        condition = _parse_parenthesized_condition_at(
            stripped,
            offset + len("switch"),
            end,
        )
        return None if condition is None else condition[1] + 1

    if _keyword_at(stripped, offset, "do"):
        return offset + len("do")

    return None


def _controlled_statement_is_unbraced(
    stripped: str,
    start: int,
    end: int,
) -> bool:
    i = start
    while i < end and stripped[i].isspace():
        i += 1
    return i < end and stripped[i] != "{"


def _parse_for_header_at(
    stripped: str,
    start: int,
    end: int,
) -> tuple[int, int] | None:
    i = start + len("for")
    while i < end and stripped[i].isspace():
        i += 1
    if i >= end or stripped[i] != "(":
        return None
    paren_close = _find_matching_token(stripped, i, "(", ")", end)
    if paren_close is None:
        return None
    return i + 1, paren_close


def _parse_parenthesized_condition_at(
    stripped: str,
    start: int,
    end: int,
) -> tuple[int, int] | None:
    i = start
    while i < end and stripped[i].isspace():
        i += 1
    if i >= end or stripped[i] != "(":
        return None
    paren_close = _find_matching_token(stripped, i, "(", ")", end)
    if paren_close is None:
        return None
    return i + 1, paren_close


def _loop_body_has_nested_name_mention(
    stripped: str,
    var_name: str,
    start: int,
    end: int,
) -> bool:
    depth = 0
    mention_offsets = set(_iter_name_offsets(stripped, var_name, start, end))
    i = start
    while i < end:
        if i in mention_offsets and depth > 0:
            return True
        if depth == 0 and _nested_controlled_statement_mentions_name(
            stripped,
            var_name,
            i,
            end,
        ):
            return True
        if _nested_control_header_mentions_name(stripped, var_name, i, end):
            return True
        ch = stripped[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        i += 1
    return False


def _loop_body_has_member_name_mention(
    stripped: str,
    var_name: str,
    start: int,
    end: int,
) -> bool:
    return any(
        _is_member_access_name(stripped, offset)
        for offset in _iter_name_offsets(stripped, var_name, start, end)
    )


def _loop_body_has_control_flow_name_mention(
    stripped: str,
    var_name: str,
    start: int,
    end: int,
) -> bool:
    i = start
    while i < end:
        if _keyword_at(stripped, i, "return") or _keyword_at(stripped, i, "goto"):
            statement_end = _find_statement_semicolon(stripped, i, end)
            if statement_end is None:
                statement_end = end
            if _range_mentions_name(stripped, var_name, i, statement_end):
                return True
            i = statement_end + 1
            continue
        if _is_statement_label_named(stripped, var_name, i, start, end):
            return True
        i += 1
    return False


def _nested_controlled_statement_mentions_name(
    stripped: str,
    var_name: str,
    offset: int,
    end: int,
) -> bool:
    if _keyword_at(stripped, offset, "if"):
        condition = _parse_parenthesized_condition_at(
            stripped,
            offset + len("if"),
            end,
        )
        if condition is None:
            return False
        _condition_start, condition_end = condition
        body = _controlled_statement_span(stripped, condition_end + 1, end)
        return body is not None and _range_mentions_name(
            stripped,
            var_name,
            body[0],
            body[1],
        )

    if _keyword_at(stripped, offset, "else"):
        body = _controlled_statement_span(stripped, offset + len("else"), end)
        return body is not None and _range_mentions_name(
            stripped,
            var_name,
            body[0],
            body[1],
        )

    if _keyword_at(stripped, offset, "for"):
        header = _parse_for_header_at(stripped, offset, end)
        if header is None:
            return False
        _header_start, header_end = header
        body = _controlled_statement_span(stripped, header_end + 1, end)
        return body is not None and _range_mentions_name(
            stripped,
            var_name,
            body[0],
            body[1],
        )

    if _keyword_at(stripped, offset, "while"):
        condition = _parse_parenthesized_condition_at(
            stripped,
            offset + len("while"),
            end,
        )
        if condition is None:
            return False
        _condition_start, condition_end = condition
        body = _controlled_statement_span(stripped, condition_end + 1, end)
        return body is not None and _range_mentions_name(
            stripped,
            var_name,
            body[0],
            body[1],
        )

    if _keyword_at(stripped, offset, "switch"):
        condition = _parse_parenthesized_condition_at(
            stripped,
            offset + len("switch"),
            end,
        )
        if condition is None:
            return False
        _condition_start, condition_end = condition
        body = _controlled_statement_span(stripped, condition_end + 1, end)
        return body is not None and _range_mentions_name(
            stripped,
            var_name,
            body[0],
            body[1],
        )

    if _keyword_at(stripped, offset, "do"):
        body = _controlled_statement_span(stripped, offset + len("do"), end)
        return body is not None and _range_mentions_name(
            stripped,
            var_name,
            body[0],
            body[1],
        )

    return False


def _controlled_statement_span(
    stripped: str,
    start: int,
    end: int,
) -> tuple[int, int] | None:
    i = start
    while i < end and stripped[i].isspace():
        i += 1
    if i >= end:
        return None
    if stripped[i] == "{":
        body_close = _find_matching_token(stripped, i, "{", "}", end)
        if body_close is None:
            return None
        return i + 1, body_close
    statement_end = _find_statement_semicolon(stripped, i, end)
    if statement_end is None:
        return None
    return i, statement_end


def _find_statement_semicolon(stripped: str, start: int, end: int) -> int | None:
    paren_depth = 0
    bracket_depth = 0
    i = start
    while i < end:
        ch = stripped[i]
        if ch == "(":
            paren_depth += 1
        elif ch == ")" and paren_depth > 0:
            paren_depth -= 1
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]" and bracket_depth > 0:
            bracket_depth -= 1
        elif ch == ";" and paren_depth == 0 and bracket_depth == 0:
            return i
        elif ch == "{" and paren_depth == 0 and bracket_depth == 0:
            return i
        elif ch == "}" and paren_depth == 0 and bracket_depth == 0:
            return i
        i += 1
    return None


def _nested_control_header_mentions_name(
    stripped: str,
    var_name: str,
    offset: int,
    end: int,
) -> bool:
    for keyword in ("if", "for", "while", "switch"):
        if not _keyword_at(stripped, offset, keyword):
            continue
        i = offset + len(keyword)
        while i < end and stripped[i].isspace():
            i += 1
        if i >= end or stripped[i] != "(":
            continue
        paren_close = _find_matching_token(stripped, i, "(", ")", end)
        if paren_close is None:
            continue
        return _range_mentions_name(stripped, var_name, i + 1, paren_close)
    return False


def _takes_address_of_name(
    stripped: str,
    var_name: str,
    start: int,
    end: int,
) -> bool:
    cursor = start
    while cursor < end:
        ampersand = stripped.find("&", cursor, end)
        if ampersand < 0:
            return False
        cursor = ampersand + 1
        if ampersand > start and stripped[ampersand - 1] == "&":
            continue
        if cursor < end and stripped[cursor] == "&":
            cursor += 1
            continue
        probe = cursor
        while probe < end and stripped[probe].isspace():
            probe += 1
        while probe < end and stripped[probe] == "(":
            probe += 1
            while probe < end and stripped[probe].isspace():
                probe += 1
        if _name_at(stripped, var_name, probe):
            return True
    return False


def _range_has_read_of_name(
    stripped: str,
    var_name: str,
    start: int,
    end: int,
) -> bool:
    return any(
        not _is_plain_assignment_to_name(stripped, var_name, offset, start)
        for offset in _iter_name_offsets(stripped, var_name, start, end)
    )


def _is_plain_assignment_to_name(
    stripped: str,
    var_name: str,
    offset: int,
    lower_bound: int,
) -> bool:
    cursor = offset + len(var_name)
    while cursor < len(stripped) and stripped[cursor].isspace():
        cursor += 1
    if cursor >= len(stripped) or stripped[cursor] != "=":
        return False
    if cursor + 1 < len(stripped) and stripped[cursor + 1] == "=":
        return False

    previous_boundary = max(
        stripped.rfind(";", lower_bound, offset),
        stripped.rfind("{", lower_bound, offset),
        stripped.rfind("}", lower_bound, offset),
    )
    statement_start = (
        lower_bound if previous_boundary < lower_bound else previous_boundary + 1
    )
    return stripped[statement_start:offset].strip() == ""


def _assignment_rhs_mentions_name(
    stripped: str,
    var_name: str,
    offset: int,
    upper_bound: int,
) -> bool:
    cursor = offset + len(var_name)
    while cursor < upper_bound and stripped[cursor].isspace():
        cursor += 1
    if cursor >= upper_bound or stripped[cursor] != "=":
        return False
    statement_end = stripped.find(";", cursor + 1, upper_bound)
    if statement_end < 0:
        statement_end = upper_bound
    return _range_mentions_name(stripped, var_name, cursor + 1, statement_end)


def _range_mentions_name(
    stripped: str,
    var_name: str,
    start: int,
    end: int,
) -> bool:
    return next(_iter_name_offsets(stripped, var_name, start, end), None) is not None


def _name_at(stripped: str, var_name: str, offset: int) -> bool:
    if not stripped.startswith(var_name, offset):
        return False
    before = stripped[offset - 1] if offset > 0 else ""
    after_offset = offset + len(var_name)
    after = stripped[after_offset] if after_offset < len(stripped) else ""
    return before not in _IDENT_CHARS and after not in _IDENT_CHARS


def _is_member_access_name(stripped: str, offset: int) -> bool:
    previous = _previous_nonspace_offset(stripped, offset - 1)
    if previous is None:
        return False
    if stripped[previous] == ".":
        return True
    if stripped[previous] != ">":
        return False
    before_arrow = _previous_nonspace_offset(stripped, previous - 1)
    return before_arrow is not None and stripped[before_arrow] == "-"


def _is_statement_label_named(
    stripped: str,
    var_name: str,
    offset: int,
    lower_bound: int,
    upper_bound: int,
) -> bool:
    if not _name_at(stripped, var_name, offset):
        return False
    cursor = offset + len(var_name)
    while cursor < upper_bound and stripped[cursor].isspace():
        cursor += 1
    if cursor >= upper_bound or stripped[cursor] != ":":
        return False
    previous = _previous_nonspace_offset(stripped, offset - 1)
    return previous is None or previous < lower_bound or stripped[previous] in ";{}:"


def _previous_nonspace_offset(stripped: str, offset: int) -> int | None:
    cursor = offset
    while cursor >= 0:
        if not stripped[cursor].isspace():
            return cursor
        cursor -= 1
    return None


def _iter_name_offsets(
    stripped: str,
    var_name: str,
    start: int,
    end: int,
):
    pattern = re.compile(_name_pattern(var_name))
    for match in pattern.finditer(stripped, start, end):
        yield match.start()


def _name_pattern(var_name: str) -> str:
    return rf"(?<![A-Za-z_0-9]){re.escape(var_name)}(?![A-Za-z_0-9])"


def _decl_order_candidate_involves_var(
    label: str,
    order: list[int],
    names: list[str],
    var_name: str,
) -> bool:
    if re.search(
        rf"(?<![A-Za-z_0-9]){re.escape(var_name)}(?![A-Za-z_0-9])",
        label,
    ) is not None:
        return True
    try:
        original_index = names.index(var_name)
    except ValueError:
        return False
    try:
        return order.index(original_index) != original_index
    except ValueError:
        return False


def _candidate_id_fragment(label: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9]+", "-", label.strip().lower())
    return fragment.strip("-") or "candidate"


def _patch_hunk(source: str, patched_source: str, candidate_id: str) -> str:
    return "\n".join(difflib.unified_diff(
        source.splitlines(),
        patched_source.splitlines(),
        fromfile="source",
        tofile=candidate_id,
        lineterm="",
    ))


def _register_name_for_class(class_id: Any, reg_num: Any) -> str | None:
    parsed = _as_int(reg_num)
    if parsed is None:
        return None
    parsed_class = _as_int(class_id)
    if parsed_class == 1:
        return f"f{parsed}"
    return f"r{parsed}"


def _first_int(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return _as_int(value[0])
    return _as_int(value)


def _first_str(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and value:
        item = value[0]
        return str(item) if item is not None else None
    return str(value) if value is not None else None


def _source_retained_for_row(
    entry: Any,
    objective: Any,
    diagnostics_path: Any,
) -> str | None:
    if isinstance(entry, Mapping):
        retained = entry.get("source_retained")
        if retained is not None:
            return str(retained)
    if isinstance(objective, Mapping):
        retained = objective.get("source_path")
        if retained is not None:
            return str(retained)
    if diagnostics_path is not None:
        return str(diagnostics_path)
    return None


def _coupled_register_rows(objective: Any) -> list[dict[str, Any]] | None:
    if not isinstance(objective, Mapping):
        return None
    per_ig = objective.get("per_ig")
    if not isinstance(per_ig, list):
        return None
    class_id = objective.get("class_id")
    rows: list[dict[str, Any]] = []
    for item in per_ig:
        if not isinstance(item, Mapping):
            continue
        achieved_reg = _as_int(item.get("assigned_reg"))
        target_reg_num = _first_int(
            item.get("target_reg_num")
            if item.get("target_reg_num") is not None
            else item.get("target_reg_nums")
        )
        rows.append({
            "target_ig": _as_int(item.get("target_ig")),
            "target_reg": _first_str(
                item.get("target_reg")
                if item.get("target_reg") is not None
                else item.get("target_regs")
            ),
            "target_reg_num": target_reg_num,
            "achieved_reg": achieved_reg,
            "achieved_register": _register_name_for_class(class_id, achieved_reg),
            "target_reg_hit": bool(item.get("target_reg_hit")),
        })
    return rows or None


def _score_row(entry: Any) -> dict[str, Any]:
    score = entry.get("score") if isinstance(entry, Mapping) else entry
    objective = (
        entry.get("objective")
        if isinstance(entry, Mapping)
        else getattr(entry, "objective", None)
    )
    candidate_id = (
        entry.get("candidate_id")
        if isinstance(entry, Mapping) and entry.get("candidate_id") is not None
        else getattr(score, "candidate_id", None)
    )
    checkdiff_delta = (
        entry.get("checkdiff_delta")
        if isinstance(entry, Mapping) and entry.get("checkdiff_delta") is not None
        else getattr(score, "checkdiff_delta", None)
    )
    compile_ok = (
        entry.get("compile_ok")
        if isinstance(entry, Mapping) and entry.get("compile_ok") is not None
        else getattr(score, "compile_ok", None)
    )
    diagnostics_path = (
        entry.get("diagnostics_path")
        if isinstance(entry, Mapping) and entry.get("diagnostics_path") is not None
        else getattr(score, "diagnostics_path", None)
    )
    source_retained = _source_retained_for_row(
        entry,
        objective,
        diagnostics_path,
    )
    objective_error = (
        objective.get("error")
        if isinstance(objective, Mapping) and objective.get("error") is not None
        else None
    )
    class_id = objective.get("class_id") if isinstance(objective, Mapping) else None
    achieved_reg = (
        _as_int(objective.get("assigned_reg"))
        if isinstance(objective, Mapping)
        else None
    )
    row = {
        "candidate_id": candidate_id,
        "compile_ok": compile_ok,
        "checkdiff_delta": checkdiff_delta,
        "checkdiff_pct": getattr(score, "checkdiff_pct", None),
        "diagnostics_path": (
            str(diagnostics_path) if diagnostics_path is not None else None
        ),
        "score_reason": getattr(score, "score_reason", None),
        "objective_status": _objective_status(objective),
        "objective_error": str(objective_error) if objective_error is not None else None,
        "objective": dict(objective) if isinstance(objective, Mapping) else objective,
    }
    if source_retained is not None:
        row["source_retained"] = source_retained
    if isinstance(objective, Mapping):
        row["target_ig"] = _as_int(objective.get("target_ig"))
        row["target_reg"] = _first_str(objective.get("target_reg"))
        row["target_reg_num"] = _first_int(objective.get("target_reg_num"))
        row["achieved_reg"] = achieved_reg
        row["achieved_register"] = _register_name_for_class(class_id, achieved_reg)
        coupled_registers = _coupled_register_rows(objective)
        if coupled_registers is not None:
            row["coupled_registers"] = coupled_registers
    return row


def _objective_status(objective: Any) -> str | None:
    if isinstance(objective, Mapping):
        status = objective.get("status")
    else:
        status = getattr(objective, "status", None)
    return str(status) if status is not None else None


def _target_register(entry: Mapping[str, Any]) -> str | None:
    regs = _target_registers(entry)
    if regs:
        return regs[0]
    return None


def _target_registers(entry: Mapping[str, Any]) -> tuple[str, ...]:
    regs: list[str] = []
    desired = entry.get("desired_registers")
    if isinstance(desired, list):
        for value in desired:
            text = _optional_str(value)
            if text is not None and text not in regs:
                regs.append(text)
    fallback = _optional_str(entry.get("target_register") or entry.get("target_reg"))
    if fallback is not None and fallback not in regs:
        regs.append(fallback)
    return tuple(regs)


def _target_reg_names(request: NodeSetSplitRequest) -> tuple[str, ...]:
    names = tuple(request.target_regs or ())
    if names:
        return names
    return (request.target_reg,) if request.target_reg is not None else ()


def _target_reg_numbers(request: NodeSetSplitRequest) -> tuple[int, ...]:
    nums: list[int] = []
    for register in _target_reg_names(request):
        num = _register_number(register)
        if num is not None and num not in nums:
            nums.append(num)
    return tuple(nums)


def _register_number(register: str | None) -> int | None:
    if register is None:
        return None
    match = _REGISTER_RE.match(register)
    if match is None:
        return None
    return int(match.group("num"))


def _is_simple_identifier(value: str | None) -> bool:
    return value is not None and _SIMPLE_IDENTIFIER_RE.match(value) is not None


def _is_field_expression(expression: str | None) -> bool:
    if expression is None:
        return False
    return "->" in expression or re.search(
        r"(?:\b[A-Za-z_][A-Za-z_0-9]*|\]|\))\s*\.",
        expression,
    ) is not None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
