# Issue 1108: Protected-Loss Continuation Handoff

## Root Cause

`debug solve allocator-ceiling` rejects Sort recombine artifacts before
classification because the combine result has no explicit top-level `function`.
The artifact is nevertheless function-scoped by shape: it is the Sort
protected-structural recombine result with `combinations` and
`protected_structural_synthesis`.

Direct retained-frontier evidence is also under-consumed by allocator-ceiling.
`retained_frontier_meta_ceiling_from_payloads` extracts frontiers from direct
artifacts, but when no wrapped retained-frontiers aggregate is present it keeps
only common-subexpr residual handoff frontiers. That drops direct
target-live-range terminal evidence and direct recombine terminal proof, causing
allocator-ceiling to report missing evidence or to fall back to stale older
lanes when other evidence is present.

## Implementation

1. In allocator evidence scope validation, infer
   `mnDiagram_SortNamesByKOs` only for Sort recombine artifacts that contain
   scored `combinations`, `protected_structural_synthesis`, and the concrete
   protected target set `{34: 27, 44: 25}`. Keep generic unscoped evidence
   rejection unchanged.
2. In retained-frontier meta synthesis, allow direct retained frontier artifacts
   to feed allocator meta-ceiling when they are concrete terminal/actionable
   retained-frontier evidence, not only common-subexpr residual handoffs.
   Scope this to target-live-range/protected-loss/source-model recombine
   frontier families so unrelated plan payloads are not promoted.
3. Preserve protected-loss/lower-drift intent in the recombine terminal proof:
   include `protected_structural_synthesis` blockers, next actions, required
   assignments, and ranked candidate/source-hunk evidence so the output is a
   terminal proof of the scored protected-loss recombine lane rather than a
   generic cross-TU terminal.
4. Preserve the existing behavior that wrapped retained-frontiers aggregates
   dominate their own extracted entries, so previously merged triage output is
   still authoritative.
5. Add regressions:
   - allocator-ceiling accepts a direct Sort recombine artifact without
     top-level function scope and returns a populated retained-frontiers
     terminal meta-ceiling instead of a function-scope error.
   - allocator-ceiling consumes the direct Sort target-live-range plan artifact
     as terminal retained-frontier evidence instead of treating the lane as
     not-present.
   - retained-frontier meta synthesis from direct recombine/TLR artifacts
     preserves the terminal proof and blocker families used by allocator.

## Verification

Run focused pytest for `test_allocator_ceiling.py` and
`test_retained_frontier_triage.py` additions, py-compile changed source files,
`git diff --check`, then CLI smoke:

```bash
PYTHONPATH=/Users/mike/code/melee/tools/melee-agent python -m src.cli debug solve allocator-ceiling \
  --function mnDiagram_SortNamesByKOs \
  --evidence /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_1107_rerun/sort_target_live_range/recombine/result.json \
  --json
```

Also smoke the TLR artifact directly. Refresh the editable
`/opt/homebrew/bin/melee-agent` install from `/Users/mike/code/melee` before
resolving the issue.
