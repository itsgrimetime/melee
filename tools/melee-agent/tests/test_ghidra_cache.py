"""Tests for ghidra SQLite cache schema and queries."""
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def db(tmp_path) -> Path:
    """A freshly-initialized cache database."""
    from src.cli.ghidra.cache import init_schema
    db_path = tmp_path / "ghidra.db"
    init_schema(db_path)
    return db_path


class TestSchema:
    def test_schema_creates_expected_tables(self, db):
        conn = sqlite3.connect(db)
        try:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            conn.close()
        assert {"functions", "xrefs", "strings"} <= tables

    def test_xrefs_has_address_indexes(self, db):
        conn = sqlite3.connect(db)
        try:
            idxs = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        finally:
            conn.close()
        assert any("xrefs" in i and "from" in i for i in idxs)
        assert any("xrefs" in i and "to" in i for i in idxs)


class TestInsertAndQuery:
    def test_insert_and_query_callers(self, db):
        from src.cli.ghidra.cache import insert_function, insert_xref, get_callers
        insert_function(db, addr=0x80243a3c, name="fn_target", size=64)
        insert_function(db, addr=0x80100000, name="fn_caller_a", size=32)
        insert_function(db, addr=0x80200000, name="fn_caller_b", size=32)
        insert_xref(db, from_addr=0x80100004, to_addr=0x80243a3c, ref_type="CALL")
        insert_xref(db, from_addr=0x80200008, to_addr=0x80243a3c, ref_type="CALL")
        callers = get_callers(db, 0x80243a3c)
        assert len(callers) == 2
        caller_names = {c["from_function"] for c in callers}
        assert caller_names == {"fn_caller_a", "fn_caller_b"}

    def test_query_callees(self, db):
        from src.cli.ghidra.cache import insert_function, insert_xref, get_callees
        insert_function(db, addr=0x80100000, name="fn_caller", size=128)
        insert_function(db, addr=0x80200000, name="fn_a", size=16)
        insert_function(db, addr=0x80300000, name="fn_b", size=16)
        insert_xref(db, from_addr=0x80100010, to_addr=0x80200000, ref_type="CALL")
        insert_xref(db, from_addr=0x80100020, to_addr=0x80300000, ref_type="CALL")
        callees = get_callees(db, 0x80100000)
        callee_names = {c["to_function"] for c in callees}
        assert callee_names == {"fn_a", "fn_b"}

    def test_strings_in_function(self, db):
        from src.cli.ghidra.cache import insert_function, insert_string, insert_xref, get_strings_for_function
        insert_function(db, addr=0x80100000, name="fn_caller", size=128)
        insert_string(db, addr=0x80400000, value="Hello, world")
        insert_string(db, addr=0x80400020, value="Goodbye")
        insert_xref(db, from_addr=0x80100008, to_addr=0x80400000, ref_type="DATA")
        insert_xref(db, from_addr=0x80100010, to_addr=0x80400020, ref_type="DATA")
        strings = get_strings_for_function(db, 0x80100000)
        assert set(strings) == {"Hello, world", "Goodbye"}
