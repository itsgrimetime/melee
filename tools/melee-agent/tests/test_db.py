"""Tests for the state database.

The database is the source of truth for:
- Function claims (who's working on what)
- Match progress (scratch slugs, match percentages)
- Subdirectory locks (worktree isolation)
- Audit history

These tests use an in-memory database to avoid filesystem side effects.
"""

import time
from pathlib import Path

import pytest


@pytest.fixture
def db(tmp_path):
    """Create a fresh database for each test."""
    from src.db import StateDB, reset_db

    # Reset any global DB instance that may have been initialized by other tests
    reset_db()
    db_path = tmp_path / "test_state.db"
    db = StateDB(db_path)
    yield db
    db.close()
    reset_db()  # Clean up after test


class TestClaims:
    """Tests for function claim management.

    Claims prevent multiple agents from working on the same function.
    They have expiration times and ownership tracking.
    """

    def test_add_claim_success(self, db):
        """Adding a new claim should succeed."""
        success, error = db.add_claim("my_func", "agent-1")
        assert success is True
        assert error is None

    def test_add_claim_same_agent_fails(self, db):
        """Same agent claiming twice should fail."""
        db.add_claim("my_func", "agent-1")
        success, error = db.add_claim("my_func", "agent-1")

        assert success is False
        assert "Already claimed by you" in error

    def test_add_claim_different_agent_fails(self, db):
        """Different agent claiming same function should fail."""
        db.add_claim("my_func", "agent-1")
        success, error = db.add_claim("my_func", "agent-2")

        assert success is False
        assert "agent-1" in error

    def test_expired_claim_can_be_reclaimed(self, db):
        """Expired claims should allow reclaiming."""
        # Add claim that expires immediately
        db.add_claim("my_func", "agent-1", timeout_seconds=0)

        # Small delay to ensure expiration
        time.sleep(0.01)

        # Different agent should be able to claim
        success, error = db.add_claim("my_func", "agent-2")
        assert success is True

    def test_release_claim(self, db):
        """Released claims should allow reclaiming."""
        db.add_claim("my_func", "agent-1")
        released = db.release_claim("my_func")

        assert released is True

        # Should be able to reclaim
        success, _ = db.add_claim("my_func", "agent-2")
        assert success is True

    def test_release_nonexistent_claim(self, db):
        """Releasing nonexistent claim should return False."""
        released = db.release_claim("nonexistent_func")
        assert released is False

    def test_release_with_wrong_agent_id(self, db):
        """Releasing with wrong agent_id should fail."""
        db.add_claim("my_func", "agent-1")
        released = db.release_claim("my_func", agent_id="agent-2")

        assert released is False

    def test_get_active_claims(self, db):
        """Should list all active claims."""
        db.add_claim("func1", "agent-1")
        db.add_claim("func2", "agent-2")

        claims = db.get_active_claims()

        assert len(claims) == 2
        func_names = [c["function_name"] for c in claims]
        assert "func1" in func_names
        assert "func2" in func_names


class TestFunctionState:
    """Tests for function state tracking.

    Functions progress through states: claimed -> in_progress -> matched -> committed
    """

    def test_upsert_function_creates(self, db):
        """Upserting new function should create it."""
        db.upsert_function(
            function_name="my_func",
            status="in_progress",
            local_scratch_slug="ABC123",
            match_percent=45.5,
        )

        func = db.get_function("my_func")
        assert func is not None
        assert func["status"] == "in_progress"
        assert func["local_scratch_slug"] == "ABC123"
        assert func["match_percent"] == 45.5

    def test_upsert_function_updates(self, db):
        """Upserting existing function should update it."""
        db.upsert_function("my_func", status="in_progress", match_percent=50)
        db.upsert_function("my_func", status="matched", match_percent=100)

        func = db.get_function("my_func")
        assert func["status"] == "matched"
        assert func["match_percent"] == 100

    def test_get_nonexistent_function(self, db):
        """Getting nonexistent function should return None."""
        func = db.get_function("nonexistent")
        assert func is None

    def test_get_functions_by_status(self, db):
        """Should filter functions by status."""
        db.upsert_function("func1", status="in_progress")
        db.upsert_function("func2", status="matched")
        db.upsert_function("func3", status="in_progress")

        in_progress = db.get_functions_by_status("in_progress")
        assert len(in_progress) == 2

        matched = db.get_functions_by_status("matched")
        assert len(matched) == 1

    def test_get_uncommitted_matches(self, db):
        """Should return 95%+ matches not yet committed."""
        db.upsert_function("func1", status="matched", match_percent=100, is_committed=False)
        db.upsert_function("func2", status="matched", match_percent=95, is_committed=False)
        db.upsert_function("func3", status="matched", match_percent=94, is_committed=False)  # Too low
        db.upsert_function("func4", status="matched", match_percent=100, is_committed=True)  # Already committed

        uncommitted = db.get_uncommitted_matches()

        func_names = [f["function_name"] for f in uncommitted]
        assert "func1" in func_names
        assert "func2" in func_names
        assert "func3" not in func_names
        assert "func4" not in func_names


class TestSubdirectoryLocking:
    """Tests for subdirectory worktree locking.

    Each subdirectory (e.g., ft-chara-ftFox) can be locked by one agent
    to prevent conflicts when committing to worktrees.
    """

    def test_lock_subdirectory_success(self, db):
        """Locking unlocked subdirectory should succeed."""
        success, error = db.lock_subdirectory("lb", "agent-1")
        assert success is True
        assert error is None

    def test_lock_already_locked_by_same_agent(self, db):
        """Re-locking by same agent should succeed (idempotent)."""
        db.lock_subdirectory("lb", "agent-1")
        success, error = db.lock_subdirectory("lb", "agent-1")

        # Should succeed - same agent can re-lock
        assert success is True

    def test_lock_by_different_agent_fails(self, db):
        """Different agent locking same subdirectory should fail."""
        db.lock_subdirectory("lb", "agent-1")
        success, error = db.lock_subdirectory("lb", "agent-2")

        assert success is False
        assert "agent-1" in error

    def test_unlock_subdirectory(self, db):
        """Unlocking should allow other agents to lock."""
        db.lock_subdirectory("lb", "agent-1")
        db.unlock_subdirectory("lb", "agent-1")

        success, _ = db.lock_subdirectory("lb", "agent-2")
        assert success is True

    def test_unlock_by_wrong_agent_fails(self, db):
        """Unlocking by non-owner should fail."""
        db.lock_subdirectory("lb", "agent-1")
        success = db.unlock_subdirectory("lb", "agent-2")

        assert success is False

    def test_get_subdirectory_lock(self, db):
        """Should return lock info for locked subdirectory."""
        db.lock_subdirectory("lb", "agent-1")

        lock = db.get_subdirectory_lock("lb")
        assert lock is not None
        assert lock["locked_by_agent"] == "agent-1"

    def test_get_subdirectory_lock_unlocked(self, db):
        """Should return None for unlocked/nonexistent subdirectory."""
        lock = db.get_subdirectory_lock("nonexistent")
        assert lock is None

    def test_get_agent_subdirectories(self, db):
        """Should list all subdirectories locked by an agent."""
        db.lock_subdirectory("lb", "agent-1")
        db.lock_subdirectory("gr", "agent-1")
        db.lock_subdirectory("it", "agent-2")

        agent1_dirs = db.get_agent_subdirectories("agent-1")
        assert set(agent1_dirs) == {"lb", "gr"}


class TestMatchScoring:
    """Tests for match score tracking.

    Tracks the history of match percentages for each scratch.
    """

    def test_record_match_score(self, db):
        """Recording score should create history entry."""
        # First create the scratch
        db.upsert_scratch("ABC123", "local", "http://localhost:8000")

        # Record a score (score=50, max=100 means 50% match)
        db.record_match_score("ABC123", 50, 100)

        # Check history was recorded
        with db.connection() as conn:
            cursor = conn.execute("SELECT * FROM match_history WHERE scratch_slug = ?", ("ABC123",))
            history = cursor.fetchall()

        assert len(history) == 1
        assert history[0]["score"] == 50

    def test_record_higher_score_adds_history(self, db):
        """Each score change should add to history."""
        db.upsert_scratch("ABC123", "local", "http://localhost:8000")

        db.record_match_score("ABC123", 50, 100)  # 50% match
        db.record_match_score("ABC123", 25, 100)  # 75% match (lower score = better)

        with db.connection() as conn:
            cursor = conn.execute("SELECT * FROM match_history WHERE scratch_slug = ? ORDER BY timestamp", ("ABC123",))
            history = cursor.fetchall()

        assert len(history) == 2

    def test_duplicate_score_not_recorded(self, db):
        """Same score shouldn't create duplicate history entries."""
        db.upsert_scratch("ABC123", "local", "http://localhost:8000")

        db.record_match_score("ABC123", 50, 100)
        db.record_match_score("ABC123", 50, 100)  # Same score

        with db.connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) as count FROM match_history WHERE scratch_slug = ?", ("ABC123",))
            count = cursor.fetchone()["count"]

        assert count == 1

    def test_record_match_score_with_worktree(self, db):
        """Recording score with worktree info should store it."""
        db.upsert_scratch("ABC123", "local", "http://localhost:8000")

        db.record_match_score("ABC123", 50, 100, worktree_path="/path/to/worktree", branch="subdirs/lb")

        with db.connection() as conn:
            cursor = conn.execute("SELECT worktree_path, branch FROM match_history WHERE scratch_slug = ?", ("ABC123",))
            row = cursor.fetchone()

        assert row["worktree_path"] == "/path/to/worktree"
        assert row["branch"] == "subdirs/lb"

    def test_record_match_score_worktree_optional(self, db):
        """Worktree info should be optional (NULL allowed)."""
        db.upsert_scratch("ABC123", "local", "http://localhost:8000")

        # Record without worktree info
        db.record_match_score("ABC123", 50, 100)

        with db.connection() as conn:
            cursor = conn.execute("SELECT worktree_path, branch FROM match_history WHERE scratch_slug = ?", ("ABC123",))
            row = cursor.fetchone()

        assert row["worktree_path"] is None
        assert row["branch"] is None

    def test_match_history_tracks_branch_changes(self, db):
        """History should track when work moves between branches."""
        db.upsert_scratch("ABC123", "local", "http://localhost:8000")

        # Work in first branch
        db.record_match_score("ABC123", 80, 100, branch="subdirs/lb")
        # Improve in same branch
        db.record_match_score("ABC123", 50, 100, branch="subdirs/lb")
        # Continue in different branch
        db.record_match_score("ABC123", 25, 100, branch="subdirs/ef")

        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT branch FROM match_history WHERE scratch_slug = ? ORDER BY timestamp", ("ABC123",)
            )
            branches = [row["branch"] for row in cursor.fetchall()]

        assert branches == ["subdirs/lb", "subdirs/lb", "subdirs/ef"]


class TestAuditLog:
    """Tests for audit logging.

    All state changes should be logged for debugging and history.
    """

    def test_log_audit_creates_entry(self, db):
        """Logging should create audit entry."""
        db.log_audit(
            entity_type="function",
            entity_id="my_func",
            action="test_action",
            agent_id="agent-1",
        )

        with db.connection() as conn:
            cursor = conn.execute("SELECT * FROM audit_log")
            entries = cursor.fetchall()

        assert len(entries) == 1
        assert entries[0]["action"] == "test_action"
        assert entries[0]["entity_id"] == "my_func"

    def test_claim_creates_audit_entry(self, db):
        """Adding claim should create audit entry."""
        db.add_claim("my_func", "agent-1")

        with db.connection() as conn:
            cursor = conn.execute("SELECT * FROM audit_log WHERE action = 'created' AND entity_type = 'claim'")
            entries = cursor.fetchall()

        assert len(entries) >= 1


class TestAddressTracking:
    """Tests for function address tracking and rename detection.

    Functions are identified by their canonical_address (hex like 0x80003100)
    which remains stable across renames (e.g., mn_80003100 -> MyFunction).
    """

    def test_normalize_address_hex_with_prefix(self, db):
        """Hex address with 0x prefix should normalize correctly."""
        result = db._normalize_address("0x80003100")
        assert result == "0x80003100"

    def test_normalize_address_hex_without_prefix(self, db):
        """Hex address without 0x prefix should normalize correctly."""
        result = db._normalize_address("80003100")
        assert result == "0x80003100"

    def test_normalize_address_decimal_int(self, db):
        """Decimal integer should normalize to hex."""
        result = db._normalize_address(2147496192)  # 0x80003100
        assert result == "0x80003100"

    def test_normalize_address_decimal_string(self, db):
        """Long decimal string should normalize to hex."""
        result = db._normalize_address("2147496192")  # 0x80003100
        assert result == "0x80003100"

    def test_normalize_address_lowercase(self, db):
        """Lowercase hex should normalize to uppercase."""
        result = db._normalize_address("0x800abc00")
        assert result == "0x800ABC00"

    def test_normalize_address_none(self, db):
        """None should return None."""
        result = db._normalize_address(None)
        assert result is None

    def test_get_function_by_address(self, db):
        """Should find function by canonical address."""
        db.upsert_function("my_func", canonical_address="0x80003100")

        func = db.get_function_by_address("0x80003100")
        assert func is not None
        assert func["function_name"] == "my_func"

    def test_get_function_by_address_not_found(self, db):
        """Should return None for unknown address."""
        func = db.get_function_by_address("0x99999999")
        assert func is None

    def test_get_function_by_address_normalizes(self, db):
        """Should normalize address before lookup."""
        db.upsert_function("my_func", canonical_address="0x80003100")

        # Look up with different format
        func = db.get_function_by_address("80003100")
        assert func is not None
        assert func["function_name"] == "my_func"

    def test_record_function_alias(self, db):
        """Should record function rename alias."""
        db.record_function_alias("0x80003100", "old_name", "new_name", source="manual")

        aliases = db.get_aliases_for_address("0x80003100")
        assert len(aliases) == 1
        assert aliases[0]["old_name"] == "old_name"
        assert aliases[0]["new_name"] == "new_name"
        assert aliases[0]["source"] == "manual"

    def test_record_multiple_aliases(self, db):
        """Should track multiple renames for same address."""
        db.record_function_alias("0x80003100", "name_v1", "name_v2")
        db.record_function_alias("0x80003100", "name_v2", "name_v3")

        aliases = db.get_aliases_for_address("0x80003100")
        assert len(aliases) == 2

    def test_get_function_by_name_or_address_finds_by_name(self, db):
        """Should find function by name first."""
        db.upsert_function("my_func", canonical_address="0x80003100")

        func = db.get_function_by_name_or_address(name="my_func")
        assert func is not None
        assert func["function_name"] == "my_func"

    def test_get_function_by_name_or_address_falls_back_to_address(self, db):
        """Should fall back to address when name not found."""
        db.upsert_function("my_func", canonical_address="0x80003100")

        func = db.get_function_by_name_or_address(name="wrong_name", address="0x80003100")
        assert func is not None
        assert func["function_name"] == "my_func"

    def test_bulk_update_addresses(self, db):
        """Should update addresses for multiple functions."""
        db.upsert_function("func1")
        db.upsert_function("func2")
        db.upsert_function("func3")

        updated = db.bulk_update_addresses(
            {
                "func1": "0x80003100",
                "func2": "0x80003200",
            }
        )

        assert updated == 2

        func1 = db.get_function("func1")
        assert func1["canonical_address"] == "0x80003100"

        func2 = db.get_function("func2")
        assert func2["canonical_address"] == "0x80003200"

        func3 = db.get_function("func3")
        assert func3["canonical_address"] is None

    def test_bulk_update_addresses_skips_unchanged(self, db):
        """Should not count already-set addresses as updates."""
        db.upsert_function("func1", canonical_address="0x80003100")

        updated = db.bulk_update_addresses(
            {
                "func1": "0x80003100",  # Already set
            }
        )

        assert updated == 0

    def test_merge_function_records_both_exist(self, db):
        """Should merge old record into new, preserving data."""
        db.upsert_function(
            "old_func",
            local_scratch_slug="ABC123",
            match_percent=95.0,
            status="matched",
        )
        db.upsert_function(
            "new_func",
            match_percent=100.0,
            status="matched",
        )

        result = db.merge_function_records("old_func", "new_func", "0x80003100")
        assert result is True

        # Old record should be deleted
        old = db.get_function("old_func")
        assert old is None

        # New record should have merged data
        new = db.get_function("new_func")
        assert new["local_scratch_slug"] == "ABC123"
        assert new["canonical_address"] == "0x80003100"

    def test_merge_function_records_creates_alias(self, db):
        """Merging should create an alias record."""
        db.upsert_function("old_func")

        db.merge_function_records("old_func", "new_func", "0x80003100")

        aliases = db.get_aliases_for_address("0x80003100")
        assert len(aliases) >= 1
        assert any(a["old_name"] == "old_func" for a in aliases)


class TestSchemaMigration:
    """Tests for schema migrations."""

    def test_migration_v7_to_v8_adds_worktree_columns(self, tmp_path):
        """Migration from v7 to v8 should add worktree_path and branch columns."""
        from src.db import StateDB
        from src.db.schema import get_migrations

        # Create a v7 database manually
        db_path = tmp_path / "v7_db.db"
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Create v7 match_history table (without worktree columns)
        conn.execute("""
            CREATE TABLE match_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scratch_slug TEXT NOT NULL,
                score INTEGER NOT NULL,
                max_score INTEGER NOT NULL,
                match_percent REAL NOT NULL,
                timestamp REAL DEFAULT (unixepoch('now', 'subsec'))
            )
        """)
        conn.execute("CREATE TABLE db_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO db_meta (key, value) VALUES ('schema_version', '7')")
        conn.execute(
            "INSERT INTO match_history (scratch_slug, score, max_score, match_percent) VALUES ('test', 50, 100, 50.0)"
        )
        conn.commit()
        conn.close()

        # Apply migration
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        migrations = get_migrations()
        conn.executescript(migrations[7])
        conn.execute("UPDATE db_meta SET value = '8' WHERE key = 'schema_version'")
        conn.commit()

        # Check columns exist
        cursor = conn.execute("PRAGMA table_info(match_history)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "worktree_path" in columns
        assert "branch" in columns

        # Check existing data preserved
        cursor = conn.execute("SELECT * FROM match_history WHERE scratch_slug = 'test'")
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "test"  # scratch_slug
        assert row[2] == 50  # score

        conn.close()

    def test_migration_v8_to_v9_adds_tool_issues(self, tmp_path):
        """Migration from v8 to v9 should add the tool issue queue."""
        from src.db import StateDB
        from src.db.schema import get_migrations

        # Create a minimal v8 database with only metadata. The migration must
        # be self-contained and not depend on a freshly-created v9 schema.
        db_path = tmp_path / "v8_db.db"
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE db_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO db_meta (key, value) VALUES ('schema_version', '8')")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(db_path)
        migrations = get_migrations()
        conn.executescript(migrations[8])
        conn.execute("UPDATE db_meta SET value = '9' WHERE key = 'schema_version'")
        conn.commit()

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tool_issues'")
        assert cursor.fetchone() is not None

        cursor = conn.execute("PRAGMA table_info(tool_issues)")
        columns = {row[1] for row in cursor.fetchall()}
        assert {
            "id",
            "status",
            "kind",
            "tool",
            "summary",
            "body",
            "functions",
            "agent_id",
            "session_id",
            "worktree_path",
            "branch",
            "created_at",
            "updated_at",
            "resolved_at",
            "resolved_by_agent",
            "resolution_note",
        }.issubset(columns)

        conn.close()


class TestToolIssues:
    """Tests for agent-reported tool issue tracking."""

    def test_report_tool_issue_stores_context_and_audit_log(self, db):
        """Reporting a tool issue should preserve context and audit history."""
        issue = db.report_tool_issue(
            summary="mwcc-debug local dump hangs before AFTER REGISTER COLORING",
            kind="bug",
            tool="mwcc-debug",
            body="Command hung for fn_80247510 after printing COLORGRAPH DECISIONS.",
            functions=["fn_80247510", "mnVibration_80248644"],
            agent_id="agent-issue-test",
            session_id="thread-123",
            worktree_path="/tmp/melee-worktree",
            branch="codex/mwcc-debug-test",
        )

        assert issue["id"] == 1
        assert issue["status"] == "open"
        assert issue["kind"] == "bug"
        assert issue["tool"] == "mwcc-debug"
        assert issue["functions"] == ["fn_80247510", "mnVibration_80248644"]

        stored = db.get_tool_issue(issue["id"])
        assert stored is not None
        assert stored["summary"].startswith("mwcc-debug local dump hangs")
        assert stored["session_id"] == "thread-123"
        assert stored["worktree_path"] == "/tmp/melee-worktree"

        history = db.get_history(entity_type="tool_issue", entity_id=str(issue["id"]))
        assert len(history) == 1
        assert history[0]["action"] == "reported"
        assert history[0]["agent_id"] == "agent-issue-test"

    def test_list_tool_issues_filters_open_by_tool(self, db):
        """Listing issues should support status and tool filters."""
        first = db.report_tool_issue("mwcc-debug parser loses macro scoped locals", tool="mwcc-debug")
        second = db.report_tool_issue("opseq should explain no-result queries", tool="opseq", kind="feature")
        db.resolve_tool_issue(second["id"], agent_id="fixer", resolution_note="Added clearer no-result output.")

        open_mwcc = db.list_tool_issues(status="open", tool="mwcc-debug")

        assert [issue["id"] for issue in open_mwcc] == [first["id"]]
        assert open_mwcc[0]["summary"] == "mwcc-debug parser loses macro scoped locals"

    def test_resolve_tool_issue_marks_status_and_preserves_resolution(self, db):
        """Resolving an issue should set resolution fields."""
        issue = db.report_tool_issue("mwcc-debug score-source needs JSON output", kind="feature")

        resolved = db.resolve_tool_issue(
            issue["id"],
            agent_id="tooling-agent",
            resolution_note="Implemented --json output and tests.",
        )

        assert resolved is not None
        assert resolved["status"] == "resolved"
        assert resolved["resolved_by_agent"] == "tooling-agent"
        assert resolved["resolution_note"] == "Implemented --json output and tests."

        open_issues = db.list_tool_issues(status="open")
        assert open_issues == []

    def test_note_tool_issue_appends_body_without_resolving(self, db):
        """Adding a note should preserve open status and append audit history."""
        issue = db.report_tool_issue(
            "mwcc-debug score-source needs JSON output",
            kind="feature",
            body="Initial investigation.",
        )

        noted = db.note_tool_issue(
            issue["id"],
            body="Second agent reproduced this with fn_80000000.",
            agent_id="note-agent",
        )

        assert noted is not None
        assert noted["status"] == "open"
        assert noted["resolution_note"] is None
        assert noted["resolved_at"] is None
        assert "Initial investigation." in noted["body"]
        assert "Note by note-agent" in noted["body"]
        assert "Second agent reproduced" in noted["body"]
        assert noted["updated_at"] >= issue["updated_at"]

        history = db.get_history(entity_type="tool_issue", entity_id=str(issue["id"]))
        assert sorted(entry["action"] for entry in history) == ["noted", "reported"]
        noted_history = [entry for entry in history if entry["action"] == "noted"]
        assert len(noted_history) == 1
        assert noted_history[0]["agent_id"] == "note-agent"

    def test_note_tool_issue_rejects_resolved_issues(self, db):
        """Closed issue threads should not receive open-status notes."""
        issue = db.report_tool_issue("mwcc-debug score-source needs JSON output")
        db.resolve_tool_issue(issue["id"], agent_id="fixer", resolution_note="fixed")

        with pytest.raises(ValueError, match="cannot note resolved issue"):
            db.note_tool_issue(issue["id"], body="follow-up note", agent_id="note-agent")


class TestDatabaseIntegrity:
    """Tests for database schema and integrity."""

    def test_database_file_created(self, tmp_path):
        """Database file should be created on init."""
        from src.db import StateDB

        db_path = tmp_path / "new_db.db"
        assert not db_path.exists()

        db = StateDB(db_path)
        assert db_path.exists()
        db.close()

    def test_transaction_rollback_on_error(self, db):
        """Failed transactions should rollback."""
        # Add a claim
        db.add_claim("my_func", "agent-1")

        # Try to do something that will fail inside a transaction
        try:
            with db.transaction() as conn:
                conn.execute("DELETE FROM claims WHERE function_name = ?", ("my_func",))
                # Force an error
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Claim should still exist (rollback happened)
        claims = db.get_active_claims()
        assert len(claims) == 1

    def test_concurrent_access_safety(self, tmp_path):
        """Multiple DB instances should handle locking."""
        from src.db import StateDB

        db_path = tmp_path / "shared.db"
        db1 = StateDB(db_path)
        db2 = StateDB(db_path)

        # Both should be able to operate
        db1.add_claim("func1", "agent-1")
        db2.add_claim("func2", "agent-2")

        # Both should see all claims
        claims1 = db1.get_active_claims()
        claims2 = db2.get_active_claims()

        assert len(claims1) == 2
        assert len(claims2) == 2

        db1.close()
        db2.close()


def test_tool_issues_claim_columns_migrate_from_v9(tmp_path):
    """An existing pre-claim (v9) DB with a row upgrades to gain
    claimed_by/claimed_at (NULL on the pre-existing row), and the migrated table
    shape matches a freshly created one."""
    import sqlite3

    from src.db import StateDB, reset_db
    from src.db.schema import SCHEMA_VERSION, get_migrations

    reset_db()

    # Seed a real v9 DB: run the frozen migrations[8] DDL to create tool_issues
    # at the v9 shape (no claim columns), insert a row, and stamp version 9.
    v9_path = tmp_path / "v9.db"
    seed = sqlite3.connect(v9_path)
    seed.execute(
        "CREATE TABLE db_meta (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)"
    )
    seed.executescript(get_migrations()[8])  # creates v9 tool_issues + indexes
    seed.execute(
        "INSERT INTO tool_issues (status, kind, summary) VALUES ('open', 'bug', 'legacy issue')"
    )
    seed.execute("INSERT INTO db_meta (key, value) VALUES ('schema_version', '9')")
    seed.commit()
    seed.close()

    # Instantiating StateDB runs _run_migrations 9 -> 10 (the ALTERs).
    migrated_db = StateDB(v9_path)
    with migrated_db.connection() as conn:
        migrated_cols = [
            (row["name"], row["type"])
            for row in conn.execute("PRAGMA table_info(tool_issues)")
        ]
        version = conn.execute(
            "SELECT value FROM db_meta WHERE key = 'schema_version'"
        ).fetchone()[0]

    names = [name for name, _ in migrated_cols]
    assert names[-2:] == ["claimed_by", "claimed_at"]
    assert version == str(SCHEMA_VERSION) == "10"

    # The pre-existing row gained the columns as NULL.
    legacy = migrated_db.get_tool_issue(1)
    assert legacy["summary"] == "legacy issue"
    assert legacy["claimed_by"] is None
    assert legacy["claimed_at"] is None

    migrated_db.close()
    reset_db()

    # A fresh DB (built from SCHEMA_SQL) has the identical column shape.
    fresh_db = StateDB(tmp_path / "fresh.db")
    with fresh_db.connection() as conn:
        fresh_cols = [
            (row["name"], row["type"])
            for row in conn.execute("PRAGMA table_info(tool_issues)")
        ]
    assert fresh_cols == migrated_cols
    fresh_db.close()
    reset_db()


def test_connection_sets_busy_timeout(tmp_path):
    """Writers must wait on contention instead of failing fast with
    'database is locked', so a claim race reports cleanly."""
    from src.db import StateDB, reset_db

    reset_db()
    db = StateDB(tmp_path / "bt.db")
    with db.connection() as conn:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout == 5000
    db.close()
    reset_db()
