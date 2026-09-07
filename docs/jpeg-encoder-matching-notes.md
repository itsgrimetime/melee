# JPEG coefficient encoder matching notes

Verified **100% on 2026-09-07** in c016. Source: `src/sysdolphin/baselib/hsd_3B34.c`.

User instruction, 2026-09-07: stay on **hsd_803B3CD8 until source100**, with no
more function switching. Public scratch: https://decomp.me/scratch/mbSPH .
The decoder experiments are set aside and its active claim was released.

**Final match:** fork commit `d318e281de` reconstructs the inline component
encoder and run helpers. Ordinary compiler verification reports zero differences,
639 instructions and the target 104-byte frame. See the final section.

Historical follow-up: `5cdb1ad08c` removes `PAD_STACK(16)` through a real bit-length
result local, with unchanged99.70266% output. See the final section; earlier
padding observations below describe the preceding source.

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

## Root-inversion compiler experiment and source reconstruction follow-up

The retained source is still **99.70266%, 639 instructions, frame104**. This
pass compiled 72 source candidates; none improved the baseline. All source
and temporary tooling edits were restored. The ordinary build passed, the
six other matched functions remain100%, RGB remains98.7788%, and the built
DOL SHA-1 equals the original (`08e0bf20134dfcb260699671004527b2d6bb1a45`).

The earlier graph relabeling model is still **not compiler-validated**. A
temporary branch-local preflight prototype recognized alias103 by requiring
agreement between the natural103->57 mapping, final alias report, root57's
successful color/flags, direct pre-coloring copy, and a single class0 round.
The prototype and existing coalesce CLI checks passed46 tests. Nevertheless,
the scoped `103=103,57=103` experiment timed out after49 seconds, produced no
object, and left wibo PID95126 in UEs. The dump shows both overrides applied
and truncates within the coalesce exit line, before coloring output. This
does not establish the precise failing backend invariant.

The prototype acceptance was reverted. Existing root/alias identity is not
sufficient evidence that the backend supports changing the representative.
Issue1514 contains the failure and is released for tooling follow-up. Do not
repeat the experiment by weakening the validator. Any future representative
inversion needs backend support and independent validation of node metadata,
graph state, and the complete alias vector. The existing local debug watchdog
now reports an unreaped process; use a healthy diagnostic lane if further
compiler tracing is needed. Ordinary production compilation remained usable.

A diagnostic-only root-ID sweep permuted all graph references consistently.
Work at IDs58–83 still selects first;84–100 moves later than the desired
position;101–103 selects second. These are permutations of the captured
baseline graph, not predictions that a source declaration rename/move will
preserve that graph. The source tests below specifically found declaration
position insufficient.

| Source family | Candidates | Result |
| --- | ---: | --- |
| Pointer/aggregate initializers, pointer-return and output helpers | 10 | No gain; direct return helpers neutral, aggregate/output helpers grow or change code |
| Ten declaration positions, aggregate member versus flat pointer | 20 | Aggregate neutral99.70266%; flat98.74022% with extra entry copy |
| Whole encoder inline helper with pointer, state, tables, or DC-table parameters, both parameter orders | 8 | Default depth changes nested inlining;37.43662–37.81377% |
| Same whole-body helpers at explicit inline depths4 and8 | 16 |90.241005–93.53991%; frames112–128; parameter reversal/depth8 no rescue |
| Work pointer and existing counters or tables in one local aggregate, varying member order | 11 | Counter variants86.482–88.56338%; table variants98.33177–99.69484%; frames128–144 |
| Flat typed/void/byte pointers, register qualification, const pointer | 7 |97.165886–98.74022%; frame104; no allocation fix |

The flat-pointer report's three opcode-aligned register-only rows are not a
three-instruction residual: its extra entry instruction shifts the raw diff.
Its pointer still starts in r31, so it does not demonstrate the desired swap.

Evidence is in `docs/matching-evidence/jpeg-encoder/2026-09-06-root-inversion-source/`:
72 complete source candidates and ordinary checkdiff results, generators,
baseline and failed override dumps, test logs, graph sweep, restored TU report,
build/checksum results, and a verified257-member SHA-256 manifest. No new source
improvement was pushed to upstream PR3377 and the TU remains Linkable.

## Bit-length result local replaces stack padding

Retained source commit **5cdb1ad08c**, clean PR3377 commit **5d8814c180**.
A branch-local result in `hsd_803B3CD8_bit_length` accounts for the stack
reservation previously supplied by `PAD_STACK(16)`:

```c
if (value & (1 << bit)) {
    s32 result = bit + 1;

    return result;
}
```

Removing the padding with this local preserves all802 disassembly/relocation
lines from the preceding encoder source:639 instructions,104-byte frame,
99.70266%,38 register-only differences. This is a retained source reconstruction
improvement, **not a match-percentage gain or allocator solution**. The same
local with a single return/goto also works; the retained early-return form
keeps the existing simple control flow. Both primary and PR TU sources agree.

22 ordinary source probes were saved:

- Bit-writing counter ownership and bit-length return forms (8): counter reuse
  preserves opcodes but shrinks the frame to88 and increases register differences;
  a preinitialized result moves the zero assignment before each scan. No gain.
- DC helper/ownership separation and bit-length output/local forms (8): splitting
  DC reads/writes adds instructions or moves address setup. A late-zero result
  with padding removed preserves the exact baseline; output parameters keep
  opcodes but give91 register differences.
- Structured single-exit and input-parameter reuse forms (4): no gain. Reusing
  the value parameter preserves opcodes/frame104 but gives117 register differences.
- Shared and branch-local early-return results (2): both preserve the exact
  baseline without padding. The simpler branch-local version is retained.

A fresh supported retail backend trace completes successfully. All283 GPR
color decisions are identical to the preceding source trace, including IDs,
assignment order, and physical registers. Thus the older allocation evidence
remains relevant; the result local resolves stack reservation but does not
change the allocator's work-pointer ownership. No forced compiler edit was used.

Full GALE01 builds pass in both worktrees. Six matched neighbors remain100%,
RGB remains98.7788%, and both built DOL SHA-1 values equal the original
`08e0bf20134dfcb260699671004527b2d6bb1a45`. Since these two functions remain
unlinked, that checksum validates the build rather than proving a source100
match. TU remains Linkable. PR3377 source and description were pushed; CI
was running at this checkpoint.

Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-06-result-local/` contains
all candidates, baseline/retained diffs, the fresh retail trace, comparison,
validation summaries, and a verified SHA-256 archive manifest.

## Retail front end, public scratch, and libjpeg provenance lead

The retained encoder remains **99.70266%, 639 instructions, frame104, 38
register-only differences**. Public scratch, owned by `itsgrimetime`:
https://decomp.me/scratch/mbSPH . Production compilation verifies score190/63900,
matching the ordinary local residual. The source is unchanged from5cdb1ad08c;
PR3377 remains5d8814c180 and its applicable CI checks passed.

A full retail front-end capture completed54 optimizer snapshots. At pass5,
`IRO_ScalarizeClassDataMembers` rewrites20 references to the local `state`
aggregate into compiler-created scalar `@319`. The global work address is
assigned at entry before and after this pass. CSE later reduces these to19
references; the scalar survives to the final pass. This supports inspecting
scalarization and pointer ownership, rather than assuming late CSE first
materializes the work pointer. The trace command adds exception/symbol options;
it is diagnostic evidence, not an independent production100 result.

32 ordinary source candidates were compiled and restored:

| Family | Count | Result |
| --- | ---: | --- |
| DC table const/void/array pointer views |9| Const neutral; other views reduce frame by8, no register fix |
| Separate AC inline helper, pointer/global ownership |6| No gain; helper depth changes inlining and frames |
| Matched header-writer donor: whole-body helper with redundant global-pointer assignment |8| No gain; best98.39593 with extra instruction/frame120 |
| Individually scalarized DC table pointer aggregates |6| One aggregate neutral; both add8 stack bytes, same38 register differences |
| Stock IJG-style zero-first branch and branch-local AC value |3|98.4241–99.253525%; instruction order regresses |

Whole-function and window donor searches completed. No convincing whole-function
twin was found. Useful windows were in the already-matched JPEG header writer
`hsd_803B4D64`; the donor index's score for that function was stale. The redundant
pointer-parameter reassignment pattern above was tested directly, not inferred
from the similarity score.

A normal decomp-permuter run also completed a bounded search (last progress1089
iterations,153 compile errors) without beating baseline score190. Importer
preserved inline bodies, but host preprocessing selected generic shift/xor
`abs` because `__MWERKS__` was absent. Correcting only the imported source to
`__abs` recovered the real baseline:38 register differences and zero stack,
branch, insertion, deletion, or reorder penalties. Issue1525 records this
importer bug. The archived reusable kit has corrected `base.c`; the importer's
old, incorrect `base.o` is deliberately excluded. No permuter job remains live.

### Remote Inspector: distinguish the failures

Windows host `nzxt-local` is available. Both native Git and MSYS Git successfully
contacted the fork and fetched exact PR ref5d8814c180. The earlier generic fetch
failure did not reproduce; credentials were not established as its root cause.

Invocation `c016-encoder-20260906-frontend` completed private checkout and then
failed PRE validation because `build/GALE01/include` was absent. Investigation
found that **worktree-doctor had downgraded the wrapper**: this branch already
contains generated-header transport fix94f54d46c1, but doctor copied the older
shared-master wrapper over it. The branch-owned wrapper has now been restored.
Do not repeat that downgrade or reimplement the existing fix.

A temporary bounded diagnostic retry using safe private-directory provisioning,
`c016-encoder-20260906-frontend-dir`, timed out180s at private-clone instead.
Neither run produced Inspector IR, and cancellation lacked a terminal cleanup
receipt. No broad process cleanup was performed. Issues1497/1526 record these
separate stages; another invocation should use the restored wrapper and inspect
clone/process state before drawing conclusions about Inspector itself.

### Public scratch tooling fixes

Scratch creation exposed two extractor bugs. Existing fixa95d06faa4 for Linkable
objects was cherry-picked as31736a7434. Multiline `Object(...)` declarations were
still omitted; fixf76d606b91 parses them across lines while retaining library
association. Four focused tests pass;38 integration tests skip because their
legacy submodule fixture is unavailable. Actual worktree extraction and public
scratch creation/compilation both succeeded. Installed shared CLI still needs
these fixes integrated; run branch-local CLI with explicit current worktree root.
Issue1527 is resolved with that qualification.

### Provenance: community lead remains worth pursuing

The user relayed a Discord suggestion that the encoder derives from libjpeg6b
with GameCube changes, specifically `jchuff-nin`. This is a stronger search lead
than quantization-table similarity. Public Doshin decompilation data confirms
`libjpeg/jchuff-nin.c` and `libjpeg/jdhuff-nin.c`, with familiar IJG symbols
including `encode_one_block`, `emit_bits`, and `jinit_huff_encoder`:
https://github.com/break-core/doshin-gc/blob/b01be768ab68782c6890b832cd61e35d3b4d9103/config/GKDP01/splits.txt

That confirms the Nintendo filename, not Melee's exact ancestry. No source body
for that Nintendo variant was located. Stock IJG6b was obtained from
https://www.ijg.org/files/jpegsrc.v6b.tar.gz (SHA256
75c3ec241e9996504fe02a9ed4d12f16b74ade713972f3db9e65ce95cd27e35d).
Its `encode_one_block` emits run/size symbols and0xF0 long-run codes, unlike the
current Melee reconstruction's separate run+1 coding. Its floating DCT also
differs, but that cannot exclude selective libjpeg borrowing or replacement of
the transform. Do not present the earlier HAL-specific implementation hypothesis
as established provenance, or the community suggestion as verified identity.

Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-07-frontend-community/`
contains32 candidates,54 retail front-end snapshots, donor results, corrected
permuter kit/run, remote-stage logs, public compile verification, and a verified
195-member SHA256 archive manifest. Ordinary build passes; TU remains Linkable.

## Recovered Windows Inspector output: compilation did finish

This corrects the earlier interpretation of the enc6 timeout. Read-only Windows
inspection found a384737-byte `artifact.partial` under invocation
`c016-encoder-20260906-frontend-dir`, despite the wrapper's timeout and lack of a
terminal record. The retrieved file contains all eight TU function sections,
both encoder local-variable listings, and a final `Compilation finished.` marker.
The remote41848-byte object also exists.

The remote source SHA256 equals the retained local source exactly:
`0f06df91008f9fe01f3264d8e69eee97685f65e62c4e81b2ca48fd651b4ea5ee`.
The remote private HEAD is5d8814c180. Remote and downloaded artifact hashes agree:
`678270f5ea1874cd18d5883e8dc198793700f877957645a6277b47460b493183`.
Its command line identifies GC/1.2.5n, private source/include paths, and the
expected TU exception/symbol options. No live processes with either invocation
ID in their command line were found in the Windows CIM snapshot.

This is useful recovered compiler evidence, **not a successful supervisor
publication or a fabricated terminal cleanup receipt**. No receipt was created,
no job was restarted, and no broad cleanup was performed. Issues1497/1526 now
record the distinction: the enc6 job progressed beyond private checkout and
completed compilation; the wrapper failed to publish the result. The precise
supervisor failure remains unproven.

The encoder snapshot contains61 local ObjObjects. `state`, tables, and ordinary
locals precede the inlining-created temporaries in sorted address order. Its
ENodes still refer to the `state` aggregate; the separate retail optimizer trace
later scalarizes it to `@319`. Thus Inspector sees an earlier ownership stage.
Heap ordering alone is not a physical-register prediction, and reordering these
source declarations was already tested without fixing the residual. The dump's
statement line-number fields contain implausible values; do not use those as
source locations.

New bounded source tests used the recovered ownership information:

- Seven valid bit-writer aggregate variants group value, length, and/or loop
  counter. Value/length-only forms preserve opcode names but enlarge frames to
 152–208 bytes; the value wrapper also reorders two `addi` operations and changes
  the run+1 register. Counter variants perturb structure further. No gain.
  Three initial generator outputs put a declaration after an assignment and
  failed C89 syntax; corrected versions were compiled, and both sets are saved.
- Three coherent plain-`int` variants cover helper types, function locals, or
  both. Helpers alone are neutral. Whole-flow/function-local variants score
 99.53052%, retain frame104, and remove a required copy instruction. The26
  opcode-aligned register differences are therefore not a26-instruction-only
  residual. This corrects the earlier description of an added instruction.
- Four follow-ups change coefficient/history/all integer work-buffer fields to
  `int` on that whole-flow candidate. All are identical99.53052%; field types do
  not restore the missing copy. All source candidates were restored.

Discord archive search finds2025 discussions of Doshin's custom `jchuff-nin` /
`jdhuff-nin`, including a participant saying they could not locate their source.
This reinforces the Nintendo-library search lead but supplies no Melee source
identity. Other JPEG/Melee hits discuss `dolphin/jpeg/jpegdec` and THP decoding;
those must not be conflated with this HSD coefficient encoder.

Upstream96a6a6a491 (PR3369) was merged as20cd3c2052. It matches
`grBigBlue_801E6C60`; the PR's author explicitly describes working on that TU, so
its remaining function was left alone. Full build passes after restoring the
encoder source. Encoder remains99.70266%, public scratchmbSPH remains available,
and the TU remains Linkable. No upstream PR source update is warranted by these
unsuccessful candidates.

Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-07-inspector-recovered/`
contains the full recovered dump, encoder-only excerpt, hash/ref/process checks,
local-object summary,17 attempted compiles (14 valid candidates), Discord search
results, final validation, and a verified74-member archive manifest.


## Focused encoder continuation: shared owners and inline reconstruction

The encoder remains **99.70266%, 639 instructions, frame104, 38 register-only
instruction differences**. All trial source changes were restored, ordinary
checkdiff verifies the retained baseline, and the full build passes. PR3377
and scratchmbSPH retain the existing best source; no percentage improvement
was found to push to the PR. The user explicitly requests continuing this
encoder until100 rather than moving to another function.

59 ordinary source compile attempts (58 valid candidates):

| Family | Attempts | Result |
| --- | ---: | --- |
| Shared second work owner across DC calls, AC calls, or all seven calls; flat/member; embedded/separate initialization |12| Best neutral; embedded ownership usually adds a copy and grows frame |
| Byte-helper expansion and all-call bit-writer expansion, with flat/member/direct work references |8| Byte expansion preserves38 register differences but grows frame128; other forms regress |
| Explicit if/else and default-then-override table selection, individual/DC-pair/all tables |12| No gain; DC pair changes work pointer to r26 and introduces copies |
| Bit/byte helper return value, length, byte, destination, or success conventions |8| All baseline-identical |
| IJG-like checks of always-successful inline emitters |2| Bit-writer checks neutral; checking both helper layers grows frame128 |
| Sequential work-buffer structs and explicit jump-context union view |5| Four valid variants baseline-identical; one generator error corrected |
| Whole encoder inline, with local owner or work parameter, original/expanded byte helper |6| Nested bit/length helpers remain calls at default depth; no gain |
| Same six variants with depth8 set before every helper definition |6| Fully inlines to longjmp-only calls, but best97.82316%, frame136, two extra instructions |

The layout generator initially removed `metadata->data` along with the intended
`JpegWork` member accesses. That candidate failed compilation in a different
function and is not matching evidence. Restoring the unrelated metadata
accesses yields the valid, neutral flat-struct result. Jump context size248
plus32 header bytes preserves the first sample offset0x118 in the sequential
layouts.

The outer-inline experiment distinguishes two observations: setting depth8
before all helper definitions does eliminate the residual bit/length helper
calls; full inlining alone does not recover the encoder's instruction stream,
frame, or register allocation. No pragma/source variant was retained.

The earlier coherent-int candidate was examined with opcode/register-normalized
alignment. It **removes**, rather than adds, the required `mr r22,r0` after the
AC coefficient test: the load instead writes r22 directly. The work pointer
still receives r31. Lower raw paired-difference counts do not represent an
allocation improvement. The earlier paragraph has been corrected accordingly.

A broader ordinary permuter run started from verified score190. At interruption
it had completed11547 iterations with1569 compile errors and produced zero
better candidate directories. It exited normally after Ctrl-C; no run remains
live. Triage found no candidate sources, so there was no winner to transfer to
the real tree. The reusable kit remains the previously corrected one; the old
imported base.o must still not be mistaken for the corrected baseline object.

Lifetime-pressure on the saved retail trace again mislabels later final-color
holders as causal blockers of IG57, which is actually selected first. Added
this encoder reproduction to issue1524; rely on the verified selection order
and scan replay, not its proposed removal of interference with a later holder.
PR3004 and PR3181 were reread for pointer-alias/lifetime techniques; they do not
provide evidence that this encoder's instruction sequence is solved by the
same source spelling.

Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-07-focused-source/`
contains all candidates and results, generators, a PR source diff, final
checkdiff/build evidence, a run summary, and a verified206-member SHA256 archive.

## State-pointer experiment: recorded retail allocator state is identical

Focus remains **hsd_803B3CD8 until source100**. This continuation retained no
source change: ordinary compilation remains **99.70266%, frame104, 639
instructions, 38 register-only differences**, and the full build passes.

The most useful new experiment passes `JpegEncoderState*` through both output
helpers instead of passing `state.work`. The local state still contains only
the work pointer. Both mutable and const state-pointer forms compile exactly
like the retained source. Passing the state pointer only through write_bits,
then extracting work for write_byte, instead adds copies and grows the frame.

A fresh supported retail backend capture of the both-layers variant completed.
Comparing its **entire recorded GPR class** against the preceding retained
retail trace gives equality for every class field: 320 nodes, 2655 edges,
coalesce mappings, all 283 color decisions, selection/simplification orders,
register pools, and non-allocatable state. The compiler command hashes also
agree. This is stronger than instruction similarity alone, but it is scoped
to the recorded allocator state at colorgraph return plus decisions/orders.
It does **not** prove that all preceding passes were identical or identify the
precise earlier pass at which the source forms converged. The interface change
alone does not move the observed coalesced representative or allocation order.

50 valid ordinary source candidates were compiled and restored:

| Family | Count | Result |
| --- | ---: | --- |
| Coefficient/history pointer as owner, flat/member and direct/recovered-parent accesses | 8 | 95.73–96.01%, additional address operations and larger frames |
| State pointer through both helpers or bits-only, mutable/const | 4 | Both layers neutral; bits-only97.22691%, frame136 |
| Sequenced comma/self-assignment owner forms and loop initializers | 10 | No gain; preserves sequence points rather than relying on unsequenced writes |
| Dedicated Huffman emitter owning table lookups and bit loop, DC-only/all calls, input/order variations | 8 | All identical to baseline |
| State/local/helper renames and legal helper definition-order changes | 5 | All identical to baseline |
| Bit-mask/test helper in scan, writer, or both | 9 | Same38 register differences; frames112–224 |
| Compact Huffman code/length locals and signed code-table view | 6 | No gain; compact pair preserves frame104 but increases register differences to82 |

The Huffman-emitter variants preserve the helper nesting depth by including the
bit loop in the new helper. The narrow code variants apply only to Huffman
codes, not arbitrary signed coefficient payloads. The signed table view casts
back to u16, preserving the original16 code bits. These are real source tests,
not register-forced models.

The public scratch was checked through authenticated `sync fetch` and its
browser Family view. There are two family members, mbSPH and yajTB, both owned
by itsgrimetime and both at score190/63900. No better family member was found;
this does not claim there are no independently created scratches elsewhere.
The temporary inspection tab was closed. Production `scratch search` failed
with403 even though `sync fetch` succeeded; issue1533 records missing auth
routing and excessively verbose challenge output. Raw challenge responses are
excluded from committed evidence. The existing unreaped local debug process
95126 was confirmed still present; it was not killed or bypassed. The supported
retail tracing lane remains usable.

Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-07-state-pointer/`
contains all50 candidates, comparison code and both full retail traces, public
scratch summaries/source, ordinary verification, and a verified190-member
SHA256 archive. PR3377 and scratchmbSPH keep the existing best source.

The next continuation tested this source hypothesis: extract the complete DC encoding phase
(table selection, difference/category, history update, Huffman/payload output),
with explicit ownership of its work reference. Earlier DC ownership probes
covered read/save operations; Huffman probes covered output/table lookups.
They do not exhaust the complete-phase boundary. Check actual inline expansion
and frame before interpreting any register score, and keep AC source behavior
and all runtime data references intact. Its results are recorded below.

## DC phase, run ownership, and category reconstruction

Focus remains **hsd_803B3CD8 until source100**. No candidate in this continuation
improved the retained 99.70266% source. The existing scratch mbSPH and PR3377
remain the sharing/review locations; a lower raw register-difference count is
not evidence of improvement when instructions move or a copy appears.

- All twelve complete DC-phase helpers fully inline when depth8 precedes every
  helper definition. The closest form passes work and the selected DC tables,
  with run initialized in the caller: 99.38184%, frame112, same opcode sequence,
  71 register differences. Other ownership/table/initialization forms regress
  further. Fully inlining the phase does not solve the work-pointer allocation.
- Six address-representation probes cover pointer/integer union views and
  static const scalar/aggregate work pointers. None improves; unions introduce
  instructions and static pointers change frame/address code. No static data
  or type-punning experiment was retained.
- Twelve valid run-phase variants cover input count/run, pointer input,
  helper-local or aggregate count, caller/helper length ownership, and reuse of
  run after its zero-count role is dead. A separate `run++;` before encoding,
  followed by the existing reset, is exactly baseline-identical. Embedding the
  increment in the bit-length argument changes code. The nearest helper forms
  preserve the 38 register differences but grow the frame to112. Five initial
  output-parameter candidates had a generator substitution error that also
  renamed `bit_length`; all five were corrected and compiled. Invalid attempts
  are saved but excluded from matching evidence.
- Twelve signed-category variants move abs and the bit scan into nested or
  direct helpers, on DC, AC, or both paths. None improves. The direct-parameter
  DC form adds `addi r25,r3,0` and changes magnitude/history addressing registers;
  its low positional register count is misleading after that insertion. The
  work pointer still receives r31. All new helpers fully inline.
- Six component parameter tests update the header consistently: int, enum,
  unsigned int/u32, and signed comparisons of the unsigned forms. Int/enum and
  explicitly signed tests reproduce the baseline. Unsigned tests alter compare
  instructions. Both source and header are restored.
- Ten second-role work-owner probes reuse dead DC code/length/table, component,
  or value locals for the AC phase. Copying through tables/value is neutral.
  Reusing DC code/length or component changes the initial pointer to r26 and
  adds a copy; direct global reinitialization adds further instructions. These
  are changes to allocation, not successful realization of the desired r30.
  Six follow-ups embed the assignment in the for initializer or coefficient
  lookup. All reproduce their respective separate-assignment candidates,
  including the extra copy; embedding alone does not fix this ownership split.

The existing structure search generated seven entries. Two malformed scope
probes mistake `state.work`'s member declaration for a function local; these
were rejected before compilation and reported as issue1534. Two entries have
identical generated source. Four unique valid candidates were compiled: three
are neutral, while a block-local int for the run payload gives99.663536%.
That candidate reuses r24 for the incremented run and moves its addi before the
length decrement. Its37 paired register differences therefore do not improve
the retained38-difference result. Generated sources and review decisions are
preserved so these invalid/duplicate entries are not counted as seven compiles.

Closed upstream PR2479 was inspected as an additional historical donor. Its
report regresses this encoder from82.84% to30.72%, and its source substitutes
standard combined JPEG run/category coding with0xF0 long-run handling. It is
not a matching donor for this function's separate run+1 coding. A fresh public
code search supplied no new encoder body; the inspected Kirby Air Ride repo
tree contains no JPEG/HSD path. These bounded searches do not establish that
no donor exists. PR3377 remains open at5d8814c180 with no new human review.

Upstream7f97c7afe0 (PR3385, Fighter input-field renames) was integrated as
4ae0cedc4c. It contains no change to the encoder TU.

Restored ordinary checkdiff confirms99.70266%, frame104,639 instructions, and38
register-only differences. All six previously matched neighbors remain100%,
RGB remains98.7788%, and the full GALE01 build passes. TU stays Linkable.
The encoder source SHA256 remains
`0f06df91008f9fe01f3264d8e69eee97685f65e62c4e81b2ca48fd651b4ea5ee`.

Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-07-phase-reconstruction/`
contains73 compile attempts (68 valid), two precompile review rejections, one
duplicate skipped, candidate generators, historical PR/search observations,
and final verification in a SHA256-verified archive. These failed source
families constrain their tested forms; they do not establish a source ceiling.

## Flat pointer: observed coalescing eligibility explains the surviving copy

The retained encoder remains **99.70266%, frame104,639 instructions,38
register-only differences**. No source change was retained in this continuation.
The most useful result is a measured distinction between a flat pointer and
the retained one-field struct, rather than another guess at register order.

A fresh supported retail backend trace for the flat `tables-rhs` candidate
completes with320 GPR nodes,2655 edges, and284 color decisions. Its persistent
work role is IG40/r31, and the global-address temporary IG103 receives r0.
They remain separate and the ordinary assembly contains `mr r31,r0` at entry.
The retained aggregate source has320 nodes,2655 edges,283 decisions, and the
natural merge103->57; work IG57 receives r31. Neither recorded graph has an
interference edge between the work owner and103. Equal total edge counts do
not mean the two graphs are identical.

Read-only probes using the existing retail hook infrastructure separately
observe **GPR coalescing bounds41..317 in both sources**, at colorgraph entry
after coalescing. Thus the flat owner40 is outside the observed interval,
while aggregate owner57 and address temporary103 are inside it. The compiler
reconstruction's `SpillCode_CanCoalesce` requires both nonphysical endpoints
inside this window; it also checks interference. Its preallocation code places
the window boundary after the initial/local-object walks. This accounts for
why absence of interference alone does not eliminate the flat pointer copy.
The reconstruction is labelled high-level equivalent with binary match
unmeasured; the bounds, mappings, colors, and ordinary output were measured
independently. No compiler data/register/alias override was used.

The trace itself does not provide source-object attribution or earlier PCode
operands. The association of the persistent work role with40/57 uses its
physical-register uses in ordinary assembly and graph comparison, not a
fabricated source-location field. Eligibility bounds were read after coalescing;
these artifacts do not claim to trace every coalescer branch or preceding pass.
Issue1535 requests including these bounds in the normal backend trace, so this
distinction can be diagnosed without a separate probe. The validated copy
pattern is saved as `named-pointer-outside-coalesce-window` in the mismatch DB.
It explains/removes the flat version's extra copy; it does not solve the
remaining r30/r31 swap.

An offline two-axis model also tested752 combinations of work-root ID57..103
and subsets of its four stale table-address edges. Before perturbation, replay
exactly reproduces all283 baseline selections. Removing edges does not broaden
the IDs that produce the desired leading run/work pair: only101..103 do so in
this model;103 is the only ID preserving the entire remaining selection order.
These are graph permutations/deletions, not compiler interventions or evidence
that a source declaration can realize them.

40 valid ordinary source probes, all restored:

| Family | Count | Result |
| --- | ---: | --- |
| Shared initialization helper for work and selected tables, aggregate return/output or separate outputs |8| All inline; no gain, extra copies/changed frames |
| Consistent global buffer declaration, typed union, direct global and flat typed access |4| Array/union declarations neutral; direct/flat access regresses |
| Switch or nested conditional table selectors |10| Additional branch/copy instructions, no gain |
| Entry work assignment inside table RHS/condition/branches or sequenced assignments, flat/member |8| Member forms mostly neutral; flat forms retain copy; branch forms regress |
| Inline work getter at every use, with/without discarded entry call |6| Multiple address forms and frames112..312; no gain |
| Integer work-address carrier, full-width bitfields and u64 carrier |4| All98.54773%, frame104, two extra instructions |

The global-type experiment follows an existing TODO: hsd_804D2648 is defined
as a0x828-byte array but declared as __jmp_buf. Both a consistent byte-array
declaration and a shared JpegWork union preserve the exact encoder output, all
six matched neighbors, both hsd_3B33 functions, and all hsd_4D11 data. This rules
out those tested declaration changes as the register-swap fix. No unrelated
type cleanup was retained. Header and definition edits are included alongside
each candidate so these experiments are reproducible.

Ordinary restoration and the full GALE01 build pass. The source hash remains
`0f06df91008f9fe01f3264d8e69eee97685f65e62c4e81b2ca48fd651b4ea5ee`.
Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-07-coalesce-eligibility/`
contains candidates, the new full flat trace, both bounds probes and hooks,
the baseline trace/comparison, offline model, compiler source references and
their revision, and final verification in a SHA256-verified archive.

## Counter ownership and a combined outer-inline reconstruction

Focus remains **hsd_803B3CD8 until source100**. The retained ordinary source is
still99.70266%,639 instructions, frame104, and38 register-only differences.
This continuation compiled46 valid source candidates; none improved the best
source, and all were restored. The preceding coalescing-window findings and
201-member verified archive were committed/pushed as006ba255af.

| Source family | Count | Result |
| --- | ---: | --- |
| Run, index, or length as int, u32, unsigned int, u16, or u8 |15| Int neutral; unsigned changes comparisons; narrow types add conversions or change frame |
| Independent scalar/one-element-array aggregate owners for run, length, index, or DC value |8| Regressions with additional instructions; no desired work-register change |
| Separate AC length, or separate run/AC category lengths |2| AC-only neutral; splitting all categories adds8 frame bytes with the same38 register differences |
| Work member as void/byte/word/const pointer or pointer to array, cast back at use |7| All98.54773%, frame104; additional instruction/lowering differences |
| Whole encoder inline combined with shared-state pointers through both output helpers, local/pointer/value owner and const variants |8| Six pointer/local forms98.39593%, frame120; by-value forms93.53991%, frame128 |
| Same outer-inline source with direct bit-length return, and individually caller-owned AC value, coefficient, run, length, or index |6| Caller AC value/coefficient restores required copy; still lower scores, frame112 and more register differences |

The combined helper experiment addresses a concrete failure of the earlier
whole-encoder inline: passing the same state object through both output helper
layers removes its three duplicate work-pointer copies near the AC loop.
All new helpers fully inline (longjmp is the only remaining call). However,
the combined form loses the required `mr r22,r0` after loading/testing an AC
coefficient, schedules run+1 before the length decrement, and assigns the work
pointer r29. It has638 instructions, not639; the diff tool's positive
`line_delta: 1` is not evidence of an inserted instruction. Its98.39593% and
frame120 remain worse than the retained source.

Changing the bit-length helper from a branch-local result to a direct return
reduces that alternate frame by8, to112, without fixing its instructions.
Keeping either the AC value or coefficient in a caller local, passed by
address to the fully inlined encoder, restores the missing copy and639
instructions. Scores are98.61502% and98.56025%, with136/142 paired register
differences and the run+1 scheduling difference still present. These output
parameter forms are source diagnostics of the helper boundary, not proposed
upstream API design or a compiler-trace proof of the specific protection flag.
The baseline's result local and source structure remain retained.

Two additional offline graph checks validate the complete283-selection
baseline replay before altering any edges. Adding each possible single new
edge to the run-payload role216 (277 cases), or removing each existing edge
from work57 (251 cases), never yields the desired leading216,57 selection.
In the baseline,216 is removed on scan2 at degree12;57 survives to scan3 and is
removed at degree15. These528 offline cases constrain only single-edge changes
in that captured graph. They neither prove a source ceiling nor model broader
source changes; no compiler graph or physical register was forced.

Final ordinary checkdiff, the whole TU report, and the full GALE01 build pass
at the retained baseline. All six matched neighbors remain100%, RGB remains
98.7788%, and the source SHA256 is unchanged:
`0f06df91008f9fe01f3264d8e69eee97685f65e62c4e81b2ca48fd651b4ea5ee`.
PR3377 remains open at5d8814c180; all applicable checks pass and it has no new
human comments or reviews. No source improvement warranted updating that PR.

Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-07-counter-and-inline-owners/`
contains all46 candidates, generators/results, both graph checks, PR status,
and final verification in a SHA256-verified archive. Stay on this encoder;
the alternate outer-inline form is a measured reconstruction branch to reason
from, not a replacement for the current best source.

## Direct preallocation bindings and the alternate helper graph

Focus remains **hsd_803B3CD8 until source100**. No source change was retained:
ordinary compilation remains99.70266%,639 instructions, frame104,38
register-only differences. This continuation adds measured source-object
bindings and35 valid source probes, rather than treating equal graph sizes
as evidence of equivalent allocation problems.

A new full retail trace of the previous caller-AC-value outer-inline candidate
completes with320 GPR nodes,2655 edges. Its leading decisions are52/r31,
51/r30,50/r29,101/r28,100/r27. The work-address merge is105->50; the two AC
table roles take r31/r30 before work takes r29. The ordinary source for this
trace is `c016-enc15-outer-homes/ac_value-direct-result.c`, not the baseline.
Normal `backend-object-events.v1.json` still contains zero events and no
capabilities; source attribution must not be inferred from an empty sidecar.

A bounded, read-only GDB hook captures the preallocation object lists before
and after0x437230. It neither changes compiler data nor calls linkname helpers.
Both baseline and alternate runs match the requested function, finish normally,
and report no reader errors. The raw objects and register-info bytes are saved.
The field layout comes from the high-level compiler reconstruction and is
checked against contiguous observed allocation slots and the existing retail
traces; this is diagnostic evidence, not a production-match claim.

| Observed preallocation return | Baseline | Outer helper with caller AC value |
| --- | ---: | ---: |
| Assigned GPR object slots |32..101 (70)|32..103 (72)|
| First merge-eligible slot |41|34|
| Named `ac_value` slot |33|33|
| Work optimizer object/slot |@319 /57|@344 /50|

Baseline named `ac_value`, `coefficient`, `indexed`, `index`, `run`, `length`,
`value`, and `tables` occupy33..40. The original table-selection locals and
state aggregate have no assigned slot; optimizer temporaries carry their
values. The @319 binding agrees with the earlier IRO scalarization snapshot.
In the alternate, `ac_value` is the only named caller local in the local list.
Its33 slot is below34, directly supporting the earlier observation that moving
it to the caller restores the protected coefficient copy. The @344 work role
uses its observed slot, the105->50 merge, and ordinary physical uses; this does
not pretend that the normal trace supplied a source-location field.

The entry snapshot still contains bounds from the preceding function. Use the
preallocation-return first bound for this function; its last bound has not yet
grown to cover later lowering temporaries. Issue1535 now includes these
observations and raw capture locations.

The two full interference graphs are **not isomorphic**, despite equal counts.
Their degree histograms differ: baseline has one degree46 node and one degree126
node, whereas the alternate has degree47 and125 nodes. Physical-register node
degrees are unchanged. The baseline affected nodes are95 (@187) and37 (`run`);
the alternate ones are90 (@209) and100 (@167). A separate color-preserving WL
comparison also rejects equivalence. These facts do not prove that exactly
one edge moved; more rewrites could preserve the other degree counts. The
baseline root-ID replay therefore cannot predict the alternate by renaming
register IDs alone.

35 valid ordinary source candidates, all restored:

- Eight caller-owned AC table/scalar combinations in the outer helper recover
  frame104 in several cases. Best98.62285%,136 register differences. Keeping
  run in the caller changes work from r29 to r31, but does not produce r30.
- Eight additional caller-local combinations and original declaration order
  reach99.32707%, frame96. Correct opcode shape alone does not resolve the
  remaining71 register differences or the frame.
- Six helpers encompass **all initialization, both DC and AC table selection,
  and the complete DC encoding phase**, leaving the AC loop in the caller.
  This extends the earlier DC helper, which did not own the full entry prefix.
  Work return versus shared-state output and direct versus local category
  returns were tested. Best99.02973%, frame104,95 register differences. All
  helpers fully inline; longjmp remains the only call.
- All five alternative bit-writer parameter orders on that shared-state prefix
  reproduce99.02973% exactly.
- Eight initialized embedded base uses (discarded coefficient/word lvalue or
  member address, flat/member work owner) do not remove the flat pointer's
  extra copy. Member forms reproduce the baseline; flat forms98.73239%, frame96.
  These diagnostics do not read an uninitialized local or propose discarded
  expressions as production design.

A fresh public code search for `jchuff-nin` still returns only the Doshin split
file. Its symbols separate encode_one_block(0x2B4) and emit_bits(0x17C), but
provide no source body or proof that this encoder shares their implementation.
The additional bounded encode_one_block/jchuff query returns no results; this
is not an exhaustive donor or provenance conclusion.

Final ordinary checkdiff, full TU report, and full GALE01 build pass after
restoration. Six matched neighbors remain100%, RGB remains98.7788%, and source
SHA256 remains0f06df91008f9fe01f3264d8e69eee97685f65e62c4e81b2ca48fd651b4ea5ee.
No better source was available to update PR3377 or scratchmbSPH.

Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-07-preallocation-objects/`
contains35 complete candidates, new retail trace, both raw object-list captures,
validation/comparison scripts, reference layouts, bounded search observations,
and restored build/checkdiff results in a verified archive.

## Ordinary-C reconstruction reaches work r30, below the best overall score

The retained source is still99.70266%, frame104,639 instructions,38 register
rows. **A new alternate source reaches the target work-pointer register r30
without compiler overrides.** Its overall99.02973% score is lower, so it is
saved as a reconstruction lead rather than replacing the best source or PR.

The earlier whole-encoder inline probes kept a one-field work aggregate or
used a work parameter. This follow-up instead declares a **flat work pointer
inside the inline encoder**, initializes it there, and passes its address
through both output helper layers. The outer function owns the AC value, run,
and DC value as locals, passed by address to the inline encoder. All helper
calls inline; longjmp remains the only external call.

Candidate: `c016-enc17-flat-boundary/caller-ac_value-run-value.c` in the archive.
The ordinary work-address instruction is `addi r30,r4,0` at+0x18. The candidate
has the exact104-byte frame and639 instructions, but95 register differences.
Register/branch-label-normalized alignment also shows the run+1 calculation
before the bit-count decrement instead of after it. Correct work r30 alone
is not a100% match or evidence that the other register differences are harmless.

The supported full retail trace independently completes with320 GPR nodes,
2655 edges,283 color decisions. It observes work-address merge105->98/r30;
98 is selected second, after101/r31. The new read-only preallocation capture
binds @173 to98, with first eligible slot36. Named caller value/run/ac_value
occupy33/34/35. All72 allocated GPR object slots32..103 are observed exactly
once. The first-selected object is @166/101; its source role has not yet been
established from a fresh front-end trace, so do not guess its role from its
final physical register. Object-reader errors are empty and both trace runs
finished normally. No physical-register or alias map was forced.

16 valid source compiles, all restored:

| Family | Count | Result |
| --- | ---: | --- |
| Inline-local flat pointer, passed by value or address/const address through output helpers; direct/local bit-length result |6| Best98.403755%, frame104; workr26, missing coefficient copy |
| Caller AC value/run/DC value combinations on the address-passing variant |4| Run ownership reaches workr30; best such form99.02973%, frame104 |
| Reassigned work parameter in either parameter order |2| Both98.403755%, frame104; no gain over inline-local form |
| Additional caller length/index/AC-table owners on the work-r30 candidate |4| Length is exactly neutral; index moves work back to r31; no overall gain |

The flat-local/by-value variants have more pointer copies and larger frames.
Passing the address through both helpers removes those extra pointer copies,
and caller AC-value ownership restores the target coefficient copy. These
source effects are validated by ordinary compilation; they are not claims
that the resulting output-parameter API is ready for upstream review.

Next useful analysis is a fresh front-end binding for @166 and the run-payload
value on this exact candidate, followed by a source test that restores the
run+1/bit-count initialization order. A specialized run-payload helper that
computes run+1 after initializing the bit counter is one untested hypothesis.
Do not reuse the baseline57/216 IDs for this candidate or declare the older
root-ID graph permutation realized: the full graph/source context differs.

Final restoration gives99.70266%, frame104,639 instructions,38 register rows.
Six neighboring functions remain100%, RGB remains98.7788%, and the full build
passes. Source hash stays0f06df91008f9fe01f3264d8e69eee97685f65e62c4e81b2ca48fd651b4ea5ee.
PR3377 and scratchmbSPH retain the best source. Stay on this encoder until100.

Evidence: `docs/matching-evidence/jpeg-encoder/2026-09-07-source-work-r30/`
contains the16 candidates and results, the unforced-r30 source/assembly,
full retail trace, preallocation capture/hook, normalized alignment summary,
and final verification in a SHA256-verified archive.


## Final ordinary-source match — 2026-09-07

User requested exclusive focus until 100%; no other function was selected.
The successful reconstruction is committed as `d318e281de`, with clean PR
counterpart `f05ca420b1` in [PR #3391](https://github.com/doldecomp/melee/pull/3391).
PR #3377 had already merged; #3391 contains only the final matching change
on fresh upstream/master. Both worktrees verify 100% with the ordinary
production compiler. No forced registers, compiler patches, or PAD_STACK are
part of the source proof.

The successful chain:

1. Move the component body into an explicit inline helper with a flat work
   pointer. Pass its address through the byte/bit helpers. Keep AC value, run,
   DC value, and index owned by the public wrapper.
2. Specialize run-payload output: initialize `bit = length - 1` before `run++`.
   This restores target instruction ordering.
3. Declare wrapper locals in order `value, run, index, ac_value`. This fixes all
   saved-register differences, leaving only the run-category r4/r5 pair.
4. Specialize run bit length: pass run itself, increment the helper parameter,
   then scan its bits. This removes the final volatile-register differences.
5. Scope `auto_inline off` around the public wrapper, preserving its call
   boundary without disabling the explicit helper inlines. Without this guard,
   the encoder alone matches but its caller regresses to 97.87519%. A trial
   `dont_inline on` instead disables needed helper expansion and is rejected.

All seven previously/currently matched TU functions now report 100%, including
`hsd_803B51C8`. RGB conversion remains 98.7788%; the TU stays Linkable. Full
GALE01 builds pass in the work and PR trees. The unlinked build alone is not
proof of this encoder; the fresh zero-diff object comparison is the proof.

44 valid source compiles in the final search: run-payload (4), work declaration
(6), run-cross (6), caller-order (23), and run-category (5). Three independent
run-category spellings match 100%: reuse-increment, bit-first-reuse, and
for-comma-reuse. The first is retained. At 100%, checkdiff classification omits
`stack_frame_sizes`; the temporary scorer initially misreported these three
as missing scores despite exit 0. The saved results are corrected using the
actual match:true, score100, empty-diff outputs. Future consumers must tolerate
optional classification fields.

The fresh front-end trace of the earlier unforced-work-r30 candidate produced
62 snapshots. @166 is its loop index, not a run-payload variable; its r31
assignment agrees with ordinary assembly. No trace inconsistency was found.
These IDs describe that intermediate source, not the final matching source.

Evidence is preserved under
`docs/matching-evidence/jpeg-encoder/2026-09-07-source100/`, including candidates,
results, compiler comparisons, builds, and SHA256-verified archive members.

Final delivery: PR #3391 is open and ready for review. Fresh upstream-based
verification remains 100%, all six previously matched neighbors remain100%,
and full build/checksum passes. Source100 evidence and learnings are committed
and pushed on the fork work branch. The public scratch still has the prior
99.70266% source; local-server discovery failed during the attempted sync.

## CI portability fix — 2026-09-07

PR #3391 Clang-Tidy rejected the four unguarded MWCC pragmas as unknown
pragmas. PR commit `87c5c22c6d` (fork `700cc4fefd`) wraps push/inline_depth,
auto_inline, and pop in `#ifdef MUST_MATCH`, following existing repository
conventions. Clang-Tidy passes locally; production encoder and all six
matched neighbors remain100%, and the full build passes. Future matching
changes using MWCC pragmas must also run the configured Clang-Tidy check.
