"""Tests for select-order typed mutators (Task 9)."""
from src.search.directed.anchors import Anchor
from src.search.directed.mutators import apply_mutator, ORDER_CHANGE_MUTATORS


def test_reorder_local_decls_exact():
    src = "{\n    s32 did = 0;\n    HSD_GObj* mgobj;\n}\n"
    a = Anchor(
        "reorder_local_decls",
        (0, 0),
        {"first_line": "    s32 did = 0;", "second_line": "    HSD_GObj* mgobj;"},
    )
    assert apply_mutator("reorder_local_decls", a, src) == (
        "{\n    HSD_GObj* mgobj;\n    s32 did = 0;\n}\n"
    )


def test_change_counter_width_exact():
    src = "{\n    s16 id;\n}\n"
    a = Anchor(
        "change_counter_width",
        (0, 0),
        {"decl_line": "    s16 id;", "from": "s16", "to": "s32"},
    )
    assert apply_mutator("change_counter_width", a, src) == "{\n    s32 id;\n}\n"


def test_split_decl_init_exact():
    src = "{\n    s32 did = 0;\n}\n"
    a = Anchor(
        "split_decl_init",
        (0, 0),
        {"decl_line": "    s32 did = 0;", "var": "did", "type": "s32", "init": "0"},
    )
    assert apply_mutator("split_decl_init", a, src) == "{\n    s32 did;\n    did = 0;\n}\n"


def test_returns_none_when_payload_absent():
    assert (
        apply_mutator(
            "reorder_local_decls",
            Anchor("reorder_local_decls", (0, 0), {"first_line": "X", "second_line": "Y"}),
            "nope",
        )
        is None
    )


def test_change_counter_width_s32_to_s16():
    src = "{\n    s32 count = 10;\n    int x;\n}\n"
    a = Anchor(
        "change_counter_width",
        (0, 0),
        {"decl_line": "    s32 count = 10;", "from": "s32", "to": "s16"},
    )
    result = apply_mutator("change_counter_width", a, src)
    assert result == "{\n    s16 count = 10;\n    int x;\n}\n"


def test_change_counter_width_only_touches_cited_line():
    """Should only change the cited decl line, not other s16/s32 occurrences."""
    src = "{\n    s32 a;\n    s32 b;\n}\n"
    a = Anchor(
        "change_counter_width",
        (0, 0),
        {"decl_line": "    s32 a;", "from": "s32", "to": "s16"},
    )
    result = apply_mutator("change_counter_width", a, src)
    # Only first occurrence of the cited line should change
    assert result == "{\n    s16 a;\n    s32 b;\n}\n"


def test_split_decl_init_preserves_indent():
    src = "{\n    s16 id = 3;\n    int x;\n}\n"
    a = Anchor(
        "split_decl_init",
        (0, 0),
        {"decl_line": "    s16 id = 3;", "var": "id", "type": "s16", "init": "3"},
    )
    result = apply_mutator("split_decl_init", a, src)
    assert result == "{\n    s16 id;\n    id = 3;\n    int x;\n}\n"


def test_split_decl_init_absent_returns_none():
    src = "{\n    int x;\n}\n"
    a = Anchor(
        "split_decl_init",
        (0, 0),
        {"decl_line": "    s32 missing = 0;", "var": "missing", "type": "s32", "init": "0"},
    )
    assert apply_mutator("split_decl_init", a, src) is None


def test_reorder_second_line_absent_returns_none():
    src = "{\n    s32 did = 0;\n}\n"
    a = Anchor(
        "reorder_local_decls",
        (0, 0),
        {"first_line": "    s32 did = 0;", "second_line": "    HSD_GObj* mgobj;"},
    )
    assert apply_mutator("reorder_local_decls", a, src) is None


def test_flatten_nested_if_else_block():
    src = (
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "} else {\n"
        "    if (kind != FTKIND_KIRBY) {\n"
        "        reload = false;\n"
        "    }\n"
        "}\n"
    )
    block = (
        "} else {\n"
        "    if (kind != FTKIND_KIRBY) {\n"
        "        reload = false;\n"
        "    }\n"
        "}"
    )
    a = Anchor("flatten_nested_if", (0, 0), {"block": block})

    assert apply_mutator("flatten_nested_if", a, src) == (
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "} else if (kind != FTKIND_KIRBY) {\n"
        "    reload = false;\n"
        "}\n"
    )


def test_suffixed_source_shape_key_dispatches_to_base_mutator():
    src = (
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "} else {\n"
        "    if (kind != FTKIND_KIRBY) {\n"
        "        reload = false;\n"
        "    }\n"
        "}\n"
    )
    block = (
        "} else {\n"
        "    if (kind != FTKIND_KIRBY) {\n"
        "        reload = false;\n"
        "    }\n"
        "}"
    )
    a = Anchor("flatten_nested_if", (0, 0), {"block": block})

    assert apply_mutator("flatten_nested_if@0", a, src) == (
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "} else if (kind != FTKIND_KIRBY) {\n"
        "    reload = false;\n"
        "}\n"
    )


def test_unflatten_else_if_block():
    src = (
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "} else if (kind != FTKIND_KIRBY) {\n"
        "    reload = false;\n"
        "}\n"
    )
    block = (
        "} else if (kind != FTKIND_KIRBY) {\n"
        "    reload = false;\n"
        "}"
    )
    a = Anchor("unflatten_else_if", (0, 0), {"block": block})

    assert apply_mutator("unflatten_else_if", a, src) == (
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "} else {\n"
        "    if (kind != FTKIND_KIRBY) {\n"
        "        reload = false;\n"
        "    }\n"
        "}\n"
    )


def test_remove_branch_block_scope():
    src = (
        "if (fp->x594_b4) {\n"
        "    {\n"
        "        s32 i;\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    block = (
        "    {\n"
        "        s32 i;\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }\n"
        "    }"
    )
    a = Anchor("remove_branch_scope", (0, 0), {"block": block})

    assert apply_mutator("remove_branch_scope", a, src) == (
        "if (fp->x594_b4) {\n"
        "    s32 i;\n"
        "    for (i = 0; i < n; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "}\n"
    )


def test_add_branch_block_scope():
    src = (
        "if (fp->x594_b4) {\n"
        "    s32 i;\n"
        "    for (i = 0; i < n; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "}\n"
    )
    body = (
        "    s32 i;\n"
        "    for (i = 0; i < n; i++) {\n"
        "        sink(i);\n"
        "    }"
    )
    a = Anchor("add_branch_scope", (0, 0), {"body": body})

    assert apply_mutator("add_branch_scope", a, src) == (
        "if (fp->x594_b4) {\n"
        "    {\n"
        "        s32 i;\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def test_widen_local_lifetime_moves_decl_before_branch():
    src = (
        "if (anim_id != -1) {\n"
        "    bool reload;\n"
        "    reload = true;\n"
        "}\n"
    )
    a = Anchor(
        "widen_local_lifetime",
        (0, 0),
        {
            "decl_line": "    bool reload;",
            "insert_before_line": "if (anim_id != -1) {",
        },
    )

    assert apply_mutator("widen_local_lifetime", a, src) == (
        "bool reload;\n"
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "}\n"
    )


def test_narrow_local_lifetime_moves_decl_into_branch():
    src = (
        "bool reload;\n"
        "if (anim_id != -1) {\n"
        "    reload = true;\n"
        "}\n"
    )
    a = Anchor(
        "narrow_local_lifetime",
        (0, 0),
        {
            "decl_line": "bool reload;",
            "insert_after_line": "if (anim_id != -1) {",
        },
    )

    assert apply_mutator("narrow_local_lifetime", a, src) == (
        "if (anim_id != -1) {\n"
        "    bool reload;\n"
        "    reload = true;\n"
        "}\n"
    )


def test_reuse_loop_counter_scope_removes_inner_decl():
    src = (
        "{\n"
        "    int i;\n"
        "    if (fallback) {\n"
        "        int i;\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    block = (
        "        int i;\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }"
    )
    a = Anchor(
        "reuse_loop_counter_scope",
        (0, 0),
        {"outer_decl_line": "    int i;", "block": block, "decl_line": "        int i;"},
    )

    assert apply_mutator("reuse_loop_counter_scope", a, src) == (
        "{\n"
        "    int i;\n"
        "    if (fallback) {\n"
        "        for (i = 0; i < n; i++) {\n"
        "            sink(i);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def test_order_change_mutators_set():
    """ORDER_CHANGE_MUTATORS must include reorder_local_decls."""
    assert "reorder_local_decls" in ORDER_CHANGE_MUTATORS


def test_order_change_mutators_is_frozenset_or_set():
    assert isinstance(ORDER_CHANGE_MUTATORS, (frozenset, set))


def test_unknown_key_returns_none():
    a = Anchor("unknown_key", (0, 0), {})
    assert apply_mutator("unknown_key", a, "anything") is None
