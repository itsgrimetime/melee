# Select-Order Causal Repair Bridges Design

Date: 2026-06-19
Issues: #844, #845

## Context

The select-order repair tooling now identifies useful source attribution, but
two mndiagram follow-up cases still stop before handing matchers an executable
next lane.

For `mnDiagram_SortNamesByKOs`, the targeted-interference summary identifies a
coupled repair pair: IG34 should move to `r27` through the bindable local
`dst_iter`, while IG44 should move to `r25` through an implicit add
(`add r44,r49,r34`). The diagnostic also has owner-split evidence for IG44:
split the C expression `dst` as `u8*`. The existing coupled node-set path only
receives the raw implicit-temp expression, so coupled request parsing drops IG44
and reports `no-coupled-probes`.

For `mnDiagram_DrawCellNumber`, the FPR protected-complement summary identifies
IG32, IG38, and IG46 as causal complement targets while preserving
IG33=`f26`, IG39=`f29`, and IG40=`f29`. IG32 is terminal for this lane because
there is no movable local write. IG38 and IG46 have materialized owner-split
probe labels, but the summary does not report a bounded causal-composition lane
that ties those probes to the scored protected-preserving candidates and the
coverage limit.

## Design

Add an executable mixed-source repair payload to
`targeted_interference_source_transforms`. The payload contains a
`materialized_node_set_delta` that preserves normal bindable local entries and
rewrites safe implicit/temp owner-split entries into typed C expressions. The
raw pcode source remains as provenance only. For IG44, the materialized source
is `kind: "synthetic-owner-split"`, `expression: "dst"`, `type: "u8*"`, and
`introduce_binding: true`; the raw `add r44,r49,r34` expression is retained in
`raw_source`.

Teach coupled node-set request parsing to honor `introduce_binding: true` and
the `synthetic-owner-split` source kind. This is necessary because a simple C
expression such as `dst` would otherwise be treated as an existing bindable
variable named `dst`, not as a typed expression that should get a new binding
before node splitting.

Add a causal complement composition lane to `protected_hit_composition`. The
lane consumes `causal_targets`, `ranked_source_hunks`, and coverage. It reports:

- protected-hit requirements that must be preserved;
- blocked targets and their terminal blockers;
- actionable causal targets, preserving every materialized owner-split label;
- scored candidates whose source composition or chain references causal labels;
- bounded pair/composition hints for the actionable causal targets;
- coverage completeness, without claiming exhaustion when the search timed out
  or hit a bounded frontier.

This keeps IG32 terminal at the target level while keeping IG38 and IG46 visible
as source-actionable owner-split work.

## Data Flow

`_select_order_protected_hit_composition_summary` already receives the ranked
composition candidates, causal target diagnostics, and targeted-interference
plan. It will attach:

- `targeted_interference_source_transforms.materialized_node_set_delta`
- `targeted_interference_source_transforms.mixed_source_repair_plan`
- `protected_hit_composition.causal_complement_composition_lane`

The mixed-source helper will return `ready` only when the materialized delta
parses into at least two coupled requests with `include_introducible=True`, or
when the helper can prove the entries are materializable without source text.
The causal lane is a summary/scoring lane only; it does not run compiles.

## Error Handling

Raw pcode expressions are never treated as safe C expressions. An implicit/temp
entry without a safe owner-split expression and type is blocked with
`implicit-temp-not-materializable`.

Coverage is incomplete when the guard-repair ledger reports `timeout`,
`frontier-empty`, `bounded-depth-exhausted`, or truncation by `max_probes`.
Target blockers remain target-local; a terminal IG32 blocker does not hide IG38
or IG46 materialized owner-split evidence.

## Testing

Focused regression tests cover:

- owner-split materialized deltas parse into coupled node-set requests while the
  raw pcode expression remains provenance only;
- raw implicit-temp entries with no owner-split evidence remain blocked;
- the Sort summary emits a materialized IG34 plus IG44 coupled delta;
- the Draw FPR summary preserves protected hits, reports IG32's blocker, lists
  all IG38/IG46 materialized labels, links scored causal candidates, and marks
  timeout/frontier coverage incomplete.
