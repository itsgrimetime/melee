# N7 pair-only fixture — provenance (plan Task 15)

## Path taken: FALLBACK (verified synthetic), not PRIMARY

The plan's PRIMARY derivation was **attempted and rejected** in favor of the
FALLBACK, on honest grounds (not a shortcut):

- The real `fn_803ACD58` cached dumps in this checkout
  (`tools/melee-agent/tests/fixtures/order_distance/fn_803ACD58/{pre_win,win,
  chain_2,chain_3,negative_control}.pcdump.txt`, 7.7 MB each, real DLL output)
  load a clean class-0 (GPR) IG: **34 nodes, G1 = 100%, 0 incomplete**.
- BUT the decl-chain experiment captured there produced **no class-0
  working-pair delta**: `pre_win`, `win`, `chain_2`, and `negative_control`
  class-0 IGs are `ig_structurally_equal` to each other AND have byte-identical
  observed registers node-by-node (only `chain_3` differs, and `win == pre_win`).
  The recorded `fn_803ACD58` decl-chain win (97.9→99.7, per session memory) acted
  through inlined-callee / FPR-class effects, not a class-0 coloring pair. There
  is therefore **no recorded class-0 "working pair" to extract** from these
  artifacts. Fabricating an arbitrary phys_target on the real graph and searching
  for a pair-only one would be exactly the kind of hand-construction the rev2-7
  trap warns against, and it would not be "the recorded working pair from the
  decl-chain history" the plan's PRIMARY requires.

Per the plan's stated FALLBACK condition ("If extraction is not clean ... use the
FALLBACK"), the fixture is the **VERIFIED Task-5 `_pair_only_ig` construction**
(`tools/melee-agent/tests/search/solver/test_enumerate.py::_pair_only_ig`), which
was already brute-force-confirmed pair-only by T5's exhaustive test and is
re-confirmed below with the production enumerator.

### Trap avoided (rev2-7)

The plan's **literal JSON illustration** (nodes 40/41/50/51, each cross-connected
to both r3-holders) is **secretly SINGLE-solvable** and is NOT used. Verified at
authoring with the production enumerator in exhaustive mode:

```
PLAN-JSON baseline assignments: {40: 3, 41: 3, 50: 4, 51: 4}
PLAN-JSON full_hits (exhaustive single): 2
   SINGLE-SOLVABLE via: order target 50 order_move ('before', 40)
   SINGLE-SOLVABLE via: order target 51 order_move ('before', 40)
```

Because 50 and 51 share the SAME two blockers (40, 41), moving one column's order
frees both targets in a single perturbation. The frozen fixture instead uses two
**independent** columns (50↔60, 51↔61; the columns do not interfere), so freeing
one column leaves the other untouched — no single perturbation meets both targets.

## The frozen fixture (`n7_ig.json`)

- `class_id = 0` (GPR)
- `select_order = [60, 61, 50, 51]`
- blockers 60, 61 (observed r3); targets 50, 51 (observed r4)
- 60↔50 interfere; 61↔51 interfere; the two columns are independent; each node
  has machine reg 0 precolored (blocks r0, so r3 is the lowest free legal pick
  the blockers contend for — the T2 contention-boundary requirement)
- `phys_target = {50: 3, 51: 3}`
- baseline `predict_assignments` = `{60: 3, 61: 3, 50: 4, 51: 4}` (targets NOT
  met at baseline — a genuine residual)

**All registers/targets here are DERIVED from `predict_assignments`, never from
narrative text (T2-review fixture-construction binding).**

## Recorded working pair

`working_pair = [{kind: order, target_ig: 50}, {kind: order, target_ig: 51}]`
(move 50 before its blocker 60, move 51 before its blocker 61 — each frees its
own column; together they meet both targets).

## Brute-force no-single confirmation (production enumerator, exhaustive)

Command (run from `tools/melee-agent`):

```python
from src.search.solver.enumerate import EnumConfig, enumerate_single
big = EnumConfig(eval_cap=10_000_000, edge_floor=4_000_000, order_floor=4_000_000)
res = enumerate_single(ig, {50: 3, 51: 3}, config=big,
                       filter_fn=lambda p, c: FilterVerdict(admit=True),
                       probe_ctx_fn=lambda p: None)
```

Output:

```
T5 baseline assignments: {60: 3, 61: 3, 50: 4, 51: 4}
T5 EXHAUSTIVE single full_hits:    0     <- NO single perturbation reaches both targets
T5 EXHAUSTIVE single partial_hits: 18    <- non-empty frontier for pair composition
T5 candidates_generated: 44
T5 evals_per_kind: {'node-add': 8, 'edge': 24, 'order': 12}
```

Escalation (default `EnumConfig`) FIRES and FINDS the recorded working pair:

```
escalation ran: True   pair_hits: 74   truncated: False
   ... PAIR HIT: [('order', 50), ('order', 51)] targets_met: 2   <- the recorded working pair
```

`full_hits == 0` is the no-single proof; the working-pair signature
`{('order', 50), ('order', 51)}` is present among `pair_hits`; `truncated` is
False (the cap was respected). These are asserted by
`test_negative_controls.py::test_n7_no_single_reaches_target_brute_force` and
`::test_n7_escalation_fires_and_FINDS_the_working_pair`.

## N5 contention proof (T2-review binding for shuffled/unreachable targets)

N5's target must toggle a CONTENDED register under the dispense rule, not merely
differ in a precolor value. Verified at authoring:

```python
# node 42, machine reg 0 precolored (blocks r0); r3 is the lowest free legal pick.
assign(no r3 pin)              -> 42 = 3    # reaches the contended boundary r3
assign(neighbor pinned at r3)  -> 42 = 4    # collision: forced off r3 -> r4
```

So r3 is the contention boundary and a neighbor pinned there is a genuine
collision. The N5 test uses `phys_target={42: 3}` (NOT the plan's narrative
`{42: 27}`: under `_GPR_CALLEE_FRESH = [31, 30, ...]` fresh callee-saves are
allocated r31-downward, so r27 is only contended once r31..r28 are taken — not
the case for an isolated target).

## Broken-solver catch confirmation

Each control was confirmed to FAIL on a deliberately broken/permissive solver at
authoring:

- N4/N5: a solver returning exit 0 (no abstain on empty / collision target) is
  caught (`assert exit_code == 3` fails).
- N6: a gate returning `surrogate-confirmed`/`is_win=True` for an
  absent-perturbation or no-op realization is caught.
- N7 no-single: a single enumerator fabricating a full hit is caught
  (`assert full_hits == []` fails).
- N7 pair-FOUND: an escalation that "ran" but returns no pair is caught; AND a
  solver that finds 72 OTHER pairs but not the recorded `(order,50)+(order,51)`
  working pair is ALSO caught (codex blocker 1: "finds the pair", not "ran").
