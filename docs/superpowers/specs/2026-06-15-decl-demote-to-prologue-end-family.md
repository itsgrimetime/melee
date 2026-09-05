# Spec+Plan: un-gate register-steering anchors so present-but-untouched unsupported decls don't suppress byte_match demotes (issue #699)

## Status

Closes the open half of #699 ("transform-corpus register-steering families engage
but don't BYTE_MATCH coloring residuals"). ~6 prior agents built families; all
produced 0 byte_match. This makes the EXISTING demote family emit a probe that
reproduces a known campaign byte_match. (Initial diagnosis — "missing cross-run
demote family" — was FALSIFIED by independent review; see Root cause.)

## Root cause (diagnosed, independently reviewed, validated)

The campaign cracked `mnDiagram2_GetAggregatedFighterRank` 99.49→100 (commit
`0b8476e7d`) by demoting `int res;` to after `int m;` (renumbers res's virtual
below i's; i then claims r26). The transform-corpus's EXISTING within-run demote
`_iter_decl_demote_anchors` (`transform_corpus.py:1190`) **already generates
exactly this `res`→after-`m` anchor** — applying it yields source byte-identical
to `0b8476e7d` (verified). Pointers count as supported
(`_register_steering_concrete_type_supported` admits single pointers), so
AggRank's prologue is ONE contiguous run `[base,curr,count,res,ptr,i,j,k,zero,n,m]`
and res is NOT its run's last element.

The real blocker is the function-level gate in
`_iter_concrete_register_steering_body_anchors` (`transform_corpus.py:1791`):

```python
if any(not _register_steering_concrete_type_supported(decl.type_name)
       for decl in top_decls):
    return   # bails the WHOLE function: rotate+demote+reuse-dead+split+widen all suppressed
```

For AggRank this fires on the aggregate-by-value `mnDiagram2_SortEntry temp;`,
so the entire concrete steering family emits 0 anchors. The 11 probes
`plan-transforms` actually emits come from a DIFFERENT ungated iterator
(`_iter_register_steering_body_anchors`, `:2084`, wired at `:6234`) that only
does adjacent-pair swaps — never the multi-position demote. So no byte_match.

The gate (added `8e0ea630f`, hardened `f04286d62` "Keep register steering probes
C89-safe") is OVERLY broad: it bails the whole function when an unsupported decl
is merely PRESENT, even though every candidate's exact-replaced span (the run
iterators break runs on unsupported decls; each anchor carries
`body_text.count(span_text) == 1`) physically leaves the unsupported decl in
place. `temp` sits outside the `res…m` span and is never touched.

**Validation target (reconstructed + confirmed this session):** overlay
`mndiagram2.c`+`mndiagram2.static.h` from `0b8476e7d~1` (= AggRank@99.49,
register-allocation, normalized_diff_lines=0). The `0b8476e7d` source →
`checkdiff match=true, 100.00%`.

## Design (minimal gate relaxation — NO new family)

In `_iter_concrete_register_steering_body_anchors` (`transform_corpus.py:1781`),
replace the function-level `any(unsupported) → return` bail with a **per-anchor
span-safety filter**: compute the spans of unsupported top-level decls; generate
the anchors as today (rotate/demote/reuse-dead/split/widen_byte); then yield only
anchors whose `span` does NOT overlap any unsupported top-level decl span. Keep
the existing `#`-directive guard (`:1782`) and duplicate-top-level-name guard
(`:1789`) unchanged.

This preserves the C89 guarantee (no candidate ever reorders across / mutates an
aggregate-by-value or other unsupported decl) while letting safe within-run
reorders/demotes through for functions that merely happen to contain an
unsupported decl elsewhere in the prologue. No new mutator key, anchor iterator,
or catalog entry — reuse the proven `_iter_decl_demote_anchors` /
`steer_demote_local_decl_to_first_use` transform.

## C89-safety / behavior guards

- The per-anchor span-overlap filter is the binding safety check: an anchor is
  emitted only if `[a0,a1)` is disjoint from every unsupported top-level decl
  `[s0,s1)`. Aggregates/arrays/initialized-or-otherwise-unsupported decls are
  never inside an emitted candidate's span ⇒ never moved/crossed.
- The existing per-anchor guards remain: exact-span (`count(span_text)==1`),
  uninitialized-only + supported-type runs (`_iter_uninitialized_decl_runs`),
  non-synthetic-name, within-prologue (run-based). Moving an uninitialized scalar
  /single-pointer among other uninitialized decls is declaration-order-only and
  behavior-preserving.
- Net behavior change is purely ADDITIVE: functions with zero unsupported
  top-level decls are unaffected (the filter removes nothing); functions that
  previously bailed now get the subset of anchors whose spans are clean.

## Out of scope

- Cracking the other #699/#705/#714 residuals (8023FC28, 80242C0C, Create,
  GetRankedFighter, 80245BA4, 8024227C) — proven unbindable-temp/coupled/multi-
  lever (0 byte_match across the #705/#714 triage).
- A genuinely cross-run move (jumping a supported decl OVER an unsupported one in
  one span) — not needed; AggRank's winning span is a clean supported run.

## Validation / acceptance (stop condition: byte_match a coloring residual)

1. Unit (`tests/search/directed/`): `_iter_concrete_register_steering_body_anchors`
   on a synthetic body with a clean supported run PLUS an unsupported aggregate
   decl OUTSIDE the run now yields the within-run demote/reorder anchors (was: 0);
   and still yields NOTHING that spans the aggregate. A control where the only
   reorderable span would have to cross the aggregate yields no unsafe anchor.
2. Regression: a function whose unsupported decl sits BETWEEN supported decls
   still never emits an anchor spanning it; functions with no unsupported decls
   are byte-identical in output to before.
3. **LIVE byte_match (the #699 stop condition):** with AggRank@99.49 overlaid,
   `plan-transforms -f mnDiagram2_GetAggregatedFighterRank -u melee/mn/mndiagram2
   --force-phys 0:51:26,0:39:26,0:41:25 --source-file src/melee/mn/mndiagram2.c
   --max-per-family 40 --write-probes DIR` now emits a demote probe that, compiled
   as mndiagram2.c, gives `checkdiff mnDiagram2_GetAggregatedFighterRank
   match=true` (100.00%). Record the winning probe.
4. Full `tools/melee-agent/tests/search/directed/` +
   `test_source_transform_catalog.py` green; compileall; git diff --check.

## Workspace contract

Implement in `/Users/mike/code/melee-2` (master tooling). The AggRank@99.49 state
is an UNCOMMITTED overlay (`git checkout 0b8476e7d~1 -- src/melee/mn/mndiagram2.c
src/melee/mn/mndiagram2.static.h`) — for the live byte_match validation ONLY; do
NOT commit it. Commit ONLY tooling (`transform_corpus.py`, tests, this spec).
NEVER touch `/Users/mike/code/melee`.
