# Exact x86 CFG Semantic Memo Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the retail GC/1.2.5n whole-PE producer proof restartable and memory-bounded by interning repeated dependencies and persisting exact-call readable-global summaries in a strict normalized store.

**Architecture:** Keep `_DirectCfgRecovery`'s semantic rules unchanged while routing its readable-global memo through a small private store interface. The default store is pooled in memory; checkpointed whole-PE recovery uses a canonical-JSON SQLite store with a bounded LRU, exact key verification, explicit semantic versioning, and ordinary dependency revalidation on every hit.

**Tech Stack:** Python 3.11, frozen dataclasses, canonical JSON, SHA-256, zlib, stdlib `sqlite3`, pytest, Ruff

## Global Constraints

- Exact compiler SHA-256 remains `ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
- Do not change any instruction, edge, target, dependency, proof rule, cap, diagnostic, fail-closed decision, or canonical artifact.
- Every persistent hit must pass exact key-byte, image-hash, semantic-version, schema, and current dependency-fingerprint validation.
- Persistent payloads use strict canonical JSON; production code must not unpickle checkpoint data.
- Cache state, host paths, timing, SQLite layout, and cache digests never enter canonical proof output.
- The current 16 GB host acceptance bounds are less than 8 GB physical footprint, no increase in swap, and less than 2 GB persistent storage for the observed 422,307 entries.
- Preserve unrelated `.agents/`, `.coverage`, and `.pi/` files and all user changes.
- Use branch-local commands from `/Users/mike/code/melee/.claude/worktrees/codex-issue-1240-retail-pcode-proof`.

---

### Task 1: Stabilize the measured in-process safeguards

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`

**Interfaces:**
- Consumes: existing `_producer_dependency_fingerprint`, `_bounded_object_result_provenance`, and `_finite_object_byte_register_values_before_uncached`
- Produces: version-counted dependency fingerprint reuse and bounded object-result provenance that later memo stores can retain safely

- [ ] **Step 1: Verify the dependency-fingerprint RED/GREEN regression**

Retain this regression in `tools/melee-agent/tests/test_retro_x86_cfg.py`:

```python
def test_global_slot_dependency_fingerprint_reuses_unchanged_writer_inventory(
    tmp_path,
):
    class CountingSet(set):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    image = load_cfg_image(tmp_path)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    slot = 0x00402300
    writes = CountingSet(
        {
            _GlobalSlotWrite(
                instruction_address=0x00401013,
                value=0,
                provenance="initial-writer",
            )
        }
    )
    recovery.global_slot_writes[slot] = writes
    recovery.global_slot_write_count = len(writes)

    first = recovery._producer_dependency_fingerprint("global-slot", slot)
    second = recovery._producer_dependency_fingerprint("global-slot", slot)
    assert second == first
    assert writes.iterations == 1

    writes.add(
        _GlobalSlotWrite(
            instruction_address=0x00401018,
            value=None,
            provenance="new-unknown-writer",
        )
    )
    recovery.global_slot_write_count += 1
    assert recovery._producer_dependency_fingerprint("global-slot", slot) != first
    assert writes.iterations == 2
```

Run:

```bash
python -m pytest -o addopts='' -q \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k global_slot_dependency_fingerprint_reuses_unchanged_writer_inventory
```

Expected: PASS.

- [ ] **Step 2: Verify the bounded-provenance semantic-marker regression**

Retain the regression that injects more than 4,096 bytes of nested provenance
and requires all control-significant markers:

```python
assert len(result[1]) < 5000
assert "provenance-sha256=" in result[1]
assert "guarded-object-association-induction" in result[1]
assert "readable-global-call-induction" in result[1]
assert "global-append-tail=" in result[1]
```

Run:

```bash
python -m pytest -o addopts='' -q \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'bounded_object_provenance or object_register_bounds_nested_provenance'
```

Expected: all selected tests PASS.

- [ ] **Step 3: Run static checks for the existing safeguards**

Run:

```bash
python -m ruff check \
  tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
python -m py_compile tools/mwcc_retro/x86_cfg.py
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit the independently reviewable safeguards**

```bash
git add \
  tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "perf(mwcc-retro): bound semantic proof memo costs"
```

---

### Task 2: Add a pooled in-memory readable-global memo store

**Files:**
- Create: `tools/mwcc_retro/semantic_memo.py`
- Create: `tools/melee-agent/tests/test_retro_semantic_memo.py`
- Modify: `tools/mwcc_retro/x86_cfg.py`

**Interfaces:**
- Produces:
  - `READABLE_GLOBAL_EFFECT_SEMANTICS: str`
  - `ReadableGlobalEffectKey`
  - `DependencyMemoEntry`
  - `ReadableGlobalEffectMemoStore`
  - `InMemoryReadableGlobalEffectMemoStore`
- Consumes later: Task 3's `SqliteReadableGlobalEffectMemoStore` and Task 4's recovery integration

- [ ] **Step 1: Write failing dependency-pooling tests**

Create `tools/melee-agent/tests/test_retro_semantic_memo.py`:

```python
from tools.mwcc_retro.semantic_memo import (
    DependencyMemoEntry,
    InMemoryReadableGlobalEffectMemoStore,
    ReadableGlobalEffectKey,
)


def key(context=((0x401000, 0x402000, 0x403000),)):
    return ReadableGlobalEffectKey(
        call_target=0x401000,
        slot=0x580000,
        field_path=(4, 0),
        exact_call_contexts=context,
        summary_fact_signature=(10, 20, 30, 40, 50, 60),
        control_flow_revision=7,
    )


def test_equal_dependency_tuples_are_interned():
    store = InMemoryReadableGlobalEffectMemoStore()
    first_dependencies = (("function", 0x401000, "a" * 64),)
    second_dependencies = tuple(list(first_dependencies))
    store.put(
        key(),
        DependencyMemoEntry("b" * 64, first_dependencies, (frozenset({1}), "one")),
    )
    store.put(
        key(((0x401000, 0x402001, 0x403000),)),
        DependencyMemoEntry("b" * 64, second_dependencies, None),
    )

    first = store.get(key())
    second = store.get(key(((0x401000, 0x402001, 0x403000),)))
    assert first is not None and second is not None
    assert first.dependencies is second.dependencies
    assert len(store.dependency_pool) == 1


def test_unequal_dependency_tuples_remain_distinct():
    store = InMemoryReadableGlobalEffectMemoStore()
    store.put(
        key(),
        DependencyMemoEntry(
            "b" * 64,
            (("function", 0x401000, "a" * 64),),
            None,
        ),
    )
    store.put(
        key(((0x401000, 0x402001, 0x403000),)),
        DependencyMemoEntry(
            "b" * 64,
            (("function", 0x401000, "c" * 64),),
            None,
        ),
    )
    assert len(store.dependency_pool) == 2
```

- [ ] **Step 2: Run the new tests to verify RED**

Run:

```bash
python -m pytest -o addopts='' -q \
  tools/melee-agent/tests/test_retro_semantic_memo.py
```

Expected: collection fails because `tools.mwcc_retro.semantic_memo` does not
exist.

- [ ] **Step 3: Implement strict types and the pooled in-memory store**

Create `tools/mwcc_retro/semantic_memo.py` with these public-private
interfaces:

```python
READABLE_GLOBAL_EFFECT_SEMANTICS = "readable-global-effect-v1"

DependencyRows = tuple[tuple[str, int, str], ...]
ReadableGlobalEffectResult = tuple[frozenset[int], str] | None


@dataclass(frozen=True, slots=True)
class DependencyMemoEntry:
    image_sha256: str
    dependencies: DependencyRows
    result: Any


@dataclass(frozen=True, slots=True)
class ReadableGlobalEffectKey:
    call_target: int
    slot: int
    field_path: tuple[int, ...]
    exact_call_contexts: tuple[tuple[int, int, int], ...]
    summary_fact_signature: tuple[int, ...]
    control_flow_revision: int
    analysis_semantics: str = READABLE_GLOBAL_EFFECT_SEMANTICS


class ReadableGlobalEffectMemoStore(Protocol):
    def get(
        self, key: ReadableGlobalEffectKey
    ) -> DependencyMemoEntry | None: ...

    def put(
        self,
        key: ReadableGlobalEffectKey,
        entry: DependencyMemoEntry,
    ) -> None: ...

    def __len__(self) -> int: ...
    def close(self) -> None: ...
```

Implement `InMemoryReadableGlobalEffectMemoStore` with:

- `entries: dict[ReadableGlobalEffectKey, DependencyMemoEntry]`;
- `dependency_pool: dict[DependencyRows, DependencyRows]`;
- a private `_intern_entry` that uses `setdefault` and reconstructs an entry
  only when its dependency tuple is not already the canonical object;
- idempotent `close`.

In `x86_cfg.py`, replace the local `_DependencyMemoEntry` definition with:

```python
from tools.mwcc_retro.semantic_memo import (
    DependencyMemoEntry as _DependencyMemoEntry,
)
```

This preserves the existing private name used throughout `x86_cfg.py` and its
tests.

- [ ] **Step 4: Run the pooling tests to verify GREEN**

Run:

```bash
python -m pytest -o addopts='' -q \
  tools/melee-agent/tests/test_retro_semantic_memo.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'dependency_tuples or dependency_memo or producer_dependency'
```

Expected: all selected tests PASS.

- [ ] **Step 5: Run static checks and commit**

```bash
python -m ruff check \
  tools/mwcc_retro/semantic_memo.py \
  tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_semantic_memo.py
python -m py_compile \
  tools/mwcc_retro/semantic_memo.py \
  tools/mwcc_retro/x86_cfg.py
git diff --check
git add \
  tools/mwcc_retro/semantic_memo.py \
  tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_semantic_memo.py
git commit -m "perf(mwcc-retro): intern semantic memo dependencies"
```

Expected: all checks pass and the commit succeeds.

---

### Task 3: Add the strict normalized SQLite store

**Files:**
- Modify: `tools/mwcc_retro/semantic_memo.py`
- Modify: `tools/melee-agent/tests/test_retro_semantic_memo.py`

**Interfaces:**
- Consumes: Task 2's `ReadableGlobalEffectKey`, `DependencyMemoEntry`, and store protocol
- Produces:
  - `SemanticMemoStoreError`
  - `SqliteReadableGlobalEffectMemoStore(path, image_sha256, lru_entries=512)`

- [ ] **Step 1: Write failing round-trip and persistence tests**

Add tests that:

```python
def test_sqlite_store_round_trips_and_reopens(tmp_path):
    path = tmp_path / "readable-global.sqlite3"
    entry = DependencyMemoEntry(
        "b" * 64,
        (("function", 0x401000, "a" * 64),),
        (frozenset({1, 7}), "preserved;proof"),
    )
    with SqliteReadableGlobalEffectMemoStore(
        path, image_sha256="b" * 64, lru_entries=1
    ) as store:
        store.put(key(), entry)
        assert store.get(key()) == entry

    with SqliteReadableGlobalEffectMemoStore(
        path, image_sha256="b" * 64, lru_entries=1
    ) as reopened:
        assert reopened.get(key()) == entry
```

Also cover `result=None`, two entries sharing one dependency row, and LRU
eviction followed by a successful disk lookup.

- [ ] **Step 2: Write failing strict-validation tests**

Add parameterized adversarial tests that mutate a temporary database and
require `SemanticMemoStoreError` for:

- wrong metadata schema;
- wrong compiler SHA-256;
- wrong analysis semantics;
- malformed or duplicate-key JSON;
- key SHA-256 mismatch;
- exact key-byte mismatch under a valid digest field;
- malformed dependency kind, identifier, or fingerprint;
- malformed result values or provenance;
- SQLite `quick_check` failure or unreadable database bytes.

The exact assertion is:

```python
with pytest.raises(SemanticMemoStoreError, match=expected_fragment):
    SqliteReadableGlobalEffectMemoStore(
        path,
        image_sha256="b" * 64,
        lru_entries=1,
    )
```

or, for row corruption discovered lazily, wrap `store.get(key())`.

- [ ] **Step 3: Run the new tests to verify RED**

Run:

```bash
python -m pytest -o addopts='' -q \
  tools/melee-agent/tests/test_retro_semantic_memo.py
```

Expected: failures because `SqliteReadableGlobalEffectMemoStore` and strict
decoders are absent.

- [ ] **Step 4: Implement canonical payloads and schema**

In `semantic_memo.py`, add:

```python
_STORE_SCHEMA = "mwcc-retro-readable-global-effect-cache-v1"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
```

Encode keys as an exact object containing:

```python
{
    "analysis_semantics": key.analysis_semantics,
    "call_target": key.call_target,
    "slot": key.slot,
    "field_path": list(key.field_path),
    "exact_call_contexts": [list(row) for row in key.exact_call_contexts],
    "summary_fact_signature": list(key.summary_fact_signature),
    "control_flow_revision": key.control_flow_revision,
}
```

Encode dependencies as a sorted list of exact `{kind, identifier,
fingerprint}` objects. Encode results as either `{"status":"blocked"}` or:

```python
{
    "status": "finite",
    "values": sorted(result[0]),
    "provenance": result[1],
}
```

Use strict duplicate-key rejection and exact-key-set checks while decoding.
Accept only dependency kinds `function`, `global-slot`, and `dynamic-field`,
64-character lowercase hexadecimal fingerprints, integer byte values
`0..255`, and nonempty provenance.

- [ ] **Step 5: Implement normalized SQLite storage and bounded LRU**

Create exact tables:

```sql
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE dependencies (
    dependency_sha256 TEXT PRIMARY KEY,
    payload BLOB NOT NULL
);
CREATE TABLE memo (
    key_sha256 TEXT PRIMARY KEY,
    key_payload BLOB NOT NULL,
    dependency_sha256 TEXT NOT NULL,
    result_payload BLOB NOT NULL
);
```

Configure WAL, `synchronous=FULL`, foreign keys, and a fixed negative
`cache_size`. On open, run `PRAGMA quick_check(1)` and verify exact metadata.
On `put`, canonicalize and intern dependencies, compress dependency/result
payloads with zlib level 1, and commit dependency plus memo rows in one
transaction before returning. On `get`, verify the stored key digest and exact
canonical bytes before decoding, intern reconstructed dependencies, and update
an `OrderedDict` LRU capped by `lru_entries`.

Implement `__enter__`, `__exit__`, and idempotent `close`; closing performs
`PRAGMA wal_checkpoint(TRUNCATE)` before closing the connection.

- [ ] **Step 6: Run persistence and adversarial tests to verify GREEN**

Run:

```bash
python -m pytest -o addopts='' -q \
  tools/melee-agent/tests/test_retro_semantic_memo.py
```

Expected: all tests PASS.

- [ ] **Step 7: Run static checks and commit**

```bash
python -m ruff check \
  tools/mwcc_retro/semantic_memo.py \
  tools/melee-agent/tests/test_retro_semantic_memo.py
python -m py_compile tools/mwcc_retro/semantic_memo.py
git diff --check
git add \
  tools/mwcc_retro/semantic_memo.py \
  tools/melee-agent/tests/test_retro_semantic_memo.py
git commit -m "perf(mwcc-retro): persist exact semantic memo results"
```

---

### Task 4: Integrate the shared store into exact CFG recovery

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_cli.py`

**Interfaces:**
- Consumes: Task 2 and Task 3 memo-store implementations
- Produces:
  - `_DirectCfgRecovery(..., readable_global_effect_store=None)`
  - one shared store across every fixed-point trial in `recover_cfg`
  - persistent path `<producer_checkpoint_dir>/.readable-global-effect-v1.sqlite3`

- [ ] **Step 1: Write failing direct-recovery store tests**

Add tests using a recording store:

```python
class RecordingStore(InMemoryReadableGlobalEffectMemoStore):
    gets = 0
    puts = 0

    def get(self, key):
        self.gets += 1
        return super().get(key)

    def put(self, key, entry):
        self.puts += 1
        return super().put(key, entry)
```

Construct `_DirectCfgRecovery` with `readable_global_effect_store=store`, run
an existing exact-readable-global fixture twice, and assert:

- the first run publishes through `put`;
- the second run consults `get`;
- equal results and provenance are returned;
- a stale dependency fingerprint causes recomputation rather than reuse.

- [ ] **Step 2: Write failing `recover_cfg` sharing and lifecycle tests**

Monkeypatch the SQLite store constructor with a context-recording fake and run
an existing fixture that creates both current and trial recoveries. Assert
that:

```python
assert created_paths == [
    checkpoint_dir / ".readable-global-effect-v1.sqlite3"
]
assert all(row.readable_global_effect_store is created_store for row in recoveries)
assert created_store.close_calls == 1
```

Add an exception-path test whose recovery raises and still requires one close.
Extend the backend CLI test to assert the nested memo path is beneath
`.producer-domain-checkpoints.v1`, never in the published generation.

- [ ] **Step 3: Run the integration tests to verify RED**

Run:

```bash
python -m pytest -o addopts='' -q \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_cli.py \
  -k 'readable_global_effect_store or semantic_memo'
```

Expected: failures because recovery does not accept or share the store.

- [ ] **Step 4: Route the readable-global memo through the store**

In `_DirectCfgRecovery.__init__`, accept:

```python
readable_global_effect_store: (
    ReadableGlobalEffectMemoStore | None
) = None
```

Default to `InMemoryReadableGlobalEffectMemoStore`. Replace the current tuple
key with `ReadableGlobalEffectKey`, including the explicit semantics field.
Replace:

```python
cached = self.readable_global_effect_cache.get(cache_key)
self.readable_global_effect_cache[final_cache_key] = entry
```

with:

```python
cached = self.readable_global_effect_store.get(cache_key)
self.readable_global_effect_store.put(final_cache_key, entry)
```

Keep `_dependency_memo_hit`, dependency collection, final-key recomputation,
and result/provenance construction in their current order.

- [ ] **Step 5: Share and close one store in `recover_cfg`**

Create the store once:

```python
if producer_checkpoint_dir is None:
    readable_store = InMemoryReadableGlobalEffectMemoStore()
else:
    readable_store = SqliteReadableGlobalEffectMemoStore(
        producer_checkpoint_dir
        / ".readable-global-effect-v1.sqlite3",
        image_sha256=image.sha256,
        lru_entries=512,
    )
```

Pass the same `readable_store` to both current and trial
`_DirectCfgRecovery` constructors. Wrap the entire fixed-point loop in
`try/finally` and call `readable_store.close()` exactly once. Do not close the
store from individual recovery objects.

- [ ] **Step 6: Verify GREEN and unchanged semantics**

Run:

```bash
python -m pytest -o addopts='' -q \
  tools/melee-agent/tests/test_retro_semantic_memo.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_cli.py \
  -k 'readable_global or semantic_memo or producer_checkpoint'
```

Expected: all selected tests PASS.

- [ ] **Step 7: Run static checks and commit**

```bash
python -m ruff check \
  tools/mwcc_retro/semantic_memo.py \
  tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_semantic_memo.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_cli.py
python -m py_compile \
  tools/mwcc_retro/semantic_memo.py \
  tools/mwcc_retro/x86_cfg.py
git diff --check
git add \
  tools/mwcc_retro/semantic_memo.py \
  tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_semantic_memo.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_cli.py
git commit -m "perf(mwcc-retro): share restartable semantic memo state"
```

---

### Task 5: Verify performance, correctness, and the Task 4 unblock

**Files:**
- Modify only if measured and separately designed: `tools/mwcc_retro/x86_cfg.py`
- Diagnostic output: `build/diagnostics/task4-repair-exact/`

**Interfaces:**
- Consumes: production pooled/persistent memo store
- Produces: benchmark evidence, exact focused-query result, and a go/no-go decision for any secondary optimization

- [x] **Step 1: Run the full focused correctness suite**

```bash
cd tools/melee-agent
python -m pytest -o addopts='' \
  tests/test_retro_semantic_memo.py \
  tests/test_retro_x86_cfg.py \
  tests/test_retro_backend_lifetime_audit.py \
  tests/test_retro_backend_cli.py \
  tests/test_ghidra_mwcc_setup.py \
  tests/test_mwcc_ghidra_setup_script.py
cd ../..
```

Expected: all tests PASS.

Result after the finite-control optimization checkpoint: 1,072 passed.

- [x] **Step 2: Run all static gates**

```bash
python -m ruff check \
  tools/mwcc_retro/semantic_memo.py \
  tools/mwcc_retro/x86_cfg.py \
  tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/src/cli/debug/retro.py \
  tools/melee-agent/tests/test_retro_semantic_memo.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py \
  tools/melee-agent/tests/test_retro_backend_cli.py
python -m py_compile \
  tools/mwcc_retro/semantic_memo.py \
  tools/mwcc_retro/x86_cfg.py \
  tools/mwcc_retro/backend_lifetime_audit.py \
  tools/melee-agent/src/cli/debug/retro.py
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 3: Benchmark store scale without timing assertions**

Populate a temporary production store from deterministic synthetic keys that
reuse 142 dependency sets across 422,307 entries. Record:

- database bytes;
- peak physical footprint from `/usr/bin/time -l`;
- cold and hot lookup throughput;
- dependency-pool size;
- LRU size after the run.

Reject the implementation if the database exceeds 2 GB, process footprint
exceeds 8 GB, swap grows, or the pool contains more dependency objects than
distinct tuples.

- [x] **Step 4: Resume the focused exact query with bounded monitoring**

Run the branch-local diagnostic for:

```text
OBJECT_BYTE_TRACE=0x46fa24,ebx,0x46f9a0,4,0
OBJECT_GUARD_CONTEXT=4,0:0:0xa:4,6,0
DECODE_CACHE_LIMIT=32768
```

Use a two-hour timeout, five-minute sample reporting, and no line tracing.
Monitor physical footprint and swap after cache open, after ten minutes, and
before completion. Require less than 8 GB footprint and no swap increase.
Preserve every completed durable summary if the timeout fires.

- [x] **Step 5: Compare focused-query semantics**

Run the focused query twice against the same completed production store and
require byte-equal JSON values/provenance. Compare that result with the
pre-integration diagnostic query when the latter has completed. If the first
completed result is bottom, use a narrowly targeted streamed trace to identify
the exact final rejecting branch before making any semantic change. Do not
change a proof rule based only on timing or cache behavior.

- [x] **Step 6: Decide secondary optimization from the new profile**

If the focused query remains materially CPU-bound, write a separate design
and implementation plan for only the dominant measured immutable helper.
Candidates are decoded-instruction LRU sizing, reachability/successor cache,
function stack-state cache, or read-before-write cache. Do not combine more
than one unmeasured candidate.

Measured decision: retain the enlarged checkpointed semantic LRU and batch up
to 128 atomically checkpointed producer queries per production CLI process.
The latter removes repeated whole-image setup without changing any semantic
cache key, producer query, certificate, or fresh-resume validation rule.
Also replace the measured quadratic relocated-dispatch write-overlap scan with
an exact prefix-maximum interval index; the production pass spent 374 seconds
testing 20,925 tentative slots and accepted none.

The next bounded profile isolated repeated finite-control graph traversals.
Batch saved-receiver reachability, cache completed intrusive-list proofs outside
their own active recursion, prefilter functions without the necessary
intrusive link store, and index stack call-dependency prefixes. These exact
changes advanced the same 420-second workload from pass 18 to pass 27. A
smaller attempted partial stack-state cache was removed after the full CFG
suite exposed a stale semantic-closure result.

- [ ] **Step 7: Run exact Task 4 closure twice** (in progress)

Use the ordinary branch-local `probe-backend-map --static-only` workflow and
the same producer checkpoint directory until the producer certificates are
fresh and closure is complete. Compare both accepted generations
byte-for-byte and require:

- zero potentially internal unresolved transfers;
- unchanged relocation dispositions;
- accepted residue reconciliation;
- exact `formatoperands` dispatch invariants;
- identical canonical output members and manifest digests.

The fourth resumable production process completed 128 atomically checkpointed
queries in 3,232.45 seconds with a 5.27 GB maximum resident set and no swap.
That batch crossed multiple fixed-point waves but correctly exited incomplete
with 24 newly exposed queries. The next continuation measures the retained
finite-control indexes without profiler overhead.

- [ ] **Step 8: Push the optimization checkpoints**

```bash
git status --short
git push origin codex/issue-1240-retail-pcode-proof
```

Expected: only preserved user-local untracked files remain and the push
succeeds.
