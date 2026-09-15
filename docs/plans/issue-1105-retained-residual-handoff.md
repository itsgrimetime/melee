# Issue 1105: Retained Residual Common-Subexpr Handoff

## Problem

The Sort KOs common-subexpression source probe reached a one-hit residual state:
IG44 was preserved at r25, while IG34 still needed r27. The downstream tools
lost that boundary. `retained-frontiers` treated the validated plan as having no
frontiers, and `allocator-ceiling` fell back to generic missing evidence.

## Root Causes

1. Retained-frontier extraction did not inherit function scope from
   `plan.function`, `request.function`, or `validation_summary.function`, so
   nested retained summaries in `plan_validated.json` could be dropped.
2. A `retained_gpr_common_subexpr_coalesce_source` `status=residual-hit`
   summary was not normalized into the real handoff contract: protect the
   preserved hit and continue only with the residual miss.
3. The residual simplify-order exhaustion existed, but no normalized retained
   frontier pointed at it, so allocator-ceiling could not distinguish an
   actionable retained handoff from missing required evidence.
4. First-divergence artifacts are advisory and may be unscoped; allocator
   scope validation should accept them when paired with scoped evidence.

## Implementation

Add regression coverage before the production change for:

- plan-validated residual hits that infer function scope and produce an
  actionable retained common-subexpr handoff;
- retained simplify-order exhaustion attachment to that handoff;
- allocator-ceiling classification of the residual handoff as actionable;
- allocator-ceiling acceptance of unscoped `allocator-first-divergence`
  advisory evidence.

Then update retained-frontier triage to:

- inherit function scope from common nested request/plan/validation containers;
- normalize common-subexpr residual hits into protected and residual force maps;
- preserve the retained source file, pcdump path, target score, source hunks,
  source-owner metadata, preserved IGs, and residual IGs in a dedicated
  `retained-common-subexpr-residual-handoff` continuation;
- attach matching retained simplify-order exhaustion metadata without turning
  it into a terminal blocker;
- avoid promoting raw nested retained probe payloads that have no summary status
  into separate frontiers.

Update allocator-ceiling to consume the normalized retained-frontier meta lane
and to treat unscoped first-divergence evidence as advisory rather than a scope
validation failure.

## Verification

Run focused retained-frontiers and allocator-ceiling tests, then smoke both CLI
commands against the Sort KOs #1104 rerun artifacts to confirm that the result
is actionable and no longer reports `no-frontiers-found` or
`missing-required-evidence`.
