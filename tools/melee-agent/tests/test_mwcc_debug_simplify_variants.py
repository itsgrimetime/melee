"""Unit tests for mwcc_debug simplify-search variant adapters."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.mwcc_debug.simplify_search import FunctionContext
from src.mwcc_debug.simplify_variants import (
    decl_orders_source,
    holder_lifetime_source,
    insert_alias_source,
    type_change_source,
)


def _ctx(tmp_path: Path, source_text: str) -> FunctionContext:
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text(source_text, encoding="utf-8")
    return FunctionContext(
        function="fn_test",
        unit="melee/mn/sample",
        source_path=src,
        melee_root=tmp_path,
    )


# ---------------------------------------------------------------------------
# decl_orders_source
# ---------------------------------------------------------------------------


def test_decl_orders_source_yields_unique_permutations(tmp_path: Path) -> None:
    """For N=3 decls, the adapter generates promote+demote+swap = 6 candidate
    permutations but dedups identical outputs.

    With [a, b, c]: promote-b and swap-a-b both produce [b, a, c]; demote-b
    and swap-b-c both produce [a, c, b]. So 6 candidate permutations collapse
    to 4 distinct outputs. Dedup matters because each surviving variant
    consumes a compile slot.
    """
    source = (
        "void fn_test(void) {\n"
        "    int a;\n"
        "    int b;\n"
        "    int c;\n"
        "    a = b + c;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(decl_orders_source(ctx))

    assert len(variants) == 4
    assert all(v.parent_baseline == ctx.source_path for v in variants)
    # Every variant should have distinct text from the baseline (it's a real
    # mutation), and distinct from each other (dedup invariant).
    assert all(v.text != source for v in variants)
    assert len({v.text for v in variants}) == len(variants)


def test_decl_orders_source_provenance_describes_each_mutation(tmp_path: Path) -> None:
    """Each emitted variant should have a provenance string identifying its
    mutation. With N=2 [x, y], all three candidates (promote y, demote x,
    swap x-y) produce the same permutation [y, x], so dedup keeps only the
    first one seen — the promote variant. Use N=3 to exercise all three
    mutation flavors surviving dedup.
    """
    source = (
        "void fn_test(void) {\n"
        "    int x;\n"
        "    int y;\n"
        "    int z;\n"
        "    x = y + z;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(decl_orders_source(ctx))

    provs = {v.provenance for v in variants}
    # promote variants are emitted first, so at least one promote provenance
    # should survive dedup for non-position-0 names.
    assert any("promote" in p and "y" in p for p in provs)
    assert any("promote" in p and "z" in p for p in provs)
    # demote x produces [y, z, x] which no earlier permutation reaches.
    assert any("demote" in p and "x" in p for p in provs)
    # All emitted provenance strings carry the decl-orders prefix.
    assert all(p.startswith("decl-orders") for p in provs)


def test_decl_orders_source_empty_when_function_has_no_decls(tmp_path: Path) -> None:
    """If a function has no declarations, no variants should be emitted —
    not a crash, just a clean empty iterator.
    """
    source = "void fn_test(void) {\n    return;\n}\n"
    ctx = _ctx(tmp_path, source)

    variants = list(decl_orders_source(ctx))

    assert variants == []


def test_decl_orders_source_empty_when_function_missing(tmp_path: Path) -> None:
    source = "void other_fn(void) {\n    int a;\n}\n"
    ctx = _ctx(tmp_path, source)

    variants = list(decl_orders_source(ctx))

    assert variants == []


def test_decl_orders_source_handles_struct_pointer_initializers(tmp_path: Path) -> None:
    source = (
        "void fn_test(void) {\n"
        "    struct UnkCostumeList* var_r8 = CostumeListsForeachCharacter;\n"
        "    ftData_UnkCountStruct* var_r9 = ftData_Table_Unk0;\n"
        "    ftData_UnkCountStruct* var_r10 = ftData_UnkIntPairs;\n"
        "    int i;\n"
        "    for (i = 0; i < FTKIND_MAX; ++i) {\n"
        "        int costume_idx = 0;\n"
        "        gFtDataList[i] = NULL;\n"
        "    }\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(decl_orders_source(ctx))

    assert variants
    assert any(
        "var_r9 = ftData_Table_Unk0;\n"
        "    struct UnkCostumeList* var_r8 = CostumeListsForeachCharacter;"
        in variant.text
        for variant in variants
    )


def test_decl_orders_source_yields_same_type_group_promotion(tmp_path: Path) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int i;\n"
        "    int guard;\n"
        "    u8 result;\n"
        "    u8 result2;\n"
        "    guard = i;\n"
        "    result = guard;\n"
        "    result2 = result;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(decl_orders_source(ctx))

    assert any(
        variant.provenance == "decl-orders promote-group u8 result+result2"
        and (
            "    u8 result;\n"
            "    u8 result2;\n"
            "    int i;\n"
            "    int guard;\n"
        ) in variant.text
        for variant in variants
    )


# ---------------------------------------------------------------------------
# insert_alias_source
# ---------------------------------------------------------------------------


def test_insert_alias_source_yields_one_variant_per_var_and_read_site(tmp_path: Path) -> None:
    """The adapter iterates over each local var, and for each, attempts to
    insert an alias at each supported reading-use site. Variables with no
    reading uses (only writes/decls) are skipped.
    """
    source = (
        "void fn_test(void) {\n"
        "    int a;\n"
        "    int b;\n"
        "    int c;\n"
        "    a = 1;\n"
        "    b = a + 1;\n"
        "    c = b + a;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(insert_alias_source(ctx))

    # `a` is read in `b = a + 1`. `b` is read in `c = b + a`.
    # `c` is never read => no alias possible. We expect at least 2.
    assert len(variants) >= 2
    provs = {v.provenance for v in variants}
    assert "insert-alias a@0" in provs
    assert "insert-alias a@1" in provs
    assert "insert-alias b@0" in provs
    # All variants share the same parent baseline path.
    assert all(v.parent_baseline == ctx.source_path for v in variants)


def test_insert_alias_source_skips_variables_with_no_reads(tmp_path: Path) -> None:
    """Variables that are only written (never read after declaration) can't
    be aliased — the mutator raises MutationUnsupported, which the adapter
    should swallow rather than propagate.
    """
    source = (
        "void fn_test(void) {\n"
        "    int unused;\n"
        "    unused = 1;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(insert_alias_source(ctx))

    # No reading uses of `unused` -> no alias variants.
    assert variants == []


# ---------------------------------------------------------------------------
# holder_lifetime_source
# ---------------------------------------------------------------------------


def test_holder_lifetime_source_yields_variants_after_read_sites(tmp_path: Path) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int holder;\n"
        "    int other;\n"
        "    holder = 1;\n"
        "    other = holder + 2;\n"
        "    other += 3;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(holder_lifetime_source(ctx))

    provs = {v.provenance for v in variants}
    assert "holder-lifetime holder@0" in provs
    variant = next(v for v in variants if v.provenance == "holder-lifetime holder@0")
    assert "volatile int holder_lifetime_sink_0;" in variant.text
    assert (
        "    other = holder + 2;\n"
        "    holder_lifetime_sink_0 = holder;\n"
        "    other += 3;"
    ) in variant.text
    assert variant.parent_baseline == ctx.source_path


def test_holder_lifetime_source_skips_variables_with_no_reads(tmp_path: Path) -> None:
    source = (
        "void fn_test(void) {\n"
        "    int unused;\n"
        "    unused = 1;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(holder_lifetime_source(ctx))

    assert variants == []


# ---------------------------------------------------------------------------
# type_change_source
# ---------------------------------------------------------------------------


def test_type_change_source_explores_alternate_signed_types(tmp_path: Path) -> None:
    """For each local var of an int-like type, propose alternates (s32<->u32,
    s8<->u8, etc.). Other types are left alone.
    """
    source = (
        "void fn_test(void) {\n"
        "    s32 a;\n"
        "    HSD_GObj* obj;\n"
        "    a = 1;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(type_change_source(ctx))

    # `a` is s32 -> at least one variant (u32) should be proposed.
    # `obj` is a pointer -> not an int-like type, no variants.
    assert len(variants) >= 1
    provs = {v.provenance for v in variants}
    assert any("a" in p for p in provs)
    # The variant text should contain the alternative type.
    assert any("u32" in v.text for v in variants)


def test_type_change_source_yields_nothing_when_no_int_locals(tmp_path: Path) -> None:
    source = (
        "void fn_test(void) {\n"
        "    HSD_GObj* obj;\n"
        "    obj = 0;\n"
        "}\n"
    )
    ctx = _ctx(tmp_path, source)

    variants = list(type_change_source(ctx))

    assert variants == []
