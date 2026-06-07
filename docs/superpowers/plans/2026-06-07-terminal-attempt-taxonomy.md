# Terminal Attempt Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent taxonomy and harvest campaigns from selecting rows whose attempt ledger evidence already marks them terminal.

**Architecture:** Add a shared attempt-evidence helper in `tools/melee-agent/src`, apply it to taxonomy records before queue writes, and apply it again inside harvest preview/load for stale queue files. Preserve bucket topology and rewrite only source-actionability metadata.

**Tech Stack:** Python 3.11+, pytest, existing melee-agent taxonomy and harvest modules.

---

## File Map

- Create `tools/melee-agent/src/attempt_evidence.py`: load the attempt ledger, classify terminal evidence, expose row overlay helpers and field names.
- Modify `tools/function_taxonomy_inventory.py`: import the helper, apply terminal overlays before writing artifacts, and include terminal columns in CSV/TSV output.
- Modify `tools/melee-agent/src/harvest.py`: apply terminal overlays to raw queue rows after existing harvest-ledger rebuckets and before filters/limits; expose preview counts/facets; make terminal actionabilities non-executable.
- Test `tools/melee-agent/tests/test_attempt_evidence.py`: shared helper behavior.
- Test `tools/melee-agent/tests/test_function_taxonomy_inventory.py`: inventory row and queue annotation.
- Test `tools/melee-agent/tests/test_harvest.py`: stale queue preview/load suppression and diagnostic inclusion.

## Task 1: Shared Terminal Attempt Evidence Helper

**Files:**
- Create: `tools/melee-agent/src/attempt_evidence.py`
- Test: `tools/melee-agent/tests/test_attempt_evidence.py`

- [ ] **Step 1: Write failing helper tests**

Add tests that create temporary `attempt_ledger.json` files and assert:

```python
from src.attempt_evidence import (
    TERMINAL_ATTEMPT_ACTIONABILITIES,
    apply_terminal_attempt_overlay,
    load_terminal_attempt_evidence,
)


def test_move_on_with_known_blocker_maps_to_tooling_blocked(tmp_path):
    ledger = tmp_path / "attempt_ledger.json"
    ledger.write_text(json.dumps({
        "version": 1,
        "functions": {
            "demo_fn": {
                "function": "demo_fn",
                "move_on_recommended": True,
                "move_on_reason": "repeated no-progress attempts",
                "suspected_blocker": "no-safe-materialized-pointer",
                "attempts": [
                    {
                        "index": 3,
                        "timestamp": 30.0,
                        "timestamp_utc": "2026-06-07T00:00:30+00:00",
                        "outcome": "blocked",
                        "classification": "indexed-struct-pointer",
                        "blocker": "no-safe-materialized-pointer",
                        "retained": False,
                        "note": "no source retained",
                    }
                ],
            }
        },
    }), encoding="utf-8")

    evidence = load_terminal_attempt_evidence(ledger)

    assert evidence["demo_fn"]["terminal_attempt_actionability"] == "tooling-blocked"
    assert evidence["demo_fn"]["terminal_attempt_blocker"] == "no-safe-materialized-pointer"
    assert evidence["demo_fn"]["terminal_attempt_stale_check"] == "no-tooling-fingerprint"
```

Also assert that a terminal blocker before a later retained improvement is not
active; that `apply_terminal_attempt_overlay(..., current_tool_fingerprints={
"tool_sha256": "new-tool"})` marks mismatched `tool_sha256` evidence stale
without rewriting a row; and that a row-level fingerprint such as
`row_tool_sha256` is not compared against an attempt-level `tool_sha256`.

- [ ] **Step 2: Run helper tests to verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_attempt_evidence.py -q
```

Expected: import failure for `src.attempt_evidence`.

- [ ] **Step 3: Implement the helper**

Implement:

```python
TERMINAL_ATTEMPT_ACTIONABILITIES = {
    "source-ceiling",
    "tooling-blocked",
    "diagnostic-only",
    "manual-review",
}

def load_terminal_attempt_evidence(
    path: Path | None = None,
    *,
    current_tool_commit: str | None = None,
) -> dict[str, dict[str, str]]:
    ...

def apply_terminal_attempt_overlay(
    raw: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    current_tool_fingerprints: Mapping[str, str] | None = None,
    current_tool_commit: str | None = None,
) -> dict[str, str]:
    ...

def is_active_terminal_attempt_row(raw: Mapping[str, Any]) -> bool:
    return str(raw.get("terminal_attempt_status") or "") == "active"
```

The helper should cache ledger loads by path, mtime, and size, classify only
terminal evidence that is not superseded by later retained or progress attempts,
and preserve stale evidence as metadata without rewriting the row. Staleness is
checked while applying a row overlay so harvest can pass row-specific tool
fingerprints.

- [ ] **Step 4: Run helper tests to verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_attempt_evidence.py -q
```

Expected: all tests pass.

## Task 2: Inventory Overlay And Queue Columns

**Files:**
- Modify: `tools/function_taxonomy_inventory.py`
- Test: `tools/melee-agent/tests/test_function_taxonomy_inventory.py`

- [ ] **Step 1: Write failing inventory regression test**

Add a test that generates a one-function indexed-pointer inventory with a temp
attempt ledger containing active `no-safe-materialized-pointer` evidence. Assert
that `taxonomy.records.jsonl` and `queues/indexed-struct-pointer.tsv` contain:

```python
assert record["source_actionability"] == "tooling-blocked"
assert record["headline_tool"] == "attempt-ledger"
assert record["terminal_attempt_status"] == "active"
assert record["terminal_attempt_blocker"] == "no-safe-materialized-pointer"
assert "attempt ledger terminal evidence" in record["actionability_reason"]
```

- [ ] **Step 2: Run inventory test to verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_function_taxonomy_inventory.py::test_generate_inventory_applies_terminal_attempt_evidence -q
```

Expected: failure because `attempt_ledger_path` and terminal columns do not
exist yet.

- [ ] **Step 3: Implement inventory integration**

Import the helper from `src.attempt_evidence`. Add optional
`attempt_ledger_path: Path | None = None` and
`include_terminal_attempts: bool = True` parameters to `generate_inventory`.
After all `records` are collected and before sorting/writing, load evidence once
and rewrite each record with `apply_terminal_attempt_overlay`, passing
`current_tool_fingerprints={"taxonomy_tool_sha256": <hash>}` where the hash is
based on `tools/function_taxonomy_inventory.py` and
`tools/melee-agent/src/attempt_evidence.py`. Add terminal field names to
`write_csv` and `write_queue` after `actionability_reason`.

- [ ] **Step 4: Run inventory tests to verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_function_taxonomy_inventory.py::test_generate_inventory_applies_terminal_attempt_evidence -q
```

Expected: pass.

## Task 3: Harvest Preview/Load Suppression

**Files:**
- Modify: `tools/melee-agent/src/harvest.py`
- Test: `tools/melee-agent/tests/test_harvest.py`

- [ ] **Step 1: Write failing harvest regression test**

Add a test with a stale `indexed-struct-pointer.tsv` containing
`blocked_fn` and `ready_fn`. Provide a temp attempt ledger where `blocked_fn`
has active `no-safe-materialized-pointer` evidence. Assert:

```python
rows = load_queue_rows(..., attempt_ledger_path=ledger)
assert [row.function for row in rows] == ["ready_fn"]

preview = preview_harvest_queue(..., attempt_ledger_path=ledger)
assert preview["counts"]["terminal_attempt_rows"] == 1
assert preview["terminal_attempt_facets"]["terminal_attempt_blocker"] == [
    {"value": "no-safe-materialized-pointer", "count": 1}
]

included = load_queue_rows(..., attempt_ledger_path=ledger, include_terminal_attempts=True)
assert [row.function for row in included] == ["blocked_fn", "ready_fn"]
assert select_harness(included[0]) is None
```

Add a second assertion in the same test or a neighboring test where the terminal
attempt records `tool_sha256="old-tool"` and `load_queue_rows` sees
`tool_sha256="new-tool"`. Assert the row remains eligible, has
`terminal_attempt_status == "stale"`, and keeps
`source_actionability == "current-tools-indexed-pointer"`. Also assert that if
only `row_tool_sha256` differs and the attempt records only `tool_sha256`, the
row is not marked stale from that incomparable value.

- [ ] **Step 2: Run harvest test to verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_harvest.py::test_terminal_attempt_evidence_filters_stale_queue_rows -q
```

Expected: failure because harvest does not accept/apply attempt ledger evidence.

- [ ] **Step 3: Implement harvest integration**

Import the helper. Add optional `attempt_ledger_path` and
`include_terminal_attempts` parameters to `load_queue_rows` and
`preview_harvest_queue`. Apply attempt overlays immediately after existing
source-actionability rebuckets, passing
the full `_rebucket_fingerprint_from_raw(...)` map as
`current_tool_fingerprints`, so `tool_sha256` and `row_tool_sha256` are compared
only against matching keys. Exclude active terminal rows by default before
`limit` is applied. Add preview counts and terminal facets. Update
`select_harness` to return `None` for `source-ceiling`,
`tooling-blocked`, `manual-review`, and rows with
`terminal_attempt_status == "active"` even if their actionability is
`diagnostic-only` and their primary would otherwise select a harness.

- [ ] **Step 4: Run harvest tests to verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest tools/melee-agent/tests/test_harvest.py::test_terminal_attempt_evidence_filters_stale_queue_rows -q
```

Expected: pass.

## Task 4: Verification, Smoke, And Issue Resolution

**Files:**
- No new source files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_attempt_evidence.py \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py::test_generate_inventory_applies_terminal_attempt_evidence \
  tools/melee-agent/tests/test_harvest.py::test_terminal_attempt_evidence_filters_stale_queue_rows \
  -q
```

- [ ] **Step 2: Run broader taxonomy/harvest tests**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest \
  tools/melee-agent/tests/test_function_taxonomy_inventory.py \
  tools/melee-agent/tests/test_harvest.py \
  -q
```

- [ ] **Step 3: Run CLI smoke checks**

Run a small preview against the live taxonomy queue and assert no terminal target
rows appear as executable current-tool sample rows:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli harvest preview indexed-struct-pointer --limit 5 --json
PYTHONPATH=tools/melee-agent python -m src.cli harvest preview register-allocator --limit 5 --json
```

- [ ] **Step 4: Commit and resolve #507**

Stage only the docs, helper, taxonomy, harvest, and tests. Do not stage unrelated
dirty Melee C source files. Commit with:

```bash
git commit -m "Consume terminal attempts in taxonomy queues"
melee-agent issue resolve 507 --note "fixed in <commit>"
```
