# Issue #1006: Draw coupled FPR expression-lifetime lane

## Root cause

The Draw post-meta source-model pass already emits legacy single-axis probes
for column product, row translation/scale, and digit callarg/fsubs shapes. It
also adapts expression-interferer source-generation rows when that older route
is still source-actionable.

The #1006 allocator ceiling names a later unsupported class:
`draw-coupled-post-meta-fpr-expression-lifetime`. At that point the
expression-interferer/post-bridge routes are already exhausted, so the adapter
can return no new rows. The source-model pass then falls back to single-axis
Draw candidates. Those can be structurally clean, but they do not jointly alter
the IG32 column product, IG37 row fsubs, and IG46 digit fsubs/callarg lifetimes,
so the reported rerun remains 0/3 on both target and expression anchors.

## Fix plan

Add a first-class, tightly gated Draw dimension:
`draw-coupled-fpr-expression-lifetime`.

The lane opens only for `mnDiagram_DrawCellNumber` FPR contexts that carry the
coupled unsupported expression class/model. It emits a bounded set of composed
source candidates that combine existing local Draw patchers across all three
anchors instead of resurrecting exhausted expression-interferer families.

Each coupled candidate must carry source components for:

- `draw-col-offset-product`
- `draw-row-fsubs`
- `draw-digit-callarg-fsubs`

Terminal proof construction remains unchanged except that the new dimension is
recognized as Draw expression-lifetime evidence, so fully scored zero-progress
coupled rows are retained in the existing triage-compatible source-model proof.

## Regression tests

Update `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`:

- Coupled Draw ceilings generate the new dimension and expected bounded
  candidate ids.
- Non-coupled Draw ceilings do not generate coupled rows.
- A representative coupled candidate composes col, row, and digit source moves.
- Terminal proofs retain the coupled dimension, target/expression scores,
  source hunks, source components, and expression-score validation metadata.

Do not depend on the cited `build/diagnostics/mndiagram_1004_1005_rerun`
artifacts; they were not present in this checkout.

## Verification

Run:

```bash
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k 'draw and coupled'
python -m pytest tools/melee-agent/tests/test_post_meta_source_family_synthesis.py
python -m py_compile tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py tools/melee-agent/tests/test_post_meta_source_family_synthesis.py
git diff --check
```
