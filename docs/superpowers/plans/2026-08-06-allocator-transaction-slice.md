# Allocator Transaction Slice Implementation Plan

> **Superseded 2026-08-06:** Do not continue this plan. Exact retail graph
> measurements invalidated its bounded-slice premise. Continue with
> `2026-08-06-allocator-session-capability-seal.md`.

> **Historical execution note (inactive):** The original plan required
> superpowers:subagent-driven-development or superpowers:executing-plans. The
> unchecked steps below are an archive of the rejected approach, not pending
> work.

**Goal:** Replace whole-backend semantic-write expansion with an exact, dependency-bound interprocedural slice from each checked backend/lifetime root to every owned call of the proved allocator.

**Architecture:** Keep the complete direct call closure for Task 5 backend identity, caller membership, body inventory, and dependency fingerprints. Add a separate bidirectional CFG/callgraph transaction slice for semantic-write auditing; it retains all reconverging branches and side calls that can execute before an allocator goal, but excludes branches whose exact successors cannot reach a goal.

**Tech Stack:** Python 3.12, Capstone x86-32 detail mode, immutable dataclasses, recovered PE CFG/call-target indexes, pytest, Ruff.

## Historical Disposition

The transaction-slice prototype never became accepted Task 4 proof evidence.
Exact retail measurements showed that the sound target-reachable slice expands
through recursive call-graph cycles, while restricting it to shortest paths
would omit valid executions. Any transaction-specific records, construction,
fixture mutations, and tests are therefore removal or migration work under
Task 5 of the replacement plan, not implementation tasks from this checklist.

Removing that scaffolding does not weaken the live proof. No positive
allocator-totality claim may depend on the rejected slice. The replacement
retains the validated full-closure identity and caller-membership inventory,
private-heap and finalized-handle contracts, typed return propagation, and
dependency replay. It then requires the stronger conjunction of a structural
session certificate, an exact returning-publication closure, a protected-state
capability seal, and a semantic allocator-state audit over that closure.

Everything below this section is retained only to document the rejected
proposal, its intended fail-closed properties, and the measurements that led to
its replacement.

## Global Constraints

- Preserve the full direct-closure check that one backend root contains the lifecycle consumer, allocation caller, and every incoming owner.
- Treat all exact owned calls from `allocation_caller` to `allocator` as terminal goals; never choose a preferred trace or subset.
- Retain branch alternatives that reconverge before a goal and audit every call in their retained blocks.
- Fail closed on unresolved retained control, uncontracted imports, unsafe writes, direction-flag ambiguity, stack pivots, or stale dependencies.
- Do not add `GlobalReAlloc` or unrelated compiler-runtime imports to `_PUBLICATION_IMPORT_CONTRACTS`.
- Preserve publication's expected 39 returning bodies, 56-function default callback closure, and five exact imports.
- Use no retail-address special case; retail addresses appear only in read-only verification commands and result notes.
- Do not launch another full retail replay until the hydrated exact transaction query advances locally.

---

### Task 1: Model and compute intraprocedural goal slices

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:1080-1165`
- Modify: `tools/mwcc_retro/x86_cfg.py:19120-19380`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py:3920-4960`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py:10800-11080`

**Interfaces:**
- Consumes: `_summary_successors(address, function_entry, following_entry)`, `_function_instruction_addresses(function_entry)`, `_owned_decoded(address)`.
- Produces: `_AllocatorTransactionFunctionSlice` and `_intraprocedural_goal_slice(function_entry, goal_call_sites) -> _AllocatorTransactionFunctionSlice | None`.

- [ ] **Step 1: Add transaction-branch fixture mutations**

Extend `_RETURN_PATH_PUBLICATION_MUTATIONS` with:

```python
"transaction-unreachable-untrusted-call",
"transaction-reconverging-untrusted-call",
"transaction-reconverging-protected-write",
"transaction-reconverging-unresolved-jump",
```

Reserve a helper after the existing prior-callback initializer and enlarge the fixture text region as needed. For the positive mutation, branch either to an untrusted helper followed by `ret` or to the normal incoming-owner calls; the helper contains `call dword ptr [unlisted_iat]`. For reconverging mutations, make the untrusted call, protected write, or unresolved jump occur on one branch whose known fallthrough rejoins before `incoming_owners[0]`.

- [ ] **Step 2: Write RED low-level slice assertions**

Add:

```python
def test_allocator_transaction_slice_excludes_unreachable_untrusted_branch():
    fixture = return_path_publication_lifecycle_image(
        mutation="transaction-unreachable-untrusted-call"
    )
    recovery = _DirectCfgRecovery(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )
    recovery.recover()
    owner_calls = frozenset(
        call.address
        for call in recovery._function_direct_calls(fixture.backend_root)
        if call.target in fixture.incoming_owners
    )

    sliced = recovery._intraprocedural_goal_slice(
        fixture.backend_root,
        owner_calls,
    )

    assert sliced is not None
    assert sliced.goal_call_sites == owner_calls
    assert sliced.retained_call_sites >= owner_calls
```

Add parameterized RED assertions that the reconverging call/write remains in `retained_addresses` and that the unresolved jump makes the helper return `None`.

- [ ] **Step 3: Run the new tests and confirm RED**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m pytest -o addopts='' \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'allocator_transaction_slice' -vv
```

Expected: fail because `_AllocatorTransactionFunctionSlice` and `_intraprocedural_goal_slice` do not exist.

- [ ] **Step 4: Add the immutable function-slice record**

Add beside `_AllocatorTotalityCertificate`:

```python
@dataclass(frozen=True, slots=True)
class _AllocatorTransactionFunctionSlice:
    function_entry: int
    goal_call_sites: frozenset[int]
    retained_addresses: frozenset[int]
    retained_call_sites: frozenset[int]
```

- [ ] **Step 5: Implement the bidirectional intraprocedural slice**

Implement:

```python
def _intraprocedural_goal_slice(
    self,
    function_entry: int,
    goal_call_sites: frozenset[int],
) -> _AllocatorTransactionFunctionSlice | None:
```

Require every goal to be an owned call. Traverse forward from the function entry, treating goals as terminal. Build reverse edges from `_summary_successors`; retain the forward/reverse intersection. Reject a forward-reachable pre-goal jump with no exact `non_call_successors`, a successor outside the function, or an unreachable goal. Record every retained call and check `max_summary_iterations` while growing each set.

- [ ] **Step 6: Run focused tests and commit**

```bash
PYTHONPATH=tools/melee-agent python -m pytest -o addopts='' \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'allocator_transaction_slice or backend_unresolved or reset_in_lifetime' -q
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): slice allocator transaction blocks"
```

Expected: selected tests and commit hooks pass.

---

### Task 2: Build and audit the interprocedural transaction

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:1080-1165`
- Modify: `tools/mwcc_retro/x86_cfg.py:15200-15680`
- Modify: `tools/mwcc_retro/x86_cfg.py:19120-19420`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py:10800-11080`

**Interfaces:**
- Consumes: `_AllocatorTransactionFunctionSlice`, `_direct_function_call_closure`, `call_targets_by_source`, `_finite_owned_function_call_scope`, `_semantic_closed_argument_domains_from_roots`, `_semantic_writes_forbidden_spans`.
- Produces: `_AllocatorTransactionSlice` and `_allocator_transaction_slice(root, allocator, allocation_caller, protected_slots, deferred_call_sites, call_return_domains) -> _AllocatorTransactionSlice | None`.

- [ ] **Step 1: Add RED end-to-end totality tests**

Add:

```python
def test_allocator_totality_ignores_unreachable_untrusted_backend_branch():
    fixture = return_path_publication_lifecycle_image(
        mutation="transaction-unreachable-untrusted-call"
    )
    recovery = _DirectCfgRecovery(
        fixture.image,
        build_seed_inventory(fixture.image, ()),
        generous_limits(fixture.image),
    )
    recovery.recover()

    certificate = recovery._allocator_totality_certificate(
        fixture.allocator,
        fixture.publishing_consumer,
        lifetime_roots=frozenset({fixture.publishing_consumer}),
    )

    assert certificate is not None
    assert {row.root for row in certificate.transaction_slices} == {
        fixture.backend_root,
        fixture.publishing_consumer,
    }
```

Parameterize the three reconverging mutations and assert totality is `None`.

- [ ] **Step 2: Run totality tests and confirm RED**

```bash
PYTHONPATH=tools/melee-agent python -m pytest -o addopts='' \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'totality_ignores_unreachable or transaction_reconverging' -vv
```

Expected: the positive case bottoms because the old whole-root scope reaches the untrusted helper; `transaction_slices` is absent.

- [ ] **Step 3: Add the transaction record**

```python
@dataclass(frozen=True, slots=True)
class _AllocatorTransactionSlice:
    root: int
    allocator: int
    allocation_caller: int
    goal_call_sites: frozenset[int]
    function_slices: tuple[_AllocatorTransactionFunctionSlice, ...]
    side_scope_functions: frozenset[int]

    @property
    def function_entries(self) -> frozenset[int]:
        return frozenset(
            row.function_entry for row in self.function_slices
        ) | self.side_scope_functions
```

Extend `_AllocatorTotalityCertificate` with the required field:

```python
transaction_slices: tuple[_AllocatorTransactionSlice, ...]
```

- [ ] **Step 4: Implement reverse callgraph distances**

Inside `_allocator_transaction_slice`, collect finite owned call targets reachable from `root`, then compute minimum reverse distance to `allocation_caller`. Reject external targets and a root with no finite distance. For `allocation_caller`, goals are all calls whose targets contain `allocator`; for another spine function, goals are calls with at least one target whose distance is strictly smaller. Call `_intraprocedural_goal_slice` for every spine function.

- [ ] **Step 5: Close retained side calls only**

For every retained call:

```python
spine_targets = targets & spine_entries
side_targets = targets - spine_targets
```

Call `_finite_owned_function_call_scope` for each side target with identical protected slots and deferred calls. Reject an unresolved call, uncontracted import, external target, or unsafe side closure. The excluded untrusted branch is never inspected because its call site is not retained.

- [ ] **Step 6: Propagate domains and audit writes**

Build `allowed_call_sites` from retained spine calls and all calls in complete side scopes. Call `_semantic_closed_argument_domains_from_roots` with `roots={root}`, the union of spine and side functions, the exact `call_return_domains`, and `allowed_call_sites`.

Call `_semantic_writes_forbidden_spans` with `addresses=function_slice.retained_addresses` for spine functions and complete bodies for side functions. Preserve the existing exclusions for the proved allocator and grow target. Return `None` on any unsafe write.

- [ ] **Step 7: Return canonical evidence**

Sort `function_slices` by `function_entry`; freeze all address/call sets. Require the record to include `root` and `allocation_caller`, and require every goal's exact targets to contain `allocator`.

- [ ] **Step 8: Run focused totality tests and commit**

```bash
PYTHONPATH=tools/melee-agent python -m pytest -o addopts='' \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'allocator_totality or lifecycle_total_allocation or transaction_' -q
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "feat(mwcc-retro): audit allocator transaction slices"
```

Expected: the unreachable branch succeeds; every reconverging/unresolved/protected mutation rejects; prior totality tests remain green.

---

### Task 3: Integrate totality, dependency replay, and backend bridge evidence

**Files:**
- Modify: `tools/mwcc_retro/x86_cfg.py:19500-20430`
- Modify: `tools/mwcc_retro/x86_cfg.py:44700-44920`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py:10880-11080`
- Test: `tools/melee-agent/tests/test_retro_x86_cfg.py:17780-18030`

**Interfaces:**
- Consumes: `_allocator_transaction_slice`, `_AllocatorTransactionSlice.function_entries`, `_allocator_totality_dependencies`.
- Produces: certificates whose transaction slices replay exactly and backend bridges whose full `backend_bodies` inventory remains unchanged.

- [ ] **Step 1: Add RED certificate and dependency assertions**

Extend the exact backend-bridge test:

```python
assert {row.root for row in totality.transaction_slices} == {
    fixture.backend_root,
    fixture.publishing_consumer,
}
assert {row.function_entry for row in bridge.backend_bodies} == set(
    result.recovery._direct_function_call_closure(fixture.backend_root)
)
```

Add a cache test that mutates a retained instruction, clears its function fingerprint cache, and asserts `_dependency_memo_hit(entry)` is false. Mutate an excluded untrusted-helper instruction and assert the transaction slice payload is unchanged, while the full backend-body dependency still invalidates a rebuilt publication bridge.

- [ ] **Step 2: Run dependency tests and confirm RED**

```bash
PYTHONPATH=tools/melee-agent python -m pytest -o addopts='' \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'backend_bridge_binds or transaction_slice_cache or totality_cache' -vv
```

Expected: fail because certificates do not populate, merge, or replay transaction slices.

- [ ] **Step 3: Replace whole-root semantic scopes in totality**

Keep `_direct_function_call_closure` for backend/lifetime membership tests. Replace the `backend_finite_scope` and `lifetime_semantic_scopes` construction with `_allocator_transaction_slice(...)`. Store both backend and lifetime records in each candidate certificate.

When compatible session candidates merge, union slices by complete immutable identity and sort by `(root, allocator, allocation_caller)`. Include `transaction_slices` in the compatibility key so incompatible surfaces cannot merge.

- [ ] **Step 4: Replay every transaction dependency**

In `_allocator_totality_dependencies`, add every transaction function and every retained address owner. Keep the existing full direct closures because Task 5's `backend_bodies` inventory fingerprints them. Before memo publication, enforce:

```python
assert all(
    self._registrar_function_entry(address) == function_slice.function_entry
    for transaction in certificate.transaction_slices
    for function_slice in transaction.function_slices
    for address in function_slice.retained_addresses
)
```

- [ ] **Step 5: Reuse totality evidence in the backend bridge**

Require exactly one slice with `root == backend_root`. Do not call `_finite_owned_function_call_scope(backend_root, ...)` again. Preserve the full body inventory:

```python
backend_closure = self._direct_function_call_closure(backend_root)
backend_bodies = tuple(
    self._publication_function_body(function_entry)
    for function_entry in sorted(backend_closure)
)
```

The bridge trusts the current dependency-bound totality slice for semantic stability and still fingerprints every full-closure body.

- [ ] **Step 6: Run focused verification**

```bash
PYTHONPATH=tools/melee-agent python -m pytest -o addopts='' \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  -k 'return_path_publication or allocator_totality or finalized_handle_arena or private_heap_allocator' -q
python -m ruff check tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
python -m py_compile tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
git diff --check
```

Expected: all selected tests and static checks pass, including five-import and full-backend-body assertions.

- [ ] **Step 7: Commit Task 3**

```bash
git add tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py
git commit -m "fix(mwcc-retro): bind allocator transaction evidence"
```

---

### Task 4: Validate the retail slice and complete allocator-proof review

**Files:**
- Modify if a generic regression requires it: `tools/mwcc_retro/x86_cfg.py`
- Modify if a generic regression requires it: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Update: `.superpowers/sdd/2026-07-12-retail-pcode-proof/progress.md`
- Update if due: `.superpowers/sdd/2026-07-12-retail-pcode-proof/outlook-ledger.md`

**Interfaces:**
- Consumes: `build/diagnostics/task4-repair-exact/raw-pe-cfg.producer-quiescent.v1.jsonl`, `hydrate-cfg-query.py`, and the complete dirty private-heap/finalized-handle proof.
- Produces: exact local evidence that the `0x4908f0` transaction excludes the independent `0x443170` buffer branch, retains the allocator/handle/finalizer chain, and advances totality beyond the old scope boundary.

- [ ] **Step 1: Add private-heap cache invalidation tests**

Compute `_private_heap_allocator_contract` on `FinalizedHandleArenaFixture`, mutate one companion-free writer instruction, clear its function fingerprint cache, and assert the cached dependency entry is stale and recomputation bottoms or produces a fresh current entry. Change the protected-slot set and prove no cache hit crosses it.

- [ ] **Step 2: Normalize typed domain annotations**

Add `"private-heap"` to every `Literal` used by call-return, argument-domain, semantic-write, transaction-slice, and allocator-totality signatures. Do not change runtime behavior.

- [ ] **Step 3: Run the hydrated exact transaction query**

Use the existing rehydrator with scanned write indexes. Compute the allocator fact, grow shape, typed call-return domains, protected slots, and transaction slice for `0x4908f0`. Print only:

```text
transaction_functions <count>
side_scope_functions <count>
contains_443170 False
contains_404610 True
contains_443120 True
contains_4431a0 True
```

If the result is `None`, instrument only the first failing retained call/write and add a generic hostile regression before production changes.

- [ ] **Step 4: Run exact totality without full line tracing**

Hydrate scanned indexes, precompute `_allocator_call_return_domains`, bind that result on the recovery instance, and call:

```python
recovery._allocator_totality_certificate(
    0x441FA0,
    0x4A24E0,
    lifetime_roots=frozenset({0x4351C0}),
)
```

Record elapsed time, transaction counts, backend/session roots, callback target/candidates, and the next exact fail-closed boundary if the certificate is still `None`.

- [ ] **Step 5: Run complete component verification**

```bash
PYTHONPATH=tools/melee-agent python -m pytest -o addopts='' \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  tools/melee-agent/tests/test_retro_backend_lifetime_audit.py -q
python -m ruff check tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
python -m py_compile tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py
git diff --check
if rg -n '0x4908f0|0x443170|0x412930|0x404610|0x443120' \
  tools/mwcc_retro/x86_cfg.py; then exit 1; fi
```

Expected: all tests/static checks pass and the production retail-address scan prints nothing.

- [ ] **Step 6: Review the complete implementation since `fc035319b`**

Review private free-side provenance, finite indexed state, callback generations, prologue argument boundaries, finite sync-wrapper arguments, transaction exclusion/reconvergence, cache keys, and dependency replay. Every soundness concern receives a failing regression before a fix.

- [ ] **Step 7: Update ledgers, commit, and push**

Append exact evidence to the progress ledger and, when due, the 12-hour outlook ledger. Then:

```bash
git add tools/mwcc_retro/x86_cfg.py \
  tools/melee-agent/tests/test_retro_x86_cfg.py \
  .superpowers/sdd/2026-07-12-retail-pcode-proof/progress.md
git commit -m "fix(mwcc-retro): close allocator transaction totality"
git push origin codex/issue-1240-retail-pcode-proof
```

Add the outlook ledger explicitly only when a new entry was required. Never add `.agents/` or `.pi/`.

---

### Task 5: Resume Task 7 retail publication validation

**Files:**
- Update: `docs/superpowers/results/2026-08-02-return-path-publication-noninterference.md`
- Update: `.superpowers/sdd/2026-07-12-retail-pcode-proof/progress.md`
- Update if due: `.superpowers/sdd/2026-07-12-retail-pcode-proof/outlook-ledger.md`

**Interfaces:**
- Consumes: verified transaction totality and checkpoint root `build/mwcc_retro/gc125n-proof/return-path-publication-v6`.
- Produces: one repaired full replay, one mandatory zero-new confirmation, exactly 29 admitted lifecycle transfers, and the exact publication audit row from the parent plan.

- [ ] **Step 1: Launch the repaired replay only after Task 4 passes**

Use the parent plan's exact `probe-backend-map` command in detached tmux with `/usr/bin/time -l`, the unchanged output root, and the next sequential log name. Do not create a new checkpoint root.

- [ ] **Step 2: Wait in 15-minute quiet intervals**

Inspect only ledger hits, accepted/rejected totals, publication hypothesis count, checkpoint refusal/publication, elapsed time, and RSS. Do not poll the full log every minute.

- [ ] **Step 3: Run the mandatory zero-new replay**

If the repaired replay writes any dependency/result variant, launch one subsequent whole invocation against the same root. Require zero new producer checkpoints and dependency variants before accepting the bundle.

- [ ] **Step 4: Run the parent plan's exact verifiers**

Require:

```text
admitted 29
returning 39
default-closure 56
imports 5
references 19 provisional 6
```

Require `0x4B1F95` outside the admitted set and without a publication certificate in integer fields or provenance strings.

- [ ] **Step 5: Update evidence, review, commit, and push**

Record exact commands, hashes, elapsed/RSS figures, and verifier output in the result note and ledgers. Run the parent Task 7 review checklist, then commit and push the evidence changes.
