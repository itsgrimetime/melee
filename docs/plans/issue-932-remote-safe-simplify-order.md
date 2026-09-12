# Issue 932: Remote-Safe Retained Case-C Simplify-Order Continuation

## Root Cause

Issue #932 was filed after the retained `mnDiagram_SortNamesByKOs` frontier
exhausted the target-live-range repair family from #931. The remaining
divergence is still class 0, iteration 40, IG44, Case C: protected IG34 keeps
matching r27, but IG44 remains at r27 instead of the target r25. The existing
local `debug mutate simplify-order` lane is unsafe for this round because the
local pcdump compiler path can hit the wedged UE/wibo state, while the matcher
already uses remote `debug target score-source --remote` successfully.

## Implemented Design

Add a transform-corpus family,
`retained_gpr_case_c_simplify_order_continuation`, integrated into
`debug search plan-transforms --select-order-json`. This keeps the workflow on
the existing retained-source probe and validation path:

- consume retained source via `--source-file`
- consume retained frontier context via `--select-order-json`
- generate bounded retained `.c` probes
- validate each probe with the caller-provided remote `score-source` command
- summarize protected IG classification, retained source paths, pcdump paths,
  target scores, source hunks, and first-divergence movement

The first implementation emits conservative source variants local to the
SortNames Case-C comparison:

- max-index alias
- max-name reload
- j-name reload
- setup-order movement
- comparison block scope
- same-line max-index spelling/normalization

The generator deliberately avoids source-visible pointer walks such as
`&array[index]`, because the retained first-divergence diagnostics flagged
those as likely to perturb the implicit address-temp shape rather than steer it.

## Verification Plan

Focused tests cover:

- transform-corpus materialization and blocked diagnostics
- CLI JSON output for protected-negative/no-op remote validation
- exact-hit early stop
- registry metadata and catalog discoverability

Command-level smoke checks should run `plan-transforms` against the retained
#932 source with `--write-probes` and a remote `debug target score-source`
validation template when the remote lane is available.
