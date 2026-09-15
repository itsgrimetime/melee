# Issue 936: Post Source-Owner Backtracking Plan

1. Extend `plan_window_order_source_probes` with an optional ranked
   indexed-byte per-target materialization limit. Keep the default at one.

2. Register `retained_gpr_case_c_post_source_owner_backtrack` in the transform
   family registry, force-class map, and select-order default family list.

3. In the transform-corpus orchestrator, add a post-source-owner family block
   that consumes the select-order context, calls the window-order planner with a
   larger per-target limit, skips the first ranked indexed-byte candidate per
   target, and emits remaining ranked indexed-byte probes as alternate
   retained candidates.

4. Add CLI summaries/classification for the new family so JSON output reports
   materialized-not-scored, scored exact, scored negative, and terminal
   `no-alternate-source-owner`/`post-source-owner-exhausted` states.

5. Add regression tests:
   - planner keeps the default one-candidate behavior
   - planner can materialize later ranked indexed-byte candidates when the new
     limit is raised
   - `plan-transforms` emits an IG34 post-source-owner alternate after the
     current owner rank
   - zero-alternate cases report an explicit terminal blocker

6. Verify with the focused pytest set and an archived
   `mnDiagram_SortNamesByKOs` CLI smoke using the issue #936 select-order
   payload.
