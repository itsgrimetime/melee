# JPEG decoder color conversion: fn_803B6820

## Verified baseline

The source from merged PR3358 is 98.81743%, 241 instructions/964 bytes, and
has the exact 176-byte frame. The other five functions in hsd_3B5C remain 100%.
This is the last unmatched function in the TU. Link only after an ordinary
100% compile and full original-DOL verification. Former PR3376 was closed
because its improvement was absorbed upstream.

## Corrected register correspondence

A fresh baseline debug dump and ordinary checkdiff reproduce the residual.
The automatic force-phys-from-diff result is incomplete and has an ambiguous
wrong binding: at+0x1d8, `add r16,r29,r11` must bind to chroma pointer IG37,
not the earlier address-sum IG105. IG105 should stay r11. The output marks
that ambiguous IG105:r16 entry runnable; issue1509 records the failure.
It also omits persistent X-offset IG65:r15 and several conversion/shift nodes.
Do not reuse the automatic CSV as a complete allocator target.

Mapping the precolor instructions by their source roles gives this diagnostic
GPR map for the exact baseline dump:

```
0:65:15,0:100:16,0:101:16,0:102:11,0:103:11,0:104:11,0:105:11,
0:106:11,0:37:16,0:114:11,0:112:11,0:110:11,0:108:16,0:63:20,
0:44:18,0:78:16,0:116:16,0:75:28,0:120:17,0:122:28,0:118:17,
0:77:17,0:124:16,0:79:17,0:128:16,0:130:18,0:126:16,0:140:17
```

With this map, the debug compiler produces the exact frame, instruction
count and register operands except for one commuted addition:

```
Target +0x1cc: add r11,r16,r11
Forced +0x1cc: add r11,r11,r16
```

Anonymous relocation names also differ in the text dump. This is a diagnostic
correspondence, **not a source match or a full 100% forced proof**. The ordinary
source remains 98.81743%. An earlier manual probe omitted the explicit `0:`
class prefix and also changed FPR nodes with the same numeric IDs; discard
that run as a GPR proof. Use the `gpr-forced` artifacts, not `manual-forced`.
The initial automatic-map union changed code size and scheduling and is also
invalid as a complete target proof.

Source attribution for IG65 is low-confidence and calls it luma_base. Its
actual precolor definition is the persistent `(x / 4) << 4` offset. Prefer
the observed instruction role over that heuristic name. Numeric IDs must be
re-established after source edits.

## Bounded source probes

All probes below use ordinary checkdiff and were reverted unless a later
section explicitly records a retained improvement.

| Probe | Match % | Frame bytes |
|---|---:|---:|
|block-row-local|98.71369|176|
|chroma-aggregate-reverse|94.381744|184|
|chroma-aggregate|94.381744|184|
|chroma-column-inner-scope|98.81743|176|
|column-compound|98.6556|168|
|column-group-embedded|98.6556|168|
|column-simple|98.6556|168|
|column-unsigned-group|98.71369|176|
|green-int|98.65145|176|
|green-s32|98.65145|176|
|green-u16|97.82158|176|
|green-u32|98.65145|176|
|integer-address|98.71369|176|
|offset-out-reuse|98.71369|176|
|quotient-compound|97.095436|176|
|quotient-existing|95.207466|176|
|quotient-right|97.11618|176|
|row-negative|98.71369|176|
|samples-aggregate-ycbcr|94.381744|192|
|samples-aggregate|94.381744|192|
|samples-inner-reverse|98.81743|176|
|samples-inner-scope|98.81743|176|

Splitting the chroma sum changes its addition order, but reusing the column
variable shrinks the frame by 8 bytes. A separate quotient/sum introduces
other ordering differences. Widening green to s32/u32/int loses the retained
u8-temporary improvement; u16 changes code further. Moving sample declarations
into the inner loop is neutral. Aggregating the samples adds 8–16 frame bytes.

Four generated lifetime-layout probes were also neutral 98.81743%:
adjacent declaration swap, tile_x s32→int, an initial luma-pointer temporary,
and an enclosing block. The generated declaration-use-distance probe placed
a closing brace inside a multiline expression and was malformed (issue1510).
The manually corrected chroma-column inner-scope probe above is neutral.
Do not count the malformed candidate as a matching experiment.

A lifetime-pressure invocation after source restoration reported a stale
cache and suppressed its source hypotheses; it compiled no candidates. The
subsequent lifetime-layout run used a freshly captured baseline dump.

## Permuter baseline

Imported the current function with the actual Ninja compiler flags, including
MUST_MATCH and the TU's Cpp_exceptions override. Inline helpers were preserved.
The standalone baseline scores 285 (57 register differences, no insertion,
deletion, branch, or stack differences). Transplanting its target function
back into the real TU independently reproduces 98.81743% and 176-byte frame.
The import is under `nonmatchings/fn_803B6820` in the c016 worktree; its compile
script stages inputs in this worktree. Every candidate still needs ordinary
real-tree verification and semantic review before retention.

The 90-second bounded standalone search completed 469 iterations with 6 compile
errors and best score 285, equal to its baseline. Saved outputs are ties only;
none is a retained improvement. The process exited cleanly after the planned
interrupt. A fresh ordinary checkdiff after restoration remains 98.81743%,
and the full build passes the original DOL checksum. No decoder PR was reopened.

## Durable evidence

### Helper and bias-loop reconstruction follow-up

Upstream naming cleanup 9eab03d07a was merged before this pass. The other
matching thread had claimed fn_8018B090; JPEG decoder work did not overlap it.
PR3380 proposes matching lbsnap using `__rlwimi`, pending upstream review.
Applying equivalent explicit RGB565 packing intrinsics here regressed to
94.17013%, so that diagnostic was reverted.

The corrected map still identifies X-offset IG65 as the first mapped
divergence: select iteration 21, baseline r20, target r15, Case C. The map is
partial, so this does not exclude an earlier unmapped cause. Advisory naming
still misidentifies this node as luma_base; use its observed definition.

Tested 43 ordinary source candidates, including the intrinsic diagnostic.
None improved on 98.81743%; all were reverted. Candidate sources and complete
checkdiff reports are in the committed evidence archive below.

| Source family | Result |
|---|---|
|Return packed RGB565 from a helper|47.821575%; actual calls to jpeg_clamp remain|
|Return group offset from a helper|Neutral 98.81743%, frame 176|
|Return group pointer from a helper|93.497925%, frame 176|
|Extract the complete luma-bias operation|97.86722%, frame 192|
|Extract sample loads, address calculation, and pixel store together|92.6805%, frame 216|
|Extract all tile groups|89.40249%, frame 280|
|Separate color helpers, retaining nested jpeg_clamp|47.821575–59.991703%; actual clamp calls|
|Scoped or TU-wide inline_depth(8)|Did not remove these calls or improve their scores|
|Separate color helpers with expanded clamp, u8 return|92.72199–98.59336%; frames 160–176|
|Separate color helpers with expanded clamp, s32 return|98.676346%; frame 168 for one channel, 160 for all three|
|Return packed RGB565 with expanded clamps|92.72199%, frame 168|
|Natural 64-sample indexed bias loop, int or u32 counter|98.24066%, frame 200|
|Natural indexed bias loop, s32 counter|96.9917%, frame 200|
|Natural bias loop using pointer post-increment|83.016594–84.51453%, frame 200|
|Flat 256-sample bias loop|95.16598–95.22407%, frame 200|
|Reuse existing bias counter, with or without channel temporary|98.24066%, frame 192|
|Bias one 8x8 block through an inline helper|int: 98.676346%; s32: 97.42738%; frame 200|

The extra calls are observed assembly facts, not merely a presumed inline-depth
limit: both tested pragma placements were ineffective. Expanding the clamp
body removes those calls, but changes the frame and allocation. Likewise,
natural int and s32 bias loops have different unrolling, and reusing the
existing counter removes 8 frame bytes without recovering the target frame.
Do not classify these families as register-only experiments.

Reviewed generated helper patches before applying anything. Candidate
scalar-return-helper-0005 silently dropped the following jpeg_store_rgb565
call, although its rejection_reason was null. It was never applied or scored;
issue1511 records the bug. Generated padding-only extractions and wrappers
were also not used as source evidence.

A further 240-second bounded permuter run completed 1,341 iterations with
32 compile errors. Best score remained 285, equal to the baseline; no improved
candidate was emitted. It exited cleanly after the planned interrupt. The
restored ordinary compile remains 98.81743%, frame 176. The other five TU
functions remain 100%, and the full build passes the original DOL checksum.
No decoder PR was reopened and the TU remains Linkable.

Committed archive:
`docs/matching-evidence/jpeg-decoder/2026-09-06-helper-reconstruction/`

This archive supplements the earlier external evidence and includes the
candidate generators, source variants, results, diagnostic suggestion output,
permuter log, and restored-build verification. The manifest records hashes
and distinguishes rejected diagnostic source from retained source.

`~/.config/decomp-me/matching-evidence/jpeg-color-2026-09-06/allocator-followup/`

Contains baseline source/checkdiff/dumps, automatic and manual target probes,
ordinary candidate sources/results, generated lifetime probes, permuter inputs
and tied outputs, build logs, and a recursive SHA256 manifest. Diagnostic
forced outputs are labeled separately from source candidates. This extends,
rather than replaces, the earlier JPEG color evidence directory.

## Deferred-sum transfer and removal of explicit padding

After merging upstream through `22dba004cd`, the baseline still measures
98.81743%, 241 instructions, frame 176. The claim moved back here after the
user reported another contributor's complete `gmtoulib` match. No overlapping
tournament-bracket PR was opened.

The RGB creation-provenance finding suggested changing the chroma address
from `(row + high) + low` to `(row + low) + high`. In ordinary compilation,
this produces the desired `low + high`, then `row + result` operands, but
also changes the division/remainder instruction order. Its score is
97.11618%. The alternate `(low + high) + row` spelling instead groups
`high + row` first, at 98.71369%. These are not retained improvements.
The compiler lowering rule transfers, but it is not sufficient to preserve
the surrounding division sequence.

Twelve further variants materialized the high term in an s32/int/u32 local,
before or after the low term, with or without the old `PAD_STACK(8)`.
Keeping padding yielded the same 97.11618% sequence and frame 176; removing
it reduced the frame to 168 and scored 96.975105%. The extra named scalar
does not supply the missing stack storage.

Seven aggregate reconstructions tested actual data storage in place of the
explicit padding:

| Reconstruction, all without PAD_STACK | Match % | Frame |
| --- | ---: | ---: |
| Paired Cb/Cr samples, either member order | 94.52282 | 176 |
| Three luma/Cb/Cr samples, two member orders | 94.381744 | 184 |
| Chroma row and column offsets | 97.94606 | 176 |
| Group luma-row and chroma-row offsets | 98.81743 | 176 |
| Luma X and row offsets | 98.381744 | 176 |

The group-row pair is a useful preserved reconstruction: removing the
separate `group_row` and `group_chroma` scalars and `PAD_STACK(8)`, then
using a local two-member struct for those offsets, preserves all 241
instruction bytes. Only anonymous constant relocation names differ in the
assembly listing. This establishes a source form without explicit padding,
not a higher match percentage or proof that the original used that struct.
It remains an experimental candidate; production source was restored.

All 23 candidates, generators, complete ordinary diffs, the instruction-byte
comparison, and restored verification are saved with SHA-256 hashes under
`docs/matching-evidence/jpeg-decoder/2026-09-06-gprsum-reconstruction/`.
The padding-free candidate is
`c016-decoder-padding-reconstruction/record-group_row-no-pad.c` inside the
archive. Future work can use it when investigating the missing aggregate
layout, without repeating these frame probes.

Restored verification: decoder 98.81743%, other five TU functions 100%;
`python configure.py && ninja` passes. Built and original DOL SHA-1 both
equal `08e0bf20134dfcb260699671004527b2d6bb1a45`. The 85-member archive was
verified against its per-member hashes. The TU remains Linkable.
