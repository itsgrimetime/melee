# Outgoing Parameter-Area Shape Transform Design

## Problem

Issue #720 reports functions where `frame-reservations` can measure an outgoing parameter-area word-count delta, but existing frame transform probes only optimize total frame size. For `mnDiagram3_80245BA4`, the live diagnostic reports an expected/current parameter-area mismatch while total frame reservation can remain unchanged. Agents need source-edit probes that can change call argument materialization and an evaluator that treats parameter-word reduction as first-class evidence.

## Design

Use the existing transform-corpus and `debug mutate frame-transform-search` path rather than adding a command. The frame-transform path already compiles source probes, retains candidate sources, scores real match percent, and evaluates compiled frame models. The new family is `outgoing_parameter_area_shape`.

The family scans only the requested target function body. It recognizes direct call statements and assignment-call statements, including multi-line calls. It rejects nested call arguments, control-flow headers, macro-like statements, labels, and arguments whose declaration type cannot be locally inferred. Eligible call sites get exact edits in two directions: insert local temporaries immediately before the call and replace selected argument expressions with those temps, or remove immediate one-use argument locals and inline their initializers back into the call. The emitted probes are bounded: one per call site and one small same-callee batch for the materialization direction.

The evaluator uses `outgoing_parameter_area_floor.parameter_word_count_model` when present. It scores each compiled variant by candidate outgoing parameter words from either the variant objective or by comparing the variant frame model to the expected frame model. A `10 -> 8` parameter-word reduction is a satisfied transform even if total frame bytes are unchanged.

## Non-Goals

This does not alter function signatures or call contracts. It does not infer ABI rules directly from prototypes, and it does not rewrite nested calls. Unknown types are skipped instead of guessed.

## Acceptance

- `generate_transform_probes(... families=("outgoing_parameter_area_shape",))` emits concrete, non-record-only probes for high-arity call sites and immediate one-use argument locals.
- Exact-edit mutator dispatch rejects stale spans.
- `frame-transform-search --include-transform-corpus` can include the new family by default.
- `evaluate_frame_transform_probe_results` reports validated or partial parameter-area stop conditions independently of frame-size movement.
