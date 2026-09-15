# Snapshot initializer checkpoint — 2026-09-07

Current upstream baseline: **98.06646%**, merged at `bbe79294b9`; see final section.

Active function: **`mnSnap_80257F24`**, module `mn`, scratch [WvrZ0](https://decomp.me/scratch/WvrZ0).
Retained source: **97.89181%, 647 instructions, 400-byte frame**, commit
`f55521849d`, following vector-layout correction `2586f64f50` (97.88254%).
The initializer is claimed by `codex-d82d`. All other 18 functions in this TU
remain 100%, including callback `fn_802545C4`, merged through PR #3392. Original initializer PR #3375 has merged;
PR [#3395](https://github.com/doldecomp/melee/pull/3395) merged both gains as
`7a44e77cb6`, integrated locally at `218532b56e`. Future source gains need a new
PR. No source gain was retained from the latest resource-reference experiments.

The thumbnail vectors now have the target offsets: `end_pos` at160 and
`start_pos` at172. Reversing their declarations and reading `snap->thumb_end`
directly fixes the vector placement; assigning `mnSnap_GetCardStatus(snap)` to
a named pointer before its second-element store restores the original frame
without shifting the vectors. Block versus function scope of that pointer is
neutral. A direct field pointer instead of the getter loses the gain. Moving
`main_joint` assignment immediately before the archive call adds a small setup
improvement while preserving those structural corrections. No padding was added.

The remaining differences are principally archive-call argument scheduling,
spill/reload placement, and register roles (including the late MR/ADDI copy
encoding and end-marker register). This is not an allocator-only or completed
match. Full build with required prototypes and original DOL byte comparison pass;
the TU is still Linkable, so the normal DOL uses the original object and is only
an integration check for this partially matched TU.

Evidence: [initializer layout manifest](matching-evidence/mnsnap/2026-09-07-initializer-layout/manifest.json).
There are 155 ordinary source candidates in this pass. The first 39 comprise: 8 helper ownership,
5 page-home,8 caller-vector,6 vector-shape,5 text-counter,3 card-status-home,
and4 final archive-boundary probes. Thirteen register/loop probes and six
conversion/interpolation probes follow below. Only the card-status/vector combination
and late main-joint assignment were retained. Ordinary repeated final verification
is separate from that candidate count. The previous main-load, slot-load,
copy-neighbor, and vector-home archives remain useful; do not repeat exhausted
families just because the active target changed back from the callback.

## Retail trace and diagnostic limits

The unmodified retail backend trace completed and passed its raw-object parity
gate. It records local offsets relative to the base/call area:8+144=152 bytes.
On the old97.853165 baseline, observed Vec3 objects @1853 and @1852 sit at
relative12/24, agreeing with ordinary offsets164/176. The following named
`photo_count`, `zero`, and warning-resource homes follow those vectors. This
motivated testing a named getter-result pointer rather than inventing padding.
The final transformed home list was not recaptured; its effective vector/frame
layout is verified through ordinary emitted instructions.

The generic fidelity report has794 equal facts,571 differing,64 retail-only,
and36 debug-only. These are raw-ID comparisons; they do not establish a semantic
compiler disagreement without mapping identities and rounds. The trace reports
one early PCode snapshot skipped with a final-scheduler fallback, and its separate
object-event capture is partial with zero events, despite the frame list being
present. Do not call it a complete object-creation history. Issue1507 (multi-round pressure colors) is now fixed locally in `1e05e7c41e`;
use branch-local PYTHONPATH until the shared tooling baseline incorporates it. Issue1518 (r0 stack accesses mislabeled as LR saves)
remain relevant; do not trust those report labels as source evidence.

Mismatch pattern `inline-result-home-restores-vector-layout`, its success record,
and exact-valued attempt notes are persisted. The ledger's one-decimal recovery
limitation1538 is still open; git and the hashed archive retain the exact best
source. No build, probe, or compiler-capture jobs remain at this checkpoint.
Older sections below are historical and superseded by this header.

## Bounded experiments and diagnostics

- Baseline slot getter: direct-return97.0881; output-parameter97.11746; embedded load96.525505; named-local-return96.48841 with408-byte frame. None retained.
- Named archive argument97.39104; named loaded-model argument96.54405; separate main field reference97.69088 retained; separate slot argument96.51314.
- On the retained seed, direct field load96.7728/frame392; adding the named archive argument96.771255/frame392; embedding the separate reference assignment97.11746/frame400; adding the slot output helper is neutral. Avoid these repetitions.
- Semantic donors top out at0.976 with shorter menu/scene constructors. Window hits0.931 are generic JObj code, not the unmatched archive-call construct. No structural twin found.
- The baseline debug dump has two failed GPR coloring rounds followed by a successful third. `debug inspect analyze` agrees with final code, but `lifetime-pressure` reports earlier colors for several roots (53r20 instead of27;41r24 instead of18;45r28 instead of23). Filed issue1507. Its blocker report is not reliable for this capture. Source probe/restore also made its freshness timestamp stale; do not treat that stale warning as the explanation for the within-capture color disagreement.

[Evidence manifest](matching-evidence/mnsnap/2026-09-06-main-load/manifest.json) contains the baseline capture, measured reports, negative summaries, donor results, and latest full-build log. Mismatch DB record: `separate-archive-output-from-model-load`. The source gain passed normal commit hooks. The later imports of unchanged upstream code required a narrowly scoped hook exception for known issue1496 (upstream double literals); canonical source was preserved and the full build reverified.

## Embedded slot-load follow-up

The retained source is:

```c
jobj2 = *(slot_jobj_ptr = &snap->slot_a_jobj);
snap->blank_img = jobj2->u.dobj->mobj->tobj->imagedesc->image_ptr;
```

This reproduces the target sequence at +0x2FC through +0x318, including direct
address materialization in r28. The extra `mr r28,r4` is gone. Assigning the
same load to `jobj2` in a separate statement was neutral; embedding the address
in the entire image-chain expression had previously regressed. The combined
definition and named load are the measured lever, not embedding in general.

The following ordinary probes were restored after measurement:

| Family | Match % | Frame / instruction delta |
|---|---:|---|
| Separate slot assignment, load into existing jobj2 | 97.69088 | 400 / +1 |
| Slot pointer struct or array | 96.24884 | 400 / +1 |
| Defer embedded slot assignment to sub-object extraction | 97.66615 | 400 / -1 |
| Blank-image return helper | 97.658424 | 400 / +1 |
| Named warning or page resource string | 97.846985–97.84853 | 400 / 0 |
| Embedded warning or page name assignment | 97.853165 | 400 / 0, neutral |
| Named or embedded main joint/animation resource string | 96.41731–96.54868 | 400 / +1 |
| Extract archive load into an inline helper | 97.05564 | 400 / -2 |
| Separate later animation/material pointer references | 96.4915–96.49304 | 400 / +1 |
| Separate later main shape-animation reference | 97.82071 | 400 / 0 |
| Separate all three main animation references | 96.58578 | 400 / -2 |
| Separate later warning model reference | 97.54405 | 400 / 0 |
| Separate later arrows model reference | 97.6847 | 400 / +1 |

The fresh retained debug capture still has three GPR allocation rounds, two
failed and one successful. Issue1507 remains open; do not trust a pressure
report that attributes earlier-round colors to final code. The successful
capture and final ordinary assembly are archived for follow-up.

The [slot-load evidence](matching-evidence/mnsnap/2026-09-06-slot-load/manifest.json)
contains all21 source candidates, reports, the retained capture, TU verification,
and PR details. Mismatch DB record: `embedded-address-load-removes-copy`.
Project memory and the shared attempts ledger also record the source gain.
The publication update used a new worktree under d82d; the other thread's
older snapshot PR checkout was not modified.

No matching probes, compiler captures, or permuters are running at this
checkpoint. Remaining work is the initializer's archive-call setup and
register roles, then the update routine, before linking the TU.

## Late copy rewrite and declaration-order follow-up

The retained source remains 97.853165%, 647 instructions, frame400. This
follow-up retains no source change. The difference in opcode counts is one
extra `mr` and one missing `addi`; other residuals include scheduling,
stack operands, and register roles. Equal counts do not prove equal data flow.

The exact retail compiler was imported and validated by `debug retro
ghidra-setup`: GC/1.2.5n SHA-256
`ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
Its MR opcode is0x8B. Registrar0x004C6320 puts five handlers on that opcode's
list; the last registration,0x004C8B90, is first in the resulting list.

That handler changes MR to ADDI with an immediate zero when all of these hold:
the candidate's flag0x80 is clear, it has at least two operands, its source
register is not r0, and either immediate instruction-list neighbor has
`flags & 3 == 1`. It does not inspect C expression spelling. This is a
verified static rule; the interpretation of flag class1 as an instruction
class is separate from the literal condition.

The retained PCode agrees with the adjacency explanation. Before the late
peephole, `mr r6,r31` is between a store and a page-pointer reload. The copies
`mr r8,r21` and `mr r10,r20` are adjacent. The latter two become ADDI in
`AFTER PEEPHOLE OPTIMIZATION`, while r6 remains MR. Final scheduling follows
that pass and changes the order again. Runtime raw neighbor flags were not
captured, so this is static-rule plus stage evidence, not an exact breakpoint
trace of this decision. Do not substitute final assembly adjacency for the
earlier instruction-list adjacency.

Tested34 ordinary source variants, including an unchanged declaration-position
control. Moving `main_animjoint` across all21 pointer-declaration positions is
neutral or slightly worse. Direct/embedded archive arguments are neutral.
A direct return accessor produces the desired r6 copy encoding but removes
three instructions and shrinks the frame to392 (96.76353%). Adding its own
local restores frame400 but still removes three instructions (96.771255%).
Global, staged, and output-parameter getter variants are neutral or worse.
Typing the actual main joint/animation/material/shape descriptors, individually
or together, is neutral. All were restored.

The isolated full-TU permuter uses the retail compiler, actual Ninja flags,
frozen source, and the existing function-splicing wrapper. The imported
standalone defaults omit build flags, including MUST_MATCH; issue1432 already
describes this import family. The wrapper avoids that context problem. Its
base score is1750; transplant verification reproduces97.853165%. The bounded
run stopped cleanly after146 completed iterations with40 compile errors and
no saved better candidate. No owned runner or staged source remains.

The verification tool initially reported a stale baseline97.82071 from the
last reverted probe, rather than the restored source97.853165%. That apparent
delta is not a gain; issue1516 records the stale-report problem. Fresh ordinary
verification after restoration confirms97.853165%, the other18 TU functions
are unchanged, and the full build/DOL byte comparison passes.

The signed instruction deltas in the preceding table were corrected by
counting instruction records: the tool's `structural.line_delta` is unsigned.
Use `signed_instruction_delta` in the evidence manifest, not that raw field,
to distinguish added from missing instructions.

The [copy-neighbor evidence](matching-evidence/mnsnap/2026-09-06-copy-neighbor/manifest.json)
records source probes, stage excerpts, compiler-audit provenance, search logs,
and final verification. Compiler binaries, Ghidra databases, and full compiler
function exports remain in ignored local storage. Mismatch DB record:
`neighbor-gated-mr-to-addi-rewrite`. A useful next source lead must change the
copy's pre-peephole neighborhood while preserving the required spill/reload
sequence; the tested declaration, argument, accessor, and type forms do not.

## Assignment order and thumbnail vector homes

Upstream `22dba004cd` is merged at `c84fe9ea67`. The restored source still
scores **97.853165%**, with 647 instructions and a 400-byte frame. All 19 TU
functions were checked against the report: the callback is 99.86399%, and the
other 17 are 100%. The full build passes the original DOL checksum and byte
comparison. Reported data matching is now **100% (1211168/1211168 bytes)**;
function matching remains 19820/19828 and linked units remain 1125/1130.

The user reports that another contributor has matched `gmtoulib` and is
preparing a PR. Treat that entire TU as reserved even without a published PR
or active CLI claim. This is contributor-announcement evidence, not a local
verification of the match. Thread `01a0749c-030f-73b1-abae-0aeb453a792b`
has moved to `fn_803B6820`; avoid the JPEG decoder and the encoder PR as well.
Our active target remains `mnSnap_80257F24` in draft PR #3375.

This follow-up compiled 36 ordinary full-TU source probes, including a repeated
declaration-order control. No source change was retained. The six assignment-order probes were
neutral except deferring `main_joint`, which scored 97.86244%; a separate
last-assignment form reproduced that result. Both still have the unwanted
`mr r6,r31`. Embedding that pointer assignment into its call argument adds an
instruction (96.525505%, 648/frame400), while a direct field argument removes
two and shrinks the frame (97.027824%, 645/frame392).

The thumbnail block supplies a separate source lead. In the retained source,
`start_pos` begins at stack offset164 and `end_pos` at176. Target offsets are
172 and160, respectively. Reversing their declarations changes their order
to176/164 without changing the score. Replacing the named end-marker argument
with the direct `snap->thumb_end` field then reaches the exact vector offsets
172/160, but shrinks the whole frame to392 and scores97.80525. Thus vector
layout and total frame size must be measured independently. The inferred
four-byte local-area effect is empirical; its precise storage owner has not
been traced in the compiler.

Other bounded thumbnail results:

| Source family | Result |
|---|---|
| Reorder/reuse marker declarations, including after the vectors | 97.853165%, frame400; wrong vector offsets remain |
| Caller-owned marker via output parameter, or direct return getter | 97.853165%, frame400; wrong vector offsets remain |
| Getter with its own named local | 97.77589%, frame408 |
| Move the entire thumbnail block into the caller | 97.35085–97.38022%, frame392 |
| Caller reads positions; inline helper creates the five thumbnails | 97.77589–97.86399%, frame392–400 |
| Group vectors in a struct or array | 95.228745%, 645 instructions/frame384 |
| Existing `HSD_JObjGetTranslation2` on either/both reads | Neutral; no useful frame or register change |
| Name the start marker instead of the end marker | Neutral relative to reversed vectors |

The highest caller/loop-helper variant has the correct start offset172 but
puts the end vector at184 rather than160. The aggregate variants obtain the
target end-marker register r28, but also remove two instructions and disturb
the archive setup. These are archived structural leads, not retained fixes.
All non-aggregate thumbnail variants retain the target instruction count647.

`debug suggest frame` supplied no specific unused-home remedy. Its report
misclassifies ordinary r0 stack loads/stores as link-register saves;
issue1518 records the reproducer and the unconditional classification in
`frame_reservations._access_kind`. Do not interpret those labels as evidence
of actual LR traffic.

The [vector-home evidence](matching-evidence/mnsnap/2026-09-06-vector-homes/manifest.json)
preserves all candidates, ordinary diffs, frame diagnostic, and final
verification. The shared attempts ledger, project memory, and mismatch record
`inline-vector-homes-versus-frame` contain the follow-up. No probe compiler or
permuter remains running. The next investigation should reconcile the measured
vector offsets, total frame, and marker lifetime rather than repeat the
declaration/getter families above.

### End-of-pass upstream refresh

The contributor subsequently opened [#3383, match and link gmtoulib](https://github.com/doldecomp/melee/pull/3383),
head `86d3b4665ec5713a05bef240277e1db94ab72411`. Its GALE01 link, diff,
and test checks pass. The PR remains open and excluded from our work; its
source was inspected without applying it locally. The changes combine reuse
of the existing `k` loop counter, a named `jobj2` load before a translation
setter, and direct global field accesses in another switch case. This is
useful donor evidence for interactions between separate state-machine
regions, not a verified fix for either snapshot residual.

Upstream CPU input cleanup `876b6e0346` also merged during this pass and was
imported at `6ab3cbe98f`. The post-refresh build result and ownership evidence
are saved beside the vector-home archive. The archive itself records the
earlier `22dba004cd` experiment baseline and is unchanged.

### gmtoulib merged and callback follow-up

PR #3383 subsequently merged as `a392908a20`, imported locally at `7d22ea542e`.
The restored full build verifies all 49 gmtoulib functions and data exact, with
the TU linked. Global status is now 19821/19828 functions, 1126/1130 linked TUs,
and 100% data matching. Snapshot scores remain initializer 97.853165% and
callback 99.86399%, with the other 17 functions exact.

The active claim moved to callback `fn_802545C4`. Its 44 new donor/lifetime
variants, the identified second-value-numbering transformation, and the tested
PCode parser fix are recorded in [the callback notes](mnsnap-update-matching-notes.md#combined-donor-follow-up).
No source gain from this follow-up was retained; PR #3375 is unchanged.

## PR publication and final-round pressure fix — 2026-09-07

PR3395 is open/ready and changes only mnsnap.c. All ten applicable checks passed;
two deployment/wiki jobs were skipped. Source still97.89181,647instructions and
frame400, with correct vector homes. Latest ordinary rebuild reconfirms it after
13 additional probes: arrows declaration/assignment swaps (3), int loop index,
delta evaluation order (2), loop forms (4), and register hints (3). None retained.
The not-equal loop condition changes branch shape and is worse; while/do/for
increment placement and register hints are byte-score neutral.

Fixed pressure issue1507 in local tooling commit1e05e7c41e. The facts adapter used
the first COLORGRAPH section, including failed pre-spill rounds. It now chooses
the last section per register class; initial-graph tiebreak searches are unchanged.
A regression test checks colors and edges from the final round despite earlier
failed coloring and a subsequent FPR section. Both pressure suites pass334 tests,
4 skipped. The actual initializer pressure now agrees with analyzer and emitted
instructions: v85 isr31, blocked fromr28 by v197 (the lis0x4330 conversion constant);
v41 isr18 andv39 isr17, with the two arrows-resource roots blocking one another.
The source-attribution heuristic still incorrectly names the base of v85; use its
actual first definition lwz85,180(snap) and emitted end-marker role instead.

The decisive scheduling boundary is visible in the retained debug dump. Before
global optimization, the end-marker's final z load precedes loop setup. By AFTER
PEEPHOLE FORWARD, lis197,17200 appears immediately before that last load, creating
an85/197 interference edge. Target reusesr28 for the pointer and then the constant,
so this overlap must disappear; merely permuting desired register numbers is
insufficient. Equivalent loop forms tested so far do not alter this placement.

Raw instruction bytes of the full initializer compiled by debug and retail are
identical (2588 bytes, SHA25610b2c1e3a574d8d5fdcb0afbdf969c1e62615e1902bd3dd25032cdf257b87536).
This independently constrains interpretation of the earlier raw-ID fidelity
report: its571 differences are not proof of different emitted code. Final source
and corrected pressure evidence are archived; no capture/build/probe jobs remain.
The goal is still active: finish initializer100 and update the PR with future gains.

## Conversion placement probes — 2026-09-07

Six additional natural source variants all regressed and were restored:

| Variant | Match percentage | Instruction delta |
|---|---:|---:|
| Named float index before calls | 93.05873 | -6 |
| Named float index after calls | 95.717155 | -8 |
| Interpolation inline taking s32 | 97.786705 | 0 |
| Interpolation inline taking f32 | 95.655334 | -8 |
| u32 thumbnail counter | 96.67079 | -1 |
| s16 thumbnail counter | 96.777435 | +3 |

The s32 inline keeps the instruction count but grows the frame from 400 to
416 bytes; its score does not support retaining it. Conversion locals remove instructions and change the frame size, so they
do not preserve the target structure or solve the observed scheduling edge.
The ordinary rebuild of the restored source reconfirms 97.89181%. Source,
reports, and result summary are included in the initializer evidence manifest;
the six rejected probes and retained checkpoint are recorded in the attempts DB.

## Grouped vectors and refreshed permuter — 2026-09-07

Ten grouped-vector variants were rejected. Named pointers to either or both
array elements scored 90.08501–93.56723%, frames 384/392. Both named pointers
introduce three extra assertion calls (980 twice, 917 once); pointer constness
does not remove them. Direct vector addresses at the accessor calls remove
those paths, but still give 645 instructions/frame384 at 94.75734–94.99227%.
This is recorded as mismatch pattern `named-vector-pointer-retains-inline-asserts`.
The exact compiler pass responsible for this visibility effect was not traced.

Five initializer value-type probes were also rejected: int, s16, or u8 zero
and a const state pointer are neutral. A const zero retains647 instructions
and correct vector offsets but shrinks the frame to392, scoring97.81453%.

The full-TU retail permuter was refreshed from the current source, including
all six mutable helper/initializer definitions. Base score1645 transplants at
97.89181%. The verification command's baseline94.99227 was the stale preceding
probe report (known issue1516), not an improvement over retained source. The
bounded four-worker run completed532 iterations with173 compile errors and no
saved better candidates; mandatory triage confirmed no candidate sources.
At180seconds SIGINT printed Exiting but failed to terminate within30seconds;
the wrapper terminated only the owned process group. Final exit-15 at210seconds
and a subsequent process audit verify no owned runner/compiler remains. This
recurrence is appended to issue1472.

The scheduler explanation command did not support the requested lwz/lis
code-offset pair and returned missing/UNKNOWN; it provides no new scheduling
proof. The prior observed pre-color scheduling edge remains valid evidence.
Restored ordinary source is97.89181%, and all other18 TU functions remain100%.
There is no source or PR update from this pass; PR3395 remains open atb46c3e25b9.

## Resource-register isolation and source-search correction — 2026-09-07

A GPR-scoped diagnostic override (`gpr:41:17,gpr:39:18`) changes exactly six
instructions at offsets dc,100,1e0,204,3c4,474. All other initializer bytes are
unchanged, including archive scheduling and the end-marker conflict. This
isolates the arrows resource swap from the broader archive residual. An earlier
bare-ID override also changed FPR nodes39/41; that run is not valid evidence of
GPR-only isolation. Neither diagnostic object is shippable source evidence.
The opcode inventories each contain647 instructions: target has one more addi,
current one more mr. Equal inventory does not prove equal instruction ordering.

Issue1543 exposed the same first-round mistake in the separate select-order
source scorer. Commit746ea8dd80 selects the last coloring round per class.
The added multi-round test covers a failed earlier GPR round and a later FPR
section; the complete select-order suite passes164 tests. Use branch-local
PYTHONPATH until the shared tooling baseline includes the fix.

The read-only directed plan proposed two invalid field-load transformations:
redirecting an archive output from the persistent state field into a local.
Both were rejected before compilation and reported as issue1544. Do not run
those generated probes as matching candidates. The plan's other suggestions
were generic declaration/width/scope changes, not a new proven arrows lever.

Fourteen ordinary source probes were restored:

- Direct-return archive getters for arrow joint/shape, singly or together:
  all97.89181, identical code.
- Correct descriptor pointer types for those fields and aliases, singly or
  together: all97.89181, identical code.
- Separate arrow/warning creation inlines with state/resource parameters,
  singly or together: all97.89181. Global-state forms score97.85935 and97.82999;
  both retain647 instructions/frame400 and the wrong arrow pair.
- Donor-inspired nested asset structure: direct access97.89181, neutral;
  early/late dedicated asset-base pointers95.52241/95.64142, rejected.

Matched menu donors inspected were mnGallery_80259868, mnCount_Create, and
mnDiagram_Init. They support direct field or aggregate-asset references but
provide no exact spill/schedule twin for this initializer. Restored ordinary
build verifies97.89181 and all18 neighbors100. PR3395 is now merged; no new
source improvement or PR was produced by this pass.

## Archive-copy repair combinations — 2026-09-07

Thirty-three source candidates tested combinations of the main animation-output
getter, embedded first-output assignment, separate later material/arrows model
references, first-output reuse, and main joint-output helper variants. None was
retained. The exact reports and full candidate sources are archived.

The strongest numerical lead was98.01082%, with645 instructions/frame400. It
uses the first archive output variable again for the model load, leaving the
old `main_load` declaration unused. Removing that dead declaration yields
97.98609% and frame392, still645 instructions. The eliminated pair is exactly
one stw and one lwz; opcode inventories otherwise agree, including the desired
addi copy encoding. This is a spill/frame tradeoff, not a complete source win.
The equivalent named animation-output getter yields97.964455/frame400 but
shifts start/end vector homes from172/160 to176/164. Thus neither higher score
preserves the existing structural corrections. Do not promote these variants
based on fuzzy score alone or retain the dead declaration as hidden padding.

The remaining main joint-output helper and global animation-getter combinations
were worse. The signature advisor produced low-confidence register-presence
findings but no validated source fix; the archive prototype and actual argument
roles remain consistent with the target. No prototype change was made.

Mismatch DB pattern `unused-pointer-local-masks-frame-regression` records the
cleanup comparison. All33 experiments are recorded as reverted; the ledger's
numeric best may now round to98.0 despite no retained source gain. Authoritative
retained source remains f55521849d at97.89181%,647instructions,frame400 with
correct vector homes; ordinary final verification reconfirms all18 neighbors100.
PR3395 has merged and this pass produces no new upstream PR.

## Stable resource-name data and spill probes — 2026-09-07

Fourteen further source variants tested naming the page/warning strings on the
clean645-instruction/frame392 candidate, then an explicit resource-name data
model. No matching gain was retained.

The original resource block is644 bytes at data offset0x184. A file-local
`mnSnap_ResourceNames` struct with21 named char arrays preserves each observed
padded extent. Replacing archive literals with these fields leaves the original
initializer code at97.89181. On the final named-resource probe, raw.data bytes
match the target exactly (1032 bytes), reported data matching remains100%, and
all18 neighbors remain100. The model is archived as `resource-name-struct.c`;
it is not installed in the retained source. This gives a controlled way to
name or move resource-address evaluations without reordering literal bytes.

In contrast, an early page-name literal changes its pool position to0x184,
ahead of the original main name. The equivalent named-field probe preserves
data but still scores97.19165:647 instructions/frame400, with the extra spill
materialized before the initial calls and the mr/addi discrepancy reintroduced.
Late named-field page variants remain97.98609; late warning variants98.00928.
Both retain645 instructions/frame392, so neither repairs the structural deficit.
The global string model itself is neutral, not evidence of a completed match.

Mismatch DB `named-resource-strings-preserve-pool-layout` records the validated
data model. All14 probes are reverted in the ledger. Restored ordinary source
is97.89181 with18 matched neighbors; no new upstream PR was created.

## Public scratch and page-name lifetimes — 2026-09-07

The initializer is published at https://decomp.me/scratch/WvrZ0. Its source
exactly equals the retained initializer and compiles successfully. Public score
is2786/64700 (about95.7%); local objdiff remains97.89181%. These are different
metrics, and full emitted-byte parity between the builds is not established.

Production context export had lost include filenames used by __FILE__ in
HSD_ASSERT. Restoring nested #line directives fixes the checked resource offset
from0x284 to0x290 and improves public score from2821 to2786. Tool commit
2cbe039d0a fixes create/update paths;49 tests pass. Issue1547 is resolved and
mismatch pattern flattened-context-filename-changes-pool records the cause.
This is a context fidelity fix, not a local C source improvement.

Seven page-name lifetime variants on the clean645-instruction named-resource
seed were rejected. Placing the name before memzero gives97.332306%,647
instructions/frame400, but materializes the spill too early. Six placements
after memzero all produce97.98609%,645 instructions/frame392. Moving among
those post-call boundaries is code-neutral. Exact Discord archive searches
for the initializer and varargs AND spill found no results.

The manifest now preserves141 manual source candidates. Retained source remains
97.89181%,647 instructions/frame400 with end160/start172 and18 matched
neighbors. PR3395 is merged; no fresh source gain or PR from this pass. Continue
on the initializer; the 100% goal is not complete.

## Thumbnail delta representation — 2026-09-07

Three additional source variants were rejected. Replacing the three scalar
steps with a Vec3 before the position locals scores97.785164; declaring it
after them scores97.81453. Both grow the frame to408 and leave the same
end-marker/conversion-constant scheduling overlap. Updating end_pos in place
before assigning the scalar steps scores96.04946 with frame400 and additional
memory traffic; the overlap remains. Retained source is restored at97.89181,
all18 neighbors100. Manifest now144 manual candidates; all three recorded as
reverted. Hashed window donor search found only generic GObj/translation
matches (best similarity0.931), no close thumbnail-loop donor. Open PRs3396
and3300 cover unrelated JPEG and ground types; no initializer collision.

## Warning-name spill decision — 2026-09-07

Three named-resource controls on the retained source are all97.89181%,647
instructions/frame400: warning-name local just before archive setup, local
after memzero, and a warning-name inline getter. All reverted. Naming alone
does not fix the archive spill choice; manifest147 manual source candidates.

Target holds warning name (data+908) inr27 and spills page name (data+760).
Current holds page name inr27 and spills warning name. Retained PCode identifies
warning asGPR141, page asGPR136. Warning141 is already SPILLED in the first
COLORGRAPH round (line11000). Final coloring assigns its rewritten short range
r0, so the final-only lifetime-pressure report's spill=false hides relevant
history. A tooling bug is recorded in warning-spill-history-issue.json. Keep
final-round physical colors but inspect earlier spill rounds for this question.

Diagnostic-only forcing141:r27 does NOT undo that first spill: the dump still
marks it SPILLED. Do not treat this object as valid target-spill evidence.
Moving141 to the front of GPR selection avoids its initial spill but assignsr0,
changes other allocations and frame, and is not a source gain. Neither override
is installed in production. The next source lever must affect initial spill
priority/lifetime rather than final register renumbering or simple name locals.
Ordinary restored check is97.89181; source unchanged and no new upstream PR.

## First-round comparison and archive name parameters — 2026-09-07

A same-TU debug capture of copy-repair-clean.c confirms the exact first-round
spill difference. Retained source spills warning141; the clean645-instruction
candidate colors141 tor12 while page136 isr9 in both first rounds. It therefore
avoids a spill rather than swapping the desired page/warning spill choice.
Final register assignments alone obscure that causal difference. Capture is
clean-spill.pcdump.txt, compiled with the real mnsnap.c unit flags and without
modifying the baseline cache.

Three asset-loading inline variants pass the warning name, page name, or both
as parameters while writing outputs to the original persistent fields. All
produce97.05719%,frame392, and are rejected. Resource string data is controlled
by the previously verified named-field model. Parameter ownership in this
wrapper does not recover the desired spill pair. Manifest now150manual probes.
Restored ordinary source verifies97.89181; goal remains active, no new source PR.

## Interpolation operand order — 2026-09-07

Two operand-order variants rejected: index-first multiplication97.84544 and
start-first addition97.89181 (neutral), both frame400. Neither changes lisr28
at0x5c4 preceding the end-marker final load at0x5d4. This arithmetic spelling
family does not remove the scheduling interference. Manifest152manual probes;
restored check97.89181. Fresh upstream fetch still7a44e77cb6; open PRs3396/3300
unrelated. Public scratch WvrZ0 remains2786/64700, no updated source observed.
No source improvement or PR from this pass; initializer100 goal remains active.

## Extended current-source search — 2026-09-07

Verified full-unit.c exactly equals retained production source before running
the retail full-TU permuter for300 seconds. It completed878 iterations with
264 compile errors and no saved candidates. Triage confirmed no source.c
candidates to transfer. SIGINT at the bound exited0 without TERM escalation;
process-group audit confirms no owned processes remain. Ordinary rebuild still
97.89181. This is additional negative search evidence, not a source gain;
manually tested candidate count remains152. Avoid another unchanged-seed run
without a new source or search hypothesis. Evidence, ledger and memory saved;
initializer100 goal remains active and no new upstream PR was warranted.

## Position-return probes and spill-history fix — 2026-09-07

Three position-accessor variants returning Vec3 by value are rejected. End only
and start only grow frame400 to408; both grow it to424. All score97.785164.
Restored retained source remains97.89181; manifest155manual probes.

Tool issue1548 is resolved in bd2239d443. COLORGRAPH rows carrying SPILLED were
silently dropped by the parser, whose annotation regex accepted only brackets.
The parser now accepts SPILLED and bracket annotations. Pressure facts retain
prior_spill_rounds per register class separately from final colors, preserve
that optional field through backend mapping, and warn when a requested node
was spilled earlier. Regression verifies class isolation and finalr25 survives
a preceding spill.438tests pass,1skip across pressure/parser/scoring/tiebreak.
Real retained initializer141 now reports finalr0,spill=false,prior rounds[1].
The old dump has an honest mtime-stale warning after restored source edits;
source baseline is unchanged, and the observed spill comes directly from it.
No production C change or new upstreamPR. Use branch-local tooling for thisfix.

## Local impasse audit — 2026-09-07

First consecutive impasse audit after the spill-parser fix. Corrected parsing
of all COLORGRAPH rows confirms that retained and clean candidates differ in
first-round spill membership only by141; both spill48 in round2 and complete
round3 without spills. This confirms existing evidence and does not identify
a new source transformation. Current source remains97.89181,647instructions,
frame400; no C edits or new candidate count in this audit.

Known source families (155 manual probes) and current-source random searches
(532 plus878 iterations, no winners) have not produced another retained gain.
No new evidence-backed source hypothesis is available at this checkpoint.
Further useful matching work needs an independent source/compiler insight or
community candidate; repeating these unchanged families is not progress.
Goal remains active during the required consecutive-blocker audit; not complete.

Third consecutive local-impasse audit: public scratch source/context unchanged2786/64700; retained source has no uncommitted changes, latest verified report97.89181 with18neighbors100. PR3395 confirmedmerged; only open upstreamPR3300 unrelated. No new source-actionable evidence or running matching job. Goal markedblocked, notcomplete, pending independent compiler/source insight or community candidate. Bestsource and all evidence preserved; resume keeps the initializer100 objective.

## Resumed on new upstream baseline — 2026-09-07

Upstream PR3398 (630a33b8df) supplied new initializer/helper changes and constant
pool fixes. Latest upstream28d090295f merged locally as bbe79294b9. Fresh
configure/checkdiff reports98.06646%,frame400,18neighbors100, with a two-line
instruction delta still present. This supersedes the previous97.89181 baseline
and the earlier local-impasse premise. Improvement is upstream work, already
merged; do not open a duplicate PR. Public scratchWvrZ0 remains oldsource at
2786/64700 and needs refreshing after baseline investigation. Source and archived
report in2026-09-07-upstream-3398 are authoritative; old permuter full-unit seed
is stale and must not be reused unchanged. Goal still initializer100, incomplete.

Three archive-output accessors tested on the new upstream3398 baseline: page
98.05409, arrows joint98.06646, arrows shapeanim98.06646. All frame400; none
retained. Restored98.06646. Evidence in2026-09-07-upstream-3398; old155manual
probes are separate from these3 on the changed baseline. No newPR source gain.

Public scratchWvrZ0 refreshed successfully with upstream baseline source/context. Public score1637/64700 (~97.5%), separately measured from local98.06646. Full cross-build byte parity remains unproven.

Fresh upstream-baseline debug trace captured. GPR spill rounds: first49,50,42,
36,38,35,89,144,141,142,139,140; second48; thirdnone. Old virtual IDs cannot
be assumed unchanged. End-marker conflict persists: lisr28 at5bc before final
lwz fromr31 at5cc. Named return locals in upstream helpers regress: mainjoint
97.04637/frame400; warnanim97.95363/frame408; both97.00618/frame408. All reverted.
Six probes total onnewbaseline, retained98.06646. No source gain or newPR.

Four additional upstream-baseline warning-output variants rejected: joint
98.04946; material98.040184; shape98.04482; material+shape98.040184. All preserve
frame400 but remain645instructions: exactly one fewerstw and onelwz than target,
like baseline98.06646. These accessors do not recover the spill pair. Tenmanual
probes now recorded onupstream3398 baseline; source restored, no newPR gain.

Upstream-baseline main-load reuse check: direct field address is neutral98.06646;
calling mnSnap_GetMainJoint again regresses97.99382. Both frame400; reverted.
Twelve manual candidates now tested on upstream3398. Retained98.06646; source
unchanged, no newPR. Repeating output accessor/reuse spellings has not recovered
the missing spill pair and should stop without new allocator evidence.

First local-impasse audit on upstream3398 baseline. Fresh pressure mapping shows
end marker isIG84 (lwz180 fromstate), assignedr31, blocked fromr28 byIG199
(lis17200). OldIG85 is now the start marker, so its candidate-order suggestion
was irrelevant; use actual first definitions, not stale IDs/heuristic names.
Correct84/199 trace reiterates the previously studied scheduler overlap and
provides no new source action beyond shorten_lifetime. Twelve new-baseline
source probes yielded no gains. Current local98.06646, goal incomplete. No
source edit or new PR in this audit; recheck external evidence before repeating.

Third consecutive impasse audit on upstream3398 baseline: no uncommitted C
changes; current report98.06646 and18neighbors100. Newbaseline12manual probes
yielded no gain. End-markerIG84 conflicts with conversionIG199; missing one
stw/lwz pair persists. Last external audit upstream28d090295f and scratch1637/
64700 unchanged. No pending candidate or matching job. Mark goalblocked, not
complete, pending independent source/compiler insight or community candidate.
Bestsource is merged upstream3398; no unsubmitted C gain exists toPR.
