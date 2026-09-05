# Issue #1007: Sort Semantic Recombine Handoff

## Root Cause

`source-model-synthesis` generated and scored the full Sort semantic algorithm-shape set, but the terminal proof stayed single-row oriented. The scored rows contained complementary one-hit evidence: one family preserved IG34->r27, while another preserved IG44->r25. Because no dual-target row passed the structural guard, the lane terminalized without preserving a bounded recombine/protected-continuation handoff.

The existing `source-family-continuation` payload already understood external protected structural synthesis artifacts, but when no artifact was supplied it only summarized the individual one-hit rows and generic structural blockers.

## Fix Plan

- Detect Sort one-hit source rows from target-score virtuals for the protected IG34->r27 and IG44->r25 assignments.
- Build bounded pairwise recombine evidence for complementary rows, including parent IDs, source hunks, source components, target-hit estimates, structural guard data, and explicit blockers.
- Keep `source-model-synthesis` terminal when it cannot materialize a recombined source file, but include the semantic recombine evidence and next-model handoff in the terminal proof.
- Let `source-family-continuation` become actionable when a concrete non-overlapping recombine route exists. If every bounded pair is blocked, terminalize with recombine-specific blockers such as overlapping hunks or source-component conflicts.
- Update retained-frontier-compatible proof data so downstream allocator ceilings close only after the recombine evidence is present.

## Regression Coverage

- Semantic terminal proofs expose recombine candidates for complementary one-hit rows.
- Non-overlapping IG34/IG44 one-hit rows become actionable continuation candidates.
- Overlapping semantic pairs terminalize with explicit recombine/source-component blockers.
- Existing semantic terminal and retained-frontier triage tests continue to consume the proof shape.
