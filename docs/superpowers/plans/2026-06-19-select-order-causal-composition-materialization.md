# Select-Order Causal Composition Materialization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Resolve issues #846 and #847 by making
`debug select-order-search` emit source-actionable causal composition
candidates when protected-hit seeds and materialized owner-split complements
exist, even if the bounded guard-repair search times out before compiling a
composed candidate.

## Design

- Preserve existing compiled `scored_causal_candidates` behavior. If ranked
  candidates already reference materialized causal labels, do not add
  synthesized fallback rows.
- When no compiled causal candidates exist, synthesize candidate payloads from
  existing diagnostics only. Mark each row with
  `score_status: materialized-not-compiled`, `compiled: false`, and
  `candidate_kind: synthesized-causal-composition`.
- Reuse `targeted_interference_source_transforms` where present so mixed local
  plus implicit-temp cases can export the same coupled `node_set_delta` that
  `debug solve node-set-split --coupled` consumes. Scope reused deltas to the
  requested causal targets plus protected/non-causal entries so pair and
  singleton rows do not advertise unrelated targets.
- For pure causal owner-split lanes, build bounded combinations: all actionable
  targets together, then each actionable target alone. Blocked targets remain in
  `blocked_targets`.
- Deduplicate compiled causal rows by candidate label, referenced materialized
  labels, and target ids before considering synthesized fallbacks.
- Validate every exported `node_set_delta` through
  `requests_from_node_set_delta(..., include_introducible=True)`. Do not emit a
  delta that the node-set-split bridge cannot parse.
- Use register class context for `r`/`f` desired register labels. Prefer
  expressions accepted by node-set-split's binding-safety gate, so cast-leading
  split expressions fall back to owner locals when available.

## Verification

- Add Sort GPR regression: protected IG34 plus actionable IG44 owner split
  emits a synthesized candidate with coupled IG34/IG44 delta.
- Add Draw FPR regression: blocked IG32 stays blocked, actionable IG38/IG46
  emit pair and singleton synthesized candidates with `f` desired registers.
- Add targeted-delta regression: synthesized singleton rows filter a broader
  materialized delta to their own target while retaining protected entries.
- Add compiled-candidate regression: duplicate ranked causal payloads collapse
  to a single scored row and do not trigger synthesized fallbacks.
- Re-run existing select-order causal/mixed-source tests to ensure compiled
  candidate reporting is unchanged.
