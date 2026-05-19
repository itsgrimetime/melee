# match-iter-first + name-magic feedback

Tested both new tools on the stuck mnvibration.c cluster. Both work as advertised; the user-facing observations follow.

## `match-iter-first` — direct hit on the wishlist

The tool answers exactly what the previous feedback asked for: given a function whose param is dead-on-arrival (or whose cascade is local-vs-local), tell me which virtual *should* be at r31/r30/r29/r28 by reading the expected `.s`.

Example on fn_80248A78 (the param-iter case I'd been pushing on):

```
Expected iter-first targets:
  r31 <- ig_idx 32   (virt r32, instr 0: mr r31, r3) [ambiguous]
  r30 <- ig_idx 48   (virt r48, instr 1: lwz r30, 0x2c(r3)) [ambiguous]
  r29 <- ig_idx 88   (virt r88, instr 143: mr r29, r3) [ambiguous]
  r28 <- ig_idx 37   (virt r37, instr 137: lwz r28, 0x2c(r31)) [ambiguous]
```

Cross-checking against `analyze` for current compile:

```
r32 (param)    -> phys r30 (should be r31)
r48 (data ptr) -> phys r31 (should be r30)
```

Diagnosis confirmed: pure swap of param vs data ptr. Same param-iter-ceiling pattern we've been chasing. `match-iter-first` gives me high-confidence "yes, this is exactly the cascade and exactly the swap" in one command instead of staring at analyze tables.

The `[ambiguous]` tag is honest about the matching — most signatures aren't unique, but the tool picks the closest by position and that worked on every case I tried. Useful future-proofing.

## `name-magic` — works perfectly, integration is the question

Tried it on the int-to-float magic constant in our .o:

```bash
melee-agent debug name-magic build/GALE01/src/melee/mn/mnvibration.o \
    --map "u32=mnVibration_804DC018"
# Renamed 1 symbol(s) in ...:
#   @477 -> mnVibration_804DC018
```

This actually works: the symbol in our .o is now named `mnVibration_804DC018` instead of `@477`.

**One thing the handoff doc doesn't mention**: the renamed symbol stays *local* (`l` in objdump), while the expected has it as *global* (`g`). Pinpointed via `powerpc-eabi-objdump -t`. Followed up with `objcopy --globalize-symbol mnVibration_804DC018` and got matching scope.

Could be worth adding `--globalize` (default-on?) to `name-magic` since the use case is always "match the expected global named symbol."

**Fuzzy match% doesn't change.** That's expected — per the existing `lb-named-float-externs` memory note, objdiff's fuzzy match% is opcode-based, and reloc-symbol-name diffs are scored separately. The name rename is a *prerequisite* for full byte match (the function won't be 100% bytes without it), but it doesn't move the % score.

So `name-magic` doesn't immediately bump match% on the stuck functions, but it does fix the named-symbol prerequisite when we're closer to the bytes match.

## Integration friction

`name-magic` is post-build, but `ninja` re-runs the compile and clobbers the rename every time `tools/checkdiff.py` runs (it invokes `ninja` even when the source hasn't changed, since the build database tracks more than just file timestamps).

I worked around this by running `objdiff-cli` directly without `ninja`, but for normal iteration the rename keeps getting undone. The handoff doc acknowledges this and says "wrap it in a script if you iterate often."

**Suggested**: integrate name-magic into the ninja build itself — e.g. as a post-link step on the .o, driven by a map file alongside each .c. Then renames survive `ninja`. The map could even be auto-derived from symbols.txt for files where the named symbols at .sdata2 offsets are predictable (the open wishlist item from the handoff).

For now, my workflow is: edit source → ninja → name-magic → objdiff-cli. checkdiff.py only works the first time after a rename before it clobbers.

## Combined experience

Both tools are clear improvements over the previous `--force-iter-first 32` "guess and check" workflow:

- `match-iter-first` removes the guessing for "which virtual should be first?"
- `name-magic` finally makes the int-to-float magic constants nameable

Neither tool, by itself, closes the stuck functions in mnvibration.c — but together they let me say with certainty:

- **fn_80248A78** (97.5%): structurally as good as the rewrite achieves; remaining gap is the param-iter swap that `match-iter-first` precisely identifies. Allocator-level only.
- **fn_80247510** (84.9%): same lens applies; the magic constant rename via `name-magic` is the bytes-prerequisite for that function too.
- **mnVibration_80248444** (95.1%): same magic constant. With name-magic + globalize, the named reloc matches; remaining gap is opcode-level.

That diagnostic certainty is genuinely valuable even when % numbers don't move.

## Workflow notes for the agent

If you want a one-shot "is this byte-matchable in principle" command, it'd be something like:

```bash
melee-agent debug match-and-fix <function>
# 1. Identify iter-first targets via match-iter-first
# 2. Identify renamable symbols via name-magic --list (compare against expected .o's globals)
# 3. Report: "with iter-first X and renames Y, function would byte-match"
# 4. Optionally: produce the patched .o on disk for one-time verification
```

That command would close the diagnostic loop: yes/no on "matchable in principle" with the artifacts needed to prove it.

Lower priority than the open wishlist items in the handoff, but flagging for the queue.
