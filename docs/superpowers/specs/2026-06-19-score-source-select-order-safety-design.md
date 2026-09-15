# Score-Source Safety and Select-Order Force-Phys Progress Design

## Context

Issues #834 and #835 are follow-ups to the bounded `score-source` work in
`574525d28`. The timeout now returns JSON and restores live source, but local
`wibo` can still remain in uninterruptible state after a timeout. Repeated
campaigns for the same source are unsafe if the lane already has an unreaped
process.

Select-order campaigns also need to stop treating spill-only score drops as
force-phys progress. The reported Sort candidates improved total score by
removing one unexpected spill, while IG34 stayed at the wrong physical register
and IG44 disappeared from the candidate coloring.

## Goals

1. Prevent repeated unsafe local `score-source` launches for a source that
   already has an unreaped uninterruptible `wibo` process.
2. Preserve the existing escape hatch:
   `MWCC_DEBUG_ALLOW_UNSAFE_LOCAL_PCDUMP=1`.
3. Make `score-source --json` timeout diagnostics include lane-safety details
   for the source that was just attempted.
4. Add select-order objective metadata that separates real force-phys progress
   from spill-only changes and missing/coalesced targets.
5. Rank target hits and target progress ahead of spill-only/coalesced-target
   candidates while keeping the existing structural guard as the outer ranking
   gate.

## Non-Goals

- Do not build a new local compiler worker service.
- Do not try to kill uninterruptible macOS processes after the kernel refuses
  to reap them.
- Do not run `score-source` for every select-order candidate; that would make
  unsafe local `wibo` usage worse.
- Do not refactor the large debug CLI beyond the touched helper boundaries.

## Design

### Score-Source Lane Guard

`debug target score-source` will call
`local_safety.guard_local_pcdump_lane(source_rel=src_rel, function=function, ...)`
before spawning `wibo`. If the guard finds an existing uninterruptible `wibo`
for the same normalized source lane, the command refuses to launch another
local compiler process. In JSON mode it returns the normal penalty score with
`error`, `returncode: 124`, and an `unsafe_local_pcdump_lane` object containing
the matching process list. In text/quiet mode it still prints the penalty score
for scorer compatibility while sending the safety message to stderr when not
quiet.

After a timeout, `score-source` will scan the same source lane. If unreaped
processes remain, JSON includes the same `unsafe_local_pcdump_lane` payload.
This makes downstream campaigns able to stop retrying the local pcdump lane
without parsing the free-form `stderr_tail`.

### Select-Order Force-Phys Progress

`SelectOrderObjective` will gain two fields:

- `force_phys_assignments`: per-target entries keyed by virtual register with
  `expected`, `actual`, and `status`.
- `force_phys_progress_kind`: one of
  `no-force-phys-targets`, `target-hit`, `target-progress`,
  `target-no-progress`, `spill-only`, or `target-missing`.

Statuses are computed from the already parsed candidate coloring:

- `matched`: target virtual is assigned to the requested physical register.
- `mismatched`: target virtual is present but assigned to another register.
- `missing_or_coalesced`: target virtual is absent from candidate coloring.
  The current pcdump data cannot distinguish coalescing from disappearance,
  optimization, wrong class selection, or parser loss, so rendered summaries use
  "missing/coalesced" wording rather than claiming a definite coalesce.

Each assignment also records `baseline_actual`, `baseline_status`, and
`changed` so progress is derived from baseline-to-candidate movement, not just
candidate state.

The progress kind is:

- `target-hit` when any target virtual exactly matches.
- `target-progress` when no target hits, but the aggregate force-phys distance
  improves versus the baseline distance.
- `target-missing` when any requested target is missing and no target hit
  exists.
- `spill-only` when force-phys distance does not improve but spill penalties
  improve.
- `target-no-progress` otherwise.
- `no-force-phys-targets` when there is no proof force-phys map.

The baseline distance is computed from the baseline pcdump using the same
target map. This lets ranking distinguish a real movement toward IG34/IG44 from
the reported case where IG44 is absent from candidate coloring and only spill
count improves.

### Ranking and Rendering

The existing structural guard stays as the first sort component in
`_variant_sort_key`. Inside the objective sort key, progress kinds rank in this
order:

1. `target-hit`
2. `target-progress`
3. `target-no-progress`
4. `spill-only`
5. `target-missing`
6. `no-force-phys-targets`

Existing force-phys satisfied count, missing/mismatch count, and distance remain
secondary tie-breakers. Terminal rendering will add progress kind and compact
per-target assignment text to the `force_phys` line. JSON consumers receive the
full assignment map.

## Error Handling

- Lane guard refusal is a successful scorer exit with penalty score, matching
  other unscoreable candidates.
- The unsafe lane payload is best-effort; if process scanning fails, the command
  falls back to the existing timeout error payload.
- Select-order classification must tolerate missing objective fields in older
  ledger JSON by using default sort/render behavior.

## Testing

Add focused tests for:

- `score-source` refusing to launch when `local_safety` reports an existing
  uninterruptible `wibo` for the same source.
- `score-source --json` including `unsafe_local_pcdump_lane` after a timeout
  leaves a matching unreaped process.
- Select-order objective JSON reporting baseline-relative per-target
  assignments and `target-missing` for absent IG44.
- Ranking target progress above spill-only/coalesced-target candidates even when
  the spill-only candidate has fewer unexpected spills.
- Terminal rendering includes progress kind and target assignment details.

## Self-Review

- No placeholder requirements remain.
- Scope is limited to the claimed issues.
- The design uses existing process scanning and select-order objective data.
- Ambiguous missing-target terminology is explicit: `missing_or_coalesced`
  stays at the assignment-status level while the semantic progress bucket is
  `target-missing`.
