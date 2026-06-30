# Fix #958: post-ceiling retained frontier triage

## Reviewed Context

- Target checkout reviewed: `/Users/mike/code/melee`.
- Issue #958 is open and already claimed by `codex-fd86-issue-resolver`.
- `melee-agent capabilities search "post-ceiling retained frontier triage allocator ceiling retained frontier ranking"` only surfaces adjacent tools:
  - `debug solve allocator-ceiling`
  - `debug permute remote triage`
  - `debug permute triage`
  - `debug search triage`
  - `debug suggest protected-expression-reconcile`
  - `scratch recover-best`
  - `/fresh-eyes`
- The exact current issue artifacts are not present in `/Users/mike/code/melee`, but they are present in the issue-origin worktree `/Users/mike/.codex/worktrees/eeff/melee`.
- `/Users/mike/code/melee` is already dirty. User-owned changes currently include:
  - `tools/melee-agent/src/cli/debug/__init__.py`
  - `tools/melee-agent/src/cli/scratch/__init__.py`
  - `tools/melee-agent/src/cli/sync/production.py`
  - `tools/melee-agent/src/search/solver/solve.py`
  - `tools/melee-agent/tests/search/solver/test_solve.py`
  - `tools/melee-agent/tests/test_scratch.py`
  - untracked `docs/matching-tooling-postmortem-2026-06-15.md`

## Root Cause

`debug solve allocator-ceiling` can classify a single evidence bundle and already knows the two terminal lanes named in #958:

- Sort: `target-only-backprojection-source-probe-continuation-terminal`, with resolver blocker `addi-copy-product-operands-not-source-visible`.
- Draw: `target-only-c2-sticky-pool-source-attribution-terminal`, with `evaluated_probe_count=42`, `exact_count=0`.

The missing tool is a cross-artifact retained-frontier aggregator. Existing diagnostics write useful retained summaries into many JSON shapes, especially:

- `validation_summary.retained_case_c_*_summary`
- top-level `retained_case_c_*_summary`
- `target_only_backprojection_source_probe_continuation`
- `target_only_c2_sticky_pool_attribution`
- resolver artifacts such as `kind=target-only-backprojection-addi-copy-product-source-resolver`

No command walks the diagnostic forest, canonicalizes equivalent lanes, applies later terminal evidence as a closure, and ranks only retained frontiers that remain actionable. That is why manual navigation through `mndiagram_sort_*` and `mndiagram_draw_*` directories became the blocker.

## Smallest High-Leverage Implementation

Add a read-only diagnostic triage command under the existing search surface:

```bash
melee-agent debug search retained-frontiers \
  --function mnDiagram_SortNamesByKOs \
  --function mnDiagram_DrawCellNumber \
  --artifact-glob 'build/diagnostics/mndiagram_sort_*/*.json' \
  --artifact-glob 'build/diagnostics/mndiagram_draw_*/*.json' \
  --json
```

This belongs under `debug search`, not `debug solve`, because it ranks and routes existing retained candidates rather than proving a new allocator ceiling. It also avoids editing the currently dirty `tools/melee-agent/src/cli/debug/__init__.py`.

## Files To Touch

- Add `tools/melee-agent/src/mwcc_debug/retained_frontier_triage.py`
  - Pure library logic for artifact discovery, JSON walking, frontier extraction, terminal closure, ranking, and output shaping.
- Edit `tools/melee-agent/src/search/cli/__init__.py`
  - Add `@search_app.command("retained-frontiers")`.
  - Keep the CLI thin: path resolution, options, call library, print JSON/text, set exit code.
- Edit `tools/melee-agent/src/cli/capabilities.py`
  - Add aliases for:
    - `post ceiling retained frontier`
    - `retained frontier triage`
    - `alternate retained frontier ranking`
    - `mndiagram retained frontier`
  - Target: `debug search retained-frontiers`.
- Add `tools/melee-agent/tests/test_retained_frontier_triage.py`
  - Unit and CLI regression tests for the new library/command.
- Edit `tools/melee-agent/tests/test_capabilities.py`
  - Assert the new alias resolves and search surfaces the command.

Avoid touching existing dirty files unless the implementation is moved to `debug solve`. If that move becomes necessary, inspect and preserve every pre-existing hunk in `tools/melee-agent/src/cli/debug/__init__.py`.

## CLI Behavior

Command:

```bash
melee-agent debug search retained-frontiers [OPTIONS]
```

Options:

- `--function, -f TEXT` repeatable. If omitted, infer functions from artifacts.
- `--artifact, -a PATH` repeatable. Accepts JSON files or directories; directories recurse for `*.json`.
- `--artifact-glob, -g TEXT` repeatable. Glob relative to the repo root unless absolute.
- `--diagnostics-root PATH` default `build/diagnostics`. Used when no artifacts/globs are supplied; scan `**/*.json`.
- `--max-files INT` default `2000`. Abort with exit 2 if exceeded unless explicitly raised.
- `--json/--text` default `--json`.

Exit codes:

- `0`: at least one unexhausted retained frontier has a concrete continuation command or source hunk route.
- `3`: artifacts were understood, but all known retained frontiers are terminal or no retained frontier exists for the requested function(s).
- `2`: invalid input, unreadable JSON, mixed-function filtering errors, or scan limit exceeded.

## Output Schema

Top-level JSON:

```json
{
  "status": "actionable | all-known-frontiers-exhausted | no-frontiers-found",
  "artifact_count": 0,
  "functions": [
    {
      "function": "mnDiagram_SortNamesByKOs",
      "current_match_percent": 99.35,
      "frontiers": [],
      "terminal_frontiers": [],
      "next_frontier": null,
      "summary": {
        "unexhausted_count": 0,
        "terminal_count": 0,
        "suppressed_by_terminal_count": 0
      }
    }
  ],
  "next_frontier": null
}
```

Each frontier record:

```json
{
  "rank": 1,
  "frontier_id": "stable canonical id",
  "function": "mnDiagram_DrawCellNumber",
  "artifact": "build/diagnostics/...",
  "summary_path": "validation_summary.retained_case_c_target_live_range_repair_summary",
  "family_id": "retained_fpr_case_c_target_live_range_repair",
  "kind": "retained-source-case-c-target-live-range-interference",
  "status": "blocked",
  "terminal": true,
  "terminal_reason": "target-only-c2-sticky-pool-source-attribution-terminal",
  "closed_by": ["build/diagnostics/.../allocator_ceiling_aggregate_plus_sticky.json"],
  "attempted_targets": {"37": 26},
  "protected_targets": {"32": 26},
  "target_hits": {"37": false},
  "protected_hits": {"32": true},
  "match_percent": null,
  "normalized_drift": {
    "normalized_diff_lines": null,
    "target_score_total": null,
    "virtual_distance": null,
    "candidate_final_distance": null,
    "baseline_final_distance": null
  },
  "metrics": {
    "evaluated_probe_count": 42,
    "exact_count": 0,
    "protected_negative_count": 38,
    "lost_protected_count": 4,
    "targeted": null,
    "matched": null
  },
  "best_candidate": {
    "probe_id": "retained_fpr_case_c_target_live_range_repair@0",
    "source_retained": "build/diagnostics/.../probe.c",
    "source_hunk": null,
    "source_diff": null
  },
  "continuation": null
}
```

For an unexhausted source route:

```json
{
  "terminal": false,
  "actionable": true,
  "continuation": {
    "route": "source-hunk",
    "source_retained": "build/diagnostics/.../candidate.c",
    "source_hunk": {
      "strategy": "case-c-max-index-probe-decl-before-dst-iter",
      "tag": "delete",
      "base_start": 908
    }
  }
}
```

For an unscored retained candidate:

```json
{
  "continuation": {
    "route": "score-source",
    "command": "melee-agent debug target score-source build/diagnostics/.../candidate.c --function mnDiagram_SortNamesByKOs --json --retain-pcdump"
  }
}
```

## Frontier Extraction Rules

Walk all JSON mappings and extract frontiers from:

- `target_only_backprojection_source_probe_continuation`
- `target_only_allocator_backprojection.source_probe_continuation`
- `target_only_c2_sticky_pool_attribution`
- `target_only_allocator_backprojection.c2_sticky_pool_attribution`
- `retained_case_c_window_order_continuation_summary`
- `retained_case_c_post_source_owner_backtrack_summary`
- `retained_case_c_target_live_range_repair_summary`
- `retained_gpr_common_subexpr_coalesce_source_summary`
- `retained_case_c_simplify_order_continuation_summary`
- `validation_summary.*_summary`
- resolver artifacts with `kind=target-only-backprojection-addi-copy-product-source-resolver`

Normalize all target maps to string IG keys and integer phys values.

Canonical frontier keys:

- Addi/copy-product terminal:
  - `function + target-only-backprojection-addi-copy-product + pcode_lever + final_force_phys`
- C2 sticky pool terminal:
  - `function + target-only-c2-sticky-pool + class_id + attempted/protected/final_force_phys`
- Retained summary:
  - `function + kind/family_id + attempted_targets + protected_targets + final_force_phys`
  - Include source owner expression only when needed to distinguish independent lanes.

Terminal classification:

- `complete=true` and `status` starts with `terminal`.
- `terminal_blocker` present with terminal statuses such as `blocked`, `scored-negative`, `terminal-blocked`, `exhausted`, and `exact_count=0`.
- Allocator-ceiling terminal reasons:
  - `target-only-backprojection-source-probe-continuation-terminal`
  - `target-only-c2-sticky-pool-source-attribution-terminal`
  - `residual-case-c-source-repair-exhausted`
  - `expression-scored-fpr-allocator-ceiling`

Actionable classification:

- `status=exact`
- `status=residual-hit`
- any best candidate with `classification` in:
  - `residual-hit-protected-lower-drift`
  - `lower-drift-frontier`
- `status=materialized-not-scored` with retained `.c` paths or `command_hints`
- bounded/incomplete records with an explicit `resume` or command hint
- `target_only_allocator_backprojection.status=source-actionable` only if no terminal source-probe continuation closes it

Suppression:

- Terminal addi/copy-product resolver evidence suppresses older target-only addi/copy-product recommendations for the same pcode lever and force vector.
- Terminal C2 sticky-pool attribution suppresses retained target-live-range and alternate-source-owner source-owner lanes with matching attempted/protected/final force vectors.
- Suppression must be recorded in `closed_by` so the JSON explains why a promising old retained candidate was not recommended.

## Ranking

Sort per function:

1. Unexhausted before terminal.
2. Exact candidates.
3. Residual-hit/source-hunk candidates.
4. Lower-drift/frontier candidates that preserve protected targets.
5. Materialized but unscored candidates with a runnable score command.
6. Bounded/incomplete candidates with a resume command.
7. Terminal frontiers.

Tie breakers:

- More attempted target hits.
- More protected target hits.
- Lower `normalized_diff_lines` when available.
- Lower `candidate_final_distance` or `target_score.total` when available.
- Higher `match_percent` when available.
- Newer artifact mtime.
- Stable path/probe id.

## Regression Tests

Add `tools/melee-agent/tests/test_retained_frontier_triage.py`.

Tests:

1. `test_sort_addi_copy_product_terminal_suppresses_old_source_actionable_lane`
   - Build temp artifacts:
     - an older source-actionable target-only backprojection or retained summary for `mnDiagram_SortNamesByKOs`
     - a terminal resolver artifact matching `target-only-backprojection-addi-copy-product-source-resolver`
   - Assert:
     - output status is exhausted if no other frontier exists
     - terminal frontier cites both terminal evidence files
     - no `next_frontier` points at the addi/copy-product lane
     - `baseline_score=25`, `best_score=266`, `target_hits=0`, `protected_preserved=false` are preserved when present

2. `test_draw_c2_sticky_pool_terminal_suppresses_current_and_alternate_owner_lanes`
   - Build temp artifacts with:
     - a blocked `retained_case_c_target_live_range_repair_summary`
     - an alternate owner summary with `current-source-owner-probes-exhausted`
     - a terminal allocator aggregate with `target_only_c2_sticky_pool_attribution.complete=true`, `evaluated_probe_count=42`, `exact_count=0`
   - Assert:
     - all matching Draw source-owner lanes are terminal/suppressed
     - `closed_by` points to the aggregate evidence
     - output is `all-known-frontiers-exhausted`

3. `test_unexhausted_source_hunk_frontier_ranks_above_terminal_noise`
   - Use a retained simplify-order summary with `status=residual-hit`, a best candidate containing `source_hunk`, `source_retained`, target/protected hit maps, and candidate/baseline distance.
   - Include an unrelated terminal artifact.
   - Assert:
     - output status is `actionable`
     - top frontier has `continuation.route=source-hunk`
     - metrics include target hits, protected hits, and normalized drift fields

4. `test_materialized_not_scored_frontier_emits_score_source_command`
   - Summary has `status=materialized-not-scored` and a retained `.c` candidate path.
   - Assert command is:
     - `melee-agent debug target score-source <candidate> --function <fn> --json --retain-pcdump`

5. `test_retained_frontiers_cli_accepts_multiple_functions_and_globs`
   - Use `CliRunner` against `search_app`.
   - Assert JSON contains separate function entries and the command exits `0` when one function is actionable.

6. `test_retained_frontiers_cli_exits_3_when_all_known_frontiers_exhausted`
   - Assert exit code `3` and terminal evidence paths are present.

7. Update `test_capabilities.py`
   - Assert `cap.run_search("post ceiling retained frontier triage", REPO)` returns `debug search retained-frontiers`.
   - Assert `cap.run_search("alternate retained frontier ranking", REPO)` returns `debug search retained-frontiers`.

## Smoke Checks

Run from `/Users/mike/code/melee` after implementation:

```bash
python -m pytest \
  tools/melee-agent/tests/test_retained_frontier_triage.py \
  tools/melee-agent/tests/test_capabilities.py \
  -q
```

```bash
melee-agent capabilities search "post-ceiling retained frontier triage"
```

If the current issue artifacts are still only in the `eeff` worktree, smoke the command with absolute artifacts:

```bash
melee-agent debug search retained-frontiers \
  --function mnDiagram_SortNamesByKOs \
  --artifact /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_sort_957_current/allocator_ceiling_with_resolver_evidence.json \
  --artifact /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_sort_957_current/addi_copy_product_resolver_evidence.json \
  --json
```

Expected: no addi/copy-product continuation is recommended; terminal summary names `addi-copy-product-operands-not-source-visible`.

```bash
melee-agent debug search retained-frontiers \
  --function mnDiagram_DrawCellNumber \
  --artifact /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_956_current/allocator_ceiling_aggregate_plus_sticky.json \
  --json
```

Expected: status `all-known-frontiers-exhausted`, terminal summary names `target-only-c2-sticky-pool-source-attribution-terminal`, `evaluated_probe_count=42`, `exact_count=0`.

Optional broader smoke:

```bash
melee-agent debug search retained-frontiers \
  --function mnDiagram_SortNamesByKOs \
  --function mnDiagram_DrawCellNumber \
  --artifact-glob '/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_sort_*/*.json' \
  --artifact-glob '/Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram_draw_*/*.json' \
  --json
```

Review that any `next_frontier` is not one of the two closed lanes.

## Dirty-File Handling

- Do not run `git checkout`, `git reset`, or any destructive cleanup.
- Before implementation, re-run `git status --short` and inspect any dirty file that will be touched.
- Prefer the `debug search` implementation path to avoid the already dirty `tools/melee-agent/src/cli/debug/__init__.py`.
- If another agent changes `tools/melee-agent/src/search/cli/__init__.py` before implementation, inspect its diff first and append the command without reverting anything.
- Keep tests in a new file where possible to reduce merge risk.

## Non-Goals

- Do not add new source-transform families.
- Do not compile or mutate C source.
- Do not reinterpret allocator-ceiling proof logic already covered by `classify_allocator_ceiling`.
- Do not hard-code `mndiagram_sort_957_current` or `mndiagram_draw_956_current`; use generic retained-frontier extraction, with the mndiagram artifacts only as regression fixtures/smoke inputs.
