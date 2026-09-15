# Issue #1005: Sort semantic parenthesized-index generation

## Root cause

The Sort semantic source-model lane is gated correctly by the semantic
`next_unsupported_source_model`, but every semantic candidate uses the same
whole-region text replacement in
`tools/melee-agent/src/mwcc_debug/post_meta_source_family_synthesis.py`. The
matcher required exact spellings such as
`mnDiagram_804A076C.sorted_names[max_idx]`. Retained sources can spell the same
index as `mnDiagram_804A076C.sorted_names[(max_idx)]`, which prevented the
semantic region from matching and starved all `sort-semantic-*` dimensions.

## Fix plan

Keep generation gated exactly as before, but make Sort semantic region matching
tolerate harmless parenthesized simple indexes for the retained sorted-name
array. The canonicalization is scoped to matching spans only; generated source
still replaces the original matched source range, and no global source rewrite
is applied.

When the semantic gate is active and a semantic dimension still emits no
candidates, annotate generated payload dimensions with
`semantic-source-region-pattern-not-matched` blockers and also expose a
top-level `generation_blockers` list. This prevents silent starvation if a
future retained spelling exceeds the matcher.

## Regression tests

Update `tools/melee-agent/tests/test_post_meta_source_family_synthesis.py`:

- Parenthesized `sorted_names[(max_idx)]` and `sorted_names[(j)]` still emit
  semantic Sort candidates across all semantic dimensions.
- The private semantic region matcher accepts the parenthesized max-index
  spelling.
- If the semantic gate is active but the required source region truly does not
  match, each semantic dimension reports a no-match blocker.

Do not require the cited `build/diagnostics` artifacts in normal pytest; they
were not present in this checkout.

## Verification

Run:

```bash
PYTHONPATH=tools/melee-agent pytest --no-cov tools/melee-agent/tests/test_post_meta_source_family_synthesis.py -k 'sort_semantic and (parenthesized or gated_zero or algorithm_shapes)'
PYTHONPATH=tools/melee-agent pytest --no-cov tools/melee-agent/tests/test_post_meta_source_family_synthesis.py
```

Run a CLI smoke with a temporary source file using the parenthesized index
spelling and confirm semantic candidates are generated with no generation
blockers.
