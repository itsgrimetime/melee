# Issue 1001 Sort Natural Rewrite Synthesis Plan

## Scope

Resolve tooling issue #1001: `mnDiagram_SortNamesByKOs` retained-frontier
artifacts had exhausted local one-hit source families and recombinations, but
post-meta source-model synthesis still generated only those retained
micro-family probes. Matcher agents needed a bounded natural C rewrite lane for
the broader Sort region.

## Fix

- Add stable `sort-natural-*` source-family dimensions for initialization and
  selection coupling, selection state, selected-value emission, and bounded
  region combinations.
- Gate the new Sort lane to broad-natural next-model evidence or explicit
  exhausted old Sort plus one-hit dimensions, not merely any closed
  `post-ceiling-source-model-proof` family.
- Make the retained selected-move `while (max_idx > i)` guard spec-controlled
  so natural selected-emission probes can use alternate move cursors or
  counted backward shifts.
- Carry `source_components` through generated candidates, validation metadata,
  score rows, retained scored probes, compact rows, and terminal
  `source_hunks_by_candidate` output.
- When a scored Sort natural-rewrite set has no accepted dual-target
  candidate and only structural guard rejections remain, emit a terminal proof
  with those blockers instead of dropping to a generic blocked payload.

## Verification

- Focused regression tests cover natural dimension generation, source component
  propagation, selected-move guard opt-out, negative gating, structural-rejected
  natural terminalization, CLI probe writing, and retained-frontier triage.
- Real #1001 artifact smokes generate 25 candidates, score all 25 candidates
  without score-source errors, and produce a terminal proof with all 9 natural
  candidates represented in source component evidence.
