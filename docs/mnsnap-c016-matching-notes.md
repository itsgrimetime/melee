# Completed: mnSnap_80257F24 — 100% matched and linked

Final solution by **gitRasheed (Rasheed)** in [PR3409](https://github.com/doldecomp/melee/pull/3409),
commit683b601cfccb5dcff498cd00dee35cc077f082f8. Imported preserving author as
ba094613fe. Earlier entries below are historical investigations, not current
blockers. No more matching work is needed on this function.

Independent configure/ninja succeeded with required prototypes enabled. All
19828functions matched, all1130TUs linked, mnsnap19/19functions and1616databytes
100%. Direct cmp of newly linked DOL versus original succeeds; both SHA1
08e0bf20134dfcb260699671004527b2d6bb1a45. The raw checkdiff match boolean remains
false because it compares anonymous relocation labels; objdiff report100 plus
byte-identical complete linked DOL are the authoritative proof.

The final patch combines a discarded archive public_info->offset expression,
main_joint pointer alias restoration without main_load, main animation/material
assignment order, direct global pointer passed to CreateThumbnails, and direct
global thumbnail/count text-array stores. It also removes the duplicate
mnSnap_thumb_imgs array, using mnSnap_804A0B90, and marks the TU Matching.
We have not ablated each change, so do not claim any one edit independently
caused a particular scheduling/register fix. The important lesson is that
source references outside the immediate diff region can change compiler web
formation and scheduling; local register-only probes missed this combination.

Our prior resource-home improvement merged as PR3407. The final match is
Rasheed's work; no duplicate final PR was opened. Final evidence:
matching-evidence/mnsnap/2026-09-07-final-3409/manifest.json.

---

# Snapshot initializer continuation

Current retained baseline: **98.13447%**, source8a94f5de1a, PR3406 head9f1bdc6bbf
on codex/mnsnap-initializer-spill. PR3406 merged as006b50d24c and was synced here;
the next source gain needs a new PR. Historical
98.06646 references below precede the page-name spill correction.

Active function mnSnap_80257F24, src/melee/mn/mnsnap.c. Baseline98.06646%,
400-byte frame; claimed as codex-c016-snap. Prior work is documented at
/Users/mike/.codex/worktrees/d82d549a-e85c-4cac-95c7-4578ab792d23/melee/docs/mnsnap-matching-notes.md.
Scratch WvrZ0 was refreshed by that task, but local ordinary compilation is
authoritative. Decoder is complete/linked upstream3404; do not resume it.

## First c016 probes — 2026-09-07

Fresh checkdiff confirms missing one stw/lwz pair, archive argument scheduling,
and a thumbnail end-marker/conversion overlap. Other18TU functions matched.
Ten controlled source tests: three resource getters (main_joint,main_shapeanim,
warn_animjoint), each with embedded result assignment into a one-field pointer
record or sequential record return; four thumbnail delta assignments comparing
embedded and sequential end_pos updates for X or XYZ. No retained improvement.
Embedded main_shapeanim96.644516/frame400, warning98.023186/frame400; sequential
record forms97.00618 or97.95363/frame408. Delta forms96.24266–97.587326/frame400.

Six discarded archive-pointer comparisons after main_joint assignment, before
lbArchive_LoadSections: archive versus main_joint/page_joint/warn_animjoint,
each equality and inequality. Main inequality96.474495 and page inequality
95.04637 preserve frame400 and recover the missing stw/lwz opcode counts.
Both still have two extra MR and two missing ADDI versus target, plus changed
scheduling/registers. This is a new diagnostic source witness of the spill-pair
count, not proof of matching spill identity/slots or a retained source gain.
Other comparisons regress and still miss memory operations. Compare the main
inequality candidate's first-round spill decisions with baseline next, rather
than treating the recovered opcode counts as a match.

Retail cost hook with90-second bound timed out before target capture; launcher
confirmed killed process group, exit2, no cost data. This is no allocator
evidence. Reuse a longer bounded capture or the working Windows path.

Parser caveat: installed shared tooling and c016 colorgraph_parser still drop
rows suffixed SPILLED. Issue1548 is resolved only in the prior task's branch.
Read-only imports from its tools/melee-agent recover first-round spills
49,50,42,36,38,35,89,144,141,142,139,140; round2 spills48; round3 succeeds.
Do not trust final-only colors or stale virtual IDs. In the archived upstream
precolor dump, page-name address is138(data+760), warning name143(data+908).
No tooling files changed here. Source restored; candidates, ordinary diffs,
scripts and failed-capture log archived in2026-09-07-c016-pressure-resume.

## Page-name spill improvement and fresh captures

Captured exact retained baseline and main-inequality candidate on Windows using
scoped IPv4/SCP staging and isolated snap_pcdump.ps1 with actual TU flags
(Cpp_exceptions off, MUST_MATCH, warnings off). Both exit0 in under one second,
source and stock DLL restored. Fresh baseline agrees with prior spill rounds.
Main inequality recovers the wrong pair: it additionally spills warning-name
data+908 and material-name+960 while no longer spilling data+788. Not retained.

Five page-name lifetime controls: named page local assigned before archive call,
compared to persistent snap after the call (equality or inequality), placement
before main-GObj comment versus after GObj_Create, and named-only control.
Equality98.12674/frame400; inequality97.80835/frame400; both placements identical.
Named-only98.05873. Moving the initializer into the existing archive argument
preserves literal pool order and improves equality to98.13447; inequality97.81607;
embedded named-only control exactly restores98.06646. Retained embedded equality:
const char* page_name; argument(page_name="MenMainPhotoSn_Top_joint"); after call
(void)((const void*)page_name==(const void*)snap).

Ordinary output has target opcode inventory647, frame400, all18neighbors100 and
data100. Fresh retained Windows capture SHA256
bc8d4534910ee3b5f36e541c1a4a437049cf1cc8bd04b9c7f8b7270b2a3717ba,
compile0.981s. First-round spills now include page-name IG64(data+760), in
addition to the baseline roles. Warning name remains unspilled and finalr27,
as in target. This confirms desired spill identity, not just opcode counts.
Later second-round spill remains48; final round succeeds.

Stack residual now clear: page home224 matches target; warning-animation address
state+108 is stored at228 instead of target196. No current instruction uses196.
Subsequent temporary slots and second-round csr animation spill move by4bytes:
current252 versus target248. The initial interpretation as merely a duplicate
getter temporary is not established: direct named warning argument98.10664,
and address-taking identity getter(void***resource)->*resource is byte-neutral.

Seven combinations replacing warning/main/main-shape getters by named arguments
all neutral or worse (97.63988–98.10664). Seven combinations changing those
getters to accept addresses of named resource pointers: warning-only neutral,
others96.462135–96.976814. All frame400. Restored retained source. Next inspect
ownership of unused home196 and spill-home placement; do not repeat plain
warning pointer aliases. Initializer still structurally/scheduling mismatched,
not allocator-only. Full captures, probes, corrected-parser analysis and retained
ordinary diff archived in2026-09-07-page-name-spill.

## Warning home ownership controls

Read prior task's d82d-snap-init-final/retail/backend-trace.v1.json: frame base8,
call area144, named warn_animjoint relative44 => absolute196. This historical
capture establishes the earlier named owner; it is not a fresh capture of the
retained source's home list. The current ordinary output never accesses196 and
loads warning animation via228 even at the final AddAnimAll call (+934).

Five explicit write-back forms: embedded getter assignment neutral98.13447;
embedded field assignment98.10664; output-parameter getter returning assignment
98.10664; separate output assignment and return98.037094/frame408; nested named
return assignment98.10664. Others frame400. Removing the earlier assignment
was part of each test; all values are assigned before use.

Six type controls: HSD_AnimJoint**, void* const*, const void**, with original
getter or direct archive argument. Getter forms98.13447, direct98.10664, all400.
Six page-comparison partners instead of snap: warning animation/material/shape,
main joint/animation, page joint. Main joint98.12519; others98.13447, all400.
No retained changes. These17 controls do not support a simple alias/type/use
repair of the slot owner. Next inspect value-numbering/copy-propagation and
spill-home assignment rather than repeating these forms.

PR3406 merged during this turn; synced upstream and restored source before
build. Evidence and historical frame excerpt in2026-09-07-warning-home-owner.

## Warning copy propagation and direct-source capture

Retained precolor passes contain addi r90,r107,108; mr r34,r90; mr r98,r90
before global optimization. r34 is used for the later warning animation load.
AFTER VALUE NUMBERING retains these copies. AFTER COPY PROPAGATION removes
r34/r98 copies and redirects both archive store and late load to90. Thus the
first disappearance is before coloring. trace-copy incorrectly labels this
coloring-coalescing because final colors happen to equalr0; issue1561 filed.

Eight in-place pointer-update diagnostics (previous/next field and increment/
decrement, with getter/direct argument) regress96.92736–97.26739/frame400 and
alter instruction count. None retained. These cross-member pointer-arithmetic
forms are diagnostic only, not source candidates to publish.

Fresh Windows capture of prior direct-warning candidate succeeds, sourceSHA
de94ae80fd2ee79dc47db4f7f4133a6d39b10a52aafa61e7552f744a5ccbfbe9,
compile0.912s. BEFORE GLOBAL already definesr34 directly; it survives copy
propagation and spills in first coloring round. Therefore merely preserving
the named vreg does NOT solve the stack-home placement. The ordinary candidate
still98.10664 and not retained. This corrects the overly narrow idea that the
removed copy alone explains the offset mismatch.

Attempted fresh frame capture with existing backend_map_probe_hook.py at120s:
timeout before target data, launcher killed owned group, exit2. Earlier cost
capture had same no-target symptom at90s. No frame evidence from either timeout;
historical frame naming must not be presented as today's final object layout.
Retained source98.13447 unchanged. Evidence in2026-09-07-warning-copy-propagation.

## Current retail home ownership recovered

A frame-only version of the existing retail probe, with immediate function
progress, completes with timeout300 (the120-second run reached the target but
did not finish). Increasing the probe sample from6 to256 captures89 locals.
Current retained source has base8+callarea144, matching the ordinary frame.
**main_joint owns relative44, absolute196**; warn_animjoint has raw offset0
(no assigned home), and compiler temporary @1905 owns relative76/absolute228.
This supersedes the historical claim that warning owns196 on the current seed.
Raw-zero object offsets must not be reported as occupied absolute152 slots.
Vectors are160/172, card_status184, photo_count188, zero192, warning material
200, warning shape204, warning joint208, pagejoint212, cursor material216,
cursor shape220, page_name224, cursor animation252. Probe evidence is diagnostic
and has not received a new retail/debug object-fidelity promotion.

Five ordinary controls based on the ownership finding: exchanging main/warning
declarations and moving main_joint assignment before/after warning or first
in the resource assignment group are all neutral98.13447. Removing main_load
alias regresses98.12519. All frame400,647instructions; restored afterward.
Simple declaration/assignment order therefore does not transfer this home.
Next useful comparison is the direct-warning candidate's actual current retail
home map (the named vreg survives there but ordinary offset196 still is unused),
to distinguish a persistent main_joint reservation from a changed owner.

Issue1562 updated with successful bounded workaround and claim released;
general tooling not changed. Issue1564 records default target extraction failure
in debug suggest frame. Supplying a sliced single-function target works, but
returns only generic frame-equality advice, not object ownership.
Evidence: matching-evidence/mnsnap/2026-09-07-retail-frame-recovery.

## Resource spill homes fixed: 98.15765%

Fresh direct-warning retail trace completed. Main_joint still owns relative44
(absolute196), while named warn_animjoint gets relative48 (absolute200); all
following resource locals shift4. Raw compiled object parity against the
ordinary direct-warning compile is exact:105552bytes, SHA256
ad7d37e4b8eaabd8717872af0866bb564b36eddcfa4b302f386fdb3251afd6fb.

Eight combined controls then removed the early main_joint alias entirely,
using either direct field or getter at the main model load, separate/embedded,
with direct/getter warning argument. The winning direct-warning + separate
main_load=&snap->main_joint scores98.15765; embedded main getter ties. Choose
the simpler separate field spelling. Other six regress98.12519 or lower.
Unused warning getter removed, whitespace cleaned; ordinary score unchanged.
All resource-pointer homes now match: warning196,material200,shape204,joint208,
page212,cursor material216/shape220,page name224, strings228..244,cursor anim248.
Frame400 and647instructions preserved. Store scheduling still differs in the
early archive setup. Eighteen neighbors100 and1616databytes100. Configure/ninja
pass; TU remainsLinkable and initializer incomplete.

Source commit615cd2f5da; fresh clean PR branch codex/mnsnap-resource-homes,
worktree /tmp/melee-c016-snap-resource-pr, source commit6304289df5. Push every
further gain to this PR while open. Previous3406 merged. Evidence in
matching-evidence/mnsnap/2026-09-07-resource-home-gain.

## Fresh arrows allocation on PR3407 seed

PR3407 opened with6304289df5. New patched-DLL capture SHA542798716f9634669f55e543a218e0c8df45bfd8199ff3596785242ce8111ed0
confirms arrows_joint IG41/r18 and arrows_shapeanim IG39/r17; desired41/r17,
39/r18. Corrected d82d parser used for lifetime-pressure, final colors confirmed.
They interfere across archive call, neither spilled, no coalesced aliases.
Six discarded comparison-lifetime probes: equality/inequality before archive,
after archive, after arrows creation. After equality neutral98.15765; after
inequality98.0881. Before equality97.598145/frame392/two fewer instructions;
before inequality96.66924/frame400/one fewer instruction. None retained.
Smaller hunk count in392candidate is diff merging, not a structural improvement.

Read-only select-order search generated an invalid address-owner rewrite:
replace arrows_joint=&snap->arrows_joint with temp=snap->arrows_joint;
arrows_joint=&temp. Archive output must update persistent snap field; this
probe redirects it to a local. Rejected without compilation, issue1565 filed.
Do not treat generated low-risk labels as semantic validation. Evidence under
matching-evidence/mnsnap/2026-09-07-arrows-pressure.
Independent thumbnail task incorporated3407 and refreshed WvrZ0; reports public
1712/64700 separately from local98.15765. Qhghg public source has invalid first
vararg pairing and is not a production candidate.

## Arrows carriers and staged loads: eight negative controls

On98.15765 seed, one-field void** carriers for arrow joint or shape both
98.10664/frame400; both carriers98.06646/frame408. Grouping all4 arrow resource
pointers in a local struct scores98.06801/frame416 in forward or reverse
member order. Every variant retains the wrong joint r18 / shape r17 pair at
ordinary offsets3c4/474. This carrier family does not move the required color.

Staging actual HSD_Joint* descriptor load immediately before HSD_JObjLoadJoint
is neutral98.15765. Staging HSD_ShapeAnimJoint* before AddAnimAll, alone or with
the model descriptor, scores98.11901; allframe400. No source retained.

Fresh spill-round comparison: old98.13447 spills49,50,42,36,38,35,90,144,141,
142,139,140,64 then48. Current98.15765 spills49,50,42,36,38,34,35,142,139,140,
137,138,64 then48. Physical resource identities/string offsets must be mapped
across changed temp IDs. Page-name64 remains first-round spill, cursor48
second-round spill. No spill-round movement from the resource-home fix.

All applicable CI checks on PR3407 are now passing, including Nix.
Evidence in matching-evidence/mnsnap/2026-09-07-arrows-carrier-staging.

## Archive resource name ownership and partial target diagnostic

Six page-name inline controls preserve literal source order: direct/named-result/
output-parameter string identity helpers, with assignment inside or outside the
call. Direct-inside neutral98.15765; direct-outside/named-inside98.06955;
named-outside98.029366/frame408; output forms98.149925/frame400. None retained.

First-divergence on fresh source targets128:7,129:5,130:4,132:6,133:7,134:8,
135:5,136:9, mapped by constant-string byte offsets, reports IG132 (string592,
cursor shape resource) at iteration65: currentr5,targetr6,caseB. It explicitly
sets earlier_unmapped_warning=true: earliest among supplied targets, not a
complete causal explanation of the target allocator. Advisory array-index
source suggestions do not apply to a constant resource-name address.

Three directed cursor-shape-name controls: embedded named local is neutral;
discarded post-call equality97.10355 and inequality97.98918, each two fewer
instructions, allframe400. Do not promote. The exact spill/color changes were
not captured for these rejected forms. Nine source probes total this pass.

Historical review links issue1565 to earlier1544 (same unsafe generated address
rewrite); recurrence noted in queue. PR3407 unchanged, no new source gain.
Evidence in matching-evidence/mnsnap/2026-09-07-archive-name-ownership.

## Instruction-first priority and recovered front-end inspection

USER STEERING: prioritize matching instruction sequence before isolated register
swaps. Both streams have647 instructions and identical opcode inventory. A
coarse opcode-only alignment differs in archive10c..170 and thumbnail5c4..5d4
(lis earlier than target). This is not full semantic instruction equivalence.
Defer isolated arrows coloring experiments.

Current page pointer42 stays among early field-address assignments through COPY
PROPAGATION/CODE MOTION. AFTER INSTRUCTION SCHEDULING moves its definition next
to string724 and the csr_shape argument store. Coloring adds page_joint spill
throughr0 following the r0 outgoing store32. Target usesr4 for early page address
and spill after outgoing store24. This is an observed current-source pass
transition, not proof of the target compiler's unseen intermediate state.

Independent callee audit: lbArchive_LoadSections has va_list GPR count2
(lis r0,512 at+38; store+6c) and first va_arg+8c returns name, supporting the
existing two-fixed-argument signature. A third fixed name is not justified.

Inspector a failed PRE because worktree-doctor downgraded branch wrapper,
removing generated include provisioning. Missing build/GALE01/include confirmed
onremote; child_reaped=true. Restoring HEAD wrapper (and doctor-edited debugDLL
source) preserves existing validations and fixes it. Invocation b succeedsexit0,
publishes889KB full-TU ENodes with initializer and both variable lists. Issue1526
updated. Do not reapply doctor downgrade or claim Windows/fetch unavailable.

Frontend shows FORCELOAD for main joint/shape getter arguments, ordinary local
page_joint, and embedded page_name assignment. Three page controls (getter with
existing alias, embedded getter assignment, embedded direct field assignment)
score98.14374/98.14374/98.15765 respectively, allframe400. All have exactly the
same opcode order as retained source; no instruction-order gain and none kept.
Next useful evidence is the scheduler dependency/priority cause for page address
motion; isolated ForceLoad introduction did not solve it.
Evidence: matching-evidence/mnsnap/2026-09-07-instruction-first.
