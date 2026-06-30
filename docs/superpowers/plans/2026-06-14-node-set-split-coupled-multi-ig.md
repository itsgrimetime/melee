# Plan — node-set-split coupled multi-ig realizer (#702)

Spec: `docs/superpowers/specs/2026-06-14-node-set-split-coupled-multi-ig-design.md`
(independent review incorporated, SHIP-WITH-CHANGES).

Worktree: `.claude/worktrees/wt-702-nodeset`, branch
`claude/issue-702-node-set-split`, off master `f63bca221`. Files touched are
disjoint from the sibling agent's active transform-corpus work
(`node_set_split.py`, `cli/debug/__init__.py`, `tests/test_node_set_split.py`).

TDD throughout: write the failing test, then the minimal implementation, then
green. Verify with `pytest tests/test_node_set_split.py -o addopts=""` (no
coverage plugin churn) after each task.

## Task 1 — `requests_from_node_set_delta` (library)
- Test: multi-virtual delta → ordered bindable requests; unbindable/field-expr
  entries dropped; solve-coloring JSON wrapper normalized; dedup by `target_ig`;
  `max_requests` cap; `source_text` filtering (undeclared var dropped).
- Impl: iterate `missing_virtuals`, reuse `_request_from_missing_virtual`, keep
  `var_name is not None and blocked_reason is None`, dedup by `target_ig`, cap.

## Task 2 — `evaluate_coupled_node_set_split_signature` (library)
- Test: `realized` only when ALL igs hit; `wrong-register` when one misses;
  `spill-regression` when new spills (precedence over hit); `missing-target`
  when a target unresolved; `per_ig` breakdown present; `_objective_status`
  reads `status` fine.
- Impl: loop requests, aggregate all-hit, status precedence
  missing-target → spill-regression → realized → wrong-register.

## Task 3 — `generate_coupled_node_set_split_patches` (library, the core)
- Test (distinct-var): a function with two distinct movable counters + a 2-req
  set → ≥1 coupled patch whose `patched_source` differs from base and contains
  BOTH igs' edits; `max_candidates` respected; deterministic ids.
- Test (prune): a 2-req set where the 2nd request has no realizable edit → `[]`.
- Test (degenerate): 1-request set ≈ single-ig candidates; empty set → `[]`.
- Test (same-var): two reqs sharing a var where a local alias still composes →
  ≥1 candidate; record `shared_source_var`.
- Impl: sequential frontier composition with incremental `max_candidates` cap +
  per-ig `max_per_ig` cap; emit only branches that edited every request; dedup
  by final source; whole-file `touched_ranges`.

## Task 4 — `summarize_node_set_split_scores` coupled kwarg (library)
- Test: existing single-ig tests still pass (no kwarg); with
  `coupled_requests=[...]` the summary gains `coupled_requests` +
  `shared_source_var`; single-ig output unchanged when kwarg omitted.
- Impl: add optional `coupled_requests=None`; attach fields only when provided.

## Task 5 — CLI `--coupled` (cli/debug)
- Test (no compiler): `--coupled` without `--node-set-delta` → exit 2;
  `--coupled` with a delta that has <2 bindable virtuals → blocked summary +
  exit 3. (Put CLI tests in `tests/test_node_set_split.py` or a new
  `tests/cli/test_solve_node_set_split_coupled.py` — NOT the sibling-dirty
  `tests/search/test_cli_smoke.py`.)
- Impl: add `--coupled` flag; build `requests` via `requests_from_node_set_delta`;
  require ≥2; choose a single `evaluate(candidate_sig)` closure (coupled vs
  single) used at the one evaluation site; build `patches` from the coupled
  generator; synthesize aggregate request + pass `coupled_requests` to summary.

## Task 6 — docs + verify + integrate
- Update any node-set-split usage doc/skill note to mention `--coupled`.
- Full `pytest tests/test_node_set_split.py` green + targeted CLI smoke
  (`debug solve node-set-split --help` shows `--coupled`; the <2-bindable path).
- Independent code review (subagent) of the diff; fix findings.
- Commit on branch; cherry-pick onto master once the main checkout is clean
  (preserving the sibling's work); resolve #702.

## Out of scope (documented in spec)
- No allocator solver; no new per-ig edit kinds; the real `target_reg_hit=true +
  checkdiff delta>0` win is downstream field validation with the patched debug
  compiler on a real TU (e.g. `mnDiagram_8023FC28`).
