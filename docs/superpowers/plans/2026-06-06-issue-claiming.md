# Cooperative Issue Claiming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let parallel agents claim an open tooling issue (`melee-agent issue`) before working it, so two agents don't implement the same one.

**Architecture:** Add two nullable columns `claimed_by`/`claimed_at` to the existing `tool_issues` SQLite table (orthogonal to `status`, so no CHECK-recreate migration). Claims are manual-release-only (no TTL); `--force` overrides. New `claim`/`release` CLI commands, a `--available` list filter, a Claimed column, and auto-clear-on-resolve. A one-line `busy_timeout` pragma makes the claim race report cleanly instead of erroring.

**Tech Stack:** Python 3, Typer CLI, SQLite (WAL), pytest + Typer `CliRunner`.

**Reference spec:** `docs/superpowers/specs/2026-06-06-issue-claiming-design.md`

---

## File Structure

All paths relative to the worktree root `/Users/mike/code/melee/.claude/worktrees/flamboyant-aryabhata-4592f9`.

- `tools/melee-agent/src/db/schema.py` — bump `SCHEMA_VERSION`, add claim columns to the canonical `CREATE TABLE`, add migration `9`.
- `tools/melee-agent/src/db/__init__.py` — `busy_timeout` pragma in `connection()`; new `claim_tool_issue` / `release_tool_issue`; `resolve_tool_issue` clears the claim; `unclaimed_only` param on `list_tool_issues`.
- `tools/melee-agent/src/cli/issue.py` — `claim` + `release` commands; `list` Claimed column + `--available`; `show` claim annotation.
- `tools/melee-agent/tests/test_db.py` — DB-level tests (migration, busy_timeout, claim/release/resolve/list-filter).
- `tools/melee-agent/tests/test_issues.py` — CLI-level tests (claim/release/list/show/note).
- `CLAUDE.md` — document the new commands.

## Conventions for every task

- **Run all pytest commands from `tools/melee-agent`** (so `from src.db import …` resolves). Example: `cd tools/melee-agent && python -m pytest tests/test_db.py -q`.
- Coverage output is noisy (the repo enables `pytest-cov`); the pass/fail line at the bottom is what matters.
- The `db` fixture already exists at the top of `tests/test_db.py` (fresh `StateDB(tmp_path/"test_state.db")` per test). The CLI tests use the module-level `runner = CliRunner()`, `reset_db()`, `get_db(tmp_path/"state.db")`, and `strip_ansi()` already defined in `tests/test_issues.py`.
- Commit after each task. End every commit message with the trailer:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  ```

---

### Task 1: Schema migration — add claim columns to `tool_issues`

**Files:**
- Modify: `tools/melee-agent/src/db/schema.py` (`SCHEMA_VERSION` line 3; canonical `CREATE TABLE tool_issues` ~line 172-189; `get_migrations()` dict ~line 818)
- Test: `tools/melee-agent/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append this standalone test function to the END of `tools/melee-agent/tests/test_db.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::test_tool_issues_claim_columns_migrate_from_v9 -q`
Expected: FAIL — `assert names[-2:] == ["claimed_by", "claimed_at"]` fails (columns don't exist yet), or a `no such column` error.

- [ ] **Step 3: Bump the schema version**

In `tools/melee-agent/src/db/schema.py` line 3, change:

```python
SCHEMA_VERSION = 9
```

to:

```python
SCHEMA_VERSION = 10
```

- [ ] **Step 4: Add the columns to the canonical CREATE TABLE**

In `tools/melee-agent/src/db/schema.py`, in the canonical `CREATE TABLE IF NOT EXISTS tool_issues (` block (~line 172), change the final lines from:

```sql
    resolved_at REAL,
    resolved_by_agent TEXT,
    resolution_note TEXT
);
```

to (append the two new columns at the END so the column order matches `ALTER TABLE ADD COLUMN`, which appends):

```sql
    resolved_at REAL,
    resolved_by_agent TEXT,
    resolution_note TEXT,
    claimed_by TEXT,
    claimed_at REAL
);
```

**Do NOT touch** the other embedded `CREATE TABLE IF NOT EXISTS tool_issues` inside the version-8 migration (~line 796) — it is the frozen v9 shape and must stay without the claim columns.

- [ ] **Step 5: Add migration 9 → 10**

In `tools/melee-agent/src/db/schema.py`, in `get_migrations()`, find the end of the dict (after the version-8 entry's closing `""",`, just before the closing `    }`):

```python
            CREATE INDEX IF NOT EXISTS idx_tool_issues_kind ON tool_issues(kind, status);
        """,
    }
```

Insert a new entry before the closing `    }`:

```python
            CREATE INDEX IF NOT EXISTS idx_tool_issues_kind ON tool_issues(kind, status);
        """,
        # Version 9 -> 10: Add claim columns to tool_issues for cooperative claiming
        9: """
            ALTER TABLE tool_issues ADD COLUMN claimed_by TEXT;
            ALTER TABLE tool_issues ADD COLUMN claimed_at REAL;
        """,
    }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::test_tool_issues_claim_columns_migrate_from_v9 -q`
Expected: PASS (1 passed).

- [ ] **Step 7: Commit**

```bash
git add tools/melee-agent/src/db/schema.py tools/melee-agent/tests/test_db.py
git commit -m "feat(issue): add claimed_by/claimed_at columns + migration 9->10

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Set `busy_timeout` so concurrent claims block instead of erroring

**Files:**
- Modify: `tools/melee-agent/src/db/__init__.py` (`connection()` ~line 97-98)
- Test: `tools/melee-agent/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append to `tools/melee-agent/tests/test_db.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::test_connection_sets_busy_timeout -q`
Expected: FAIL — `assert 0 == 5000` (SQLite default busy_timeout is 0).

- [ ] **Step 3: Add the pragma**

In `tools/melee-agent/src/db/__init__.py`, in `connection()`, change:

```python
            # Enable foreign keys and WAL mode for better concurrency
            _local.connection.execute("PRAGMA foreign_keys = ON")
            _local.connection.execute("PRAGMA journal_mode = WAL")
```

to:

```python
            # Enable foreign keys and WAL mode for better concurrency
            _local.connection.execute("PRAGMA foreign_keys = ON")
            _local.connection.execute("PRAGMA journal_mode = WAL")
            # Wait up to 5s on write contention instead of failing fast with
            # "database is locked" — lets BEGIN IMMEDIATE losers retry and read
            # the committed claim rather than raising OperationalError.
            _local.connection.execute("PRAGMA busy_timeout = 5000")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::test_connection_sets_busy_timeout -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/db/__init__.py tools/melee-agent/tests/test_db.py
git commit -m "feat(db): set busy_timeout=5000 so write contention blocks not errors

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `claim_tool_issue` DB method

**Files:**
- Modify: `tools/melee-agent/src/db/__init__.py` (add method after `note_tool_issue`, ~line 592)
- Test: `tools/melee-agent/tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append this new test class to the END of `tools/melee-agent/tests/test_db.py`:

```python
class TestToolIssueClaims:
    """Tests for cooperative claiming of tool issues."""

    def test_claim_sets_owner(self, db):
        issue = db.report_tool_issue(summary="fix the thing", agent_id="reporter")
        claimed = db.claim_tool_issue(issue["id"], "agent-1")
        assert claimed["claimed_by"] == "agent-1"
        assert claimed["claimed_at"] is not None

    def test_claim_conflict_different_agent(self, db):
        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        db.claim_tool_issue(issue["id"], "agent-1")
        with pytest.raises(ValueError, match="already claimed by agent-1"):
            db.claim_tool_issue(issue["id"], "agent-2")

    def test_claim_force_takes_over(self, db):
        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        db.claim_tool_issue(issue["id"], "agent-1")
        taken = db.claim_tool_issue(issue["id"], "agent-2", force=True)
        assert taken["claimed_by"] == "agent-2"

    def test_claim_same_agent_is_idempotent(self, db):
        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        first = db.claim_tool_issue(issue["id"], "agent-1")
        second = db.claim_tool_issue(issue["id"], "agent-1")
        assert second["claimed_by"] == "agent-1"
        assert second["claimed_at"] >= first["claimed_at"]

    def test_claim_resolved_errors(self, db):
        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        db.resolve_tool_issue(issue["id"], agent_id="agent-1")
        with pytest.raises(ValueError, match="cannot claim resolved"):
            db.claim_tool_issue(issue["id"], "agent-1")

    def test_claim_missing_returns_none(self, db):
        assert db.claim_tool_issue(99999, "agent-1") is None

    def test_claim_force_records_displaced_owner_in_audit(self, db):
        import json as _json

        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        db.claim_tool_issue(issue["id"], "agent-1")
        db.claim_tool_issue(issue["id"], "agent-2", force=True)

        with db.connection() as conn:
            row = conn.execute(
                """
                SELECT old_value FROM audit_log
                WHERE entity_type = 'tool_issue' AND entity_id = ? AND action = 'claimed'
                ORDER BY id DESC LIMIT 1
                """,
                (str(issue["id"]),),
            ).fetchone()
        old = _json.loads(row["old_value"])
        assert old["claimed_by"] == "agent-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::TestToolIssueClaims -q`
Expected: FAIL — `AttributeError: 'StateDB' object has no attribute 'claim_tool_issue'`.

- [ ] **Step 3: Implement the method**

In `tools/melee-agent/src/db/__init__.py`, immediately after the end of `note_tool_issue` (the `return issue` near line 592, before the `# ===` section comment that follows), add:

```python
    def claim_tool_issue(
        self,
        issue_id: int,
        agent_id: str,
        force: bool = False,
    ) -> dict | None:
        """Claim an open tool issue so other agents skip it.

        Returns the updated issue, or None if the issue does not exist.
        Raises ValueError if the issue is resolved, or already claimed by a
        different agent without ``force``.
        """
        now = time.time()

        with self.transaction() as conn:
            old_row = conn.execute("SELECT * FROM tool_issues WHERE id = ?", (issue_id,)).fetchone()
            old_value = self._decode_tool_issue_row(old_row)
            if old_value is None:
                return None
            if old_value["status"] != "open":
                raise ValueError(f"cannot claim resolved issue #{issue_id}")

            current = old_value.get("claimed_by")
            if current and current != agent_id and not force:
                raise ValueError(
                    f"issue #{issue_id} already claimed by {current}; use --force to take over"
                )

            conn.execute(
                """
                UPDATE tool_issues
                SET claimed_by = ?,
                    claimed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (agent_id, now, now, issue_id),
            )
            new_row = conn.execute("SELECT * FROM tool_issues WHERE id = ?", (issue_id,)).fetchone()
            issue = self._decode_tool_issue_row(new_row)

            self.log_audit(
                "tool_issue",
                str(issue_id),
                "claimed",
                agent_id=agent_id,
                old_value=old_value,
                new_value=issue,
            )

        return issue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::TestToolIssueClaims -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/db/__init__.py tools/melee-agent/tests/test_db.py
git commit -m "feat(db): add claim_tool_issue with force takeover + audit

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `release_tool_issue` DB method

**Files:**
- Modify: `tools/melee-agent/src/db/__init__.py` (add method after `claim_tool_issue`)
- Test: `tools/melee-agent/tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append these methods INSIDE the existing `class TestToolIssueClaims` in `tools/melee-agent/tests/test_db.py`:

```python
    def test_release_clears_claim(self, db):
        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        db.claim_tool_issue(issue["id"], "agent-1")
        released = db.release_tool_issue(issue["id"], "agent-1")
        assert released["claimed_by"] is None
        assert released["claimed_at"] is None

    def test_release_unclaimed_errors(self, db):
        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        with pytest.raises(ValueError, match="is not claimed"):
            db.release_tool_issue(issue["id"], "agent-1")

    def test_release_non_owner_errors(self, db):
        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        db.claim_tool_issue(issue["id"], "agent-1")
        with pytest.raises(ValueError, match="claimed by agent-1"):
            db.release_tool_issue(issue["id"], "agent-2")

    def test_release_force_non_owner(self, db):
        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        db.claim_tool_issue(issue["id"], "agent-1")
        released = db.release_tool_issue(issue["id"], "agent-2", force=True)
        assert released["claimed_by"] is None

    def test_release_missing_returns_none(self, db):
        assert db.release_tool_issue(99999, "agent-1") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/melee-agent && python -m pytest "tests/test_db.py::TestToolIssueClaims" -k release -q`
Expected: FAIL — `AttributeError: 'StateDB' object has no attribute 'release_tool_issue'`.

- [ ] **Step 3: Implement the method**

In `tools/melee-agent/src/db/__init__.py`, immediately after the `claim_tool_issue` method you added in Task 3, add:

```python
    def release_tool_issue(
        self,
        issue_id: int,
        agent_id: str | None = None,
        force: bool = False,
    ) -> dict | None:
        """Release a claim on a tool issue without resolving it.

        Returns the updated issue, or None if the issue does not exist.
        Raises ValueError if the issue is not claimed, or claimed by a
        different agent without ``force``.
        """
        now = time.time()

        with self.transaction() as conn:
            old_row = conn.execute("SELECT * FROM tool_issues WHERE id = ?", (issue_id,)).fetchone()
            old_value = self._decode_tool_issue_row(old_row)
            if old_value is None:
                return None

            current = old_value.get("claimed_by")
            if not current:
                raise ValueError(f"issue #{issue_id} is not claimed")
            if current != agent_id and not force:
                raise ValueError(
                    f"issue #{issue_id} claimed by {current}; use --force to release"
                )

            conn.execute(
                """
                UPDATE tool_issues
                SET claimed_by = NULL,
                    claimed_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, issue_id),
            )
            new_row = conn.execute("SELECT * FROM tool_issues WHERE id = ?", (issue_id,)).fetchone()
            issue = self._decode_tool_issue_row(new_row)

            self.log_audit(
                "tool_issue",
                str(issue_id),
                "released",
                agent_id=agent_id,
                old_value=old_value,
                new_value=issue,
            )

        return issue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest "tests/test_db.py::TestToolIssueClaims" -k release -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/db/__init__.py tools/melee-agent/tests/test_db.py
git commit -m "feat(db): add release_tool_issue with force + owner check

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `resolve_tool_issue` clears the claim

**Files:**
- Modify: `tools/melee-agent/src/db/__init__.py` (`resolve_tool_issue` UPDATE, ~line 515-526)
- Test: `tools/melee-agent/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append this method INSIDE `class TestToolIssueClaims` in `tools/melee-agent/tests/test_db.py`:

```python
    def test_resolve_clears_claim(self, db):
        issue = db.report_tool_issue(summary="x", agent_id="reporter")
        db.claim_tool_issue(issue["id"], "agent-1")
        resolved = db.resolve_tool_issue(issue["id"], agent_id="agent-1")
        assert resolved["status"] == "resolved"
        assert resolved["claimed_by"] is None
        assert resolved["claimed_at"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::TestToolIssueClaims::test_resolve_clears_claim -q`
Expected: FAIL — `assert 'agent-1' is None` (resolve does not yet clear the claim).

- [ ] **Step 3: Update the resolve UPDATE**

In `tools/melee-agent/src/db/__init__.py`, in `resolve_tool_issue`, change:

```python
                UPDATE tool_issues
                SET status = 'resolved',
                    updated_at = ?,
                    resolved_at = ?,
                    resolved_by_agent = ?,
                    resolution_note = ?
                WHERE id = ?
```

to:

```python
                UPDATE tool_issues
                SET status = 'resolved',
                    claimed_by = NULL,
                    claimed_at = NULL,
                    updated_at = ?,
                    resolved_at = ?,
                    resolved_by_agent = ?,
                    resolution_note = ?
                WHERE id = ?
```

(The parameter tuple is unchanged — `NULL` is literal in the SQL.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::TestToolIssueClaims::test_resolve_clears_claim -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/db/__init__.py tools/melee-agent/tests/test_db.py
git commit -m "feat(db): resolve_tool_issue clears the claim

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `list_tool_issues` gains `unclaimed_only` filter

**Files:**
- Modify: `tools/melee-agent/src/db/__init__.py` (`list_tool_issues` signature + query, ~line 462-491)
- Test: `tools/melee-agent/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append this method INSIDE `class TestToolIssueClaims` in `tools/melee-agent/tests/test_db.py`:

```python
    def test_list_unclaimed_only_filters_claimed(self, db):
        claimed = db.report_tool_issue(summary="claimed one", agent_id="r")
        free = db.report_tool_issue(summary="free one", agent_id="r")
        db.claim_tool_issue(claimed["id"], "agent-1")

        available_ids = {i["id"] for i in db.list_tool_issues(unclaimed_only=True)}
        assert free["id"] in available_ids
        assert claimed["id"] not in available_ids

        # Default list still shows both (claimed-by-others stays visible).
        all_ids = {i["id"] for i in db.list_tool_issues()}
        assert {claimed["id"], free["id"]} <= all_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::TestToolIssueClaims::test_list_unclaimed_only_filters_claimed -q`
Expected: FAIL — `TypeError: list_tool_issues() got an unexpected keyword argument 'unclaimed_only'`.

- [ ] **Step 3: Add the param and filter clause**

In `tools/melee-agent/src/db/__init__.py`, change the `list_tool_issues` signature:

```python
    def list_tool_issues(
        self,
        status: str | None = "open",
        tool: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
```

to add the new parameter:

```python
    def list_tool_issues(
        self,
        status: str | None = "open",
        tool: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        unclaimed_only: bool = False,
    ) -> list[dict]:
```

Then, in the same method, find the `kind` filter clause:

```python
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY created_at DESC LIMIT ?"
```

and insert the unclaimed filter before the `ORDER BY` line:

```python
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        if unclaimed_only:
            query += " AND claimed_by IS NULL"
        query += " ORDER BY created_at DESC LIMIT ?"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py::TestToolIssueClaims::test_list_unclaimed_only_filters_claimed -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the whole DB test file to confirm no regressions**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py -q`
Expected: PASS (all tests, including the pre-existing ones).

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/db/__init__.py tools/melee-agent/tests/test_db.py
git commit -m "feat(db): list_tool_issues unclaimed_only filter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `issue claim` CLI command

**Files:**
- Modify: `tools/melee-agent/src/cli/issue.py` (add command after `resolve_command`, end of file)
- Test: `tools/melee-agent/tests/test_issues.py`

- [ ] **Step 1: Write the failing test**

Append to the END of `tools/melee-agent/tests/test_issues.py`:

```python
def test_issue_claim_from_cli(tmp_path):
    """claim sets the owner; a second agent conflicts; --force takes over."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="claimable issue", agent_id="reporter")

    result = runner.invoke(
        app, ["issue", "claim", str(issue["id"]), "--agent-id", "agent-1"]
    )
    assert result.exit_code == 0, result.stdout
    assert "Claimed issue" in strip_ansi(result.stdout)
    assert db.get_tool_issue(issue["id"])["claimed_by"] == "agent-1"

    # Second agent conflicts (exit 2), message names owner and --force.
    result = runner.invoke(
        app, ["issue", "claim", str(issue["id"]), "--agent-id", "agent-2"]
    )
    assert result.exit_code == 2
    out = strip_ansi(result.stdout)
    assert "agent-1" in out
    assert "--force" in out

    # Force takeover succeeds.
    result = runner.invoke(
        app, ["issue", "claim", str(issue["id"]), "--agent-id", "agent-2", "--force"]
    )
    assert result.exit_code == 0, result.stdout
    assert db.get_tool_issue(issue["id"])["claimed_by"] == "agent-2"


def test_issue_claim_missing_issue(tmp_path):
    reset_db()
    get_db(tmp_path / "state.db")
    result = runner.invoke(app, ["issue", "claim", "9999", "--agent-id", "agent-1"])
    assert result.exit_code == 1
    assert "not found" in strip_ansi(result.stdout).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_issues.py::test_issue_claim_from_cli -q`
Expected: FAIL — Typer reports no such command `claim` (exit code 2 with "No such command", but the assertion on "Claimed issue" fails first / command missing).

- [ ] **Step 3: Implement the command**

In `tools/melee-agent/src/cli/issue.py`, add at the END of the file (after `resolve_command`):

```python
@issue_app.command("claim")
def claim_command(
    issue_id: Annotated[int, typer.Argument(help="Issue ID")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Take over a claim held by another agent"),
    ] = False,
    agent_id: Annotated[
        str | None,
        typer.Option("--agent-id", help="Claiming agent ID; auto-detected when omitted"),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Claim an open issue so other agents skip it."""
    resolved_agent = agent_id or _get_agent_id()
    try:
        issue = get_db().claim_tool_issue(issue_id, agent_id=resolved_agent, force=force)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    if issue is None:
        console.print(f"[red]Issue not found: {issue_id}[/red]")
        raise typer.Exit(1)

    if output_json:
        _echo_json(issue)
        return

    console.print(
        f"[green]Claimed issue #{issue['id']}[/green] ({issue['claimed_by']}): {issue['summary']}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_issues.py::test_issue_claim_from_cli tests/test_issues.py::test_issue_claim_missing_issue -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/issue.py tools/melee-agent/tests/test_issues.py
git commit -m "feat(cli): add 'issue claim' command

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: `issue release` CLI command

**Files:**
- Modify: `tools/melee-agent/src/cli/issue.py` (add command after `claim_command`)
- Test: `tools/melee-agent/tests/test_issues.py`

- [ ] **Step 1: Write the failing test**

Append to the END of `tools/melee-agent/tests/test_issues.py`:

```python
def test_issue_release_from_cli(tmp_path):
    """Owner releases; non-owner needs --force."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="releasable", agent_id="reporter")
    db.claim_tool_issue(issue["id"], "agent-1")

    # Non-owner without --force fails.
    result = runner.invoke(
        app, ["issue", "release", str(issue["id"]), "--agent-id", "agent-2"]
    )
    assert result.exit_code == 2
    assert "agent-1" in strip_ansi(result.stdout)

    # Owner releases.
    result = runner.invoke(
        app, ["issue", "release", str(issue["id"]), "--agent-id", "agent-1"]
    )
    assert result.exit_code == 0, result.stdout
    assert "Released issue" in strip_ansi(result.stdout)
    assert db.get_tool_issue(issue["id"])["claimed_by"] is None

    # Releasing an unclaimed issue errors.
    result = runner.invoke(
        app, ["issue", "release", str(issue["id"]), "--agent-id", "agent-1"]
    )
    assert result.exit_code == 2
    assert "not claimed" in strip_ansi(result.stdout)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_issues.py::test_issue_release_from_cli -q`
Expected: FAIL — no such command `release`.

- [ ] **Step 3: Implement the command**

In `tools/melee-agent/src/cli/issue.py`, add after `claim_command`:

```python
@issue_app.command("release")
def release_command(
    issue_id: Annotated[int, typer.Argument(help="Issue ID")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Release a claim held by another agent"),
    ] = False,
    agent_id: Annotated[
        str | None,
        typer.Option("--agent-id", help="Releasing agent ID; auto-detected when omitted"),
    ] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
    """Release your claim on an issue without resolving it."""
    resolved_agent = agent_id or _get_agent_id()
    try:
        issue = get_db().release_tool_issue(issue_id, agent_id=resolved_agent, force=force)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    if issue is None:
        console.print(f"[red]Issue not found: {issue_id}[/red]")
        raise typer.Exit(1)

    if output_json:
        _echo_json(issue)
        return

    console.print(f"[green]Released issue #{issue['id']}[/green]: {issue['summary']}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_issues.py::test_issue_release_from_cli -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/issue.py tools/melee-agent/tests/test_issues.py
git commit -m "feat(cli): add 'issue release' command

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: `issue list` — Claimed column + `--available` filter

**Files:**
- Modify: `tools/melee-agent/src/cli/issue.py` (`list_command`, ~line 473-515)
- Test: `tools/melee-agent/tests/test_issues.py`

- [ ] **Step 1: Write the failing test**

Append to the END of `tools/melee-agent/tests/test_issues.py`:

```python
def test_issue_list_claim_column_and_available_filter(tmp_path):
    """list annotates the owner and --available hides claimed-by-others
    identically in --json and table modes."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    claimed = db.report_tool_issue(summary="claimed one", agent_id="r")
    free = db.report_tool_issue(summary="free one", agent_id="r")
    db.claim_tool_issue(claimed["id"], "agent-1")

    # Plain table render works.
    assert runner.invoke(app, ["issue", "list"]).exit_code == 0

    # Default --json shows both and annotates the owner.
    payload = json.loads(runner.invoke(app, ["issue", "list", "--json"]).stdout)
    by_id = {i["id"]: i for i in payload}
    assert by_id[claimed["id"]]["claimed_by"] == "agent-1"
    assert by_id[free["id"]]["claimed_by"] is None

    # --available hides claimed-by-others.
    payload = json.loads(
        runner.invoke(app, ["issue", "list", "--available", "--json"]).stdout
    )
    ids = {i["id"] for i in payload}
    assert free["id"] in ids
    assert claimed["id"] not in ids

    # The --unclaimed alias behaves the same and the table render works.
    assert runner.invoke(app, ["issue", "list", "--unclaimed"]).exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_issues.py::test_issue_list_claim_column_and_available_filter -q`
Expected: FAIL — `--available` is not a known option (Typer exits 2), so the first `--available` invocation errors.

- [ ] **Step 3: Add the option, pass-through, and column**

In `tools/melee-agent/src/cli/issue.py`, change the `list_command` signature:

```python
def list_command(
    status: Annotated[str, typer.Option("--status", "-s", help="Filter by status: open, resolved, all")] = "open",
    tool: Annotated[str | None, typer.Option("--tool", "-t", help="Filter by tool")] = None,
    kind: Annotated[str | None, typer.Option("--kind", "-k", help="Filter by kind")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum issues to show")] = 50,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
```

to add the `available` flag (with `--unclaimed` as an alias):

```python
def list_command(
    status: Annotated[str, typer.Option("--status", "-s", help="Filter by status: open, resolved, all")] = "open",
    tool: Annotated[str | None, typer.Option("--tool", "-t", help="Filter by tool")] = None,
    kind: Annotated[str | None, typer.Option("--kind", "-k", help="Filter by kind")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum issues to show")] = 50,
    available: Annotated[
        bool,
        typer.Option("--available", "--unclaimed", help="Show only unclaimed open issues"),
    ] = False,
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
):
```

Change the DB call:

```python
        issues = db.list_tool_issues(status=status, tool=tool, kind=kind, limit=limit)
```

to:

```python
        issues = db.list_tool_issues(
            status=status, tool=tool, kind=kind, limit=limit, unclaimed_only=available
        )
```

Change the table column definitions (note the reduced widths to make room for the new column):

```python
    table.add_column("Summary", max_width=60)
    table.add_column("Functions", max_width=28)
```

to:

```python
    table.add_column("Summary", max_width=48)
    table.add_column("Functions", max_width=22)
    table.add_column("Claimed", max_width=16)
```

Change the `add_row` call:

```python
        table.add_row(
            str(issue["id"]),
            issue["status"],
            issue["kind"],
            issue.get("tool") or "-",
            issue["summary"],
            ", ".join(issue.get("functions") or []) or "-",
        )
```

to add the claimed cell:

```python
        table.add_row(
            str(issue["id"]),
            issue["status"],
            issue["kind"],
            issue.get("tool") or "-",
            issue["summary"],
            ", ".join(issue.get("functions") or []) or "-",
            issue.get("claimed_by") or "-",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_issues.py::test_issue_list_claim_column_and_available_filter -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/issue.py tools/melee-agent/tests/test_issues.py
git commit -m "feat(cli): issue list Claimed column + --available filter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: `issue show` — annotate the claim owner

**Files:**
- Modify: `tools/melee-agent/src/cli/issue.py` (`import time` near top; `show_command` ~line 545-548)
- Test: `tools/melee-agent/tests/test_issues.py`

- [ ] **Step 1: Write the failing test**

Append to the END of `tools/melee-agent/tests/test_issues.py`:

```python
def test_issue_show_displays_claim_owner(tmp_path):
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="x", agent_id="r")
    db.claim_tool_issue(issue["id"], "agent-1")

    result = runner.invoke(app, ["issue", "show", str(issue["id"])])
    assert result.exit_code == 0, result.stdout
    out = strip_ansi(result.stdout)
    assert "Claimed by:" in out
    assert "agent-1" in out


def test_issue_show_unclaimed_has_no_claim_line(tmp_path):
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="x", agent_id="r")

    result = runner.invoke(app, ["issue", "show", str(issue["id"])])
    assert result.exit_code == 0, result.stdout
    assert "Claimed by:" not in strip_ansi(result.stdout)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_issues.py::test_issue_show_displays_claim_owner -q`
Expected: FAIL — `assert 'Claimed by:' in out` fails (show does not print the claim).

- [ ] **Step 3: Add the `time` import and the claim line**

In `tools/melee-agent/src/cli/issue.py`, the top imports currently are:

```python
import json
import os
import re
import subprocess
```

Add `time`:

```python
import json
import os
import re
import subprocess
import time
```

Then in `show_command`, find:

```python
    if issue.get("branch"):
        console.print(f"[bold]Branch:[/bold] {issue['branch']}")
    if issue.get("body"):
        console.print(f"\n{issue['body']}")
```

and insert the claim block between the branch line and the body line:

```python
    if issue.get("branch"):
        console.print(f"[bold]Branch:[/bold] {issue['branch']}")
    if issue.get("claimed_by"):
        stamp = (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(issue["claimed_at"]))
            if issue.get("claimed_at")
            else "-"
        )
        console.print(f"[bold]Claimed by:[/bold] {issue['claimed_by']} (at {stamp})")
    if issue.get("body"):
        console.print(f"\n{issue['body']}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_issues.py::test_issue_show_displays_claim_owner tests/test_issues.py::test_issue_show_unclaimed_has_no_claim_line -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/issue.py tools/melee-agent/tests/test_issues.py
git commit -m "feat(cli): issue show annotates claim owner

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Lock in `note`-on-claimed behavior + document the commands

**Files:**
- Test: `tools/melee-agent/tests/test_issues.py`
- Modify: `CLAUDE.md` (issue command block, ~line 62-66)

- [ ] **Step 1: Write the behavior-locking test (no code change expected)**

Append to the END of `tools/melee-agent/tests/test_issues.py`:

```python
def test_note_allowed_on_claimed_issue_by_other_agent(tmp_path):
    """note is not ownership-gated: any agent may annotate a claimed (open)
    issue, and noting does not disturb the claim."""
    reset_db()
    db = get_db(tmp_path / "state.db")
    issue = db.report_tool_issue(summary="x", agent_id="r")
    db.claim_tool_issue(issue["id"], "agent-1")

    result = runner.invoke(
        app,
        [
            "issue",
            "note",
            str(issue["id"]),
            "--body",
            "extra context from a passer-by",
            "--agent-id",
            "agent-2",
        ],
    )
    assert result.exit_code == 0, result.stdout
    updated = db.get_tool_issue(issue["id"])
    assert "extra context from a passer-by" in (updated["body"] or "")
    assert updated["claimed_by"] == "agent-1"
```

- [ ] **Step 2: Run the test to verify it already passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_issues.py::test_note_allowed_on_claimed_issue_by_other_agent -q`
Expected: PASS (1 passed) — this documents existing behavior; no code change needed. If it FAILS, stop and investigate before editing anything.

- [ ] **Step 3: Document the new commands in CLAUDE.md**

In `CLAUDE.md`, find the issue command block:

```
# Tool issue reporting (bugs, feature requests, papercuts, blockers)
melee-agent issue report "short summary" --tool mwcc-debug --kind bug --function <func>
melee-agent issue list --status open
melee-agent issue show <id>
melee-agent issue resolve <id> --note "fixed in <commit-or-summary>"
```

and replace it with:

```
# Tool issue reporting (bugs, feature requests, papercuts, blockers)
melee-agent issue report "short summary" --tool mwcc-debug --kind bug --function <func>
melee-agent issue list --status open
melee-agent issue list --available          # only unclaimed open issues (grab one of these)
melee-agent issue show <id>
melee-agent issue claim <id>                # claim before working it; fails if already claimed
melee-agent issue release <id>              # give a claim back without resolving
melee-agent issue resolve <id> --note "fixed in <commit-or-summary>"  # also clears the claim
```

Then add this sentence to the Tooling Feedback prose paragraph (right after the
heredoc example that ends with `... and what this blocked`):

```
Before starting work on an issue, run `melee-agent issue claim <id>` so other
parallel agents skip it; there is no auto-expiry, so if an agent abandons a
claim, recover it with `melee-agent issue release <id> --force` (or
`melee-agent issue claim <id> --force` to take it over directly).
```

- [ ] **Step 4: Run the full test suite for the touched files**

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py tests/test_issues.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/tests/test_issues.py CLAUDE.md
git commit -m "docs: document issue claim/release/--available; lock note-on-claimed

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the full melee-agent test suite** to confirm nothing else regressed:

Run: `cd tools/melee-agent && python -m pytest tests/test_db.py tests/test_issues.py -q`
Expected: all pass.

- [ ] **Isolated smoke test** (optional). The CLI has **no DB-path override** (`DEFAULT_DB_PATH` is hardcoded to `~/.config/decomp-me/agent_state.db`), so do **NOT** smoke-test the `issue` CLI directly — it would mutate the real shared queue. Instead exercise the DB layer against a temp path:

```bash
cd tools/melee-agent && python - <<'PY'
import tempfile, pathlib
from src.db import StateDB
db = StateDB(pathlib.Path(tempfile.mkdtemp()) / "smoke.db")
i = db.report_tool_issue(summary="smoke", agent_id="reporter")
print("claim ->", db.claim_tool_issue(i["id"], "agent-1")["claimed_by"])
print("available ->", [x["id"] for x in db.list_tool_issues(unclaimed_only=True)])
try:
    db.claim_tool_issue(i["id"], "agent-2")
except ValueError as e:
    print("conflict ->", e)
print("force ->", db.claim_tool_issue(i["id"], "agent-2", force=True)["claimed_by"])
print("release ->", db.release_tool_issue(i["id"], "agent-2")["claimed_by"])
db.close()
PY
```

Expected: `claim -> agent-1`, `available -> []`, a `conflict ->` line mentioning `--force`, `force -> agent-2`, `release -> None`. The pytest suite already covers every command path against temp DBs, so this is purely confirmatory.

## Notes for the implementer

- **Test isolation:** every test that builds a `StateDB` directly must `close()` it and call `reset_db()` when done (the `db` fixture does this; the standalone migration/busy_timeout tests do it explicitly). The thread-local connection is shared across `StateDB` instances, so a leaked open connection to one path corrupts the next test.
- **Column order matters:** the canonical `CREATE TABLE` appends `claimed_by`/`claimed_at` LAST because `ALTER TABLE ADD COLUMN` appends; the migration test asserts the two shapes match.
- **Do not** add the claim columns to the version-8 embedded `CREATE TABLE` in `get_migrations()` — that would break the 8→10 upgrade with a duplicate-column error.
- All new `ValueError` messages are asserted by substring in tests; keep the wording (`already claimed by`, `is not claimed`, `claimed by`, `cannot claim resolved`, `--force`) intact or update the tests in lockstep.
