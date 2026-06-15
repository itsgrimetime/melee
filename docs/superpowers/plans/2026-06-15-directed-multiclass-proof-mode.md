# Directed Multi-Class Proof Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or equivalent review checkpoints when
> implementing this plan.

**Goal:** Let `debug search directed` handle mixed GPR/FPR force-phys proofs by
splitting them into per-class directed runs and aggregating their evidence.

**Architecture:** Keep the directed search engine single-class. Add grouped
proof parsing and aggregate JSON only at the CLI boundary in
`tools/melee-agent/src/search/cli/__init__.py`.

## Tasks

- [x] Add grouped force-phys parser while preserving the existing single-class
      parser and error semantics for callers that still require one class.
- [x] Refactor `--directed-from-diff` proof derivation so standalone directed
      mode can consume grouped proof vectors.
- [x] Update `debug search directed` to run one directed search per class when a
      mixed proof is provided.
- [x] Aggregate per-class result JSON with class-tagged telemetry, grouped proof
      metadata, per-class accounting, and conservative gate reduction.
- [x] Add CLI regressions for explicit mixed proof and mixed
      `--directed-from-diff`.
- [x] Add a downstream regression proving the aggregate payload feeds
      allocator-ceiling practical-ceiling classification.
- [x] Run focused tests and a real command-level smoke on `mnDiagram3_8024714C`.
- [x] Request independent review before committing.
- [x] Address review findings for aggregate bounded accounting and
      class-aware backend blockers.
