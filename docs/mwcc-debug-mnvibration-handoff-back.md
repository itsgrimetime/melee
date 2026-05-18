# `mnVibration_80248644` — handoff back to debugger agent

This doc reports the results of testing the hypotheses in [`mwcc-debug-mnvibration-findings.md`](mwcc-debug-mnvibration-findings.md) against the actual compile.

## TL;DR

- Tried the suggested `s32 zero = 0; data->texts[i] = (HSD_Text*) zero;` change and four variations.
- **None shifted scroll_offset (r36) from r27 to r31.** Several made things worse.
- The agent's framing ("we need r36's workingMask to be `{r31}`") is correct, but the proposed fix doesn't change r36's interferer set in the way needed.
- The deeper question — how to extend r36's live range backward into the cleanup loop without emitting an extra instruction — is what needs the agent's next investigation.

## Current state

- Branch: `wip/mn-heartbeat` at `/Users/mike/.codex/worktrees/626f/melee-2`
- Best commit so far: `9731c25df` (99.8% match)
- Source uses dual-indexed-walker cleanup loop (`data->texts[i]` + `ptr2->texts[i]`), chained `ptr2 = data = arg0->user_data`, `void` return type
- All commits pushed to `origin/wip/mn-heartbeat`

The 2-line diff that's still open:

```
+094: lbz r31, 10(r28)   ← expected (scroll_offset in r31)
+094: lbz r27, 10(r28)   ← current (scroll_offset in r27)

+0b4: add r0, r31, r29   ← expected
+0b4: add r0, r27, r29   ← current
```

## Attempts and results

### Attempt 1: `s32 zero = 0; ... = (HSD_Text*) zero;` (the agent's primary suggestion)

```c
s32 zero = 0;             // added decl
...
data->texts[i] = (HSD_Text*) zero;   // use it instead of NULL literal
```

**Result:**
- Match stays at 99.8%, but **stack grew from 40 → 48 bytes** (`stwu r1, -48` vs `-40`; `stmw r26, 24(r1)` vs `16(r1)`; matching epilogue adjustments).
- Cleanup loop body still byte-perfect — MWCC hoisted `zero` into r31 exactly like the NULL literal would have been.
- **scroll_offset still → r27.** No change in the j-loop's coloring.
- Net: same register cascade, +8 bytes of stack overhead. Strictly worse than baseline.

The agent's reasoning was that `zero` would create a new callee-save virtual living across the cleanup loop, dispensed r31, then dying — leaving r31 in the pool for scroll_offset. **What actually happened:** MWCC did keep `zero` in r31, but its lifetime end was no later than the literal NULL's, so r36's interferer set was identical and the workingMask `{r27, r28, r30, r31}` was unchanged. r36 picks lowest set bit = r27.

### Attempt 2: Early load of `scroll_offset = data->scroll_offset;` before cleanup loop

```c
ptr2 = data = arg0->user_data;
scroll_offset = data->scroll_offset;   // hypothesized to extend r36's lifetime backward
for (i = 0; i < 8; i++) { ... }
```

**Result:** No ASM change. MWCC's dead-store elimination removed the early assignment (scroll_offset is overwritten before any read). Virtual r36's live range is the same as the baseline.

### Attempt 3: Change `void` return type → `s32 ... return count`

This matched master's signature (master has `s32 mnVibration_80248644(...)`, returns `count`). Hypothesis: maybe the original had the s32 return.

**Result:** Match dropped to 94.2%. The required return-value preservation cascaded the ENTIRE register map down by one:
- arg0 r26 → r31
- i r27 → r26
- data r28 → r27
- etc.

The function's callers (`fn_802487A8`, etc.) expect `void`, and the additional preserved-register requirement breaks the prologue/epilogue. **Not the right path.**

### Attempt 4: `volatile u8 scroll_offset`

Hypothesis: volatile forces the variable to be treated as having unknown side effects, possibly extending its live range.

**Result:** Match dropped to 94.4% with 6 stack-reference diffs. `volatile` forces stack storage of the variable, which breaks the entire shape.

### Attempt 5: Reorder declarations (scroll_offset before i / before everything)

Tried various positions. Only the current order (scroll_offset right before j) gives 99.8%. Moving it anywhere else (before i, at end, between other vars) regresses to 99.3% (j gets a different register, breaking the j-loop further).

## What the binary hook tells us about r36 (current source)

From the `COLORGRAPH DECISIONS` section for iter 16:

```
16    36      r27        11      14      0x02
      interferers: 0=r0 3=r3 4=r4 5=r5 6=r6 7=r7 8=r8 9=r9 10=r10 11=r11 12=r12 32=r26 35=r29 39=r-1
```

r36's interferer set (the callee-save ones that matter):
- 32 → r26 (arg0 — lives entire function)
- 35 → r29 (j — same loop, overlapping range)
- 39 → r-1 (per hook output; corresponds to data, which actually got r28 at iter 13)

The hook's `39=r-1` is confusing — by iter 16, virtual 39 had already been assigned r28 at iter 13. Likely a hook bug where late-assignment doesn't propagate to earlier iterations' interferer dumps. The agent should treat the final assignment list as authoritative when reading this output.

At r36's iter, the workingMask logic gives `{r27, r28, r30, r31}` minus `{r28}` (r39 interferer) minus `{r29}` (r35 interferer) minus `{r26}` (r32 interferer) = `{r27, r30, r31}`.

Lowest set bit → r27. Done.

## The unanswered question

To force r36 → r31, r36's interferer set must additionally exclude r27 and r30. That means r36 must interfere with:
- The holder of r27 (ig_idx 38 in our build, which is `i` from the cleanup loop)
- The holder of r30 (ig_idx 45 in our build, which is the ptr2 walker)

Both are cleanup-loop locals whose natural live range ends at the cleanup loop's exit. **r36 (scroll_offset) is born in the j-loop body, after those die.** The natural live-range graph gives them disjoint, non-interfering ranges.

**The agent's hypothesis was that some structural change would create the needed interferences.** What we've learned empirically:

1. Adding a new callee-save virtual (like `s32 zero` with a real use) doesn't add interferences for r36 — `zero`'s lifetime ends at the cleanup loop just like NULL's would.
2. Adding instructions before the cleanup loop that "use" scroll_offset gets dead-store-eliminated. **The C-level reference doesn't survive to MWCC's late passes.**
3. `volatile`, return-type changes, and decl-order shuffling don't create the needed interferences either.

### What we need to know

- **Can a C-source construct create an "implicit use" of scroll_offset before its natural first use, without emitting an extra instruction?** Some MWCC-specific idiom or expression form that extends a virtual's live range backward in the IR without surviving to the emitted ASM?

- **Or: is the right approach to extend r38 (i counter) or r45 (ptr2 walker) FORWARD into the j-loop**, so they hold their values long enough to interfere with r36? If so, what source construct does that?

- **Or: can the cleanup-loop variable allocation be steered to NOT use r27, r28, or r30 in the first place** — leaving fewer "stale" callee-save regs in the pool for r36 to grab? Then r36 might be forced to r31 by elimination. But we'd need r38, r45 to go elsewhere without breaking the byte-perfect cleanup-loop match.

- **Is there a known MWCC trick for "stealing" a higher register for a short-lived variable**, when the algorithm naturally would assign a lower one? This is the structural shape of the problem.

## Tooling state

- `melee-agent debug pcdump src/melee/mn/mnvibration.c --output build/mwcc_debug/mnvibration.txt --no-pull` — works, produces the COLORGRAPH DECISIONS section
- `melee-agent debug analyze` — gives per-virtual interferer summary (with the known limitation that some interferences may not show due to positional alignment)
- `melee-agent debug simulate` — works; for our function it predicts r36 → r31 (matches what we *want*), which is precisely the "model wrong vs. reality" gap the binary hook resolves

The branch `wip/mn-heartbeat` has the current source committed and pushed. The dump at `build/mwcc_debug/mnvibration.txt` is fresh as of the latest source state (baseline 99.8%, no experimental changes left in working tree).
