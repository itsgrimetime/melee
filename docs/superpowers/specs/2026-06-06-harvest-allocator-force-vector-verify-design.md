# harvest allocator force-vector verify design

Date: 2026-06-06
Status: Codex-reviewed; implementation may proceed
Issue: #458

## Problem

`allocator-pcdump-triage` routes register-allocator rows through
`debug target match-iter-first`, but it stops after deriving a runnable
`force_vector`. The resulting harvest ledger records the row as a generic
`allocator-target-vector` blocker. Agents must manually rerun the force-vector
probe to learn whether the override matches, improves, or does nothing.

This loses the most important diagnostic evidence: a force-vector union or
singleton match proves a narrow allocator target that should be translated into
source-shape work, while a no-match result means the specific vector should not
be treated as a promising next action.

## Goals

1. Let `match-iter-first` verify its derived `force_vector` without requiring a
   caller to know that vector ahead of time.
2. Have harvest request that verification for allocator triage rows.
3. Preserve union, singleton, and prefix probe evidence in the harvest details.
4. Classify diagnostic force-vector matches separately from generic blockers
   and no-match evidence so ledger summaries do not report diagnostic matches as
   negative evidence.

## Non-goals

- Do not synthesize or apply source edits.
- Do not create a new source-transform queue file in this change. The harvest
  ledger will expose the exact target/probe metadata needed for follow-up queue
  generation.
- Do not loosen stale-pcdump safety or bypass existing restore behavior.

## Design

### Debug command

Extend `debug target match-iter-first --force-vector` to accept the literal
value `auto`. After the command derives `target_vector`, `auto` resolves to the
derived `target_vector["force_vector"]`. If no force vector is available, the
existing `force_vector_verify` payload reports `ran=false` with a reason.

This keeps the current explicit `--force-vector <csv>` workflow intact and gives
batch callers one command that can both derive and verify the vector.

### Harvest adapter

Change the allocator triage command to:

```text
debug target match-iter-first -f <function> --regs gpr-callee,gpr-volatile,r0 --force-vector auto --json
```

The command still runs through the existing pcdump preflight and uses
`match-iter-first` restore handling.

### Ledger details

Allocator triage details should keep the existing target fields and additionally
preserve:

- `force_vector_verify`
- `force_vector_status`
- `force_vector_match`
- `force_vector_matched_probes`
- `source_transform_hint`

`force_vector_matched_probes` is a compact list of union/singleton/prefix probes
whose payload has `match=true`. `source_transform_hint` records that the next
human/tool step is source-shape work and includes the matched probe labels plus
the original targets.

Harvest must inspect `force_vector_verify.union` and every
`force_vector_verify.probes[]` entry. The top-level `force_vector_match` field
only reflects the union result and is not enough for singleton-only diagnostic
matches.

### Classification

If `force_vector_verify.ran` is true:

- Any matching union/singleton/prefix probe returns
  `status=diagnostic_match`, `blocker=allocator-force-vector-match`.
- A successful verification with no matching probes returns
  `status=no_match`, `blocker=allocator-force-vector-no-match`.
- A verification failure returns `status=blocked`,
  `blocker=allocator-force-vector-verify-failed`.

If verification did not run, existing allocator triage classification stays in
place. This preserves current behavior for non-runnable, targetless, stale, or
unclassified rows.

## Acceptance

- Harvest allocator triage invokes `match-iter-first` with
  `--force-vector auto`.
- A payload with a matching force-vector union or singleton is recorded as
  `diagnostic_match`, not `blocked`.
- A payload with verification probes but no matches is recorded as `no_match`
  with a force-vector-specific blocker.
- Details retain the full `force_vector_verify` payload and a compact matched
  probe summary.
- `summarize_harvest_ledgers()` does not include diagnostic matches in
  `negative_evidence_functions`.
- Existing allocator triage blocker behavior remains unchanged when
  verification did not run.
