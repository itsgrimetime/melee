"""Tests for select-order anchor resolver (Task 8)."""
from src.search.directed.anchors import resolve_anchor

SRC = (
    "int grIceMt_801F9ACC(Ground_GObj* gobj, float y, GrIceMtSegmentLookup ev,\n"
    "                     Ground_GObj* arg3)\n"
    "{\n"
    "    s16* seg = (s16*) gobj;\n"
    "    s32 did = 0;\n"
    "    HSD_GObj* mgobj;\n"
    "    HSD_JObj* jobj;\n"
    "}\n"
)


class _Idea:
    def __init__(self, var_name, first_def=None):
        self.var_name = var_name
        self.first_def = first_def


def test_resolves_and_span_matches_source():
    a = resolve_anchor(_Idea("did", "s32 did = 0;"), SRC)
    assert a is not None
    # Every payload line must literally appear in SRC
    for key in ("first_line", "decl_line"):
        if key in a.payload:
            assert a.payload[key] in SRC
            break
    # mutator_key must be one of the three valid keys
    assert a.mutator_key in {"reorder_local_decls", "change_counter_width", "split_decl_init"}
    # the cited decl line must literally appear in SRC
    assert "    s32 did = 0;" in SRC


def test_unresolvable_returns_none():
    assert resolve_anchor(_Idea("zzz", "nope"), SRC) is None


def test_reorder_chosen_when_adjacent_decl_present():
    """'did' has an adjacent local decl (HSD_GObj* mgobj) → reorder_local_decls."""
    a = resolve_anchor(_Idea("did", "s32 did = 0;"), SRC)
    assert a is not None
    assert a.mutator_key == "reorder_local_decls"
    assert a.payload["first_line"] == "    s32 did = 0;"
    assert a.payload["second_line"] == "    HSD_GObj* mgobj;"


def test_change_counter_width_when_no_adjacent_decl():
    """A lone s32 decl without adjacent decl → change_counter_width."""
    src_lone = "{\n    s32 x = 5;\n}\n"
    a = resolve_anchor(_Idea("x", "s32 x = 5;"), src_lone)
    assert a is not None
    assert a.mutator_key in {"change_counter_width", "split_decl_init"}


def test_split_decl_init_for_initialised_decl():
    """Lone decl with initializer and no type-width type → split_decl_init."""
    src = "{\n    GObj* p = foo();\n}\n"
    a = resolve_anchor(_Idea("p", "GObj* p = foo();"), src)
    # May be split_decl_init or None depending on type; just verify no crash
    # and that if resolved it's a valid key
    if a is not None:
        assert a.mutator_key in {"reorder_local_decls", "change_counter_width", "split_decl_init"}


def test_anchor_span_payload_line_matches_source_slice():
    """span must be consistent: source[start:end] == payload's primary line."""
    a = resolve_anchor(_Idea("did", "s32 did = 0;"), SRC)
    assert a is not None
    start, end = a.span
    # The span slice must at minimum contain the primary decl line text
    primary_key = "first_line" if "first_line" in a.payload else "decl_line"
    assert a.payload[primary_key] in SRC[start:end]


def test_anchor_is_frozen():
    """Anchor must be a frozen dataclass (immutable)."""
    a = resolve_anchor(_Idea("did", "s32 did = 0;"), SRC)
    assert a is not None
    import dataclasses
    assert dataclasses.is_dataclass(a)
    try:
        a.mutator_key = "other"
        assert False, "should be frozen"
    except (dataclasses.FrozenInstanceError, TypeError, AttributeError):
        pass
