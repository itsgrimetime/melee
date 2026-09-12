# Issue 919 Lower-Drift Case-C Ceiling Design

## Problem

After issue 918, the Sort matcher has a useful lower-drift retained source at
`normalized_diff_lines <= 52`, but residual protected assignments remain stuck:
`IG34` wants `r27` and stays at `r28`, while `IG44` wants `r25` and stays at
`r27`. The select-order bridge can identify the residual source shape, but the
remaining `IG34` attribution is a pcode-only copy/coalesce product
(`mr r34,r37`) with `implicit-temp-no-safe-source-move`. A retained
simplify-order search from the best `type-width-0` source compiled and retained
candidate probes, but none improved residual force-phys distance.

The matcher needs a command-level answer, not another raw JSON inspection step:
either show actionable source candidates, or name the current unsupported source
span and prove the lower-drift repair lane is exhausted.

## Chosen Approach

Extend the existing read-only `debug solve allocator-ceiling` command. It already
classifies negative allocator evidence and reports practical source-shape
ceilings, so the lower-drift residual belongs there rather than in a new command.

The classifier should recognize a residual Case-C source-repair proof only when
both evidence classes are present:

1. A select-order artifact with `source_bridge_summary.leads` containing at least
   one non-actionable lead whose terminal blocker is
   `implicit-temp-no-safe-source-move` and whose source kind is
   `implicit-temp` or `copy/coalesce-product`. The source bridge itself must be
   blocked by `source-probes-exhausted`, and the select-order terminal
   exhaustion must report `transform-family-exhausted`.
2. A retained simplify-order artifact whose terminal blocker is
   `no-retained-candidate-improved-residual-force-phys`. It must be retained
   mode, include a residual force-phys map, retain at least one probe, and its
   `source_file` must match the select-order artifact's best retained source.

If both are present and no positive proof or bounded-evidence condition
overrides them, `allocator-ceiling` reports `status="practical-ceiling"` and
`terminal_reason="residual-case-c-source-repair-exhausted"`.

## Output Contract

The result includes `residual_case_c_source_repair` with:

- `status="terminal-current-source-shape-ceiling"` and
  `terminal_blocker="current-source-shape-allocator-ceiling"`;
- `blocked_source_spans`, including target IG, desired phys, order move,
  source kind, expression, source file/line, pcode first-def details, and base
  virtual when available;
- `materialized_actions` for any sibling source bridge probes that did
  materialize, so the matcher can see which part already had an actionable lane;
- `simplify_order_exhaustion`, including retained probe count, compiled count,
  and progress hits.

If the select-order bridge is present without simplify-order exhaustion, the
classifier remains `incomplete` and asks for retained simplify-order
no-improvement evidence. If neither evidence class is present, the residual
Case-C section stays `not-present` and does not affect existing verdicts.

## Tests

Regression coverage should prove:

- a select-order blocked copy/coalesce source span plus retained simplify-order
  exhaustion produces the practical ceiling verdict;
- the same bridge without simplify-order exhaustion remains incomplete;
- unblocked bridges, mismatched simplify source files, non-retained simplify
  evidence, and local source attributions do not classify as terminal;
- CLI text output names the residual copy/coalesce blocker and simplify-order
  exhaustion counts;
- existing allocator-ceiling paths keep passing unchanged.
