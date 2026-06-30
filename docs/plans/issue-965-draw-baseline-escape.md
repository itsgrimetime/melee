# Issue #965 Plan: Draw Post-Ceiling Baseline Escape

## Goal

Resolve issue #965 by adding a bounded post-ceiling baseline-escape source search
for `mnDiagram_DrawCellNumber`. The new command should consume the allocator
ceiling, expression-interferer, and retained-frontier terminal artifacts, write
ranked candidate `.c` files, classify optional score JSON, and emit a terminal
when all generated post-ceiling candidates are scored without expression
progress.

## Files

- `tools/melee-agent/src/mwcc_debug/post_ceiling_baseline_escape.py`
- `tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- `tools/melee-agent/src/search/cli/__init__.py`
- `tools/melee-agent/tests/test_post_ceiling_baseline_escape.py`
- `tools/melee-agent/tests/test_retained_frontier_triage.py`
- `docs/superpowers/specs/2026-06-23-issue-965-draw-baseline-escape-design.md`
- `docs/plans/issue-965-draw-baseline-escape.md`

## Steps

1. Add the pure `post_ceiling_baseline_escape` module with artifact evidence
   normalization, retained source resolution, candidate generation, candidate
   file writing, score classification, and terminal summary construction.
2. Implement source resolution in this order: explicit `--source-file`,
   allocator-ceiling source-generation source, expression-interferer
   source-generation source, retained-frontiers source, then retained candidate
   source/path fields.
3. Add `debug search baseline-escape` in `search_app`, including validation
   metadata options for `--source-function`, `--target`, `--cflags-from`,
   `--unit-source`, `--expression-baseline`, and `--expression-source`.
4. Reject or mark candidate families that overlap exhausted/suppressed evidence,
   and include a `novelty_reason` for emitted candidates.
5. Teach retained-frontier triage to extract the post-ceiling terminal summary
   and treat `no-post-ceiling-draw-source-family/current-source-shape-ceiling` as
   terminal closure evidence.
6. Add unit tests for evidence parsing, source resolution, candidate generation,
   candidate file writing, score classification, and terminal emission.
7. Add CLI smoke coverage with `CliRunner`.
8. Run focused tests:
   `PYTHONPATH=tools/melee-agent pytest --no-cov tools/melee-agent/tests/test_post_ceiling_baseline_escape.py tools/melee-agent/tests/test_retained_frontier_triage.py -q`.
9. Run command-level smoke:
   `PYTHONPATH=tools/melee-agent python -m src.cli debug search baseline-escape
   --function mnDiagram_DrawCellNumber --allocator-ceiling-json <allocator.json>
   --expression-interferer-json <expression.json> --retained-frontiers-json
   <retained.json> --target <target.json> --cflags-from <source.c>
   --expression-baseline <baseline.pcdump.txt> --json --write-probes <tmp>`.
10. Replay the command against the live #965 artifacts without `--source-file` to
   verify it resolves the retained baseline source from retained-frontiers and
   writes candidate source files.

## Risks

The main risk is producing candidates that are too close to the already exhausted
row/product families. Keep the emitted family names distinct and require the
post-ceiling terminal stack before generation. A second risk is source-name
resolution: the live repo may use address-style function names, so the command
must prefer the retained source path embedded in artifacts when available.
