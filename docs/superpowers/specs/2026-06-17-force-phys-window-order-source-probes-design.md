# Force-Phys Window-Order Source Probes Design

## Goal

Close issues #749 and #750 by letting `debug select-order-search` turn solver
window-order fallback leads into source probes and compose those probes with the
existing transform corpus in beam search.

## Boundary

The solver remains diagnostic. It predicts window-order moves that may change a
target virtual's physical register, but it does not own source rewriting.
`debug select-order-search` owns orchestration, scoring, and beam composition.
The reusable source materialization belongs in a small helper under
`src/search/directed`, returning normal `LifetimeLayoutProbe` instances that
the CLI can rank with the existing force-phys objective.

No new public CLI command is needed. The behavior is additive and enabled only
when `--transform-force-phys` is present, matching the issue reports' command
shape.

## Requirements

- Preserve the existing no-force beam behavior: rank by real match percent
  first, then the select-order objective.
- In force-phys beam mode, rank frontier and final output by the existing
  select-order objective, because that objective already prioritizes
  `force_phys_satisfied_count` ahead of match percent.
- Expand transform-corpus probes per beam parent, not just at seed depth.
  This lets indexed-byte spelling probes compose with source-order probes.
- Include `window_order_fallback` in JSON output when force-phys mode runs,
  with the existing lead shape preserved.
- Generate source probes only when a fallback lead has a unique source binding.
  Missing or ambiguous source attribution is a diagnostic, not a guessed edit.
- Use existing statement-move safety rules for generic source moves. Do not
  invent a broader parser or move statements across hard barriers.

## Approach

Add `src/search/directed/window_order_source.py`.

The helper accepts source text, a function name, fallback leads, and optional
source-attribution records keyed by IG id. It locates movable statement units
with `src.search.statement_move`, binds a lead to a local by attribution name,
filters legal destinations by the lead direction (`before` means hoist, `after`
means sink), and returns `LifetimeLayoutProbe` objects with structured
provenance.

In `debug select-order-search`, compute window-order fallback only in
force-phys mode, add it to JSON output, append generated window-order probes to
the normal probe list, and include both transform-corpus and window-order probes
inside each beam round. Beam ranking uses objective-first ranking only in
force-phys mode.

## Subagent Review Notes

The independent review agreed that this should not live in solver realization
and should not become a new command. It specifically identified the current
beam loop as the #750 blocker because it only expands
`generate_lifetime_layout_probes` per parent.
