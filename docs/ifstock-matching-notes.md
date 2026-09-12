# Stock HUD matching checkpoint — 2026-09-06

## Completed by upstream PR #3378 — supersedes historical checkpoints below

On 2026-09-06, sadkellz merged [match and link ifstock](https://github.com/doldecomp/melee/pull/3378), commit `94d0c898834ca28d379375bfc6efd25d379caa8a`. This worktree adopts its source and types verbatim. Both `ifStock_802F8298` and `ifStock_802F98E8` now verify at **100%**; all **28/28** functions and all data match, the TU links from C, the full build and symbol comparison pass, and the rebuilt DOL is byte-identical to the original. The older partial-match checkpoints below are historical, not current blockers.

Our separate callback candidate also reached **100%** with a 136-byte frame before this integration. It is archived, not retained as production source: its additional byte-pointer and offset assignments offer no clear readability improvement over the merged implementation. The fork style hook rejected the byte-addressed field access, including the typed final-field variant; neither failed commit was bypassed. Do not revive the old draft PR #3370 as a duplicate matching contribution. Consider a future cleanup only if it is demonstrably clearer and preserves the complete match.

### Reusable local result: two address boundaries

The callback improved from 99.745766% to 100% by keeping **both** a typed unadjusted row assignment and a final byte-pointer assignment inside the access expression. Naming only the integer row produced the desired temporary but commuted the following ADD; separate assignment statements changed indexed addressing and added eight bytes to the frame. The row and final pointer boundaries together preserve distinct lowering values without those changes.

Condition/store sites additionally needed a named final frame pointer to preserve full-address reuse. Interpolation needed its own row local rather than the common row temporary. The last four instruction differences disappeared when the steal-JObj access embedded two named integer offset assignments. These are measured source-shape levers for the archived candidate, not general claims that such pointer arithmetic is desirable production C. The mismatch DB record is `two-stage-address-materialization`.

### What upstream changed

The merged callback uses named `flag`, `anim`, and `steal` fields, typed element/prefix macros, a stock-count update inline, an animation-step inline, and a palette-frame inline. Its macros retain an explicit cleanup TODO. Our longer byte-addressed candidate is not an obvious improvement.

The merged initializer takes `u8` for both parameters, recomputes typed per-player data through a macro, and uses ordinary `i++` loops instead of a persistent userdata walker and discarded counter cast. It also changes inline ownership and uses `PAD_STACK(20)`. These interacting changes match as a set; we have not isolated a single causal change and should not attribute the win to the parameter type or padding alone.

### Allocator replay and negative coverage

The existing retail coloring replay reproduced every observed select decision and color for the retained 98E8 graph after resolving coalesced aliases. Single degree changes through ±12, paired changes through ±5, single creation-rank changes, and sampled call-window degree changes did not solve it. Combined rank/degree and paired-rank edits did reproduce the desired saved-register roles in the abstract graph, but not the initial volatile pair. This was diagnostic reachability evidence, not matching C. The fresh role labels are root44=GObj/r30 and root43=JObj/r29; older heuristic notes swapped these labels.

Source tests of paired helper ownership and split initialization/body inlines did not improve 98E8 and were restored. The local coloring solver issue #1504 remains a separate tool limitation: failure of its order heuristic is not proof of physical-register unreachability. No further stock matching search is running.

The [callback completion evidence](matching-evidence/ifstock/2026-09-06-callback-match/manifest.json) preserves the 100% source candidate, patch, measured reports, full-build output, upstream verification, bounded negative summaries, and exact-replay snapshot/results. Larger raw traces remain supplementary build artifacts.

## Active goal continuation: clean saved-register allocation recovered

Retained **26714679db** brings `ifStock_802F8298` to **99.745766%**, with
all saved-register roles, the 136-byte frame, and vector homes matching the
target. `ifStock_802F98E8` remains **99.57843%**; the other 26 functions are
exact and full configure/build passes. Draft PR #3370 head is
`f9912a7b9dd0db30c6a7af828a6a148fd5fc681f`. Both functions remain unmatched.

The one-field userdata carrier was a useful diagnostic and is no longer needed.
A direct typed getter containing only `return gobj->user_data;` produces its
allocation without an extra home. A getter that accepts the already-loaded
pointer and returns it adds a four-byte vector shift. Broader context structs
also add homes. These are measured source-shape differences, not a rule that
all value-returning getters add stack space.

A separate `steal_jobj` for the final loop removes its higher-numbered later
live range from the earlier `jobj2` local. Declaration position then matters:
on the carrier seed, placing `steal_jobj` after `jobj_anim` reaches 99.49152%,
after `i` reaches 99.60805%, and after `jobj2` reaches 99.682205%. The final
position lets the root animation JObj, counter, and first-loop JObj claim their
target registers before the steal-loop web claims r23. Splitting only the
second loop is neutral. The ordinary scalar seed also improves, but still
needs the direct typed getter to place userdata in r28.

For both first-loop flag tests, initialize `data` at the unadjusted typed player
base and use `(data += sizeof(struct IfStockDataOffset))[2]` in the condition.
This gives the prefix and adjusted pointer the same source web: the target
`add r4; lbz ...,518(r4); addi r4,r4,516` appears in order. It raises
99.682205% to 99.745766%. Separate updates before the condition, separate flag
locals, and branch-local updates regress scheduling or reserve stack homes.
The retained source uses separate named call-argument assignments and no carrier.

The residual consists of temporary address-register reuse and one commuted
addition. Several two-add address sequences use one virtual in the initial
backend PCode where the target needs two physical roles. Broad byte/int/pointer
base replacements do not fix this cleanly; named intermediate bases can produce
r0 but commute the following addition or change indexed/displacement load forms.
A register-only mask cannot distinguish commuted input roles. Preserve exact
instructions and stack constants when judging candidates.

The new permuter run is stopped: 5,424 iterations, 271 compile errors, best raw
650 against baseline765. Both lower-score candidates read an uninitialized
JObj and were rejected by the semantic audit. SIGINT again hung after Exiting
(issue1472); only the verified owned process tree was terminated and all its
PIDs are confirmed gone. Import also reproduced the sizeof-plus parser bug1493;
its repaired base was verified at98.644066 before the search. The old run is
preserved separately. Neither search is active.

Fresh 98E8 allocator evidence still selects userdata42 at iteration3/r28 with
permanent degree24 before walker64 and stride55, both r27. Its permanent
neighbors include aliases58/60/62 into root51 and59/61 into root50, in addition
to physical argument copies. Root51 is the truncated player value; root50 is
an array-address computation. Source attribution for some field-load/call-return
nodes is heuristic and misnames the source, so inspect PCode before trusting it.
This is the next allocator investigation; no new98E8 source gain yet.

Evidence: [saved-register checkpoint](matching-evidence/ifstock/2026-09-06-saved-registers/manifest.json).
Mismatch DB records `split-late-loop-jobj-stratum` and
`conditional-prefix-pointer-web`; attempts ledger records the retained result.
The goal remains **both functions at100%**.


### Follow-up: solver verdict and negative coverage

Both `solve coloring` runs (retained cast and no-cast) complete with an
unsupported structural-unreachability verdict. Source inspection shows that
`_collect_order_target_inputs` derives an order heuristic (79,82,55 here),
verifies that order, and exposes its success as `forced_class_clean` to the
coloring solver. It does **not** verify the physical map printed beside the
verdict. This is not established stale-cache behavior; the failed order heuristic
cannot prove that no physical relabel reaches the target. Issue #1504 includes
this correction. The previously verified no-cast map including57:4 remains
valid diagnostic evidence. The new no-cast source measures99.53432 and is restored.

Six targeted 98E8 probes embedding the GObj creation in its userdata store and/or
the JObj creation in its condition are neutral, with and without the counter
cast. They do not remove the relevant allocator effect. No 98E8 gain is retained.

For8298, opcode search found matching address windows in `mnRulePlus_GetDescIdx`
and Master/Crazy Hand code. Four pointer-return getter variants add80–112 bytes
of frame space without fixing the address roots; two value getters add16–32
bytes and regress structure. They are restored. Byte-index casts to s32/u32 are
neutral, while u16/u8 add masking instructions and regress to92.30296/frame144.
The compact donor/probe summaries and final retained reports are in the current
evidence manifest. Fresh actual-source backend capture is
`clean-split-prefix-backend.pcdump.txt`; rebind virtual IDs to it before further
8298 forcing or lifetime analysis. All source probes and searches are stopped.

## Earlier checkpoint: permanent coalesced degree recovered

Retained source `4c42bf7705` raises `ifStock_802F8298` to **98.644066%**.
The three named call arguments `palette_index`, `count_jobj`, and `ones_jobj`
are assigned separately before their calls. Together they restore three copies
coalesced into physical r3 that survive through the pass before coloring.
Gobj's permanent degree rises from 12 to 15, so it selects first into target
r31; the stock base also reaches target r29. Each argument alone is neutral.
This is a measured nonadditive allocator effect, not a general declaration-order
rule. The frame remains 136 bytes, and masking only registers and instruction
bytes leaves the same four anonymous float-constant relocations. Userdata,
JObj, and loop register roles still differ.

The full build passes, `ifStock_802F98E8` remains **99.57843%**, and the other
26 functions remain exact. The source gain is pushed to draft PR #3370 as
`ba9cf3a19380747e9ca3f8008870297418225600`. Keep the PR draft and this TU
Linkable until both remaining functions match.

A diagnostic one-field userdata carrier reaches **99.23729%** with correct
frame, vector offsets, and instruction sequence. It promotes userdata out of
the ordinary-local virtual-register stratum, producing gobj r31, userdata r28,
stock r29, and original JObj r26. It is **not retained**: seek a maintainable
scalar expression with the same allocation. Remaining diagnostic role errors
are jobj_anim r23→r24, first-loop i r24→r25, first-loop JObj r25→r27, and
conversion magic r27→r23, plus volatile address registers. An initialization
helper reaches 99.15678% but moves vector homes by four bytes; score alone
does not make it preferable.

Extra named AObj or TObj arguments individually are neutral; both together
regress to 98.22034%, including on the carrier seed. Reusing the loop counter
for the initial stock count introduces three structural differences. Reusing
the first-loop JObj for an earlier call changes the wrong register cascade.
The select-order search is **complete and restored**: 13 generated, 8 compiled,
5 malformed, no improvement. Issue #1501 records incorrect scope/type/store
handling in its pointer-walk candidates; those do not establish safe exhaustive
coverage. Both retail frontend captures are also complete.

Mismatch record `named-call-arguments-permanent-degree` and the attempts ledger
preserve this partial gain. The evidence bundle includes the source, whole-TU
report, strict register-only comparison, backend allocation capture, and
negative experiment summaries. The goal remains both functions at 100%.

## Earlier checkpoint: instruction shape recovered

Current source commit `ce0fae4392` raises `ifStock_802F8298` to
**98.16737%**. Its instruction sequence, immediate constants, frame size
(136 bytes), and vector stack offsets agree with the target. A comparison
masking only instruction bytes and register operands leaves four anonymous
floating-constant relocation names. Register assignments still differ; this is
not a 100% match. `ifStock_802F98E8` remains **99.57843%**, the other 26
functions are exact, and full configure/build passes. Draft PR #3370 is updated
through source-only cherry-pick `1cbb14509f`.

Two local retail frontend traces completed successfully, with 62 IRO snapshots
each. The expanded X byte-offset expression retains nested additions and type
conversions through the final IRO pass. Its D-form load appears in the initial
backend PCode. Changing the source to the existing typed
`anim_data->anim[i - 5].start.x` / `.end.x` produces the target `addi` + `lfsx`.
The typed final IRO actually represents `(base + stride) - 168/-144`; textual
grouping alone therefore does not predict the selector's result. Do not claim
the IRO optimizer first folded the address into its wrong machine form.

Typed X accesses alone reach 98.144066% and zero normalized structural
differences. A stricter comparison then exposes another real address-form
difference: the interpolation call uses unadjusted base + 528, while the target
uses base + 516 then offset + 12. Reusing its existing data pointer fixes this.
Using the typed animation member for interpolation and removing the unused
`anim_offset` local reaches the retained 98.16737%. Normalization masks
constants and cannot establish that a residual is only register allocation.
Natural typed Y accesses regress by six structural differences; adding a cast
around their complete `(i - 5)` index regresses by 28. Both were restored.

Fresh allocator capture `typed-array-backend.pcdump.txt` and lifetime-pressure
analysis bind these main roles: gobj IG32 r23→r31, userdata IG43 r25→r28,
stock base IG78 r30→r29, original JObj IG69 r28→r26. Gobj is blocked by roots
72/73/206, userdata by 69/70/186, stock by 71/135, and original JObj by 39.
The old helper capture selected gobj IG32 first with permanent degree 15;
the current capture selects it at iteration 15 with degree 12. The old capture
contains three additional copies coalesced into physical r3: its roots 73/74/75
are the old x40, x3C, and first-loop player accessor results. These copies survive
through the pass before coloring. This suggests a specific permanent-degree
lever, rather than arbitrary declaration order. Cross-capture numeric edge
diffs are not meaningful for other roots without role rebinding.

Five initialization-order permutations are instruction-neutral. Explicit gobj
local copies at entry/after loads regress nine structural differences; a copy
after clamping preserves structure but changes the wrong saved-register roles.
Restoring only the initial helper, nested initializers, or a flattened initializer
does not improve the retained source. The source is restored after every probe.
The mismatch record `typed-animation-array-indexed-float-load` preserves the
addressing gain; further allocator work remains active.

## Earlier checkpoint: target frame and vector layout recovered

Retained source commit `3fc7c22000` brings `ifStock_802F8298` to
**97.65678%**, with the target's **136-byte frame**, vector offsets, and
instruction count. Four normalized structural differences remain: two
X-coordinate loads use `add` followed by displacement-form `lfs`, where the
target uses `addi` followed by indexed `lfsx`. Saved and volatile register
assignments also differ. The X-load form is already present **before global
optimization** in a fresh backend capture, so coloring cannot repair it.

`ifStock_802F98E8` remains **99.57843%**, with 408 instructions and a 152-byte
frame. The other 26 functions remain exact. Full configure/build passes.
Source-only commit `52778f6880` is on
[draft PR #3370](https://github.com/doldecomp/melee/pull/3370), verified as its
head. Keep the PR draft and the translation unit Linkable until both match.
The original-object linked checksum is not proof for either unmatched C body.

The useful new source levers were:

- Remove the remaining artificial 8298 helpers and use the standard JObj
  getter/setter. This recovers the frame, initially with worse instruction
  shape. Read `gobj->user_data` directly to remove the final four-byte shift
  in vector homes caused by its otherwise pure getter inline.
- Cast the **complete byte index**, such as `(int) (i + 5)`, at selected
  accesses. Casting only `i` does not have the same effect. Both complete
  `int` and `u32` casts change address materialization, so this observation
  cannot be explained only as signedness. Preserve the independent flag
  reload where required by the target's address instruction order.
- Use signed animation-size products for Y accesses, retain unsigned
  subtraction for the X seed, and flatten the final byte flag store.
- Increment the existing typed 516-byte prefix pointer before casting to the
  animation base. Unlike a simple byte-pointer `+= 516`, this preserves the
  target base `addi` and improves 97.442795% / five structural differences to
  97.65678% / four. The same layout idiom occurs in the matched first function
  of this file. These are measured partial gains, not general compiler rules.

The local permuter supplied the complete-index cast lead (output 6020-1).
It is **stopped** at 10,067 iterations, 400 compile errors, best raw score
6020 against 6625. Shutdown reproduced issue #1472; only its verified parent
and six owned workers were terminated, and all are confirmed gone. Its old
91.79873% baseline is not the current retained source.

Further X-load probes are neutral at 97.65678% / four differences: complete
int/u32/s32 index casts, float-array and float-pointer loads, commuted pointer
addition, integer-address casts, and materializing the complete -168/-144
offset in existing or new int/u32 locals. The offset locals fold before backend
selection. Do not repeat these spelling families without new frontend evidence.

The bounded 98E8 node-set-split run is complete and restored: 38 generated,
24 evaluated, no retained source gain. Its pointer-alias generator can remove
the original pointer's compound increment (issue #1495); malformed candidates
and that semantic error invalidate any claim of exhaustive safe coverage.
Coalesce discovery finds no direct identity edges, so noninterference alone
does not justify a coalesce intervention. Rebind virtual IDs after source edits.

Two remote frontend inspector attempts produced no IR: exact-ref fetch failure
then a private-clone timeout even with a remote-present base commit. Scoped
cancellations lack terminal cleanup proof (issue #1497); no broad remote kill
was used. Invocation IDs are `d82d-8298-postinc-20260906` and
`d82d-8298-postinc-cached-20260906`. Local retail frontend tracing is the next
diagnostic. Mismatch DB records `whole-index-cast-address-materialization` and
`typed-prefix-base-materialization` preserve the observed source levers.

Current source, reports, backend capture, build log, search summaries, and
dated intermediate evidence are in
[the goal-continuation evidence manifest](matching-evidence/ifstock/2026-09-06-goal-1/manifest.json).
The active goal remains **both functions at 100%**.

## Earlier intermediate checkpoint: frame reduced to 320

Commit `c5064e3da3` removes the `get_flag` and `get_player` accessor inlines
from `ifStock_802F8298`. The frame decreases from 344 to **320 bytes** against
the target's 136. The score stays **97.64831%**, with the same 10 normalized
structural differences. A separate instruction comparison preserving every
opcode and register operand finds **zero differences after masking only stack
offsets**. Vector homes move down 20 bytes, while frame alignment accounts for
the 24-byte frame reduction. This is a partial source improvement, not a match.

The full configure/build passes. `ifStock_802F98E8` remains **99.57843%** and
the other 26 functions remain exact. The source-only cherry-pick `14fb579519`
is on [draft PR #3370](https://github.com/doldecomp/melee/pull/3370). Keep the PR
draft and the translation unit Linkable while either function is unmatched.

The bounded accessor matrix explains why removing all trivial helpers at once
is not instruction-neutral. Each of four removals individually preserves the
score. Combining `get_flag` with any one other helper preserves the score with
a 320-byte frame. Other pairs and triples change saved-register assignments
(96.620766%); all four reach 296 bytes with that worse coloring. `register` on
the inline parameters or loop counter does not alter codegen. This finding is
recorded as `nonadditive-inline-home-removal` in the mismatch DB.

Additional valid probes are preserved under
`build/d82d-stock-goal-1/`: raw/typed base expressions, data alignment/layout,
named frame fields, standard JObj getter/setter calls, whole-function wrappers,
index types, output-parameter data helpers, numeric address helpers, explicit
frame pointers, distinct local copies of inline parameters/results, and end-Y
address caching. None improves the retained instruction stream. The direct
accessor seed with signed tail sizes reaches 92.254234%, 31 normalized
differences, and a 136-byte frame; equal frame size does not prove equal vector
home offsets. Shared `data_array = ...` comma probes contain repeated writes
in a nested full expression and are invalid candidates, not evidence that a
semantically valid family is exhausted. Malformed generated probes are likewise
excluded. Distinct-temporary replacements compiled but did not improve shape.

Tool recovery enabled a new local 8298 permuter search:

- `a95d06faa4` fixes issue #1487: the extractor omitted `Object(Linkable, ...)`
  from configure parsing. Models now preserve that status and report scores
  still decide whether functions match. Nine focused tests pass (38 unrelated
  integration tests skip without their fixture). Both real stock functions
  export successfully. Use branch-local `PYTHONPATH` until this tooling commit
  reaches the shared installed CLI baseline.
- Issue #1493: import misparses `sizeof(struct T) - 5` as a cast inside sizeof.
  Four generated expressions were repaired to the parenthesized original.
  Repaired baseline transfers to the real TU at exactly 91.79873%, the seed's
  original score. Local search uses six workers, stack differences, best-only
  output, and stop-on-zero. Raw permuter scores do not establish a source match.
- Issue #1494: triage flags preexisting `vecC.x/y` component assignments as
  use-before-def even though `lbVector_8000DE38(..., &vecC, ...)` initializes it.
  Independently, output-6340-1 writes a float through `+= 0`, and output-6410-1
  uses `new_var` in an else branch where it is uninitialized: both are rejected.
  The safe final-Y address-cache idea from output-6340-2 was rebuilt manually;
  it adds no retained gain. Do not blindly bypass candidate guards.

The 98E8 coalesce-discovery report finds noninterfering pairs but no direct
copy/identity edges or actionable suggestions. These are not safe forced
coalesces. A fresh 98E8 backend capture and a bounded node-set-split source
search are the next allocator investigation; register IDs must be tied to
their capture. The goal remains both functions at 100%.

Durable source, build, comparison, search setup, negative-result summaries, and
mismatch record snapshots are in
[the goal-continuation evidence manifest](matching-evidence/ifstock/2026-09-06-goal-1/manifest.json).

## Earlier source and upstream snapshot

The retained `ifStock_802F98E8` source remains **99.57843%**. Its retained change
is commit `32b12b3ac0`, already upstream through PR #3362. The follow-up improves
`ifStock_802F8298` from **97.19068% to 97.64831%** with signed animation-offset
arithmetic. Neither remaining function is an exact match.

Fetched upstream through `ca65e3dbc1` and merged it into the matcher worktree
as `666fed4285`. PR #3368 (name-entry menu) is merged as `57606966fd`.
All seven open upstream PRs were checked: #3369, #3359, #3358, #3344, #3300,
#3089, and #2955. None changes `ifstock.c`; #3358's broader harness changes
also contain no stock HUD implementation. This is a dated snapshot.

The fresh full build passes the original DOL SHA-1 and byte comparison.
`ifstock.c` is still Linkable, with **26 of 28 functions matching**:

| Remaining function | Match |
| --- | ---: |
| `ifStock_802F8298` | 97.64831% |
| `ifStock_802F98E8` | 99.57843% |

The linked checksum does not validate either unmatched function: their original
objects still supply this translation unit to the matching build.

## Measured residual

`98E8` has the target's 408 instructions and 152-byte frame. The current saved
register assignment exchanges the user-data cursor and the icon/stride values.
Initial byte-index and multiplication temporaries also use different volatile
registers. The compact report's `stack-layout` classification is misleading
here: the two stack stores differ by source register, while their offsets agree.

Fresh debug capture identifies user-data root 42 as r28 (wanted r27), stride-80
root 55 and first-loop walker 64 as r27 (wanted r28), product-84 root 56 as r3
(wanted r0), and initial byte-index root 57 as r0 (wanted r4). First-divergence
reports Case C2 at select iteration 3: root 42 claims r28 before 64 and 55.
The earlier retail backend investigation independently confirmed the relevant
allocation; that historical trace was recovered, not rerun in this checkpoint.

### A scheduling caveat hidden by the register swap

Two same-TU **diagnostic, forced-register** captures establish a useful target:

1. Retained source, GPR map
   `42:27,55:28,64:28,56:0,57:4,145:28,159:28`: all non-relocation differences
   disappear except two exchanged pointer increments at function offsets
   `0x368` and `0x36C`.
2. Remove only `(u16)` from the first loop's discarded `i++` expression; use
   the corresponding map with roots 143/157 instead of 145/159: **zero
   non-relocation instruction differences** remain.

These are not source matches. They isolate coloring and scheduling, and show
why the earlier score-improving counter cast must be reconsidered after a
natural register-allocation fix. Keep the retained source until a real compiler
build proves a better result. Virtual IDs belong to these captures only.

## Experiments and search coverage

The ledger already contained 507 attempts and a detailed negative-results
checkpoint at attempt 362. Read that checkpoint before repeating source families.
The old remote search on coder3 is stopped: iteration 200353, best score 270,
no output candidate. Its files were fetched; the one local output-190 candidate
is the already-retained counter cast, not a new discovery.

Twenty new variants were compiled in the real translation unit and restored:

- Six output-parameter index helpers: u16/u32/unsigned-char parameters, with
  and without an explicit byte mask. Scores 96.42402–97.36275%.
- Eight user-data initialization helpers: return, output, local/output, and
  input/output shapes with unsigned-char or u16 player arguments. Scores
  98.3652–99.52941%; some reserve additional frame space or retain a copy.
- Six direct index/product mask spellings. Five regress; the u32 byte-offset
  form preserves 99.57843%. The glyph count-helper result is not a general
  cure for this function's allocation.

Whole-function donor searches used both semantic and hashed backends; the
best hashed similarity was only 0.653. Window hits (up to 0.965) centered on
generic JObj translation/assertion code. The exact initialization opcode query
found no donor. A relaxed query returned `fn_8019C048` and `fn_80196FFC`;
inspection shows table-driven animation-state updates, not this initialization
structure. The search index's displayed 97.09% is stale; use the fresh local
report for the current score.

## Recovery and next step

Tracked [evidence](matching-evidence/ifstock/manifest.json) includes the baseline
allocator dump, forced diagnostic diffs, twenty-variant results, final diff,
upstream build log, and the mismatch DB record. Full candidate sources and
larger captures remain under `build/d82d-ifstock-investigation/`.

The next useful source result must change the first allocator decision or
explain the source lifetime/interference that causes it. Do not repeat blanket
declaration, integer-width, or helper-return sweeps. The forced no-cast result
provides an instruction-level target, not permission to ship forced code.

Mismatch DB: `discarded-counter-cast-hidden-scheduling-residual`.
Tool issues filed: #1487 (`extract get` misses this existing symbol) and #1489
(`inspect guide` labels coalesced roots 50/51 as unexpected spills despite
their recorded r24/r25 assignments). Do not infer a stack-spill source fix from
that guide output without independent evidence.

## Follow-up: signed animation offsets in `8298`

The four tail accesses to stock-steal start/end X/Y coordinates use an `int`
loop index with `sizeof(struct IfStockStealAnim)`. The unsigned `sizeof` operands
affect common-subexpression elimination and induction-variable selection.
Casting both size operands to `int` in each access improves the real-TU score
to 97.64831%. The loop still visits only indices 5 and 6, so these casts preserve
its in-range address calculations. This is a partial improvement: the current
frame remains 344 bytes against 136, and the instruction stream is four
instructions shorter than the target.

The retail backend trace explains the frame growth. Before the four vectors,
MWCC reserves 53 objects occupying 206 bytes plus two bytes of alignment:
51 compiler-synthetic objects, `count_index`, and a local `data` pointer. Their
208-byte region shifts every vector home by the same amount. This is unused
local/inline home reservation, not evidence of active register spilling.
Removing value-returning accessor inlines reduces that space, but also changes
the source expression structure and worsens the complete function. Do not add
padding or assume that renaming a vector repairs this frame.

Retail capture and a freshly regenerated debug dump agree on all comparable
allocator fields: 1,212 equal, with 148 differences solely from simplify-order
entries absent in the debug dump. The first comparison used a stale debug cache
and was discarded. The named `count_index` local is present in the retained
source; its presence in the retail trace is not evidence of a stale source.

Measured alternatives, all restored:

- Direct accessor removal: 92.15%, frame 200; flattening all value helpers:
  91.31356%, frame 144. Void initialization helpers and inline-depth changes did
  not recover the retained instruction/register structure.
- `int` and `s32` size casts, applied to the tail or every animation access,
  all produce 97.64831%. The minimal tail-only `int` version is retained.
- Typed data/animation arrays: 97.41314%. Factoring `(i - 5)` into the signed
  multiplication gives 95.85381%; mixing typed X/Y accesses gives at most
  96.95339%. Correct-looking Y offsets alone do not establish a better function.
- Casting only the multiplication: 97.317795%; casting only the subtracted
  size or the complete expression preserves 97.19068%. A signed negative
  constant plus signed multiplication is equivalent to the retained version.
- Isolated byte-data, increment-pointer, animation-getter, and tail-frame
  pointer changes do not improve the retained score. Removing `count_index`
  reduces the frame to 336 but scores 97.430084% and still changes instructions.

Candidate sources and full captures are in `build/d82d-stock-continue/`.
Tracked follow-up evidence is in
[2026-09-06-followup](matching-evidence/ifstock/2026-09-06-followup/manifest.json).
Mismatch DB: `sizeof-unsigned-animation-offset-cse` (partial gain) and
`inline-return-unused-frame-homes` (diagnostic).

The direct-access diagnostic was extended using the retail object map: remove
`count_index` and the local end-position `data` pointer as well. This reproduces
exactly the target's **136-byte frame**, confirming the reservation explanation,
but scores **91.79873%** with 33 normalized structural differences versus the
retained version's 10. Preserve `8298-direct-no-homes.c` as a separate structural
candidate; it is not a retained production improvement.

### Follow-up allocator-directed search for `98E8`

A fresh pcdump and `select-order-search` tested two composition rounds with
width 4, targeting `r64<r42,r55<r42` plus the known seven desired assignments.
The campaign completed normally and restored the source. Of 23 generated
variants, 18 were scored and five temporary-introduction variants were malformed
(the generator used an `int` temporary for a pointer expression). No scored
variant changed the desired assignments or beat 99.57843%; the best preserved
candidates leave root42 selected third, root64 fourth, and root55 fifth.

Families included indexed-byte expression ordering, adjacent declarations,
type width, early guard returns, block scopes, and compositions. The tool's
terminal label applies to this candidate family, not to the function itself.
`98e8-select-order-summary.json` records the scored results; the full report and
candidate sources remain in the build directory. Malformed-probe issue #1491 was
reported separately rather than treating those five variants as negative source
evidence.

The retained source is committed as `71d5a2e0e1` in the local fork. The same
file bytes were cherry-picked onto a fresh upstream branch as `beaae21538`
and submitted as draft [PR #3370](https://github.com/doldecomp/melee/pull/3370).
The source-only PR contains no fork tooling or investigation artifacts. The
final formatted source again builds successfully and retains the reported
scores; the other 26 matching functions remain at 100%.
