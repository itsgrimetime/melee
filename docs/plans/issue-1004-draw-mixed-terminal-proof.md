# Issue #1004: Draw mixed source-model terminal proof

## Root cause

The #1002 fix allowed Draw adapted expression-lifetime rows to terminalize when
all scored rows were structurally rejected, but the real Draw rerun generated a
mixed set: legacy post-meta Draw rows plus adapted expression-lifetime rows. The
terminalization gate required every rejected Draw row to be an adapted
expression-lifetime row, so a fully joined, zero-progress mixed batch still
returned `score-rows-not-terminal-safe`.

## Fix plan

Update `tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`
with a Draw-specific mixed exhaustion gate. It should terminalize only in the
Draw FPR coupled expression-lifetime context, only when every row is scored,
has no score error, has complete target-score coverage, has zero target and
expression progress, and includes at least one adapted expression-lifetime row.
Top-level blockers must remain limited to structural guard rejection, with
row-level ownership blockers preserved as terminal-safe evidence.

Preserve terminal blocker evidence in the terminal proof surfaces consumed by
retained-frontiers and allocator-ceiling:

- top-level terminal payload
- `source_model_proof`
- `source_model_proof.source_family_synthesis`
- `post_ceiling_source_family_discovery`
- `score_classification`

Keep Sort behavior unchanged and keep accepted progress actionable. Rejected
progress remains blocked/risky rather than terminalizing.

## Regression tests

Update `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`:

- Mixed legacy/adapted Draw rows with zero progress terminalize and retain
  target scores, structural blockers, and both legacy/adapted dimensions.
- Accepted target progress remains actionable.
- Rejected target progress remains blocked with `risky_candidates`.
- The mixed terminal proof is consumable by retained-frontier triage.

Do not require the cited `build/diagnostics` artifacts in normal pytest; they
were not present in this checkout.

## Verification

Run:

```bash
PYTHONPATH=tools/melee-agent pytest --no-cov tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k 'draw_mixed or draw_adapted_structural_guard or rejected_structural_guard'
PYTHONPATH=tools/melee-agent pytest --no-cov tools/melee-agent/tests/test_post_meta_source_family_synthesis.py
```
