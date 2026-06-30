# Node-Set-Split Retained Source Implementation Plan

Date: 2026-06-19
Issues: #851, #852

## Steps

1. Add regression coverage first.
   - Add a CLI test where `--source-file` is a retained source under
     `build/diagnostics/` and assert that baseline and candidate compiles use
     the real `src/<unit>.c` as `unit_source`.
   - Assert the retained source text, not the live source text, is passed into
     `generate_node_set_split_patches`.
   - Add a long candidate ID test that reaches wrong-register source retention
     without raising `OSError` and emits JSON.
   - Add a long candidate ID test that reaches realized-candidate scoring, so
     the `_score_node_set_split_candidate` temp write path is also covered.
   - Add a retained-source realized-candidate test asserting scoring receives
     `full_unit_source=True` and sees retained unit-level text outside the
     target function.
   - Add a helper-level filename cap assertion for temporary and retained
     candidate filenames.

2. Implement retained-source routing in
   `tools/melee-agent/src/cli/debug/__init__.py`.
   - Resolve `compile_unit_source` from the function's report unit.
   - Keep `resolved_source` as the mutation baseline.
   - Pass `compile_unit_source` to baseline and candidate signature compiles.
   - Use `compile_unit_source` for `--apply-best` so verified patches land in
     the real source file.
   - Transfer through the real unit source whenever a source path is not exactly
     the real unit path, even if it happens to share the source directory.

3. Implement retained-source baseline scoring.
   - Add a small helper that returns the direct baseline percent for real source
     input and scores external retained source with
     `_score_source_candidate_real_tree(..., full_unit_source=True)`.
   - Use that helper before candidate scoring so checkdiff deltas are relative
     to the selected retained baseline.
   - Pass the same full-unit flag to realized-candidate scoring and apply-best
     when the selected baseline is retained.

4. Bound candidate filenames.
   - Cap `_safe_filename` output and append a stable digest when truncated.
   - Use bounded names for temp candidates and retained source files.
   - Move candidate temp writes into the candidate try block and handle the case
     where there is no file to retain.

5. Verify and close.
   - Run focused tests in `tools/melee-agent/tests/test_node_set_split.py`.
   - Run command-level smoke checks for `melee-agent debug solve node-set-split --help`.
   - Commit the fix, merge it into `/Users/mike/code/melee` master, refresh the
     editable `melee-agent` install, and resolve #851/#852 with the commit hash.
