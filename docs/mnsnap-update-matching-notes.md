# Snapshot update matching — completed 2026-09-07

Target: `fn_802545C4`, `src/melee/mn/mnsnap.c`, module `mn`, public scratch
[decomp.me/scratch/vdsqC](https://decomp.me/scratch/vdsqC), owned by `itsgrimetime`.

**Retained ordinary full-TU result: 100.0%, all 3566 instructions / 14264 bytes
identical, frame 440.** Final local source commit `71ea541c5a`, after the five-line
checkpoint `70164e9a00`. All 17 already matched neighbors remain 100; initializer
`mnSnap_80257F24` remains 97.853165%, so the TU stays Linkable.

PR #3389 merged at upstream `8c2ac43d9b`; this checkout includes upstream
`9dc083a2d5`. The user requested completing the remaining differences before
opening a new PR, then explicitly said “Let’s get that up into a PR.” The completed match is published in ready PR [#3392](https://github.com/doldecomp/melee/pull/3392),
commit `9b7bb943c7`, branch `pr/mnsnap-update-match`, in
`../melee-pr-mnsnap-update`. Preserve ready status. Fresh PR worktree validation
passes: callback100, all14264 instruction bytes identical, 17 neighbors100, full
required-prototype build and DOL comparison pass. The PR changes only mnsnap.c.

The final steps were: pass named loop offsets by reference (right loop 99.971954,
both loops 99.99299), restore pending state to the existing `state` local, and
reuse parent `jobj` instead of `jobj2` for the first case-11 move-cursor update
(100.0%). Existing `PAD_STACK(304)` and the initial loop's cursor aggregate remain;
the original local stack layout has not been recovered. Source alternatives and
failed cleanup attempts are retained below and in the evidence archive.

ELF audit accounts for all 711 relocation pairs: 393 identical external targets,
308 equal section offsets, and 10 reordered constants with equal values. All 29
distinct referenced data objects have equal raw bytes. Ordinary report uses
`functionRelocDiffs=data_value`. The text diff still distinguishes named BSS/data
anchors; that is not a register/instruction residual. The normal full build and
DOL comparison pass, but the Linkable TU uses its original object in the DOL;
that comparison alone is not proof of linking the entire C TU.

Public scratch source is byte-identical to the extracted final source (SHA256
`20809d9f0efb9dccb744a0f156326c0dc19cbea6e8416f6ed3e94ed3bbcbee83`).
Its independent score is 165/356600, **99.95372966909703%**, not zero. Do not confuse
the CLI's rounded 100.0 display with an exact public match. Investigating its
diff via generic scratch get hit a production-auth transport bug (#1537); the
production sync fetch/update paths work. Full-TU local verification is definitive
for the retained source. No community messages have been sent.

Evidence: `docs/matching-evidence/mnsnap/2026-09-07-six-registers/`. Older sections
below preserve investigation history and are superseded by this checkpoint.

## Collision audit

The initial audit of open PR files and thread
`01a0749c-030f-73b1-abae-0aeb453a792b` found the other thread working on
`lbSnap_8001DA5C`. We claimed the snapshot callback in our own PR #3375.
On the final audit the other thread had moved to `fn_803B6820`, claimed by
`codex-c016`. Neither target, its worktree, nor its publication branches were
modified. PRs #3372 and #3376 were closed, not merged; their gains were already
in the upstream batch. PR #3377 had advanced independently. Recheck claims and
open PR files before selecting another target; this audit is a dated snapshot.

## What the register diff hides

The baseline has 3566 actual instructions and 68 differing instruction operands,
all in case 2, offsets +0x5CC through +0xD38. Opcodes and frame agree. The
normalizer reports zero structural differences, but this does not establish
equivalent value flow.

At +0x830 the target loads the selected slot into volatile r0. After dialog
setup calls, +0xA70 reloads `active_slot` into r3, and +0xA84 compares that
fresh r3 with zero. The C instead compares the earlier `slot` local, which
keeps it live across those calls in r22. Replacing just that late comparison
with the global field reproduces the target's volatile roles but moves saved
registers elsewhere: **99.50084%, 352 register differences, still 3566
instructions and frame 440**. This is a verified data-flow lead, not a match.

The baseline and reload debug captures each have one successful GPR coloring
round. Their first differing PCode operation is the comparison in block B261:
the reload form initially emits a new load, value numbering replaces it with
the preceding load's value, and copy propagation leaves the comparison using
that fresh value. The cached value is virtual r94. Shortening its lifetime
changes selection order outside this branch: the **case 11 pending-state value**
IG95 moves from selection 10/r23 to selection 6/r27, before the button halves and
several field pointers. This is not the initial switch-state read: its constants
0/4/6 and final field store identify its source role. The attribution tool reports
no source owner; this identification comes from following PCode definitions and
uses. An explicit baseline-like selection prefix did not restore a match.
No compiler override is production proof.

## Tested source families

The evidence manifest records every ordinary compile result. Highlights:

- Reload through the existing local, reusing `i`, `state`, or `result`, a
  discarded `slot` reference, and a small error-text inline all leave the
  99.50084%/352-register result unchanged.
- Moving the reload before the status check and scoping the local were also
  neutral in staged debug probes. Eliminating all cached reads changed the
  instruction shape. Staged probes have assertion-string layout differences;
  ordinary in-tree compilation is authoritative.
- Named active-slot, state, and card-status pointers do not improve the seed.
- Extracting the whole input block reaches 99.51598%, frame 448, with one
  instruction missing. It shares the bit-mask constant 4 with the following
  animation loop instead of emitting the target's separate `li` at +0x92C.
  Removing the unused parent local, reusing the byte offset, or changing its
  type to `int` does not fix this.
- Reusing `mnSnap_AnimateCardSlots` for both input branches reaches 99.84128%,
  frame 448. Reducing the existing diagnostic padding by the measured eight
  bytes restores frame 440 and reaches **99.85838%**, still below the baseline
  and still missing an instruction. Neither padding change nor helper rewrite
  is retained. Nested helpers and a whole-case helper regress further.
- Whole-function donor search tops out at 0.979 with a much shorter menu
  function; window hits are generic JObj operations or unrelated loops. No
  matching twin for the slot/dialog construct was identified.

Do not repeat these spelling and helper families without new evidence. A useful
next diagnostic would explain how the shortened slot lifetime changes the
simplify/select ordering while retaining a separate mask constant and loop
initializer. Follow actual definitions and coalesced roots; automatic physical
target maps and normalized diffs are hypotheses, not exactness proofs.

## Tooling and persistence

`lifetime-pressure` produced no output for 101 seconds unscoped and more than
243 seconds with just `325:21,303:23`, at approximately full CPU. Both read-only
runs were terminated; issue **#1508** records commands and timing. The ordinary
analysis and target derivation completed on the same capture. The earlier
multi-round issue #1507 does not explain this single-round case. Source was kept
unchanged while each pressure run was active.

The [evidence directory](matching-evidence/mnsnap/2026-09-06-update-lifetime/)
contains a manifest and compressed sources, reports, captures, and build logs.
The shared mismatch DB records `cross-call-cache-hides-in-register-only-diff` as
an unsolved diagnostic observation. There are no active compiler/probe jobs at
this checkpoint. The best source was restored before final verification.

## Combined donor follow-up

The gmtoulib contribution is now merged as upstream `a392908a20` (#3383).
Read-only inspection suggested counter reuse and named JObj loads as possible
source levers. The snapshot follow-up tested **44 ordinary full-TU candidates**;
all were restored. Both initializer and callback baselines remain unchanged.

| Source family | Probes | Result |
| --- | ---: | --- |
| Reuse `slot`, `result`, or `state` in case 2 animation loops | 8 | All-loop variants grow the frame to 448; refresh-only adds an instruction. |
| Materialize each animation JObj argument into `jobj`/`jobj2` | 8 | Names behave identically; no gain with cached or fresh slot comparisons. |
| Reuse a counter in right/left input loops only | 12 | Neutral: cached 99.86399%, fresh 99.50084%; 3566 instructions/frame 440. |
| Reuse or isolate the case 11 pending-state local | 8 | No gain; the fresh comparison remains 99.50084%. |
| Index-derived offset in the common animation inline | 4 | Assignment form restores the missing instruction and exact opcode sequence; register/frame differences remain. |
| Isolate the donor effect and existing padding | 4 | Effect depends on inline context; no retained source gain. |

The matched local donor `mnSnap_80253F60` computes
`byte_off = (i * 2 + 1) * 4` inside its loop. Applying that assignment to
`mnSnap_AnimateCardSlots`, with both case 2 input branches using the inline and
the late slot comparison reloading the field, restores **3566 instructions** and
an identical opcode sequence. It scores **99.49187%**, frame **448**. The earlier
two-helper seed had **3565 instructions**, **99.84128%**, frame **448**.
Inlining the index expression separately at each call instead produces 3572
instructions. Applying the assignment only to the original caller's left loop
removes an instruction. The formula is therefore not a context-independent fix.

Reducing the existing diagnostic `PAD_STACK(312)` to 304 in the shape-correct
donor candidate gives **3566 instructions/frame 440**, **99.50897%**. This is a
diagnostic result, not a retained fix: registers still differ and the baseline
remains better. No new padding was introduced.

### The pass that merges the constant

Fresh **patched debug-backend** captures identify the lost initializer at
`AFTER VALUE NUMBERING 2`. In control block B228, `li r387,4` becomes
`mr r387,r536`, reusing the earlier button-mask constant across the audio call.
The control has 19 `li ...,4` operations before this pass and 18 after it. The
index-derived form gains its loop constant during strength reduction and keeps
19 through the second value-numbering pass. After coloring the captures have
3616 and 3617 PCode instructions respectively. Ordinary retail builds confirm
the missing/restored machine instruction; no unmodified retail pass trace was
taken, so the exact pass attribution is limited to the patched backend.

The target uses a volatile mask at +0x8FC and a separate `li r20,4` at +0x92C
after the audio call. The two-helper control keeps the mask in saved r22 and
reuses it as the loop offset. Next work should reconcile counter/offset lifetime
and coloring in the shape-correct donor form. Do not repeat the 44 recorded
families or infer source equivalence from a normalized opcode match.

### Trace parser correction and final verification

The PCode parser rejected numeric pass suffixes and silently appended
`AFTER VALUE NUMBERING 2` to the preceding snapshot. Issue **#1519** is fixed in
local-fork commit **`ff9dd90891`**, with a regression test that failed before the
fix and **67 passing parser/diff/capture tests** afterward. Use branch-local
`PYTHONPATH`; the installed CLI's shared master checkout has not been changed.
`constant-four-census-before-parser-fix.json` is an invalid intermediate result
preserved only as a bug reproducer. `constant-four-stage-census.json` is the
corrected evidence.

The [combined evidence](matching-evidence/mnsnap/2026-09-06-combined-donor/)
contains all 44 source/report pairs, raw captures, the corrected census,
regression-test output, and final restored build checks. The mismatch DB entry
`second-value-numbering-reuses-loop-mask` and the attempt ledger retain the
finding without claiming a successful match.

After source restoration, `configure.py`, Ninja, build SHA1, and an original-DOL
byte comparison pass. All **49/49 gmtoulib functions** and its data match and its
TU is linked. Snapshot still has 17/19 functions exact; initializer 97.853165%,
callback 99.86399%. Global status is **19821/19828 functions**, **1126/1130 TUs
linked**, and **1211168/1211168 data bytes** matched. Linked-DOL equality does not
prove the two remaining snapshot C functions exact. The other thread owns JPEG
decoder `fn_803B6820`; open PRs cover the encoder and grbigblue. Our active claim
is the snapshot callback `fn_802545C4`, agent `codex-d82d`.

## Inline isolation and usable lifetime diagnostics

A further **10 ordinary full-TU candidates** are preserved in
`matching-evidence/mnsnap/2026-09-06-inline-isolation`. None is retained.
The indexed helper is now separate from the original case 0 helper, so the
already-matching case 0 loop keeps its original source. Pointer-parameter and
direct-global helper versions produce identical results:

| Indexed input loops | Match | Instructions | Frame |
| --- | ---: | ---: | ---: |
| Right only | 99.84633% | 3565 | 448 |
| Left only | 99.83791% | 3565 | 448 |
| Both | 99.49804% | 3566 | 448 |

The both-indexed form keeps the target opcode sequence. Fresh patched-backend
captures show why the left-only change is insufficient: after the second
value-numbering stage, its left-loop `li r1273,4` becomes `mr r1273,r537`,
reusing the mask. With both loops indexed, `li r1275,4` survives. This narrows
the investigation to an interaction with the preceding input loop; it does not
establish the underlying value-numbering decision rule. The source/passing
mode of the active-slot parameter is neutral.

### Lifetime-pressure performance repair

Issue #1508 is fixed in local-fork commit **`315fd457a6`**. A 15-second bounded
profile showed that batch virtual attribution reparsed PCode, allocator events,
and function analysis for each requested virtual. Missing source bindings also
triggered repeated source parsing. After eliminating those repeated parses, a
second profile identified full instruction scans repeated for each virtual.
The batch now builds instruction-site and call-return lookup indices once and
keeps all cached facts scoped to that request.

The exact earlier targeted callback command, using the preserved fresh-slot
source and dump with `--force-phys 325:21,303:23`, completes in **23.85 seconds**.
Earlier runs had been stopped after 101 seconds unscoped and more than 243
seconds targeted without output. The before/after attribution JSON for five
selected virtuals and their pair relationship is identical. **387 relevant
tests pass, four are skipped**; the new regression first failed because five
requested virtuals caused six PCode/hook/analysis passes and five source-binding
parses. It now verifies one parse per batch and one flatten per compiler pass.
The installed shared-master CLI is unchanged; use branch-local `PYTHONPATH`.

The completed report identifies IG306, the address of `dlg_timer` at offset
0x150, as the r23 holder interfering with IG303, `active_slot` at offset 0x140.
IG325, the early `card_status` address, has a selection-order difference.
These roles come from the actual field offsets; the tool's field-name confidence
is unresolved. The proposed source actions remain hypotheses.

Four ordinary pointer-lifetime probes followed this report. Naming only the
case 2 dialog-timer pointer is neutral on both the fresh-slot seed
(99.50084%, frame 440) and both-indexed seed (99.49804%, frame 448).
Also naming the active-slot pointer changes opcode order and regresses to
99.4641% and 99.416435% respectively. All four still have 3566 instructions.
The baseline was restored and rebuilt before reading final scores.

The attempt ledger and mismatch record
`index-offset-cse-depends-on-earlier-loop` preserve these negative results.
The next diagnostic can now use lifetime-pressure on the indexed seed's own
capture and derived register targets; register IDs from the older fresh-slot
capture must not be reused without checking their definitions.

That follow-up also completed, in **22.52 seconds**, using the indexed seed's
own derived targets. The right/left index-derived offsets IG1274/IG1275 occupy
r19; target r20 is held by their respective status-walk pointers IG335/IG333.
Their first definitions are `mr ... ,r289`, with base `&mnSnap_804A0A10`.
This points to investigating the walk/offset ownership and relative ordering
inside the inline, rather than repeating field-pointer declarations.

The same report incorrectly labels loop counters IG390/IG388 as spilled,
although the single successful GPR coloring round assigns both r22. Their
`SPILLED` simplify annotations describe spill candidates, not proof of final
spills. Issue **#1521** records the contradiction and reproducer; treat its
"keep the target live range colorable" recommendation as unproven. The
performance fix does not change spill-status interpretation or resolve the
separate multi-round issue #1507. No forced-compiler result is a production
source match.

## Walk ordering, equivalent offsets, and solver verification

Thirteen further ordinary full-TU candidates are saved in the
[walk-order evidence](matching-evidence/mnsnap/2026-09-06-walk-order/).
The retained callback remains 99.86399%; no candidate from this group is retained.
All start from the separate both-indexed helper and fresh late slot comparison.

| Candidate family | Probes | Result |
| --- | ---: | --- |
| `for` instead of `do`, `int` counters, explicit status walks, and declaration positions | 7 | 99.44447–99.49804%, 3566 instructions/frame 448; walk and offset registers remain reversed. |
| `i * 8 + 4` or `(i << 3) + 4` | 2 | 99.81912%, 3565/frame 448: the higher score loses an instruction. |
| `(i + 1) * 8 - 4` or `(i + i + 1) << 2` | 2 | 99.18396%, 3568/frame 448. |
| Case 2 named status pointer, mutable or const | 2 | 99.32698%, 3565/frame 448, changed opcode order. |

The arithmetic variants establish expression-shape sensitivity; their individual
internal optimizer paths have not been traced. The mismatch DB record
`algebraic-offset-shape-changes-loop-lowering` and thirteen attempt records
preserve this distinction. Do not select the higher-scoring missing-instruction
form as structural progress.

The SELECT surrogate reproduces 998/998 observed indexed-seed assignments, with
two abstentions. Moving walk IG335 before offset IG1274 swaps their r20/r19
assignments; moving IG333 before IG1275 does the same for the other loop.
Together, these simulated moves change exactly four registers and satisfy four
of the 70 derived mismatched targets. Moving case 2 status address IG290 earlier
satisfies at most five of those targets in the tested positions. These are
validated local counterfactuals, not source fixes or proof of whole-function
reachability.

### Coloring solver issue #1522

Local-fork commit **`7e2b503840`** fixes a mismatch between the coloring solver's
reported physical targets and its executed verification. The original run
reported 70 physical-register targets but tested five `iter-first` anchors.
Its failure was then presented as proof that no register relabeling could work.
The initial report suspected stale cache state; code inspection disproved that.
The anchor probe was a deliberate, limited ordering heuristic reused by the
coloring caller.

Coloring now verifies all derived physical assignments directly, while ordinary
order-target derivation keeps its anchor workflow. The live corrected run used
all 70 `force-phys` entries, no `iter-first` entries, and completed in 25.79
seconds. It remained unmatched. The final abstention text now describes the
failed verification without declaring register relabeling impossible. **123
tests pass**, including GPR/FPR coverage above the unrelated 64-anchor limit.
The installed shared-master CLI is unchanged; use branch-local `PYTHONPATH`.

The indexed source also has frame 448 rather than 440. A separate diagnostic
reduces its existing padding from 312 to 304: ordinary compilation gives
99.515144%, 3566 instructions/frame 440. Reusing the physical vector in that
diagnostic does not yield a match and also changes scheduling/instruction count.
It is not a clean register-only proof; no natural capture was taken to establish
virtual-ID identity after the padding change. The raw forced dump is retained
for inspection. `ordinary-object-after-forced.json` reads the ordinary object
restored by the dump tool, not the forced object, and has no authoritative score.

### Permuter import verification

Before searching, the imported source failed ordinary transplant verification.
Fallback preprocessing expanded `HSD_ASSERT` with `<stdin>` line numbers and
dropped the guarded `MUST_MATCH` self-assignment. Correct compiler flags in a
later full-TU wrapper cannot recover already-lost source. Preserving the assert
macro and restoring that assignment recovers the exact indexed seed:
**99.49804%, 3566 instructions/frame 448**, identical opcode sequence.
This additional reproducer is recorded on existing issue #1432.

The isolated search uses the ordinary retail compiler with actual Ninja flags,
a frozen full TU, and the existing function-splicing wrapper restricted to the
callback and indexed helper. Randomization is restricted to case 2 and that
helper. The verified base score is 3185 without stack penalties; the bounded
search enables stack differences as well. Compiler overrides are not involved.

The five-minute run completed **196 iterations**, with **30 compile errors**
and no saved improvement. It stopped at its time limit; its process and owned
staged sources are gone. This bounded negative result does not exhaust the
source space. Future work should use a new source hypothesis or a validated
precolor-to-final operand correspondence before expanding this search.

The verification tests also exposed issue #1523: one timeout-forwarding test
wrote synthetic `mnDiagram_OnFrame` target metadata into the real worktree.
Commit **`2bbe5d86f1`** directs that test to `tmp_path`; all five affected CLI
tests pass, and the proven fixture artifact was removed. Its synthetic hashes
are retained only in this evidence archive, never as matching input.

At the restored checkpoint, the full configure/Ninja build and original-DOL
comparison pass. Snapshot remains 17/19 exact (callback 99.86399%, initializer
97.853165%); gmtoulib is 49/49 and linked. Global counts remain 19821/19828
functions, 1126/1130 linked TUs, and 100% data. PR #3375 remains unchanged with
passing checks. The other thread now holds both JPEG targets `fn_803B6820` and
`hsd_803B3408`; PRs #3384/#3377 cover those files. All excluded targets and
publication branches were left alone.

## Retail correspondence: opcode equality is not enough

The retained callback has **3566 instruction mnemonics in the target order**, a
440-byte frame, and 68 differing machine-operand lines, all involving GPRs.
Its score remains 99.86399%. However, this is not proof of a pure coloring
problem: one register discrepancy uses a different value.

At callback offset `+0x830`, the candidate caches `active_slot` in r22; the
target loads it into r0. Later, both versions reload `active_slot` into r3 at
`+0xA70`. At `+0xA84`, the target compares that fresh r3 with zero, while the
candidate compares the old r22. The source is the late `if (slot == 0)` inside
the unavailable-card dialog branch. A single rename cannot reconcile a cached
value with a later reload across calls.

This is confirmed by an unmodified retail GC/1.2.5n trace. The retained source's
precolor root r94 has one definition and six uses: six operand sites correspond
to target r0, but the late comparison corresponds to target r3. The conservative
precolor-to-final mapping therefore reports one conflicting target assignment,
`r94 -> {r0, r3}`. This establishes a compiler value-use/lifetime discrepancy;
it does not establish that the intervening calls actually change the global at
runtime.

Replacing only that comparison with
`if (mnSnap_804A0A10.active_slot == 0)` produces **99.50084%, 3566 instructions,
frame 440**. A fresh retail trace has **no conflicting target assignments** in
the checked correspondence. Shortening the cached value's lifetime changes the
allocator's decisions throughout the function: 66 mapped roots still need
different physical assignments. Thus the concrete remaining task is to find
natural source lifetimes and ordering that preserve this corrected value use
and also recover the target registers. The lower score is not evidence that
the reload correction is wrong. Neither candidate is a completed match, and no
new source edit is retained in this checkpoint.

The evidence is saved in
[retail correspondence](matching-evidence/mnsnap/2026-09-06-retail-correspondence/).
The mapper joins forward-peephole and final PCode by instruction identity,
requires unchanged opcodes/nonregister operands, and checks final GPRs against
ordinary compiler output before transferring target registers. Post-allocation
operand rewrites are excluded rather than assigned speculative provenance.

| Retail capture | G1 replay | Checked GPR sites | Mapped roots | Target conflicts |
| --- | ---: | ---: | ---: | ---: |
| Retained source | 1177/1177 | 3613 | 916 | 1 |
| Fresh late comparison | 1178/1178 | 3613 | 916 | 0 |
| Both-indexed helper plus fresh comparison | 1182/1182 | 3515 | 916 | 0 |

All three have zero checked-register validation errors. The indexed form has
58 target operand-shape differences, chiefly its 448-byte frame, and 68 mapped
roots with changed target assignments. Each mapping excludes 193 post-allocation
operand rewrites and 643 other rows. These are incomplete GPR correspondences,
not a proof that all value flow, relocations, or FPRs match. The existing retail
snapshot validator accepts all three allocator snapshots (1503 blocks each).

Captures use compiler SHA256
`ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`,
selected function index 0017, and end at that function's final scheduling stage.
They do not complete a whole compiler invocation or prove trace-object parity.
The full baseline includes creation provenance. The two successful focused
captures omit initial lowering and creation hooks; no birth provenance is
claimed for them. An earlier slim indexed capture timed out at 120 seconds:
its initial-stage callback re-enabled costly creation breakpoints. That partial
capture is retained only as a failed diagnostic, not as matching evidence.

Five additional ordinary donor probes are negative. Embedding the counter
initializer in a typed or byte-based walker initialization gives 99.35474%,
3568 instructions/frame 448. Three `sizeof(HSD_JObj*)` offset variants remain
99.49804%, 3566/frame 448. The matched `fn_80169C54` walker idiom and the ifStock
sizeof idiom do not resolve this callback in these tested forms. All sources
were restored after measurement.

The final restored-source configure/Ninja build passes. Snapshot remains 17/19
exact, with callback 99.86399% and initializer 97.853165%; global counts remain
19821/19828 functions, 1126/1130 linked TUs, and 100% data. The linked DOL is
byte-identical to the original (this alone does not prove unmatched C). The
archive contains 112 hash-verified files. Six attempt records, mismatch pattern
`register-only-diff-can-hide-reloaded-value`, and the local checkpoint memory
preserve this result. No source changes or PR updates were made.

## Full simplify replay and the corrected working baseline

The preceding best-score-only checkpoint is superseded for the callback.
The one-line fresh `active_slot` comparison is now retained locally. Target
`+0xA84` uses the reload at `+0xA70`; the old cached `slot` comparison is the
wrong value-use/lifetime shape. Its higher score does not justify keeping it
as the source baseline. Current callback: **99.50084%, 3566 instructions in
target opcode order, frame 440**. The initializer and the other 17 functions
are unchanged. The former source is preserved in Git and prior evidence.

The tool audit identified four incompletely explored paths: full simplify and
inverse coloring, constrained source-rank search, differential virtual-register
birth/origin analysis, and an allocator-guided permuter. This checkpoint
executes the first two in bounded forms and establishes prerequisites for the
third. Evidence is in
[retail graph analysis](matching-evidence/mnsnap/2026-09-06-retail-graph/).

The existing `mwcc-decomp` full simplify-plus-select model reproduces every
captured ordering decision and GPR assignment: retained historical source
1177/1177, fresh comparison 1178/1178, indexed helper 1182/1182. Four simplify
jam selections occur in each capture; their selected values receive registers
in the successful round. They are not proof of final stack spills. The fresh
full selected-function capture agrees with its earlier focused capture on all
GPR nodes' neighbors, flags, degree, color, spill cost, select order, and
coalescing map. Capture scope remains selected function through final
scheduling, not an entire compiler invocation or object-parity proof.

No same-color interference edges exist among the conservatively transferred
target assignments and fixed registers in any of the three candidate graphs.
Unmapped values remain unknown, and the old cached source still has its
separate conflicting root94 target. Absence of these edge conflicts does not
prove the target coloring is globally reachable or the full dataflow matches.

The inverse degree query tests 80 combinations for roots303/306 and 728 for
roots95/303/306, allowing zero through eight extra permanent neighbors. A
single synthetic degree addition on root303 (the active-slot address) restores
the queried target colors: root303/r23, root306/r26, and root95/r23. Against
all 916 mapped targets it improves only 850 to 853 hits. Testing 56 concrete
synthetic edges to existing coalesced nodes likewise yields partial results.
These are graph hypotheses; no C edit has yet demonstrated the added overlap.

The source-rank solver classifies 307 object-backed webs, including inline and
generated objects. To avoid treating them all as reorderable C declarations,
the bounded experiment fixes every object except four manually identified
webs: loop counter53, byte offset54, selected slot94, and pending state95. It
exhausts the 24 modeled orders, reaching at most 854/916 targets. This excludes
only those 24 rank assignments on the captured graph. It does not exclude
other source forms, and a web-rank permutation is not itself a demonstrated
declaration-order transformation.

Five natural source probes replace existing slot-polling code with the already
defined `mnSnap_UpdateSlotStatus` inline: case2 slot0, slot1, both, the initial
poll, or all three. All are neutral against the corrected seed: 99.50084%,
3566 instructions/frame440. None is retained.

The origin-ranking audit found a coverage gap. Existing baseline and fresh
creation captures record 4109 and 4111 PCode creations respectively, but zero
individual virtual-register birth events. The empty `rank_register_origins`
comparison means missing coverage, not equal origins. The next birth capture
must enable `virtual_register_breakpoints`,
`direct_virtual_register_breakpoints`, and
`virtual_register_counter_reset_breakpoint` in both source variants; assert
nonzero birth events and matching compiler/function identities before using
the ranking. No allocator-guided permuter run or exhaustive source-rank search
has been completed for this callback.

Upstream remains `a392908a20`. The other thread has advanced JPEG PR #3377 to
`5d8814c18093525f573011ff5e37e97020d3c655` and currently claims `hsd_803B3CD8`
plus decoder `fn_803B6820`; both JPEG files and grbigblue remain excluded.
Our draft PR #3375 is unchanged; the callback correction is local working
source pending further matching progress.


## Public scratch and dialog-local improvement

Created the requested community scratch https://decomp.me/scratch/vdsqC using
refreshed production credentials, then updated it to the retained source and
matching `-DMUST_MATCH` flag. The uploaded function is byte-identical to the
62,676-byte extracted repository function; the refreshed context is 353,369
bytes. Production reports 1720/356600, or **99.51766685%**, while local objdiff
reports **99.563934%**. These are different scoring schemes. The scratch is owned
by `itsgrimetime` and is ready to share. No community messages were sent.

The newly merged grBigBlue_801E6C60 donor suggested named call-result staging.
Five ordinary full-TU probes tested this in `mnSnap_InitDialogText`:

| Probe | Local score | Opcode similarity | Decision |
|---|---:|---:|---|
| Separate `created` local | 99.50084 | 1.0 | Neutral |
| Expand first case-2 dialog with staged result | 99.50084 | 1.0 | Neutral |
| Reuse `t` for call result and later font access | 99.563934 | 1.0 | Retained |
| Also use local for alignment | 99.3438 | 0.998877 | Rejected: target loads removed |
| Use local for all fields | 98.92737 | 0.996624 | Rejected: target loads removed |

All frames remain 440 bytes. The retained helper keeps the global field accesses
and reuses the existing `t` local for the creation result. It reduces GPR-only
paired differences from 352 to 307 without changing the opcode sequence. The
precise graph edge/order responsible is still unverified; this is an observed
source improvement, not proof of the earlier synthetic permanent-edge model.
The fresh late `active_slot` comparison remains in place.

Full configure/Ninja passes. Seventeen other snapshot functions stay at 100%;
the initializer stays at 97.853165%. The generated DOL equals the original.
Global progress is 19822/19828 functions, 1126/1130 linked TUs, all data matched.
Upstream PR #3369 matched grBigBlue_801E6C60; its author was working on that TU,
so the remaining grBigBlue_801EE398 remains excluded. Own draft PR #3375 has
not been updated with this callback work.

Production setup exposed two fixed CLI defects: the default omitted MUST_MATCH,
and `sync fetch --json` interpreted C subscripts as Rich markup and wrapped JSON
strings. Commit `a65a6d328f` adds explicit production flag updates and raw JSON
export. All 49 relevant tests pass; a real export round-trips the uploaded C.
Shared issues #1528/#1529 are resolved. Do not use the older `public-source.c` or
`public-context.h` artifacts: they came from the corrupt pre-fix JSON display,
not from a corrupt scratch upload.

The first all-birth-hook retail capture timed out after 361.38 seconds (360-second
limit), before writing an initial stage. It reached the selected callback and
wrote 17 function identities, but no birth stream. This is missing evidence,
not a finding that the birth order matches. Issue #1530 records the command and
coverage gap. A follow-up isolates direct temporary-counter hooks, omits dynamic
object-allocator return breakpoints, and streams events for progress visibility.


The direct-only follow-up also timed out at the 360-second limit, reaching
fn_802545C4 without an initial snapshot or streamed direct event. Removing the
object-allocator hook group did not resolve the timeout; it does not establish
the cause, and these two runs use different source variants. Issue #1530 now
includes both observations. All owned diagnostic processes terminated.

Three source follow-ups completed: reusing `t` for old-dialog cleanup (either
initializer or assignment) regresses to 99.04375% with opcode similarity
0.99551318; both are rejected. Removing the redundant inner scope preserves
99.563934% and produces exactly identical target/current assembly and diff to
the retained reused-local form. The flat helper is now the working source and
was uploaded to the same public scratch, which retains its flags and score.
All eight probes are recorded in the attempts DB; the reusable partial-gain
pattern is `reused-return-local-can-shift-regalloc` in the mismatch DB.

Final export confirms byte-exact function source and context identical to the
repository extraction except for one trailing newline removed by the server.


## Embedded pointer and pending-state progress

The user explicitly requested staying on `fn_802545C4` until a verified 100%
match. Keep this target active; do not switch to the initializer or another TU.
Public scratch remains https://decomp.me/scratch/vdsqC.

Two retained ordinary source changes improve the callback from 99.563934% to
**99.6088%, 3566 instructions/frame440, 275 GPR-only differing lines**:

| Change | Score | Register-only lines |
|---|---:|---:|
| Assign a case-local slot pointer inside its first dereference, then reuse it | 99.60179 | 280 |
| Give case11 its own initialized `s32 next_state` | 99.6088 | 275 |

The pointer preserves fresh field loads after calls; it does not restore the
historical cached-slot discrepancy. Initializing the pointer at case entry is
not equivalent for code generation: it loses an opcode and scores99.5272%.
Embedding only the dialog-timer pointer is a smaller gain99.57936%; combining
both pointers gives the same99.60179% as the slot pointer alone. The cleaned
slot spelling produces byte-identical function assembly to its measured probe.

The focused unmodified-retail capture for the slot-pointer source checks3613
GPR operands and maps916 roots, with zero checked validation, operand-shape,
target-color, or fixed-register conflicts. It excludes193 post-allocation
operand rewrites and643 other rows; it is not complete compiler/object parity.
Both simplify and select replay reproduce1186/1186 captured decisions. The two
important addresses now receive target registers: slot addressr23 and
dialog-timer addressr26. Their permanent degrees remain18 and19.

A concrete rank model explains the pointer gain. Map oldroot311 to newroot43,
increment oldranks43..310, and leave the rest unchanged. Running the original
retail graph with only this ordering change reproduces **916/916 mapped new
colors**. No synthetic permanent-neighbor addition is needed for this result.
The pending-state follow-up similarly moves oldroot104 to rank43 and increments
43..103; it predicts all916 mapped ordinary colors. The actual source changes
five pending-state operands fromr27 tor23 and moves a nearby page address from
r23 tor24 at two instructions (that address remains unmatched). All three
originally queried target allocations are now correct.

Twenty subset probes isolate the earlier dialog-helper gain. Only call sites4,
6, and8 contribute, changing13,16,and16 instructions respectively. Every measured
subset equals the disjoint union of those local changes. This rules out that
helper edit as the explanation of the broader allocation cascade in these
measured outputs. Eight pointer/return/helper-interface forms and three scope
forms provide no additional retained gain.

Two allocator-guided permuter campaigns ran143 and421 iterations, reporting54
and258 compilation errors. The first three saved winners changed conditional
call behavior or cached a field across mutations and were rejected. Restricting
mutation passes yielded one candidate using a volatile local; this is not
evidence of a correct allocator role or source match. The fixed numeric target
IDs are not stable under arbitrary mutations. Import fidelity was checked by
splicing the callback and helper into the original TU and obtaining exactly the
retained baseline assembly before either campaign.

Issue1531 (a member called `buttons` confused with the scalar `buttons`) is fixed
in local commit50780877b6, with41 passing audit tests. Issue1532 records the
remaining whole-preprocessed-TU audit false positives. An earlier generated
root `debug_source.c` was accidentally overwritten by permuter debug mode; it
was regenerated from its unchanged old base, checked against the prior saved
source log, and restored. Future permuter debug runs use private directories.

Next lead: a bounded rank-insertion model strongly favors moving the first
case2 animation-loop counter later. The best sampled insertion reaches902/916
mapped target roots, but is only a diagnostic ordering. Ten natural carrier and
inline source probes alter the instruction shape: the `int` carrier and six
inline forms introduce a second zero initializer in the right-input loop. The
carrier additionally grows the frame by8bytes; the `s32` carrier spills and
adds more instructions. Preserve the target's sharing of the button-mask zero
with the following loop counter when pursuing this family. Eight further zero-init
placement probes moved the right-loop initialization before its audio call. All
still add the zero instruction. Reducing the carrier's existing padding by8bytes
restores the frame only (diagnostic99.67442%,3567instructions); it is not retained.
No carrier or new animation inline is retained.

A separate1000-sample ordering search across51 wrong object-backed webs reaches
883/916 targets. It includes inline/generated objects and is exploratory, not a
C declaration-order witness or an exhaustive impossibility proof.

The [dialog-cascade evidence](matching-evidence/mnsnap/2026-09-06-dialog-cascade/)
archives the sources, ordinary reports, two retail captures, rank-model checks,
permuter configurations/winners, and final TU verification. Final public export
is byte-identical to the retained function and preserves the353369-byte context
and production flags. Its score is 1560/356600 (99.56253505%).
All17 previously matched snapshot functions remain100%, initializer97.853165%.
Configure, Ninja, and DOL byte comparison pass; source is restored to99.6088%.


## Shared counter and card-status pointer continuation

The user explicitly requested staying on `fn_802545C4` until a verified complete
match. Do not switch targets because of a residual ceiling. The public scratch
remains `vdsqC`; public updates use the clean retained source.

A case2 `s16* card_status` declared after `s32* active_slot` and defined in the
first constant-index-zero read improves the clean source to 99.64947%. The other
two constant-index-zero reads use `*card_status`; indexed accesses still use the
global array. This preserves fresh reads after calls and all 3566 instructions.
Moving the declaration before the slot pointer is worse; initializing it at
case entry changes instruction shape. Clean source evidence is
`status-pointer-retained-source.c`, with 247 GPR-only differing lines.

Using one promoted `struct { int index; } cursor` across all three case2 loops
preserves the zero shared by the 64-bit button mask and loop initialization.
Isolating only the first loop had added another zero initializer. Together with
the card-status pointer this reaches 99.92008%, 53 GPR-only differing lines.
The aggregate grows the frame by eight bytes; the saved exploratory variant
reduces existing PAD_STACK312 to304 solely to compare allocation at frame440.
This is not yet clean production source or a complete match. Signed-long fields,
one-element integer arrays, and single-member unions produce identical code;
unsigned and narrow fields change compare or extension instructions.

The unmodified retail capture for this candidate checks 3613 GPR operands,
916 mapped roots, and all1186 simplify/select rows. It reports no checked
validation, shape, target-assignment, or fixed-register conflicts. It excludes
193 post-allocation operand rewrites and643 other rows, so its value-flow claim
is limited to checked operands. Eleven mapped assignments remain wrong.
A greedy rank insertion replay reaches all916 mapped target assignments with
four changes, applied sequentially: root60 to rank365, root61 to rank345,
root339 to rank331, and root41 to rank44. These represent the two input-loop
counters, an early active-slot field address, and pending state. This is a
source-order hypothesis on a fixed graph, not an actual compiler match.

New ordinary source families and terminal results:

- Six counter-sharing parameter/return variants still add one instruction.
- Four all-loop carrier variants preserve the stream; frame normalization is
  diagnostic. Six plain scalar counter variants do not reproduce the gain.
- Four address-taken scalar counter variants spill and add15 instructions.
- Four aggregate counter-plus-offset layouts add an instruction and grow to456.
- Eight early field-address variants do not improve99.92008; simple initialized
  pointers and parent-slot staging are neutral, while early JObj initialization
  changes scheduling.
- Six all-loop helper variants, varying counter type and context parameter,
  each add an instruction and grow the frame to456.
- Eight index-from-byte-offset variants add6-9 instructions or otherwise change
  the stream; no source candidate retained.
- Seven pending-state scalar/scope/reuse variants are neutral on the promoted
  counter seed. Two whole-case11 inline helpers add92 instructions.
- Eight carrier type/storage variants confirm integer aggregate promotion is
  the common behavior; enum and narrow/unsigned types fail the stream guard.

The complete source/diff/model evidence through these probes is hash-verified in
`docs/matching-evidence/mnsnap/2026-09-06-counter-cascade/manifest.json`.
Attempts are recorded in the local DB. Pattern
`shared-counter-scope-preserves-mask-zero` records the empirical sharing result
and explicitly labels the source-order explanation unresolved.

A focused read-only retail object snapshot completed successfully. Counter roots60
and61 belong to generated integer objects `@1761` and `@1760`; byte-offset77
belongs to generated `@1741`. Root41 is the named `next_state` local, root44
`card_status`, and root56 the named `byte_off2`. The early address roots332,338,339
are generated `@1486`, `@1480`, `@1479`. This confirms ownership at coloring, not
when the objects were created. Capturing individual birth events remains blocked
by the earlier timeout issue1530. The object snapshot and hook are archived.

## Selection and card-status helper gains — 2026-09-07

Direct selection translation arguments remove two helper locals and improve the
promoted-counter source from 99.92008% to 99.9327% after restoring the measured
440-byte frame. Reusing the promoted counter field for the pending-state value
then reaches 99.9355%. A card-status helper taking the slot argument fixes the
three early address roots; its extra eight-byte home is compensated by reducing
existing padding from 312 to 304, reaching 99.949524%. No-argument and state-pointer
helpers do not reproduce this gain. Removing the unused `i`, staging the fresh
slot in its parent local, using a register parameter, or inlining the status
condition does not remove the extra home or further improve coloring.

Twelve for/while/do/increment variants add no gain; reversed increment order
changes instruction order without improving allocation. A 600-second stock
permuter run completed 710 iterations with 45 compile errors and no saved
candidates. Its score includes 227 anonymous-relocation spelling differences
in addition to 53 true GPR lines on the older seed (tool issue #1536). Ordinary
compilation remains authoritative.

### Publication steering after PR creation
The user manually marked #3389 ready for review and merged current upstream into
the PR branch, producing5bf90ac28b. They confirmed on2026-09-07 that the community
plans to merge improvements immediately. Preserve ready status and the merge;
do not restore draft status. Continue to publish best verified progress.

## Right-loop inline parameters — 2026-09-07

A helper taking the initial index, initial byte offset, and active-slot pointer
for the right-input animation loop reaches **99.95794%**, preserving all3566
instructions/frame440. The right counter and thumbnail-image pointer now match.
The remaining26 instruction lines are a right-loop pointer/offset swap (r20/r19
versus r19/r20), left counter/offset swap (r20/r21 versus r21/r20), and pending
state r27 versus r23. Both parameter orders gave the same right-loop result.
Using the helper for the left loop removes the target's separate constant4
instruction, so applying it to both branches is not a valid improvement.

The extracted helper inherited raw byte-offset accesses and the commit check
flagged the newly moved expressions. Ordinary probes showed that typed array
views or grouping the offset sum inside the load change instructions. The
existing M2C_FIELD macro with an integer base-plus-stride and a named offsetof
reproduces the winning instruction stream exactly and passes the commit checks.
This is provisional strided access; it does not establish final source cleanup.
All17 matched neighbors remain100; full build/DOL comparison passes.

Retained local commit a71179d015; published PR3389 commit ff1152914f. The user's
remote upstream merge5bf90ac28b was preserved; initializer integration is
075f62372e. Public scratch updated, score315/356600. No additional communities
were messaged. Retail loop-parameter capture is being mapped separately.

Retail verification completed for the99.95794 source:916 mapped roots,3613 checked
GPR operands,1187/1187 simplify/select replay,zero checked shape/value-target/fixed
conflicts. Five mismatched roots remain:397 r19→r20 (right offset),345 r20→r19
(right card-status walk),59 r20→r21 (left zero/counter),55 r21→r20 (left offset),
60 r27→r23 (pending state).193 postallocation operand rewrites and643 unmatched
rows are excluded, so this is not a universal equivalence proof.
Public source byte-equality is verified:315/356600 (99.9116657319125% public),
61704 source bytes, SHA2564e3cb513e73b1c51373b0320633aca9e9091afcb8f7d2d2fcd98c5a67e9c14cc.
Current main fork incorporatesc4a88262e7 at26e4265793. Current PRff1152914f is
open/ready with checks pending. Retained C is byte-identical between worktrees.
The pressure report's scalar-name attribution is ambiguous and its `spilled`
labels are simplify annotations; retail successful allocation supersedes those
automated interpretations.

## Five pending-state instructions — latest steering

Passing the right-loop offset by reference fixes its pointer/offset swap
(99.971954%,18 lines). Reusing that pointer-offset helper for the left loop also
preserves the separate constant4 and fixes its counter/offset colors, reaching
**99.99299%,5 lines**. Returning the pending-state local to the original `state`
variable has identical instructions and is retained for clarity. The remaining
array cursor wrapper now belongs only to the initial refresh loop.
Retained source commit70164e9a00; build and commit checks pass. All17 matched
neighbors remain100, the frame440 and3566 instructions agree, DOL byte-equal.

PR3389 merged while these final local gains were being verified. User instruction:
“3389 just merged so we’ll need to open a new PR. Let’s just see if we can get
the remaining differences first before we do that.” Do not open a new PR yet.

Counter-wrapper removal still regresses (s32/int:99.60011/99.60853, frame432).
Named pending case-local variable gives7 differences; function-scope int and
reusing state give5. A case-local pointer to pending state adds4 instructions
and8 frame bytes. These spelling families are exhausted on this seed.

## Final five-line resolution and limits

The five-line retail capture completed with 916 mapped roots, 3613 checked GPR
operands and 1187/1187 simplify/select replay, with no checked shape/value/fixed
conflicts. Only pending-state root 102 had a wrong color (r27 instead of r23).
Moving its modeled creation rank next to root 103, the first explicit move-JObj
clone, predicted all target colors. This directed the final parent-pointer reuse
experiment. Reusing `jobj` only for that first move update gives an ordinary C
100% result; the exact new clone order has not been captured, so that causal
mechanism remains an inference. Six declaration-order changes were neutral.
Removing the initial JObj temporary added one instruction and was rejected.
The winning probe compiled successfully; its collector then expected a stack
classification key absent at 100% and stopped. The saved result and source
establish the win; unrun planned probes are not counted as failures.

Mismatch DB patterns now include `inline-offset-reference-preserves-init-coloring`
and `parent-pointer-reuse-fixes-pending-state-color`, with success records. The
retained/matched attempt is recorded with exact numbers in its note. The attempt
ledger rounds to one decimal and discards later recovery snapshots at the same
rounded score; this is reported separately, and exact final source/evidence are
persisted in git instead of relying on that rounded high-water slot.

## Publication and final persistence

Follow-up ready PR: https://github.com/doldecomp/melee/pull/3392, head9b7bb943c7.
The explicit user request to publish was fulfilled after completing the function.
Source is byte-identical between matching and PR worktrees. Match claim linked
via the CLI. The final25 source-family outcomes are recorded with exact values
in notes, and both new mismatch patterns have success records. Attempt ledger
precision/snapshot issue1538 is open. Build-cache issue1539 is resolved: backing
up the damaged .ninja_deps and rebuilding once fixed the regeneration loop;
a direct split alone had not cured it. Never overlap builds in one worktree.
Existing unrelated untracked files and the PR worktree's tools/decomp.py overlay
were not included. No build/probe jobs remain. CI status at publication is saved
in the archive; do not claim CI completed from the local build result.
