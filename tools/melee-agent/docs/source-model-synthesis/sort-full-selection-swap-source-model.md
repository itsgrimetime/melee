# Sort Full Selection/Swap Source Model

## Problem

`mnDiagram_SortNamesByKOs` can reach a source-model ceiling where the
lower-drift and protected-loss families prove that one target assignment is
preserved, but no bounded candidate jointly preserves `IG34->r27` and
`IG44->r25`. In that state the terminal proof names a concrete next source
model: the full Sort selection/swap source structure outside the local
protected-loss and init-lifetime families.

That next model must not remain only terminal text. Source-model synthesis
needs to materialize bounded retained C probes over the full selection,
comparison, selected-name, and swap/emission region; score those probes with
real target evidence; and then either promote a jointly preserving candidate or
emit a stronger terminal proof for the attempted full selection/swap family.

## Applicability

The first supported target is `mnDiagram_SortNamesByKOs`, implemented in the
retained source as `mnDiagram_8023FC28` in `src/melee/mn/mndiagram.c`.

The reusable class is GPR Case-C selection/swap algorithms where the selected
element, best or max state, comparison state, and swap or emission state
interact across one algorithmic region. The current implementation is
intentionally Sort-specific until another fixture proves the same structure in
another function.

## Input Evidence Contract

The synthesis path consumes:

- a source-family continuation JSON that names the full Sort selection/swap
  source structure as the next unsupported source model;
- a retained-frontiers aggregate JSON that preserves terminal frontier
  evidence for the same function;
- an allocator-ceiling JSON whose nested retained-frontiers evidence still
  names the full selection/swap model;
- the retained C baseline source for `src/melee/mn/mndiagram.c`; and
- target score-source JSON for the required assignments `IG34->r27` and
  `IG44->r25` when classifying scored probes.

The gate recognizes the canonical unsupported-model text as well as stable
tokens such as `full Sort selection/swap source structure` and
`full Sort selection/swap`.

## Candidate Contract

Generated candidates belong to the dimension
`sort-full-selection-swap-source-structure`. Each candidate must describe a
bounded full selection/swap variant rather than a local protected-loss lifetime
edit.

Required variant coverage includes:

- combined carried selection/swap state;
- loop-carried state locals;
- comparison state latched before selection update;
- stable selected-name local; and
- swap/emission pointer walk.

Each candidate records a stable candidate ID, equivalence class, variant ID,
source path when probes are written, source hunks for the replaced algorithm
region, structural guard metadata, source components, and required assignment
metadata for `IG34->r27` plus `IG44->r25`.

If the expected Sort region cannot be found in the retained baseline,
generation fails closed with
`sort-full-selection-swap-source-model-not-materialized` instead of silently
reporting that all known frontiers are exhausted.

## Scoring Contract

Real `target_score` evidence is authoritative. Estimates may rank candidates
only before real score-source results exist.

A full selection/swap candidate is actionable only when both required
assignments are preserved:

- `target_score.virtuals["34"].actual == 27` and its `matched` value is true;
- `target_score.virtuals["44"].actual == 25` and its `matched` value is true;
  and
- when checkdiff guard enforcement is enabled, the structural guard is
  accepted.

One-hit results remain ranked scored evidence, but they must not be promoted as
retained/actionable candidates.

## Terminal Proof Contract

When the full selection/swap family is generated and scored with no candidate
jointly preserving `IG34/IG44`, the terminal proof must distinguish attempted
exhaustion from pre-attempt materialization failure.

The proof should include `sort-full-selection-swap-source-structure` in the
exhausted dimensions, preserve generated and scored candidate IDs, retain
source hunks and structural guard evidence for scored probes, and name the next
unsupported family after this bounded model:
`sort-whole-function-control-data-flow-rewrite`.

It must not keep pointing at
`sort-full-selection-swap-source-model-not-materialized` after concrete full
selection/swap probes have been generated or scored.

## Retained-Frontiers And Allocator Propagation

Retained-frontiers triage prefers evidence in this order:

1. an actionable full selection/swap candidate with both required assignments
   and accepted structural guard;
2. a terminal full selection/swap exhausted proof;
3. a terminal lower-drift or protected-loss proof that names full
   selection/swap as the next unsupported model; and
4. older semantic, natural, or source-model proofs.

Retained-frontiers summaries preserve candidate IDs, dimension IDs,
`source_hunks`, `target_score.virtuals`, and `structural_guard` for retained
scored probes.

Allocator-ceiling classification may still report `status=practical-ceiling`
with
`terminal_reason=retained-frontiers-all-known-frontiers-exhausted/current-source-shape-ceiling`
when no candidate succeeds, but the nested retained-frontiers/meta-ceiling
payload must preserve the full selection/swap exhausted proof and next-family
text.

## CLI Smoke

Run commands from `tools/melee-agent` with the local module entrypoint so the
source tree under review is used. Set the checkout and artifact roots first:

```bash
MELEE_ROOT=/path/to/melee
ISSUE_WORKTREE=/path/to/worktree-containing-mndiagram_1022_rerun
```

```bash
python -m src.cli debug search source-model-synthesis --help
python -m src.cli debug solve allocator-ceiling --help
```

Generate probes from issue 1023 terminal artifacts:

```bash
python -m src.cli debug search source-model-synthesis \
  -f mnDiagram_SortNamesByKOs \
  --meta-ceiling-json "$ISSUE_WORKTREE/build/diagnostics/mndiagram_1022_rerun/retained_frontiers_after_regen/sort_allocator_after_semantic_terminal.json" \
  --retained-frontiers-json "$ISSUE_WORKTREE/build/diagnostics/mndiagram_1022_rerun/retained_frontiers_after_regen/sort_frontiers_after_semantic_terminal.json" \
  --source-file "$MELEE_ROOT/src/melee/mn/mndiagram.c" \
  --write-probes "$MELEE_ROOT/build/diagnostics/issue_1023_full_selection/source_model/probes" \
  --json
```

Expected generation output has at least one candidate with
`dimension_id=sort-full-selection-swap-source-structure` and writes retained C
probe files under the probe directory.

Offline classification can add repeated `--score-json` arguments. It exits `0`
when a candidate is actionable and `3` when the bounded family is terminal.
Terminal output must retain scored probe evidence and name the next unsupported
family after full selection/swap exhaustion.

## Related Issues

Issue 1018 identified the need for a full selection/swap source model after
earlier Sort source families were exhausted. Issue 1019 propagated exhaustion
through retained-frontiers. Issue 1022 made real score-source evidence
authoritative over semantic recombine estimates. This model is the next bounded
source-family attempt after those fixes.
