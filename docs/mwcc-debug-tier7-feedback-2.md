# Tier 7 followup-2 — small bugs + UX polish

Two more rounds of using the toolkit since the last writeup. Three things worth flagging.

## 1. `--threshold 0.10` default is too strict for triage-perm

Default `--threshold 0.10` filtered out small but real wins this iteration. Lowering to `--threshold 0.05` surfaced two `WIN` candidates that:

- fn_80248A78: +0.07% (98.94% → 99.01%) — chained alias around `temp_x`
- fn_802487A8: +0.09% (95.22% → 95.31%) — chained alias around int-to-float

Both transferred cleanly to real source. Neither would have surfaced at 0.10%.

Suggest **lowering the default to 0.05** (or making it 0.07 — half of 0.10 still feels meaningful, lets people opt UP if they want only big wins). The risk is more triage-perm runs apply candidates that don't help much, but the cost is one extra `git checkout` per false positive — much cheaper than missing a real +0.1% chain.

Same applies to `enumerate-decl-orders --threshold` and the `ceiling` command's internal threshold (`No decl-order win found` may hide small gains that stack).

## 2. `enumerate-decl-orders --iterate` left the file in a broken state

Running `--iterate` with `--keep-best --threshold 0.04` after the regular run:

```
$ melee-agent debug enumerate-decl-orders fn_80248A78 --strategy all \
    --iterate --iterate-max 5 --keep-best --threshold 0.04
...
swap base_y <-> spacing: BUILD FAILED
swap spacing <-> temp_x: BUILD FAILED
...
No more wins; stopping iterate loop.
No wins clearing iterate-threshold 0.010% in any round.
```

After this, `git status` showed `M src/melee/mn/mnvibration.c` with a 137-insertion / 131-deletion diff — the iterate loop had reordered MANY decls before hitting build failures, but didn't revert when the iteration found nothing better than baseline. I had to `git checkout` manually.

Suggest: **on `--iterate` exit, if no win cleared the threshold, revert to the original state.** Same contract as the non-iterate path (which does revert by default). Or at least an explicit `Reverting...` log line so the user knows the file moved.

## 3. `stuck` and `ceiling` could auto-derive a target spec

Both commands say things like "Provide --target to compare against a specific mapping" but constructing a target spec is itself a multi-step process (force-phys then derive-target). Once we KNOW we're at the param-iter-ceiling, we KNOW which mapping is "correct" — it's the one with the parameter virtual at the top callee-save.

Suggest: **`debug stuck --auto-target`** (or `ceiling --auto-target`) that:

1. Reads the current pcdump
2. Identifies the parameter virtuals (low ig_idx, callee-save class)
3. Constructs a target spec where each parameter virtual swaps with the highest competing local at the same physical level
4. Runs force-phys to verify, then derive-target to materialize the spec

This is exactly the workflow we'd manually run when we suspect param-iter-ceiling. Automating it gets you from "stuck" to "verdict + reproducible target" in one command.

If the auto-target produces target ASM that doesn't match expected, the ceiling is something DEEPER (e.g. the int-to-float magic naming case for fn_802487A8). That's also useful signal — it rules out "just the ig_idx ordering" and points at "additional structural issue too."

## Open from the last writeup

Coalescenodes hook for parameter→high-ig-idx-local merge is still the killer Tier 6 feature for these. The new rank-callees output makes it easy to identify the right merge candidate (any local at higher ig_idx than the param, ideally at the top callee-save).

## Current state

| Function | Match | Status |
|---|---|---|
| fn_80248A78 | 99.01% | param-iter-ceiling + small chain alias on top |
| fn_802487A8 | 95.31% | param-iter-ceiling + small chain alias on top + magic |

Probably one or two more triage-perm rounds will close out the chain-alias-find-rate; after that, fn_80248A78 plateaus near 99.5% and fn_802487A8 near 96% without a Tier 6 escalation.
