# hsd_803B3408 follow-up, 2026-09-06

The current source originates in merged PR3350 and remains 98.7788%, 868 bytes, 152-byte frame. No new source improvement retained in this pass. Baseline and final ordinary checkdiff agree.

Whole-function hashed donor search across indexed projects peaked at0.403; 32-instruction windows peaked at0.588. No structural twin found. Existing historical note #254 says retail IRO already confirmed the parenthesized chroma address grouping survives the frontend but is reassociated during initial PCode lowering.

New/checked source families and exact results (all reverted):

| Probe | Match % |
|---|---:|
| bitfields | 70.691246 |
| src-row-unsigned | 98.68664 |
| chroma-x-unsigned | 98.7788 |
| chroma-pointer | 97.32719 |
| chroma-offset-helper | 98.5576 |
| luma-base-before | 98.6636 |
| luma-base-after-zero | 98.6636 |
| luma-counter-int | 98.7788 |
| luma-index-unsigned | 98.7788 |
| offset-first | 91.258064 |
| dst-order | 98.7788 |

Bitfield union changed channel extraction and added8frame bytes. Explicit row pointer breaks the target single scalar-index address calculation. Inline row-offset helper adds8frame bytes without fixing addition grouping. Early reuse of chroma_index changes its CSE/lifetime substantially and regresses. Reversing dst_row operands is neutral. Moving invariant luma base out of the loop condition regresses; int/u32 pixel counter is neutral.

Residual: commuted row add at+0xb4, chroma scalar-index reassociation at+0xc4/+0xc8, downstream GPR cascade, and luma setup li/addi order at+0x1f0/+0x1f4. Next useful source lever should change lowering dependencies, not merely add parentheses. Dump is a baseline artifact; recapture after source changes before deriving allocation targets.

A final subtract-negative operand-order probe regressed96.65899% and was reverted.

## Address-lowering follow-up after upstream PR3358 merged

Upstream is now `87976be9f5`; the c016 merge `d24f281a99` preserves the
coefficient encoder's later lookup improvement. The RGB baseline remains
98.7788%, 868 bytes, 152-byte frame. No RGB source change is retained.

A fresh baseline debug dump still has the unwanted address association at
`BEFORE GLOBAL OPTIMIZATION`: the two column terms are added before the row
term. The ordinary final output agrees. This reinforces the existing retail
finding about initial lowering; changing register allocation alone cannot
repair that grouping. The luma setup still has `addi` before `li`, and the
row addition still has commuted source registers.

The successful coefficient lookup assignment technique did not transfer to
this source. Embedded integer-index assignments can preserve a different
association, but introduce another instruction and change the load form or
register allocation. Explicit pointer assignments also disturb the load
sequence. Typed luma field references compile identically; assigning a new
pointer within that access regresses. Integer-address spelling, byte-pointer
arithmetic, and equivalent shifts supply no retained improvement.

Ordinary probe results (all reverted):

| Probe | Match % | Instruction delta | Frame bytes |
|---|---:|---:|---:|
|byte-pointer-address|98.7788|0|152|
|dst-embedded-assignment|98.31797|0|152|
|dst-row-compound|98.7788|0|152|
|group-increment-index|95.96774|1|152|
|high-shift|98.29493|0|152|
|index-embedded-existing-first|95.89862|1|152|
|index-embedded-existing|95.89862|1|152|
|index-embedded-new|95.89862|1|152|
|index-embedded-srcrow|97.99539|0|152|
|index-group-u32|98.7788|0|152|
|index-group-unsigned-cast|98.7788|0|152|
|int-all-locals|98.7788|0|152|
|int-chroma-index|98.7788|0|152|
|int-coordinates|98.7788|0|152|
|int-dstrow|96.65899|0|152|
|int-srcrow|98.7788|0|152|
|integer-address-indexed|95.99078|0|152|
|integer-address|98.7788|0|152|
|low-shift|98.7788|0|152|
|luma-field-indexed|98.7788|0|152|
|luma-typed-array|98.7788|0|152|
|luma-typed-field-embedded|95.02304|1|152|
|luma-typed-field|98.7788|0|152|
|luma-typed-word-offset|98.7788|0|152|
|negative-group|98.7788|0|152|
|pixel-pointer-embedded-reuse|91.70046|2|152|
|pixel-pointer-embedded|92.156685|1|152|
|row-assignment-first|90.08295|2|152|
|row-assignment-in-index|95.39171|1|152|
|row-formula-in-index|96.26728|0|152|
|row-initializer-fixed|97.741936|0|152|
|shifts|98.29493|0|152|
|unsigned-row-group|98.68664|0|152|
|x-assignment-in-index|95.9447|1|152|

`row-initializer` initially had a generated-source replacement error and did
not compile; it is not evidence against the source family. The corrected
`row-initializer-fixed` probe above is the valid measurement. The self-assignment
and nested destination-assignment variants were diagnostics only and are not
proposed production source.

Restored ordinary checkdiff is 98.7788%. The merged baseline also passed the
full GALE01 build and original DOL checksum. Durable source, checkdiff, dump,
result index and SHA256 manifest are under:

`~/.config/decomp-me/matching-evidence/jpeg-rgb-2026-09-06/address-lowering-followup/`

These rejected source families do not prove that matching is impossible.
A next attempt should target a specific initial-lowering dependency or a
substantially different address/helper reconstruction, rather than more
parentheses or a forced physical register map.

## Pixel-helper and tiled-layout follow-up

Merged upstream `f6c322a352` (the `lbsnap` match/link) into this worktree before
probing. RGB remains **98.7788%, 868 bytes, frame 152**. The 53 compiled
candidates below contain 45 valid source probes and eight excluded diagnostic
array casts. No source change was retained.

| Source family | Count | Result |
| --- | ---: | --- |
| Row-plus-column inline helper, s32/u32/int and reversed parameters | 6 | 97.98157–98.07373%; changes grouping but combines low column with row first, still wrong |
| Pixel-load or pointer-return helper, with index, row/x, or separate high/low parameters | 5 | 98.02765–98.5576%; no target grouping; extra inline homes |
| OR/XOR for disjoint column bits | 2 | 95.76037% / 98.45622%; instruction differences remain |
| Cached index as scalar, array member, or struct member; embedded/separate/compound assignments | 12 | 95.89862–97.90323%; frame 152, but load/address sequence changes |
| Synthetic multidimensional casts leaving row offset in the inner subscript | 8 | **Excluded:** inner indexing crosses declared row bounds; not production-source evidence |
| Explicit pointer-addition chains | 2 | 94.03226%; one extra instruction |
| Tiled rows of 4/8/16 pixels, row offset carried in outer index, signed/unsigned division or shifts | 9 | 90.52995–95%; no gain |
| Narrow or register-qualified luma counter; `< 4` / `<= 3` loop tests | 7 | Narrow counters 77.866356–78.29493%; register qualifier and relational tests neutral |
| Single destination-row expression or base-first accumulation | 2 | 96.65899%; no commutation fix |

The cached-index probes intentionally still perform both pixel loads: storing
the first chroma result could alias the input image, so reusing the first pixel
value would not preserve the original behavior. The unsigned tiled variants
use the existing aligned row offset, with column subscripts inside each row.

The compiler static-audit setup was validated for exact GC/1.2.5n SHA-256
`ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`:
3,248 functions and a working native Ghidra decompiler. Inspection of the
available `mwcc-decomp` reconstruction found pass coordination and operand
materialization, but did **not** identify the addition-lowering routine that
causes this residual. Many exact-1.2.5n register-origin sites remain unnamed.
Do not treat that audit setup as a new explanation or as proof of a compiler
bug. A useful next diagnostic would correlate these specific initial-PCode
adds to their creation sites before further reassociation experiments.

Restored ordinary checkdiff and the full build passed. All six already-matched
TU functions remain 100%; the coefficient encoder remains 99.70266%. Built
and original DOL SHA-1 both equal
`08e0bf20134dfcb260699671004527b2d6bb1a45`. The TU stays Linkable; no new upstream
PR or PR source update is warranted by this pass.

Durable evidence is in
`docs/matching-evidence/jpeg-rgb/2026-09-06-helper-layout/`: complete candidate
sources/results, generators, baseline/final diffs, audit setup result, restored
TU report, build/checksum evidence, and a verified 203-member SHA-256 manifest.

## Retail creation provenance: the addition-lowering cause

The next capture **identified the lowering routine** and produced a source
variant with the exact target pixel-address window. This supersedes the
previous static audit's lack of an explanation. The production baseline
remains **98.7788%, 217 instructions, 868 bytes, frame 152**; the structurally
useful candidate is preserved separately, at **98.04147%**.

Both pixel loads in the useful candidate use:

```c
pixel = src[((chroma_x & 1) * 2 + (chroma_x & 2) * 4) + src_row];
```

The ordinary compiler now produces the exact target instructions at
`+0xbc` through `+0xc8`: high-column extraction, low-column extraction,
`high + row`, then `low + result`. The lower score does not invalidate this
local instruction-window improvement. Preserve it as a starting point for
further reconstruction, rather than rerunning the same association search.

The exact retail GC/1.2.5n executable's `FUN_004a1130` combines operands.
An operand can carry a deferred pair of registers (`GPRSum`, kind 2), instead
of an already emitted addition. Combining a scalar register with that pair
emits an add of the pair's secondary register and the new scalar, while
keeping its primary register deferred. `Operands_ForceGPR` / `FUN_004a0ba0`
subsequently materializes the remaining addition.

In the old source, the pair is `(row, high)` and the new scalar is `low`:
the compiler emits `high + low`, then `row + result`. In the useful source,
the pair is `(low, high)` and the new scalar is `row`: it emits `high + row`,
then `low + result`. Read-only entry observations and PCode creation events
confirm both paths. The relevant emission call sites are `0x004a1402` and
`0x004a0c87`; the addition-lowering caller returns at `0x004b8511`.
The combiner sidecar's `requested` argument was read as 32 bits although the
parameter is 16 bits: only its low 16 bits are meaningful. This field is not
needed for the pair-order conclusion.

The baseline capture joins all 220 initial instructions to 220 creation
events; the candidate joins all 219 to 219. The ordinary final output for
both has 217 instructions. These are read-only diagnostics, not modified
compiler output or proof of a complete traced compile. The compiler SHA-256
is `ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
The reusable finding is recorded as mismatch pattern
`mwcc-deferred-gpr-sum-reassociation`.

### Remaining scheduling and allocation evidence

Nine candidate PCode stages and four GPR/FPR coloring snapshots passed the
standalone structural validators. Their instruction counts are respectively
219, 240, 219, 218, 212, 217, 217, 217, and 217, from initial lowering through
final scheduling. Stage comparison follows instruction addresses within the
same capture; it is not an independent byte-for-byte object verification.

The first pixel load is `LHZ` (the later luma load is `LHZX`). The low-bit
extraction used by the destination index is before this load through
post-allocation peephole, and the final scheduler moves it after the load.
The target has the extraction immediately before the load. This isolates
the new ordering difference to final scheduling, after the corrected
address sequence has already survived lowering and allocation.

The candidate destination pointer, virtual GPR 37, has one definition and
two store-base uses, is not coalesced, and receives physical r30; the target
uses r22. The chroma index receives r23 where the target uses r21. The
remaining diff also includes the old destination-row add commutation and
luma `li`/`addi` order. Declaration movement alone does not resolve these.
Object-name/vreg-origin capture was deliberately disabled in this focused
run: `?` names and the report's generic scratch labels are **not** evidence
that every register represents a compiler-generated temporary. Likewise,
an alias displayed as `r61` is a virtual parent, not a physical register 61.

### Source probes and tooling lessons

There were 71 compiled candidates in this pass; six are excluded as evidence
for their intended high-term sharing transform because the generator failed
to replace its uses. The six corrected high-sharing probes were rerun.
All experiments were restored; none improved the full-function percentage.

| Source family | Count | Match % range / result |
| --- | ---: | --- |
| Pixel-address operand order and association | 12 | 98.04147–98.7788; two forms fix the target four-instruction window |
| Named low/high terms, scalar/struct/array | 11 | 97.92627–98.04147; six ineffective high-term transforms excluded |
| Corrected high-term / both-term sharing | 6 | 98.20277 |
| Destination pointer ownership and early index calculation | 10 | 96.95853–98.133644 |
| Pixel s32/u32/int types on baseline and corrected address | 6 | 81.6636–98.7788; u32 changes float conversion |
| Reuse existing index for low/high term | 4 | 91.07373–97.99539 |
| Destination-index operand order and association | 12 | 94.691246–95.912445 |
| Destination/index scope and inner declaration order | 10 | 97.23502–98.04147 |

The existing standalone `mwcc-decomp` reader worked through the retail
emulator without Docker. Its GDB entry point needs `runpy.run_path` in this
embedding; plain GDB `source` inherited the wrong import context. The
standalone function-name cache was empty, so the focused hook used the
existing exact-1.2.5n object decoder to select the function. An earlier run
completed successfully while selecting no functions: exit success alone
does not establish that a trace was captured. Disabling unrelated register
creation breakpoints made the focused capture practical. No inferior memory
was changed. Tool issue 1515 requests a supported focused provenance command.

Complete candidate sources/results, read-only hooks, successful and failed
capture artifacts, static compiler export, stage validation/comparisons,
tool input snapshots, and the exported mismatch pattern are archived under
`docs/matching-evidence/jpeg-rgb/2026-09-06-creation-provenance/` with per-member
SHA-256 hashes. The source candidate is
`c016-rgb-combine-rule/LHR-left.c` inside the archive.

Next source work should preserve the proven address association and target
the destination-index lifetime or its scheduling dependency, using the
captured stages to reject ineffective transformations. More operand-order
or declaration-scope sweeps from this set would repeat measured failures.

After restoring the production source, ordinary checkdiff reproduced
98.7788%. The encoder remained 99.70266% and the other six TU functions
remained 100%. `python configure.py && ninja` passed; built and original DOL
SHA-1 both equal `08e0bf20134dfcb260699671004527b2d6bb1a45`. The TU remains
Linkable, and no upstream source PR update is warranted by these experiments.

## Decoder technique transfer and retail SELECT replay

After rechecking upstream and active PRs/claims, RGB remains available; the
Big Blue and snapshot residuals are covered by other work. The decoder's new
outer-subtract-negative technique was tested here in six pixel-address forms
and eight destination-row forms (the latter on both original and corrected
pixel-address trees). None improves the retained 98.7788%. Correcting the pixel
address still gives 98.04147%; some row forms regress as far as 96.17512%.
All fourteen keep the 152-byte frame. The decoder technique is therefore not
a general fix for this RGB residual.

A fresh local diagnostic dump was refused with exit125: the earlier encoder
root-inversion process, PID95126, remains uninterruptible (UEs, parent1) in
macOS. No new wibo process or unsafe override was used. The refusal and live
process observation were added to existing issue1514. This blocks that dump
route, not ordinary compilation or analysis of saved retail evidence.

The corrected pixel candidate's existing retail before/after coloring
snapshots were adapted to the existing SELECT model. The adapter uses the
before snapshot's recorded list in its listed order and after snapshot's
physical assignments, resolving coalesced aliases through their roots. It
reproduces **105 of 105 GPR assignments**, with no incomplete or spilled nodes.
Reversing the list reproduces only 28/105; the snapshot field's name
`simplify_order` must not be taken as an instruction to reverse it here.
These inputs were already structurally validated in the creation-provenance
archive; this replay adds a check against observed retail allocation.

Moving destination pointer IG37 later in this abstract selection order can
change it from r30 to the target r22. Fifteen positions do so, but every one
also changes IG95 r22 to r23 and IG38 r23 to r20. This is **not** a full-target
solution or a source-realizability claim. It establishes that the pointer's
single desired color must be evaluated together with the collateral changes.

Six source follow-ups tried assigning the destination pointer inside the store
expression, computing a named Cb result before the pointer, and computing it
before the destination index. Each was tested on original and corrected pixel
address trees. All six are neutral for their respective baselines; the three
forms in each group emit identical instruction bytes. Merely moving those
statements does not supply the modeled selection-order change.

All 20 compile runs, candidate sources, retail model inputs/adapter/results,
diagnostic refusal, and restored verification are preserved under
`docs/matching-evidence/jpeg-rgb/2026-09-06-decoder-transfer/`. Ordinary final
checkdiff remains **98.7788%**, all six already-matched TU functions remain
100%, and the encoder remains99.70266%. The full build passes and its DOL
matches the original SHA-1 `08e0bf20134dfcb260699671004527b2d6bb1a45`.
No source change or new PR was warranted; the TU remains Linkable.

## Inline channel boundaries and shared work-buffer ownership

A further 24 real-TU compiles tested larger source boundaries on both the
98.7788% baseline and 98.04147% corrected pixel-address tree. No source change
was retained.

| Family | Runs | Result |
| --- | ---: | --- |
| Cb/Cr result helpers and store helpers with both argument orders | 10 | Single result helpers and store helpers neutral; extracting both result helpers adds eight frame bytes, giving98.5576% /97.820274% |
| Luminance JpegWork view, then one shared work pointer at function/tile scope | 6 | Changes luminance loop code, adds two instructions and eight frame bytes;82.576035–83.77419% |
| Cb addition order, constant-last products, and negative channel expressions | 8 | Addition/product commutations neutral; negative expressions alter arithmetic code and regress97.05069–98.04147% |

The shared-work reconstruction addresses chroma through `work->data.x518` /
`x618` and luminance through `work->data.x118[pixel_index * 64]`, shifting the
work pointer by the logical luminance position. This is a diagnostic source
shape, not a proposed type-layout change. Its emitted code is substantially
worse than the separate scalar luma-base representation. The negative channel
expressions are likewise diagnostics; mathematical equivalence alone is not
proof of identical contracted floating-point evaluation.

These results close the tested helper and cross-phase pointer-sharing forms.
They do not rule out a different original helper boundary or prove that the
remaining register order is unreachable. The saved retail model remains useful,
but none of these source forms realizes its destination-pointer selection move.

The restored ordinary check is98.7788%; the encoder is99.70266% and all six
other functions in the TU remain100%. `python configure.py && ninja` passes,
and built/original DOL SHA-1 remains
`08e0bf20134dfcb260699671004527b2d6bb1a45`. Source, complete diffs, generators,
and final verification are archived in
`docs/matching-evidence/jpeg-rgb/2026-09-06-inline-ownership/`.
