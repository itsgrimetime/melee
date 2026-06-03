"""Variant-source adapters for `simplify_search.search()`.

Each adapter wraps an existing source-mutation primitive into the
`VariantSource` interface: a callable that takes a `FunctionContext` and
yields `SourceVariant`s. The MVP ships three adapters:

- `decl_orders_source`: declaration reorderings (promote/demote/swap).
- `insert_alias_source`: insert an alias before the first reading-use of
  each local.
- `type_change_source`: try signedness flips for int-like locals.

Each adapter is fail-soft: if the underlying mutator raises (variable not
found, ambiguous match, etc.), the adapter swallows the error and moves on
to the next candidate rather than aborting the whole search.

Adding a permuter-backed adapter is the natural next step — it follows the
same `(ctx) -> Iterable[SourceVariant]` shape and plugs into `search()`
without touching the driver. Returning a precomputed `list[SourceVariant]`
is fine too; the driver only needs an iterable.
"""

from __future__ import annotations

from typing import Iterator

from .mutators import (
    MutationUnsupported,
    mutate_insert_alias_before_use,
    mutate_type_change,
)
from .simplify_search import FunctionContext, SourceVariant
from .source_patch import get_decl_names_by_scope, reorder_decls_in_function_scope
from .symbol_bridge import _extract_function_text, walk_local_decls


# ---------------------------------------------------------------------------
# decl_orders_source
# ---------------------------------------------------------------------------


def decl_orders_source(ctx: FunctionContext) -> Iterator[SourceVariant]:
    """Yield declaration-order variants (promote/demote/swap).

    Wraps the same primitives as `debug mutate decl-orders --strategy all`
    but as a library call so the search driver doesn't need to subprocess
    the CLI. Variants where the reorder doesn't actually change the source
    are silently skipped (so we don't waste a compile slot on a no-op).
    """
    source_text = ctx.source_path.read_text(encoding="utf-8")
    scope_map = get_decl_names_by_scope(source_text, ctx.function)
    selected_scope = (ctx.function,)
    if not scope_map.get(selected_scope):
        nested_scopes = [
            scope_path
            for scope_path, scope_names in scope_map.items()
            if scope_path != (ctx.function,) and len(scope_names) >= 2
        ]
        if not nested_scopes:
            nested_scopes = [
                scope_path
                for scope_path in scope_map
                if scope_path != (ctx.function,)
            ]
        if nested_scopes:
            selected_scope = nested_scopes[0]
    names = scope_map.get(selected_scope)
    if not names:
        return
    n = len(names)
    if n < 2:
        return

    candidates: list[tuple[str, list[int]]] = []
    # promote: each non-zero index to the front.
    for k in range(1, n):
        perm = [k] + [i for i in range(n) if i != k]
        candidates.append((f"decl-orders promote {names[k]}", perm))
    # demote: each non-last index to the end.
    for k in range(n - 1):
        perm = [i for i in range(n) if i != k] + [k]
        candidates.append((f"decl-orders demote {names[k]}", perm))
    # swap: adjacent pair swaps.
    for k in range(n - 1):
        perm = list(range(n))
        perm[k], perm[k + 1] = perm[k + 1], perm[k]
        candidates.append(
            (f"decl-orders swap {names[k]} <-> {names[k + 1]}", perm),
        )

    seen_texts: set[str] = set()
    for label, perm in candidates:
        try:
            patched = reorder_decls_in_function_scope(
                source_text,
                ctx.function,
                selected_scope,
                perm,
            )
        except Exception:
            # Reorder helper returns None on bad inputs; we also defensively
            # swallow any unexpected exception so one bad permutation can't
            # poison the rest of the search.
            continue
        if patched is None or patched == source_text or patched in seen_texts:
            continue
        seen_texts.add(patched)
        yield SourceVariant(
            text=patched,
            provenance=label,
            parent_baseline=ctx.source_path,
        )


# ---------------------------------------------------------------------------
# insert_alias_source
# ---------------------------------------------------------------------------


def insert_alias_source(ctx: FunctionContext) -> Iterator[SourceVariant]:
    """Yield alias-insertion variants for each local that has a reading use.

    For each local, try inserting an alias at the first reading use
    (`at_stmt_index=0`). Variables that have no reading uses, that can't
    be unambiguously located, or that look like struct fields are skipped
    via `MutationUnsupported`.
    """
    source_text = ctx.source_path.read_text(encoding="utf-8")
    extracted = _extract_function_text(source_text, ctx.function)
    if extracted is None:
        return
    _params, body_text, _line = extracted
    locals_ = walk_local_decls(body_text)

    seen_texts: set[str] = set()
    for decl in locals_:
        try:
            patched = mutate_insert_alias_before_use(
                source_text,
                ctx.function,
                decl.name,
                at_stmt_index=0,
            )
        except MutationUnsupported:
            continue
        except Exception:
            continue
        if patched == source_text or patched in seen_texts:
            continue
        seen_texts.add(patched)
        yield SourceVariant(
            text=patched,
            provenance=f"insert-alias {decl.name}@0",
            parent_baseline=ctx.source_path,
        )


# ---------------------------------------------------------------------------
# type_change_source
# ---------------------------------------------------------------------------


# Pairs of (from_type, to_type) the adapter will try for any local matching
# the `from_type` exactly. Limited to the signed/unsigned flips that show
# up most often in the matching-shop-floor literature; expand as needed.
_TYPE_FLIPS: list[tuple[str, str]] = [
    ("s32", "u32"),
    ("u32", "s32"),
    ("s16", "u16"),
    ("u16", "s16"),
    ("s8", "u8"),
    ("u8", "s8"),
    ("int", "unsigned int"),
    ("unsigned int", "int"),
]


def type_change_source(ctx: FunctionContext) -> Iterator[SourceVariant]:
    """Yield type-change variants for int-like locals (s32 <-> u32, etc.).

    Each variant flips one local's type to its signed/unsigned counterpart.
    Pointer locals and structured types are left alone — those changes
    rarely preserve the precolor shape.
    """
    source_text = ctx.source_path.read_text(encoding="utf-8")
    extracted = _extract_function_text(source_text, ctx.function)
    if extracted is None:
        return
    _params, body_text, _line = extracted
    locals_ = walk_local_decls(body_text)

    seen_texts: set[str] = set()
    for decl in locals_:
        for from_type, to_type in _TYPE_FLIPS:
            if decl.type_str != from_type:
                continue
            try:
                patched = mutate_type_change(
                    source_text,
                    ctx.function,
                    decl.name,
                    to_type,
                )
            except MutationUnsupported:
                continue
            except Exception:
                continue
            if patched == source_text or patched in seen_texts:
                continue
            seen_texts.add(patched)
            yield SourceVariant(
                text=patched,
                provenance=f"type-change {decl.name}: {from_type}->{to_type}",
                parent_baseline=ctx.source_path,
            )
