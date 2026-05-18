# `mnVibration_80248644` — second handoff back (after followup proposal)

This responds to [`docs/mwcc-debug-mnvibration-followup.md`](mwcc-debug-mnvibration-followup.md), where the debugger agent proposed using `scroll_offset` itself (not a separate `zero` variable) as the NULL store source, with `scroll_offset` initialized at top, used in cleanup, and reassigned in j-loop.

## TL;DR

- Tried the primary proposal exactly as written → **scroll_offset still landed in r27**, identical 2-line diff.
- Tried the fallback (`volatile u8 _seed = 0; scroll_offset = _seed;`) → match crashed to **87.6%**.
- The binary hook confirms the agent's predicted failure mode: **MWCC split scroll_offset's live range**. r36's interferer list is byte-identical to the baseline.
- The cleanup-loop use of `scroll_offset` (value 0) is treated as a separate IGNode from the j-loop use (after `scroll_offset = data->scroll_offset;`).

## Attempt 6: primary proposal (commit [`6315864fb`](https://github.com/itsgrimetime/melee/commit/6315864fb))

```c
u8 scroll_offset = 0;          // declare + init at top
...
ptr2 = data = arg0->user_data;
for (i = 0; i < 8; i++) {
    if (data->texts[i] != NULL) {
        HSD_SisLib_803A5CC4(ptr2->texts[i]);
        data->texts[i] = (HSD_Text*) (s32) scroll_offset;
    }
}
...
for (j = 0; j < 8; j++) {
    scroll_offset = data->scroll_offset;   // reassign in j-loop
    ...
}
```

**Result:** 99.8% match, identical 2-line diff as baseline.

Cleanup loop is still byte-perfect: `li r31, 0` at +01c, `stw r31, 112(r30)` at +040 (scroll_offset's initial 0 value still flows into r31). But scroll_offset reassignment in j-loop creates a fresh IGNode that goes to r27.

### Binary hook output (iter 16, r36)

Identical to the baseline:

```
16    36      r27        11      14      0x02
      interferers: 0=r0 3=r3 4=r4 5=r5 6=r6 7=r7 8=r8 9=r9 10=r10 11=r11 12=r12 32=r26 35=r29 39=r-1
```

**No new interferences with cleanup-loop virtuals were added.** The IR is splitting scroll_offset's lifetime — exactly the predicted failure mode.

Confirmed: the `data->texts[i] = (HSD_Text*)(s32) scroll_offset;` statement reads `scroll_offset` (value 0), but MWCC's IR represents this as a use of a "scroll_offset_v1" virtual that's distinct from the "scroll_offset_v2" virtual created by the j-loop reassignment. They don't interfere because their live ranges are disjoint.

## Attempt 7: volatile-seed fallback (the followup's escape hatch)

```c
u8 scroll_offset;
volatile u8 _seed = 0;
...
scroll_offset = _seed;        // read from volatile, supposed to defeat constant-folding
```

**Result:** Match crashed to **87.6%**. The `volatile u8 _seed = 0;` forced a stack slot (volatile cannot live entirely in a register), changing the prologue and stack layout. Multiple symbol/relocation diffs cascaded.

This confirms `volatile` is too heavy-handed for nudging the IR — it changes too much else.

## What this means

The agent's hypothesis that introducing an interference between scroll_offset and cleanup-loop virtuals would force r36 → r31 is correct in principle, but **MWCC's IR doesn't let us create that interference through normal source means**:

1. Separate `zero` variable: zero is a distinct virtual, dies at end of cleanup, doesn't help scroll_offset.
2. Reused `scroll_offset` with initial 0 + later reassignment: MWCC splits the live range — the two uses become distinct virtuals.
3. Volatile to prevent splitting: too disruptive, breaks the prologue/stack.

Each approach was blocked by a different MWCC optimization pass:
1. Distinct C variables → distinct IGNodes (by definition).
2. Same C variable with reassignment → live-range splitting (MWCC's IR optimizer separates pre- and post-reassignment uses).
3. Volatile → forces stack allocation.

## Open question for the agent

**Is there a way to write C source that yields a SINGLE IGNode for a variable across two disjoint uses with intervening reassignment, in MWCC's IR?**

The agent's followup says:
> if MWCC's liveness analysis still considers the cleanup uses of `scroll_offset` (where its value is 0) as a SEPARATE live range from the j-loop uses (where it gets reassigned from `data->scroll_offset`). Live-range splitting would defeat this approach.

That's exactly what happened. The question is whether there's a source pattern that prevents the split. Candidates we haven't tested:

- **Phi-style flow**: have scroll_offset's value depend on something that prevents MWCC from seeing a clean break between cleanup and j-loop reads. E.g., put the cleanup loop inside a conditional that DOESN'T fire on the first call, so MWCC can't statically determine the value is always 0.
- **Pointer indirection**: take `&scroll_offset` somewhere so the alias prevents some optimization. But this likely forces stack allocation like volatile.
- **Return value reuse**: have scroll_offset be initialized from a function call that returns 0 (untraceable by MWCC's constant prop), so the live range is anchored at the function call's return.

The third option is interesting:

```c
u8 scroll_offset;
scroll_offset = (u8) some_function_returning_zero();  // MWCC can't prove this is 0
... cleanup loop uses scroll_offset (MWCC thinks it might be non-zero) ...
scroll_offset = data->scroll_offset;  // reassign
... j-loop uses scroll_offset ...
```

But adding a function call adds ASM. Won't match.

What about using an EXISTING function call's return value? `arg0->user_data` is a load — could we load `data->scroll_offset` once into a temp and route through it?

```c
u8 init_offset = data->scroll_offset;  // load once
u8 scroll_offset = init_offset & 0;     // mask to 0 — but MWCC will constant-fold this back to 0
```

Same problem.

## Possible structural alternative

Maybe the actual HAL source had `scroll_offset` initialized from `data->scroll_offset` BEFORE the cleanup loop, and then USED in the cleanup loop body (not just for the NULL store). That would naturally extend the live range without breaking the cleanup loop's match — IF the use in the cleanup loop maps to existing ASM instructions.

But our cleanup loop doesn't have any "spare" instructions that could be a hidden scroll_offset use.

## Where I'm stuck

I don't have a source idea that:
1. Keeps the cleanup loop's ASM byte-perfect
2. Doesn't add an extra instruction
3. Creates the needed interference between scroll_offset and r38/r45

The agent's reasoning is sound but the C-source vector seems exhausted. Maybe the right answer is Tier 3 work (inspect MWCC's IR optimizer to see what makes it split scroll_offset's live range, then craft a source that doesn't trigger that pass).

## Current state

- Branch: `wip/mn-heartbeat`
- HEAD: [`6315864fb`](https://github.com/itsgrimetime/melee/commit/6315864fb) (the failed experiment, marked `wip:`)
- Source restored to 99.8% baseline in working tree (not yet committed)
- Fresh pcdump at `build/mwcc_debug/mnvibration.txt` corresponds to the experimental source (commit 6315864fb), confirming the failure mode

For the agent: the experimental commit's binary hook output should be sufficient to confirm the live-range-split hypothesis without rerunning. The 99.8% baseline source is unchanged on disk.
