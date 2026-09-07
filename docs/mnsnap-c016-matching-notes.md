# Snapshot initializer continuation

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
