# Corpus-style investigation: mn/ 100%-matched TUs vs mndiagram/mndiagram2/mndiagram3/mnvibration

Worktree: `wall/corpus-style`. Baselines established via a from-scratch
`report.json` build (all mn/*.c objects rebuilt; `src/melee/ft/ft_459A.c` was
temporarily stubbed to unblock the link -- stub removed, worktree left clean,
nothing committed).

## Corpus definition (from report.json, not guesswork)

Per-unit average match% across `melee/mn/*`:

| Unit | avg% | fully-matched? |
|---|---|---|
| mndeflicker | 100.00 | yes |
| mngallery | 100.00 | yes |
| mnhyaku | 100.00 | yes |
| mninfobonus | 100.00 | yes |
| mnlanguage | 100.00 | yes |
| mnmain | 99.95 | no (2/66 open) |
| mnstagesel | 99.96 | no (1/14 open) |
| mncount | 99.34 | no (3/21 open) |
| mnname | 99.21 | no (8/37 open) |
| mnnamenew | 97.85 | no (13/25 open) |
| mnruleplus | 96.15 | no (3/9 open) |
| mndiagram (target) | 99.80 | no (7/45 open) |
| mndiagram2 (target) | 99.76 | no (4/21 open) |
| mndiagram3 (target) | 99.30 | no (3/9 open) |
| mnvibration (target) | 99.39 | no (3/12 open) |

The task brief cited mnname/mnnamenew as fully-matched siblings, but the
current tree shows both with open residuals (mnname 29/37, mnnamenew 12/25).
I treated mndeflicker, mngallery, mnhyaku, mninfobonus, mnlanguage as the true
"100%" corpus, and used mncount (99.34%, only 3 open, and structurally the
closest sibling -- same VS-records/menu family as mndiagram/mndiagram2) as a
secondary high-value reference since it shares idioms directly with the
targets.

Fresh baselines for all 15 named target functions (fuzzy_match_percent from
report.json):

| Function | % |
|---|---|
| mnDiagram_DrawCellValue | 99.88 |
| mnDiagram_DrawGridValues | 96.42 |
| mnDiagram_InputProc | 98.83 |
| mnDiagram_DrawNameHeaders | 98.84 |
| mnDiagram_DrawFighterHeaders | 98.11 |
| mnDiagram_CreatePopupTexts | 99.47 |
| mnDiagram2_CreateStatRow | 97.92 |
| mnDiagram2_GetRankedFighter | 98.12 |
| mnDiagram3_PopulateRankings | 95.84 |
| mnVibration_Think | 97.00 |
| mnVibration_HandleInput | 96.26 |
| mnVibration_IntroProc | 99.39 |
| mnDiagram2_HandleInput | 99.58 |
| mnDiagram_UpdateScrollArrows | 99.57 |
| mnDiagram3_Init | 99.35 |

## Convention catalog: delta found, cosmetic vs plausibly match-relevant

1. **`int` vs `s32`/`u32` loop counters -- NOT a uniform corpus convention.**
   `mncount.c` (matched) itself uses bare `int i, j` for its selection-sort
   loops (`mnCount_8025035C`, line ~160-161) right alongside `s32` elsewhere.
   The targets are equally mixed (`mnDiagram_DrawNameHeaders`/
   `DrawFighterHeaders` use `int i`; `DrawCellValue`/`GetRankedFighter` use
   `s32 i`). Verdict: cosmetic at the file level -- already tuned per-site in
   both corpus and targets, not a missing sweep.

2. **`register` keyword** -- appears exactly once tree-wide in mn/
   (`mndiagram3.c:393`, `register HSD_GObj* gobj` in `mnDiagram3_Create`,
   already matched at 100%) and nowhere in the fully-matched corpus files.
   Verdict: cosmetic / already applied where needed, not a gap.

3. **`volatile` locals -- a real, under-used lever.** `mncount.c:553`
   (matched) uses `HSD_Text* volatile value_text = userdata->values[...]`
   inside a scoped block purely to force a reload/defeat CSE before a
   `HSD_SisLib_803A5CC4` call -- the same idiom documented in memory
   (volatile-ptr-keeps-assert) and in `mnruleplus.c`'s file-scope
   `volatile const f64` / `volatile f32` globals. None of the 4 target TUs use
   a `volatile`-qualified local anywhere. Verdict: plausibly match-relevant in
   general, but no open residual among the 15 targets matched this idiom's
   signature (stale-reload/duplicate-call). Flagging for anyone who hits a
   "value read twice, should be reloaded once" residual.

4. **Doxygen `/// @brief` block comments are NOT a matched-corpus
   convention** -- mndiagram.c (65 hits) and mndiagram2.c (71 hits) have far
   more doc-comments than any of the 5 fully-matched files (0 each, aside
   from 1-2 incidental in mnname/mnruleplus). This is campaign-added
   documentation layered on top of already-matched code elsewhere in the
   tree. Verdict: purely cosmetic, no codegen relevance, and not something to
   "fix" toward a corpus norm since the corpus norm is actually sparser.

5. **`(void) &stack_obj;` address-taken-but-unused idiom is UNIQUE to
   mndiagram.c** (`mnDiagram_DrawFighterHeaders` lines 2626-2628, and one more
   at line 2804 in `mnDiagram_CreateCursor`) -- zero occurrences anywhere else
   in mn/, matched or not. This pattern (declare a stack buffer, take its
   address to force a stack slot, then `(void)`-discard it without ever using
   the pointer) reads as scaffolding standing in for a missing real write
   through that address (per the accessor-macro/inline-frame lever pattern).
   Verdict: plausibly match-relevant as a *symptom* of a missing inline;
   worth a follow-up pass specifically on `mnDiagram_DrawFighterHeaders`
   (98.11%) and `mnDiagram_CreateCursor` to find the real HAL call that
   should own that stack address instead of the placeholder cast.

6. **`GET_X(gobj)` HAL accessor macros -- real, project-wide, and
   inconsistently applied across the target TUs.** `mn/inlines.h` defines
   `GET_MENU`/`GET_DIAGRAM`; `mncount.h` defines its own `GET_MNCOUNT` and
   uses it pervasively (10 call sites, matched-adjacent file). None of
   mndiagram2.c, mndiagram3.c, or mnvibration.c define an equivalent
   `GET_DIAGRAM2`/`GET_DIAGRAM3`/`GET_VIBRATION` macro -- every `->user_data`
   access in those three files is a raw cast. This is exactly the documented
   accessor-macro-inline-frame lever (frame + coalescing lever, proven on
   `mnDiagram_80241310`, not cosmetic). Tested on `mnDiagram_UpdateScrollArrows`
   (single top-level `Diagram* data = gobj->user_data;` site, carries
   `PAD_STACK(8)` -- exactly the lever's trigger signature): checkdiff shows
   this residual is a pure register-permutation swap (r22/r23/r25 across two
   structurally-identical unrolled lookup loops), classification
   `register-allocation`, `source-shape-not-frame-reservation` -- checkdiff
   itself already ruled out the PAD_STACK/frame explanation here. I did not
   find a target function among the 15 where the macro's frame-reservation
   signature (PAD_STACK present + callee-save permutation + no addressed
   locals) was the dominant residual; `mnDiagram2_HandleInput`
   (`PAD_STACK(40)`, multi-site `->user_data`) is the best remaining
   untested candidate -- I did not get to it (see follow-up list). Verdict:
   plausibly match-relevant, proven lever elsewhere in this exact module
   family, worth a dedicated pass on `mnDiagram2_HandleInput` and defining
   `GET_DIAGRAM2`/`GET_DIAGRAM3`/`GET_VIBRATION` macros per-site (test each
   site individually, keep only wins, per the lever's own triage rule).

7. **`Menu_GetAllInputs()` inline-call vs manual-inline body -- a false
   lead.** `mnDiagram2_HandleInput`/`mncount.c`/`mnevent.c`/`mninfo.c`/
   `mnsnap.c` all hand-inline `x = mn_804A04F0.buttons = mn_80229624(4);`
   instead of calling the `inlines.h` helper, while `mndiagram.c`/
   `mndiagram3.c`/`mngallery.c`/etc. call `Menu_GetAllInputs()` directly. Both
   forms coexist in the matched corpus, so this is already a per-site,
   match-driven choice, not a convention gap. Verdict: cosmetic, ruled out.

8. **Anonymous magic-constant / sdata2 float-pool ordering -- real, but
   this is a register/pool-allocation wall, not a source idiom gap.** Tested
   on `mnDiagram3_PopulateRankings` (95.84%, 16 normalized diff lines,
   `instruction-sequence` classification -- looked structural at first
   glance). The diff shows `f27`/`f28`/`f29` assigned to
   `mnDiagram3_804DC010` (icon_x_offset) / an anonymous, never-referenced
   `extern f64 mnDiagram3_804DC000` / `mnDiagram3_804DC008` (divider) in a
   different order than ours. Swapping the C-level assignment order of
   `icon_x_offset`/`divider` (the two named floats) does not reproduce the
   expected order, because the anonymous f64 constant sits textually between
   them in the pool and isn't controllable from a named-variable reorder
   alone -- this is the `(f32) i` int-to-float conversion idiom's implicit
   double, and its pool position is a genuine SDA2-allocation-order question
   (anon-magic-constant workflow), adjacent to the register-coloring wall the
   other agents are already working. Tested and reverted (wrong direction --
   see Tested section). Verdict: plausibly match-relevant in principle but
   this specific instance is coloring/pool-order territory; flagged for the
   register-coloring team rather than re-attempted here.

9. **Widen-through-an-`int`-local for a `u8` parameter forces an
   unnecessary `clrlwi` at function entry -- genuine, isolated, C-level
   finding.** `mnDiagram2_CreateStatRow` declares `int mode = is_name_mode;`
   at the top of the function (line 622) purely because the 7 downstream call
   sites to `mnDiagram2_GetStatValue(int, u8, u8)` need an `int`. The matched
   target asm does the u8-to-callee-save move for `is_name_mode` with a plain
   `addi r24,r4,0` (no mask), proving the widening must be deferred to each
   call site rather than materialized once at entry. Removing the `int mode`
   local and substituting `is_name_mode` directly at all 7 use sites exactly
   fixes the diff line in question (the `clrlwi r28,r4,24` at function entry
   disappears, replaced by the expected plain move) but nets worse overall
   (normalized_diff_lines 4 to 9) because it perturbs a pre-existing,
   independent `row_idx`/`entity_idx` (r26<->r27) callee-save permutation
   that happens to currently cancel out under fuzzy-match scoring with the
   wider frame. Verdict: plausibly match-relevant and the `clrlwi` fix in
   isolation is provably correct -- but it's coupled to a second, still-open
   coloring residual. Reverted (see Tested section). Best next step for
   someone continuing register-coloring work on this function: apply the
   `int mode` removal together with a fix for the r26/r27 swap (try
   force-phys on r26/r27, or vary the C declaration order of
   `row_idx`/`entity_idx`) rather than alone.

## Tested (compile + checkdiff, all reverted -- no keepers this session)

| Function | Hypothesis | Result |
|---|---|---|
| mnDiagram3_PopulateRankings | Swap icon_x_offset/divider assignment order to fix f27/f29 anon-double pool order | No improvement in the tested direction (expected order is icon_x_offset, [anon], divider; swapping put divider first, made it worse). Reverted. |
| mnVibration_HandleInput | Replace scoped `s32 text_idx` re-assigned to `i` with reusing `i` directly in the exit-branch text cleanup loop | normalized_diff_lines 28 to 29 (regression) -- the register reused in expected (r31) comes from cross-branch coloring reuse, not variable identity. Reverted. |
| mnDiagram2_CreateStatRow | Remove `int mode = is_name_mode;` local, pass `is_name_mode` directly to all 7 mnDiagram2_GetStatValue call sites | Exactly fixes the targeted clrlwi instruction, but normalized_diff_lines 4 to 9 net (couples to a pre-existing r26/r27 permutation). Reverted. Also tried compensating with PAD_STACK(8) -- wrong direction (frame overshoot to 144 vs expected 136). Reverted. |

All three reverts confirmed clean (git status clean, objects rebuilt back to
baseline .o's) before finishing.

## Ranked follow-up list (most worth chasing, in order)

1. mnDiagram2_CreateStatRow `int mode` removal + r26/r27 coloring together
   (item 9) -- highest confidence, smallest/cleanest isolated diff (started
   at only 4 normalized diff lines), and the fix for half of it is already
   written up above. Combine the `int mode` removal with a targeted
   force-phys or declaration-order probe on row_idx/entity_idx.
2. mnDiagram2_HandleInput GET_DIAGRAM2 macro test (item 6) -- the
   accessor-macro lever is proven in this exact file family
   (mnDiagram_80241310) and this function has the strongest trigger
   signature (PAD_STACK(40), 5+ raw ->user_data sites) of any untested
   target; not reached this session.
3. mnDiagram_DrawFighterHeaders / mnDiagram_CreateCursor `(void)
   &stack_obj` archaeology (item 5) -- a real, unique-to-this-file
   scaffolding smell that likely hides a missing inline; needs someone to
   find what real HAL call should own that stack address.
4. mnDiagram3_PopulateRankings anon-double pool order (item 8) -- likely
   belongs to the register-coloring/pointer-walk parallel effort rather than
   a separate pass; flagging so it isn't independently re-discovered.
5. volatile local lever (item 3) -- no current target match, but worth
   keeping in mind for any future "duplicate read should CSE away" residual.

## Notes on process

- report.json required a full-tree build; src/melee/ft/ft_459A.c is missing
  on this branch (pre-existing, per ground rules, present on master too -- a
  bss-only TU with no functions). I stubbed it locally with correctly sized
  bss arrays purely to unblock the link, generated report.json, then deleted
  the stub. Nothing from that stub was committed; git status is clean at the
  end of this session.
- System load was very high throughout (7 other parallel agents on the same
  functions/tools, load average ~200) -- several checkdiff.py --summary
  invocations without --no-build timed out on report.json regeneration or
  hit an unrelated sqlite attempt-tracking KeyError in
  tools/melee-agent/src/cli/tracking.py: increment_replay (likely
  concurrent-write contention on agent_state.db, not reported as a new issue
  per this session's ground rules -- direct-investigation only, no
  issue-resolver loop).
