# Issue 1118: Void Inline-Boundary Probe Support

## Problem

`debug measure inline-leverage` found `HSD_JObjSetTranslateX/Y/Z_Fake` in
`mnDiagram3_8024714C`, but the first-slice de-inliner rejected the records as
`nontrivial argument would be duplicated`. The duplicate-use guard counted
field names such as `jobj->translate.y` as parameter uses of `y`, so single-use
void setters were incorrectly blocked. `debug suggest inline-boundary-continuation`
then only accepted scalar assignment-splice records, so the reporter had no
bounded retained candidate family.

## Fix

- Make void statement-splice de-inlining count parameter uses while ignoring
  struct/union field names.
- Materialize truly duplicated nontrivial void arguments into block-local temps.
- Add a void helper-boundary continuation family:
  `void_statement_splice_boundary`, `void_value_argument_temp`, and
  `void_direct_helper_call`.
- Emit `source_hunks` for retained boundary candidates and full-unit
  `score-source --retain-pcdump` hints.
- Accept stale unsupported void-duplication leverage records as continuation
  seeds so old reporter artifacts can still produce probes.
- Allow terminal proofs to consume checkdiff JSON evidence when no register
  target map exists.

## Verification

Fresh `mnDiagram3_8024714C` leverage now reports the translate helpers as
`lever` / `statement_splice`. The Y-helper continuation generated three retained
probes. Checkdiff results were bounded but not improving:

- `void_statement_splice_boundary`: 90.41892%, regressed from 97.5%.
- `void_value_argument_temp`: 97.5%, neutral.
- `void_direct_helper_call`: 89.88739%, regressed.

Feeding those checkdiff results back through
`debug suggest inline-boundary-continuation --score-json ...` emits a terminal
frontier with all three void dimensions exhausted and
`inline-leverage-helper-boundary-exhausted/no-target-progress`.
