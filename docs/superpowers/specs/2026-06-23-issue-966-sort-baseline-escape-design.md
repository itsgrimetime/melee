# Issue 966: Sort Post-Ceiling Baseline Escape Design

## Problem

`mnDiagram_SortNamesByKOs` is at a practical allocator ceiling with normalized structural match and a GPR-only target mismatch: IG34 should land in `r27` and IG44 should land in `r25`. Existing residual Case-C, indexed-byte owner, node-set split, coalesce, pointer-reset, source-owner, and retained-frontier lanes are exhausted.

The missing virtuals are pcode-only implicit temps, so retrying source-owner probes cannot expose new bindable source variables. The resolver needs a post-current-source-shape baseline-escape layer that proposes broader coherent Sort source baselines, then either emits scored source-actionable candidates or a terminal that retained-frontier triage can suppress.

## Evidence Inputs

- Allocator ceiling: `status=practical-ceiling`, `terminal_reason=residual-case-c-source-repair-exhausted`.
- Select-order/indexed-byte evidence: source probes exhausted around `sorted_names`, `totals`, `max_idx`, and `dst_iter`.
- Node-set evidence: blocked with zero bindable coupled probes.
- Coalesce/copy-survived evidence: pointer-reset probes exhausted for the IG34/IG41 copy path.
- Retained-frontiers evidence: `all-known-frontiers-exhausted` and no next frontier for Sort.
- Target evidence: force/target JSON for IG34 to `r27` and IG44 to `r25`.

## Design

Extend `debug search baseline-escape` rather than creating a new command. The command gains a Sort evidence profile alongside the Draw expression-FPR profile:

- Draw remains expression-score based and requires the expression-interferer terminal.
- Sort accepts residual Case-C terminal evidence and optional supplemental evidence JSONs.
- Source resolution still favors explicit source, artifact-retained source, and finally repo source.
- Validation hints use GPR target-score validation for Sort.

The Sort generator emits a bounded set of natural source-shape baselines that are intentionally broader than already-exhausted local owner permutations:

- `post_ceiling_sort_address_value_pair`: materialize paired sorted-name address/value ownership before the inner comparison.
- `post_ceiling_sort_loop_shape`: make the initialization loop a pointer-walk baseline around `dst_iter` and `tp`.
- `post_ceiling_sort_swap_materialization`: materialize the selected name slot and value side of the insertion move together.

Score classification accepts either `expression_score` or `target_score` style JSON. A candidate is progress when it matches any requested target virtual. If all generated candidates are scored with no target progress, the terminal is:

`no-post-ceiling-sort-source-family/current-source-shape-ceiling`

Retained-frontier triage must recognize both Draw and Sort post-ceiling terminal kinds as the same suppression family: `post-ceiling-baseline-escape`.

## Non-Goals

- Do not retry residual Case-C owner ordering or indexed-byte source-owner families.
- Do not require expression-FPR evidence for Sort.
- Do not change decompiled source semantics or commit generated candidate sources.
