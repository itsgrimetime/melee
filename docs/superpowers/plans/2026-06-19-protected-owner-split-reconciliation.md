# Protected Owner-Split Reconciliation Plan

## Task 1: Node-Set Safe Call-Argument Bindings

- [x] Add a failing regression test showing an introducible synthetic owner
      split used only as a call argument produces a typed binding patch.
- [x] Add a failing regression test showing call-argument statements with side
      effects are rejected.
- [x] Extend `_binding_context_for_span` with a conservative expression
      statement mode for safe call-argument reads.
- [x] Run focused node-set-split regression tests.

## Task 2: Select-Order Orientation Lanes

- [x] Add a failing regression test where the primary protected orientation is
      blocked but another orientation has source-actionable materialized repair
      evidence.
- [x] Add compact orientation lane summaries and
      `source_actionable_orientations` to protected/complement repair output.
- [x] Preserve existing primary fields and nested `groups` payloads.
- [x] Run focused select-order regression tests.

## Task 3: End-to-End Verification and Queue Hygiene

- [x] Run the narrow test set for the two changed modules.
- [x] Run CLI smoke checks for node-set-split candidate generation.
- [ ] Commit the fix, integrate it into `/Users/mike/code/melee` master, and
      refresh the editable `melee-agent` install.
- [ ] Resolve #849 and #850 only after the verified commit is on master.
