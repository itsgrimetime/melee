# Issue 1128: Window-Order Call-Return and Pcode Field-Load Probes

Issue #1128 covers a tooling-only source-actionability gap in retained GPR
window-order planning. The allocator diagnostics can name source-relevant
events for `fn_80248A78`, but the source planner previously stopped at
`unsupported-source-attribution-kind` for named call-return owners and pcode-only
field loads.

The planner now handles two bounded cases:

- `call-return` attributions with a named local assignment are materialized as a
  synthetic owner split:
  `synthetic = Call(...); local = synthetic;`.
- pcode-first-def field-load-like attributions with `base_virtual` and
  `field_offset` resolve the base virtual through `source_attributions`; for
  `HSD_GObj*` offset `44`, the planner recovers `user_data` and reuses the
  existing field-load inline-temp probe.

Both paths are intentionally conservative. Call-return probing requires a unique
assignment and local declaration. Pcode field-load probing requires a resolvable
pointer base and field name. Otherwise the JSON diagnostics emit exact terminal
blockers such as `call-return-owner-copy-not-found`,
`field-load-base-source-unresolved`, `field-load-base-type-unresolved`, or
`field-load-field-name-unresolved`.

Probe provenance preserves `source_hunks`, `source_diff`,
`call_return_source_probe`, `field_load_source_candidate`, `pcode_first_def`,
and force-phys target metadata through transform-corpus continuation planning.

Completion proof for the reporter workflow should use `plan-transforms` with a
`debug target score-source` validation command. The scored artifact must include
the retained source path, retained pcdump path, `target_score`, source hunks, and
the terminal blocker/next source lever classes when the bounded candidates miss
the requested target register. For #1128, the retained call-return split remains
negative evidence for IG40->r29 and hands off to target-aware live-range or
interference-shape source levers rather than another unsupported family label.
