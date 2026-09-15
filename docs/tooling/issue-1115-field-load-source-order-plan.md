# Issue 1115 Field-Load Source-Order Plan

## Goal

Teach the retained select-order source bridge to handle attributed struct field
loads, starting with the `HSD_GObj::user_data` load observed as
`gobj->field_at_0x2C` in `fn_802487A8`.

The issue is not resolved by merely avoiding an
`unsupported-source-attribution-kind` blocker. The reporter workflow must
produce bounded retained full-function C probes with source hunks and scoring
evidence, or terminal proof that the field-load family was safely exhausted.

## Design

- Extend `plan_window_order_source_probes` for
  `SourceAttribution.kind == "field-load"`.
- Resolve synthetic `base->field_at_0xNN` names in source context. For offset
  `0x2C`, resolve to `user_data` only when the base variable is typed as an
  `HSD_GObj*` in the function signature or local declarations.
- Generate bounded `window-order-field-load-*` probes that introduce a local
  temp and replace a concrete `base->field` occurrence in a self-contained
  statement.
- Reject unsafe continuation-only lines as
  `field-load-no-safe-insertion-point` rather than synthesizing a probe that
  changes statement semantics.
- Preserve `field_load_source_candidate`, `source_hunks`, and target selection
  metadata through transform-corpus conversion and source-bridge summaries.
- Add capability aliases so audit-first discovery points users at
  `debug select-order-search` and `debug search plan-transforms`.

## Verification

- Unit tests cover GObj user-data field-load materialization, unknown-base
  terminal blockers, bounded probe limits, continuation-line rejection,
  transform payload preservation, capability search, and source-bridge summary
  evidence.
- Reporter workflow smoke:
  `debug select-order-search -f fn_802487A8 --target r32<r72 ... --force-phys 43:31`
  emitted retained field-load probes with source hunks, retained source paths,
  pcdumps, and target scores. The safe probes did not recover IG43->r31, and
  continuation-only candidates terminalized as
  `field-load-no-safe-insertion-point`.
