# Issue 876 Expression-Aware Interferer Repair Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development when available, or the local
> fix-procedure subagent workflow when the superpowers skill path is missing.

**Goal:** Resolve issue #876 by adding a reusable evaluator that protects
source-expression anchors while diagnosing the final 5/6 FPR repair frontier.

**Architecture:** Implement a pure helper module plus a thin `debug suggest`
CLI wrapper. Do not add compiler-backed mutation loops for v1; consume existing
candidate score/residual artifacts.

**Tech Stack:** Python, Typer CLI, pytest.

## Constraints

- Preserve unrelated dirty files in `/Users/mike/code/melee`.
- Keep the evaluator pure and JSON-friendly.
- Reject improvements that only satisfy raw virtual ids while source-expression
  anchors regress.
- Commit the spec, plan, tests, fixtures, helper, and CLI together.
- Refresh the editable `/opt/homebrew/bin/melee-agent` install after commit.

## Tasks

- [x] Add expression-score fixtures for the natural 5/6 Case A frontier, forced
  6/6 proof, regressed 2/6 select-order C2 candidate, and destructive manual
  product-before-row attempt.
- [x] Add regression tests for protected expression policy, false positive raw
  virtual hits, candidate-virtual force-map derivation, residual labeling,
  ranking, terminal summaries, and source-reachability proof.
- [x] Implement `expression_interferer_repair.py` with dataclass payload types,
  candidate evaluation, ranking, residual labeling, terminal summary, and force
  proof comparison.
- [x] Add `debug suggest expression-interferer-repair` so matcher automation can
  run the evaluator from candidate JSON files.
- [x] Verify with targeted pytest and CLI help/JSON smoke checks.
