# Issue 1139: Select-Order Param Source Bridge

## Root Cause

`debug select-order-search` can attribute a window-order lead to
`kind="param"`, but `plan_window_order_source_probes` only materialized source
probes for locals and several synthetic attribution kinds. Param attributions
therefore fell through to `unsupported-source-attribution-kind`, leaving
`source_bridge_summary.listed_source_probes=0` for `mnDiagram_8024227C`.

## Plan

- Add a reusable param-alias probe family for simple source shapes like
  `TYPE alias = param;`.
- Generate bounded full-function C probes for adjacent param-alias declaration
  order and delayed alias initialization.
- Preserve structured `source_hunks`, retained source paths, pcdump paths, and
  target scores through the existing select-order scoring flow.
- When generated probes do not satisfy the requested physical register targets,
  emit an explicit terminal proof that the param-alias family was exhausted and
  hand off to broader source-level lifetime/interference shaping.
- Cover the mechanism with synthetic planner tests plus bridge-summary and
  terminal-proof tests.

## Verification

- `PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/search/directed/test_window_order_source.py`
- `PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_select_order_search.py -k 'param_alias or terminal_exhaustion_reports_param_alias_family or materialized_field_load_action or field_load_terminal_blocker'`
- `PYTHONPATH=tools/melee-agent python -m src.cli debug select-order-search -f mnDiagram_8024227C --target 'r35<r34' --force-phys 34:29 --campaign-dir build/diagnostics/issue1139_param_alias --timeout 180 --json`

The command-level smoke generated three retained/scored param-alias probes.
All left IG34 assigned to r30 instead of r29, so the terminal proof classifies
the bounded family as exhausted and hands off to broader `arg2_r`
lifetime/interference shaping rather than retrying alias declaration-order or
delayed-init moves.
