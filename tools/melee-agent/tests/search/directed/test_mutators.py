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


def test_order_change_mutators_set():
    """ORDER_CHANGE_MUTATORS must include reorder_local_decls."""
    assert "reorder_local_decls" in ORDER_CHANGE_MUTATORS


def test_order_change_mutators_is_frozenset_or_set():
    assert isinstance(ORDER_CHANGE_MUTATORS, (frozenset, set))


def test_unknown_key_returns_none():
    a = Anchor("unknown_key", (0, 0), {})
    assert apply_mutator("unknown_key", a, "anything") is None
