# Structural pattern corpus-diff: mn/ idioms vs our 4 residual TUs

Session: wall/corpus-patterns, worktree `.claude/worktrees/corpus-patterns`.
Scope: `src/melee/mn/mndiagram.c`, `mndiagram2.c`, `mndiagram3.c`, `mnvibration.c`
(+ `mnvibration.h`). Compared idioms used by MATCHED functions within these
same 4 TUs (best-controlled comparison: same compiler/era/author pool)
against every currently-OPEN residual, targeting the 5 pattern classes in
the task brief.

Environment note: `build/GALE01/report.json` needed a full `ninja` build;
this worktree was missing `src/melee/ft/ft_459A.c` (known pre-existing
config-drift issue per ground rules, present on master too). Since it's
unrelated to mn/ and touching sibling worktrees is out of bounds, I
temporarily added a local-only, untracked 0xC28-byte `.bss` stub just to
let `configure.py`/`ninja` produce a report.json for `checkdiff.py`, then
deleted it before finishing. Worktree is clean (verified `git status --short`
empty) at the end of this session.

## Complete residual list (report.json, 2026-07-02)

| Function | % | classification |
|---|---|---|
| mnDiagram3_PopulateRankings | 95.84 | instruction-sequence (indexed scan; sibling effort active) |
| mnVibration_HandleInput | 96.26 | control-flow-source-shape (stack-slot shear; sibling `cluster-mnvib-tail` active) |
| mnDiagram_DrawGridValues | 96.42 | normalized-structural-near-match (2 lines) |
| mnVibration_Think | 97.00 | backend-ceiling (documented, register renumbering only) |
| mnDiagram2_CreateStatRow | 97.92 | instruction-sequence (documented assume-clean dead end) |
| mnDiagram2_GetRankedFighter | 98.12 | normalized-structural-near-match (1 line; sibling effort active) |
| mnDiagram_DrawFighterHeaders | 98.11 | normalized-structural-near-match (2 lines) |
| mnDiagram3_HandleInput | 98.50 | backend-ceiling (99.9% opcode, pure coloring) |
| mnDiagram_InputProc | 98.83 | instruction-sequence (99.6% opcode, pure coloring, documented ceiling) |
| mnDiagram_DrawNameHeaders | 98.84 | stack-layout (structural-match) |
| mnDiagram3_Init | 99.35 | register-allocation (100% opcode, r26<->r27/r27<->r29 swap) |
| mnDiagram2_Create | 99.38 | normalized-structural-match (100% opcode, r25<->r27 swap) |
| mnVibration_IntroProc | 99.39 | register-allocation (structural-match) |
| mnDiagram_CreatePopupTexts | 99.47 | instruction-sequence (99.6% opcode) |
| mnDiagram_UpdateScrollArrows | 99.57 | register-allocation (structural-match) |
| mnDiagram2_HandleInput | 99.58 | normalized-structural-near-match (1 line) |
| mnDiagram_DrawCellValue | 99.88 | normalized-structural-match (100% opcode, f26/f28 tie, 26-shape-exhausted) |

`mnDiagram_OnFrame`, `mnDiagram_CursorProc`, `mnVibration_OnAnimComplete`,
`mnVibration_CreatePortPanels/CreateNameRow/RefreshNameRows/UpdatePortPanel/
CreateScreen`, `mnDiagram2_GetRankedName`, `mnDiagram2_GetAggregatedFighterRank`
are now **100% matched** (some were open per older memory notes — progress
since then). Confirmed via `checkdiff.py --format summary` per function.

## (a) Dual-indexed-walker cleanup-loop pattern — FULLY DEPLOYED, no gap found

The documented lever (`mnvibration_dual_indexed_walker.md`: `ptr2 = data =
arg0->user_data; for(i..) if(data->x[i]) { free(ptr2->x[i]); data->x[i]=NULL; }`)
is already applied everywhere it structurally fits in all 4 TUs:

- `mnVibration_RefreshNameRows` (mnvibration.c:634-639) — canonical form,
  100% matched.
- `mnDiagram2_ClearStatRows` (mndiagram2.c:144-163) — canonical form
  (`ptr = data = ...`), triple field (labels/values/icons), matched.
- `mnDiagram_PopupCleanup` (mndiagram.c:1636-1655) — single-pointer form
  (`data->text[i]`, no dual walker needed because `data` isn't read after
  the loop under a different name), matched, correctly NOT using the
  dual form.

I checked every other fixed-count loop in the 4 TUs (grep sweep of
`for (i = 0; i < N` across all four files) for a candidate cleanup loop
that still uses a single pointer/index where the dual form would help.
The only remaining fixed-count loops are: (1) simple **zero-init** loops
(`mnDiagram3_InitUserData` mndiagram3.c:376, `mnDiagram2_InitUserData`
mndiagram2.c:987) — no conditional free, no second pointer needed, no fit
for the lever, and both are already 100% matched; (2) **linked-list
walkers** (mnVibration_Think's `for(i<port) child=child->next`) — a
different pointer class entirely (traversal, not parallel-array access);
(3) the sort-family scan loops (item b below). **No untested transfer
candidate exists for item (a).**

## (b) Candidate-pointer-walk idiom — genuinely house style, ONE gap left (already claimed by sibling effort)

Confirmed this IS house style across the mnDiagram2 sort family, not a
one-off:

- `mnDiagram_SortFightersByKOs` (mndiagram.c:760-782) — candidate-pointer
  inner scan (`candidate = &dst[++j]; for(;j<0x19;candidate++,j++)`), matched.
- `mnDiagram_SortNamesByKOs` (mndiagram.c:823-849) — same idiom, matched
  100% today (was the "Sort" ceiling in the Jun16-Jul1 siege; cracked via
  fjooord PR-2782's candidate-pointer idiom, commit `ca09d173b`).
- `mnDiagram2_GetRankedName` (mndiagram2.c:1175-1227) — shift loop already
  uses `ptr = &entries[maxIdx]; *ptr = *(ptr-1); ptr--;`, matched 100%.
- `mnDiagram2_GetAggregatedFighterRank` (mndiagram2.c:1238-1319) — bubble
  sort already uses `curr = &entries[k]; ... curr++;`, matched 100%.

**The one remaining indexed (non-pointer-walk) scan in the entire sort
family is `mnDiagram2_GetRankedFighter`'s inner loop**
(mndiagram2.c:1119-1132): `while (k < 25) { if (entries[k].value != neg1)
{...} k++; }` — still indexed, unlike every sibling's shift loop which
already uses the pointer form. This is exactly the transfer target the
task flagged, and per ground rules a sibling effort is already testing it
directly on `GetRankedFighter`/`PopulateRankings` — did not duplicate.
Checked (confirmed) it's the only remaining gap: `GetRankedName`'s and
`AggregatedFighterRank`'s SCAN loops (not just their shift loops) are ALSO
still indexed (`entries[maxIdx].value < entries[j].value`), but both those
functions are already 100% matched with the indexed scan form — meaning
the indexed SCAN form is fine/matches for those two. This means the
pointer-walk transfer for GetRankedFighter is plausible but NOT guaranteed
to be the exact missing byte, since 2/3 matched siblings keep an indexed
scan; the actual blocker there is more likely the `neg1`/
`entries[i].value==neg1` OR-arm specific to GetRankedFighter, worth relaying
to whoever owns that investigation.

`DrawGridValues`/`InputProc` do NOT contain raw indexed-array scan loops at
all — they call the `GetVisibleFighterCursorFrom2`/`GetVisibleNameCursorFrom`
helpers by single index, no loop over a range in the caller itself. The
`Find*/GetVisible*` helper family (mndiagram.c:886-1099, all 10 functions)
already universally uses the dual-pointer-walk idiom (`p`/`p2` incremented
in tandem with `idx`) — confirmed by direct read, no gaps.

## (c) Typed-param-helper vs raw pointer/offset math — no untested gap

Checked every function taking `void*`/`HSD_GObj*` that immediately casts.
`mnDiagram2_CreateStatRow(HSD_GObj* gobj, ...)` already uses the typed
form (not `void*`); its residual is the documented `is_name_mode`
assume-clean catch-22 (`createstatrow_assume_clean_wall.md`) — explicitly
closed on all 3 known axes (register-steering, assume-clean-typing,
prototype-form) as of 2026-07-01, re-confirmed unchanged today
(normalized_diff_lines=4, same classification). Not re-tested per ground
rules (would just reproduce a closed investigation).

`mnDiagram_DrawCellValue`/`DrawGridValues`/`DrawNameHeaders`/
`DrawFighterHeaders`/`ClearGrid`/`mnDiagram_UpdateScrollArrowVisibility` all
deliberately keep `void* arg0` — this is a real, consistent house-style
split from `RefreshGrid`/`UpdateScrollArrows`/`ExitAnimProc` which use
`HSD_GObj*` directly. Checked whether this was ever tested as a lever on
the open Draw-family residuals: per `mndiagram_levers_and_walls.md`, their
residuals are proven pure register-coloring/frame ties (Draw: f26/f28 FPR
tie, 26 shapes tried; DrawGridValues/8024227C: extensive coloring-ceiling
dossier with param-alias root already fixed in C, per commit `8bd6f8648`).
A signature change here would need to touch call sites across
`RefreshGrid`/`OnFrame`, re-testing an axis (param typing) not cited as
untested in either dossier — did not attempt; flagging as LOW priority
follow-up only if register/frame axes are ever fully re-opened.

## (d) Accessor-macro pattern — GET_DIAGRAM already correctly scoped, no bypass found

`#define GET_DIAGRAM(gobj) ((Diagram*) HSD_GObjGetUserData(gobj))`
(mndiagram.c:29) is used in `OnFrame`, `DrawFighterHeaders`, `CursorProc`,
`PopupAnimProc`, `CreatePopup` — 7 call sites, all where the field really
is `Diagram*`. Functions using raw `gobj->user_data` instead
(`mnDiagram_UpdateScrollArrows`, `ExitAnimProc`) were checked individually:
`ExitAnimProc`'s `data` is `mnDiagram_AnimData*`, a DIFFERENT struct type
than `Diagram*` — GET_DIAGRAM would be a type error, not a missed
opportunity. `UpdateScrollArrows`'s direct access was already specifically
tried against the macro form per `mndiagram_levers_and_walls.md` line 22
("802417D0 ... = macro REGRESSES, keep direct") — a closed experiment, not
a gap. **No accessor-macro bypass was found on any open residual.**

## (e) Hoisted-float-constant-to-local — pattern's precondition does not exist in this corpus

Searched all 4 TUs for repeated identical float-constant comparisons
(`!= 0.0f`, `< 0.0f`, `>= 0.0f`, `<= 0.0f`, `> 0.0f` — the lever's exact
precondition, per `hoist_float_const_local.md`, is "compares a value
against the SAME float constant multiple times"): **zero matches** in
`mndiagram.c`, `mndiagram2.c`, `mndiagram3.c`, `mnvibration.c`. Draw's
residual (`row_offset`/`col_offset`) is two DIFFERENT expressions computed
from different variables (`y_spacing*col` vs `y_offset*row`), not the same
constant reused — confirmed via the checkdiff EXPECTED/CURRENT (pure
register-only diff, no immediate/operand difference at all, 100% opcode).
`mnVibration_IntroProc`'s five `mnVibration_804DC050/054/058/05C/060 ==
frame` comparisons are five DIFFERENT named constants, not the same one
reused. **This lever's precondition is absent from the entire corpus under
investigation — confirmed dead end, not worth another look unless a NEW
residual with a genuinely-repeated float constant surfaces.**

## Tested this session

1. **mnVibration_HandleInput exit-cleanup loop-counter reuse** (merge
   `text_idx` into outer `i` instead of a separate block-scoped local, to
   try to coalesce with the target's apparent register reuse at `+0a8`
   `slwi r0,r31,2`). Baseline: opcode 95.3%, ndiff=28. Result: opcode
   **95.2%** (worse), ndiff=29, one MORE register-only diff (14 vs 13).
   **REVERTED, working tree confirmed clean.** (Also: the fingerprint
   tracker flagged this exact baseline as already probed 4x by
   `cluster-mnvib-tail`, i.e. this exact residual is under active parallel
   investigation — appropriately backed off after one confirmatory probe.)
2. **mnDiagram3_Init decl-order search** (`melee-agent debug mutate
   decl-orders --strategy all --keep-best`, targeting the r26<->r27/
   r27<->r29 callee-save swap in the 10-iteration row-label init loop).
   Launched; the shared-worktree CPU contention (7-15+ concurrent
   `ninja`/MWCC processes across sibling worktrees this session) meant it
   accumulated only ~3s of CPU time over 15+ minutes wall-clock. Stopped
   it and verified the one candidate reorder it had written
   (`row0`/`row_spacing` decl swap) was neutral (99.35%, unchanged) via
   checkdiff, then reverted to a clean baseline. **Flagged as the top
   follow-up** below — this is a clean, well-scoped, tool-supported probe
   on a 100%-opcode / pure-coloring residual, exactly the shape the
   decl-order tool has a strong track record on elsewhere in this campaign
   (7/7 mndiagram.c wins recorded in `mndiagram_levers_and_walls.md`), it
   just didn't get a fair CPU budget this session.

## Ranked follow-up recommendations

1. **mnDiagram3_Init decl-order sweep** (re-run on a less-contended
   window) — 100% opcode match, single callee-save swap pair, exactly the
   profile this tool has repeatedly cracked (7 wins on mndiagram.c per
   `mndiagram_levers_and_walls.md`); this specific function was never
   previously run through it. Same recommendation for `mnDiagram2_Create`
   (100% opcode, r25<->r27 swap, also never listed as decl-order-swept in
   memory).
2. **mnDiagram_UpdateScrollArrowVisibility / DrawGridValues / DrawCellValue
   `void*`-vs-`HSD_GObj*` param axis** — plausible but NOT run this
   session (would touch call sites in `InputProc`/`RefreshGrid`/`OnFrame`,
   all currently at high % or 100%, so any test needs to verify it doesn't
   regress those matched callers). Low-confidence, medium effort.
3. **mnDiagram2_GetRankedFighter candidate-pointer scan conversion** —
   already claimed by a sibling effort; if it stalls, relay back that
   `GetRankedName`/`AggregatedFighterRank` keep an INDEXED scan while only
   their SHIFT loop uses pointer-walk (both matched) — the pointer-walk
   transfer isn't guaranteed by house style alone since 2/3 matched
   siblings show indexed scans are also fine; the actual blocker is
   probably the `neg1`/`entries[i].value==neg1` OR-arm specific to
   GetRankedFighter, not the scan's indexing style per se.
4. Items (c)/(d)/(e) are confirmed dead ends for this corpus — do not
   re-run without a genuinely new residual appearing that satisfies their
   preconditions (repeated float constant / raw-pointer-cast helper /
   macro-bypass on a same-struct-type field).

## Worktree state

Clean at end of session (`git status --short` empty). No commits made — no
kept improvement this session; both tested hypotheses were reverted after
verification.
