"""Unit tests for the permuter_source variant adapter.

The permuter_source adapter harvests pre-existing decomp-permuter output
dirs and yields each ``output-*/source.c`` as a SourceVariant. This MVP
does NOT launch permuter — the user runs permuter separately, and the
adapter walks whatever output is already on disk.

Tests cover:
  - Empty / missing perm dirs (silent no-op, never crashes)
  - Single + multiple output dirs (deterministic order)
  - Missing source.c per-dir (skipped without aborting the rest)
  - --permuter-dir override
  - Auto-resolution via the standard ``<perm_root>/nonmatchings/<fn>/`` layout
  - Provenance shape (parseable, includes the output-NNNN-N name)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.mwcc_debug.simplify_search import FunctionContext
from src.mwcc_debug.simplify_variants_permuter import (
    permuter_source,
    resolve_permuter_function_dir,
)


def _ctx(tmp_path: Path) -> FunctionContext:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text(
        "void fn_test(void) {\n    int a;\n    a = 1;\n}\n",
        encoding="utf-8",
    )
    return FunctionContext(
        function="fn_test",
        unit="melee/mn/sample",
        source_path=src,
        melee_root=tmp_path,
    )


# ---------------------------------------------------------------------------
# Harvest path — explicit perm_dir_override
# ---------------------------------------------------------------------------


def test_permuter_source_yields_nothing_when_dir_missing(tmp_path: Path) -> None:
    """Pointing at a non-existent dir should be a no-op, not a crash.

    The adapter is meant to be cheap to include in every search; if the
    user hasn't run permuter for this function, we just want zero
    variants rather than an exception."""
    ctx = _ctx(tmp_path)
    perm_dir = tmp_path / "no" / "such" / "dir"

    variants = list(permuter_source(ctx, perm_dir_override=perm_dir))

    assert variants == []


def test_permuter_source_yields_nothing_for_empty_dir(tmp_path: Path) -> None:
    """A perm dir that exists but contains no output-* subdirs yields []."""
    ctx = _ctx(tmp_path)
    perm_dir = tmp_path / "permdir"
    perm_dir.mkdir()

    variants = list(permuter_source(ctx, perm_dir_override=perm_dir))

    assert variants == []


def test_permuter_source_yields_single_variant(tmp_path: Path) -> None:
    """One output-NNNN-N/source.c → one SourceVariant."""
    ctx = _ctx(tmp_path)
    perm_dir = tmp_path / "permdir"
    output = perm_dir / "output-0001-0"
    output.mkdir(parents=True)
    src_content = "void fn_test(void) {\n    int x;\n    x = 1;\n}\n"
    (output / "source.c").write_text(src_content, encoding="utf-8")

    variants = list(permuter_source(ctx, perm_dir_override=perm_dir))

    assert len(variants) == 1
    v = variants[0]
    assert v.text == src_content
    assert v.parent_baseline == ctx.source_path
    assert "output-0001-0" in v.provenance
    # Provenance string should start with the "permuter" prefix so callers
    # can tell at a glance which adapter produced it.
    assert v.provenance.startswith("permuter ")


def test_permuter_source_yields_in_deterministic_sorted_order(
    tmp_path: Path,
) -> None:
    """Multiple output dirs are emitted in lexicographic order.

    Determinism matters for reproducible search runs: re-running on the
    same dir layout must compile the same candidates in the same order.
    Permuter's output- names sort naturally (output-0001-0 < output-0002-0
    < ...), so plain sorted() on the dir name is enough."""
    ctx = _ctx(tmp_path)
    perm_dir = tmp_path / "permdir"
    # Create out-of-lexicographic-order to make sure the adapter sorts.
    for i, name in enumerate(["output-0010-0", "output-0001-0", "output-0005-1"]):
        out = perm_dir / name
        out.mkdir(parents=True)
        (out / "source.c").write_text(
            f"// candidate {i}\nvoid fn_test(void) {{ int v{i}; }}\n",
            encoding="utf-8",
        )

    variants = list(permuter_source(ctx, perm_dir_override=perm_dir))

    assert len(variants) == 3
    provs = [v.provenance for v in variants]
    # Sorted by dir name lexicographically.
    assert provs == [
        next(p for p in provs if "output-0001-0" in p),
        next(p for p in provs if "output-0005-1" in p),
        next(p for p in provs if "output-0010-0" in p),
    ]


def test_permuter_source_skips_output_dirs_without_source_c(
    tmp_path: Path,
) -> None:
    """If an output-NNNN-N dir exists but its source.c is missing,
    that one is skipped — but the others still come through.

    Permuter occasionally fails mid-write and leaves a half-baked
    output dir; we shouldn't let one bad apple abort the whole harvest."""
    ctx = _ctx(tmp_path)
    perm_dir = tmp_path / "permdir"

    good = perm_dir / "output-0001-0"
    good.mkdir(parents=True)
    (good / "source.c").write_text("void fn_test(void) { int g; }\n", encoding="utf-8")

    bad = perm_dir / "output-0002-0"
    bad.mkdir(parents=True)
    # No source.c — just a leftover stderr.txt.
    (bad / "stderr.txt").write_text("permuter crashed", encoding="utf-8")

    also_good = perm_dir / "output-0003-0"
    also_good.mkdir(parents=True)
    (also_good / "source.c").write_text("void fn_test(void) { int g2; }\n", encoding="utf-8")

    variants = list(permuter_source(ctx, perm_dir_override=perm_dir))

    assert len(variants) == 2
    assert all("output-0001-0" in v.provenance or "output-0003-0" in v.provenance
               for v in variants)


def test_permuter_source_skips_non_directory_entries(tmp_path: Path) -> None:
    """Stray files (not dirs) named like output-* are ignored.

    A user might accidentally drop a .tar.gz next to the output dirs;
    we glob for output-*/source.c so non-dir entries are filtered
    automatically — but check explicitly here so regressions are caught."""
    ctx = _ctx(tmp_path)
    perm_dir = tmp_path / "permdir"
    perm_dir.mkdir()
    # Stray file named like an output dir but actually a regular file.
    (perm_dir / "output-bogus").write_text("not a dir", encoding="utf-8")
    # And a real output dir with a source.c.
    real = perm_dir / "output-0001-0"
    real.mkdir()
    (real / "source.c").write_text("void fn_test(void) {}\n", encoding="utf-8")

    variants = list(permuter_source(ctx, perm_dir_override=perm_dir))

    assert len(variants) == 1
    assert "output-0001-0" in variants[0].provenance


def test_permuter_source_handles_unusual_output_dir_names(tmp_path: Path) -> None:
    """The adapter should match any `output-*` shape, not just the canonical
    output-NNNN-N format. Permuter has shipped multiple suffix schemes;
    the only invariant is the `output-` prefix and a `source.c` inside."""
    ctx = _ctx(tmp_path)
    perm_dir = tmp_path / "permdir"
    for name in ["output-abc", "output-1-2-3", "output-final"]:
        out = perm_dir / name
        out.mkdir(parents=True)
        (out / "source.c").write_text(f"// {name}\n", encoding="utf-8")

    variants = list(permuter_source(ctx, perm_dir_override=perm_dir))

    assert len(variants) == 3


# ---------------------------------------------------------------------------
# Auto-resolve path
# ---------------------------------------------------------------------------


def test_resolve_permuter_function_dir_default_layout(tmp_path: Path) -> None:
    """The helper should resolve to <perm_root>/nonmatchings/<fn>/.

    Uses the env var override that mirrors permute_with_mwcc.py — keeps
    the helper testable without touching $HOME."""
    perm_root = tmp_path / "decomp-permuter"
    fn_dir = perm_root / "nonmatchings" / "fn_test"
    fn_dir.mkdir(parents=True)

    resolved = resolve_permuter_function_dir(
        "fn_test", perm_root=perm_root,
    )

    assert resolved == fn_dir


def test_resolve_permuter_function_dir_returns_none_when_missing(
    tmp_path: Path,
) -> None:
    """If the function dir doesn't exist under the perm root, return None
    so the caller can decide whether to warn (CLI does) or ignore
    (adapter does)."""
    perm_root = tmp_path / "decomp-permuter"
    perm_root.mkdir()  # exists but has no nonmatchings/

    resolved = resolve_permuter_function_dir(
        "fn_test", perm_root=perm_root,
    )

    assert resolved is None


def test_permuter_source_auto_resolves_when_no_override(tmp_path: Path) -> None:
    """When perm_dir_override is None, the adapter auto-resolves via
    <perm_root>/nonmatchings/<fn>/."""
    ctx = _ctx(tmp_path)
    perm_root = tmp_path / "decomp-permuter"
    fn_dir = perm_root / "nonmatchings" / "fn_test"
    out = fn_dir / "output-0001-0"
    out.mkdir(parents=True)
    (out / "source.c").write_text("void fn_test(void) { int auto_; }\n", encoding="utf-8")

    variants = list(permuter_source(ctx, perm_root=perm_root))

    assert len(variants) == 1
    assert "output-0001-0" in variants[0].provenance


def test_permuter_source_auto_resolve_missing_dir_yields_empty(
    tmp_path: Path,
) -> None:
    """If perm_root has no nonmatchings/<fn>/, return [] without error."""
    ctx = _ctx(tmp_path)
    perm_root = tmp_path / "decomp-permuter"
    perm_root.mkdir()

    variants = list(permuter_source(ctx, perm_root=perm_root))

    assert variants == []


# ---------------------------------------------------------------------------
# Search integration — confirm permuter outputs dedup against decl-orders
# ---------------------------------------------------------------------------


def test_search_dedups_permuter_output_matching_decl_orders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a permuter output is byte-identical to a decl-orders output,
    only one compile slot should be consumed (cross-source dedup).

    The search driver dedups on `variant.text`. Adding permuter_source
    must not change that invariant — confirms our adapter integrates
    cleanly rather than shadowing the existing dedup."""
    from src.mwcc_debug.simplify_search import (
        BaselineSignature,
        SearchResult,
        search,
    )
    from src.mwcc_debug import simplify_search

    # Build a source with two simple decls so decl_orders_source produces
    # a deterministic swap variant.
    source = (
        "void fn_test(void) {\n"
        "    int a;\n"
        "    int b;\n"
        "    a = b + 1;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path)
    ctx.source_path.write_text(source, encoding="utf-8")

    # Run decl_orders to figure out what text the swap variant produces;
    # we'll stage that exact text as a permuter output too.
    from src.mwcc_debug.simplify_variants import decl_orders_source
    decl_variants = list(decl_orders_source(ctx))
    assert decl_variants, "need at least one decl-orders variant to dedup against"
    duplicate_text = decl_variants[0].text

    perm_dir = tmp_path / "permdir"
    out = perm_dir / "output-0001-0"
    out.mkdir(parents=True)
    (out / "source.c").write_text(duplicate_text, encoding="utf-8")

    # Stub compile so we count how many distinct texts the driver sends.
    seen_compiles: list[str] = []

    fake_pcdump = (
        "Starting function fn_test\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)\n"
        "iter ig_idx assigned degree n_interferers flags\n"
        "  0  32  r30  0  0  0x0\n"
        "[COALESCE] enter class=0 n_virtuals=40\n"
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)\n"
        "iter ig_idx degree array_size flags\n"
        "  0  32  1  1  0x0\n"
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        # Persist the text the driver actually staged.
        seen_compiles.append(Path(diff_input.path).read_text(encoding="utf-8"))
        return fake_pcdump

    monkeypatch.setattr(simplify_search, "compile_source_variant", fake_compile)

    baseline = BaselineSignature(
        interference_edges=frozenset(),
        coalesce_mappings=frozenset(),
        spill_set=frozenset(),
        simplify_order=(32,),
    )

    def perm_only(ctx_):
        return permuter_source(ctx_, perm_dir_override=perm_dir)

    result = search(
        sources=[decl_orders_source, perm_only],
        ctx=ctx,
        baseline=baseline,
        target=(99,),
        class_id=0,
        max_candidates=100,
        timeout=30,
    )

    # The duplicate_text should only appear once across all compile calls.
    duplicates = [t for t in seen_compiles if t == duplicate_text]
    assert len(duplicates) == 1, (
        f"expected exactly one compile of the duplicated text; "
        f"got {len(duplicates)}"
    )
