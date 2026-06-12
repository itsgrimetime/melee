# Door-A Matched-Corpus Miner Report

**Date:** 2026-06-11
**Worktree:** `.claude/worktrees/mndiagram3-campaign` (branch `claude/mndiagram3-campaign`)
**Mission:** Mine the already-matched (`fuzzy_match_percent == 100`) function corpus
for the "Door A" construct — a C structure that creates a *genuine IR-level `mr`/copy
between a constant-load and a runtime value*, i.e. a same-value copy that **survives**
to the register allocator (a second live virtual with a copy edge) rather than being
folded away by IRO at PCode construction.

**Verdict (headline): Door A construct FOUND — three distinct, byte-confirmed shapes,
all present in the target TU (`mndiagram.c`) itself.** See the DECISION section.

---

## 0. Background — the wall this serves

`docs/mwcc-allocator-mechanism-deep-dive.md` established that MWCC erases variable
*identity* at PCode construction (it tracks VALUES, not names): `scroll_offset = 0`
and `data->texts[i] = NULL` produce byte-identical IR, so a constant-init local and a
later runtime-load of the "same" variable land in two **disjoint, non-interfering**
virtuals that no pass can unify. The deep-dive names three escape routes; **Door A** is
"different C source structure that creates IR-level `mr` instructions between the
constant-load and runtime-load values." Nobody had mined the matched binary+source
corpus to see whether such a construct actually exists in shipped code and what C shape
produces it. That is this report.

Three parked target sites motivate the hunt:
- **`mnDiagram_InputProc +048`** — a zero loaded (`li`) then COPIED (`mr`/`addi rY,rX,0`)
  into a second live register (the *constant-rider* / zero-rider fingerprint).
- **`mnDiagram_80242C0C +13c`** — `addi r26,r21,0`, a surviving copy of a runtime jobj
  pointer (the *runtime-value-copy into a frame-group survivor* fingerprint). Confirmed
  target site: `80242D48  addi r26, r21, 0x0`, right after `bl HSD_JObjAnimAll` /
  `lwz r19,0x24(r27)`, just before a `cmplwi r19,0; bne; __assert` and a downstream loop.
- **`mnDiagram2_HandleInput S2`** — a third surviving-copy site (same family).

---

## 1. Scan stats (Phase 1)

Read-only scan over `build/GALE01/asm/**` (objdump-format `.s`), filtered to functions
matched at 100% per `build/GALE01/report.json`. Scanner: `/tmp/doora_scan.py`
(per-`.fn` block parse + per-opcode GPR def/use model + linear reaching-def & forward
liveness windows). Raw hit dump: `/tmp/doora_hits.json`.

| Metric | Value |
|---|---|
| Matched functions in report (==100) | 18,748 |
| ASM `.s` files scanned | 1,053 |
| `.fn` blocks parsed | 19,835 |
| Matched `.fn` blocks scanned | 18,771 |
| `.fn` blocks skipped (not 100%) | 1,064 |
| Instructions parsed | 970,518 |
| **Class (a) constant-rider hits** | **148** |
| **Class (b) runtime-value-copy hits** | **4,996** |

### Class (a) constant-rider — `li rX,K` … later `mr/addi rY,rX,0`, both live

148 hits. K distribution: `0x0`×123 (the zero-rider — the InputProc +048 K), plus a
long tail of small constants (`0x1`×5, `-0x1`×4, `0x3`×3, etc.). Near-exhaustive by
design. Of the 148, **9 are loop-counter snapshots** (`rY = rX; rX++`, where the source
register is incremented on the immediately following instruction) — e.g.
`mnDiagram_GetLeastPlayedFighter @ 8023F974`, `__THPHuffGenerateDecoderTables @ 80330F90`,
`CARDOpen @ 80357618`. **11 of the 148 are in the target TU `mndiagram.c`.**

### Class (b) runtime-value copy — mid-block `mr/addi rY,rX,0`, both live

4,996 raw hits, but this class needs precision tiering (the brief warned recall < precision
here). Filter cascade:

| Tier | Count | Note |
|---|---|---|
| Raw class (b) | 4,996 | all surviving non-prologue/epilogue/argsetup copies |
| **Noise**: rX is an incoming arg / has no in-function def | 4,285 | copying a param into a 2nd reg — mostly caller-save preservation, low signal |
| **Signal**: rX defined by a load/compute (`lwz/addi/add/lbz/...`) | 598 | rX is a *computed/loaded runtime value*, the Door-A-relevant subset |
| … copy is `addi rY,rX,0` (pointer-copy fingerprint, == `80242C0C +13c`) | 359 | |
| … dest is callee-save `r14–r31` (survivor across calls/loops) | 210 | |
| … in melee `src/` | 183 | (top files: mpcoll 21, grlast 12, **mndiagram 10**, gm_16AE 7, ftcoll 7) |

The 210 callee-save pointer-copy survivors are the high-value class-(b) catalogue: a
loaded/computed pointer copied into a callee-save register so it outlives subsequent
calls and loop bodies — structurally identical to the `80242C0C +13c` jobj copy.

**Filter caveats (precision/recall):** The reaching-def walk used by class (a) is
*linear* (by instruction index), not control-flow-aware, so a reported `li rX,K`
"reaching" a copy may have an intervening redefinition on a different path; this does
not affect whether the *copy itself* survived (the structural fingerprint), only the
K-value attribution. Class (b)'s "noise" tier (incoming-arg copies) is conservatively
demoted, not deleted — a handful of genuine Door-A arg-snapshots live there
(e.g. `mnDiagram_GetNextNameIndex`, where the "arg" is double-assigned; see A3). All
negatives below are scoped to *these filters over this matched corpus*, not to the
source space at large.

---

## 2. Construct catalogue (Phase 2) — three distinct shapes

All three were attributed to exact C source lines and traced through the MWCC IR via
`melee-agent debug dump local` on the **unmodified** repo files (read-only: the tool
compiles the file on disk, no edits, no new TU). Dump: `/tmp/mndiagram_pcdump.txt`.

There are **two distinct IR sub-mechanisms** by which a same-value copy survives:

- **(I) Copy created at REGISTER COLORING** — two equal-constant locals where one is
  live at the other's def point; the allocator emits `mr` instead of a redundant `li`.
  *(Construct A1.)*
- **(II) Copy present in IR FROM THE START, survives coalescing via live-range
  interference** — a runtime value assigned to a second local that is simultaneously
  live; because the two virtuals **interfere**, the conservative coalescer cannot merge
  them and the `mr` survives. *(Constructs A2, A3.)*

Mechanism (II) is the direct refutation of the scroll_offset negative: scroll_offset's
two halves had **disjoint** live ranges (no interference → folded); A2/A3's source and
dest are **both live after** the copy (interference → copy survives).

### Construct A1 — "two locals seeded from the same constant" (zero-rider)

**Shape:** `T a = K; U b; ... /* both used */` where two locals receive the same
compile-time constant and one is live where the other is initialized.

**Cleanest exemplar — `mnDiagram_GetNameTotalFalls` (matched, target TU):**
```c
static inline int mnDiagram_SumNameFalls(u8 field_index) {
    int total = 0;          // -> li rX,0
    int i;                  // for (i = 0; ...) i seeded 0
    for (i = 0; i < 0x78; i++) {
        if (GetNameText(i & 0xFF))
            total += GetPersistentNameData((u8) i)->vs_kos[field_index];
    }
    ...
}
```
**IR trace (`li r34,0`=total, `li r35,0`=i):**

| Pass | encoding |
|---|---|
| BEFORE GLOBAL OPTIMIZATION | `li r34,0` ; `li r35,0`  (two independent constant loads) |
| … through AFTER PEEPHOLE FORWARD | unchanged: two independent `li` |
| **AFTER REGISTER COLORING** | `li r30,0` ; **`mr r31,r30`** ← copy created here |
| AFTER PEEPHOLE OPTIMIZATION (final) | `li r30,0` ; **`addi r31,r30,0`** |

**Matched retail asm (byte-identical):** `8023EFF8 li r30,0x0` ; `8023EFFC addi r31,r30,0x0`.

So the allocator colored total→r30, i→r31, then **rematerialized i's zero as a copy of
total's register** rather than a second `li`. This is the *exact* InputProc +048
fingerprint, reproduced by the local debug DLL byte-for-byte. **11 instances in
`mndiagram.c` alone** (GetNameTotalFalls, GetFighterTotalFalls, GetRankedFighterForName×3,
GetLeastPlayedFighter×4, mnDiagram_8023FA6C×2).

### Construct A2 — "loop-counter snapshot" (`saved = i;` inside the loop)

**Shape:** survivor initialized to a constant, then conditionally reassigned to the live
loop counter inside the loop body: `int s = 0; for (i=...; i++) { ... s = i; ... }`.

**Cleanest exemplar — `mnDiagram_GetLeastPlayedFighter` (matched, target TU):**
```c
min_fighter = 0;                    // li rX,0
for (i = 1; i < 0x19; i++) {        // i in its own reg, incremented
    if (mn_IsFighterUnlocked(i) != 0) {
        if (...->play_time_by_fighter[min_fighter] > ...[i])
            min_fighter = i;        // <-- mr  (min_fighter = i)
    }
}
```
**IR trace (BEFORE GLOBAL OPTIMIZATION — copy is present from the START):**
```
B11:  li r34,0      ; min_fighter = 0
      li r35,1      ; i = 1
B20:  mr r34,r35    ; min_fighter = i     <-- genuine IR-level mr at earliest pass
B21:  addi r35,r35,1; i++
```
Final (after coloring r34→r30, r35→r25): **`mr r30,r25`**, matching retail
`8023F974 mr r30, r25`. r25 (i) keeps incrementing, r30 (min_fighter) holds the
captured index — **both live after the copy → they interfere → coalescer cannot merge
→ copy survives.** This is the cleanest analog to the runtime-value-copy targets.

### Construct A3 — "double-assignment chain" (`a = b = expr;`)

**Shape:** two locals receive the *same runtime value* via an assignment chain, and both
remain live (one is mutated, the other read later). This is the deep-dive's named
"two locals initialized from the same call result," generalized to any runtime RHS.

**Exemplar 1 — `mnDiagram_GetNextNameIndex` (matched, target TU):**
```c
u8 mnDiagram_GetNextNameIndex(s32 idx) {
    s32 original, i;
    original = i = idx;          // <-- chained copy from a runtime param
    do { i++; if (i >= 0x78) return original; }
    while (GetNameText(i & 0xFF) == NULL);
    return i;
}
```
**IR (BEFORE GLOBAL OPTIMIZATION — both copies present from start):**
```
B1:  mr r32,r3       ; idx -> r32
B2:  mr r33,r32      ; i = idx
     mr r34,r33      ; original = i      <-- genuine chained mr
B3:  addi r33,r33,1  ; i++   (r33 mutated)
B4:  rlwinm r3,r34   ; return original   (r34 read on early-exit)
```
Final: `8023F414 addi r30,r3,0x0` ; `8023F418 addi r31,r30,0x0` ; `8023F41C addi r30,r30,0x1`.
`original` (r31) and `i` (r30) both live → interference → `addi r31,r30,0` copy survives.
(`mnDiagram_GetPrevNameIndex` is the `--i` twin, identical shape.)

**Exemplar 2 — `__CARDFormatRegionAsync` (matched, `extern/.../CARDFormat.c`):**
```c
rand = time = OSGetTime();        // 64-bit OSTime, both halves chained
sramEx = __OSLockSramEx();
for (i = 0; i < 12; i++) { rand = (rand * 1103515245 + 12345) >> 16; ... }
*(OSTime *)&id->serial[12] = time;   // time read after the loop
```
Retail: `80356B28 addi r21,r4,0x0` ; `80356B2C addi r20,r3,0x0` ;
**`80356B30 addi r26,r21,0x0`** ; **`80356B34 addi r30,r20,0x0`** — the OSTime value is
copied into a SECOND pair of live callee-save regs (`time`) that survive `bl
__OSLockSramEx` and the loop, while `rand` (r20/r21) is mutated. This is the **same
instruction form as the `80242C0C +13c` target (`addi r26,r21,0`)** and proves A3
generalizes beyond the `idx` parameter case to any chained runtime RHS.

### Class-(b) corpus precedent for the pointer-copy target

The 210 callee-save pointer-copy survivors corroborate A3's runtime-value family. Clean
melee-src examples (loaded pointer copied into a callee-save to outlive calls/loops):
- `mnDiagram_GetNextNameIndex/GetPrevNameIndex` (A3, above).
- `grPura_80212EF4 @ 80212F18`: `lwz r3,0x2c(r3)` then `addi r31,r3,0x0` **and**
  `add r30,r3,r0` — one loaded pointer feeds two survivors (r30, r31) across a loop.
- `grOnett_801E41C8 @ 801E42A0`, `grCastle_801CD8A8 @ 801CD8E8`: a gobj/data pointer in
  a callee-save copied into another callee-save across stage-init `bl` calls.

---

## 3. Probe verdicts (Phase 3)

The `debug dump local` tool requires the `.c` file to live **inside** the repo, so a
standalone `/tmp` probe was rejected (`is not inside the melee repo`). I therefore probed
**by dumping the unmodified matched source files already on disk** — fully read-only on
the repo (the tool compiles the file as-is; no edits, no new TU added to the build). The
three constructs already exist verbatim in matched code, so this is a stronger test than
a synthetic probe: it confirms the construct survives **in the real codegen context** and
**byte-matches retail**, not merely in isolation.

| Probe | Construct | IR evidence | Verdict |
|---|---|---|---|
| `mnDiagram_GetNameTotalFalls` (mndiagram.c) | A1 zero-rider | BEFORE-GLOBAL `li r34,0; li r35,0` → AFTER-COLORING `li r30,0; mr r31,r30` → FINAL `li r30,0; addi r31,r30,0` | **SURVIVES.** Copy created at register coloring; byte-matches retail `8023EFFC addi r31,r30,0`. |
| `mnDiagram_GetLeastPlayedFighter` (mndiagram.c) | A2 loop-snapshot | BEFORE-GLOBAL `mr r34,r35` (`min_fighter=i`) present from start; FINAL `mr r30,r25` | **SURVIVES.** Copy in IR from the start; both regs live → interference → un-coalesced; byte-matches retail `8023F974 mr r30,r25`. |
| `mnDiagram_GetNextNameIndex` (mndiagram.c) | A3 chain `a=b=expr` | BEFORE-GLOBAL `mr r33,r32; mr r34,r33` (`i=idx; original=i`) present from start; FINAL `addi r30,r3,0; addi r31,r30,0` | **SURVIVES.** Chained copy in IR from the start; both regs live → interference; byte-matches retail `8023F418 addi r31,r30,0`. |

All three probes are **TESTED** (not UNTESTED): the IR dump tool ran successfully and the
final-pass encoding matches the retail `.s` byte-for-byte.

---

## 4. DECISION

**Door A construct FOUND in the matched corpus.** Same-value copies that survive to the
allocator are real, common, and present in the target TU itself. Two mechanisms, three
shippable C shapes:

1. **A1 — zero-rider / "two locals share a constant":** `int total = 0; int i; for(i=0;
   ...)` style. The allocator rematerializes the second constant as `mr/addi rY,rX,0`
   when one local is live at the other's init. **Directly matches `mnDiagram_InputProc
   +048`** (`li rX,0` then a copy into a second live register). **Recommend testing at
   InputProc +048.** Lever: arrange the function so the zero that feeds +048's second
   register is the *same* `int x = 0;` (or loop seed) as an already-live zero local,
   rather than two independent zero literals — so the allocator copies instead of
   re-`li`ing. 11 in-TU precedents make this the highest-confidence shape.

2. **A3 — double-assignment chain / "two live locals from the same runtime value":**
   `a = b = expr;` (or `orig = i = idx;`, `rand = time = OSGetTime();`). Produces a
   genuine IR `mr` from the start that survives because both locals stay live (interfere).
   **Directly matches `mnDiagram_80242C0C +13c`** (`addi r26,r21,0`, a runtime jobj
   pointer snapshotted into a callee-save survivor) and the `__CARDFormatRegionAsync`
   precedent is the same `addi r26,r21,0` instruction form. **Recommend testing at
   80242C0C +13c**: model the value in r21 and r26 as `survivor = working = <jobj expr>;`
   (or `survivor = working;` immediately before working is mutated/reused), keeping both
   live across the downstream assert/loop so they interfere.

3. **A2 — loop-counter snapshot / `saved = i;`:** survivor initialized to a constant then
   reassigned to the live loop counter inside the loop. Genuine surviving `mr` from
   runtime counter to survivor. **Recommend testing at `mnDiagram2_HandleInput S2`** if
   S2's surviving copy sits at a loop where a running index is captured into a
   longer-lived variable.

**The unifying, actionable principle for the matching agents:** a same-value copy
survives MWCC iff the two virtuals **interfere** (are simultaneously live after the copy).
The C lever is therefore not "force a copy" but "make the two values **overlap in live
range**" — e.g. a chained assignment whose LHS is read later while the RHS is mutated
(A3), a loop counter captured into a survivor that outlives the loop (A2), or a constant
shared between a live local and a second local so the allocator copies rather than
re-loads (A1). This is exactly the structural escape the deep-dive predicted, now with
in-TU, byte-confirmed precedents.

### Implications for the Discord ask

The deep-dive's "no known C-source lever reaches it" was correctly scoped to
scroll_offset's **disjoint-live-range** pattern, where no interference exists and the two
halves are genuinely a single variable across a reassignment. That negative still stands
for *that* pattern. But the broader claim "MWCC can never be made to keep a same-value
copy from C source" is **refuted by this corpus**: when the C structure keeps both values
simultaneously live (interference), the copy survives. The Discord ask should be reframed
from "is there any C that defeats constant-inlining?" to the narrower, honest question:
"for a site whose two values have **disjoint** live ranges (one dead before the other is
born), is there a C shape that introduces interference *without* changing the emitted
work elsewhere?" — i.e. the residual is specifically the disjoint-live-range case, not
same-value copies in general.

---

## 5. Reproduction

- Scanner: `/tmp/doora_scan.py` → `/tmp/doora_hits.json` (run from worktree root).
- IR dumps: `melee-agent debug dump local src/melee/mn/mndiagram.c -o /tmp/mndiagram_pcdump.txt`
  (read-only compile of the on-disk file; cached to `build/mwcc_debug_cache/melee/mn/mndiagram.txt`).
- All retail asm quoted from `build/GALE01/asm/melee/mn/mndiagram.s` and the listed
  `extern/`/`src/` `.s` files.

No campaign source, no `src/melee/mn/*`, and no CAMPAIGN-STATE file was modified. The
only repo write is this report.
