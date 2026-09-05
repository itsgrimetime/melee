# Case-C Terminal Exhaustion Design

## Context

Issue #865 is a follow-up to the retained-source Case-C FPR order repair work for `mnDiagram_DrawCellNumber`. The #864 route now runs with a concrete target order (`r33<r46`) and JSON-safe ledgers, but the retained select-order beams exhaust without any `force-phys-hit-46` candidate. The best retained variants only move IG46 from `f0` to `f1`, and the suggested `debug search combine` lane skips all combinations because their source hunks overlap.

The matcher needs a machine-readable terminal result for this state, not another blind scoring loop. The terminal result must preserve the full six-FPR target state so agents can see which protected registers were kept or lost without rescoring every retained source.

## Goals

- Surface a named soft terminal summary when retained select-order search has exhausted source probes without any hit for the blocker target.
- Preserve `target_score.virtuals` anywhere select-order summaries name terminal candidates or diagnostic buckets, when that target score is already present.
- Surface a named terminal summary from `debug search combine` when every suggested recombination is skipped due overlapping source hunks.
- Give the matcher concrete next-source-lever classes and manual-subhunk recombine guidance instead of only a generic "try recombine" command.

## Non-Goals

- Do not add a new compiler/scoring loop.
- Do not add a new source transform family in this issue.
- Do not change ranking semantics for select-order candidates or combine candidates.
- Do not modify Melee C source.

## Approaches Considered

### Approach A: Generate New Source Transform Families

Add target-aware live-range anchors or interference-shape source transforms directly to select-order search. This is attractive because it might find a candidate immediately, but it is too broad for #865: the issue already has evidence that the current bounded family exhausted, and it asks for a terminal proof when no lever exists.

### Approach B: Add a Separate Post-Processor Command

Create a new command that consumes select-order JSON and combine JSON artifacts and emits an exhaustion report. This avoids touching the hot commands, but it creates one more workflow step and would not help agents reading the primary command output.

### Approach C: Add Terminal Summaries to Existing JSON Outputs

Extend `debug select-order-search` and `debug search combine` to emit terminal summaries directly. This keeps the current workflow intact, reuses existing evidence, and gives matchers actionable state in the artifacts they already inspect.

Chosen approach: C.

## Design

### Select-Order Terminal Summary

Add a helper in `tools/melee-agent/src/cli/debug/__init__.py` that derives a `terminal_exhaustion_summary` from the already-ranked select-order variants, diagnostic buckets, force-phys targets, source bridge summary, and optional guard repair summary.

The summary is emitted when:

- a force-phys target map exists;
- the command did not time out;
- no successful variant satisfies the full force-phys target;
- the blocker target's `force-phys-hit-<ig>` diagnostic bucket is empty, even if protected targets in a wider run have hits;
- source bridge status is blocked, especially `source-probes-exhausted` or `terminal-allocator-ceiling`.

The payload includes:

- `status: "blocked"`;
- `kind: "degree-zero-fpr-case-c-source-exhaustion"` when class 1/FPR evidence is available, otherwise `"select-order-source-exhaustion"`;
- `dominant_blocker`, `blocker_classes`, and `terminal_blocker`;
- `force_phys_targets` as string keys;
- `target_score` copied from the best available objective;
- `best_retained_variants`, limited to a small ranked subset and including label, path, operator, source hunk, registers, residual analysis, and target score;
- `next_source_lever_classes`, including `manual-subhunk-recombine`, `target-aware-live-range-anchor`, and `target-aware-interference-shape`;
- `recombine_status: "unverified"` when select-order only suggested recombine and no combine artifact has been inspected.

The existing `source_bridge_summary` remains unchanged for compatibility. The new summary is additive in JSON output.

Select-order does not claim recombine exhaustion. It can say that source probes exhausted and manual subhunk recombine is the remaining lane. The hard terminal proof for skipped recombinations belongs to `debug search combine`.

### Target Score Preservation

Add a helper that extracts a target score from candidate objectives in this order:

1. `objective["target_score"]`;
2. `objective["validator_payload"]["target_score"]`;
3. `variant["target_score"]`.

Use it in:

- `_select_order_diagnostic_buckets`;
- `_select_order_source_bridge_terminal_next_lane`;
- `_select_order_source_bridge_summary` variant summaries;
- the new terminal summary.

Only copy JSON-safe dictionaries. If no target score is present, omit the field. This issue preserves target scores already produced by existing scorers; it does not add a new six-FPR rescoring hook to select-order beam scoring.

### Combine Terminal Summary

Extend `tools/melee-agent/src/search/cli/__init__.py` so `debug search combine --json` includes `terminal_summary` when:

- at least one combination was attempted;
- every combination has `status: "skipped"`;
- every skipped combination has `reason: "overlapping-source-hunks"`.

The summary includes:

- `status: "blocked"`;
- `dominant_blocker: "recombine-overlapping-source-hunks"`;
- `terminal_blocker: "manual-subhunk-recombine-required"`;
- `skipped_count`;
- `parents` for each skipped pair;
- broad hunk spans for each skipped parent so a matcher can write `--range` values without rediscovering the source lines;
- `manual_range_hint` explaining `--range CANDIDATE_ID:BASE_START-BASE_END=CANDIDATE_START-CANDIDATE_END`;
- `next_actions` with a concrete `debug search combine --range ... --json` hint.

When any combination succeeds, `terminal_summary` is omitted.

## Testing

Use TDD:

- Add a select-order unit test proving target scores are copied into diagnostic buckets and terminal summaries.
- Add a select-order unit test proving no-hit, source-probe-exhausted retained variants emit a blocked terminal summary with the expected blocker and next lever classes.
- Add a search combine CLI smoke test proving all-overlap skipped combinations emit `terminal_summary`.

Run the narrow tests first, then the touched test files, then CLI help smoke checks.

## Acceptance Criteria

- `debug select-order-search --json` can explain a no-hit retained force-phys run with a stable soft terminal summary that does not claim recombine has already failed.
- Terminal candidate summaries preserve full `target_score.virtuals` when available.
- `debug search combine --json` distinguishes "all recombinations skipped due overlap" from an empty or successful recombination run and reports hunk spans for manual subhunk recombine.
- Stable blocker names include `recombine-overlapping-source-hunks`, `transform-family-exhausted`, `missing-degree-zero-fpr-attribution`, and `current-source-shape-allocator-ceiling`.
- No unrelated dirty files in `/Users/mike/code/melee` are staged or overwritten.
- The editable `/opt/homebrew/bin/melee-agent` install is refreshed from `/Users/mike/code/melee` after the commit.

## Review Notes

An independent Codex subagent reviews this design and the implementation. Human approval is intentionally not requested because the automation instruction for #865 requires subagent review instead of human design feedback.
