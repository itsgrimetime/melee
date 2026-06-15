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


def test_steer_reorder_local_decls_alias_uses_validated_reorder():
    src = "{\n    s32 did = 0;\n    HSD_GObj* mgobj;\n}\n"
    a = Anchor(
        "steer_reorder_local_decls",
        (0, 0),
        {"first_line": "    s32 did = 0;", "second_line": "    HSD_GObj* mgobj;"},
    )

    assert apply_mutator("steer_reorder_local_decls", a, src) == apply_mutator(
        "reorder_local_decls",
        Anchor("reorder_local_decls", a.span, a.payload),
        src,
    )


def test_change_counter_width_exact():
    src = "{\n    s16 id;\n}\n"
    a = Anchor(
        "change_counter_width",
        (0, 0),
        {"decl_line": "    s16 id;", "from": "s16", "to": "s32"},
    )
    assert apply_mutator("change_counter_width", a, src) == "{\n    s32 id;\n}\n"


def test_steer_change_counter_width_alias_uses_validated_width_change():
    src = "{\n    s16 id;\n}\n"
    a = Anchor(
        "steer_change_counter_width",
        (0, 0),
        {"decl_line": "    s16 id;", "from": "s16", "to": "s32"},
    )

    assert apply_mutator("steer_change_counter_width", a, src) == apply_mutator(
        "change_counter_width",
        Anchor("change_counter_width", a.span, a.payload),
        src,
    )


def test_split_decl_init_exact():
    src = "{\n    s32 did = 0;\n}\n"
    a = Anchor(
        "split_decl_init",
        (0, 0),
        {"decl_line": "    s32 did = 0;", "var": "did", "type": "s32", "init": "0"},
    )
    assert apply_mutator("split_decl_init", a, src) == "{\n    s32 did;\n    did = 0;\n}\n"


def test_steer_split_decl_init_alias_uses_validated_split():
    src = "{\n    s32 did = 0;\n}\n"
    a = Anchor(
        "steer_split_decl_init",
        (0, 0),
        {"decl_line": "    s32 did = 0;", "var": "did", "type": "s32", "init": "0"},
    )

    assert apply_mutator("steer_split_decl_init", a, src) == apply_mutator(
        "split_decl_init",
        Anchor("split_decl_init", a.span, a.payload),
        src,
    )


def test_steering_aliases_return_none_for_stale_anchors():
    src = "{\n    s32 did = 0;\n}\n"

    assert (
        apply_mutator(
            "steer_reorder_local_decls",
            Anchor(
                "steer_reorder_local_decls",
                (0, 0),
                {"first_line": "    s32 missing;", "second_line": "    HSD_GObj* mgobj;"},
            ),
            src,
        )
        is None
    )
    assert (
        apply_mutator(
            "steer_change_counter_width",
            Anchor(
                "steer_change_counter_width",
                (0, 0),
                {"decl_line": "    s16 missing;", "from": "s16", "to": "s32"},
            ),
            src,
        )
        is None
    )
    assert (
        apply_mutator(
            "steer_split_decl_init",
            Anchor(
                "steer_split_decl_init",
                (0, 0),
                {"decl_line": "    s32 missing = 0;", "var": "missing", "type": "s32", "init": "0"},
            ),
            src,
        )
        is None
    )


def test_steer_rotate_local_decl_window_validates_exact_span() -> None:
    src = "void f(void) {\n    s32 a;\n    s32 b;\n    HSD_GObj* gobj;\n}\n"
    span_text = "    s32 a;\n    s32 b;\n    HSD_GObj* gobj;"
    start = src.index(span_text)
    anchor = Anchor(
        "steer_rotate_local_decl_window",
        (start, start + len(span_text)),
        {
            "span_text": span_text,
            "replacement_text": "    HSD_GObj* gobj;\n    s32 a;\n    s32 b;",
        },
    )

    assert apply_mutator("steer_rotate_local_decl_window", anchor, src) == (
        "void f(void) {\n    HSD_GObj* gobj;\n    s32 a;\n    s32 b;\n}\n"
    )


def test_steer_demote_local_decl_to_first_use_validates_exact_span() -> None:
    src = (
        "void f(void) {\n"
        "    s32 temp;\n"
        "    s32 rank;\n"
        "    HSD_GObj* gobj;\n"
        "    rank = seed + 1;\n"
        "    temp = rank;\n"
        "    use(gobj);\n"
        "}\n"
    )
    span_text = "    s32 temp;\n    s32 rank;\n    HSD_GObj* gobj;"
    replacement = "    s32 rank;\n    HSD_GObj* gobj;\n    s32 temp;"
    start = src.index(span_text)
    anchor = Anchor(
        "steer_demote_local_decl_to_first_use",
        (start, start + len(span_text)),
        {"span_text": span_text, "replacement_text": replacement},
    )

    assert apply_mutator("steer_demote_local_decl_to_first_use", anchor, src) == (
        "void f(void) {\n"
        "    s32 rank;\n"
        "    HSD_GObj* gobj;\n"
        "    s32 temp;\n"
        "    rank = seed + 1;\n"
        "    temp = rank;\n"
        "    use(gobj);\n"
        "}\n"
    )


def test_steer_split_reused_loop_counter_validates_exact_span() -> None:
    src = (
        "void f(s32* a, s32* b) {\n"
        "    s32 i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(a[i]);\n"
        "    }\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        sink(b[i]);\n"
        "    }\n"
        "}\n"
    )
    span_text = (
        "    s32 i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(a[i]);\n"
        "    }\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        sink(b[i]);\n"
        "    }"
    )
    replacement = (
        "    s32 i;\n"
        "    s32 i_1;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(a[i]);\n"
        "    }\n"
        "    for (i_1 = 0; i_1 < 2; i_1++) {\n"
        "        sink(b[i_1]);\n"
        "    }"
    )
    start = src.index(span_text)
    anchor = Anchor(
        "steer_split_reused_loop_counter",
        (start, start + len(span_text)),
        {"span_text": span_text, "replacement_text": replacement},
    )

    assert apply_mutator("steer_split_reused_loop_counter", anchor, src) == src.replace(
        span_text,
        replacement,
        1,
    )


def test_steer_reuse_dead_top_level_loop_counter_validates_exact_span() -> None:
    src = (
        "void f(void) {\n"
        "    int j;\n"
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    j = 0;\n"
        "    do {\n"
        "        sink(j);\n"
        "        j++;\n"
        "    } while (j < 2);\n"
        "}\n"
    )
    span_text = (
        "    int j;\n"
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    j = 0;\n"
        "    do {\n"
        "        sink(j);\n"
        "        j++;\n"
        "    } while (j < 2);"
    )
    replacement_text = (
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    i = 0;\n"
        "    do {\n"
        "        sink(i);\n"
        "        i++;\n"
        "    } while (i < 2);"
    )
    start = src.index(span_text)
    anchor = Anchor(
        "steer_reuse_dead_top_level_loop_counter",
        (start, start + len(span_text)),
        {"span_text": span_text, "replacement_text": replacement_text},
    )

    assert apply_mutator("steer_reuse_dead_top_level_loop_counter", anchor, src) == (
        "void f(void) {\n"
        "    int i;\n"
        "    for (i = 0; i < 3; i++) {\n"
        "        sink(i);\n"
        "    }\n"
        "    i = 0;\n"
        "    do {\n"
        "        sink(i);\n"
        "        i++;\n"
        "    } while (i < 2);\n"
        "}\n"
    )


def test_concrete_steering_mutators_reject_stale_spans() -> None:
    src = "void f(void) {\n    s32 already_changed;\n}\n"
    keys = (
        "steer_rotate_local_decl_window",
        "steer_demote_local_decl_to_first_use",
        "steer_split_reused_loop_counter",
        "steer_reuse_dead_top_level_loop_counter",
    )
    for key in keys:
        assert (
            apply_mutator(
                key,
                Anchor(
                    key,
                    (0, 3),
                    {
                        "span_text": "    s32 missing;",
                        "replacement_text": "    s32 replacement;",
                    },
                ),
                src,
            )
            is None
        )


def test_returns_none_when_payload_absent():
    assert (
        apply_mutator(
            "reorder_local_decls",
            Anchor("reorder_local_decls", (0, 0), {"first_line": "X", "second_line": "Y"}),
            "nope",
        )
        is None
    )


def test_remove_unused_trailing_parameter_applies_validated_full_source_edits():
    src = (
        "static int helper(int value, int unused) {\n"
        "    return value;\n"
        "}\n"
        "int target(void) { return helper(1, 0); }\n"
    )
    sig_start = src.index(", int unused")
    call_start = src.index(", 0")
    a = Anchor(
        "remove_unused_trailing_parameter",
        (sig_start, call_start + len(", 0")),
        {
            "edits": [
                {
                    "start": sig_start,
                    "end": sig_start + len(", int unused"),
                    "span_text": ", int unused",
                    "replacement_text": "",
                },
                {
                    "start": call_start,
                    "end": call_start + len(", 0"),
                    "span_text": ", 0",
                    "replacement_text": "",
                },
            ],
        },
    )

    assert apply_mutator("remove_unused_trailing_parameter", a, src) == (
        "static int helper(int value) {\n"
        "    return value;\n"
        "}\n"
        "int target(void) { return helper(1); }\n"
    )


def test_add_unused_trailing_parameter_rejects_stale_validated_edits():
    src = "static int helper(void) { return 1; }\n"
    a = Anchor(
        "add_unused_trailing_parameter",
        (0, 0),
        {
            "edits": [
                {
                    "start": src.index("void"),
                    "end": src.index("void") + len("void"),
                    "span_text": "VOID",
                    "replacement_text": "int unused",
                }
            ],
        },
    )

    assert apply_mutator("add_unused_trailing_parameter", a, src) is None


def test_materialize_outgoing_parameter_area_call_args_applies_exact_edits():
    src = (
        "void target(int i) {\n"
        "    f32 x;\n"
        "    HSD_SisLib_803A6B98(text, x + 1.0F, x, name);\n"
        "}\n"
    )
    insert_at = src.index("    HSD_SisLib")
    arg_start = src.index("x + 1.0F")
    a = Anchor(
        "materialize_outgoing_parameter_area_call_args",
        (insert_at, arg_start + len("x + 1.0F")),
        {
            "edits": [
                {
                    "start": insert_at,
                    "end": insert_at,
                    "span_text": "",
                    "replacement_text": "    f32 param_area_0_1 = x + 1.0F;\n",
                },
                {
                    "start": arg_start,
                    "end": arg_start + len("x + 1.0F"),
                    "span_text": "x + 1.0F",
                    "replacement_text": "param_area_0_1",
                },
            ],
        },
    )

    assert apply_mutator(
        "materialize_outgoing_parameter_area_call_args",
        a,
        src,
    ) == (
        "void target(int i) {\n"
        "    f32 x;\n"
        "    f32 param_area_0_1 = x + 1.0F;\n"
        "    HSD_SisLib_803A6B98(text, param_area_0_1, x, name);\n"
        "}\n"
    )


def test_materialize_outgoing_parameter_area_call_args_rejects_stale_spans():
    src = "void target(void) { HSD_SisLib_803A6B98(text, x, y, name); }\n"
    insert_at = src.index("HSD_SisLib")
    a = Anchor(
        "materialize_outgoing_parameter_area_call_args",
        (insert_at, insert_at),
        {
            "edits": [
                {
                    "start": insert_at,
                    "end": insert_at + len("HSD"),
                    "span_text": "XYZ",
                    "replacement_text": "abc",
                },
            ],
        },
    )

    assert apply_mutator(
        "materialize_outgoing_parameter_area_call_args",
        a,
        src,
    ) is None


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


def test_steer_reuse_loop_counter_scope_alias_uses_validated_reuse():
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
        "steer_reuse_loop_counter_scope",
        (0, 0),
        {"outer_decl_line": "    int i;", "block": block, "decl_line": "        int i;"},
    )

    assert apply_mutator("steer_reuse_loop_counter_scope", a, src) == apply_mutator(
        "reuse_loop_counter_scope",
        Anchor("reuse_loop_counter_scope", a.span, a.payload),
        src,
    )


def test_add_explicit_zero_return_after_call_only_wrapper():
    src = "{\n    un_802FFD94(arg0, &un_803FA8E8, fn_802FFE6C);\n}\n"
    a = Anchor(
        "add_explicit_zero_return",
        (0, 0),
        {
            "call_line": "    un_802FFD94(arg0, &un_803FA8E8, fn_802FFE6C);",
            "return_line": "    return 0;",
        },
    )

    assert apply_mutator("add_explicit_zero_return", a, src) == (
        "{\n"
        "    un_802FFD94(arg0, &un_803FA8E8, fn_802FFE6C);\n"
        "    return 0;\n"
        "}\n"
    )


def test_add_explicit_zero_return_returns_none_when_call_line_absent():
    src = "{\n    other(arg0);\n}\n"
    a = Anchor(
        "add_explicit_zero_return",
        (0, 0),
        {
            "call_line": "    un_802FFD94(arg0, &un_803FA8E8, fn_802FFE6C);",
            "return_line": "    return 0;",
        },
    )

    assert apply_mutator("add_explicit_zero_return", a, src) is None


def test_add_explicit_zero_return_prefers_anchor_span_when_call_line_repeats():
    call_line = "    repeated(arg0);"
    src = (
        "int first(int arg0) {\n"
        f"{call_line}\n"
        "}\n"
        "int second(int arg0) {\n"
        f"{call_line}\n"
        "}\n"
    )
    target = src.rfind(call_line)
    a = Anchor(
        "add_explicit_zero_return",
        (target, target + len(call_line)),
        {
            "call_line": call_line,
            "return_line": "    return 0;",
        },
    )

    assert apply_mutator("add_explicit_zero_return", a, src) == (
        "int first(int arg0) {\n"
        f"{call_line}\n"
        "}\n"
        "int second(int arg0) {\n"
        f"{call_line}\n"
        "    return 0;\n"
        "}\n"
    )


def test_wrap_comma_noop_assignment_rhs():
    src = "{\n    jobj = (HSD_JObj*) HSD_GObjGetHSDObj(gobj);\n}\n"
    a = Anchor(
        "wrap_comma_noop_assignment_rhs",
        (0, 0),
        {
            "line": "    jobj = (HSD_JObj*) HSD_GObjGetHSDObj(gobj);",
            "replacement_line": (
                "    jobj = (0, (HSD_JObj*) HSD_GObjGetHSDObj(gobj));"
            ),
        },
    )

    assert apply_mutator("wrap_comma_noop_assignment_rhs", a, src) == (
        "{\n    jobj = (0, (HSD_JObj*) HSD_GObjGetHSDObj(gobj));\n}\n"
    )


def test_insert_empty_do_while_barrier_after_statement():
    src = "{\n    process(cur);\n    update(cur);\n}\n"
    a = Anchor(
        "insert_empty_do_while_barrier",
        (0, 0),
        {
            "after_line": "    process(cur);",
            "barrier": "    do {\n    } while (0);",
        },
    )

    assert apply_mutator("insert_empty_do_while_barrier", a, src) == (
        "{\n"
        "    process(cur);\n"
        "    do {\n"
        "    } while (0);\n"
        "    update(cur);\n"
        "}\n"
    )


def test_fold_assignment_expression_seed_into_if_condition():
    src = "{\n    item = HSD_GObj_Entities->items;\n    if (item != NULL) {\n        use(item);\n    }\n}\n"
    a = Anchor(
        "fold_assignment_expression_seed",
        (0, 0),
        {
            "assignment_line": "    item = HSD_GObj_Entities->items;",
            "condition_line": "    if (item != NULL) {",
            "replacement_line": "    if ((item = HSD_GObj_Entities->items) != NULL) {",
        },
    )

    assert apply_mutator("fold_assignment_expression_seed", a, src) == (
        "{\n"
        "    if ((item = HSD_GObj_Entities->items) != NULL) {\n"
        "        use(item);\n"
        "    }\n"
        "}\n"
    )


def test_elide_numeric_cast_line():
    src = "{\n    it_8026F790(gobj, (f32) angle);\n}\n"
    a = Anchor(
        "elide_numeric_cast",
        (0, 0),
        {
            "line": "    it_8026F790(gobj, (f32) angle);",
            "replacement_line": "    it_8026F790(gobj, angle);",
        },
    )

    assert apply_mutator("elide_numeric_cast", a, src) == (
        "{\n    it_8026F790(gobj, angle);\n}\n"
    )


def test_type_cast_compatibility_mutators_replace_validated_spans():
    src = (
        "void target(void) {\n"
        "    use_gobj((HSD_GObj*) gobj);\n"
        "    register_cb(gobj, (void (*)(HSD_GObj*)) callback);\n"
        "    Point3d pos;\n"
        "}\n"
    )

    pointer_span = "(HSD_GObj*) gobj"
    pointer = Anchor(
        "elide_redundant_pointer_cast",
        (src.index(pointer_span), src.index(pointer_span) + len(pointer_span)),
        {"span_text": pointer_span, "replacement_text": "gobj"},
    )
    callback_span = "(void (*)(HSD_GObj*)) callback"
    callback = Anchor(
        "elide_callback_cast",
        (src.index(callback_span), src.index(callback_span) + len(callback_span)),
        {"span_text": callback_span, "replacement_text": "callback"},
    )
    vector_span = "Point3d"
    vector = Anchor(
        "rewrite_vector_alias_type",
        (src.index(vector_span), src.index(vector_span) + len(vector_span)),
        {"span_text": vector_span, "replacement_text": "Vec3"},
    )

    assert "use_gobj(gobj);" in apply_mutator(
        "elide_redundant_pointer_cast",
        pointer,
        src,
    )
    assert "register_cb(gobj, callback);" in apply_mutator(
        "elide_callback_cast",
        callback,
        src,
    )
    assert "    Vec3 pos;" in apply_mutator("rewrite_vector_alias_type", vector, src)


def test_type_cast_compatibility_mutators_reject_stale_spans():
    src = "void target(void) {\n    use_gobj((HSD_GObj*) gobj);\n}\n"
    span_text = "(HSD_GObj*) other"
    anchor = Anchor(
        "elide_redundant_pointer_cast",
        (src.index("(HSD_GObj*) gobj"), src.index("(HSD_GObj*) gobj") + len(span_text)),
        {"span_text": span_text, "replacement_text": "other"},
    )

    assert apply_mutator("elide_redundant_pointer_cast", anchor, src) is None


def test_swap_simple_switch_cases():
    src = (
        "switch (kind) {\n"
        "case 7:\n"
        "    b();\n"
        "    break;\n"
        "case 9:\n"
        "    c();\n"
        "    break;\n"
        "}\n"
    )
    first = "case 7:\n    b();\n    break;"
    second = "case 9:\n    c();\n    break;"
    a = Anchor(
        "swap_simple_switch_cases",
        (0, 0),
        {"first_arm": first, "second_arm": second},
    )

    assert apply_mutator("swap_simple_switch_cases", a, src) == (
        "switch (kind) {\n"
        "case 9:\n"
        "    c();\n"
        "    break;\n"
        "case 7:\n"
        "    b();\n"
        "    break;\n"
        "}\n"
    )


def test_collapse_hsd_assert():
    src = '{\n    if (archive == NULL)\n        __assert("mined.c", 0x617, "0");\n}\n'
    block = '    if (archive == NULL)\n        __assert("mined.c", 0x617, "0");'
    a = Anchor(
        "collapse_hsd_assert",
        (0, 0),
        {"block": block, "replacement": '    HSD_ASSERTMSG(0x617, archive, "0");'},
    )

    assert apply_mutator("collapse_hsd_assert", a, src) == (
        '{\n    HSD_ASSERTMSG(0x617, archive, "0");\n}\n'
    )


def test_return_tail_call_value():
    src = "static void mined(Item* it) {\n    setup(it);\n    fn_8017F0A0(it);\n}\n"
    a = Anchor(
        "return_tail_call_value",
        (0, len(src)),
        {
            "signature": "static void mined(Item* it)",
            "replacement_signature": "static s32 mined(Item* it)",
            "line": "    fn_8017F0A0(it);",
            "replacement_line": "    return fn_8017F0A0(it);",
        },
    )

    assert apply_mutator("return_tail_call_value", a, src) == (
        "static s32 mined(Item* it) {\n"
        "    setup(it);\n"
        "    return fn_8017F0A0(it);\n"
        "}\n"
    )


def test_replace_string_literal_with_data_field():
    src = '{\n    OSReport("loaded stage %d\\n", id);\n}\n'
    a = Anchor(
        "replace_string_literal_with_data_field",
        (0, 0),
        {
            "line": '    OSReport("loaded stage %d\\n", id);',
            "literal": '"loaded stage %d\\n"',
            "replacement": "grIm_803E4800.report_format",
        },
    )

    assert apply_mutator("replace_string_literal_with_data_field", a, src) == (
        "{\n    OSReport(grIm_803E4800.report_format, id);\n}\n"
    )


def test_replace_float_literal_with_global_constant_rewrites_validated_span():
    src = "void target(void) {\n    f32 x = 0.5f;\n}\n"
    start = src.index("0.5f")
    a = Anchor(
        "replace_float_literal_with_global_constant",
        (start, start + len("0.5f")),
        {
            "span_text": "0.5f",
            "replacement_text": "lbl_804D8000",
        },
    )

    assert apply_mutator("replace_float_literal_with_global_constant", a, src) == (
        "void target(void) {\n    f32 x = lbl_804D8000;\n}\n"
    )


def test_replace_global_float_constant_with_literal_rewrites_validated_span():
    src = "void target(void) {\n    f64 x = lbl_804D8008;\n}\n"
    start = src.index("lbl_804D8008")
    a = Anchor(
        "replace_global_float_constant_with_literal",
        (start, start + len("lbl_804D8008")),
        {
            "span_text": "lbl_804D8008",
            "replacement_text": "0.75",
        },
    )

    assert apply_mutator("replace_global_float_constant_with_literal", a, src) == (
        "void target(void) {\n    f64 x = 0.75;\n}\n"
    )


def test_global_float_literal_mutators_reject_stale_span():
    src = "void target(void) {\n    f32 x = 1.0f;\n}\n"
    a = Anchor(
        "replace_float_literal_with_global_constant",
        (src.index("1.0f"), src.index("1.0f") + len("1.0f")),
        {
            "span_text": "0.5f",
            "replacement_text": "lbl_804D8000",
        },
    )

    assert apply_mutator("replace_float_literal_with_global_constant", a, src) is None


def test_introduce_global_pointer_alias():
    src = (
        "void f(void) {\n"
        "    lbl_80472D28.field = x;\n"
        "    use(lbl_80472D28.other);\n"
        "}\n"
    )
    a = Anchor(
        "introduce_global_pointer_alias",
        (0, 0),
        {
            "insert_after_line": "void f(void) {",
            "alias_line": "    State* lbl_80472D28_alias = &lbl_80472D28;",
            "global_prefix": "lbl_80472D28.",
            "alias_prefix": "lbl_80472D28_alias->",
        },
    )

    assert apply_mutator("introduce_global_pointer_alias", a, src) == (
        "void f(void) {\n"
        "    State* lbl_80472D28_alias = &lbl_80472D28;\n"
        "    lbl_80472D28_alias->field = x;\n"
        "    use(lbl_80472D28_alias->other);\n"
        "}\n"
    )


def test_rewrite_raw_pointer_offset_field():
    src = "{\n    *(Vec3*) ((u8*) gp + 0xE0) = scroll;\n}\n"
    a = Anchor(
        "rewrite_raw_pointer_offset_field",
        (0, 0),
        {
            "line": "    *(Vec3*) ((u8*) gp + 0xE0) = scroll;",
            "replacement_line": "    gp->scroll = scroll;",
        },
    )

    assert apply_mutator("rewrite_raw_pointer_offset_field", a, src) == (
        "{\n    gp->scroll = scroll;\n}\n"
    )


def test_rewrite_raw_index_struct_field_validates_span() -> None:
    src = "void f(void) {\n    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n}\n"
    span_text = "*(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10)"
    start = src.index(span_text)
    anchor = Anchor(
        "rewrite_raw_index_struct_field",
        (start, start + len(span_text)),
        {
            "span_text": span_text,
            "replacement_text": "entries[i].voice_id",
        },
    )

    assert apply_mutator("rewrite_raw_index_struct_field", anchor, src) == (
        "void f(void) {\n    value = entries[i].voice_id;\n}\n"
    )


def test_rewrite_raw_index_struct_field_rejects_stale_span() -> None:
    src = "void f(void) {\n    value = entries[i].voice_id;\n}\n"
    anchor = Anchor(
        "rewrite_raw_index_struct_field",
        (0, 3),
        {
            "span_text": "*(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10)",
            "replacement_text": "entries[i].voice_id",
        },
    )

    assert apply_mutator("rewrite_raw_index_struct_field", anchor, src) is None


def test_rewrite_data_table_indirection_validates_span() -> None:
    src = "void f(void) {\n    value = table_b[idx];\n}\n"
    span_text = "table_b[idx]"
    start = src.index(span_text)
    anchor = Anchor(
        "rewrite_data_table_indirection",
        (start, start + len(span_text)),
        {
            "span_text": span_text,
            "replacement_text": "sOuterTable[1][idx]",
        },
    )

    assert apply_mutator("rewrite_data_table_indirection", anchor, src) == (
        "void f(void) {\n    value = sOuterTable[1][idx];\n}\n"
    )


def test_rewrite_bool_accumulator_as_int():
    src = (
        "{\n"
        "    bool test;\n"
        "    test = first(gobj);\n"
        "    if (test != false) {\n"
        "        use(gobj);\n"
        "    }\n"
        "    if (test == true) {\n"
        "        use_true(gobj);\n"
        "    }\n"
        "    test |= second(gobj);\n"
        "    return test;\n"
        "}\n"
    )
    a = Anchor(
        "rewrite_bool_accumulator_as_int",
        (0, len(src)),
        {
            "scope_text": src,
            "decl_line": "    bool test;",
            "replacement_decl_line": "    s32 test;",
            "compare_replacements": (
                ("    if (test != false) {", "    if (test != 0) {"),
                ("    if (test == true) {", "    if (test == 1) {"),
            ),
        },
    )

    assert apply_mutator("rewrite_bool_accumulator_as_int", a, src) == (
        "{\n"
        "    s32 test;\n"
        "    test = first(gobj);\n"
        "    if (test != 0) {\n"
        "        use(gobj);\n"
        "    }\n"
        "    if (test == 1) {\n"
        "        use_true(gobj);\n"
        "    }\n"
        "    test |= second(gobj);\n"
        "    return test;\n"
        "}\n"
    )


def test_rewrite_zero_compare_logical_not():
    src = "{\n    if (call(gobj) == 0) {\n        return false;\n    }\n}\n"
    a = Anchor(
        "rewrite_zero_compare_logical_not",
        (0, 0),
        {
            "line": "    if (call(gobj) == 0) {",
            "replacement_line": "    if (!call(gobj)) {",
        },
    )

    assert apply_mutator("rewrite_zero_compare_logical_not", a, src) == (
        "{\n    if (!call(gobj)) {\n        return false;\n    }\n}\n"
    )


def test_rewrite_abs_ternary_to_macro():
    src = "{\n    use((delta < 0.0F) ? -delta : delta);\n}\n"
    a = Anchor(
        "rewrite_abs_ternary_to_macro",
        (0, 0),
        {
            "line": "    use((delta < 0.0F) ? -delta : delta);",
            "replacement_line": "    use(ABS(delta));",
        },
    )

    assert apply_mutator("rewrite_abs_ternary_to_macro", a, src) == (
        "{\n    use(ABS(delta));\n}\n"
    )


def test_rewrite_minmax_macro_to_ternary():
    src = "{\n    clamped = MAX(value, limit);\n}\n"
    a = Anchor(
        "rewrite_minmax_macro_to_ternary",
        (0, 0),
        {
            "line": "    clamped = MAX(value, limit);",
            "replacement_line": "    clamped = ((value) > (limit) ? (value) : (limit));",
        },
    )

    assert apply_mutator("rewrite_minmax_macro_to_ternary", a, src) == (
        "{\n    clamped = ((value) > (limit) ? (value) : (limit));\n}\n"
    )


def test_new_mutators_return_none_when_payload_line_absent():
    assert (
        apply_mutator(
            "wrap_comma_noop_assignment_rhs",
            Anchor(
                "wrap_comma_noop_assignment_rhs",
                (0, 0),
                {"line": "    missing = x;", "replacement_line": "    missing = (0, x);"},
            ),
            "{\n    present = x;\n}\n",
        )
        is None
    )


def test_scalar_mutators_return_none_when_payload_absent():
    assert (
        apply_mutator(
            "rewrite_zero_compare_logical_not",
            Anchor(
                "rewrite_zero_compare_logical_not",
                (0, 0),
                {"line": "    if (missing == 0) {", "replacement_line": "    if (!missing) {"},
            ),
            "{\n    if (present == 0) {\n    }\n}\n",
        )
        is None
    )


def test_scalar_line_mutator_uses_anchor_span_for_repeated_lines():
    src = (
        "void first(void) {\n"
        "    if (flag == 0) {\n"
        "        use_first();\n"
        "    }\n"
        "}\n"
        "void second(void) {\n"
        "    if (flag == 0) {\n"
        "        use_second();\n"
        "    }\n"
        "}\n"
    )
    second_start = src.index("    if (flag == 0) {", src.index("void second"))
    a = Anchor(
        "rewrite_zero_compare_logical_not",
        (second_start, second_start + len("    if (flag == 0) {")),
        {
            "line": "    if (flag == 0) {",
            "replacement_line": "    if (!flag) {",
        },
    )

    assert apply_mutator("rewrite_zero_compare_logical_not", a, src) == (
        "void first(void) {\n"
        "    if (flag == 0) {\n"
        "        use_first();\n"
        "    }\n"
        "}\n"
        "void second(void) {\n"
        "    if (!flag) {\n"
        "        use_second();\n"
        "    }\n"
        "}\n"
    )


def test_scalar_line_mutator_rejects_stale_repeated_line_span():
    src = (
        "void first(void) {\n"
        "    if (flag == 0) {\n"
        "        use_first();\n"
        "    }\n"
        "}\n"
        "void second(void) {\n"
        "    if (flag == 0) {\n"
        "        use_second();\n"
        "    }\n"
        "}\n"
    )
    a = Anchor(
        "rewrite_zero_compare_logical_not",
        (0, 0),
        {
            "line": "    if (flag == 0) {",
            "replacement_line": "    if (!flag) {",
        },
    )

    assert apply_mutator("rewrite_zero_compare_logical_not", a, src) is None


def test_inline_simple_helper_call_replaces_exact_line():
    src = "{\n    score = add_bonus(arg0, arg1);\n}\n"
    a = Anchor(
        "inline_simple_helper_call",
        (0, 0),
        {
            "line": "    score = add_bonus(arg0, arg1);",
            "replacement_line": "    score = (arg0 + arg1);",
        },
    )

    assert apply_mutator("inline_simple_helper_call", a, src) == (
        "{\n    score = (arg0 + arg1);\n}\n"
    )


def test_extract_repeated_assignment_helper_inserts_helper_and_rewrites_lines():
    src = (
        "void target(s32 arg0, s32 arg1) {\n"
        "    s32 left;\n"
        "    s32 right;\n"
        "    left = arg0 + arg1;\n"
        "    right = arg0 + arg1;\n"
        "}\n"
    )
    a = Anchor(
        "extract_repeated_assignment_helper",
        (0, 0),
        {
            "insert_before": "void target(s32 arg0, s32 arg1) {",
            "helper_text": (
                "static s32 target__helper_shape_0(s32 arg0, s32 arg1) {\n"
                "    return arg0 + arg1;\n"
                "}\n"
                "\n"
            ),
            "line_replacements": (
                (
                    "    left = arg0 + arg1;",
                    "    left = target__helper_shape_0(arg0, arg1);",
                ),
                (
                    "    right = arg0 + arg1;",
                    "    right = target__helper_shape_0(arg0, arg1);",
                ),
            ),
            "helper_name": "target__helper_shape_0",
            "target_function": "target",
            "rhs": "arg0 + arg1",
            "operand_order": ("arg0", "arg1"),
            "operand_types": (("arg0", "s32"), ("arg1", "s32")),
        },
    )

    assert apply_mutator("extract_repeated_assignment_helper", a, src) == (
        "static s32 target__helper_shape_0(s32 arg0, s32 arg1) {\n"
        "    return arg0 + arg1;\n"
        "}\n"
        "\n"
        "void target(s32 arg0, s32 arg1) {\n"
        "    s32 left;\n"
        "    s32 right;\n"
        "    left = target__helper_shape_0(arg0, arg1);\n"
        "    right = target__helper_shape_0(arg0, arg1);\n"
        "}\n"
    )


def test_reuse_same_type_local_lifetime_rewrites_validated_scope():
    body = (
        "\n"
        "    ItemLink* cur;\n"
        "    ItemLink* prev;\n"
        "    cur = link->next;\n"
        "    sink(cur);\n"
        "    prev = it_802BCB88_prev(link);\n"
        "    sink(prev);\n"
    )
    replacement = (
        "\n"
        "    ItemLink* cur;\n"
        "    cur = link->next;\n"
        "    sink(cur);\n"
        "    cur = it_802BCB88_prev(link);\n"
        "    sink(cur);\n"
    )
    src = "{" + body + "}\n"
    a = Anchor(
        "reuse_same_type_local_lifetime",
        (1, 1 + len(body)),
        {
            "scope_text": body,
            "replacement_scope_text": replacement,
            "reused_name": "cur",
            "original_name": "prev",
            "local_type": "ItemLink*",
        },
    )

    assert apply_mutator("reuse_same_type_local_lifetime", a, src) == (
        "{" + replacement + "}\n"
    )


def test_steer_reuse_same_type_local_lifetime_alias_uses_validated_scope():
    body = (
        "\n"
        "    ItemLink* cur;\n"
        "    ItemLink* prev;\n"
        "    cur = link->next;\n"
        "    sink(cur);\n"
        "    prev = it_802BCB88_prev(link);\n"
        "    sink(prev);\n"
    )
    replacement = (
        "\n"
        "    ItemLink* cur;\n"
        "    cur = link->next;\n"
        "    sink(cur);\n"
        "    cur = it_802BCB88_prev(link);\n"
        "    sink(cur);\n"
    )
    src = "{" + body + "}\n"
    a = Anchor(
        "steer_reuse_same_type_local_lifetime",
        (1, 1 + len(body)),
        {
            "scope_text": body,
            "replacement_scope_text": replacement,
            "reused_name": "cur",
            "original_name": "prev",
            "local_type": "ItemLink*",
        },
    )

    assert apply_mutator("steer_reuse_same_type_local_lifetime", a, src) == apply_mutator(
        "reuse_same_type_local_lifetime",
        Anchor("reuse_same_type_local_lifetime", a.span, a.payload),
        src,
    )


def test_reuse_same_type_local_lifetime_rejects_stale_scope_span():
    scope = (
        "\n"
        "    int cur;\n"
        "    int prev;\n"
        "    cur = a;\n"
        "    prev = b;\n"
    )
    replacement = (
        "\n"
        "    int cur;\n"
        "    cur = a;\n"
        "    cur = b;\n"
    )
    src = "void helper(void) {" + scope + "}\nvoid target(void) {" + scope + "}\n"
    target_start = src.index("void target")
    a = Anchor(
        "reuse_same_type_local_lifetime",
        (target_start, target_start + len(scope)),
        {
            "scope_text": scope,
            "replacement_scope_text": replacement,
            "reused_name": "cur",
            "original_name": "prev",
            "local_type": "int",
        },
    )

    assert apply_mutator("reuse_same_type_local_lifetime", a, src) is None


def test_add_dont_inline_pragma_pair_rewrites_validated_function_span():
    src = "bool target(void)\n{\n    return false;\n}\n"
    replacement = (
        "#pragma push\n"
        "#pragma dont_inline on\n"
        "bool target(void)\n"
        "{\n"
        "    return false;\n"
        "}\n"
        "#pragma pop\n"
    )
    a = Anchor(
        "add_dont_inline_pragma_pair",
        (0, len(src)),
        {"span_text": src, "replacement_text": replacement},
    )

    assert apply_mutator("add_dont_inline_pragma_pair", a, src) == replacement


def test_remove_dont_inline_pragma_pair_rewrites_validated_wrapper_span():
    src = (
        "#pragma push\n"
        "#pragma dont_inline on\n"
        "bool target(void)\n"
        "{\n"
        "    return false;\n"
        "}\n"
        "#pragma pop\n"
    )
    replacement = "bool target(void)\n{\n    return false;\n}\n"
    a = Anchor(
        "remove_dont_inline_pragma_pair",
        (0, len(src)),
        {"span_text": src, "replacement_text": replacement},
    )

    assert apply_mutator("remove_dont_inline_pragma_pair", a, src) == replacement


def test_dont_inline_pragma_pair_mutators_reject_stale_span():
    src = (
        "bool helper(void)\n{\n    return true;\n}\n"
        "bool target(void)\n{\n    return false;\n}\n"
    )
    span_text = "bool target(void)\n{\n    return false;\n}\n"
    replacement = "#pragma push\n#pragma dont_inline on\n" + span_text + "#pragma pop\n"
    a = Anchor(
        "add_dont_inline_pragma_pair",
        (0, len(span_text)),
        {"span_text": span_text, "replacement_text": replacement},
    )

    assert apply_mutator("add_dont_inline_pragma_pair", a, src) is None


def test_swap_independent_adjacent_statements_replaces_validated_span():
    src = (
        "void target(void) {\n"
        "    a = x + 1;\n"
        "    b = y + 2;\n"
        "}\n"
    )
    span_text = "    a = x + 1;\n    b = y + 2;\n"
    replacement_text = "    b = y + 2;\n    a = x + 1;\n"
    start = src.index(span_text)
    a = Anchor(
        "swap_independent_adjacent_statements",
        (start, start + len(span_text)),
        {
            "span_text": span_text,
            "replacement_text": replacement_text,
        },
    )

    assert apply_mutator("swap_independent_adjacent_statements", a, src) == (
        "void target(void) {\n"
        "    b = y + 2;\n"
        "    a = x + 1;\n"
        "}\n"
    )


def test_swap_independent_adjacent_statements_rejects_stale_span():
    src = (
        "void target(void) {\n"
        "    a = x + 1;\n"
        "    b = y + 2;\n"
        "}\n"
    )
    a = Anchor(
        "swap_independent_adjacent_statements",
        (src.index("    a ="), src.index("    b =")),
        {
            "span_text": "    a = stale;\n",
            "replacement_text": "    b = y + 2;\n    a = x + 1;\n",
        },
    )

    assert apply_mutator("swap_independent_adjacent_statements", a, src) is None


def test_order_change_mutators_set():
    """ORDER_CHANGE_MUTATORS must include reorder_local_decls."""
    assert "reorder_local_decls" in ORDER_CHANGE_MUTATORS


def test_order_change_mutators_is_frozenset_or_set():
    assert isinstance(ORDER_CHANGE_MUTATORS, (frozenset, set))


def test_unknown_key_returns_none():
    a = Anchor("unknown_key", (0, 0), {})
    assert apply_mutator("unknown_key", a, "anything") is None
