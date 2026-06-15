# Ranked Cursor IV Unification Design

## Goal

Issue #715 is an umbrella for residual transform-corpus gaps. Several original
classes have since been implemented or corrected as backend-only: Class B/C
polarity was reversed in the issue text, Class E is covered by outgoing
parameter-area probes, and Class A has a product-recompute probe with negative
byte-match evidence. The remaining narrow source-actionable slice is Class D:
`mnDiagram2_GetRankedFighter` still compares through `entries[maxIdx].value`
even though the loop already has a cursor-derived `baseVal` accumulator.

This slice adds a guarded transform-corpus family that emits compiling source
probes for ranked selection-sort loops shaped like `mnDiagram2_GetRankedFighter`.
The first probe rewrites the indexed max-value read into the existing cursor
value accumulator and updates that accumulator when the max index changes. The
second probe reuses the already-materialized rank pointer for the final return.

## Non-Goals

- Do not edit `src/melee/mn/mndiagram2.c` as part of the tool fix.
- Do not add a new CLI command; use `debug search plan-transforms`.
- Do not implement corrected Class B/C backend levers in this slice.
- Do not resolve unrelated issue reports that are merely mentioned by #715.
- Do not auto-apply generated probes to source; the workflow writes candidates
  for compile/checkdiff scoring.

## Existing Evidence

The current `mnDiagram2_GetRankedFighter` source has:

```c
baseVal = base->value;
while (k < 25) {
    if (curr->value != (u64) neg1) {
        if (curr->value > entries[maxIdx].value ||
            baseVal == (u64) neg1)
        {
            maxIdx = k;
        }
    }
    curr++;
    k++;
}
```

and later:

```c
ptr = &entries[rank];
if (ptr->value == (u64) -1) {
    return 25;
}
return entries[rank].name;
```

The requested Class D root cause is a value/IV unification source shape: keep
the selected value in the same accumulator that was initialized from the base
cursor, and avoid re-indexing after computing `ptr`.

## Selected Design

Add a transform family:

- family id: `ranked_cursor_iv_unification`
- mutator keys:
  - `unify_ranked_cursor_value_accumulator`
  - `reuse_rank_pointer_return_field`

`ranked_cursor_iv_unification` is selected for `mnDiagram2_GetRankedFighter`
plans and can also be requested directly from `generate_transform_probes()` in
tests. It emits exact-source edit anchors and reuses the existing batch-edit
mutator machinery.

The value-accumulator probe changes the inner selection update to:

```c
if (curr->value > baseVal ||
    baseVal == (u64) neg1)
{
    maxIdx = k;
    if (baseVal != (u64) neg1) {
        baseVal = curr->value;
    }
}
```

The sentinel guard is intentional. In the current source, when the base entry
is sentinel `-1`, `baseVal == (u64) neg1` remains true for the full scan and
each valid candidate can replace `maxIdx`. Updating `baseVal` unconditionally
would change that path from "last valid wins" to "first valid wins." The probe
therefore only updates `baseVal` when the original base value was not the
sentinel.

The rank-pointer probe changes the final return to:

```c
return ptr->name;
```

The family should be visible in CLI planning with `--source-file`, even when
there is no force-phys proof vector, and should write concrete candidate `.c`
files when `--write-probes` is supplied.

## Guards

The analyzer must abstain unless it can prove the exact local pattern:

- the target function exists and has no preprocessor directives in its body,
- there is a local array indexed as `entries[...]`,
- `baseVal = base->value;` occurs before the matched `while`,
- the comparison references `curr->value > entries[maxIdx].value`,
- the update block contains `maxIdx = k;`,
- the inserted accumulator update is sentinel-preserving,
- `baseVal` is not read after the matched selection loop,
- `curr`, `baseVal`, `entries`, `maxIdx`, and `k` are simple local names,
- no matched edit crosses comments, macros, labels, or nested function-like
  macro statements,
- the exact spans are unique and validated before mutation,
- for the return probe, `ptr = &entries[rank];` and the guard on `ptr->value`
  must immediately dominate `return entries[rank].name;` in the same tail
  region.

The first implementation is intentionally pattern-specific. It may generalize
later, but it should not guess at arbitrary selection-sort structures.

## Testing

Add regression coverage for:

- metadata includes `ranked_cursor_iv_unification`,
- `plan_transform_experiments()` attaches the new family to
  `mnDiagram2_GetRankedFighter`,
- the value-accumulator probe emits the `baseVal` comparison and assignment,
- the return-field probe emits `return ptr->name;`,
- stale-span mutation rejects changed source,
- guards reject non-adjacent accumulator/update blocks and function bodies with
  preprocessor directives,
- guards reject functions that read `baseVal` after the matched loop,
- a CLI `plan-transforms --source-file --write-probes --json` smoke writes
  concrete ranked-cursor probes for `mnDiagram2_GetRankedFighter`,
- the CLI smoke omits `--force-phys` to exercise the source-only family path,
- live compile/checkdiff smoke runs at least the generated candidate path for
  `mnDiagram2_GetRankedFighter`.

## Resolution Gate

#715 may be resolved if this family produces a verified `match=true` candidate
for `mnDiagram2_GetRankedFighter`. If the family only produces compiling
negative evidence, leave #715 open with a note describing the implemented family
and remaining blocker.
