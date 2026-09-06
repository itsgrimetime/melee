# Tournament bracket animation matching

## Retained baseline, 2026-09-06

`fn_8018B090` in `src/melee/gm/gmtoulib.c` remains **99.94527%**, with
6212 bytes of code and the exact 208-byte frame. The other 48 functions in
the TU match. The retained source incorporates @fjooord's work from
[PR #3358](https://github.com/doldecomp/melee/pull/3358), published separately
as [PR #3372](https://github.com/doldecomp/melee/pull/3372). Do not mark the
TU Matching until the residual is solved and the linked DOL verifies.

The latest donor head checked was `c734b0cf92bbd5b8575015b0c43753efe7098101`.
Its `gmtoulib.c` is identical to the retained worktree source. Its recent
upstream merges add no new source lever for this function.

## Two remaining register differences

The opcode sequence already matches. There are 15 differing instruction
rows, in two regions:

- Case 23, offsets `+764` through `+820`: the loop counter should use r26
  and the JObj should use r22; the compiler assigns these in reverse.
- Case 33, offsets `+1218` through `+1228`: the slot stride should use r6,
  while the coordinate address and signed-halfword load should use r3.
  The compiler uses r3 for the stride and r5 for the coordinate.

The baseline debug dump identifies the counter as IG51 and JObj as IG100
(coalesced with IG168). Their select positions are 593 and 554. The
coordinate stride is IG489, selected at 186; the coordinate load/address
are IG487/IG486, selected at 188/189. IG489 takes r3 before the coordinate
nodes. Source attribution incorrectly calls IG51 `t5`; identify its role
from the loop instructions, not that heuristic label.

The complete diagnostic map
`0:51:26,0:100:22,0:489:6,0:486:3,0:487:3` removes all 15 instruction
differences. Remaining relocation-name differences are presentation data.
This is a forced diagnostic result, not a source match.

## Continuation experiments

No candidate in this continuation improved the retained score. All source
and header experiments were reverted and the baseline was compiled again.

| Source family | Result |
| --- | --- |
| Replace three duplicated camera if/else calls with discarded `ABS(call)` | Exact same assembly, 99.94527% |
| Existing JObj local; four simple setter helper argument arrangements | Neutral |
| Coordinate table as records with named x/y members | Neutral |
| Case-33 `int` indices, unsigned slot index, unsigned entrant index | Neutral |
| Named coordinate pointer or integer value | 99.85061%, frame grows to 216 |
| Reuse i, k, or the completed-slot counter for the entrant index | 99.93239%; adds load-register differences |
| Reuse i or k for the final slot index | Neutral |
| Direct negative-Y setter expression | 99.93883%, exact frame and opcode sequence |
| Reuse the existing `fn_8018B090_inline7` Y setter | 99.90019%, exact frame and opcode sequence |
| Local GObj pointer | 99.870575%, frame 216 |
| Explicit cast and second JObj alias | 99.80618%, extra instruction and frame 216 |
| Entire case 23 in a helper, with entry, entries/index, or global/index inputs | 99.81197%, exact opcode sequence but frame 216 |
| Case-23 scoped int counter, or unsigned counter with signed comparison | Neutral |
| Function-wide int loop counter, generated lifetime probe | 99.77463%; affects other loops |
| Inline the case-21 object getter body, generated lifetime probe | 99.82292% |
| Generated adjacent declaration swap, temporary introduction, tighter scope | Neutral |

Earlier probes in the same campaign also rejected an integer counter
record (98.216354%), reuse of the completed-slot counter in case 23
(99.42692%), and a slot animation helper (99.85705%). Earlier case-33
store/getter helpers, slot pointers, discarded reads, comma/self assignments,
and removal of the unused entrant assignment produced no retained gain.

The natural `ABS` spelling explains the repeated camera calls without
changing code generation, but is not evidence that this macro caused the
register problem. The whole-state helper changes the allocation substantially
without changing opcodes, but moves the counter, slot cursor, and JObj away
from the target. Do not treat it as a nearer solution just because it is a
larger reconstruction.

## Diagnostic caveats and next direction

Issue #1504 tracks an invalid solver verdict reproduced here. `debug solve
coloring` derives the correct physical map but verifies an unrelated
iteration-order hint, then reports physical register reassignment as
unreachable. The independent five-node forced proof above contradicts that
conclusion. Do not use this verdict to rule out an allocator solution or to
justify a node-splitting rewrite.

The lifetime probe ranking also compares numeric virtual IDs across changed
sources. Those IDs can move: the case-21 getter-body probe reports IG51 as
r0, which is no longer the original counter role. Its reported pressure
improvement is not a demonstrated improvement to the desired counter/JObj
allocation. Prefer final assembly and re-establish semantic node identities
before interpreting graph deltas.

Small local spelling and type changes have now been tested extensively.
The next useful experiment needs a specific change to the counter/JObj
coalescing or to the coordinate-stride select order, with a verified source
role mapping. Neither the failed source families nor the solver bug proves
that matching is impossible. Other outstanding functions are reasonable
work while waiting for a new donor or a better supported source hypothesis.

## Evidence

The durable local evidence root is:

`~/.config/decomp-me/matching-evidence/gmtoulib-2026-09-06/`

It contains the original donor baseline, forced proof, target map,
first-divergence report, and lifetime report. The
`continuation-register-source/` subdirectory adds source candidates, ordinary
checkdiff JSON, the generated lifetime-probe sources and dumps, a compact
`results.json`, and a SHA-256 manifest. These files are diagnostic evidence;
only the restored ordinary compiler result describes retained source.

## JPEG lookup technique transfer (follow-up)

The indexed-pointer assignment that improved the JPEG encoder was tested
against this bracket function. It did not transfer into a retained win:
slot assignment 99.57437% (+2 instructions), reused slot assignment
98.72118% (200-byte frame), coordinate pointer assignment/raw dereference
99.803604%, indexed slot entry 99.83258% (+1 instruction), embedded existing
JObj assignment 99.94527% (neutral), new JObj assignment 99.86478%, and new
GObj assignment 99.90019%. The baseline was restored. Source/checkdiff probes
are retained in the `jpeg-lookup-transfer/` evidence subdirectory.
