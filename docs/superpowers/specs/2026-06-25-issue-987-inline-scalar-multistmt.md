# Issue 987: Inline Leverage Scalar Multi-Statement Support

## Root Cause

`debug measure inline-leverage` detected `mnDiagram_SumNameKOs` in
`mnDiagram_8023FC28`, but `build_deinline_patch` only supported non-void
single-return expression inlines and void standalone statement splices. Scalar
multi-statement helpers fell through to the generic first-slice unsupported
reason before the scorer could run.

## Implementation Plan

- Add a distinct `scalar_assignment_splice` expansion form so scalar
  multi-statement measurements are not pooled with value-expression de-inlines.
- Recognize the safe subset needed by Sort: one terminal `return local;` and a
  call that forms the complete RHS of an assignment statement.
- Preserve existing safety checks for duplicated nontrivial arguments.
- Emit specific terminal blockers for nested expression calls, declaration
  initializers, multiple returns, non-local returns, and side-effecting LHS
  forms.
- Add optional evidence retention for scored runs with baseline/deinlined
  source, baseline/deinlined checkdiff JSON, score JSON, and an explicit pcdump
  blocker noting that pcdump capture is outside the checkdiff-only scorer.

## Verification Plan

- Unit-test the Sort-style scalar assignment splice and all new blockers.
- Unit-test `measure_function_source` classification and dry-run reporting for
  the new expansion form.
- Unit-test evidence file creation with a fake checkdiff scorer.
- Smoke-test the local target with:
  `debug measure inline-leverage --function mnDiagram_8023FC28`.
