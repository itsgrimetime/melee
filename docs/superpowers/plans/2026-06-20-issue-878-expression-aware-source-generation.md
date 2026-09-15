# Issue 878 Expression-Aware Source Generation Plan

## Goal

Add a source-actionable handoff lane for protected expression-scored FPR Case A
and C2 failures in `mnDiagram_DrawCellNumber`, focused on the
`row_offset`/`col_offset_product_fpr` interference root cause.

## Implemented Vertical Slice

- Extend `mwcc_debug.expression_interferer_repair` with pure source-generation
  helpers that emit retained C candidates and source hunks without compiling.
- Extend `debug suggest expression-interferer-repair` with `--source-file`,
  `--source-function`, `--write-probes`, and `--max-source-candidates`.
- Preserve existing `--candidate-json` ranking behavior and attach
  `source_generation` as an additive payload.
- Add alias-safe diagnostics when a target label such as
  `mnDiagram_DrawCellNumber` differs from the function present in a source file.
- Add regressions for helper output and CLI probe writing using the existing
  Case A/C2 expression-interferer fixtures.

## Validation

Focused tests:

```bash
PYTEST_ADDOPTS=--no-cov PYTHONPATH=tools/melee-agent \
  pytest tools/melee-agent/tests/test_expression_interferer_repair.py -q
```

CLI smoke:

```bash
melee-agent debug suggest expression-interferer-repair \
  --candidate-json <case-a.json>,<case-c2.json> \
  --source-file <retained-source.c> \
  --source-function mnDiagram_DrawCellNumber \
  --write-probes <out-dir> \
  --json
```

The next matcher step is to score emitted probe paths through
`debug target score-source` with the same expression baseline and protected
anchor target used for the frontier.
