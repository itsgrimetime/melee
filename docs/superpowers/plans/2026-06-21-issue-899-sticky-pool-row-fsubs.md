# Issue 899 Implementation Plan

## Target

Resolve issue #899 by making sticky-pool bridge output source-actionable for
the reported Case C2 row/column swap class.

## Steps

1. Add regression tests for sticky-pool target grouping and row fsubs repair
   metadata in `test_expression_interferer_repair.py`.
2. Add regression tests for window-order row fsubs source probe generation in
   `test_window_order_source.py`.
3. Add regression tests for select-order summaries that demote already
   baseline-satisfied support-order targets.
4. Update `expression_interferer_repair.py` to emit structured target groups,
   row fsubs repair metadata, and source-generation candidates that require
   expression-score validation.
5. Update `window_order_source.py` with a narrow whitelisted
   `HSD_JObjGetTranslationY(local) - local` owner-split path.
6. Update select-order terminal summaries to surface baseline-satisfied support
   orders and suggest unsatisfied alternatives.
7. Run focused pytest targets and command-level smoke checks.

## Acceptance

The #899 route is fixed when the tool either emits/scored row fsubs owner probes
or reports a named no-safe-transform/validation blocker, and when
support-before-product target orders that are already baseline-satisfied are no
longer presented as the primary repair route.
