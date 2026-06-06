# harvest allocator pcdump triage

Date: 2026-06-06
Status: Codex-reviewed; implementation may proceed
Issue: #449

## Problem

The function taxonomy emits `register-allocator` queue rows with
`source_actionability=pcdump-proof-needed`, `headline_tool=mwcc-debug`, and a
`next_command` that only tells an agent to collect a local pcdump. `harvest`
currently has no registered harness for that state, so the rows become
`unsupported-harness` even though `debug target match-iter-first` can already
turn a fresh pcdump and checkdiff into target-vector actionability.

Agents then repeat the same manual triage before they know whether the row is a
force-vector diagnostic target, a source-lifetime dead end, or a narrower
pcdump/source prerequisite.

## Goals

1. Route `register-allocator` / `pcdump-proof-needed` rows to a registered
   harvest harness instead of `unsupported-harness`.
2. Reuse the existing pcdump preflight so triage rows have fresh
   `debug dump setup` and `debug dump local <source> --function <fn>` coverage.
3. Run the existing `debug target match-iter-first` classifier with a broad
   bounded register set as the first-stage triage pass.
4. Record terminal harvest ledger classifications from
   `target_vector_actionability` without pretending a source candidate was
   generated.

## Non-goals

- Do not synthesize new coalesce, select-order, or source-transform candidates.
- Do not apply source changes.
- Do not resolve #444 or #446. Those issues need scored source-transform or
  structure-search work after this triage bridge identifies the correct bucket.
- Do not loosen stale-pcdump safety. The underlying debug command should keep
  rejecting stale auto-resolved pcdumps unless a future feature deliberately
  exposes a reviewed override.

## Design

### Harness selection

Add `HARNESS_ALLOCATOR_PCDUMP_TRIAGE = "allocator-pcdump-triage"` to harvest's
registered harnesses.

`select_harness()` should choose it when:

- `request.work_bucket == "register-allocator"`, and
- one of these signals is present:
  - `source_actionability == "pcdump-proof-needed"`
  - `headline_tool == "mwcc-debug"`
  - `next_command` or `frame_next_command` contains `debug dump local`

The explicit `facts["harness"]` override keeps winning, so target maps can still
force existing `coalesce-search` or `select-order-search` layers when they have
real targets.

### Pcdump preflight

The existing preflight should include allocator triage rows. For every eligible
row with a resolved source file, harvest should check the cache unit derived
from the source path, run `debug dump setup` once if any unit is stale or
missing, then run `debug dump local <source> --function <function>` for one
representative function per missing or stale unit.

This keeps multi-function TUs bounded and matches the existing stack-layout
preflight behavior.

### Adapter command

The adapter command is:

```text
debug target match-iter-first -f <function> --regs gpr-callee,gpr-volatile,r0 --json
```

The explicit register set is important. The debug command defaults to
`r31,r30,r29,r28`, which is too narrow for current `register-allocator` rows:
many rows involve volatile registers or lower callee-saves such as `r26` and
`r27`. The broad bounded set keeps this first-stage triage from falsely
classifying rows as targetless.

The command runs from `tools/melee-agent` like the other adapters. It relies on
the debug command's existing auto pcdump lookup, checkdiff lookup, and stale
cache validation. This v1 does not pass `--auto-verify`, so
`auto-verify-no-improvement` is out of scope for this harness.

The harvest harness should not require `source_file` beyond the preflight path;
if the queue cannot resolve a source file, return the existing
`missing-source-file` blocker because preflight cannot seed the cache.

### Ledger translation

`allocator-pcdump-triage` is diagnostic-only. It should bypass normal retained
source candidate parsing and translate the JSON payload directly.

Required fields to preserve in `details` when present:

- `target_vector_actionability`
- `force_vector`
- `force_vector_runnable`
- `force_vector_recommended`
- `force_phys_csv`
- `force_vector_conflicts`
- `unit`
- `targets`
- `results`

`match-iter-first --json` does not emit a pcdump path. Harvest should infer
`details["pcdump"]` from `unit` with the existing pcdump cache path convention
when the unit is present.

Classification rules:

- `target_vector_actionability.status == "needs-move"` and
  `force_vector_recommended` is not false: return `status=blocked`,
  `blocker=allocator-target-vector`. The reason should combine the
  actionability summary and next step.
- `target_vector_actionability.status == "already-satisfied"`: return
  `status=blocked`, `blocker=source-lifetime-callee-save-shape`.
- `target_vector_actionability.status == "current-unknown"`: return
  `status=blocked`, `blocker=allocator-current-unknown`.
- No target rows: return `status=blocked`, `blocker=allocator-no-targets`.
- `force_vector_runnable is False` or conflicts exist without a runnable
  recommended vector: return `status=blocked`,
  `blocker=allocator-vector-not-runnable`.
- Missing or malformed actionability: return `status=blocked`,
  `blocker=allocator-triage-unclassified` and preserve a compact payload in
  details.

Subprocess failures and invalid JSON should continue to use the existing
`harness-exit-nonzero` and `harness-invalid-json` error paths.

## Acceptance

- A representative `register-allocator` row with
  `source_actionability=pcdump-proof-needed` selects
  `allocator-pcdump-triage`.
- Explicit target-map `facts["harness"]` still wins over allocator triage
  auto-selection, and non-`register-allocator` `mwcc-debug` rows do not select
  this harness.
- `run_harvest("register-allocator", ...)` preflights pcdumps for triage rows
  and then runs `debug target match-iter-first -f <function> --regs
  gpr-callee,gpr-volatile,r0 --json`.
- Ledger output for `needs-move` rows records a blocked
  `allocator-target-vector` result with force-vector details.
- Ledger output for `already-satisfied` rows records a blocked
  `source-lifetime-callee-save-shape` result.
- Ledger output for missing/no-target/non-runnable actionability is a narrow
  blocker rather than a generic unsupported row.
- `apply=True` does not try to apply a source candidate for this diagnostic-only
  harness.
- Existing source-candidate harvest harness behavior remains unchanged.
