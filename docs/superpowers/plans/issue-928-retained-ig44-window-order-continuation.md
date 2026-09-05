# Issue 928: Retained IG44 Window-Order Continuation

## Goal

Bridge retained Case-C select-order/window-order evidence into the existing
`plan-transforms` write and validation path. The targeted continuation is for
`mnDiagram_SortNamesByKOs` candidates where IG34 is already protected at r27 and
IG44 needs to move from r27 to r25.

## Approach

Add transform family `retained_gpr_case_c_window_order_continuation` with
mutator marker `steer_retained_gpr_case_c_window_order_continuation`. This
family does not use a normal mutator dispatch function because its inputs are
already full `LifetimeLayoutProbe` source candidates produced by the
window-order source planner.

Add `plan-transforms --select-order-json PATH`. The option accepts JSON emitted
by `debug select-order-search --json`, reads
`window_order_fallback.leads` and `window_order_source_attributions`, and passes
them to `plan_window_order_source_probes()`. When the option is present, the
continuation family is auto-included; callers may still request additional
families with `--transform-family`.

Convert `window-order-source-steering` probes for IG44 implicit temps into
normal transform-corpus probe records. The adapter preserves the original
window-order label, lead details, source attribution, synthetic indexed-byte
metadata, compact source diff, protected targets, and attempted targets. The
resulting probes flow through existing `--write-probes` and `--validate-command`
handling.

Classify retained validation results using `target_score.virtuals`:

- `exact`: IG34 protected target and IG44 attempted target both hit.
- `protected-negative`: IG34 hits but IG44 misses.
- `lost-protected`: IG34 misses regardless of IG44.
- `no-target-progress`: neither protected nor attempted targets hit.

Emit a bounded summary only for materialized and scored probes. If validation is
not run, report `materialized-not-scored` with a command hint instead of
claiming exhaustion.

## Acceptance Checks

- `plan-transforms --select-order-json` writes a retained IG44
  `window-order-ranked-indexed-byte...` candidate from retained source.
- Validation summaries include target-score evidence for IG34 and IG44.
- Exact IG34/IG44 hits stop as success.
- IG34-preserving IG44 misses are distinguished from candidates that lose IG34.
- Exhaustion language is only used for probes actually written and scored.
