# JPEG coefficient encoder matching notes

Verified 2026-09-06 in c016. Source: `src/sysdolphin/baselib/hsd_3B34.c`.

## Retained improvement

- `hsd_803B3CD8`: 97.746475% → **99.51487%**.
- Fork source commit `597831ba77`; clean upstream PR commit `f7014a75c6`.
- [PR #3377](https://github.com/doldecomp/melee/pull/3377), adapted with credit from @fjooord’s [#3358](https://github.com/doldecomp/melee/pull/3358).
- Bit-length and bit-output helpers replace repeated loops. `JpegEncodeTables` names the existing table layout.
- Six other functions remain 100%; `hsd_803B3408` remains 98.7788%. TU stays Linkable until both residuals match.
- Clean upstream PR full GALE01 build passes the original DOL checksum. This validates the unlinked baseline build, not byte identity of the still-unmatched encoder.

## Residual and diagnostic proof

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

This is not a source match: forced results come from the debug compiler. The final ordinary production compile reproduces 99.51487%. Next useful work should address pointer/index expression lowering and how the work-pointer web gets its allocation priority. Avoid repeating register-only spelling sweeps.

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

## Evidence

Durable local kit: `~/.config/decomp-me/matching-evidence/jpeg-encoder-2026-09-06/`.
Contains original/donor/final and failed-probe JSONs, baseline/final source, baseline and forced dumps, allocation/pressure reports, whole-unit report, clean PR build log, and a SHA-256 manifest. Source notes are committed separately on the fork work branch, not included in the upstream PR.
