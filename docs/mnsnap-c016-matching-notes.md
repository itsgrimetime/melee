# Snapshot initializer continuation

Current retained baseline: **98.13447%**, source8a94f5de1a, PR3406 head9f1bdc6bbf
on codex/mnsnap-initializer-spill. PR worktree /tmp/melee-c016-snap-pr. Push all
further source improvements to this PR while it remains open. Historical
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
