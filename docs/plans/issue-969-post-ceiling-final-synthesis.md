# Issue 969 Implementation Plan

## Scope

Implement route-closure-aware final synthesis in
`tools/melee-agent/src/mwcc_debug/post_ceiling_baseline_escape.py` and cover it
with focused regression tests in
`tools/melee-agent/tests/test_post_ceiling_baseline_escape.py`.

## Steps

1. Add constants for the stable final terminal:
   `post-ceiling-all-frontiers-exhausted` and
   `post-ceiling-all-frontiers-exhausted/current-source-shape-ceiling`.
2. Extend retained-frontiers normalization to summarize the requested
   function's closed families, terminal rows, and residual frontier rows.
3. Add force-map helpers that derive `{logical_ig: target_reg}` from score row
   `target_score.virtuals` and `expression_score.virtuals`.
4. Use the score-derived force map to backfill `terminal_summary`,
   `attempted_targets`, and continuation analysis when normalized evidence is
   empty.
5. Treat conflicting score-derived expected registers as an explicit
   `post-ceiling-force-map-conflict` terminal.
6. Short-circuit terminal continuation summaries without route signatures, and
   suppress source-actionable continuation routes only when their current route
   signatures match retained route closure signatures or route terminal
   blockers.
7. Preserve the existing continuation path when retained-frontiers closure is
   absent, stale, partial, or when score classification reports fresh progress.
8. Add tests for Draw exact closure suppression, Draw stale closure retention,
   Sort score-derived force preservation, conflict terminal output, and the
   existing no-closure continuation behavior.
9. Run focused pytest, lightweight lint/compile checks, and issue-artifact CLI
   smoke checks.

## Verification

- `python -m pytest tools/melee-agent/tests/test_post_ceiling_baseline_escape.py`
- `python -m py_compile tools/melee-agent/src/mwcc_debug/post_ceiling_baseline_escape.py`
- `python -m ruff check --select F,E9 tools/melee-agent/src/mwcc_debug/post_ceiling_baseline_escape.py tools/melee-agent/tests/test_post_ceiling_baseline_escape.py`
- `melee-agent debug search baseline-escape` against the issue #969 Draw and
  Sort artifact sets after refreshing the editable install.

## Review

An independent Codex subagent should review the design and final patch before
the issue is resolved.
