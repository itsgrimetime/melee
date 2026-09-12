from src.inline_leverage.deinline import build_deinline_patch
from src.inline_leverage.detect import (
    find_call_sites,
    parse_inline_defs,
    resolve_inline_defs,
)


SOURCE = """
static inline f32 framef(HSD_JObj* jobj) {
    return mn_frame(jobj);
}

static inline void setpos(Foo* p, s32 x) {
    p->a = x;
    p->b = x + 1;
}

void target(HSD_JObj* jobj, Foo* foo, s32 x) {
    f32 y = framef(jobj);
    setpos(foo, x);
}
"""

SCALAR_MULTI_SOURCE = """
static inline int sum_name_kos(u8 field_index) {
    int total;
    int j;
    total = 0;
    for (j = total; j < 0x78; j++) {
        if (GetNameText(j & 0xFF)) {
            total += GetPersistentNameData(field_index)->vs_kos[(u8) j];
        }
    }
    return total;
}

void target(u32* tp, int n) {
    *tp = sum_name_kos(n & 0xFF);
}
"""


def test_detects_inline_defs_and_calls() -> None:
    defs = {item.name: item for item in parse_inline_defs(SOURCE, "u.c")}

    assert set(defs) == {"framef", "setpos"}
    assert defs["framef"].return_class == "scalar"
    assert defs["framef"].body_kind == "single_return_expr"
    assert defs["framef"].params == [("HSD_JObj*", "jobj")]
    assert defs["setpos"].return_class == "void"
    assert defs["setpos"].body_kind == "multi_statement"
    assert defs["setpos"].params == [("Foo*", "p"), ("s32", "x")]

    calls = find_call_sites(SOURCE, "target", "framef")
    assert len(calls) == 1
    assert calls[0].args == ["jobj"]


def test_value_expr_deinline_replaces_call_expression() -> None:
    defs = {item.name: item for item in parse_inline_defs(SOURCE, "u.c")}
    calls = find_call_sites(SOURCE, "target", "framef")

    result = build_deinline_patch(SOURCE, "target", defs["framef"], calls)

    assert result.ok
    assert result.expansion_form == "value_expr"
    assert "f32 y = (mn_frame(jobj));" in (result.new_source or "")


def test_statement_splice_deinline_replaces_standalone_call() -> None:
    defs = {item.name: item for item in parse_inline_defs(SOURCE, "u.c")}
    calls = find_call_sites(SOURCE, "target", "setpos")

    result = build_deinline_patch(SOURCE, "target", defs["setpos"], calls)

    assert result.ok
    assert result.expansion_form == "statement_splice"
    assert "foo->a = x;" in (result.new_source or "")
    assert "foo->b = x + 1;" in (result.new_source or "")


def test_void_statement_splice_materializes_duplicated_nontrivial_argument() -> None:
    source = SOURCE.replace(
        "setpos(foo, x);",
        "setpos(foo, x + 1);",
    )
    defs = {item.name: item for item in parse_inline_defs(source, "u.c")}
    calls = find_call_sites(source, "target", "setpos")

    result = build_deinline_patch(source, "target", defs["setpos"], calls)

    new_source = result.new_source or ""
    assert result.ok
    assert result.expansion_form == "statement_splice"
    assert "s32 inline_x_arg = x + 1;" in new_source
    assert "foo->a = inline_x_arg;" in new_source
    assert "foo->b = inline_x_arg + 1;" in new_source
    assert "setpos(foo, x + 1);" not in new_source


def test_void_statement_splice_ignores_matching_field_names_for_duplication() -> None:
    source = """
static inline void setx(JObj* jobj, f32 x) {
    jobj->translate.x = x;
    HSD_JObjSetMtxDirtySub(jobj);
}

void target(JObj* jobj, JObj* row0) {
    setx(jobj, HSD_JObjGetTranslationX(row0) + 1.0f);
}
"""
    defs = {item.name: item for item in parse_inline_defs(source, "u.c")}
    calls = find_call_sites(source, "target", "setx")

    result = build_deinline_patch(source, "target", defs["setx"], calls)

    new_source = result.new_source or ""
    assert result.ok
    assert result.expansion_form == "statement_splice"
    assert "inline_x_arg" not in new_source
    assert "jobj->translate.x = HSD_JObjGetTranslationX(row0) + 1.0f;" in new_source
    assert "HSD_JObjSetMtxDirtySub(jobj);" in new_source
    assert "setx(jobj, HSD_JObjGetTranslationX(row0) + 1.0f);" not in new_source


def test_scalar_multi_statement_deinline_replaces_assignment_rhs() -> None:
    defs = {item.name: item for item in parse_inline_defs(SCALAR_MULTI_SOURCE, "u.c")}
    calls = find_call_sites(SCALAR_MULTI_SOURCE, "target", "sum_name_kos")

    assert defs["sum_name_kos"].return_class == "scalar"
    assert defs["sum_name_kos"].body_kind == "multi_statement"
    assert defs["sum_name_kos"].n_statements == 7
    assert len(calls) == 1
    assert calls[0].args == ["n & 0xFF"]

    result = build_deinline_patch(
        SCALAR_MULTI_SOURCE,
        "target",
        defs["sum_name_kos"],
        calls,
    )

    new_source = result.new_source or ""
    assert result.ok
    assert result.expansion_form == "scalar_assignment_splice"
    assert "GetPersistentNameData(n & 0xFF)->vs_kos[(u8) j]" in new_source
    assert "*tp = total;" in new_source
    assert "*tp = sum_name_kos(n & 0xFF);" not in new_source


def test_deinline_rejects_non_standalone_void_call() -> None:
    source = SOURCE.replace("setpos(foo, x);", "if (setpos(foo, x)) {}")
    defs = {item.name: item for item in parse_inline_defs(source, "u.c")}
    calls = find_call_sites(source, "target", "setpos")

    result = build_deinline_patch(source, "target", defs["setpos"], calls)

    assert not result.ok
    assert result.unsupported_reason == "void inline call is not a standalone statement"


def test_scalar_multi_statement_rejects_multiple_returns() -> None:
    source = SCALAR_MULTI_SOURCE.replace(
        "total = 0;",
        "if (field_index == 0) { return 0; }\n    total = 0;",
    )
    defs = {item.name: item for item in parse_inline_defs(source, "u.c")}
    calls = find_call_sites(source, "target", "sum_name_kos")

    result = build_deinline_patch(source, "target", defs["sum_name_kos"], calls)

    assert not result.ok
    assert result.unsupported_reason == "scalar multi-statement inline has multiple returns"


def test_scalar_multi_statement_rejects_non_return_local() -> None:
    source = SCALAR_MULTI_SOURCE.replace("return total;", "return total + 1;")
    defs = {item.name: item for item in parse_inline_defs(source, "u.c")}
    calls = find_call_sites(source, "target", "sum_name_kos")

    result = build_deinline_patch(source, "target", defs["sum_name_kos"], calls)

    assert not result.ok
    assert (
        result.unsupported_reason
        == "scalar multi-statement inline does not end in return-local"
    )


def test_scalar_multi_statement_rejects_nested_expression_call() -> None:
    source = SCALAR_MULTI_SOURCE.replace(
        "*tp = sum_name_kos(n & 0xFF);",
        "*tp = sum_name_kos(n & 0xFF) + 1;",
    )
    defs = {item.name: item for item in parse_inline_defs(source, "u.c")}
    calls = find_call_sites(source, "target", "sum_name_kos")

    result = build_deinline_patch(source, "target", defs["sum_name_kos"], calls)

    assert not result.ok
    assert (
        result.unsupported_reason
        == "scalar multi-statement call is not whole assignment RHS"
    )


def test_scalar_multi_statement_rejects_declaration_initializer() -> None:
    source = SCALAR_MULTI_SOURCE.replace(
        "*tp = sum_name_kos(n & 0xFF);",
        "int total = sum_name_kos(n & 0xFF);",
    )
    defs = {item.name: item for item in parse_inline_defs(source, "u.c")}
    calls = find_call_sites(source, "target", "sum_name_kos")

    result = build_deinline_patch(source, "target", defs["sum_name_kos"], calls)

    assert not result.ok
    assert (
        result.unsupported_reason
        == "scalar multi-statement declaration initializer is not supported"
    )


def test_scalar_multi_statement_rejects_side_effecting_assignment_lhs() -> None:
    source = SCALAR_MULTI_SOURCE.replace(
        "*tp = sum_name_kos(n & 0xFF);",
        "*tp++ = sum_name_kos(n & 0xFF);",
    )
    defs = {item.name: item for item in parse_inline_defs(source, "u.c")}
    calls = find_call_sites(source, "target", "sum_name_kos")

    result = build_deinline_patch(source, "target", defs["sum_name_kos"], calls)

    assert not result.ok
    assert (
        result.unsupported_reason
        == "scalar multi-statement assignment lhs may have side effects"
    )


def test_scalar_multi_statement_rejects_duplicated_nontrivial_argument() -> None:
    source = SCALAR_MULTI_SOURCE.replace(
        "total += GetPersistentNameData(field_index)->vs_kos[(u8) j];",
        (
            "total += GetPersistentNameData(field_index)->vs_kos[(u8) j];\n"
            "            total += field_index;"
        ),
    )
    defs = {item.name: item for item in parse_inline_defs(source, "u.c")}
    calls = find_call_sites(source, "target", "sum_name_kos")

    result = build_deinline_patch(source, "target", defs["sum_name_kos"], calls)

    assert not result.ok
    assert result.unsupported_reason == "nontrivial argument would be duplicated"


def test_resolve_inline_defs_finds_header_inline(tmp_path) -> None:
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    header = include_dir / "helper.h"
    header.write_text(
        """
static inline s32 header_helper(s32 x) {
    return x + 1;
}
"""
    )
    tu = tmp_path / "unit.c"
    tu.write_text(
        """
#include "helper.h"

void target(s32 x) {
    s32 y = header_helper(x);
}
"""
    )

    defs = resolve_inline_defs(tu, [include_dir])

    assert defs["header_helper"].def_location == "header"
    assert defs["header_helper"].body_kind == "single_return_expr"
