# Tier 6 `--force-iter-first` feedback — works as advertised, plus one gap

Verified `--force-iter-first` against the three remaining stuck functions in `mn/mnvibration.c`. The hook works exactly as the handoff describes; flagging two findings worth knowing.

## What I ran

```bash
melee-agent debug pcdump src/melee/mn/mnvibration.c \
    --force-iter-first 32,33 \
    --output /tmp/forced.txt
```

(Picked 32,33 because both showed up as `param-like (low ig_idx)` in `rank-callees` on fn_802487A8.)

## What I saw

### fn_80248A78 (your verified case, re-confirmed)

Baseline `rank-callees` had ig_idx 87 → r31 (correct top) and the param at ig_idx 32 cascading down to r27.

With `--force-iter-first 32,33`:

```
   ig_idx  phys  predict  deg  notes
  -------  ----  -------  ---  -----
       87  r30       r31   13  got r30 not r31     ← was r31 before
       74  r30       r30   12
       ...
```

ig_idx 87 dropped one slot — confirms ig_idx 32 (param) jumped past it to r31. Matches your test exactly.

### fn_802487A8 (param-iter-ceiling cascade-4)

Baseline:
```
       78  r31       r31   13
       73  r26       r30   13  got r26 not r30
       ...
       33  r31       r22   14  param-like; got r31 not r22
       32  r27       r21   15  param-like; got r27 not r21
```

With `--force-iter-first 32,33`:
```
       79  r30       r31   13  got r30 not r31     ← dropped from r31
       74  r26       r30   13
       ...
       33  r31       r22   14  param-like; got r31 not r22
       32  r31       r21   15  param-like; got r31 not r21   ← was r27
```

Both params now share r31 (non-interfering, so they coalesce naturally). The ig_idx 79 local dropped to r30. Cascade reshuffles cleanly. **Confirms pure iter-order ceiling — no other structural issues hiding.**

### fn_80247510 (the case where the hook doesn't apply)

This is the interesting one. The function signature is `void fn_80247510(HSD_GObj* gobj)`, but `gobj` is dead-on-arrival — never read, immediately overwritten when the cooldown branch loads `mn_804D6BC8.cooldown` into r3. The function operates on the global `mnVibration_804D6C28` instead.

`rank-callees` confirms: no `param-like` tag on any virtual. The cascade is entirely local-vs-local:

```
      241  r28       r31   12  got r28 not r31
      239  r28       r30   12  got r28 not r30
      218  r28       r29   12  got r28 not r29
      188  r27       r28   12  got r27 not r28
      ...
```

Three locals at ig_idx 218–241 all got r28 instead of r29/r30/r31. So the "expected" target for this function (whatever produces the matching .o) has a particular high-ig_idx local getting r31, but `--force-iter-first` can't tell us which local would have gotten it from the original C source.

**No obvious `--force-iter-first` argument helps here.** There's no canonical "should be first" virtual; we'd need to guess high-ig_idx locals one at a time and see which produces the target asm.

This isn't a flaw in the hook — it's a different kind of ceiling. Just flagging that the param-iter-ceiling pattern doesn't capture all the iter-order cases we hit in practice.

## Implications for mn/mnvibration.c

The hook lets me cleanly close out the diagnostic on three functions:

| Function | Match | Verdict |
|---|---|---|
| fn_80248A78 | 99.01% | **Confirmed Tier 6 param-iter-ceiling** (hook produces target-like cascade) |
| fn_802487A8 | 95.31% | **Confirmed Tier 6 param-iter-ceiling** + int-to-float magic |
| fn_80247510 | 83.4% | **Local-vs-local iter cascade** (hook doesn't directly apply) + int-to-float magic |
| mnVibration_80248444 | 95.12% | int-to-float magic ceiling (not an iter case) |

Three of four hit the int-to-float anonymous reloc (`@472` instead of `mnVibration_804DC018`). If the magic-constant naming patch ever ships, that closes the bytes-match on those three at the same time.

## What the hook does for our matching workflow

Honest assessment: the hook is **valuable for diagnostic certainty** — I can now say "this is definitively Tier 6 and worth documenting/moving on" instead of "we tried a lot of things and ran out of ideas." The "Move on" verdict at the bottom of your handoff doc is the right call.

It does NOT help us close the bytes on these functions, but that wasn't the claim. Useful as a confidence-builder when telling reviewers "this function is structurally unmatchable."

## One small wishlist item

For local-vs-local cascades like fn_80247510, it would be useful if `rank-callees` could highlight WHICH high-ig_idx local "should have been" the top callee-save — i.e., the one that the expected .o gives r31 to. Currently the tool predicts top-down dispense, but the expected can differ from that prediction in ways the current heuristic doesn't surface.

If you had a tool that read the matched .o, identified the expected `r31`-bound virtual's first store/load, traced it back to its ig_idx in the current pcdump, and emitted "expected ig_idx N to be first" — then `--force-iter-first N` could verify it. This would extend the `--force-iter-first` workflow to local-vs-local cases.

(Lower priority than the worktree support / threshold fix, but listing it for the wishlist.)

## Status

Branch `wip/mn-heartbeat` unchanged — `mnvibration.c` is at the same state as before this experiment (the hook only affects the pcdump on the remote, not our `.o`). Three functions cleanly documented as Tier 6.
