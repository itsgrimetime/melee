# Issue 991 Implementation Plan

## Scope

Implement a post-meta-ceiling Sort source-family synthesis layer for
`mnDiagram_SortNamesByKOs`. The command consumes the retained-frontiers
meta-ceiling produced after all modeled lanes are exhausted, materializes a
bounded set of natural-C source-family probes, joins `score-source` results back
to those candidates, and emits either actionable ranked probes or a
retained-frontiers-compatible terminal proof.

## Root Cause

After issue #990, allocator-ceiling can prove the final retained-frontiers
artifact is a practical ceiling, but the next unsupported model is only
reported as text. The existing `debug search baseline-escape` implementation
contains Sort source-family dimensions, but its evidence gate expects older
allocator and supplemental artifacts and cannot consume
`meta_ceiling_sort.json` directly.

## Design

1. Add `debug search source-model-synthesis`.
2. Accept either a top-level allocator/meta-ceiling result or a retained-frontiers
   aggregate.
3. Normalize the actual `current_ceiling` shape, extracting IG34->r27 and
   IG44->r25 deterministically from duplicate allocator facts while preserving
   conflicting facts for review.
4. Reuse the existing Sort source-family neighborhood patchers from
   `post_ceiling_baseline_escape.py`.
5. Generate bounded probes for:
   - `sort-init-indexed-write`
   - `sort-indexed-byte-cache`
   - `sort-call-return-copy-local`
   - `sort-swap-slot-lvalue`
6. Emit score-source command hints and candidate metadata for target validation.
7. Treat fixture `--score-json` as offline classification and `--score` as live
   scoring against written probes.
8. Rank only structurally accepted target-progress rows as actionable.
9. Terminalize only when every generated candidate has a joined score row, no
   row has scoring errors, every structural guard is accepted, and no row moves
   IG34/IG44 onto the requested registers.
10. Emit terminal proof in the existing `post-ceiling-source-model-proof`
    contract with nested `source_model_proof.source_family_synthesis`, so
    retained-frontiers can close the broader family in a follow-up scan.
11. Record transform-corpus adapter outcomes per dimension. If no adapter input
    is available, emit explicit skipped-dimension reasons rather than silently
    claiming adapter coverage.

## Review Corrections

Independent review required:

- Do not put generation inside allocator-ceiling.
- Do not invent a terminal proof that retained-frontiers cannot consume.
- Do not terminalize on missing scores, rejected structural guards, scoring
  errors, or unjoined score rows.
- Join live and fixture score rows back to candidate metadata because raw
  `score-source` JSON may not contain enough identity fields.
- Test the real #991 meta-ceiling shape with duplicate allocator facts.

## Verification

- Focused pytest for post-meta synthesis, baseline-escape, retained-frontiers,
  allocator-ceiling, and capabilities.
- Command smoke generating probes from `meta_ceiling_sort.json`.
- Command smoke generating probes from `frontiers_all_sort.json`.
- Command smoke terminalizing all generated probes with synthetic no-progress
  score JSON.
- Retained-frontiers smoke proving the terminal output closes
  `post-ceiling-source-model-proof`.
