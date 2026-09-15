# Post-Cross-TU Sort Terminal Proof

`source-model-synthesis` consumes the final retained-frontier Sort ceiling after
the cross-TU symbol/linkage and data-section ownership layer has been scored.
That state is terminal. It should not generate another bounded source family or
loop back to the older local Sort probes.

The final non-looping next family is:

```text
sort-no-modeled-source-actionable-family-after-cross-tu-linkage
```

Terminalization is evidence-gated. The final family and model are not enough by
themselves; the proof must also carry the cross-TU layer id,
`sort-cross-tu-symbol-linkage-or-data-section-ownership-source-context`, retained
real score rows, and one-hit evidence showing that the protected targets were
not jointly preserved.

The terminal payload preserves retained evidence in three places:

- top-level `candidate_scores`, `retained_scored_probes`,
  `source_hunks_by_candidate`, and `scored_count`;
- `source_model_proof`;
- `source_model_proof.source_family_synthesis`.

Retained rows keep their score-source evidence, including `source_retained`,
`pcdump_path`, `target_score`, and `structural_guard` where present. The emitted
terminal blockers include both
`no-modeled-source-actionable-family-after-cross-tu-linkage` and
`one-hit-protected-targets-not-jointly-preserved`.

Replay:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug search source-model-synthesis \
  --function mnDiagram_SortNamesByKOs \
  --meta-ceiling-json build/diagnostics/mndiagram_1030_rerun/retained_frontiers_after_source_family_continuation/sort_allocator_after_source_family_continuation.json \
  --retained-frontiers-json build/diagnostics/mndiagram_1030_rerun/retained_frontiers_after_source_family_continuation/sort_frontiers_after_source_family_continuation.json \
  --source-file src/melee/mn/mndiagram.c \
  --json
```

Expected output has `status="terminal"`, `candidate_count=0`, retained score
evidence under `source_model_proof.source_family_synthesis`, and
`next_unsupported_source_family` set to the final no-modeled-source sentinel.
