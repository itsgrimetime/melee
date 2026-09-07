# JPEG decoder color conversion: fn_803B6820

Current retained source: **98.83817%**, committed as `94db8b8d65` and submitted
in [PR #3384](https://github.com/doldecomp/melee/pull/3384), clean head
`535a768bd1`. The final section records the chroma-addition improvement.
Earlier baseline sections below describe the preceding 98.81743% source.

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

## Fresh allocator facts and source interactions

The next pass refreshed the ordinary debug dump and ran lifetime-pressure
against that exact source. Freshness passed with no warnings. X-offset IG65
still selects at iteration 21 into r20, with target r15; chroma-pointer IG37
selects at iteration 34 into r11, with target r16. The first-divergence report
retains its earlier-unmapped-node warning: the two-node target is a focused
diagnostic, not a complete target map. The pressure report's final holders
of r15 are not all earlier selection events; do not interpret that list as
a chronological explanation of the first wrong choice.

### Distinguish virtual renumbering from changed allocation

The padding-free grouped-row source was captured separately with cache sync
disabled. The standard dump comparison reports differences from initial
PCode onward, including hundreds of raw interference-edge differences.
An explicit register correspondence explains these much more precisely:

- All ten precolor passes align instruction-for-instruction under a
  consistent, one-to-one register renaming within each pass.
- The final precolor map sends baseline X-offset r65 to candidate r64,
  stride r66 to r65, and chroma pointer r37 to r37.
- All 84 mapped GPR decisions and 34 mapped FPR decisions preserve their
  physical colors. Seven mapped GPR selection positions move by one, late
  in the order; neither focused target's outcome improves.

The comparison uses the existing dump parser and validates block/instruction
positions, opcode and operand shapes, physical-register identity, and the
register-map bijection. Anonymous constant names are normalized for alignment;
this is not an independent data-equivalence or whole-graph isomorphism proof.
Unused/unmapped allocator nodes are outside its coloring comparison. The
ordinary instruction-byte comparison from the preceding pass remains the
production-code evidence. Raw virtual-ID graph deltas alone should not
motivate another source rewrite here.

### Bounded source families

The newly merged tournament-bracket match (#3383) combined independently
neutral source changes. Its direct-global access technique motivated paired
decoder tests on the baseline and padding-free grouped-row sources. Those
eight variants add instructions and regress equally in both source layouts.
Other bounded probes below also produced no retained percentage gain.

| Family | Count | Result |
| --- | ---: | --- |
| Direct global buffer access at all/pixel/chroma/luma sites, both row layouts | 8 | 86.6639–89.10789%; six additional instructions |
| RGB helper argument order, output first/last and channel permutations | 11 | Neutral 98.81743%, frame 176 |
| RGBA u8/u16/u32/s32 records, byte arrays, actual GXColor | 7 | Byte layouts/GXColor neutral; wider layouts 97.556015–97.92946%, frame 184–192 |
| Discarded chroma/base, chroma/luma-end, or chroma/output dependencies at three sites | 12 | Six neutral; others 89.57677–90.28216% with two/four added instructions |
| Red/green/blue scalar-copy combinations and green struct/array ownership | 11 | Green scalar determines retained 98.81743%; other combinations 98.510376–98.65145% |
| Clamp return type and explicit byte narrowing | 9 | int/u32/u16 retaining byte cast neutral; u8 return or removed byte cast 92.11618–93.443985% |

The discarded pointer differences use pointers into the same work array;
cross-buffer probes use equality, not pointer subtraction. These are
diagnostic source forms inspired by the recorded mismatch pattern, not
proposed production code. The green aggregate does not add frame storage
in this helper; removing PAD_STACK with it incorrectly shrinks the frame to
168. Red and blue scalar intermediates do not substitute for the green scalar.

`jpeg_clamp` currently returns **s32**, with an explicit `(u8) (s32)` cast
on the floating conversion path. It does not return u8. An initial probe
generator assumed u8 and stopped at its source-marker assertion before
editing or compiling; the corrected nine candidates above are the measured
experiments. Keeping the byte cast while changing the return declaration to
int, u32, or u16 is neutral. Narrowing the return type to u8, or removing the
byte cast from the wide-return body, changes emitted instructions despite
the bounded channel values. Preserve this distinction in future helper work.

The 58 candidate sources/results, generators, fresh dumps, fresh pressure
report, register correspondence and comparison script, and upstream PR
reference are archived under
`docs/matching-evidence/jpeg-decoder/2026-09-06-allocator-interactions/`.
Source is restored at 98.81743%; the other five decoder functions remain
100%. Upstream through `a392908a20` is merged, including the linked gmtoulib
match. Full build and original DOL checksum verification pass. No decoder
PR is warranted by these probes and its TU remains Linkable.

## Constructive select-order diagnostic and conversion boundaries

The baseline GPR tiebreak model reproduces all 110 recorded decisions, with
no truncated nodes. Keeping that interference graph unchanged, this sequence
of abstract select-order moves reproduces the full 110-node diagnostic target:

1. Move X-offset IG65 after IG122 (luminance conversion for green).
2. Move Cr sample IG63 before luminance sample IG64.
3. Move red clamp result IG78 after IG122.
4. Move chroma pointer IG37 after IG114 (luminance conversion for red).
5. Move green clamp result IG77 after IG128 (Cb conversion for blue).
6. Move narrowed green result IG79 after blue clamp result IG76.

Moves apply sequentially to the observed **selection** order, not instruction
order. The target uses the corrected explicit GPR map above and assumes the
other observed assignments remain unchanged. This is a constructive result
for the existing SELECT model, not a source-realizability, simplify-order,
retail-compiler, or 100% assembly proof. The commuted addition remains outside
its scope. All six one-move omissions fail, leaving respectively 21, 2, 2, 4,
3, and 5 assignment differences. That establishes local necessity within this
specific construction, not global minimality.

The 48 bounded model scenarios include nine exact target-map results. Moving
IG65 alone after IG122 or IG120 gives r15, but swaps the luma/Cr assignment
and leaves other differences. Moving it after stride IG66 instead gives r14.
This explains why fixing only the first divergence is insufficient and gives
concrete coupled lifetime targets for future source reconstruction. The saved
script calls the existing `mwcc_debug.tiebreak` implementation; it does not
implement a second allocator.

### Source tests following those leads

No retained source improvement resulted from this pass:

| Family | Runs | Result |
| --- | ---: | --- |
| Clamp double input, wide channel locals, rounding at helper-call conversion | 10 | 94.0083–98.81743%; individual call-rounding forms neutral |
| X quotient/scaled ownership in parameters, locals, records, before bias/groups; paired coordinates; wide channels without padding | 15 | 90.39419–98.81743%; no improved allocation |
| Floating sample parameters at the RGB helper boundary | 8 | 90.676346–98.81743%; only Cb-to-f32 neutral |
| Embedded/inner X-offset assignments and chroma declaration scopes | 10 | Nine neutral; embedded out_offset reuse 96.82573% |
| Direct conditional/branch clamp expansions | 8 | 92.72199–98.59336%; frames 160–168 |
| Wide clamp-result temporaries and wide-value/flat-blue interaction | 5 | Wide results 98.676346%; paired blue form adds three instructions, 95.29046% |

There are 56 compile runs, including two equivalent chroma-inner declarations
that differ only in whitespace; do not count those as independent hypotheses.
Moving both red/blue rounding operations to the f32 clamp-parameter conversion
while declaring those channel locals f64 supplies eight frame bytes. Removing
the old PAD_STACK(8) then preserves all 241 baseline instruction bytes and the
176-byte frame. It is another padding-free reconstruction, not a match gain;
anonymous constant references still require the usual relocation treatment.
The combined wide-value/flat-blue test shows that these frame effects are not
independent arithmetic adjustments: its frame is correct but its instructions
change. All production source was restored.

Whole-function donor search peaked at 0.420 with hashed vectors and 0.976 with
local vectors. The strongest hashed window (0.980) is a repeated load/update/
store sequence in ftAction_800722C8's SKIP_CMD macro, not a decoder twin. The
index still reports an old 79.88% query score; current ordinary checkdiff is
authoritative. No donor justified a wholesale transplant.

Sources, results, model inputs and implementation snapshots, explicit successful
orders, ablations, donor outputs, and restored verification are archived under
`docs/matching-evidence/jpeg-decoder/2026-09-06-select-order-construction/`.

## Retained chroma-addition improvement

The following expression raises ordinary matching from 98.81743% to
**98.83817%** while preserving all other instruction bytes:

```c
chroma = base + (((chroma_row + chroma_column) -
                  (-((block / 2) << 5))) * 4);
```

At +0x1cc, the emitted add changes from `add r11,r11,r15` to
`add r11,r15,r11`: the low-column term now precedes the high-row term,
as in the target. The signed remainder still precedes the signed division.
There are still 241 instructions/964 bytes and a 176-byte frame. This is
the subtract-negative lever documented in MATCHING_GUIDE section 6, applied
to the **outer high term**. The previously rejected `row - (-low - high)`
form is a different tree and does not produce this improvement.

### Frontend evidence and rejected alternatives

Two successful retail frontend captures, baseline and `(row + low) + high`,
each contain 54 optimizer snapshots. In the baseline, copy propagation
substitutes the remainder expression for chroma_column at snapshot 06;
its remaining assignment is gone by snapshot 09 (UseDef). The final tree
is `low + (row + high)`. The reassociated candidate ends as
`high + (row + low)`, explaining its division-first lowering. IRO linear
listing order is not emitted evaluation order: follow the expression edges.
Both groupings are already visible in the initial flowgraph, so do not
attribute the association itself to the later copy-propagation pass.

Twelve low/high coordinate-record or array variants, raw or scaled, preserve
the rejected reassociation (96.975105% with padding, 97.11618% without it).
Ten expression-boundary probes tested subtraction, integer casts, a narrow
pair, and a diagnostic pointer round trip. Only outer subtraction of the
negative high term improved matching. Three valid spelling follow-ups show
that multiplying by -32, or negating the quotient before multiplication,
adds instructions; parenthesizing the negation preserves 98.83817%.
An additional negative-left-shift diagnostic was compiled but is excluded
from valid source evidence: it shifts a negative signed value. It was never
retained. The pointer round trip was also diagnostic, not proposed PR code.

### Allocation state after the improvement

A fresh dump of the retained source has exactly the same 110-node recorded
GPR graph, precolored neighbors, selection order, and observed assignments
as the previous baseline. The changed add operand order is already present
in the first PCode pass. The existing six-step abstract order replays to the
same target map under the validated model; it remains a diagnostic, not a
source realization. The old source-specific node IDs were revalidated here,
not assumed to survive the edit. The source still needs its GPR cascade fixed.

### Remote inspection and verification

Windows accepted SSH and initialized invocation
`inspect-24ade80b72d832b1894b2449`, but could not fetch exact fork commit
`cbbaf705f7`. The wrapper waited until its 300-second deadline, returned 125,
and reported missing terminal cleanup proof. An exact-invocation cancellation
retry returned 124 with the same missing proof. No inspector dump was produced;
no new remote job was launched after that failure. The reproduction was added
to existing issue1497. The two local retail frontend captures both exited 0.

The working branch and clean PR branch independently build successfully;
all other five TU functions remain 100%. Both built DOLs match original SHA-1
`08e0bf20134dfcb260699671004527b2d6bb1a45`. The TU remains Linkable because the
function is not yet 100%. Source, complete failed and retained diffs, frontend
traces, model revalidation, remote logs, and verification are preserved under
`docs/matching-evidence/jpeg-decoder/2026-09-06-chroma-add-order/`.

## Source realizes the Cr/luminance role-order swap

Putting luminance first in the red addition changes the source to:

```c
red_value = (f32) ((f64) luminance + (1.402 * (f64) cr));
```

Ordinary matching drops to **98.75519%**, with the same 241 instructions and
176-byte frame. This candidate is experimental and was restored, not retained
in PR #3384. Its value is a concrete source lever: the luminance and Cr sample
roles exchange selection positions and physical registers while the arithmetic
instruction sequence remains unchanged. Merely reordering their loads did not
produce this effect.

All ten aligned precolor passes admit a consistent register bijection. At the
last precolor pass, old luminance IG64 maps to candidate IG63, and old Cr IG63
maps to candidate IG64. Among 84 mapped GPR decisions, these are the only two
with changed colors or selection positions: luminance r19 to r18 (22 to 23),
and Cr r18 to r19 (23 to 22). All 34 mapped FPR decisions remain unchanged.
The recorded full GPR graph is isomorphic under this mapping, including an
identity extension for nodes not present in the instruction correspondence.
The existing allocator model reproduces all 110 candidate GPR assignments.

The candidate therefore supplies the Cr-before-luminance **role** ordering from
the earlier six-move construction. Replaying only the five other abstract
moves on the candidate reproduces the same extended target map:

1. IG65 after IG122 (X offset).
2. IG78 after IG122 (raw red result).
3. IG37 after IG114 (chroma pointer).
4. IG77 after IG128 (raw green result).
5. IG79 after IG76 (narrowed green result).

Wrong assignments after successive prefixes are 21, 13, 11, 7, 5, and 0.
This is evidence for combining the red expression with a future X-offset
source change, **not** a source-level 100% match. The target extension still
assumes other baseline physical assignments should remain unchanged, and the
five remaining order changes have not been realized in source.

### Bounded follow-ups

The 46 compile runs cover five families:

| Family | Runs | Result |
| --- | ---: | --- |
| Sample-load order and loaded call arguments | 10 | All six load permutations neutral; Cb call-argument forms change instruction shape |
| Channel expression operand order | 8 | Luminance-first red realizes the role swap; other isolated permutations neutral |
| Output-address negative/add trees, with and without the red change | 8 | No X-offset role movement; nested negation adds an instruction |
| Channel temporary reuse and green accumulation | 10 | Neutral or worse; some byte reuse reduces the frame to 168 bytes |
| Green subtraction/negation trees, with and without the red change | 10 | Neutral or worse; no additional useful role-order change |

The automatic `order-target` entry point refused this residual before any
allocator-target compile because stack accesses with register-only differences
were classified as stack-layout. Both frame sizes are 176 and there are no
stack-offset discrepancies. This gate problem is reported as issue1520.
The separate selection-order proposal tool worked; its no-compile suggestions
largely repeat already tested declaration, type, and address-temporary families.
No suggested end-pointer transform was run: the proposed endpoint needs a
subarray-bound review before it can be considered valid C.

Production source remains **98.83817%**, and all five other TU functions remain
100%. The restored full build passes and its DOL matches the original SHA-1
`08e0bf20134dfcb260699671004527b2d6bb1a45`. This turn's sources, diffs, graph
correspondence, model replay, tool-gate failure, and final verification are in
`docs/matching-evidence/jpeg-decoder/2026-09-06-source-role-order/`.

## Retained clamp result local removes PAD_STACK

Retained source commit5401bbeed8, clean PR3384 commit515f95abfe. A local result
in `jpeg_clamp` supplies the eight stack bytes previously reserved explicitly:

```c
static inline s32 jpeg_clamp(f32 value)
{
    s32 result;

    if (value < 0.0f) {
        return 0;
    }
    if (255.0f < value) {
        return 255;
    }
    result = (u8) (s32) value;
    return result;
}
```

Removing `PAD_STACK(8)` from `fn_803B6820` with this local retains **98.83817%,
241 instructions/964 bytes, frame176**. This is a source reconstruction
improvement, not a percentage gain or a claim that all registers match.
The return type and byte narrowing remain unchanged. The earlier alternative
using wide red/blue channel locals also preserves this baseline, but the
retained result local requires fewer changes to the source.

Eight candidate runs test s32/u8 result locals with padding kept/removed,
branch-local versus function-local declaration, implicit byte narrowing, and
the earlier call-rounding reconstruction against the retained chroma addition.
Keeping both the local and padding grows the frame to184. Removing padding
with either local type or placement preserves the baseline. The function-local
s32 declaration was retained for the existing wide return type.

Verification compares the complete TU objects at the same post-checkdiff stage:
all non-debug section bytes, sizes, flags and alignment agree; all relocations
agree after mapping renamed anonymous constants to their actual section,
offset, size and bytes. Initial source diff listings showed five renamed
anonymous constants; those names alone were not treated as equivalent.
A comparison between a raw Ninja object and a post-checkdiff object exposed
symbol/section canonicalization differences, so the final comparison uses
symmetric processing stages. The archive includes both final compared objects
and the verification implementation/results.

Both primary and clean PR worktrees build successfully. The other five TU
functions remain100%; the TU stays Linkable. PR3384 was pushed and its title
and description updated to include the padding removal. CI was still running
at this checkpoint; later verification below records the observed final state.

A fresh supported retail GC/1.2.5n backend capture completed on the retained
source. All110 recorded GPR IDs, physical assignments, and selection positions
agree with the preceding chroma-improved debug dump. The trace also records48
FPR decisions. This comparison does not assert full graph equality or realize
the abstract target ordering; it establishes that removing padding did not
solve or perturb the observed GPR allocation. The existing target roles remain
relevant to the next matching pass.

Evidence is in
`docs/matching-evidence/jpeg-decoder/2026-09-07-clamp-result/`: eight source
candidates, both compared objects, full object/relocation verification, fresh
retail trace, GPR comparison, primary/PR build and original-DOL verification,
and a per-member SHA256 archive manifest.

## Resumed after RGB encoder completion — 2026-09-07

User redirected work here after upstream PR3399 completed hsd_803B3408 and linked
hsd_3B34. Merged upstream into c016 as b1c5824798; resolved RGB source to upstream
exactly. Local report verifies all eight RGB TU functions100 and Matching config.
Claimed fn_803B6820; fresh ordinary checkdiff confirms98.83817. Snapshot work has
another local matching process and is intentionally not modified here.

Four direct chroma array probes remove named shifted chroma pointer, using the
original index expression in work.cr/work.cb on the actual base. Neither/both
unsigned index casts retain98.83817; asymmetric cr-only/cb-only casts96.618256.
Thus encoder's late-sharing source lever does not immediately improve decoder.
All restored; ninja passes. Sources/diffs in2026-09-07-direct-address-resume.
The extract get command could not find this static function despite its symbol
and report entry; issue1552 filed. Source and checkdiff remain usable.

## Diagnostic resume failures and fallback — 2026-09-07

Fresh stage capture with the previously successful RGB CaptureSession hook
reaches fn_803B6820 then GDB aborts(SIGABRT), no stage streams. Issue1553 filed;
functions.jsonl confirms target was reached, so not a static-name filter miss.
Windows current isolated runner instead fails prototype checking at earlier
fn_803B61B4 line340, before target, compileexit2; stock DLL restored. Issue1554
filed. Local ordinary build/checkdiff still passes. Neither failed capture is
valid allocator evidence and no target artifact from those runs was scored.

Recovered preserved clamp-result retail backend from committed archive and ran
supported lifetime-pressure for65:15,37:16,78:16,77:17,79:17. It is readable but
freshness unknown, ownership unattributed, scope suggestions low confidence.
Existing target mapping/six-move construction remains hypothesis evidence rather
than source proof. Report and GDB failure log saved in2026-09-07-diagnostic-resume.
Next actionable diagnostic repair: remote prototype flag/context parity or
bounded retail capture avoiding GDB hook abort; manual source/checkdiff remains
available. No production changes,98.83817 baseline retained.

## Windows compile flags recovered — 2026-09-07

Issue1554 root cause: remote runner hardcodes -Cpp_exceptions off, omits MUST_MATCH,
and adds -warn iserror. Real TU command uses exceptions on,MUST_MATCH,warnings off.
An isolated decoder_pcdump.ps1 changes those three settings; it lives beside the
repaired DLL under C:\Users\mikes\code\mwcc_debug\codex-c016-v6-20260907.
No shared default runner or production compile flags changed. Staged exact local
source SHA256 a4c7e7d8c3bf0531c2d2ba7cfc2658ff1f24ff1e87969400ffedc68dddb12e58.
Remote compiles exit0 in0.526s,940152-byte dump; source and stock DLL restored.

verify-backend against committed clamp-result retail capture:790 comparable facts
equal,0 different,69 retail-only nodes. This validates captured allocator fields,
not arbitrary runner equivalence for other TUs. Fresh lifetime-pressure now has
no warnings; hypotheses still need source proof and final-color-holder causality
caution. Coalesce discover returns no pairs. General remote TU-flag parity remains
an open tooling issue; this per-TU runner is the verified local workaround.

Four source probes combine direct chroma array access with luminance-first red
expression: neither/both unsigned indices98.75519; one unsigned96.53527. No retained
gain; production restored98.83817 and ninja passes. Verified runner, fresh dump,
fidelity/pressure reports and candidate sources/diffs archived under
2026-09-07-windows-flags-recovery. Next captures should use decoder_pcdump.ps1,
not the generic runner that rejects the earlier unprototyped helper.

## Clamp output-parameter boundaries — 2026-09-07

Ten probes replace selected red/green/blue clamp calls with a u8 output-parameter
helper, either wrapping existing jpeg_clamp or spelling its branches directly.
The wrapper adds another inline depth and leaves calls:47.821575–59.991703,
frames272–312. Direct branches single-channel preserve176-byte frame:
red98.443985,green98.46473,blue98.75519. Red+green93.28216/frame168;
all92.72199/frame168. None exceeds98.83817; all restored, ninja passes.

Fresh Windows capture of direct-blue candidate succeeds in0.521s using verified
per-TU runner; stagedsource SHA256a5066f558492a02a26d2e8005801fee7c235e31f89a3879d0343d13ae20dd43f.
Aligned precolor bijection audit fails correctly: initial257->255 instructions,
last precolor249->248; old133 and76 map non-bijectively to candidate75. Therefore
this source is not a simple role renumbering and old force-phys mapping must not
be reused. No full target allocation claim. Sources/diffs,dump,and failed mapping
report archived in2026-09-07-clamp-output-parameters. No new PR delta.

## Output address parameters — 2026-09-07

Four ordinary source probes tested inline output parameters for the group pointer
or X offset. All add eight stack bytes (frame 184 vs target 176): complete pointer
calculation 92.28631%, precomputed offsets and row/stride forms 96.72614%, X-offset
output alone 98.6971%. None is retained. Unlike the previously tested returned
pointer/offset helpers, these explicitly pass the address of the caller local.
No compiler allocation claims are inferred from their lower match scores.

The existing lifetime-layout tool was also queried with the fresh verified
Windows baseline and helper-inline-lifetime focus, without compiling probes.
It offers only generic declaration/type/scope probes; specialized helper families
have no supported pattern, and jpeg_store_rgb565 is too complex for its pure
expression inliner. This is a tool coverage limitation, not proof that helper
reconstruction cannot work. Sources, ordinary checkdiff results, and diagnostic
JSON are archived in 2026-09-07-output-address-parameters. Baseline restored.
