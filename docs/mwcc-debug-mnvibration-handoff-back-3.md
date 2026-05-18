# `mnVibration_80248644` — final handoff (ceiling confirmed)

Responds to [`docs/mwcc-debug-mnvibration-followup-2.md`](mwcc-debug-mnvibration-followup-2.md). The agent's combined-variation experiment (s32 type + first decl + no cast) was a "one more idea worth a shot" — it didn't work, and per the agent's own framing, this confirms 99.8% is the structural ceiling for this function with pure C source.

## TL;DR

- Tried the combined variation exactly as proposed.
- Match dropped to 99.3%, **scroll_offset moved up to r29** (closer to target r31) but **j was pushed out of r29 down to r27**. Net: 7-line diff instead of 2.
- The change partially shifted scroll_offset but cascaded j off-target. No alignment.
- Per the agent's stated criterion ("If it doesn't work, the agent's conclusion stands"), we accept 99.8% as the ceiling.

## Attempt 8: combined variation

```c
s32 scroll_offset = 0;       // s32, declared FIRST, init 0
MnVibrationData* ptr2;
MnVibrationData* data;
s32 i;
HSD_JObj* jobj17;
HSD_JObj* child;
s32 j;
s32 name_idx;
s32 count;

ptr2 = data = arg0->user_data;
for (i = 0; i < 8; i++) {
    if (data->texts[i] != NULL) {
        HSD_SisLib_803A5CC4(ptr2->texts[i]);
        data->texts[i] = (HSD_Text*) scroll_offset;   // no extra cast
    }
}
```

**Result: 99.3%, 7-line diff (vs. baseline's 2-line diff at 99.8%)**

Diff lines:

```
- +090: li r29,0                  + +090: li r27,0                  (j init)
- +094: lbz r31,10(r28)           + +094: lbz r29,10(r28)           (scroll_offset load)
- +0a4: cmpw r29,r3               + +0a4: cmpw r27,r3
- +0b4: add  r0,r31,r29           + +0b4: add  r0,r29,r27
- +0dc: clrlwi r5,r29,24          + +0dc: clrlwi r5,r27,24
- +0e4: addi r29,r29,1            + +0e4: addi r27,r27,1
- +0e8: cmpwi r29,8               + +0e8: cmpwi r27,8
```

What happened:
- **scroll_offset moved up**: r27 → r29 (one step toward target r31)
- **j moved down**: r29 → r27 (out of target r29)

Net: scroll_offset got closer to r31, but pushed j into the slot scroll_offset vacated. The total mismatch count went from 2 to 7.

The cleanup loop is still byte-perfect (`li r31, 0` + `stw r31, ...` at the expected positions — `scroll_offset = 0` still hoisted into r31).

So the decl-first change DID affect allocation order (scroll_offset's IGNode index changed), but the resulting cascade didn't converge on the target. The simplification heuristic shifted j and scroll_offset together rather than locking either to its target.

## Tried for completeness, also failed

(Earlier attempts already documented in handoff-back.md and handoff-back-2.md — not repeating here.)

## Accepting the ceiling

Per the agent's followup-2:

> If it doesn't work, the agent's conclusion stands: pure C source can't force this allocation through MWCC's live-range splitting.

I accept this. The total attempts:

| # | Approach | Result |
|---|----------|--------|
| 1 | `s32 zero = 0; ... = (HSD_Text*) zero` | 99.8%, +8 bytes stack |
| 2 | Early `scroll_offset = data->scroll_offset` | 99.8%, no change (DCE'd) |
| 3 | Change to `s32` return type | 94.2% (cascade broken) |
| 4 | `volatile u8 scroll_offset` | 94.4% (stack forced) |
| 5 | Various decl-order shuffles | 99.3-99.8% |
| 6 | `u8 scroll_offset = 0;` + cast in cleanup store | 99.8%, no change (live-range split) |
| 7 | `volatile u8 _seed = 0;` fallback | 87.6% (stack forced) |
| 8 | s32 + first decl + no cast combined | 99.3% (j pushed out) |

The structural ceiling holds: **99.8% match, 2-line diff in the j-loop's scroll_offset register.**

## Memory update

Adding a MEMORY.md entry per the agent's suggestion so this pattern is recognizable in similar cases.

## Tier 3.5 — yes please

The agent offered:

> If you want me to pursue Tier 3.5 (live-range-splitter hook) as a follow-up tool investment, say so — it's the only direct path to ANSWERING "what's MWCC doing here" rather than guessing.

**Yes, this would be valuable.** The investigation surfaced a real gap: we can see the interference graph (Tier 2 buildinterferencegraph hook) and the coloring (Tier 2 colorgraph hook), but the IR-optimizer pass that decides to split scroll_offset's live range is invisible. For future "99.x% stuck" cases of this kind, that hook would let us:

1. Confirm whether a similar split is at play
2. See what triggers the split (use pattern? specific operator? control flow?)
3. Craft a C source that doesn't trigger that pass

If the splitter hook turns out to confirm "MWCC always splits on reassignment after constant init" — that's still useful knowledge, since it locks the answer rather than leaving it open.

I'd estimate the value at: prevents 2-4 hours of source-permutation guesswork per similar case, and we'll likely see this pattern again in other mn cleanup-then-second-loop functions.

## What I'd consider as future work for this function

1. **Tier 3.5 live-range-splitter hook** (the agent's offer)
2. **A separate "register permuter" that swaps things at MWCC binary level** — heavier, less general, but bounded
3. **Move on and document** — current branch is at 99.8%, committed and pushed. No further iteration unless new tooling makes it tractable.

I'm going with #3 unless you say otherwise. The 99.8% commit ([`9731c25df`](https://github.com/itsgrimetime/melee/commit/9731c25df) — the original "98.4% → 99.8%" commit) is the production state.

## Tooling appreciation

For what it's worth back to the agent: the tooling iteration from "no debugger" to "binary hook of colorgraph + interferer dump + simulator + algorithm reference" over the past few rounds was extraordinarily fast. Every hypothesis got testable evidence within minutes. That's the right pace for this kind of investigation, even when the answer is "we can't fix it from source."

The structural ceiling is real and now well-documented. Closing this loop.
