# Issue 1107: Local-Expression Target-Live-Range Handoff

## Problem

The Sort retained-frontier loop after issue 1106 had two stale handoffs:

- The target-live-range fallback still used global expressions such as
  `mnDiagram_804A076C.sorted_names[j]`, while retained source materialized in
  the active continuation used local expressions such as `sorted_names[j]` and
  `sorted_names[(max_idx)]`.
- Retained-frontier and allocator meta-ceiling synthesis still ranked an older
  `retained_gpr_common_subexpr_coalesce_source` residual after a newer
  `retained_gpr_case_c_window_order_continuation` terminal had already proven
  the same Sort force lane exhausted.

## Design

Resolve Sort target-live-range repair expressions from the retained source text
before falling back to legacy globals. Prefer local expressions first:

- value: `sorted_names[j]`
- address: `sorted_names[(max_idx)]`, then `sorted_names[max_idx]`

Use the same resolver for the default Sort fallback and for the
`--virtual-explain-json` blocker-color-chain path so both entry points
materialize probes from the same retained source surface.

For retained-frontier suppression, close only the stale common-subexpr residual
when all of these are true:

- function is `mnDiagram_SortNamesByKOs` or its known alias
- terminal family is `retained_gpr_case_c_window_order_continuation`
- terminal reason is `ranked-indexed-byte-window-order-probes-exhausted`
- attempted/protected force is exactly `{34: 27}` / `{44: 25}`
- the terminal has protected-negative scored evidence with at least one matched
  target and two targeted anchors
- the frontier being closed is the common-subexpr residual-handoff route for
  the same final force

Also apply that narrow suppression when replaying public retained-frontier
payloads into allocator meta-ceiling synthesis, because allocator diagnostics
can consume already-normalized retained-frontiers output.

## Verification Plan

- CLI smoke: default Sort target-live-range planning without explicit repair
  goals uses local retained expressions and writes probes.
- CLI smoke: `--virtual-explain-json` blocker-color-chain planning uses the
  same local retained expressions.
- Retained-frontier triage: newer Sort window-order terminal closes the stale
  common-subexpr residual handoff.
- Negative control: a window-order terminal without protected-negative scored
  evidence must not close the common-subexpr residual.
- Meta-ceiling replay: normalized retained-frontiers output should not re-rank
  the closed residual as allocator `next_frontier`.
