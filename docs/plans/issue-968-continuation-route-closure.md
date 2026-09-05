# Issue 968 Implementation Plan

## Objective

Make post-ceiling baseline-escape continuation routes closable after their
emitted select-order commands have run and produced terminal/no-progress route
artifacts.

## Steps

1. Add regression fixtures in `test_retained_frontier_triage.py` for:
   - a post-ceiling continuation summary with two emitted routes,
   - matching route output artifacts with terminal exhaustion summaries,
   - a partial evidence case where one route terminal is missing,
   - a same-force but different-pcdump mismatch case.
2. Extend retained-frontier extraction:
   - store all post-ceiling continuation route signatures on the parent frontier,
   - store source/pcdump-aware route signatures on nested retained select-order
     command frontiers,
   - extract generic select-order terminal frontiers for both
     `degree-zero-fpr-case-c-source-exhaustion` and
     `select-order-source-exhaustion`.
3. Extend terminal suppression:
   - use generic select-order terminal signatures to suppress matching nested
     retained select-order command frontiers,
   - close post-ceiling continuation parent frontiers only when all route
     signatures have matching route terminals,
   - copy closure artifacts and route blocker summaries to the closed parent.
4. Verify baseline-escape integration:
   - retained-frontiers should now return `all-known-frontiers-exhausted`,
   - baseline-escape should no longer be blocked by the still-open continuation
     when fed the refreshed retained-frontiers artifact.
5. Run focused tests and command smokes.
6. Commit the spec, plan, tests, and implementation together.

## Risks

- Sort may emit two routes with the same class/order/force but different
  pcdumps. Source/pcdump fields must distinguish those route closures.
- Route outputs may omit source or pcdump paths. Those artifacts should not close
  route-scoped post-ceiling continuations, because Sort can have same-force
  routes that are distinguished only by retained pcdump/source.
- Nested continuation route mappings can be extracted as standalone retained
  select-order command frontiers; the suppression pass must close them too.

## Success Criteria

- With all four #968 route outputs included, retained-frontiers reports
  `all-known-frontiers-exhausted`.
- With only one of two route outputs included, retained-frontiers remains
  `actionable`.
- The public terminal frontier for the parent continuation records
  `post-ceiling-continuation-routes-exhausted/current-source-shape-ceiling`.
- No unrelated dirty files are modified.
