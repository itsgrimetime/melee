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

## Two-role target correspondence and whole-conversion helper

The corrected pixel-address candidate now has a checked GPR target
correspondence: 264 operand occurrences across 81 virtual roots. Each included
instruction is joined by its stable address between the precolor and final
retail captures, then checked against ordinary candidate assembly. Target
instruction shape is checked after aligning the known swaps at 0xd4/0xd8 and
0x1f0/0x1f4. The commuted row add at 0xb4 is excluded; it needs a source-order
fix. Prologue/epilogue, implicit-operand, and changed-opcode exclusions are
listed in the result, rather than guessed.

Eight mapped roles differ from target: pointer 37, index 38, and extraction /
conversion temporaries 94,95,97,98,100,101. Extending the partial target with
observed baseline colors for unmapped roots, the existing model can reproduce
all 105 assignments by moving only pointer 37 and index 38 in SELECT order.
Of 10,609 tested pairs of positions, 1,045 reach that extended target. One is
`37 after 126`, then `38 after 121`. This demonstrates a compatible coloring on
the recorded graph; it does **not** demonstrate source realization, resolve
the instruction-order differences, or independently prove the unmapped target.

Sixteen real-TU source probes followed:

| Family | Runs | Result |
| --- | ---: | --- |
| Whole per-pixel chroma helper, reversed arguments, precomputed input pointer, whole chroma-x loop helper | 8 |96.92166–98.68664%; whole-loop helper adds eight frame bytes |
| Direct named array stores with index, full expression, index helper, or repeated pointer expression | 8 |89.963135–98.133644%; index helper adds16 frame bytes |

Every form preserves the two pixel reads with a chroma store between them;
none reuses a potentially stale first pixel after the store. No source was
retained.

### Retail explanation of the whole-helper regression

A new read-only retail capture of the corrected-pixel, whole-source-first
helper reaches final scheduling for `hsd_803B3408`, with 217 final instructions
and exit 0. All 13 PCode/coloring snapshots pass the capture repository's
structural validator. The older decomp-scripts validator rejected the 1.2.5n
hash because its whitelist only supports 1.2.5; inputs and whitelists were not
altered. This is a selected-function capture, not a full compiler run.

Initial, optimized, and final precolor stages have consistent instruction /
register bijections (219,240,218 instructions). Symbol identity is not proved
by that correspondence alone. Of 84 mapped GPR decisions, many change selection
positions or colors. Pointer37 becomes 73 and moves from SELECT position 23 to SELECT position 2,
receiving r5 instead of r30. Index38 becomes 72, moves from 99 to 86, and receives r22
instead of r23. All 39 mapped FPR decisions are unchanged.

This is a concrete reason the whole helper is worse: it selects the pointer
much earlier, while the successful abstract constructions delay it. The
captured correspondence is partial; it does not assert full graph isomorphism.

Source, complete diffs, the target correspondence and search, retail captures,
validators, and restored verification are preserved under
`docs/matching-evidence/jpeg-rgb/2026-09-06-two-role-target/`. Ordinary restored
matching is 98.7788%, encoder 99.70266%, and the other six TU functions 100%.
The full build passes and built/original DOL SHA-1 is
`08e0bf20134dfcb260699671004527b2d6bb1a45`. The TU remains Linkable; no source
PR update is warranted.

## From SELECT-only targets to a checked simplify reconstruction

The graph from the corrected pixel candidate now reproduces the full GPR
simplify order as well as its coloring: two ascending-ID scans remove nodes
whose dynamic degree is below 29, updating neighbors immediately. Reversing
that removal list reproduces all 105 retail selections. Coalesced-away nodes
are excluded using the recorded flags. The replay makes no jam/spill choice
because neither scan jams in this input.

Twenty diagnostic swaps of pointer 37/index 38 with the otherwise unused
virtual slots 32–36 fail to fix any of the eight target color differences.
This rules out that specific parameter-slot renumbering idea under the model;
it does not assume a C parameter reuse would necessarily produce those IDs.

A second search moves the two roles later in the virtual-number sequence,
preserving other roles' relative order, then recomputes **simplify and SELECT**.
Of 10,000 insertion pairs, 140 reproduce the extended target. For example,
inserting pointer 37 after old 103 and index 38 after old 101 maps the pointer to
new 103 and index to new 100. They select at positions 55 and 58. This is stronger
than prescribing SELECT order directly: the simplify rules produce that order
on an isomorphic graph. It remains a diagnostic relabeling, not a source-level
match or a proof that the source can realize the same graph and numbering.
The extended target still assumes unchanged colors for unmapped roles, and the
known instruction-order/add-operand residuals remain separate.

### Retail backend route and pressure-report limitation

The supported `debug retro backend` route succeeds and produces a retail
backend-v1 trace with 105 GPR and 48 FPR decisions. Both selection lists and all
153 colors agree with the earlier independently captured snapshots. Its
first-definition, live-interval, and source-attribution fields are explicitly
unavailable; the route did not provide the complete lifetime/source facts
initially sought. The supported pressure explorer consumes it, but cannot
invent those missing fields.

The pressure report calls IG95's final r22 color a blocker for IG37 even
though IG37 selects at 23 and IG95 at 64. That is a final-color compatibility
conflict, not evidence that IG95 already blocked r22 at the earlier decision.
It also labels the selection of r30 as coming from a volatile pool. These
misleading causal/pool descriptions are reported in issue1524. The separately
checked simplify/SELECT replay is the basis for the ordering conclusions.

### Source follow-ups

Twelve component-variable probes introduce explicit red/green/blue scalar,
record, or floating values after **each** pixel read, on both source baselines.
None improves matching. Scalar forms add eight frame bytes; records add 16;
floating forms also perturb registers. Three pointer-return helpers used
directly on store left-hand sides test the later-value-creation hypothesis:
expression return, named index, and passed buffer base. They score 95.7235% or
91.870964%, adding eight or 16 frame bytes. All fifteen were restored.

Evidence is in
`docs/matching-evidence/jpeg-rgb/2026-09-06-simplify-creation/`: source probes,
ordinary diffs, full backend-v1 output, pressure report, simplify/label models,
and verification. Restored RGB is 98.7788%, encoder 99.70266%, and the other six
TU functions 100%. The full build passes and built/original DOL SHA-1 is
`08e0bf20134dfcb260699671004527b2d6bb1a45`; the TU remains Linkable.

## Row materialization boundaries and destination types

Reinspection of the old `base - (-row)` candidate confirms that its lower
score is not a useful row-add frontier: it combines the high-row term with
the tile base before adding the low-row term. That differs from the target's
completed low-plus-high row sum followed by the tile-base addition.

Twenty-four more source probes were measured and restored:

| Family | Runs | Result |
| --- | ---: | --- |
| u8/s8/u16/s16 cast around the first row sum, or narrow dst_row local | 8 | Casts add one instruction, locals add two; 98.31797% / 96.935486%, frame 152 |
| Row-sum/full-row helpers, with and without named luminance offsets | 10 | Sum helper neutral; full helper changes grouping/allocation; no match improvement |
| Word pointer, byte pointer, or named chroma-record destination | 6 | Same instruction bytes as the respective baseline; pointer representation alone is not the lever |

Removing the named `row_offset` and `column_offset` locals from the luminance
loop frees exactly eight frame bytes. The simple expression-only version is
frame 144, with the same instruction count. Combining that with the full row
helper restores frame 152 but still scores only 96.474655% (or 95.76037% with
the corrected pixel-address tree). The frame reservation is therefore real,
but fixing that reservation does not fix the helper's grouping or allocation.
Narrow row types add masks despite the small runtime range; they do not create
a free materialization boundary.

The source remains 98.7788%, encoder 99.70266%, with all six other TU functions
at 100%. The full build passes and built/original DOL SHA-1 remains
`08e0bf20134dfcb260699671004527b2d6bb1a45`. Complete probes and verification are
in `docs/matching-evidence/jpeg-rgb/2026-09-06-row-boundaries/`.
The RGB claim was released after this checkpoint; active work returns to the
coefficient encoder's narrower register-ownership residual. The recorded RGB
creation-order and structural hypotheses remain available for a new source
lead rather than repeating these tested families.


## Resumed after encoder source100 — 2026-09-07

All PR3391 checks passed, including Clang and Nix. User authorized moving to
another remaining function. Claimed hsd_803B3408 as codex-c016: no competing
claim or RGB-specific open PR was found. This is the last residual in the
encoder TU once PR3391 lands. Upstream was merged as 5003f7bfea; conflict
resolution preserves the final encoder helper and upstream snapshot changes.

Four source probes adapt the encoder's caller-owned-temporary technique:
whole-body inline alone, caller-owned pixel_index, caller-owned luma_base,
and both. Scores are respectively90.599075,91.40553,90.599075,91.40553;
all retain instruction count but worsen instruction sequence. Merely moving
the luma pointer owner is neutral within this family. All are restored.
This is not evidence against a narrower inline boundary around just address
formation; that should be assessed against the known initial-lowering
reassociation before attempting further register-order variations.

Fresh restored RGB remains98.7788%; encoder remains100%. Evidence and complete
source/diffs are in 2026-09-07-caller-owners with verified SHA256 members.
Active target is RGB hsd_803B3408; there is no active scratch for this pass.


## Row parameter reuse and a combined structural candidate — 2026-09-07

30 new valid ordinary compiles: chroma caller ownership (8), row helper
parameter reuse (10), luminance offset/frame combinations (6), and row-return
ownership (6). All are preserved and restored; best retained remains98.7788%.
Whole-conversion caller-owned chroma_dest/chroma_index variants score
90.230415–90.71429 and do not repair the body.

A useful new structural candidate is row-frame/corrected-no-row.c (97.1659%).
Its helper computes `low += high; return tile + low;`, passing extracted low,
high, and tile terms. This produces the target low/high extraction order,
low+high followed by tile+sum operand ordering. The corrected chroma pixel
expression also retains high+row followed by low+result. Removing only the
luminance row_offset local recovers the target152-byte frame; removing both
row and column locals gives identical output. No padding is introduced.

The target additions are now present, but register allocation and scheduling
remain different. The helper result uses separate physical registers across
its two adds, whereas the target reuses one; do not call this a full structural
or register-only match. The luma li/addi order also remains wrong. Alternative
final-result locals/reused parameters do not improve the combined candidate;
some restore an unwanted160-byte frame or undo addition grouping.

A fresh supported retail backend trace of corrected-no-row completes exit0,
with105 GPR and48 FPR color decisions. All decision colors agree with their
node records. The pressure explorer successfully imports it in inventory mode.
However, first-definition, live intervals, and source attribution are still
unavailable, so it does not establish which new IG IDs belong to source
variables. Old pointer37/index38 target maps must not be reused without a
fresh PCode/source correspondence. No forced color or compiler override was
used. This candidate and trace give the next source/allocator reconstruction
a precise starting point, not a source100 verdict.

Evidence: docs/matching-evidence/jpeg-rgb/2026-09-07-row-reconstruction/.
Final ordinary verification: RGB98.7788%, coefficient encoder100%; full build
passes. Stay on RGB; no source improvement was pushed to the upstream PR.


## Row candidate disproved as a coloring-only target — 2026-09-07

Goal remains match hsd_803B3408, open PR, and link the TU. PR3391 was verified
merged as3e19efe8a885de8ca35d525d2c978aff5e580c1c. RGB remains claimed by
codex-c016; snapshot initializer work belongs to codex-d82d.

Fresh read-only stage capture through final scheduling completed for
row-frame/corrected-no-row.c. Same-address precolor/final PCode correspondence
was checked against ordinary assembly, with known0xd4/0xd8 and0x1f0/0x1f4
transpositions aligned. Unlike the older mapping,0xb4 is included.

The attempted target mapping contradicts itself at0xb0/0xb4: virtual74 must
be r22 for the low-bit extraction/input but r26 for the row-sum output/input.
Thus the row helper coalesces roles which the target keeps separate. The saved
correspondence explicitly has valid_complete_coloring_target:false and lists
all conflicts; its combined target_assignments must NOT be used as a proven
force-phys target. This supersedes treating the candidate as a register-only
frontier. Neither abstract renumbering nor register permutation alone can
solve its low/sum lifetime split.

13 valid ordinary follow-ups: output/local row-sum boundaries (5), and paired
source/destination-row helpers using pointers or struct return, raw/shared low
term, either assignment order (8). No improvement retained. out-update returns
the corrected-pixel98.04147% baseline including the reversed0xb4 operands;
local-update separates low/sum but also reverses0xb4. Paired pointer forms
score96.036865–96.77419%; struct forms add32frame bytes and10instructions.
Every variant is restored. No caller/coloring override or unsafe memory access
is used as matching proof.

Next source reconstruction must simultaneously preserve the completed row
sum and prevent its merge with the extraction value, while retaining tile+sum
operand order. The checked correspondence makes this a concrete precolor
constraint, rather than another physical-register declaration-order sweep.

Final restored RGB98.7788%, encoder100%; full build passes. Full stage/creation
capture, partial correspondence with contradictions, sources and diffs are
SHA256-verified in 2026-09-07-row-correspondence. No source100 or PR/link claim.


## Natural row lifetime extensions — 2026-09-07

30 valid ordinary source compiles, all restored:

- Sharing the low-row value with source-row calculation (s32/int/u32,
  scaled as4 or32, before/after destination row) gives94.60829–96.29032%.
  Keeping a meaningful later use does not preserve target instruction shape.
- Isolating only final tile+row_sum in an add helper (direct/result local,
  argument order, parameter mutation; full/no luminance row local) gives
  95.53917–97.1659%. Row-update converges to the previously rejected
  coalesced-low candidate; simpler return forms undo the complete-sum boundary.
- Scalar row represented as array[1] or single-field struct gives97.14286%
  on corrected-pixel source, with high extraction and sum sharing the same
  register and reversed final operands. Paired src/dst row records regress
  and add8frame bytes. Arrays are indexed only within declared bounds.

The node-set-split and coalesce-search CLI interfaces were audited. They use
single-color-per-IG or pair-coalescing targets; the rejected candidate has a
one-IG/two-target-color contradiction. Do not pretend either desired color
alone represents a complete valid target, or pass the conflicting map to a
force-phys scorer. No new compiler override was invoked.

This closes these specific row lifetime/helper/aggregate forms without a
retained percentage gain. A broader use/temporary ownership reconstruction
must be evaluated against the low/sum distinction and full instruction stream,
not scored as a simple register permutation. RGB remains98.7788%, coefficient
encoder100%, full build passes. Evidence is SHA256-verified under
2026-09-07-row-lifetime-source. Goal remains active; no PR/link yet.


## Front-end compound-assignment origin — 2026-09-07

A fresh unmodified-retail frontend dump of retained RGB completed with46
snapshots. In iro-00 (after BuildflowGraph), source `dst_row = tile + dst_row`
is already EADDASS93,88 (node94): the dst_row operand is marked assigned+used.
In iro-45 it remains EADDASS151,146 (node152). Thus operand reversal is not a
register-coloring or late scheduling artifact. The exact earliest parser/
pre-IRO rewrite pass has not been captured; do not claim which earlier pass
introduced it merely because it is present in the first snapshot.

The previously saved corrected-pixel creation trace independently shows final
row ADD at0x6507d4 emitted at0x4a0c87 by Operands_ForceGPR. Its same-item
combiner entry is already leftGPR40(row), rightGPR73(tile), caller0x4b8511.
All saved stages retain sum-first ordering. The frontend evidence explains why
spelling the source tile-first did not preserve that order.

27 ordinary probes, all restored: s64/u64 intermediate casts/locals (16),
single-field row-record return/output helpers (4), and casts/identity accessors
to disrupt ADDASS recognition (7). Wide variants retain one unwanted
instruction. Record return forms add instructions/frame bytes. Identity
helpers remain the corrected-pixel98.04147% baseline; result local adds8frame
bytes. int/u32 casts and unsigned identity change grouping and regress96.17512%.
No source improvement retained.

Donor search was refreshed using local semantic and hashed-window indexes.
Semantic index has44613functions; nearest results include THP quantization,
libm rem_pio2, and unrelated MP4 rendering functions. The inspected THP source
uses quantization-table scaling, not RGB565 tile conversion. Best hashed
window remains0.588. Web searches for GC/RGB565/HAL/JPEG arithmetic found no
verified source twin; ordinary JPEG color coefficients alone are not ancestry
proof. No external donor was transplanted.

Next useful reconstruction should avoid updating the same dst_row object:
consider computing the final destination row inside the destination-address
expression or accessor and letting invariant motion place it. This must be
measured against the preserved previous inline/address attempts, rather than
repeating known parentheses, declaration, or identity-helper variants.

Final RGB98.7788%, encoder100%, full build passes. Goal remains active. Full
frontend snapshots and27 candidate sources/results are SHA256-verified in
2026-09-07-addass-origin. No PR or Matching flag yet.


## Destination-address placement and row copies — 2026-09-07

22 valid ordinary probes, all restored. Moving final tile+row into the chroma
index or pointer expression, with inner row local/helper alternatives (8),
reaches at best97.14286%; sequential index accumulation is worse. Inner full
row expressions add8frame bytes. No retained address-placement gain.

Two-view row unions (8; same s32 type, u32, int, unsigned int; separate result
or update) do not provide a free materialization boundary. Same-type forms
add8frame bytes and regress; unlike-type views introduce memory operations
and2–4extra instructions. Both fields cover the same initialized32bits and
nonnegative row values; no out-of-bounds or uninitialized alias was scored.

Combined row helper with a preserved low copy or separate sum, using that
value in the source-row calculation (6; full or removed luma row_offset),
adds an instruction for explicit copy-first. Sum-separate changes grouping;
source-output-first converges to the rejected97.1659% low/sum-merged candidate.
Removing the luminance offset restores152bytes but does not repair its graph.

Final RGB98.7788%, encoder100%, full build passes. Goal remains active. Evidence
with complete source/diffs is SHA256-verified in2026-09-07-row-address-boundaries.
The tested local row/helper/union forms provide no retained gain; further work
should change the row-loop/data ownership reconstruction, or inspect a concrete
front-end rewrite condition, rather than re-run these equivalent forms.

## Whole-loop state and bounded permuter — 2026-09-07

The plain permuter completed 1415 iterations (89 compile errors) with four
workers and a 250-point baseline, without saving an improvement. Historical
output-250-1 already represented the retained 98.7788% source and must not be
counted as a new result. The run was interrupted cleanly; no worker remains.
Installed bootstrap failed to extract this Linkable TU (issue1540); branch-local
CLI bootstrap succeeded. No backend patches or forced scheduling were used.

Eight new source probes grouped loop state in an ordinary local struct:
all counters, all scalar state including pixel, tile/chroma counters, or luma
state/offsets; each tested with baseline and corrected pixel-address grouping.
These substantially alter optimization (36.25–61.41%) and frame layout. None
was retained. They do not resolve the row-sum materialization boundary.

Retained RGB98.7788%, encoder100%, full build passes. Complete source/results
and permuter log are SHA256-verified in2026-09-07-loop-state-permuter. No new
upstream PR or Matching flag. The active goal remains unfinished; a useful next
step needs a concrete new row-expression/ownership hypothesis or a trace of the
pre-IRO compound-assignment rewrite, rather than repeating scalar spellings.

## Entry AST separates commutation from ADDASS — 2026-09-07

Read-only retail CodeGen entry capture at0x4351c0 completes85 statements for
hsd_803B3408. First parameter (esp+4) is the statement list, second parameter
identifies the function. The source's second dst_row assignment is already
EASS(dst_row,EADD(dst_row,tile)) here: the addition operands have reversed,
but the node is still EASS, not EADDASS. The earlier first-IRO snapshot shows
EADDASS. Thus operand commutation precedes compound-assignment conversion;
merely suppressing the latter is not sufficient. Next static/live inquiry
should follow the AST construction/normalization before CodeGen entry.

The initial reader failed: GC/1.2.5n NODE_NAMES was empty and _patch_elabel
masked the decoding exception as an ELABEL with no type. Reported issue1541.
The valid diagnostic initializes75 node names from the exact retail PE table
at0x55268c, located via EADDASS string/pointer xrefs. Source line numbers,
constants, object names and surrounding assignments agree with current source.
The rejected partial AST is not evidence. No compiler/source state was mutated.
Ghidra setup validated the compiler hash and3248-function project before audit.

Complete valid AST, hook, extracted node names and CodeGen decompilation are
SHA256-verified in2026-09-07-entry-ast. Production source remains unchanged at
RGB98.7788%, encoder100%; goal still requires100%, new PR, and TU linking.

## Exact arithmetic-builder complexity swap — 2026-09-07

Read-only AST captures at0x50ee60 and0x47b3f0 both already contain the reversed
EADD, ruling out their subsequent passes. Static audit of the exact retail PE
follows addition builder0x4fa620 to constructor0x473e30 and reorder0x4fb470.
Constructor byte+1 is a Sethi-Ullman-style expression-complexity value: max of
unequal child values, or equal value+1 (capped200). For ordinary integer nodes,
reorder swaps children when left complexity exceeds right, with constant/type
special cases. This is not merely source assignment canonicalization.

Live read-only entry/return capture at0x4fb470 for the target row expression
confirms exact pointer exchange: node0x644784 has left0x644724 (tile expression,
complexity3), right0x644764 (dst_row,complexity1), then left/right reverse. The
before/after expression trees agree. This identifies the exact early reversal
site rather than inferring it from IRO snapshots.

Four ordinary corrected-pixel candidates introduce an explicit tile_offset
local at row or tile scope, with dst_row self-update or separate row_sum.
Three score96.17512%,frame152; row-scope separate sum95.95392%,frame160. None
retained. Equalizing parsed operand complexity is insufficient on its own:
later optimization and materialization still need to match the target graph.
Do not repeat these simple tile-local forms or rely on patched operand order
as production evidence. Next source work should combine this measured ordering
rule with a coherent row-sum ownership boundary, not blind parenthesis sweeps.

Evidence and four full source/diff candidates are SHA256-verified in
2026-09-07-expression-complexity. Source restored; no PR delta or Matching flag.

## Direct row-call structural candidate — 2026-09-07

NEW NEXT STARTING POINT: docs/matching-evidence/jpeg-rgb/2026-09-07-direct-row-call/structural-candidate.c.txt
(full TU,98.04147%,152-byte frame). It uses an inline row-sum helper with a named
sum result, then `dst_row = tile_offset + jpeg_row_sum(chroma_y)` and corrected
pixel addressing. Removing the luma row_offset local recovers the helper's
8-byte reservation. Unlike the old97.1659% helper, this preserves both the
correct row operand order and distinct virtuals for extraction and sum.

Read-only retail PCode: at0xa8 low=83, at0xac high=84;0xb0 ADD74,83,84;
0xb4 ADD40,67,74. Target requires74:r26 (currentr5), while40 alreadyr26.
The graph has no74–40 interference; sharingr26 is legal.74 is simplified at
index86 and40 at21;74 currently takes available volatiler5. This is a separate
short-lived result, NOT the old merged-low contradiction.

Same-address precolor/final correspondence checks267 GPR operands,82virtuals,
with NO contradictory target assignments.217 instruction shapes align after
the known0xd4/d8 and0x1f0/f4 scheduling swaps. Skipped implicit/rewritten nodes
are explicitly listed; this is not a complete binary match or proof that every
allocator target is feasible. Desired changed colors:
74:26,38:21,101:22,102:22,98:22,99:22,95:23,96:23,37:22.
Do not reuse this map on another candidate without renewed correspondence.

Lifetime-pressure was run on the fresh backend trace. It has no reliable first
def/live intervals/source attribution and flags incomplete allocator state for74.
Other reported holders describe final interfering colors, not necessarily the
causal first SELECT blocker (known limitation). Use full captured before/after
coloring snapshots for order/coalescing analysis; avoid source suggestions that
pretend to have attribution.

Eight direct helper forms and four tile-parameter helper forms tested. Direct
return expression yields96.17512%; named helper result/full frame97.820274%;
no-row offset98.04147%. Moving tile addition inside helper scores95.53917–
97.14286%, no improvement. Original production baseline remains98.7788%.
The new candidate is retained separately for allocation work, not submitted as
a percentage improvement. All evidence, sources, full retail stages and backend
trace are SHA256-verified in2026-09-07-direct-row-call.

Normal frontend IRO dump consumed CPU for90+seconds without a trace; stopped
only that emulator, reported issue1542. Read-only hooks/full backend still work.

## Helper result ownership probes — 2026-09-07

16 ordinary source variants, all restored. Starting from the coherent direct
row-call candidate, explicit assignment of the helper result to dst_row followed
by tile addition is instruction-identical to the direct expression, including
sumr5 and finalr26. u32/int/unsigned-int casts at that caller boundary are also
neutral; identity/accessor helpers add8frame bytes (six probes total).

Void output helpers, direct or named-local sum and both parameter orders (four
probes), remove8frame bytes but do not merge the sum/final row allocation.
Named-local output gives97.820274%,frame144; direct output95.95392%,frame144.

Tile-parameter helper updating sum through u32/int/unsigned-int, with reversed
argument order too (six probes), gives97.58064%,frame152. Its row ADD order is
correct but the surrounding allocation changes substantially: chroma_y takes
r26, lowr6, highr5, sumr5, finalr6. No improvement over the preserved coherent
98.04147% candidate. Do not re-run these equivalent caller assignment/cast/
output-parameter spellings. The mismatch DB also rules out register-keyword-only
allocation probes for this compiler configuration; none were wasted here.

Evidence is SHA256-verified in2026-09-07-helper-ownership. Production remains
98.7788%; the direct-row-call candidate remains the next structural starting
point. Exact matching, a new source-improvement PR and TU linking remain open.

## Fixed-graph SELECT-order obstruction — 2026-09-07

For direct-row-call virtual74, EVERY virtual neighbor is covered by the derived
target map. None has target physicalr5. The fixed neighbors are1,3. Consequently
r5 remains unblocked for74 under ANY selection order consistent with these
final target colors. The verified lowest-available SELECT rule cannot select
r26 while r5 is available. This is stronger than merely observing different
simplify indices: declaration/order-only searches on this exact graph cannot
solve74. A real graph/lifetime/coalescing change is required. It does not show
which source transformation will cause that change. Complete neighbor ledger
and target mappings are archived in2026-09-07-row-order-obstruction.

Five new helper-result lifetime placements move tile+row into the chroma loop:
combined index, sequential accumulation, pointer expression, inner local and
inner local update. Scores93.36405–96.9447%,frames152/160, all restored. The
inner-update generator initially put a statement before a declaration; corrected
that C89 ordering and compiled the corrected candidate. No invalid compile is
counted as matching evidence. No retained source gain. These loop-placement
spellings do not supply the required lifetime extension/coalescing.

The next source work should alter ownership across a larger helper/loop boundary
or inspect where the return-result copy disappears. Avoid pure SELECT-order
search and re-running the now exhausted direct/cast/output/inner-row variants.

## Full chroma-row boundary and missing return copy — 2026-09-07

The coherent candidate's INITIAL backend snapshot already has ADD74,83,84 then
ADD40,41,74. Optimized/forward snapshots only replace tile virtual41 with67.
No MR/return copy involving74 exists at any captured backend stage, so backend
copy elimination is not the missing lever. Any separation/copy propagation that
matters happened during frontend inlining/lowering, before initial PCode.

Eight broader source reconstructions were measured and restored. A helper owns
row-sum/src-row calculations AND the four-pixel chroma loop, unlike the earlier
whole-loop helper that received already computed row offsets. Four ownership
variants keep pixel and/or chroma_x in the caller via pointers or helper locals;
scores94.548386–95.92166%,frame152/160. Four follow-ups pass chroma_y by pointer,
optionally tile_offset too, to preserve caller counter ownership. They score
94.548386/95.70046%,frame160. They do not recover the required row register and
add frame cost. Do not repeat this full-row helper family on this baseline.

Sources/diffs and compact stage lineage are SHA256-verified in
2026-09-07-full-row-helper. Production remains98.7788%; the direct-row-call
structural candidate remains preserved separately. Goal remains active.

## Row-input normalization donor check — 2026-09-07

Refreshed upstream/PR3350 discussion: no new RGB delta or review clue; the only
new upstream commit is snapshot initializer work (#3395). PR3376 is a DIFFERENT
JPEG decoder function, not an RGB donor. Checked recent mismatch patterns:
inline-count-mask-survivor-regalloc (mnNameNew_GlyphVariantSetup), output-inline
expression allocation, and single-return FPR coalescing. The count example
establishes that narrow/masked inline inputs can change surviving virtuals.

Tested that concrete mechanism on the row helper (input is0–3): u16/u8 formal
is neutral98.04147%; s16/s8 regresses97.53456%; int/unsigned-int and s32 explicit
mask add8frame bytes and score95.95392%; u16 masked gives97.90323%,frame152.
Then tested assigning row expression back into the formal input before return:
s32/u32 reproduce the structural candidate; u16/u8 give97.4424%,frame152.
Restoring named luma row_offset adds8frame bytes and worsens these candidates.
16 valid sources total, all restored, complete evidence SHA256-verified in
2026-09-07-row-input-normalization. This donor mechanism gives no improvement
here; do not repeat these input-width/mask/assignment-return variants.

Production remains98.7788%, no unsubmitted source gain. Goal remains active.

## Chroma condition and shared destination storage — 2026-09-07

14 ordinary candidates on retained baseline and direct-row structural candidate.
Moving chroma_index and/or destination pointer setup into the for-condition
(comma assignments, analogous to existing luma loop) regresses87.39–90.82%.
Only local arithmetic/pointer formation runs at the terminating condition; no
extra pixel load/store. These are valid but clearly wrong loop shapes.

Sharing destination storage across chroma/luma while keeping their original
address expressions is DISTINCT from the earlier common JpegWork-pointer probe
that rewrote luma addressing. A union of JpegWork*/s32* (each field read only
after writing that same field) gives96.96% baseline,96.76% structural. A single
void* with explicit casts for accesses gives98.27189% baseline,97.39632%
structural,frame152. Tile-y scope is neutral to function scope; tile-x scope
improves to98.59447% baseline/97.88019% structural. Still below retained score.
These pointer-storage forms change allocation but provide no retained gain.

Complete source/diffs SHA256-verified in2026-09-07-chroma-pointer-lifetime.
Source restored; production98.7788%, goal remains active with no new PR delta.

## Windows diagnostics recovered for structural candidate — 2026-09-07

The remote Windows path is AVAILABLE. `debug dump remote` streamed the coherent
candidate from build/verification/hsd3408/direct-row-call.c using --unit-source
src/sysdolphin/baselib/hsd_3B34.c. It created the branch-specific remote worktree,
compiled successfully in0.583s, emitted2036217bytes, restored staged source and
stock DLL. SHA2565e405f9532537bc57802811d4c907029d3582e833cb2e5034c876272ab0d39ab
matches the local candidate. Direct /tmp source is rejected by repo containment;
staging an ignored build/verification copy is the supported path.

Compared the remote dump against the EXISTING retail trace for this exact
candidate:60equal,208retail-only,0different. This is agreement for comparable
facts, not complete parity or matching proof. Local DLL lane remains unsafe:
old PID95126 stillUEs; no override/bypass attempted.

`debug suggest coalesce -V74=40` on fresh remote dump reports no direct copy/
identity edge and lacks detailed colorgraph decision nodes74/40. Forced merge
is correctly rejected. Issue1545 records the remote diagnostic metadata gap.
`coalesce-search --no-compile-probes` can read interference/IR and emits generic
local-order/type/pointer-loop probes, but no scored/specific coalescing fix.
Do not apply linear end-pointer/induction advice to this tiled, nonuniform
address mapping without proving semantic equivalence. No generated probe or
forced allocator mutation was run. Full outputs SHA256-verified in
2026-09-07-remote-frontier. Production untouched98.7788%; goal remains active.

## Final-add-only output and guarded helpers — 2026-09-07

11 ordinary variants, all restored. Unlike earlier output helpers computing the
row sum, a final-add-only void helper receives tile expression and &dst_row,
updating *row = tile + *row. Parameter ordering, a u32 read cast, and named tile
local all converge:96.65899% baseline pixel grouping,96.17512% corrected,
frame152. They add tile to high-row before low-row, the rejected grouping.

Null-check, early-return null-check, and conditional value-return forms around
that helper regress85.97696–86.82949%,frame152. Although the caller supplies a
valid local address, these guarded forms do not preserve the required generated
code. No reason to pursue this guard timing family further.

Complete source/diffs SHA256-verified in2026-09-07-final-row-output. Production
restored98.7788%, no new PR delta; direct-row-call structural candidate remains
separately preserved. Goal remains active.

## Row pointer update and final pointer-return boundaries — 2026-09-07

Eight ordinary compiler probes, all restored. Build the row destination pointer
from buffer+row sum first, then update it by tile offset, and index columns from
that pointer. Byte and word forms, direct row expression or named sum, converge
to88.24424%/88.02765%,frame152/160. The byte form keeps arithmetic within the
work object's byte representation; word reinterpretation is diagnostic only,
not a newly established array-layout contract. Neither is a source candidate.

Separately, keep scalar dst_row but pass &dst_row to a const-pointer input helper
that RETURNS tile+*row, with direct or named result and luma offset local variants.
Scores95.53917–95.76037%,frame152/160. Unlike the earlier output-only/guarded
helpers this has no null test or destination write inside the helper, but still
fails to preserve target code. No pointer boundary gain.

Complete sources/diffs SHA256-verified in2026-09-07-row-pointer-boundaries.
Production restored98.7788%, build passes. Goal remains active, no PR delta.

## Offline merge model and physical-sharing recheck — 2026-09-07

Exact simplify+SELECT replay reproduces106/106 decisions for the coherent direct
row-call candidate (this candidate has106 active GPR webs). OFFLINE hypothetical
merge74->40 unions root neighbors and leaves the alias as a permanent blocker.
It gives rowr26 but leaves8other mapped target mismatches. Reverse40->74 gives
rowr5 and23mismatches. This is a graph model only, NOT an actual compiler merge
or source-realizability proof. It confirms row repair alone is insufficient.

Revisited prior combined inner-loop tile+row placement with the remaining luma
column_offset local removed:97.1659%,frame152,217instructions. Fresh retail
stages and267-operand/82-virtual correspondence have no contradictions, but
row sum74 and final row73 are DISTINCT virtuals that happen to getr5. This is
not a merged lifetime.74's target-colored neighbors again include no r5;
selection-order-only repair remains impossible for it. Do not confuse this
candidate with the old97.1659% low/sum-merged contradictory helper: equal
fuzzy scores do not imply equivalent virtual graphs.

Complete model, source, diffs and fresh stages SHA256-verified in
2026-09-07-row-merge-model. Source restored98.7788%, build passes. Goal active.

## Row loop condition and update boundaries — 2026-09-07

Twelve probes move dst_row, src_row, or both to the chroma_y loop condition,
or to its initializer/update expression. Tested against production and the
coherent direct-row-call structural candidate. Unlike the earlier chroma_x
condition experiments, these change the row calculation lifetime boundary.
Only bounded local arithmetic executes for the terminating chroma_y=4; no
pixel access or output store is added there.

Condition results (dst/src/both): production92.90323/93.940094/91.63595;
structural92.53456/92.58986/90.89862. Initializer/update results:
production94.28571/92.68664/88.354836;
structural93.09677/91.64056/87.39632. Frames152–168; no gain. All
sources and complete diffs retained in2026-09-07-row-loop-boundaries.
Production source restored. These loop boundaries are not a productive way
to obtain the needed row lifetime merge. Matching remains unfinished.

## Chroma/luma sequential local reuse — 2026-09-07

24 probes share s32 locals between nonoverlapping chroma/luma phases. No
uninitialized reads, cross-store pixel reuse, or compiler forcing. Twelve
counter/index probes against baseline and coherent structural candidate reuse
chroma_x as luma_x, chroma_y as luma_y, chroma_index as pixel_index/luma_y,
dst_row as luma_y, or src_row as luma_x. No gain; baseline98.110596–98.7788,
structural97.39632–98.04147; all frame152.

Twelve offset probes reuse dst_row/src_row/chroma_index for row_offset or
column_offset, hoisting the shared declaration to function scope. Baseline
frames shrink to144 and scores98.18894–98.5576. Structural variants start with
both named luma offsets restored, so reuse recovers152 without padding; scores
97.67281–98.04147. Reusing chroma_index yields assembly exactly identical to
the preserved direct-row-call candidate (current_asm equality checked), so
that alternative local/frame explanation does not change the row allocator
problem. No productive sequential local-sharing lever found in these pairs.

Full sources and diffs saved in2026-09-07-phase-local-reuse. Production source
restored; ninja passes. Best remains98.7788%; no upstream PR delta.

## Common scaled tiled-offset helper — 2026-09-07

Nine reconstruction probes factor (i&1)*low_stride+(i&2)*high_stride into one
inline helper, called for destination/source rows, optionally luma addresses,
and optionally both chroma column calculations. Both chroma pixel loads remain.
This is broader than the earlier row-plus-column helper: one scaled bit-offset
abstraction serves multiple source/destination address domains.

Helper bodies use direct return, named sum, or named low/high terms. Scores
95.07834–96.48387; frames152–232. Direct-return rows+luma is the only152-frame
variant,96.059906. Inspection shows high-row+tile followed by low-row+result,
not the target low+high then tile+sum, and row counter r26 rather than r7.
Thus its frame recovery does not hide a useful structural row improvement.
Named-local forms create more stack homes without solving the whole function.
No common-helper candidate retained. Full sources/diffs in
2026-09-07-common-tiled-offset; production restored.

## Delayed simplification diagnostic — 2026-09-07

Tool/history audit found no new upstream RGB donor; latest merged PR still3395.
Remote metadata issue1545 remains open. Source-model-synthesis is specialized
around profiled functions/meta-ceiling artifacts, not a ready generic RGB solver.

Six DIAGNOSTIC algebraic probes test whether a more complex RHS can survive
frontend ordering, simplify later, and retain the row's shared lifetime. These
are not suggested maintainable source, and none was retained. All operands
are bounded row/tile counters or row offsets, so cancellations do not rely on
signed overflow. Corrected pixel grouping used throughout.

row+chroma_y-chroma_y:98.04147%,152frame, retains reversed r26+r8 row ADD.
row+tile-tile, row-tile+tile, row+low-low, and row+rowsum-rowsum all96.17512%,
152frame: they regroup high+tile then low+result, losing target grouping.
row^tile^tile:97.11981%,152frame, preserves tile+sum ordering but keeps TWO
XOR instructions and a separate sumr5/finalr26. No late simplification path
in these probes yields both target operand order and shared row lifetime.
Full sources/diffs retained in2026-09-07-late-simplification; source restored.

## DONOR BREAKTHROUGH: row ADDs solved — 2026-09-07

Operand-constrained opseq `add v0 v1 v2,add v0 v3 v0` found matched integer
example hsd_803921B8. Fresh ordinary checkdiff confirms100%. Its source uses
`cur_dst = dst + (s32)((u32)y*(u32)stride) + x2`, producing product+x2 followed
by dst+sum in one register. Exact four-op RGB extract/extract/add/add query
had no matched donor. Pointer examples and pl_800386E8 also appeared, but this
integer donor directly informed the change.

18 probes (8 donor casts/part/tile placement;10 grouping/two-local followups).
Key form: declare tile_offset=tile_y*16+tile_x*2 at tile_x body, row_part local
inside chroma_y body, then row_part=(chroma_y&1)*4;
dst_row=tile_offset+row_part+(chroma_y&2)*16. No row helper or padding.
BOTH target row adds now match EXACTLY: +b0 ADD r26,r22,r5 and +b4 ADD r26,r8,r26.
Keep the source's left association: parenthesizing the row sum regresses.

Production with existing pixel expression improves98.7788 ->98.82488,
868bytes/frame152. Commit6c579233b8, fresh upstream PR3396 via commit0cdb5236b9.
All seven other TU functions100%; python configure.py && ninja passes.
TU remains Linkable because RGB is not100%; do not link prematurely.

Separately preserved corrected-pixel candidate:98.087555%,217instructions,
frame152, both row adds exact. Fresh readonly retail stages plus correspondence
validate267 GPR operands/81virtuals, NO target contradictions, after known
d4/d8 and1f0/1f4 scheduler transpositions. Usual implicit/prologue skipped sites
listed in correspondence JSON; this is not full binary equality. Remaining
changed virtuals (CANDIDATE-SPECIFIC):38:23->21,100/101/97/98:21->22,
94/95:22->23,37:30->22. Old direct-row-call virtual74 fixed-graph obstruction
no longer applies to this source! Do not recycle its IDs or its impossibility
conclusion. New active structural candidate is structural-candidate.c.txt here.

Complete donors/probes/fresh traces under2026-09-07-donor-row-breakthrough.
The row blocker is resolved; next work is chroma allocation and scheduling.

## Chroma SELECT frontier after row breakthrough — 2026-09-07

Fresh full retail backend capture of the corrected-pixel structural candidate
succeeds. Supported lifetime-pressure with its eight changed target virtuals
runs on this trace; attribution remains low confidence/unattributed, with
freshness unknown. Its final-color holder lists are not causal SELECT timing
proof. Use the exact fresh snapshots for order analysis.

All neighbors of the eight changed virtuals are target-mapped; no target-color
interference contradictions.105-web simplify+SELECT replay matches the capture.
OFFLINE order search: moving38 alone to positions40–47 reduces8target misses to1.
Moving38 to39 and37 to55 (and several nearby positions) yields ZERO mapped target
misses on the unchanged graph. This is a SELECT-order hypothesis, not an actual
compiler or source result; unmodeled scheduler/implicit operands still require
ordinary verification. Critically, unlike the old row-helper graph, current
chroma target colors ARE reachable by ordering alone.

19 ordinary source probes:11 index/destination type/scope/expression changes,
8 index-inline caller/local/frame variants. Scalar int/u32 types, pointer view
casts, and most scopes retain98.087555; direct pointer expression97.258064,
function-scope pointer97.39632. Index helper variants95.7235–95.935486,frames152–168.
No new source gain. These test the NEW row-fixed candidate; do not count earlier
old-row failures as equivalent graph evidence. No forced compiler mutation.

Production restored98.82488. All PR3396 checks now pass (deploy/wiki jobs skipped).
Full traces/replay/probes in2026-09-07-chroma-select-frontier. Goal remains active.

## Direct chroma addresses and correspondence check — 2026-09-07

19 probes on the row-fixed source:6 destination byte-offset/index reuse forms,
12 direct column-sum permutations with/without named destination pointer, and
one best-form baseline pixel-expression recheck. Byte-offset locals97.036865,
frame160; reuse-index97.258064/frame152. Direct forms94.73733–98.156685/frame152.
No production gain beyond98.82488.

Fresh capture of prior dest-expression97.258064 validates267GPRoperands/81virtuals
without contradictions after BOTH known scheduler transpositions.19changed
assignments instead of the named-pointer candidate's8: removing the pointer
alone broadly perturbs the row/tile graph, not just its own SELECT slot.

Direct row+low+high address expression98.156685 eliminates chroma scheduling
transposition; normalized instructions differ only at luma1f0/1f4. However a
fresh retail correspondence (only luma transposition aligned) exposes exact
operand contradictions at104: virtual38 would need r26 AND r21; virtual100
would need r21 AND r26. This is the destination-index ADD's commuted operands,
not a consistent pure-coloring target. Do not promote it as allocator-only just
because opcode-normalized diff has only2lines. Baseline/corrected pixel versions
score equally98.156685 but raw current_asm lists differ; equal score is not
byte-identity proof. Preserve the earlier coherent donor structural candidate
as primary. No forced changes; source restored and all evidence archived in
2026-09-07-direct-chroma-addresses.

## Simplify-input rank frontier — 2026-09-07

Current coherent row-fixed graph: pointer37 and index38 both flags2, same as
conversion temporaries; flag2 is NOT a named-local discriminator. Object pointer
is populated for37/38 and zero for conversion temps. Initial neighbor counts
pointer31/index28, before captured removals; captured degree4/3 are final state.
Do not confuse them with initial simplify degrees.

Exact105-web baseline replay verified again. Prior arbitrary SELECT-order
success alone did not show how SIMPLIFY could produce it. New offline tests
vary its scan ranks while preserving graph edges and costs. Coarse49rank pairs
best1miss. Degree-only81pairs(-4..4) best8misses. Joint rank-index/abstract pointer
degree tests reach0misses with degree delta-3 and index rank101.5+, but that is
an abstract degree hypothesis, not an actual edge or source transformation.

More useful: fine5450pair rank-only grid reaches ZERO mapped target misses with
pointer37 rank103.5 and index38 rank101.5 (several adjacent pairs work). Graph,
color pools, costs and degree rules unchanged. Both virtuals need creation/rank
positions among conversion temporaries, not just reversed local declarations.
This is still OFFLINE, no compiler forcing or source-realizability proof. It
strengthens the target beyond arbitrary SELECT replay: ordinary recovered
simplify+SELECT itself can yield these target colors with changed scan ranks.

Eight low-first/direct chroma-index source forms with arithmetic before/after
first pixel load score97.97235–98.087555,frame152, no production gain. Both loads
preserved. Full models/probes in2026-09-07-simplify-rank-frontier. Production
restored98.82488. Next source question: how to make both index and destination
compiler temporaries created near color-conversion lowering, while preserving
exact ADD operand order and both source loads.

## Chroma store evaluation boundaries — 2026-09-07

14 probes target late temporary creation at the Cb store. Six embedded pointer/
last-index/all-index assignment forms use LHS or RHS-comma boundaries. LHS forms
98.087555/frame152; pointer RHS97.036865/frame160; other RHS90.03226/frame160.
RHS probes use an independently formed LHS address to avoid an unsequenced read
of the pointer assigned on the RHS. Both pixel loads remain; no alias assumption.

Eight inline store helper forms pass color value and offset in both argument
orders, with named/direct index and full/removed luma row local. Named-index
97.258064, direct-index95.96774; allframe152. Filtered full instruction rows of
value-first/local/full helper equal the prior direct-destination variant exactly.
Embedded-pointer LHS instruction rows equal the coherent donor seed exactly.
This is final instruction-output equivalence, not a claim of identical virtual
IDs. These evaluation boundaries add no new codegen behavior to pursue.

Production restored98.82488; complete sources/diffs archived in
2026-09-07-chroma-store-boundaries. PR3396 is now MERGED upstream. No further
source gain; full matching and TU linking remain unfinished.

## Chroma scalar-record promotion — 2026-09-07

18 probes:8 local records for index/destination/both and field/scope order;
4 luma-row-home followups;6 variants compute Cb in a local before first record
index assignment, with full/removed luma offsets. Both pixel loads and the
Cb-store/second-read ordering remain preserved. No production gain.

Index-only record with luma row local removed gives98.087555/frame152 and exact
instruction-row equality to the coherent scalar seed. Fresh readonly trace,
267 GPR operands/81 mapped virtuals, no contradictions: index moves38->73,
pointer stays37; same eight physical mismatches. Thus scalar record promotion
DOES change index numbering, but not enough to reach the successful rank range.

Cb-value-before-record source does not postpone that promotion. Fresh second
trace on index/no-luma-offsets again gives index73, pointer37 and the SAME eight
mapped mismatches. The specific hypothesis that first field access following
FP conversion would create index near conversion virtuals100+ is falsified by
this source pair. Do not continue shuffling these statement boundaries on that
assumption. Named Cb is optimized away; full variants reserve160/168 frames.
Destination/both record variants96.76037–96.98157 and add homes; neither field
order nor pixel/row scope helps. Full sources/diffs and both captured stages
archived in2026-09-07-chroma-records. Production restored98.82488.

## Store-return ownership and direct-index cast boundaries — 2026-09-07

17 probes, all restored. Eight Cb helper forms store a converted value then
RETURN the computed JpegWork pointer for Cr: value/offset parameter order,
named/direct column index, full/removed luma offset locals. Named-index96.76037,
direct94.70968; frames168/full and160/reduced. Unlike prior void store helpers,
these explicitly return pointer ownership; no useful later-temporary source
or production gain results. Both source pixel loads preserved around Cb store.

Nine int/u32/unsigned-int casts at row, column-bit sum, or row+low boundaries
in the direct-address98.156685 candidate. Row and row+low casts remain98.156685;
bit-sum casts95.96774. Frame152 throughout. Checked +104 in int-row, u32-row,
and unsigned-int-sum: still `add r6,r29,r6`, retaining the row-first operands
that conflict with target `add r21,r21,r26`. These casts do not repair the
candidate's known operand-order contradiction. Full sources/diffs under
2026-09-07-store-return-and-index-casts. Production restored98.82488.

## Luma loop forms after row fix — 2026-09-07

Ten valid probes: while-condition, do/base-before, do/base-inside,
for-initializer-base and for-body-base on production and coherent row-fixed
sources. The initial do/body generator put a declaration after a statement,
failed to compile, and was corrected with an inner C declaration block; invalid
output was never interpreted as a score. Archived sources/results are corrected.

While-condition neutral98.82488/98.087555,frame152. Do/base-before85.129036/
84.13825,frame152; do/base-inside84.91705/83.92627,frame160. For-initializer and
for-body98.48848/97.75115,frame160. These are loop structure effects, not a
new numerical improvement. All four for-based moved-base outputs still show
+1f0 addi r5,r21,280 followed by +1f4 li r26,0: the unwanted scheduling order
is preserved. Moving luma setup around these source loop boundaries is not a
repair of that residual. Source restored98.82488; archive in
2026-09-07-luma-loop-forms. Goal remains active.

## RGB channel inline boundaries on row-fixed source — 2026-09-07

Eight probes factor per-channel RGB565 extraction into separate inline helpers:
u16/s32 input, s32/f32 result, chroma-only/all including luma. Coefficients and
expression association unchanged; both source reads remain around Cb store.
Every variant97.866356%; frames176(chroma) or192(all), up from152. After excluding
stack-reference/prologue/epilogue instructions, complete instruction text and
register operands equal the coherent scalar seed for ALL eight variants. This
is a scoped non-stack comparison, not full object equivalence or proof that
virtual IDs are identical. No needed physical-allocation change was obtained;
helper homes account for the visible stack growth. No source retained.
Full sources/diffs in2026-09-07-channel-inline; production restored98.82488.

## Named column-term donor transfer — 2026-09-07

16 probes transfer the successful named-row-term idea to the direct-address
candidate's destination index. Twelve name either low or high column part,
then permute the three sum terms at both chroma stores; four row-first forms
remove the named luma row offset to recover frame152. Other full variants
frame160. No source/pixel load is removed and row fix remains intact.

Best direct-address variant low-row-low-high reaches98.22581/frame152, above
that family's previous98.156685 but below production98.82488. All four
frame-restored row-first forms still emit +104 `add r6,r29,r6`, retaining the
known row-first operand contradiction against target `add r21,r21,r26`.
The source-term donor is therefore not a complete transfer of the row fix:
it slightly changes allocation but leaves the destination ADD wrong. Do not
promote its percentage as a pure-register frontier. Complete sources/diffs in
2026-09-07-column-term-donor. Production restored98.82488.

## Automated order-search route audit — 2026-09-07

Inspected current simplify-order/select-order-search CLI and implementation.
Both accept pcdump baselines; neither exposes a retail backend-trace runner.
Source candidate compilation in mwcc_debug/diff_capture.py invokes `debug dump
local`. Revalidated actual local process95126:UEs,elapsed9h50m. The guarded local
runner must not be bypassed. Healthy retail backend/snapshot lane remains usable;
this limits one automation route, not all progress on the match.

Filed shared feature1549 with reusable runner/artifact-adapter requirements and
ordinary checkdiff stop/validation criteria. Separate remote metadata issue1545
remains relevant. Also found existing open1446/1288: select-order search can
report false physical-target hits after virtual IDs change.1446's concrete
example compares baseline pointer91 with candidate index91 while pointer moved92,
and actual match regresses. This is directly relevant to our deliberate rank/
numbering hypothesis. A future automated rank search must derive fresh operand/
virtual correspondence for each candidate; never reuse target37/38 blindly.

No candidate compiler was launched through the unsafe route and no source was
changed. Existing manual retail correspondence path still works. Production
remains98.82488; PR3396 merged; exact match and TU linking remain unfinished.

## Direct typed chroma arrays — 2026-09-07

Six source forms directly index JpegWork.data.x518/x618 at the actual work
object base, instead of indexing field[0] through a shifted work pointer.
Named column index, direct column-first sum, or direct row-first sum; direct
base expression or function-local JpegWork pointer. Indices stay within the
64-element chroma arrays, and both pixel reads remain around Cb store.

Scores97.258064/95.96774/98.156685 respectively,frame152; local base pointer
neutral. Full instruction-row comparison confirms the three direct-base forms
are exactly equal to their prior shifted-pointer/direct-destination counterparts.
This is scoped instruction-output equivalence excluding relocation-only rows,
not a statement about hidden virtual identity. No new lowering/allocation
behavior or production gain. Sources/diffs in2026-09-07-typed-chroma-arrays;
production restored98.82488.

## Parameter storage reuse — 2026-09-07

Nine row-fixed source probes reuse unused height for chroma_index,row_part,
dst_row,chroma_y,chroma_x,pixel_index, or reuse x/y/width for chroma_index AFTER
their original values have been consumed by image_offset/stride. Every new
working value is assigned before read. Function signature and alias-sensitive
store/load ordering unchanged; no incoming height value becomes observable.

Index reuse through any of four parameters and row_part through height retain
98.087555/frame152, with exact full instruction-row equality to coherent seed.
Other height reuse regresses97.88019(dst_row),97.64977(chroma_y),96.56682(chroma_x),
97.46544(pixel_index), allframe152. Thus parameter object classification does
not give the desired index allocation order in these cases. No source retained.
Full sources/diffs in2026-09-07-parameter-storage; production restored98.82488.

## Windows diagnostic recovery and simplify IDs — 2026-09-07

The Windows host is healthy. Its installed DLL was obsolete (13554 bytes,
SHA256 95dd139c92403370363344201445b47cd7257f2c78bd637090d188a7573a9c37),
with no feature manifest or coalescing event strings. Deployed current runner
and DLL in a separate owned directory, leaving the installed originals alone:
C:\Users\mikes\code\mwcc_debug\codex-c016-v6-20260907.
Use debug dump remote with --remote-script pointing to run_pcdump.ps1 there.
Staged coherent donor source SHA256:
3d4b97bfd5971eed8ab120a1392dee0e78a984e778b3acff69a70c6fb641c7d9.

The fresh v6 DLL exposes coalescing and colorgraph, but simplify IDs above37
were -1. Root cause: hook_simplifygraph scans only N_IGNODES (38 here, a
block count), although the class contains139 virtuals. Read node->ig_idx
as the colorgraph hook already does. Also correct simplify SPILLED annotation
to IG_FLAG_SPILLED instead of coalesce-root bit0x08. These are logging-only
changes. Built successfully with build_macos.sh and ran the isolated Windows
runner: compile exit0,0.457seconds; staged source and stock DLL restored.
Repaired DLL SHA256:
ee9c5d22ba10bc9473f94ec3b63ac95b756e976df6d55e357d3c17f593ec8a8a.

Verification against existing full retail donor backend:765 equal,0 different,
66 retail-only nodes (including physical nodes),0 debug-only. Equality comprises
153 entries each for assigned_phys,color_status,degree,simplify_order,select_order.
Before repair:624 equal,141 different due to missing simplify IDs. This validates
these comparable allocator fields, not every compiler pass or the emitted binary.
Fresh pressure report now runs from the Windows dump with no warnings, but its
source hypotheses remain low-confidence conversion-temporary scope suggestions.
Coalesce discovery emits5 pairs, all correctly rejected for forcing because there
is no direct identity/copy edge; none contains a concrete source suggestion.
Existing late-color-holder causality caveat still applies. Automated source-order
search remains constrained by issue1549's local-only candidate runner and fresh
identity requirement; recovering remote dumps does not resolve that integration.

Issue1550 covers the simplify diagnostic repair; issue1545's old-DLL data gap
is resolved by the isolated updated runner. Artifacts, compressed full dump,
pressure/coalesce reports and hashes are preserved under matching-evidence/
jpeg-rgb/2026-09-07-windows-simplify-repair. No production C source was changed;
98.82488 remains the best merged source, and exact match/TU linking remain open.

## Local array promotion — 2026-09-07

Six diagnostic probes replace chroma_index and/or chroma_dest with one-element
local arrays, with/without the named luma row_offset. This distinguishes array
promotion from the earlier scalar-record promotion, not a proposed stylistic
change for upstream. Both source loads remain around the Cb store.

Index-only scores97.866356/frame160, or98.087555/frame152 with luma row inlined.
Pointer-only96.76037/frame160 or96.98157/frame152; combined96.76037/frame160.
The best array candidate's full instruction rows exactly equal the coherent
scalar seed (raw current_asm lists differ in non-instruction content).
Fresh read-only retail capture and target correspondence validate267 GPR operands,
81 virtuals, no target contradictions after the known two instruction swaps.
Index moves38->73, exactly as for the prior scalar record; pointer stays37 and
all eight color differences remain. Array promotion does not move the index
near desired rank101 or change final instructions. Sources/diffs/correspondence
archived in2026-09-07-local-array-promotion; retail snapshot is locally in
/tmp/c016-rgb-array-stages. Production restored and ninja passes.

The generic lifetime-layout generator was also inspected with repaired Windows
pcdump. Its12 defaults are declaration/type/scope and pointer-walk families,
mostly already explored; no automated local debug candidate runner was launched.
Its baseline still calls coalesce-root nodes62/72 spills, so do not use that
spill_set as proof (existing flag0x08 interpretation issue). Best source remains
98.82488, already merged; no new upstream source delta.

## Separate chroma pixel locals — 2026-09-07

Sixteen valid probes use independent cb_pixel/cr_pixel locals for the two chroma
loads, preserving Cb store before the Cr load. Twelve cover u16/s32/u32 and
shared loop scope versus independent per-store blocks on production/coherent
sources. Initial per-store generator incorrectly placed a C89 declaration after
statements; corrected to explicit blocks before scoring and reran the set.
No stale object was scored on that compile failure.

u16 and s32: production98.60368/coherent97.866356,frame160. u32 changes integer
conversion lowering and regresses86.5576/86.37327,frame160. Scope does not change
these results. Two followups removing only luma row_offset stayframe160 (their
artifact labels say frame-neutral, but this intended result was NOT achieved).
Removing BOTH row_offset and column_offset in two further probes recovers152:
production98.82488, coherent98.087555. Coherent full instruction rows exactly
equal original coherent seed. Thus these independent pixel-value scopes provide
no final instruction gain after recovering the source frame; this does not assert
unchanged hidden virtual identities without a fresh trace. All sources/results
in2026-09-07-split-chroma-pixels. Production restored; ninja passes. No new source
change to submit upstream;100% and TU linking remain unfinished.

## Late address merging breakthrough:99.400925% — 2026-09-07

Revisited direct-address source97.258064 (dest-expression.c), whose fresh earlier
retail correspondence has19 changed mapped virtuals, no contradictory operand
mapping, and no target-color edge conflicts. Exact full simplify+SELECT replay
verified. Single-rank scan across19 changed virtuals: moving destination53 to
rank100.5 reduces19 misses to6. Joint5450-rank scan: destination53 rank100.5 and
index37 rank98.5–102.5 yields0 mapped misses on unchanged graph. This is a model
only, but identifies late creation for the compiler-generated address as a source
lever, not just named-variable declaration order.

Ten asymmetric-store address probes change only Cb or Cr address signedness or
pointer view. Unsigned casts regress95.400925; typed arrays/char base97.258064.
Fresh read-only retail capture of x518-unsigned-index PROVES a meaningful stage
change despite lower score: both stores share virtual103 (object=NULL), defined
by ADD103,121,100. The prior direct-address source shared virtual53 with a nonnull
compiler object. Thus asymmetric signedness prevents early object-backed sharing
and permits later backend address merging. No compiler forcing was used.

Next12 probes eliminate the named index, varying six row/low/high sum orders
and unsigned cast around sum versus low term only. High-row-low and row-high-low
unsigned-sum forms98.870964; ROW-LOW-HIGH with unsigned low term99.400925.
Other forms94.84792–97.02765. Both pixel loads and store/load ordering preserved;
all152-byte frames. This source improvement follows actual compiler lowering,
not an offline coloring score or reuse of old virtual IDs.

Cleanup verifies direct indexing of JpegWork.data.x518/x618 at the actual base
object, replacing cast-of-shifted-work-pointer. Replacing (u32)(chroma_x&1) with
(chroma_x&1UL), then final(chroma_x&1U), retains99.400925. No temporary index or
destination locals. Source column address uses(low*2+high*4)+src_row. Final
clang-format source changes only hsd_803B3408. Only raw instruction differences:
+104 target add r21,r21,r26 vs current add r21,r26,r21;
+1f0/+1f4 target li r26,0 then addi r5,r5,280, current reversed. No remaining
physical register allocation cascade in these final instruction rows. Anonymous
float relocation names still differ in textual diffs, not new source evidence.

Production source commit3b282183aa pushed to fork work branch. Clean upstream
branch pr/jpeg-rgb-direct-chroma cherry-pick4648ec0d10; PR3397 opened:
https://github.com/doldecomp/melee/pull/3397 . python configure.py && ninja passes;
all seven other TU functions100. TU stays Linkable until exact RGB match verified.
All probes, allocator-stage evidence, model winners and final source/diff archived
in2026-09-07-late-address-breakthrough. This supersedes98.82488 as best production.
Next focus: the commuted +104 ADD and luma entry scheduling pair, preserving the
late shared-address lowering recovered here. Re-derive virtual correspondence
if further allocator diagnostics are needed; old37/53 IDs are not final-source IDs.

## Post-breakthrough source shapes — 2026-09-07

Starting strictly from99.400925/PR3397,51 probes test the two remaining instruction
sites without relying on earlier source graphs. Fifteen independent Cb/Cr index
parenthesizations (left-associative row-first versus row+(low+high),column+row,
row+(high+low)) regress90.036865–97.00461. Recovered late sharing is sensitive
to grouping, not just unsigned arithmetic.

Six luma base forms: typed x118 array, s32-element pointer arithmetic in three
orders, index-first pointer addition, byte-base-offset. Typed/element/index-first
forms99.179726/frame160; grouped element-index97.31336/frame160; byte-base-offset
99.400925/frame152. None resolves the luma scheduling pair.

Twelve named low/high/both chroma column-term probes, row-first/column-first,
with/without luma row local. Low-only row-first99.28571 introduces a low/high
register exchange but still commutes+104; column-first96.24424. High/both row-first
99.400925, column-first97.00461. No improvement or ADD fix.

Twelve unsigned-term probes move unsignedness to dst_row or the high column term
across six term orders. Several unsigned-row forms retain99.400925, even
column-first spelling, but exact instruction diff still has commuted+104 and
luma1f0/1f4 swap. Others95.32258–99.354836. Thus textual term order is not final
ADD order; early expression canonicalization remains relevant.

Six final row-complexity probes expand the existing row arithmetic at Cb,Cr,or
both store sites, row-first versus grouped-column-first. One-store expansion
85.39171–85.41475, both96.10599–96.129036. This does not preserve late address
sharing/row lowering and gives no gain. No probe retained; production restored,
ninja passes. All sources, compile-producing diffs and runners archived in
2026-09-07-post-breakthrough-source-shapes. Next diagnostics should inspect the
current final source's actual ADD construction/optimization stage before more
parenthesis sweeps; old virtual identities are not proof on this new source.

## Exact 99.400925 lowering and scheduling trace — 2026-09-07

Fresh read-only retail stages for final production confirm217 instructions.
+104 instruction address0x00652708 is emitted initially as ADD101,38,100;
operands persist through optimization and scheduling, coloring to21,26,21.
It is not a late register-coloring swap. Current-CodeGen-item AST printed live
at emit shows unsigned nested(row+low)+high, with high replaced by frontend CSE
object@53. Thus integer instruction selection materializes row+column despite
nested tree spelling, rather than a scheduler reversing the ADD operands.

Luma ADDI+280 address0x00654238: initial position156, optimized142, scheduled124.
LI0 address0x00653fc0: initial149, optimized138, scheduled127. The desired LI-before-
ADDI order exists initially and is reversed at pre-allocation scheduling; final
positions124/125 retain the wrong order. This is independent of the ADD issue.
Four luma_base type probes u32,s32,u8*,void* with casts at use all99.400925/frame152,
no gain; original production restored and rebuilt.

Exact-hash Ghidra project validated. FUN_004a0ba0 materializes type2 descriptors
with ADD; FUN_004a0fc0 leaves type2 unchanged. Fresh live breakpoint at4a0ba0
finds target descriptor raw0200260000006400000000000000000000000000000000000000:
kind2,short+2=38(row),short+6=100(column),requested destination0,caller4b8086.
The caller's raw disassembly calls ENode dispatch then materializer before the
shift. Table0x560648 maps EADD15->4b8240, ESHL17->4b7fd0. These are next static
inspection entry points. Do not treat old virtual numbers as source identities
for changed candidates.

Issue1551's Java decoder exception is from passing a null function to decompiler:
getFunctionContaining(4b8086) returnsNone although instructions exist. This is a
missing function-boundary annotation, not Windows unavailability; raw listing
works. Need create a bounded temporary function at verified dispatch-table entry
4b7fd0 (or use instruction analysis) before querying that routine. Avoid changing
shared tooling/project state unnecessarily. No source improvement this turn.
Artifacts, full stages, ASTs, descriptor trace, static materializer decompilations,
and luma-type probe results archived in2026-09-07-final-lowering-trace.
