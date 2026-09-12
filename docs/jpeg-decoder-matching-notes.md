# JPEG decoder checkpoint — 2026-09-06

`fn_803B6820`, in `src/sysdolphin/baselib/hsd_3B5C.c`, remains **98.81743%**,
241 instructions and a 176-byte frame. No source change from this pass is
retained. There is no scratch. PR #3376 was closed after upstream #3358
imported its improvement; do not reopen it without a new source gain.

The other matching thread, `01a0749c-030f-73b1-abae-0aeb453a792b`, is working
on JPEG encoder functions in `hsd_3B34.c` under PR #3377. This pass touched
only our decoder source and restored it after each probe. The final claim
audit found that thread on `hsd_803B3408`. Recheck claims and PRs before
resuming; this is a dated audit.

## Retail evidence

An ordinary debug capture and an unmodified GC/1.2.5n retail backend capture
reproduce the register differences. Fidelity reports 674 equal fields, 69
retail-only fields, and 116 differences caused by missing debug simplify-order
fields. This comparison found no conflicting physical colors. It does not
establish complete optimizer or PCode-history coverage.

The persistent X offset `(x / 4) << 4` is GPR IG65, selected at iteration 21
into r20; the target uses r15. Heuristic source attribution incorrectly names
this node `luma_base`: follow the defining instruction. IG64 is luminance
(iteration 22/r19), IG63 is Cr (23/r18, target r20), and IG44 is Cb
(24/r17, target r18). The persistent row stride is IG66 (29/r14, already
correct). A single forced IG65:r15 diagnostic does not fix the cascade.

A separate read-only retail capture reused the existing cost hook and snapshot
reader. Its provenance records compiler 1.2.5n and exit 0. GPR capture has
147 nodes, 81 with nonzero costs. IG65 and IG66 both have cost 17 and
post-simplification degree 7, despite their different selection positions.
IG63 and IG64 both have cost 28679 and degree 4. Equal costs therefore do not
explain these ordering differences; graph structure and node ordering still
matter. These are captured costs, not a proof that a particular source edit
will produce the target. The hook's inherited schema name starts with `c016`;
its recorded function and worktree identify this decoder run.

The complete previously observed GPR remapping still leaves a commuted add at
+0x1CC. Do not call it a forced exact match. Automatic target derivation also
misbound the chroma pointer definition at +0x1D8 (issue #1509). Explicit class
prefixes are required when experimenting with GPR maps.

## Bounded source probes

All scores below come from ordinary compilation in the real translation unit.
The evidence archive contains complete sources and checkdiff reports.

| Source form | Match % | Frame |
|---|---:|---:|
| Word pointer for chroma addressing | 98.81743 | 176 |
| 32-word chroma row view | 95.497925 | 176 |
| 128-byte chroma row view | 95.497925 | 176 |
| Output-pointer helper using successive additions | 92.39834 | 176 |
| Offset output-parameter helper | 96.84647 | 176 |
| Output-pointer helper using one array index | 96.84647 | 176 |
| One-field X-offset struct or one-element array | 95.60166 | 176 |
| Two-field address struct, unused row field, either order | 95.46058 | 184 |
| Two-field address struct, both fields used, either order | 93.489624 | 184 |
| Both fields used, existing padding removed | 93.63071 | 176 |

The offset-output and indexed-output helpers introduce one instruction. They
leave the X offset in r20; their other allocation changes are not an X-offset
solution. The one-field carriers move X offset to r14 and row stride to r20,
while also changing scheduling. Matching the frame by replacing existing
padding with a real two-field local does not fix the instruction stream.

One additional four-word row-view probe was compiled and restored but is
**semantically invalid**: its second index can exceed the subarray bound.
Its 94.87552% score is excluded from valid source evidence. Do not reuse it.
The first two-field variants intentionally retained here as negative evidence
had an unused row field; the later `-both` variants tested both field uses.

The archived prior attempt ledger records earlier neutral or regressing color
helper, clamp, declaration, chroma-sum, and bias-loop reconstructions. Two prior
bounded permuter runs also retained no gain. Avoid repeating these families
without a new lead. Whole-function donor search found no close twin in the
queried index; the strongest window hit was a generic unrolled bias loop.
Bounded local and GitHub constant searches did not identify a source donor.

## Persistence and verification

The [evidence manifest](matching-evidence/jpeg-decoder/2026-09-06-retail-cost/manifest.json)
records every archived file's hash, probe results, captures, and verification.
A fresh checkdiff after restoration confirms 98.81743%; all five other TU
functions remain 100%. The full build passes and its DOL is byte-identical to
the original. The decoder TU remains Linkable, so that DOL check does not prove
the unmatched C body is correct.

Repository totals remain 19819/19828 matched functions and 1124/1130 linked
translation units. No compiler, capture, or permuter job from this pass remains
running. This function remains in the unmatched pool; the next useful lead
must preserve the target address arithmetic and explain the joint selection
order, rather than merely force one register.
