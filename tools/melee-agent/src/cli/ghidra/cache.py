"""SQLite cache for Ghidra-derived data.

Built once via `melee-agent ghidra cache-build`; queried by xrefs/strings/func
commands without starting the JVM. Approx 200k rows total, single-file <50MB.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .._common import DECOMP_CONFIG_DIR

CACHE_DB_PATH = DECOMP_CONFIG_DIR / "ghidra.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS functions (
    addr        INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    size        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS xrefs (
    from_addr   INTEGER NOT NULL,
    to_addr     INTEGER NOT NULL,
    ref_type    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS xrefs_to_idx   ON xrefs (to_addr);
CREATE INDEX IF NOT EXISTS xrefs_from_idx ON xrefs (from_addr);

CREATE TABLE IF NOT EXISTS strings (
    addr        INTEGER PRIMARY KEY,
    value       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""


def init_schema(db_path: Path) -> None:
    """Create the schema. Idempotent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_function(db_path: Path, *, addr: int, name: str, size: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO functions(addr, name, size) VALUES (?, ?, ?)",
            (addr, name, size),
        )


def insert_xref(db_path: Path, *, from_addr: int, to_addr: int, ref_type: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO xrefs(from_addr, to_addr, ref_type) VALUES (?, ?, ?)",
            (from_addr, to_addr, ref_type),
        )


def insert_string(db_path: Path, *, addr: int, value: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO strings(addr, value) VALUES (?, ?)",
            (addr, value),
        )


def get_function(db_path: Path, addr: int) -> dict | None:
    """Get function metadata at or containing addr."""
    with _connect(db_path) as conn:
        # Try exact match first
        row = conn.execute(
            "SELECT addr, name, size FROM functions WHERE addr = ?",
            (addr,),
        ).fetchone()
        if row is not None:
            return dict(row)
        # Fall back to range scan: a function containing addr
        row = conn.execute(
            "SELECT addr, name, size FROM functions "
            "WHERE addr <= ? AND addr + size > ? "
            "ORDER BY addr DESC LIMIT 1",
            (addr, addr),
        ).fetchone()
        return dict(row) if row else None


def get_callers(db_path: Path, addr: int) -> list[dict]:
    """Functions that call `addr`.

    Returns one row per (from_addr) site, joined with the containing
    function so callers display names instead of raw addresses.
    """
    with _connect(db_path) as conn:
        return [
            dict(r) for r in conn.execute(
                """
                SELECT
                    x.from_addr AS from_addr,
                    x.ref_type  AS ref_type,
                    f.addr      AS from_function_addr,
                    COALESCE(f.name, 'unknown') AS from_function
                FROM xrefs x
                LEFT JOIN functions f
                    ON f.addr <= x.from_addr AND f.addr + f.size > x.from_addr
                WHERE x.to_addr = ?
                ORDER BY x.from_addr
                """,
                (addr,),
            )
        ]


def get_callees(db_path: Path, addr: int) -> list[dict]:
    """Functions called from inside the function at `addr`.

    Joins xref destinations back to functions; returns unique callee names.
    """
    with _connect(db_path) as conn:
        return [
            dict(r) for r in conn.execute(
                """
                SELECT DISTINCT
                    target.addr AS to_function_addr,
                    target.name AS to_function,
                    x.ref_type  AS ref_type
                FROM functions caller
                JOIN xrefs x
                    ON x.from_addr >= caller.addr
                   AND x.from_addr <  caller.addr + caller.size
                JOIN functions target
                    ON target.addr = x.to_addr
                WHERE caller.addr = ?
                ORDER BY target.addr
                """,
                (addr,),
            )
        ]


def get_strings_for_function(db_path: Path, addr: int) -> list[str]:
    """Strings referenced from inside the function at `addr`."""
    with _connect(db_path) as conn:
        return [
            r["value"] for r in conn.execute(
                """
                SELECT DISTINCT s.value AS value
                FROM functions caller
                JOIN xrefs x
                    ON x.from_addr >= caller.addr
                   AND x.from_addr <  caller.addr + caller.size
                JOIN strings s
                    ON s.addr = x.to_addr
                WHERE caller.addr = ?
                """,
                (addr,),
            )
        ]


def search_strings(db_path: Path, pattern: str, limit: int = 50) -> list[dict]:
    """Find strings whose value matches the LIKE pattern (case-insensitive)."""
    with _connect(db_path) as conn:
        like = f"%{pattern}%"
        return [
            dict(r) for r in conn.execute(
                "SELECT addr, value FROM strings WHERE value LIKE ? "
                "ORDER BY addr LIMIT ?",
                (like, limit),
            )
        ]


def build_from_project(db_path: Path, project_dir: Path, project_name: str) -> dict[str, int]:
    """Populate the cache from a Ghidra project.

    Returns counts of inserted rows: {functions, xrefs, strings}.
    Caller is responsible for ensuring pyghidra is initialized.
    """
    import pyghidra
    from ghidra.util.task import TaskMonitor

    init_schema(db_path)

    counts = {"functions": 0, "xrefs": 0, "strings": 0}

    with pyghidra.open_project(str(project_dir), project_name) as project:
        files = list(project.getProjectData().getRootFolder().getFiles())
        if not files:
            raise RuntimeError(
                f"Project at {project_dir} has no programs imported. "
                f"Run 'melee-agent ghidra setup' first."
            )

        program = files[0].getDomainObject(project, False, False, TaskMonitor.DUMMY)
        try:
            func_mgr = program.getFunctionManager()
            ref_mgr = program.getReferenceManager()
            listing = program.getListing()

            # Bulk inserts: open one connection, batch
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with _connect(db_path) as conn:
                conn.execute("DELETE FROM functions")
                conn.execute("DELETE FROM xrefs")
                conn.execute("DELETE FROM strings")

                # Functions
                for func in func_mgr.getFunctions(True):
                    body = func.getBody()
                    addr = int(func.getEntryPoint().getOffset())
                    size = int(body.getNumAddresses())
                    conn.execute(
                        "INSERT OR REPLACE INTO functions(addr, name, size) VALUES (?, ?, ?)",
                        (addr, str(func.getName()), size),
                    )
                    counts["functions"] += 1

                # Strings (must be cached before xrefs so we know which xref targets are strings)
                string_addrs: set[int] = set()
                for data in listing.getDefinedData(True):
                    if data.hasStringValue():
                        addr = int(data.getAddress().getOffset())
                        value = str(data.getValue())
                        conn.execute(
                            "INSERT OR REPLACE INTO strings(addr, value) VALUES (?, ?)",
                            (addr, value),
                        )
                        string_addrs.add(addr)
                        counts["strings"] += 1

                # Xrefs (only CALL/DATA — skip flow-internal stuff)
                # Iterate over functions, then over each function's body
                for func in func_mgr.getFunctions(True):
                    body = func.getBody()
                    addr_iter = body.getAddresses(True)
                    while addr_iter.hasNext():
                        cur_addr = addr_iter.next()
                        for ref in ref_mgr.getReferencesFrom(cur_addr):
                            to_addr = int(ref.getToAddress().getOffset())
                            ref_type = str(ref.getReferenceType())
                            # Keep CALL references and DATA references to strings only
                            if "CALL" in ref_type or to_addr in string_addrs:
                                conn.execute(
                                    "INSERT INTO xrefs(from_addr, to_addr, ref_type) VALUES (?, ?, ?)",
                                    (int(cur_addr.getOffset()), to_addr, ref_type),
                                )
                                counts["xrefs"] += 1

                # Mark cache as built
                from datetime import datetime, timezone
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    ("built_at", datetime.now(timezone.utc).isoformat()),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    ("program_name", str(program.getName())),
                )
        finally:
            program.release(project)

    return counts
