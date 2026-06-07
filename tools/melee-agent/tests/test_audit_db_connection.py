"""Regression tests for the StateDB thread-local connection-cache bug.

Bug: ``StateDB.connection()`` cached the SQLite connection on a thread-local
that was NOT keyed by ``db_path``. A second ``StateDB(pathB)`` created on the
same thread silently reused the first ``StateDB(pathA)``'s connection, so it
operated on ``pathA`` while reporting ``self.db_path == pathB``. This made the
test suite leak claims into the real ``agent_state.db`` and made claim tests
order-dependent (a stale connection to the real DB, where ``my_func`` was
already claimed, leaked into a "fresh temp DB" test).
"""

from __future__ import annotations

import pytest

from src.db import StateDB, reset_db


@pytest.fixture(autouse=True)
def _isolate_global_db():
    reset_db()
    yield
    reset_db()


def test_second_statedb_on_same_thread_uses_its_own_db(tmp_path):
    """StateDB(b) must operate on b, not reuse StateDB(a)'s connection."""
    db_a = StateDB(tmp_path / "a.db")
    ok_a, err_a = db_a.add_claim("my_func", "agent-1")
    assert ok_a is True and err_a is None

    # A different StateDB on the SAME thread, pointing at a FRESH empty DB.
    db_b = StateDB(tmp_path / "b.db")
    ok_b, err_b = db_b.add_claim("my_func", "agent-1")
    # b.db is empty -> the claim must succeed. Before the fix this returned
    # (False, "Already claimed by you (agent-1)") because db_b reused db_a's
    # connection and saw the claim written to a.db.
    assert ok_b is True, f"db_b reused db_a's connection: {err_b!r}"
    assert err_b is None


def test_reset_db_clears_thread_local_even_when_global_unset(tmp_path):
    """reset_db() must drop a stale thread-local connection left by a direct
    StateDB instance, even though the global singleton was never initialized."""
    stale = StateDB(tmp_path / "stale.db")
    stale.add_claim("my_func", "agent-1")  # opens + caches the thread-local

    reset_db()  # _db is None here; must still clear the thread-local

    fresh = StateDB(tmp_path / "fresh.db")
    ok, err = fresh.add_claim("my_func", "agent-1")
    assert ok is True, f"stale thread-local leaked into fresh DB: {err!r}"


def test_same_path_statedb_still_shares_state(tmp_path):
    """GUARD: two StateDB instances for the SAME path must see each other's
    writes (the path-keying fix must not spuriously isolate same-path access)."""
    path = tmp_path / "shared.db"
    StateDB(path).add_claim("my_func", "agent-1")

    ok, err = StateDB(path).add_claim("my_func", "agent-2")
    # Same DB -> the claim already exists -> must be rejected.
    assert ok is False
    assert err is not None and "agent-1" in err
