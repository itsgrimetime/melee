# /understand pass — mndiagram/2/3 + mnvibration (2026-07-01)

Full findings from the read-only /understand analysis agent (verified against DOL + target ASM;
asm dumps referenced live in that agent's scratchpad). Test order: A1 → A2 → A3/A4 → renames.

## A-ranked findings

**A1 (highest codegen impact) — fn_802487A8 dual-view walker.** MnVibrationData layout verified
correct field-by-field; the divergence is access *shape* on `mnVibration_804D4FE8`: target walks a
`u16* panel_joint` (init before loop, `addi r25,r25,2` at loop bottom) for BOTH
HSD_JObjSetFlagsAll/ClearFlagsAll sites, while the toggle-jobj lookup stays *indexed* via
`(u8)port` (`slwi r0,r27,1; lhzx`) through `mnVibration_804D6C28->user_data`. `(u8)port` is
computed once per iter (`clrlwi r27,r23,24`) and reused for the `mulli r0,r27,0x44` PadCopyStatus
index. u32→f32 magic pre-hoisted (`lfd f31, mnVibration_804DC018` + `lis r29,0x4330` before loop).
Proposed C: walking `u16* panel_joint` incremented in the for-header, single `u8 port_u8 = (u8)port_idx`
per iter, `data->jobjs[*panel_joint]` at both FlagsAll sites, indexed `mnVibration_804D4FE8[port_u8]`
for the toggle. Sibling of memory `mnvibration_dual_indexed_walker`.

**A2 — CreateStatRow u8 catch-22: NO data-model fix exists (provenance fully verified:
GameRules.xD u8 → Diagram2.is_name_mode u8@0x48 → both callers pass raw; target GetStatValue body
has `clrlwi. r0,r3,24` so its param IS int).** One untested C probe: give mnDiagram2_GetStatValue a
**K&R-style definition** (`int f(a,b,c) int a; u8 b, c; {...}`) — no prototype ⇒ call sites use
default promotions (raw u8 register pass) while the definition keeps int binding + body masks.
Single compile to test.

**A3 — mnDiagram2_803EEAD0 typed overlay (byte-neutral expected, verify):**
0x00 Vec3 header_pos(-2.5,0.3,0) / 0x0C Vec3 label_pos(-2.2,0.5,0) / 0x18 Vec3 value_pos(-1,0.5,0) /
0x24 Vec3 icon_pos(-2,0,0) / 0x30 u16 label_ids[24] (SIS 0x4A..0x61) / 0x60 u16 unit_glyph_ids[24]
(0x7A times, 0x7B players, 0x7C %, 0x7D coins, 0x7E ft, 0xFFFF none) / 0x90 = 803EEB60 arrow anims.
Target addr-gen in CreateStatRow: `clrlslwi r0,r25,24,1; add r28,r31,r0; lhz 0x30/0x60(r28)` ==
`layout->label_ids[stat_type]` with u8 stat_type. Keep separate 803EEB60 extern for OnAnimComplete.

**A4 — mnDiagram3_803EEC10 typed overlay:** 0x00 exit_anim{10,19,-0.1} / 0x0C arrow_anim{0,199,0} /
0x18 title_pos(3.3,0.5,0) / 0x24 rank_name_pos(-2,0.57,0) / 0x30 value_pos(8,0.57,0) /
0x3C u16 label_ids[24] (0x62..0x79) / 0x6C u16 unit_glyph_ids[24] (tail differs from diagram2:
icon-only stats = 0x7B here vs 0xFFFF there — do NOT dedupe). Keep 4 separate initialized globals in
address order (80247008 recipe); overlay only for base-relative readers (80245BA4/fn_802461BC/8024714C).

**A5 — mnDiagram_803EE728 AnimTable verified CORRECT; Draw does NOT read blob floats** (spacings come
from JObj translations `lfs 0x38/0x3c(rJObj)`; 0.4f from sdata2 pool 804DBFA0). Doc-only renames:
x40→intro_anim{0,9,-0.1}, pad_4C→exit_anim{10,19,-0.1}, pad_24→default_fighter_order[0x1C],
x70/x88/x94→user_data_error/file_name/user_data_name.

**A6 — mnvibration asset names provably WRONG:** 803EECE0 layout fields actually hold:
0x64 MenMainConVi_* (screen root→804A0898), 0xDC MenMainCtlVi_* (port panels→804A0878),
0x154 MenMainOnoffVi_* (name toggles→804A0888), 0x1D8 MenMainCursorVi_Top_joint (cursor→804A0868).
Rename to convi_top_*/ctlvi_top_*/onoffvi_top_*/cursorvi_top_joint; replace MnVibrationAssets
(names wrong, 0x40 span shadows 3 sibling symbols) with four MnVibrationJointAssets. Overlay is
load-bearing (single reloc + addi offsets) — do NOT convert to literals.

**A7 — 804DC030..060 sdata2 floats: keep individual externs (array view breaks relocs).** Values:
0.0, 0.03, -9.5, 9.1, 17.0, 364.68332, 38.38772, 0.0521; 804DC050..060 = 10.0..14.0 = intro reveal
frames for port panels 1-4 + name list. Comment, don't restructure.

**A8 — Diagram2DetailView/JObjContainer are a wrong overlay of Diagram3** (only caller passes
mnDiagram3_804D6C20; container == Diagram3.jobjs[6]; JObjContainer.jobj@0x10 == HSD_JObj.child).
Rewrite ClearDetailView over Diagram3* (byte-neutral, verify; function is 100%); delete both types.
Must stay in mndiagram2.c for link order.

**A9 — NameTagData.x1A1 → rumble_toggle (u8)** (gm/types.h sibling already names it).

**A10 — Sort/stat structures verified correct.** SortEntry union (u64 compare, 2×f64 copy arm
load-bearing, stride 0x10); 804A0750/076C/mnDiagram_Assets sizes+addresses line up; GetRankedFighter
97.47 residual = register tie not model; 80245BA4 = param-area floor #635.

**A11 — Diagram3.saved_selection → cursor_row** (live D-pad row 0..9, drives popup Y + displayed stat).

## Provably wrong vs binary (fix list)
1. `extern f32 mnDiagram_803EE758[]` (mndiagram.static.h:19) is bogus — 0x758 is offset 0xC inside
   u8 table 803EE74C (fighter ids). Delete.
2. mnvibration asset naming inverted (A6).
3. Diagram3.saved_selection is the live cursor row (A11).
4. Diagram2DetailView/JObjContainer misrepresent Diagram3 (A8).
5. Draw-reads-blob-floats premise false (A5).
6. mnDiagram2_804D4FD0 = SJIS "－" placeholder, currently opaque u8[3]; dead `offset += 4` in
   CountTiedFighters/CheckAllZeroPlayTime/AllPlayTimesZero inlines is match-load-bearing — document.

## Naming table (functions)
8023FA6C SortFightersByKOs · 8023FC28 SortNamesByKOs · 80240D94 CreatePopupTexts ·
80241310 CreatePopup · 80241668 ClearGrid · 80241730 RefreshGrid · 802417D0 UpdateScrollArrows ·
80241E78 DrawCellValue · 8024227C DrawGridValues · 802427B4 DrawNameHeaders ·
80242B38 CreateFighterIcon · 80242C0C DrawFighterHeaders · 802433AC CreateCursor ·
80243434 CreateScreen · 802437E8 Init (mndiagram) ·
mnDiagram3: 80245BA4 PopulateRankings · 802461BC HandleInput · 80246D40 UpdateScrollArrows ·
80246E04 OnAnimComplete · 80246E64 Think · 80246F0C FreeUserData · 80246F2C InitUserData ·
80247008 Create · 8024714C Init ·
mnVibration: 802474C4 GetNameRowJObj · 80247510 HandleInput · 80248084 CursorThink ·
802480B4 UpdatePortPanel · 8024829C CreatePortPanels · 80248444 CreateNameRow ·
80248644 RefreshNameRows · 80248748 OnAnimComplete · 802487A8 Think · 80248A78 IntroProc ·
80248ED4 CreateScreen · 80249174 Init.
Data: 803EE74C DefaultFighterOrder · 804D4FA0 GXColor popup text color · 804D4FE8
PortPanelJointIds u16[4]{22,21,20,19} · MnVibrationData.x0[6] → intro_timer/cursor_row/port_mode[4] ·
x6[4] → port_connected[4] · MenuFlow.x10 → vs_records_page (0 grid/1 details/2 rankings).
