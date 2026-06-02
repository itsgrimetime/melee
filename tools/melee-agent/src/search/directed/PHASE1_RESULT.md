# Phase-1 Live Gate Result — grIceMt_801F9ACC (HONEST RE-RUN)

> This OVERWRITES the earlier "PASSED — attributable_progress" result, which
> was **hollow** and is hereby **rescinded**. The earlier pass came from an
> iter-ordering metric derived from the baseline's own coloring (so
> `displacement=1.0` only meant "the mutation changed nothing") plus a
> hardcoded `control_displacement=0.0` and a `var_name=None` blind decl-pair
> fallback that produced falsely-"attributed" no-op candidates. Confirmed by an
> independent Codex (gpt-5.5 xhigh) review (spec round 4). The gate signal is
> now **phys-match** (`fix(directed)` commit `fe70f240c`).

## Verdict

**NOT PASSED** — `unattributed_or_regressing`

```json
{
  "gate": {
    "passed": false,
    "reason": "unattributed_or_regressing",
    "evidence": { "n_treatment": 4, "n_non_actionable": 4 }
  }
}
```

This is the **correct, valuable** Phase-1 outcome, not a mechanism failure. The
mechanism is non-VOID (it compiled + scored 4 distinct candidates against a real
control), it is honestly diagnosing the divergence (`case=C2`, i.e.
`C2_STICKY_POOL`), and it correctly refuses to claim progress where there is
none. It routes to Phase 2 (LLM Editor). See "Interpretation" below for why the
verdict is `unattributed_or_regressing` rather than `no_smooth_gradient`.

## Real control baseline (the wall, by construction)

The UNCHANGED source was compiled and scored through the SAME `score_directed`
path; its phys-match fraction is the control the gate must be beaten against
(no longer a hardcoded `0.0`):

| | value |
|---|---|
| control `phys_match_fraction` | **0.0** (0 of 2 target roles at desired phys) |
| ig33 (param y float-shadow) | desired `r27`, **assigned `r29`** → blocked |
| ig40 (local `did=0`)        | desired `r29`, **assigned `r27`** → blocked |

`GRICEMT_9ACC_FORCE_PHYS = {33: 27, 40: 29}`. The baseline IS the wall, so the
control scores `0/2` **by construction** — it is not trivially satisfiable, and
a candidate can only beat it by actually moving a role to its desired phys.

## Per-candidate phys-match evidence (the honest signal)

All 4 candidates came from the blind `var_name=None` decl-pair fallback (the
`C2_STICKY_POOL` divergence resolves no specific variable), so each is tagged
`non_actionable=True` and the gate treats it as **unattributed**.

| cand | case | phys_match | mismatch (order_distance) | sat/blk/abs | beats control? | actionably attributed? | (diag) iter_od |
|------|------|-----------:|--------------------------:|:-----------:|:--------------:|:----------------------:|---------------:|
| 0 | C2 | **0.0** | 2 | 0/2/0 | no | **no** (non_actionable) | 0 |
| 1 | C2 | **0.0** | 2 | 0/2/0 | no | **no** (non_actionable) | 0 |
| 2 | C2 | **0.0** | 2 | 0/2/0 | no | **no** (non_actionable) | 0 |
| 3 | C2 | **0.0** | 2 | 0/2/0 | no | **no** (non_actionable) | 0 |

- Every candidate scores `phys_match = 0.0` — identical to the control. The
  blind reorder-of-decls levers move NEITHER target role to its desired phys
  (both roles stay `blocked`). `applied_mutator = reorder_local_decls` for all.
- The candidates ARE genuinely distinct compiles (chained parents
  root→s1→s2→s3, distinct candidate_ids/source_hashes); the source changed, it
  just didn't change the register coloring of the two swapped roles.
- **Diagnostic only:** the old iter-ordering distance is `iter_od = 0` for these
  (they reproduce the baseline iter-order) — which under the OLD metric was
  scored `displacement = 1.0` and produced the hollow "pass." The phys-match
  metric correctly reports `0.0`. This is the direct, reproduced proof that the
  old signal was hollow and the new one is sound.

## Divergence case

`C2` (`C2_STICKY_POOL`) — a 2-role register select-order / interference-graph
ordering swap (`ev`/`did`-class wall). The first-divergence analysis yields a
valid diagnosis but **no specific var_name** for this case, so the
source-anchor resolver produces no actionable mutator; only the (now
explicitly non-actionable) blind decl-pair fallback fires.

## Interpretation — `unattributed_or_regressing` vs `no_smooth_gradient`

Both are honest non-passes that route to Phase 2; the distinction is precise:

- `no_smooth_gradient` requires **≥1 actionable (attributed) + covered**
  candidate that simply failed to beat the control. It says: "the mechanism
  produced real, attributed levers, but none moved a role to its desired phys."
- `unattributed_or_regressing` (this run) means there were **zero** actionable
  candidates at all — every candidate was the blind `non_actionable` fallback.
  The current 9ACC diagnosis path does not resolve a var_name for
  `C2_STICKY_POOL`, so it cannot emit an anchored (actionable) mutator.

So the even-more-honest finding is: the Phase-1 deterministic typed-mutator
spine has **no actionable lever** for the 9ACC `C2_STICKY_POOL` swap, and the
blind fallback achieves no phys-match progress. This is exactly the class the
Phase-2 LLM Editor is for. The mechanism's refusal to pass here is the gate
doing its job.

## Is the mechanism now sound? (frank assessment)

**Yes — the hollow signal is gone.**

1. **Gate signal = phys-match, not baseline-derived iter-ordering.** A no-op
   that reproduces the baseline coloring now scores `0.0` (proven above: the
   same candidates that previously "passed" now score `0.0`).
2. **Real control baseline.** The control is the actual unchanged-source
   phys-match (`0.0`), scored through the identical path — not a hardcoded
   `0.0`. A candidate can only pass by strictly beating it.
3. **Attribution integrity.** The blind `var_name=None` fallback is tagged
   `non_actionable`; the gate excludes it from "attributed." A no-op can never
   satisfy the `applied_mutator` requirement.
4. **Escalation is explicit.** Directed-from-iteration-1 is a documented
   `directed_from_start=True` config flag, not an `_AlwaysEscalate` subclass.

The full search unit-test suite is green (135 passed), including new tests that
pin: phys-match as the gate signal (0/2 wall → 1/2 → 2/2 win), the real-control
comparison, `non_actionable` candidates can never pass, the `directed_from_start`
flag, and the 3-tuple propose → `producer_meta` propagation.

## Run command

```bash
PYTHONPATH=/Users/mike/code/melee/tools/melee-agent \
melee-agent debug search directed \
  --function grIceMt_801F9ACC \
  --unit melee/gr/gricemt \
  --no-dry --max-iters 4
```

(`PYTHONPATH` pins the main-checkout `tools/melee-agent` ahead of a stale
sibling-worktree editable `.pth` that otherwise shadows `src` on this machine.)
