# FPR Copy-Propagation Repair Design

## Context

Issue #861 covers a trace-copy case in `mnDiagram_DrawCellNumber` where the target FPR copy `f46 <- f56` is visible before copy propagation but disappears before the backend coalesce/intervention point. Issues #859 and #860 fixed class-qualified FPR handoff and force-coalesce plumbing, so `debug dump/intervene` now correctly refuses `f46=f56`: there is no direct pre-coloring copy edge left to force.

The remaining gap is diagnostic: `debug coalesce-search --trace-copy-json` can report that generic coalesce probes did not help, but it does not explain that the blocker is source/copy-propagation shape or name the unmapped FPR expressions that prevented source-actionable transforms.

## Approaches Considered

1. Add a new `debug repair trace-copy` command.
   This would isolate the concept, but it would split the matcher workflow from the command they are already using after `debug inspect trace-copy`.

2. Extend `debug coalesce-search --trace-copy-json`.
   This keeps the current issue workflow intact and allows the command to report both backend coalesce probe scoring and copy-propagation source repair status in one JSON payload.

3. Expand the transform corpus to synthesize C rewrites from raw pcode FPR expressions.
   This is the long-term target, but it needs reliable source-span attribution for expressions such as `fsubs f46,f45,f44` and `fmadds f56,f35,f55,f32`. Generating edits from unmapped pcode would be speculative.

## Design

Use approach 2. Add a `copy_propagation_repair` section to `debug coalesce-search --trace-copy-json` output. The section is emitted when the trace-copy target has `first_absent_pass == "AFTER COPY PROPAGATION"` or a `copy-propagation` transform/cause. It summarizes the FPR source and destination virtuals, their register class, first/last copy pass, and operand expressions derived from trace-copy mappings.

If any scored `.c` source candidate with retained source changes the target relation, the existing `copy_survived_repair.status == "source-actionable"` remains the actionable result, and `copy_propagation_repair` reports that a scored source candidate changed the relation. A raw `.txt` pcdump candidate, a manual pcdump, or an unscored repair sketch must not produce `source-actionable`.

If no scored source candidate changes the target relation, the new section reports a terminal blocker. When source expressions are unmapped to concrete C source, the blocker must name the unmapped virtuals using the correct register prefix and include the pcode expressions or first-def operands that could not be converted into source edits. This directly satisfies the #861 stop condition without inventing unsafe source patches.

When future trace-copy JSON contains concrete source expressions for both sides, the same section may expose deterministic repair ideas as metadata, but it must still report `terminal-blocker` until at least one scored retained source candidate changes the target relation.

## Trace-Copy Normalization

The loader normalizes only fields produced by `debug inspect trace-copy --json`:

- `first_absent_pass`, `first_copy`, `last_copy`, `likely_cause`, and `transform_category` are copied from the top level.
- For each of `from_mapping` and `to_mapping`, the loader preserves `class_id`, `assigned_reg`, `ig_idx`, `first_occurrence`, `last_occurrence`, and `call_return_origin`.
- Register class is resolved from explicit top-level `register_class`, then mapping `class_id`, then FPR/GPR tokens in mapping first/last occurrences. Top-level copy operands are used only as a fallback because real FPR trace-copy artifacts can spell the pseudo-copy itself as `mr r46,r56` while the defining operands are `fmadds f56,...` and `fsubs f46,...`.
- The operand expression is resolved from `call_return_origin.expression` first, then `call_return_origin.call_symbol`, then `first_occurrence.opcode + " " + first_occurrence.operands`.
- `mapped_to_source` is true only when `call_return_origin.source_file` and `call_return_origin.source_line` are present. Pcode-first-def expressions such as `fmadds f56,f35,f55,f32` are useful diagnostics, but they are not source-mapped edits.

## JSON Contract

`copy_propagation_repair` includes:

- `status`: `not-applicable`, `source-actionable`, or `terminal-blocker`
- `first_absent_pass`
- `register_class` and `class_id`
- `target_pair`: rendered as `f56/f46` for FPRs and `rA/rB` for GPRs
- `source_operands.from` and `source_operands.to`, each with `virtual`, `token`, `expression`, `source_file`, `source_line`, `confidence`, `first_occurrence`, and `mapped_to_source`
- `ranked_source_repairs`: deterministic repair sketches when source operands are mapped; these do not by themselves make the result source-actionable
- `best_source_candidate`: present only for a scored `.c` source candidate whose objective changes the target relation
- `terminal_blocker`: explanation naming unmapped operands when edits cannot be generated safely

## Testing

Add regression coverage in `tools/melee-agent/tests/test_coalesce_search.py`:

- A FPR trace-copy JSON with `first_absent_pass: "AFTER COPY PROPAGATION"` and only pcode first-def mappings should produce `copy_propagation_repair.status == "terminal-blocker"` and include `f56`, `f46`, `fmadds`, and `fsubs`.
- A scored `.c` source candidate that changes the FPR target relation should produce `status == "source-actionable"`, include `best_source_candidate`, and preserve frame/spill/objective details.
- A trace-copy JSON with source-mapped operands but no scored source candidate should not produce `source-actionable`.
- A mixed mapped/unmapped operand case should still produce a terminal blocker naming the unmapped side.
- Non-copy-propagation disappearance should produce `not-applicable`; copy-propagation `transform_category` should apply even when `first_absent_pass` is absent.
- Text output should mention the copy-propagation terminal blocker for FPR targets.

## Non-Goals

This change does not synthesize speculative C edits from unmapped pcode expressions. It also does not change backend force-coalesce behavior; after #860, refusing a missing pre-coloring edge is correct.
