# Node-Set Planning Diagnostics Implementation Plan

Date: 2026-06-18
Issues: #783, #784, #785

## Steps

1. Add regression coverage first.
   - Add a node-set helper test that rejects a synthetic local used outside its declaration block.
   - Add a repeated-local source-line test that prefers an innermost shadowing scope.
   - Add a node-set introduce-binding test that fails if recursive split generation invokes combo expansion when disabled.
   - Add a summary test for wrong-register row residual fields and retained source path.
   - Add a summary test for mixed wrong-register and compile-failed terminal exhaustion.

2. Implement candidate validity checks.
   - Add a local declaration/use scope helper in `tools/melee-agent/src/mwcc_debug/node_set_split.py`.
   - Apply it to alias and lifetime candidates before `_append_unique_patch`.
   - Prefer the innermost containing declaration when source-line scope anchoring sees multiple same-name locals.

3. Bound plan-transform generation.
   - Add `include_split_combos` to `generate_node_set_introduce_binding_patches`.
   - Pass `False` from coupled/request composition and from `transform_corpus.register_steering`.

4. Expose wrong-register evidence.
   - Generalize source retention in `tools/melee-agent/src/cli/debug/__init__.py`.
   - Retain compile-ok wrong-register candidates and store the retained path in the objective and scored entry.
   - Extend `_score_row` to surface row-level target/achieved register fields and coupled residuals.
   - Mark wrong-register plus compile-failed exhaustive rows as terminal source-shape exhaustion.

5. Verify and close.
   - Run focused tests for node-set split and solve CLI.
   - Run CLI smoke checks for solve and plan-transforms help.
   - Refresh editable `melee-agent` install from `/Users/mike/code/melee`.
   - Resolve #783, #784, and #785 with the commit hash if verification passes.
