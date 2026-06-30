# In-Place Recolor Classification Design

## Goal

Issue #728 tracks coupled same-class register-color residuals where
`node-set-split` can generate and score source-shape candidates, but no
candidate swaps the requested physical colors in place. Matching agents need a
terminal, machine-readable answer instead of another "try more source splits"
loop.

The feature should let `debug solve node-set-split --coupled --json` emit a
per-function classification when the search has reached a practical ceiling:
the existing source-shape and steering candidate families were exhausted and
every compiled candidate stayed `wrong-register`.

## Selected Approach

Add a small classification object to the existing node-set-split summary rather
than adding a speculative new mutator.

The summary already tracks:

- `wrong_register_exhausted`: true only when every generated candidate was
  compiled, no candidates are pending, no candidate/budget stop occurred, and
  every objective stayed `wrong-register`.
- `terminal_reason`: currently `all-wrong-register` for that case.
- `coupled_requests`: the exact same-class targets used in coupled mode.

When `coupled_requests` is present, attach `in_place_recolor`:

- `status: "no-shippable-mutator"` when `wrong_register_exhausted` is true.
  This means the current node-set-split plus bounded steering families did not
  produce a source-realizable in-place recolor for that delta.
- `status: "insufficient-source-bindings"` when coupled mode blocks before
  search because fewer than two requests are source-bindable.
- `status: "incomplete"` when the search stops due `candidate-limit` or
  `budget-exhausted`, including early coupled exits before baseline or
  baseline-checkdiff compilation. A generated candidate list that reaches the
  caller's `--max-candidates` cap is also incomplete unless the caller used
  `--max-candidates 0`.
- `status: "search-active"` for coupled summaries that are neither terminal nor
  blocked.

The object includes `kind`, `target_igs`, `class_id`, `evidence`, and
`recommendation`. Existing top-level fields remain unchanged for compatibility.

## Non-Goals

- Do not invent a generic source mutator that claims to swap arbitrary
  interfering colors in place. The current evidence says source-level edits
  mostly add virtuals or fail to move the physical colors.
- Do not change candidate acceptance semantics in this slice. A candidate that
  realizes the objective and improves checkdiff should still win.
- Do not classify candidate-limited or budget-limited runs as terminal.

## Testing

Add tests that prove:

- Exhaustive coupled all-wrong-register summaries include
  `in_place_recolor.status == "no-shippable-mutator"`.
- Candidate-limited coupled runs report `status == "incomplete"`, not a
  terminal no-shippable classification.
- Blocked `<2` bindable coupled runs report
  `status == "insufficient-source-bindings"`.
- CLI JSON carries the classification through the existing
  `debug solve node-set-split --coupled` path.
- Coupled early budget exits still include the classification object.

## Live Verification

Run one or more real #728 functions through:

```bash
melee-agent debug solve coloring -f <function> --class <gpr|fpr> --json
melee-agent debug solve node-set-split --coupled --node-set-delta <json> --json --max-candidates 0
```

If the run is exhaustive all-wrong-register, the summary should emit
`no-shippable-mutator`. If the run is blocked or budget-limited, the
classification should say so explicitly and should not masquerade as terminal
proof.
