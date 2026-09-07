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

`~/.config/decomp-me/matching-evidence/jpeg-color-2026-09-06/allocator-followup/`

Contains baseline source/checkdiff/dumps, automatic and manual target probes,
ordinary candidate sources/results, generated lifetime probes, permuter inputs
and tied outputs, build logs, and a recursive SHA256 manifest. Diagnostic
forced outputs are labeled separately from source candidates. This extends,
rather than replaces, the earlier JPEG color evidence directory.
