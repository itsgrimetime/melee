# tests/test_audit_struct_layout.py
"""Regression tests for confirmed correctness bugs in struct_layout.

BUG 3: nested named struct/union members leak into the parent field list, and
       _find_struct_body truncates at the first inner '}' (non-brace-balanced).
BUG 4: macro/enum-sized arrays (e.g. entries[NUM_CHARACTERS]) are silently
       dropped instead of kept as a non-numeric-sized array.
"""
from pathlib import Path

from src.common import struct_layout


# ---------------------------------------------------------------------------
# BUG 3 — nested named struct/union must be a single leaf field
# ---------------------------------------------------------------------------
def test_named_nested_union_not_spliced():
    # Documented repro: the inner union members 'jobj'/'shape_set' must NOT
    # leak; only the trailing member 'u' (and 'display'/'after') survive.
    body = "u8* display; union X { int jobj; int shape_set; } u; int after;"
    names = [f["name"] for f in struct_layout._parse_c_fields(body)]
    assert names == ["display", "u", "after"]
    # explicitly assert the inner members did not leak as bare top-level fields
    assert "jobj" not in names
    assert "shape_set" not in names


def test_named_nested_struct_not_spliced():
    body = "u8* display; struct Inner { int a; int b; } inner; int after;"
    names = [f["name"] for f in struct_layout._parse_c_fields(body)]
    assert names == ["display", "inner", "after"]
    assert "a" not in names
    assert "b" not in names


def test_find_struct_body_brace_balanced(tmp_path):
    # A struct that contains a nested struct must be captured to its matching
    # outer brace, not truncated at the first inner '}'.
    inc = tmp_path / "include"
    inc.mkdir()
    (inc / "foo.h").write_text(
        "struct Foo {\n"
        "    u8* display;\n"
        "    struct Inner { int a; int b; } inner;\n"
        "    int after;\n"
        "};\n"
    )
    body = struct_layout._find_struct_body(tmp_path, "Foo")
    assert body is not None
    # The trailing member must be present (proves we did not truncate early).
    assert "after" in body
    # And the inner struct's closing member 'b' must also be captured.
    assert "inner" in body


# OVER-CORRECTION GUARD for BUG 3: a flat struct body is unchanged.
def test_flat_body_unchanged_guard():
    body = "int a; u8* b; float c;"
    names = [f["name"] for f in struct_layout._parse_c_fields(body)]
    assert names == ["a", "b", "c"]


def test_real_nested_struct_keeps_post_member_guard():
    # The member that follows a nested aggregate must be preserved (not eaten).
    body = (
        "int before; struct S { int p; int q; } mid; "
        "u8* tail; int final;"
    )
    names = [f["name"] for f in struct_layout._parse_c_fields(body)]
    assert names == ["before", "mid", "tail", "final"]
    assert "p" not in names and "q" not in names


# ---------------------------------------------------------------------------
# BUG 4 — macro/enum-sized arrays must not be dropped
# ---------------------------------------------------------------------------
def test_macro_sized_array_kept():
    body = "CountEntry entries[NUM_CHARACTERS]; int x;"
    fields = {f["name"]: f for f in struct_layout._parse_c_fields(body)}
    # The field must survive (was dropped entirely before the fix).
    assert "entries" in fields
    assert "x" in fields
    e = fields["entries"]
    assert e["is_array"] is True
    # Non-numeric size cannot be resolved → array_size None.
    assert e["array_size"] is None


def test_enumerate_macro_sized_array_emits_bare_name(tmp_path, monkeypatch):
    # With a macro-sized array, enumerate_field_paths must still emit at least
    # the bare field path instead of dropping it.
    def fake_body(repo, name):
        if name == "Target":
            return "CountEntry entries[NUM_CHARACTERS]; int after;"
        return None

    monkeypatch.setattr(struct_layout, "_find_struct_body", fake_body)
    paths = struct_layout.enumerate_field_paths(tmp_path, "Target")
    assert "after" in paths
    # The macro-sized array must contribute a path (bare name or name[0]).
    assert ("entries" in paths) or ("entries[0]" in paths)


# OVER-CORRECTION GUARD for BUG 4: numeric arrays + scalars still parse.
def test_numeric_array_and_scalar_guard():
    body = "u8 data[0x10]; s32 vals[4]; int x;"
    fields = {f["name"]: f for f in struct_layout._parse_c_fields(body)}
    assert fields["data"]["array_size"] == 0x10
    assert fields["data"]["is_array"] is True
    assert fields["vals"]["array_size"] == 4
    assert fields["x"]["is_array"] is False
    assert fields["x"]["array_size"] is None


def test_enumerate_numeric_array_unchanged_guard(tmp_path, monkeypatch):
    def fake_body(repo, name):
        if name == "Target":
            return "u8 data[0x10]; int x;"
        return None

    monkeypatch.setattr(struct_layout, "_find_struct_body", fake_body)
    paths = struct_layout.enumerate_field_paths(tmp_path, "Target")
    # Numeric array emits index 0 and 1; scalar emits bare name.
    assert "data[0]" in paths
    assert "data[1]" in paths
    assert "x" in paths
