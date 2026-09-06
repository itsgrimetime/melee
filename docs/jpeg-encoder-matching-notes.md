# JPEG coefficient encoder matching notes

Verified 2026-09-06 in c016. Source: `src/sysdolphin/baselib/hsd_3B34.c`.

## Retained improvement

- `hsd_803B3CD8`: 97.746475% → 99.51487% → **99.70266%**.
- Latest fork source commit `d2e79f7910`; clean upstream PR commit `fae69cf9e1`.
  Initial helper/table improvement: `597831ba77` / `f7014a75c6`.
- [PR #3377](https://github.com/doldecomp/melee/pull/3377), adapted with credit from @fjooord’s [#3358](https://github.com/doldecomp/melee/pull/3358).
- Bit-length and bit-output helpers replace repeated loops. `JpegEncodeTables` names the existing table layout.
- Six other functions remain 100%; `hsd_803B3408` remains 98.7788%. TU stays Linkable until both residuals match.
- Clean upstream PR full GALE01 build passes the original DOL checksum. This validates the unlinked baseline build, not byte identity of the still-unmatched encoder.

## Initial residual and diagnostic proof, before the lookup fix

Unforced code has the exact 104-byte frame and instruction count. Work-buffer pointer is r31 (target r30); DC bit length and three later bit-writing values use r30 (target r31).

The captured baseline debug dump uses these GPR targets:

```
0:56:30,0:85:31,0:91:31,0:100:31,0:216:31
```

Applying that complete map diagnostically resolves every register difference. Only the coefficient lookup at +0x370 remains:

```
Target:  slwi r0,r0,2; add r3,r30,r0; lwz r0,1816(r3)
Current: slwi r3,r0,2; addi r0,r3,1816; lwzx r0,r30,r0
```

This was not a source match: forced results came from the debug compiler. The ordinary production compile at this stage reproduced 99.51487%. The lookup follow-up below resolves the pointer/index lowering difference.

First-divergence reports Case C2: IG56 is selected first and receives r31; target requires r30. Automatic target derivation omitted IG85 and IG91 (the two `lhzx` values); add them for a complete diagnostic map. IG IDs belong only to this exact source/dump.

Fresh lifetime-pressure reports incorrectly label colored IG56 as spilled because of its simplify-graph event. Filed shared tooling issue #1503. Trust its observed physical assignment and the forced proof; do not infer an actual stack spill from that label.

## Rejected or neutral source probes

Each started from the retained baseline; all were reverted. Scores are ordinary production compiles.

| Probe | Match % | Frame bytes |
|---|---:|---:|
| flat | 98.55243 | 104 |
| index-s32 | 99.51487 | 104 |
| no-pad | 99.50704 | 88 |
| coef-helper | 99.50704 | 112 |
| coef-int-local | 99.50704 | 112 |
| coef-pointer | 99.11424 | 112 |
| jmp-helper | 99.51487 | 104 |
| state-length | 92.428795 | 120 |
| late-work | 98.153366 | 104 |
| ac-int | 99.35055 | 104 |
| index-first | 99.51487 | 104 |

Flattening the single-member work-pointer wrapper introduces an extra entry copy. Signed index casts and passing `__jmp_buf*` into bit-writing helpers are neutral. A coefficient lookup helper/local index adds a stack home; moving length into the state aggregate changes control flow/codegen substantially. Delaying the work-pointer assignment changes allocation but regresses.

`PAD_STACK(16)` remains from the donor. Removing it reduces the exact 104-byte frame to 88. Added index/helper homes reach 112 rather than solving the frame naturally. Padding is not a register-allocation solution; revisit missing original locals/inlines if reconstructing the function further.

## Retained coefficient lookup fix

The index-before-field-offset technique in @sadkellz's
[PR #3378](https://github.com/doldecomp/melee/pull/3378) supplied a new source
hypothesis. Merely casting a shifted work pointer was neutral. Assigning that
pointer **inside the dereference** produced the desired `slwi; add; lwz`
sequence:

```c
JpegWork* indexed;
/* Apply the zigzag index before the coefficient array offset. */
s32 coefficient =
    (indexed = (JpegWork*) ((s32*) state.work + lbl_80431638[index]))
        ->data.coef[0];
```

The ordinary compiler now reports **99.70266%**, an exact opcode sequence,
2556 bytes of code, and the exact 104-byte frame. All six matched functions
remain at 100%; RGB conversion remains 98.7788%. Both the primary and clean
PR checkout passed the full GALE01 build and DOL checksum. The TU still has
two unmatched functions and remains Linkable.

The assignment position matters: a separately initialized `indexed` pointer
keeps the old `addi/lwzx` sequence and grows the frame to 112. Plain typed
casts, byte and word address arithmetic, `offsetof`, and explicit shifts are
neutral. The exact compiler pass responsible has not been established.

Recorded the validated pattern as
`indexed-pointer-assignment-preserves-field-displacement` in the mismatch
database. Credit both PR #3358's original helper reconstruction and PR #3378's
address technique when describing this source.

## Current allocator-only residual

There are 38 register-only instruction differences: r30/r31 are exchanged
between the work pointer and four bit-length/output values. In the fresh
improved-source dump, the complete diagnostic map is:

```
0:57:30,0:86:31,0:92:31,0:101:31,0:216:31
```

This map produces **byte-identical function code** with the forced debug
compiler. It is diagnostic proof only; the restored, unforced source remains
99.70266%. Do not reuse the earlier source's numeric IG map.

IG57 coalesces with IG103 and is selected at position 0, taking r31. The
first-divergence report is still Case C2: the target needs r30, so the
nonvolatile allocation order must change. The four other values are selected
at positions 12, 8, 2, and 1 respectively. The pressure report still labels
IG57 spilled even though it has an observed physical register; issue #1503
applies. No stack spill is established by that label.

Follow-up probes on the improved source, all reverted:

| Family | Result |
| --- | --- |
| Three bit-writer parameter orderings; byte-writer work argument first | Neutral |
| Bit-length counter int, value int/unsigned, return int | Neutral |
| Local union exposing work and jump-buffer pointer views, either member order | Neutral |
| Separate jump-buffer pointer first, work pointer derived from it | 99.69484%, exact opcodes but frame 112 |
| Independent second jump-buffer pointer | 98.1518%, four extra instructions, frame 128 |
| Second jump-buffer pointer derived from the work member | 98.33177%, three extra instructions, frame 128 |
| Jump-buffer pointer as the sole local state member | 98.54773%, two extra instructions, frame 104 |

Before the retained fix, unifying the coefficient and AC value locals gave
99.35055%, and sharing the DC value local for AC work gave 99.16276%; both
added an instruction. Reusing the DC value as the zigzag index was neutral.
An integer address sum with the index first regressed to 98.53677% and frame
112. These are not improvements hidden by score noise.

## Evidence

Durable local kit: `~/.config/decomp-me/matching-evidence/jpeg-encoder-2026-09-06/`.
Contains original/donor/final and failed-probe JSONs, baseline/final source, baseline and forced dumps, allocation/pressure reports, whole-unit report, clean PR build log, and a SHA-256 manifest. Source notes are committed separately on the fork work branch, not included in the upstream PR.

`lookup-assignment-followup/` adds the new baseline and retained source,
all address/type/helper candidates, ordinary checkdiff results, the fresh
allocator map and pressure report, the byte-identical forced proof, and a
recursive SHA-256 manifest. Its `results.json` is a compact score index.
