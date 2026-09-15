# Issue 879: expression interferer repair second generation

## Scope

Extend `debug suggest expression-interferer-repair`'s pure backend source
generator for `mnDiagram_DrawCellNumber` FPR Case A row/product interferers.
Generation stays compile-free: it emits retained `.c` probes plus metadata that
can later be scored with `debug target score-source`.

## Backend Changes

- Preserve first-generation IDs:
  - `row-offset-owner-split`
  - `product-owner-sticky-copy`
  - `row-owner-product-interleave`
- Add an expression-aware row/product source model covering:
  - direct and split row first-defs from `HSD_JObjGetTranslationY`
  - row scaled products from `row_offset *= rowf` or `row_offset = y_offset * ...`
  - direct and product-local `col_offset` materialization
  - digit-count anchors and row/product sink statements
- Add second-generation source families:
  - row first/scaled ownership
  - row sink/branch ownership
  - product materialization/sink/handoff ownership
  - guarded pure statement motion around `mn_GetDigitCount`
  - non-overlapping paired row/product recombines
- Raise backend source candidate defaults to 16 while preserving caller caps.
- Keep JSON compatibility additive and enrich ranked summaries with source hunks,
  expression virtuals, target score, match percent, structural guard details, and
  useful scoring/checkdiff extras preserved from scored payloads.

## CLI Follow-Up

`tools/melee-agent/src/cli/debug/__init__.py` had unrelated local edits during
implementation, so wrapper changes should be applied separately:

- Change `--max-source-candidates` default from `6` to `16`.
- Add `--checkdiff-guard` to generated `score_source.command`.
- Optionally add a concise terminal `terminal_summary:` line for blocked
  source-generation runs with no expression-legal 6/6 winner.

## Verification

Primary regression target:

```bash
python -m pytest tools/melee-agent/tests/test_expression_interferer_repair.py -q
```
