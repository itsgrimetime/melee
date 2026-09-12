# Issue #1124 Stack-Array Base Temp Probes Plan

## Scope

Issue #1124 asks `melee-agent` to turn node-set/register-tiebreak
diagnostics for `mnDiagram2_GetRankedFighter` into source-actionable probes
when a pcode virtual represents a local stack-array base, for example:

- `IG40`: `addi r40,r1,entries`, target `r25`
- `IG45`: `lwz r45,12(r50)`, target `r12`
- `IG46`: `lwz r46,8(r50)`, target `r11`

The tooling must produce bounded retained C candidates when possible, including
`source_hunks`, retained source, retained pcdumps, and `target_score`. If the
bounded family cannot jointly realize the requested registers, the command must
emit terminal proof with concrete source-level next handoff details instead of
only reporting another unsupported source model.

## Root Cause

The node-set source enrichment path could resolve field/global source owners,
but it did not model `addi rX,r1,<local_array>` as a source owner. That left
`entries`-base temps as unbindable implicit temps, so node-set split planning
either produced no candidates or dropped the base request before it could be
coupled to related load/store-address targets.

The same gap affected directed transform-corpus probes because the steering
path asks node-set enrichment for introducible requests. A stack-array base temp
never became introducible, so the corpus rejected the family as
`source-pattern-not-found` even though the C source had a real owner:
`entries`.

## Implementation

1. Add stack-array local discovery to
   `tools/melee-agent/src/mwcc_debug/source_field_attribution.py`.
   Record local arrays as element type plus pointer type, and resolve only
   simple frame-base pcode expressions of the form `addi rDEST,r1,NAME` where
   `NAME` is a real local array.

2. Extend node-set source enrichment in
   `tools/melee-agent/src/mwcc_debug/node_set_split.py`.
   Convert supported frame-base pcode into `stack-array-base` requests that are
   introducible but not treated as assignable scalar locals. Resolve related
   load/store-address requests through the same stack-array owner only when the
   base virtual maps back to that owner.

3. Add bounded stack-array base probe generation.
   Generate typed pointer binding candidates such as:

   ```c
   Entry* entries_base_bind_40_0;
   entries_base_bind_40_0 = entries;
   ptr = entries_base_bind_40_0;
   ```

4. Preserve retained evidence through the directed search and CLI validation
   paths. Candidate rows must carry source hunks, retained source, retained
   pcdumps, and target-score evidence.

5. Add terminal proof for exhausted stack-array base families.
   The proof is emitted only after actual evaluated candidates with target-score
   coverage for every requested IG. It includes candidate evidence, requested
   target registers, observed assigned registers, and a concrete source-level
   next handoff.

## Regression Tests

Add tests that cover:

- stack-array base request enrichment from `addi rX,r1,entries`;
- rejection of ambiguous stack-array field occurrences;
- bounded typed pointer binding probe generation;
- coupled synthetic stack-array base and field-load composition;
- terminal-proof guards for zero candidates, unevaluated candidates, and missing
  target-score coverage;
- directed transform-corpus probe generation with source hunks; and
- solver/CLI retained evidence and target-score output.

## Acceptance

The original #1124 workflow should now produce one bounded retained full-function
C probe for `mnDiagram2_GetRankedFighter`. The probe does not jointly recover
`IG40->r25`, `IG45->r12`, and `IG46->r11`, so the accepted result is terminal
proof showing the family was exhausted and stating the next source-level handoff:
the remaining load/store-address targets still lack a source owner for their
base virtual and that producer chain must be linked to the stack array before
retrying coupled targets.
