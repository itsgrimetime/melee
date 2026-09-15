# Issue 970: Post-Ceiling Source-Family Discovery Handoff

## Context

Issue #969 added final synthesis for post-ceiling baseline escape runs when all
retained frontiers and continuation routes are closed. That summary preserves
the final target force map, residual blocker targets, retained families, and
route closure. It still leaves the matcher with a generic
`current-source-shape-ceiling` when the predefined post-ceiling source families
do not move Draw or Sort.

Issue #970 asks for a bounded handoff after that terminal state. The handoff
must make the next source work concrete: name the source neighborhoods,
preserve scored retained evidence, and either emit new source-family probes or
state which bounded dimensions were exhausted.

## Design

Add a nested `post_ceiling_source_family_discovery` object to
`post_ceiling_final_summary`.

The object is diagnostic-only and deterministic. It does not run MWCC or score
new probes. It derives a bounded set of source neighborhoods from the resolved
function source, terminal target anchors, retained scored candidate rows, and
the final force map. It then emits source-actionable probe hunks for source
families outside the existing post-ceiling baseline-escape families.

For Draw, the neighborhoods are:

- `draw-col-offset-product`: the `col_offset = y_spacing * (f32) col` product.
- `draw-row-offset-scale`: the translation-delta and row-scale statements that
  feed `row_offset`.
- `draw-digit-callarg`: the digit-to-float call argument for
  `HSD_JObjReqAnimAll`.

For Sort, the neighborhoods are:

- `sort-init-pointer-walk`: initialization of `sorted_names` and `totals`.
- `sort-max-idx-indexed-byte`: indexed byte loads around `max_idx` and `j`.
- `sort-swap-materialization`: the selected slot and insertion-shift copy.

Each handoff includes:

- `source_neighborhoods`: concrete labels, anchor virtuals, line ranges, and
  baseline text snippets.
- `generated_family_dimensions`: the bounded dimensions explored.
- `probes`: new source-family probe hunks with `probe_id`, `family`,
  `dimension`, rationale, validation metadata, and `source_hunks`.
- `retained_scored_probes`: scored retained rows with candidate id, pcdump
  path, retained source path if available, expression/target scores, and
  classification.
- `final_force_phys`, `target_anchors`, and `residual_blocker_targets`.

If no supported neighborhood can be located, the handoff becomes terminal with
`terminal_reason:
post-ceiling-source-family-discovery-exhausted/bounded-source-spans-missing`
and lists the dimensions it attempted to locate.

## Scope

This feature is intentionally a handoff, not an automatic broad permuter. The
output gives matchers the next bounded candidates and enough evidence to decide
whether to score them, manually rewrite the source, or move to a broader
permuter. It does not change existing candidate generation, retained-frontier
classification, or scoring behavior.

## Testing

Regression coverage asserts that Draw and Sort final synthesis now includes the
handoff object, the expected source neighborhoods, generated probe hunks,
retained scored rows, and preserved final force maps.
