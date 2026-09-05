# Issue 930: Coupled address/value repair for SortNames retained Case-C

## Context

Issue 930 follows issue 929. The `retained_gpr_case_c_target_live_range_repair`
family can now materialize two SortNames probes, but both only operate on the
visible `sorted_names[j]` value expression. Scored matcher evidence says those
probes preserve IG34->r27 yet leave IG44 at r27 instead of r25. The retained
pcdump shows the target blocker is coupled: IG44 is an address temp formed from
the `max_idx` side, while IG39/IG41 are duplicate value temps around
`GetNameText(sorted_names[j])`.

The referenced `$superpowers:brainstorming` skill path was not present on this
machine. I am using the requested design cycle shape manually: plan, independent
subagent review, tests, implementation, scored smoke, and commit.

## Existing capability check

`melee-agent capabilities search "Sort retained Case-C address-temp value-temp dual repair"`
found these adjacent commands:

- `debug suggest expression-interferer-repair`
- `debug suggest register-tiebreak`

Those are diagnostic/suggestion surfaces. The issue needs retained source probe
generation through `debug search plan-transforms`, so the implementation should
reuse the existing target-live-range family and validation summaries instead of
adding a separate one-off command.

## Design

Extend `plan_target_aware_live_range_repair_probes` in
`tools/melee-agent/src/search/directed/window_order_source.py` to emit bounded
additional source probes from the same repair goal:

- address side: materialize the `max_idx` indexed-byte address expression as an
  explicit pointer temp, for example `u8* p = &sorted_names[max_idx]; ... *p`.
- value side: materialize the `j` indexed-byte value used by `GetNameText` as a
  duplicated source temp so the `r39/r41` value relation is visible.
- coupled address+value: combine the address-side pointer and value-side temp in
  one source candidate to let scoring test the allocator relation rather than
  isolated local moves.

Keep the same transform family id:
`retained_gpr_case_c_target_live_range_repair`. The family already carries the
right protected/attempted target metadata and exact/protected-negative
classification. The summary should include the new lever names and continue to
stop on exact IG34->r27 and IG44->r25.

## Tests First

Add/update regression tests before production changes:

- Unit planner test asserts the family now emits the old two probes plus the new
  `target-aware-address-side-temp`, `target-aware-value-side-temp`, and
  `target-aware-coupled-address-value` kinds from a SortNames-like retained
  source fixture.
- CLI smoke test increases `--max-per-family` and asserts `plan-transforms`
  writes/materializes all five bounded retained probes.
- Validation summary test asserts the terminal `next_source_lever_classes`
  includes the new address/value/coupled levers.

## Verification

Run the focused pytest set for window-order source and CLI smoke, compile the
changed Python files, run `git diff --check`, then run a real
`plan-transforms` smoke against the matcher worktree artifacts from issue 929.
If the generated probes score, record exact/protected-negative/lost-protected
evidence and resolve only issue 930.
