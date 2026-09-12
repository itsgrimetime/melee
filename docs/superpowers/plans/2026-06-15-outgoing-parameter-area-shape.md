# Outgoing Parameter-Area Shape Transform Plan

## Scope

Resolve #720 by adding a reusable transform-corpus family for outgoing parameter-area call-shape probes and teaching frame-transform evaluation to score outgoing parameter words.

## Implementation Steps

1. Add regression tests for transform metadata, generated call-site and same-callee-batch probes, nested-call rejection, exact-edit mutator behavior, stale-span rejection, and parameter-word evaluator verdicts.
2. Add `outgoing_parameter_area_shape` metadata and `materialize_outgoing_parameter_area_call_args` dispatch.
3. Implement target-function call-site scanning with conservative statement/type guards and exact-edit payloads.
4. Wire the family into full-source transform generation and frame-transform default transform-corpus families.
5. Extend frame-transform scoring and stop-condition output for outgoing parameter-word objectives.
6. Update source-transform catalog metadata and invariants.
7. Verify with focused tests, affected broader suites, py_compile, `git diff --check`, and live CLI smokes against `mnDiagram3_80245BA4`.

## Review Notes

An independent Codex reviewer recommended this slice: transform-corpus family, exact-edit mutator key, default frame-transform integration, and parameter-word scoring in `frame_reservations`. The implementation follows that recommendation and avoids a new debug command.
