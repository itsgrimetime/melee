# Node-set-split coupled multi-ig realizer — design (#702)

## Problem

`debug solve node-set-split` realizes **one** missing virtual at a time. For a
**coupled rotation** — N interference-graph nodes that must move to N target
physical registers *simultaneously* — every single-ig candidate lands
wrong-register, because the rotation is interdependent.

Concrete instance (`mnDiagram_8023FC28`, class 0):

- `ig34` observed `r24`, wants `r27`
- `ig44` observed `r27`, wants `r25`

Moving `ig34` alone cannot reach `r27` while `ig44` still occupies it; the two
moves are a cycle. The realizer currently emits one candidate per ig
(`node-split-decl-order-…-ig34` etc.), all of which score
`objective_status=wrong-register` (issue #702 reproduction).

## Current shape (single-ig)

- `request_from_node_set_delta(delta, target_ig=None, source_text=None)` →
  **one** `NodeSetSplitRequest` (first bindable missing virtual).
- `generate_node_set_split_patches(source, fn, request)` → candidates each
  moving **one** ig (alias / lifetime / decl-order / per-loop-rename /
  reassociation).
- `evaluate_node_set_split_signature(baseline, candidate, request)` → checks
  the **one** `request.target_ig` reached `request.target_reg`, no new spills.

## Design (coupled)

Three additive helpers in `src/mwcc_debug/node_set_split.py`. The single-ig API
is unchanged.

1. **`requests_from_node_set_delta(delta, source_text=None, max_requests=4)
   -> list[NodeSetSplitRequest]`**
   Return *every* bindable missing virtual (in payload order), each as a
   `NodeSetSplitRequest`. Reuses `_request_from_missing_virtual` (so
   `source_text` IS threaded through — entries whose var isn't declared in the
   function are dropped). Keeps only entries with `var_name is not None AND
   blocked_reason is None`. **Dedups by `target_ig`** (keep first; solve-coloring
   can list a desired ig twice). Caps at `max_requests` (default 4, not 8: the
   composition space is `O(max_per_ig^N)`, so a low N keeps the unlimited
   `--max-candidates 0` path tractable). This is the coupled move-set.

2. **`generate_coupled_node_set_split_patches(source, function, requests, *,
   max_read_sites=4, max_per_ig=6, max_candidates=24)
   -> list[CandidatePatch]`**
   Compose the existing per-ig single edits across the set, so one candidate
   carries edits for *all* igs at once.
   - Sequential frontier composition: start `frontier = [base_source]`; for each
     request in turn, expand each frontier source by running
     `generate_node_set_split_patches(frontier_source, function, request)`,
     taking at most `max_per_ig` of its candidates, and keeping each resulting
     `patched_source` that differs from its parent. **The frontier is truncated
     to `max_candidates` after EACH request's expansion** (incremental cap), so
     it never exceeds `max_candidates` between rounds and the transient per
     round is `<= max_candidates * max_per_ig` (bounded regardless of N).
   - A coupled candidate is emitted only if it differs from `base_source` and an
     edit was applied for **every** request (a request that produces no edit on
     a given frontier source prunes that branch; if a request prunes all
     branches, return `[]`).
   - `candidate_id` is `node-split-coupled-ig34+ig44-c{idx}` (enumerated, bounded
     length); `summary` lists each per-ig move; `hunk` is the base->combined
     diff; `touched_ranges=((0, len(source)),)` (whole-file, matching
     `_append_unique_patch`). Dedup by final source; ordering is deterministic
     (payload request order + stable generator order).
   - **Safety:** each per-ig edit is individually semantics-preserving (the five
     existing single-ig generators are the shipped, tested ones — reassociation
     is restricted to GPR-class bare-identifier/integer-literal operands where
     `a+b == b+a` holds). Composition runs the *real* generator on each
     intermediate, so every later edit is re-parsed and re-validated against the
     already-edited text (no blind string splicing); a layered edit that no
     longer applies simply prunes its branch.
   - **Same-var coupled sets (review C1):** distinct missing virtuals do NOT
     always bind distinct C vars. When two requests share a `var_name`, a
     whole-var edit from the earlier request (e.g. per-loop-rename) can rename
     the var away, so the later request's generator finds nothing and prunes —
     yielding fewer or zero coupled candidates, but **never a wrong edit**
     (safety is preserved by construction). Local splits (alias/lifetime, which
     leave the name in place at other sites) still compose for same-var sets.
     The function records when the coupled set shares a var so the CLI can
     surface `shared_source_var` in the summary. The #702 reproduction
     (`mnDiagram_8023FC28`) is a *distinct-var* rotation — a loop counter plus a
     hoisted `max_idx` local — so the primary distinct-var path covers it.

3. **`evaluate_coupled_node_set_split_signature(baseline, candidate, requests)
   -> dict`**
   `target_reg_hit=True` iff **every** request's `target_ig` is assigned its
   `target_reg`. `status`:
   - `missing-target` if any target ig/reg is unresolved,
   - `spill-regression` if `candidate.spill_set - baseline.spill_set` is
     non-empty,
   - `realized` iff all hit and no new spills,
   - else `wrong-register`.
   Returns a `per_ig` breakdown plus the aggregate. `_score_row` /
   `_objective_status` read only `objective["status"]`, so the per-candidate
   rows consume the coupled objective unchanged; only the `status` value drives
   the `realized` filter in `summarize_node_set_split_scores`.

   `summarize_node_set_split_scores` itself takes a single `request` and emits
   `asdict(request)` / prints one `target_ig`/`target_reg`. For coupled mode we
   (a) pass a **synthesized aggregate request** for the `request` field
   (`target_ig` = first, `target_reg`/`var_name` = `"+"`-joined across the set)
   and (b) add an **optional `coupled_requests=None` kwarg** to
   `summarize_node_set_split_scores` that, when provided, attaches
   `coupled_requests: [asdict(r), ...]` and `shared_source_var` to the summary.
   The new kwarg defaults to `None`, so the single-ig summary output is
   byte-for-byte unchanged and existing tests stay green.

4. **CLI `--coupled`** on `debug solve node-set-split`:
   - Requires `--node-set-delta` (reject with exit 2 in explicit `--ig/--target-reg`
     mode — a coupled set comes from the delta's missing-virtual list).
   - Parse the full set via `requests_from_node_set_delta(delta,
     source_text=...)`, require **>=2** bindable requests (else a blocked summary
     "coupled mode needs >=2 bindable missing virtuals", exit 3).
   - Minimal-blast-radius threading (review I3): the existing scoring loop calls
     `evaluate_node_set_split_signature(baseline_sig, candidate_sig, request)`
     with a single request at one site. Replace that one call with a small
     `evaluate(candidate_sig) -> objective` closure chosen once up front
     (coupled vs single). Build `patches` from the coupled generator, and pass
     the synthesized aggregate request + `coupled_requests=requests` to every
     `summarize_node_set_split_scores` call on the coupled path. All other
     compile / `--apply-best` / budget plumbing is unchanged.
   - Without `--coupled`, behavior is byte-for-byte unchanged (single request,
     single evaluator, no new kwargs passed).

## Stop condition (issue #702)

> node-set-split yields ≥1 candidate with `target_reg_hit=true` + checkdiff
> delta>0 on a structurally-different-virtual residual.

The realizer now **can** emit simultaneous multi-ig candidates — the capability
that was missing. Whether a *specific* function then yields a byte win is
downstream field validation that runs with the patched debug compiler
(`mwcceppc_debug.exe`) on the real TU (e.g. `mnDiagram_8023FC28`); that toolchain
is not exercised by unit tests. Unit tests prove (a) the coupled candidate
generation, and (b) the all-hit objective.

## Non-goals

- No allocator/coloring solver — we enumerate bounded compositions and let the
  existing compile+score loop verify which composition realizes the rotation.
- No new per-ig edit kinds (reuse the five existing generators).
- No change to single-ig generation/evaluation/CLI behavior.

## Tests (unit, no compiler)

- `requests_from_node_set_delta`: multi-virtual delta → ordered bindable
  requests; unbindable/field-expression entries skipped; solve-coloring JSON
  wrapper normalized; `max_requests` cap.
- `generate_coupled_…`: source with two distinct movable counters → ≥1 combined
  patch whose `patched_source` differs from base and contains *both* igs' edits;
  `max_candidates` respected; `[]` when one request has no realizable edit.
- `evaluate_coupled_…`: `realized` only when all hit; `wrong-register` when one
  misses; `spill-regression`; `missing-target`.
- CLI: `--coupled` with <2 bindable requests → blocked summary + exit 3 (no
  compiler); `--coupled` rejects explicit (non-delta) mode.

## Design review incorporated (2026-06-14, independent Claude reviewer)

Verdict: SHIP-WITH-CHANGES. All findings folded in above:

- **C1 (same-var self-prune):** the coupled set may share a C var; composition
  now prunes safely (never a wrong edit), local alias/lifetime splits still
  compose, and the summary surfaces `shared_source_var`. Verified the #702
  reproduction (8023FC28) is a distinct-var rotation (loop counter + hoisted
  `max_idx`), so the primary path covers it.
- **C3 (reassoc commutativity):** scoped the safety claim to the generator's
  existing GPR-class bare-ident/int-literal operand restriction.
- **I1 (combinatorial bound):** cap applied incrementally per request + per-ig
  cap; transient bounded to `max_candidates * max_per_ig`; `max_requests`
  lowered to 4.
- **I2 (summary `request` field):** synthesized aggregate request + optional,
  back-compatible `coupled_requests` kwarg.
- **I3 (CLI threading):** single evaluator-closure swap + aggregate request,
  not a blanket plumbing change.
- **I4 (dedup/filter/source_text):** dedup by `target_ig`, keep only
  `var_name is not None and blocked_reason is None`, thread `source_text`.
- **M1/M2/M3/M5:** tests for 1-request (== single-ig) and 0-request (== []);
  documented order bias + `--max-candidates 0` escape; whole-file
  `touched_ranges`; re-running the generator preserves earlier edits.
