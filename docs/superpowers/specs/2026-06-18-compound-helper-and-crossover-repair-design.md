# Compound Helper And Crossover Repair Design

## Context

Issues #809, #810, and #811 are follow-ups to the recent source-lifetime and
guard-repair work.

#809 reports that `GetNameText` is now accepted as read-only, but repeated calls
inside compound boolean `if` expressions still stop at
`unsupported-call-site-shape`. Manual `mnDiagram_SortNamesByKOs` experiments
show that materializing an `int`/boolean "exists" temp for repeated
`GetNameText` conditions is source-actionable and can move an allocator target.

#810 reports that `debug select-order-search` can now find useful retained
one-target neighborhoods, but it does not combine retained source chains that
hit different force-phys targets. #811 is the same frontier problem in the FPR
class for `mnDiagram_DrawCellNumber`: one retained lane preserves opcode shape
and several FPR hits but grows the frame, while another lane preserves the frame
and a different subset of FPR hits.

## Approaches Considered

The smallest option is to add more issue-specific manual probes. That is quick,
but it would not help future Sort or Draw lanes and would leave the same manual
candidate workflow in place.

The broadest option is to add a new command for multi-neighborhood search. That
would keep `select-order-search` smaller, but it would duplicate candidate
parsing, source scoring, guard repair ledgers, and force-phys summaries.

The selected option extends the existing probe families and guard-repair beam.
It keeps scoring in one place, uses the existing `LifetimeLayoutProbe` payload,
and makes the new behavior available wherever retained `--candidate` sources
and force-phys maps are already supported.

## Design

### Compound Boolean Helper Reuse

`pressure_explorer` will keep the existing simple-statement
`repeated-helper-result-reuse` path unchanged for assignments, returns, and
simple call statements. A new condition-specific branch will run when the
simple-statement path rejects a repeated read-only helper occurrence because
the call is embedded in a supported `if (...) {` condition.

The condition branch will only accept simple `if` conditions in one C89-safe
block before any executable statement in that block. It will reject labels,
case labels, preprocessor regions, loop conditions, ternary/comma expressions,
mutating arguments, and helper calls whose arguments are not already considered
simple. For supported occurrences it will insert a temp before the first
condition:

```c
int ll_probe_helper_exists_0 = GetNameText(slot) != 0;
```

It will rewrite the condition expression, not blindly replace only the call
token. For pointer-return calls, supported rewrites include
`GetNameText(x) != NULL` to `exists`, `GetNameText(x) == NULL` to `!exists`, and
bare `GetNameText(x)` to `exists`. This avoids awkward or misleading
intermediate expressions such as `exists == NULL`. For scalar helpers where the
existing metadata says the direct result can be used as truthy, the initializer
may omit `!= 0`; pointer-return helpers such as `GetNameText` use `!= 0` so the
emitted local is explicitly boolean.

Short-circuit expressions are deliberately narrow. The first implementation
will accept only repeated identical calls whose arguments are already simple and
not protected by an earlier `&&`/`||` guard that makes the call argument safe.
For example, `ptr && GetNameText(*ptr)` remains unsupported because hoisting the
call would evaluate `*ptr` before the guard. Provenance records the callee, call
text, temp name, temp type, occurrence count, and
`reuse_kind=condition-bool`.

### Source-Hunk Crossover Repair

`debug select-order-search` guard repair will generate crossover probes when at
least two retained source seeds are available. The generator compares the
original base function with each seed function, extracts bounded executable
hunks, and applies donor hunks from one seed onto another seed. It should reuse
or factor the existing `debug search combine` hunk-merging logic where practical
so the project does not grow two incompatible source-hunk merge semantics. It
emits:

- single-hunk donor-to-recipient probes;
- small pair-hunk probes when the budget allows;
- provenance with donor/recipient labels, hunk indexes, source ranges,
  protected force-phys hits, and `repair_action=crossover`.

The probes are scored through the existing `_score_candidate` path, so they get
the same objective, structural guard, match percent, frame delta, and
force-phys accounting as all other select-order candidates. Guard repair will
try crossover probes before generic generated probes because crossovers directly
target retained near-miss neighborhoods. Crossovers use function-span
replacement instead of raw whole-file string replacement, cap seeds and hunks to
the existing guard-repair budgets, and protect the union of meaningful achieved
force-phys hits across donor and recipient seeds rather than only the recipient
seed's hits.

### Frame-Aware FPR Frontier Reporting

The select-order variant already contains `objective.frame_delta`,
`structural_guard`, and `delta.saved_added`/`delta.saved_removed`. Guard-repair
seed and result summaries will surface those saved-register deltas and the
actual force-phys hit/mismatch map. That gives FPR lanes a concrete frontier
report: which protected FPR hits are preserved, which are lost, whether the
candidate adds/removes saved FPRs, and whether frame delta improves.

No synthetic saved-FPR facts will be invented. If a pcdump lacks saved-register
data, the summary will omit it or report an empty delta from the existing
pressure model.

## Data Flow

For #809, `generate_source_lifetime_probes` scans helper calls, groups repeated
calls by source text, and first attempts the established simple-statement
rewrite. If the unsupported shape is an eligible condition, it emits the
condition bool-temp probe into the same source-lifetime axis output and the
existing structure search scoring path ranks it.

For #810/#811, `select-order-search` scores user-supplied or generated
candidates, ranks guard-repair seeds, loads their retained source, generates
source-hunk subtraction and crossover probes, writes them into the guard-repair
campaign directory, and appends ledger entries after scoring. Existing ranking
then chooses the next frontier by guard acceptance, protected hit count,
normalized diff lines, frame delta, force-phys distance, and match percent.

## Error Handling And Stop Conditions

Unsupported condition shapes will continue to report
`unsupported-call-site-shape`, but with source-location-oriented reasons where
possible. Crossover generation will skip unreadable sources, candidates without
extractable function bodies, non-executable hunks, duplicate body/diff hashes,
and hunks that would produce unchanged source. The guard-repair ledger records
deduped and skipped candidates.

The stop condition for #809 is that simple repeated helper calls in supported
boolean `if` conditions emit ranked source variants, while unsafe shapes remain
classified. The stop condition for #810/#811 is that bounded retained-source
crossovers are scored and the guard-repair summaries report protected hit loss,
frame delta, saved-register deltas, and concrete source paths.

## Testing

Unit tests will cover boolean helper reuse for repeated `GetNameText` in
compound conditions, continued rejection of unsafe loop/return/assignment
condition shapes, direct crossover probe generation from two retained source
neighborhoods, guard-repair scoring of a crossover candidate, and FPR/frame
summary fields for saved-register deltas.

Command-level smoke checks will cover `debug search structure` with the
source-lifetime axis and `debug select-order-search` help/JSON behavior for
guard repair.
