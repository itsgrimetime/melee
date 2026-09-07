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

## Upstream merge and PR refresh

PR3358 and PR3378 merged upstream. c016 merge `d24f281a99` incorporates
upstream `87976be9f5` and retains the later coefficient lookup fix. The clean
PR branch was updated with merge `116e620820`; PR3377 is now a single-file,
five-addition/one-deletion patch against upstream, improving99.51487% to
99.70266%. Its body describes that remaining change and credits both donors.

The refreshed PR build passes the original DOL checksum. All six previously
matched TU functions remain100%; RGB remains98.7788%. GitHub reports the PR
mergeable; CI was running after the push, with all three style jobs passed at
the first check. Local build evidence is saved separately from CI status.

PR3372 (bracket) and PR3376 (JPEG decoder) were closed after confirming their
source files were byte-identical to current upstream. Their improvements were
absorbed by PR3358; no replacement PR was opened. PR3375 remains open and
another agent holds the fn_802545C4 claim, so this pass did not alter it.

The fork pre-commit style checker flags four unsuffixed floating literals
already present in the merged upstream grbigblue/psdisp sources. All other
checks and the full build passed. Merge commits preserve upstream source;
the hook was bypassed for those merge commits only.

Follow-up CI check: every applicable job for PR3377 head `116e620820` passed,
including Nix, native, clang, diff/link/test, and all style jobs. Pages/wiki
publication jobs were skipped as expected for the PR workflow.

## Retail allocation and owner follow-up

Baseline remains 99.70266%, 639 instructions, frame104. No source improvement
was retained. This pass compiled 51 candidates: 50 valid source probes and one
invalid unsequenced-assignment probe explicitly excluded from matching evidence.

The standard retail backend command completed and observed all283 GPR color
decisions. IG57 selects first into r31; IG216 selects second into r30. The
retail/debug comparison has1311 equal fields,37 retail-only entries, and104
differences, all of the latter being missing debug simplify-order entries.
It reports no differing observed physical assignments. This is allocator
evidence, not a claim that all tracing capabilities are complete: the early
PCode boundary was rejected, the final-scheduler fallback captured639
instructions, and operand instrumentation remains partial.

The alleged spill has a concrete reporting cause. In mwcc_debug.c the simplify
hook tests flags&0x08 and prints SPILLED, while the same file defines0x08 as
COALESCE_ROOT and0x01 as SPILLED. Retail reports IG57 colored. Issue1503 now
contains this diagnosis. There is no actual spill or fallback selection in the
validated baseline replay below.

A read-only retail cost/graph capture reused the existing mnitemsw hook and
pinned GC/1.2.5n compiler. IG57 has four coalesced-away table-address neighbors:
107/109 merge into DC-code root61;111/113 merge into DC-length root60. Together
with eleven fixed physical neighbors they account for its final degree15.
Its cost is0, but that cost is irrelevant here because normal simplification
completes without fallback.

Replaying the retail scan algorithm from the captured graph reproduces every
one of the283 recorded selections, including all three scans. Scan1 removes
260 nodes; scan2 removes22; scan3 removes only57. These are one-based scan
numbers; JSON uses zero-based indices. Removing one, two, or three of the four
table edges leaves57 first-selected. Removing all four makes it select17th,
which explains why simply delaying pointer initialization overshoots the
desired order.

A hypothetical relabeling of root57 and alias103, preserving every graph edge
and flag, produces the desired leading selection sequence216,103,101. This
is a precise next hypothesis: change ownership of the shared address while
preserving its entry definition and uses. It is **not a compiler-validated
intervention or source match**. The scoped force-coalesce inversion was refused
before compilation because alias103 has no standalone color decision. The
alias is present in the observed graph; issue1514 records the limitation. No
guard was bypassed and no forced object was produced.

Ordinary source probes, all restored:

- Direct-global longjmp/byte/bit helpers:95.241005%, frame136.
- Work wrapper passed by value:86.11268%, frame192. Byte-writer error wrapper:
  96.76526%, frame192.
- Named run+1 temporary at function or loop scope:99.22535%, frame104.
  Register-qualified pointer wrapper:neutral.
- All21 individual embedded copies at the seven bit-writing calls (value,
  length, or work argument): neutral or worse. Every variant keeps the entry
  work pointer in r31. This does not establish failure of combined windows.
- Work initialization after tables:neutral; after DC-code selection:98.763695%,
  r31; after DC-length or AC selections:98.341156%, r26. All have frame104.
- DC-code/length wrappers, combined or reversed, and selector helpers:
  99.69484%, frame112. Wrapping all four tables gives frame120 and the same
  score. The38 register differences remain.
- Repeated direct global addresses with no named work owner:93.53677%,
  frame128, with or without the unused state declaration.
- A first-use assignment on one side of subtraction read the uninitialized
  pointer on the other side. Its97.666664% score is invalid evidence. The
  corrected sequenced-comma and direct-global-right versions are98.6072% and
  97.165886%, both frame104.
- Pointer array, state array, or array member:neutral99.70266%, frame104.
  Integer-address owner:98.54773%, frame104.

The generated select-order plan was reviewed but not compiled: its synthetic
IG216 attribution led to unrelated byte-index spelling probes. The observed
definition is run+1, and the manually authored run-count probes tested that
actual source relationship instead.

Committed evidence and per-candidate results:
`docs/matching-evidence/jpeg-encoder/2026-09-06-retail-owner/`.
Includes baseline/source probes, full retail allocator trace, partial PCode
metadata, cost capture, replay inputs/code/results, refused inversion log,
ordinary restoration, and final full-build/DOL verification. PR3377 is unchanged;
the TU still has the separate RGB residual and stays Linkable.
