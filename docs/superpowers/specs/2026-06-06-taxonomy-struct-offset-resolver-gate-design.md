# Taxonomy Struct Offset Resolver Gate Design

Date: 2026-06-06
Status: Implemented after independent Codex review
Issue: #455

## Problem

`tools/function_taxonomy_inventory.py` currently uses raw
`classification.offset_discrepancies` as the fallback signal for the
`struct-offset-discrepancy` bucket after higher-priority signature, data-symbol,
inline, stack, register, and control-flow classifications are ruled out. That
raw checkdiff signal still over-captures global-address, relocation, array-base,
pad/unnamed-field, and other data-symbol shaped residuals. The queue is noisy
enough that matching agents are sent to `struct verify` only to find no
actionable named field.

Issue #456 made `melee-agent struct verify` capable of inferring struct
identity from source. Taxonomy can now use `struct verify` as a precision gate
instead of treating raw displacement rows as field-layout work.

## Goals

1. Keep the cheap checkdiff bucket heuristic as the first pass.
2. For candidate `struct-offset-discrepancy` rows, run `struct verify` in JSON
   mode against the function and TU source.
3. Keep the row in `struct-offset-discrepancy` only when `struct verify`
   returns at least one resolver-proved, non-conflicting, non-ambiguous finding
   with both `struct` and `field`.
4. Rebucketing successful resolver-negative rows to `data-symbol-relocation`
   must preserve the raw offset summary and attach struct-verify evidence so
   agents can see why the raw row was rejected.
5. Production inventory generation should enable this gate by default, while
   tests can inject a fake runner and the CLI can skip the gate for fast legacy
   runs.

## Non-Goals

- Do not make taxonomy parse C or infer structs itself.
- Do not require `struct verify` to solve #460 THP alias dataflow before #455
  can rebucket unresolved rows.
- Do not remove raw offset summary fields from records.
- Do not change checkdiff classification.

## Approach Options

### Option A: Inline Heuristics

Taxonomy could inspect raw displacement sizes, bases, and primary reasons to
guess whether a row is a data-symbol residual. This is fast, but it repeats
struct-verify logic and would still misclassify cases where source identity is
only visible in C.

### Option B: Resolver Gate After Initial Classification

Taxonomy keeps the existing first-pass bucket selection, then calls
`struct verify` only for rows that would enter `struct-offset-discrepancy`.
Rows with verified named-field findings stay in the bucket; unresolved or only
ambiguous/conflicting findings are rebucketed to `data-symbol-relocation`.
This is the recommended approach because it reuses the source-aware resolver
from #456 and keeps the expensive command scoped to the noisy bucket.

### Option C: Precompute Struct Verify for Every Candidate

The inventory could run `struct verify` before bucket selection for every
function. This would produce more evidence, but it is slower and unnecessary
for signatures, stack layout, inline boundaries, and other non-offset classes.

## Design

Add a `StructVerifyRunner` hook to `tools/function_taxonomy_inventory.py`.
The default runner executes:

```bash
melee-agent struct verify <function> [--base <unique-base>] --tu-src <source> --json
```

The `--base` argument is included only when the raw offset summary has exactly
one concrete base register; otherwise omitted so `struct verify` can use its
own dataflow and fallback logic.

Add:

- `DEFAULT_STRUCT_VERIFY_TIMEOUT = 180.0`
- a `--struct-verify-timeout` CLI option, where `0` disables the subprocess
  timeout
- a `--skip-struct-verify-gate` CLI option that passes `None` for the runner and
  preserves legacy heuristic struct-offset classification

The timeout belongs to the taxonomy runner subprocess. This protects inventory
workers even though `struct verify` itself may run nested checkdiff commands.

`classify_candidate()` keeps its current first-pass `classify_bucket()` result.
After raw offset summary fields are attached, if the row is in
`struct-offset-discrepancy` and a struct-verify runner is present, taxonomy
runs the gate and stores:

- `struct_verify_status`: `verified`, `unverified`, or `unavailable`
- `struct_verify_finding_count`
- `struct_verify_verified_count`
- `struct_verify_structs`
- `struct_verify_fields`
- `struct_verify_skipped`
- `struct_verify_reason`

A finding is verified only when:

- `struct` is present
- `field` is present
- `conflict` is false
- `ambiguous` is false

If one or more verified findings exist, the row remains:

- `work_bucket = struct-offset-discrepancy`
- `subcategory = struct-field-offset-displacement`
- `confidence = resolver-verified`

If no verified findings exist, the row is rebucketed:

- `work_bucket = data-symbol-relocation`
- `subcategory = unverified-struct-offset-displacement`
- `confidence = resolver-rebucketed`
- `source_actionability`, `headline_tool`, `actionability_reason`, and
  `next_command` are recomputed for data-symbol work.

When rebucketing to data-symbol, the existing name-magic preflight should still
run after the final bucket is known, just as it does for rows that were
initially classified as data-symbol-relocation.

Add the `struct_verify_*` fields to both `write_csv()` and `write_queue()` so
agents consuming CSV/TSV queues can see the resolver evidence without opening
the JSONL artifact.

## Error Handling

If `struct verify` times out, fails, emits invalid JSON, or returns no payload,
taxonomy records `struct_verify_status = unavailable` and keeps the row in the
legacy `struct-offset-discrepancy` bucket with `confidence = heuristic`. The
inventory should not fail solely because the gate could not run for one
candidate.

Successful `struct verify --json` payloads with no verified findings are
resolver-negative and should be rebucketed. Skipped reasons that include
`auto-struct unresolved`, `no offset discrepancies`, `unmapped cur`, or
`ambiguous` are resolver-negative evidence. Skipped reasons such as
`checkdiff failed` or source-read failures should be treated as unavailable if
there are no findings.

## Acceptance

- A fake struct-verify payload with a non-ambiguous named field keeps a raw
  offset row in `struct-offset-discrepancy` with `resolver-verified`
  confidence.
- Empty findings, all-ambiguous findings, all-conflicting findings, missing
  struct/field, and resolver-negative skips rebucket the row to
  `data-symbol-relocation`.
- Runner failures, timeouts, invalid JSON, and unavailable skips keep the row in
  `struct-offset-discrepancy` with `struct_verify_status = unavailable`.
- Rebucketing preserves `offset_discrepancy_*` summary fields.
- Rebucketing still allows name-magic preflight to attach blocker metadata.
- The production CLI enables the gate by default and offers a skip flag for
  fast legacy runs.
- CSV and queue TSV outputs include the `struct_verify_*` evidence columns.
