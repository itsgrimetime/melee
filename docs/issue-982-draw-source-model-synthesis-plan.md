# Fix plan: issue #982 Draw source-model synthesis

## Scope

Issue #982 asks for the next tooling layer after #980 for
`mnDiagram_DrawCellNumber`. The existing terminal proof correctly names the
remaining FPR expression boundary, but retained-frontier triage does not carry
the broader Draw source-family synthesis evidence into the proof artifacts that
matcher agents consume.

This plan is limited to tooling. It must not change retained Melee source in
`src/melee/mn/mndiagram.c`.

## Evidence reviewed

- Issue record: `melee-agent issue show 982`
- Extracted proof artifact:
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_981_rerun/source_model_proofs/draw_source_model_terminal_proof.json`
- Draw source-family discovery artifact:
  `/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_970_rerun/draw_baseline_escape/baseline_escape_discovery.json`
- Producer specs in
  `tools/melee-agent/src/mwcc_debug/post_ceiling_baseline_escape.py`
- Consumer proof code in
  `tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
- Focused regression tests in
  `tools/melee-agent/tests/test_retained_frontier_triage.py`

The #981/#982 proof reports `mnDiagram_DrawCellNumber` at a post-ceiling FPR
expression source-model boundary. The unresolved anchors are:

- IG32, `col_offset = y_spacing * (f32) col`, expected `f28`
- IG37, `row_offset = HSD_JObjGetTranslationY(jobj2) - base`, expected `f26`
- IG46, `fsubs f46,f45,f44`, expected `f26`

The broader Draw source-family discovery layer already has the three dimensions
needed for this issue:

- `draw-col-cast-product-local`
- `draw-row-translation-scale-split`
- `draw-digit-callarg-fsubs-temp`

## Root cause

Issue #980 added the terminal proof for the local FPR expression source-model
ceiling, and #983 later taught retained-frontier triage to preserve Sort
source-family synthesis evidence. That #983 enrichment was Sort-only. Draw proof
artifacts with expression anchors still returned the base
`post-ceiling-fpr-expression-source-model-proof` and dropped source-family
discovery, generated/scored candidate IDs, source hunks, exhausted dimensions,
and the next unsupported source model.

Older extracted #980-era proof artifacts also lack the discovery payload
entirely. They still contain enough local candidate metadata to infer a
conservative unsupported synthesis model, but only if retained-frontier triage
maps the Draw candidate families back to the broader Draw dimensions.

## Implementation plan

1. Add Draw source-family synthesis constants and an FPR synthesis proof kind:
   `post-ceiling-fpr-expression-source-model-synthesis-proof` with terminal
   reason `post-ceiling-fpr-expression-source-model-synthesis-exhausted`.
2. Replace the Sort-only enrichment gate in `retained_frontier_triage.py` with a
   small profile abstraction for supported source-model synthesis functions.
   The first two profiles are Sort and Draw.
3. Use the active profile for:
   - dimension ordering
   - missing dimension reporting
   - fallback candidate-family to dimension mapping
   - next unsupported source-model text
   - normalized extracted proof enrichment
4. For Draw, map fallback local candidates as follows:
   - paired offset / paired visible owner candidates cover column cast/product
     and row translation/scale dimensions
   - digit animation / callarg / fsubs candidates cover the digit callarg/fsubs
     temp dimension
5. Preserve richer artifact-backed synthesis evidence when present, including
   generated/scored candidate IDs, source hunks, retained scored probes,
   exhausted dimensions, missing inputs, and plateau summaries.

## Regression tests

Update `tools/melee-agent/tests/test_retained_frontier_triage.py` to cover:

- the base Draw terminal proof still names the FPR expression anchors and now
  includes fallback source-family synthesis evidence for all three Draw
  dimensions;
- an extracted Draw source-model proof artifact without discovery data is
  re-enriched from local candidate families;
- a richer Draw source-family discovery artifact emits the new FPR synthesis
  proof kind/reason and preserves generated/scored candidate IDs, source hunks,
  retained scored probes, missing inputs, exhausted dimensions, and next
  unsupported source-model text.

## Verification

Run the focused retained-frontier regression tests:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_retained_frontier_triage.py
```

Then smoke the installed CLI against the real extracted Draw proof and the
Draw source-family discovery artifact to verify the JSON proof shape seen by
matcher agents.
