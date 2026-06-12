# mndiagram3.c TU-Completion Campaign — State

**Worktree:** `/Users/mike/code/melee/.claude/worktrees/mndiagram3-campaign`
**Branch:** `claude/mndiagram3-campaign`
**Compiler:** MWCC GC/1.2.5n, `-O4,p -nodefaults -proc gekko -fp hardware -Cpp_exceptions off -enum int -fp_contract on -inline auto`
**Methodology:** `docs/mndiagram-inputproc-campaign.md` (precise difflib map, reloc-strip before counting, mechanism evidence, no source-impossibility claims).

## TU Goal

Complete all 9 functions in `src/melee/mn/mndiagram3.c` to 100%.

| Function | Size | Status | Notes |
|----------|------|--------|-------|
| mnDiagram3_80246D40 | 0xC4 | **100%** | matched (PROTECTED) |
| fn_80246E04 | 0x60 | **100%** | matched; uses `table=&mnDiagram3_803EEC10` (PROTECTED) |
| fn_80246E64 | 0xA8 | **100%** | matched (PROTECTED) |
| fn_80246F0C | 0x20 | **100%** | matched (PROTECTED) |
| mnDiagram3_80246F2C | 0xDC | **100%** | matched (PROTECTED) |
| **mnDiagram3_80247008** | 0x144 (324B) | **100%** | MATCHED (iteration 3, data linking f66cc758a) |
| **mnDiagram3_8024714C** | 0x378 (888B) | **90.23%** | OPEN — coloring-dominated (iter-4: decl-order axis exhausted). See Map 2 + Iteration 4. |
| mnDiagram3_80245BA4 | 0x618 (1560B) | **94.07%** | OPEN — iteration 7 (93.74→94.07, Δ2); assoc-order+conversion-node+frame-pad LANDED; S9 float wall = confirmed coloring ceiling (statement+decl axes exhausted). See Map 3 + Iteration 7 residual. |
| fn_802461BC | 0xB84 (2948B) | 98.42% | OPEN — big-body register endgame, do LAST |

Driver 1 mapped 80247008 + 8024714C (this iteration). NO builds beyond baseline diffs (3 checkdiff runs total: 1 build + reused diffs).

---

## MAP 1 — mnDiagram3_80247008 (97.22%)

**Baseline anchors:** match 97.22% | opcode 97.5% | line-edit 9 instrs / sim 88.9% | line Δ **0** | hunks 5.
Classification: instruction-sequence. checkdiff compact: "1 stack-slot, 6 data/symbol-reloc, 2 register-only".

### Per-site map (reloc-normalized, side-by-side)

| Site | Expected | Current | Mechanism |
|------|----------|---------|-----------|
| +004 | `lis r5, mnDiagram3_803EEC10@ha` | `lis r4, ...data.0@ha` | base-materialization: target builds `&mnDiagram3_803EEC10`; ours builds the fresh string-pool base `...data.0` |
| +00c/+018/+01c/+020 | `addi r30,r5,803EEC10@l` ... | `addi r30,r4,...data.0@l` | same base, different symbol + preamble ordering of the two address bases (`&803EEC10` vs `&804A0844`) |
| +0a8 | `addi r3,r30,156` | `addi r3,r30,0` | OSReport string `"Can't get user_data.\n"` addressed as `&803EEC10 + 0x9C` (target) vs `...data.0 + 0` (ours) |
| +0b4 | `addi r3,r30,180` | `addi r3,r30,24` | `__assert __FILE__` string `"mndiagram3.c"` at `&803EEC10 + 0xB4` (target) vs `...data.0 + 0x18` (ours) |
| +0b8 | `addi r5,r30,196` | `addi r5,r30,40` | `__assert #cond` string `"user_data"` at `&803EEC10 + 0xC4` (target) vs `...data.0 + 0x28` (ours) |

**ALL 9 differing instrs = ONE root cause** (the +004/+020 "register-only" lines are downstream of the same mechanism, NOT independent register coloring).

### Root-cause evidence (GROUND TRUTH, from object dumps)

- Source uses `HSD_ASSERTREPORT(0x3FC, user_data, "Can't get user_data.\n")` (line 383). Macro = `OSReport("Can't get user_data.\n"), __assert(__FILE__="mndiagram3.c", 0x3FC, #cond="user_data")`.
- **Reference object** `build/GALE01/obj/melee/mn/mndiagram3.o` `.data` = 0xD0 bytes and **DEFINES** the four named objects `mnDiagram3_803EEC10 / _803EEC1C / _803EEC28 / _803EEC4C`, with the **three assert strings appended into the tail of the StatTable** (`mnDiagram3_803EEC4C`): `"Can't get user_data.\n"` @ blob 0x9C, `"mndiagram3.c"` @ blob 0xB4, `"user_data"` @ blob 0xC4. Strings are addressed `&mnDiagram3_803EEC10 + {156,180,196}`.
- **Our build** `build/GALE01/src/melee/mn/mndiagram3.o` `.data` = only 0x32 bytes containing ONLY the three strings as anonymous `@330/@331/@332`, with all four named objects `*UND*` (declared `extern` in `mndiagram3.static.h`). The strings form their own pool `...data.0` with base 0.
- Because the named objects are extern in our TU, MWCC has nothing to coalesce the OSReport/`__assert` literals into, so it mints a fresh `.data` string pool and a fresh base register. The reference TU defined those objects, so the literals appended to the same section and were addressed off `mnDiagram3_803EEC10`.

### Ranked lever candidates (NOT built)

1. **(PRIMARY, near-certain) Define the four `.data` objects in this C TU**, with the OSReport/`__assert` strings modeled as the tail fields of the `mnDiagram3_StatTable` (`x50`/`x68`/`x78` char arrays, per the "Name hidden string/data offsets" doctrine). This makes the literals coalesce into the named .data section, base becomes `&mnDiagram3_803EEC10`, and the +004/+020 preamble + the 3 offset sites resolve simultaneously.
   - Evidence: the reference object's `.data` IS exactly this layout.
   - **CAVEAT / GOVERNANCE:** This is a TU-wide DATA-definition change, not a `.text` one-liner. The sibling `mndiagram2.c` is in the IDENTICAL state (its `mnDiagram2_803EEAD0`/`_803EEB60` are also extern/UND in the `src/` build, reference defines them) yet ships at 97.46% — so the project's current convention is to leave these data blobs extern and accept the residual. Per `upstream_no_premature_data_fixes`, defining a 0xD0-byte data blob purely to fix `.text` string-addressing may be rejected upstream. **Confirm the data-definition policy with the human before building.** If the policy permits, this is a clean, mechanically-certain close.
   - The `mnDiagram3_StatTable` struct in `static.h` (`indices[0x28]; char x50[0x18]; char x68[0x10]; char x78[0x1C]`) ALREADY reserves the right tail layout — strong evidence a prior session anticipated this fix. Note: the reference indices data actually runs to blob 0x9C (struct 0x60), so the `indices` count / `x50` start offset in the struct may need re-derivation from the reference bytes before defining the initializer.

2. (fallback, weaker) If data-definition is off-limits: this residual is a DATA-LAYOUT ceiling for the `.text` compile and 80247008 stays at 97.22 (same class as mndiagram2's accepted 97.46). Bank it and move on; do NOT chase the +004/+020 "register" sites as a coloring problem — they are not.

**Verdict:** 80247008 is NOT a quick register close. Its 9-instr residual is a single data-pooling mechanism gated on a TU-wide data-definition policy decision. Map is complete; build is policy-blocked, not technique-blocked.

---

## MAP 2 — mnDiagram3_8024714C (86.64%)

**Baseline anchors:** match 86.64% | opcode 72.7% | line-edit 120 instrs / sim 45.9% | line Δ **1** (expected 293, current 292 — **ours is 1 instruction SHORT**) | hunks 28.
Classification: signature-type-mismatch. `diagnostic_pad_stack=64`. checkdiff: "call shape differs; 11 stack-slot, 44 data/reloc, 38 register-only; callee-save swap r28<->r29".

Source: `src/melee/mn/mndiagram3.c:425-545`. `PAD_STACK(64)` present; `Vec3 sp48` local; calls `mnDiagram3_80247008`, GObj_Create, the three `HSD_JObjSetTranslate{X,Y,Z}_Fake` inlines (each wraps `HSD_ASSERT` + `jobj->translate.* = v` + dirty-flag), `HSD_JObjGetTranslation{X,Y,Z}` getter inlines, `lb_8000B1CC`, a `do{}while(i<10)` loop with `HSD_SisLib_803A5ACC` + index-table lookup + `HSD_SisLib_803A6368`.

### Structural-vs-rename split

The 72.7% opcode similarity (vs 97.5% for 80247008) means there is GENUINE STRUCTURE divergence here, not just coloring. Breakdown of the 28 hunks:

- **A. Callee-save permutation (most of +038..+1f4, ~30+ register-only lines):** target ↔ ours differ by a consistent callee-save relabel: target {r29=gobj/diagram, r27=data, r26=row1-jobj/popup, r28=temp}; ours {r27=gobj, r28=data, r31=popup-jobj, r29/r26 shuffled}. Plus float `f30`↔`f31` swap (target: f30=row_spacing/result, f31=GetTranslationY temp; ours inverts). The `callee-save swap r28<->r29` hint names this. **This is coloring-cascade NOISE downstream of (B)/(C); per doctrine "registers fall into place when structure is correct" — do not chase first.**

- **B. STRUCTURAL: jobj-pointer load vs assert-check interleaving (+0bc..+0e8, +200..+228).** For `row_spacing = HSD_JObjGetTranslationY(row1) - HSD_JObjGetTranslationY(row0)` and the second block's recompute:
  - Target order: load row1-ptr (`lwz r29,44(r29)`), assert(row1), load row0-ptr+`.y`, assert(row0), `fsubs`.
  - Ours: hoists BOTH `lwz ...,44(...)` ptr-loads together (`lwz r28,44(r27)` / `lwz r29,44(r28)` adjacent at +0bc/+0c4) before the asserts.
  - Mechanism: differs in how `data = gobj->user_data` / `d->jobjs[8|9]` reloads are CSE'd vs re-read per getter call. The source re-assigns `row0 = data->jobjs[8]` 4× (lines 464/469/472/477) and reloads `data = gobj->user_data` (448/463/488). The target appears to re-read `jobjs[]` at each getter site (materialization) while ours caches. Signature: this is the **re-read-field-at-call-site / inline-boundary** family (cf. `reread_field_materializes_arg_register`).

- **C. STRUCTURAL + Δ1: the loop limit/val comparison form (+2e0..+2f8).** For `val = stat_idx + type_idx; if (val >= (u8)limit) val -= (u8)limit; else val=(u8)val;`:
  - Target: `clrlwi r0,r0,24` (=(u8)limit) ; `add r4,r28,r4` (val=stat_idx+type_idx) ; `cmpw r4,r0` ; `blt` ; `subf r0,r0,r4` (val-limit).
  - Ours: `add r0,r30,r4` ; `clrlwi r4,r5,24` ; `cmpw r0,r4` (operands SWAPPED) ; `blt` ; `subf r0,r4,r0` (operands SWAPPED).
  - Mechanism: the **operand-flip (comparison form)** lever — `val >= (u8)limit` vs `(u8)limit <= val` / which side is `(u8)`-truncated. The `li r0,limit` vs `li r5,limit` register choice (target loads limit into r0, ours into r5) suggests the SOURCE should compute the limit into a variable/expression that lands in the val-comparison's first operand. This region is instruction-count-balanced (both ~7 insns), so it is NOT the Δ1 site, but the operand swap is a clean structural mismatch. Tractable C lever.
  - **Δ1 attribution:** ours is 1 instr SHORT overall. Most likely at the (B) assert-interleave region (+0bc: target `bl __assert` at +0d8, ours at +0dc — ours emits the `lwz ...,44` ptr-loads more compactly, dropping one instruction). Resolving (B) should restore the missing instruction. Confirm at build time.

- **D. STRUCTURAL: float scheduling around lb_8000B1CC / SisLib args (+254..+2c0, +244..+254).** Target schedules `fsubs f30,f0,f30` (the `row_spacing` subtract) and `fneg f29,f30` (`neg_spacing=-row_spacing`) BEFORE the `lb_8000B1CC` call (+254/+260); ours defers `fsubs` to after (+25c) and uses `fneg f29,f0`. The `(f32)i` int→float magic-number conversion (`xoris r,r26,32768` + `lfd f,804DC000` + `fsubs`/`fmadds`) is present in BOTH (CONVERSION-SELECTION law fires identically on signed `(f32)i` — NOT a lever). The divergence is the **placement of `neg_spacing = -row_spacing` and the `row_spacing` subtract relative to lb_8000B1CC** — i.e. statement ordering of lines 493-498 (`row_spacing = ...; lb_8000B1CC(...); neg_spacing = -row_spacing;`). Per InputProc doctrine, loop-shape float-scheduling is often coloring noise, but the `fsubs`/`fneg` POSITION here is statement-order-controlled (B-class lever, lower confidence).

- **E. Frame size (PAD_STACK over-reservation):** target frame = 152B (`stwu r1,-152`); ours = 200B (`-200`). `sp48` at r1+72 (target) vs r1+128 (ours). **Ours OVER-reserves by 48B** — PAD_STACK(64) is 48B too large. The natural frame is 152B. Per doctrine, replace PAD_STACK with the real locals (the int→float conversion needs an 8-byte aligned `f64`/double scratch slot on the stack at r1+72ish region; `sp48` Vec3 + the conversion-magic stack temp). Resolving B/C/D may shrink the frame naturally; if not, model the conversion scratch as a real local rather than PAD_STACK.

### Ranked lever candidates (NOT built)

1. **(C) Loop comparison-operand form** (`val >= (u8)limit` → flip which operand is `(u8)`-truncated / introduce a `u8 limit` variable so it lands in the cmpw first operand). Likely fixes the **Δ1** AND the +2e0..+2f8 hunk. Highest-confidence STRUCTURAL lever. Evidence: operand-flip lever (InputProc §3, iter-45 precedent) + the `li r0` vs `li r5` limit-register tell.
2. **(B) jobj re-read vs cache at GetTranslation call sites** — re-read `data->jobjs[8|9]` / `gobj->user_data` directly at each getter rather than caching in `row0`/`d` locals, to match the +0bc/+200 load-vs-assert interleaving. Medium-high confidence (re-read-materialization family). Try removing the repeated `row0 = data->jobjs[8]` caching and inlining `data->jobjs[8]` at each `HSD_JObjGetTranslation*` arg.
3. **(D) Statement-order of `neg_spacing = -row_spacing` / row_spacing subtract vs lb_8000B1CC** (lines 493-498) — move the subtract/neg before/after the lb_8000B1CC to match +254/+260 scheduling. Medium confidence (statement-order lever; may be coloring noise).
4. **(E) Replace PAD_STACK(64) with natural 152B frame** — likely a real `f64`/double conversion scratch local. Do AFTER B/C/D (frame may settle on its own).
5. **(A) callee-save / float-reg permutation** — do NOT chase directly; re-measure after B/C/D land. Pure coloring cascade.

**Ordering for the FIX session:** C (Δ1 + comparison hunk) → B (load interleave) → D (float schedule) → re-measure A → E (frame). Sibling archaeology is cheap and high-yield: fn_80246E64 / 80246F2C (matched, same file) and mnDiagram2_HandleInput (sibling TU, 97.46) for the GetTranslation/user_data idioms.

---

## TU-Completion Ordering Recommendation

After this dual map, recommended order for the remaining four:

1. **mnDiagram3_8024714C FIRST** (main target, 86.64%). Despite being lower %, its residual has THREE tractable structural levers (C/B/D) with a clear Δ1 root candidate (C). Highest expected yield-per-effort; structural wins here will also de-risk the shared idioms (GetTranslation inlines, user_data reload, conversion path) that recur in 80245BA4 and fn_802461BC.
2. **mnDiagram3_80245BA4** (90.56%, 1560B) NEXT — not yet mapped; shares the SisLib/lb_8000B1CC/PosTable idioms with 8024714C (lines 26-254 use the same `&mnDiagram3_803EEC28` PosTable + jobj getters), so 8024714C's levers likely transfer. Map it after 8024714C closes.
3. **mnDiagram3_80247008** (97.22%) — **policy-gated, not technique-gated.** Map is complete and the fix is mechanically certain (define the .data blob in C). Hold until the human rules on the data-definition policy (the sibling-TU precedent says the project currently leaves these extern). If policy permits, it is a fast close; otherwise bank it alongside mndiagram2's accepted 97.46.
4. **fn_802461BC** (98.42%, 2948B) LAST — big-body register endgame as planned.

---

## Doc Feedback (for docs/mndiagram-inputproc-campaign.md)

- The campaign doc's signature catalogue did not include a **DATA-DEFINITION / string-pooling** signature, which is the ENTIRE mechanism for 80247008 (and a latent factor in any mn-menu TU using `HSD_ASSERTREPORT`). Proposed addition: *"extern-vs-defined data objects control string-literal pooling: when a TU's named .data objects are extern, OSReport/`__assert` literals form a fresh `...data.N` pool with their own base register; when defined in-TU, the literals coalesce into the named section and address off the first .data symbol. Diagnose by dumping `.data` of `build/GALE01/{obj,src}/.../<tu>.o` — UND named objects + anonymous `@NNN` string blobs = this signature."*
- The reloc-strip-before-counting doctrine worked perfectly: 80247008's "6 data/symbol reloc" + "2 register-only" lines collapsed to ONE mechanism once the data-pooling root was found. Confirms the doctrine; the "register-only after normalization" label can still be downstream of a non-register root (the +004/+020 base-materialization). Suggest noting: *"register-only-after-normalization is necessary-not-sufficient for a coloring cause; verify the base symbol is the same before treating it as coloring."*

---

## Iteration 2 (driver 1) — 8024714C fix ladder C→B→D→A→E

**Result: 86.64 → 89.7** | opcode 72.7 → 92.3 | line-edit 120 → 73 | Δ1 → 0 | stack-slot reasons 11 → 3. Commit stack (all gate-passed individually, 11/11 protected checks):
- `8e04f3bc5` C: `stat_idx = (u8) scroll` (int scroll) restored the Δ1 clrlwi; `limit = (u8) limit` self-truncation (int limit) + bare uses → join window BYTE-ALIGNED (li r0×2/clrlwi r0,r0/add/cmpw r4,r0/blt/subf r0,r0,r4). 86.64→87.6.
- `936de6bd1` B: row1 re-read through the field (`d->jobjs[9]` inside the GetTranslationY arg) at BOTH sites; row0 stays cached (target's lbz-scroll between row0's lwz and cmplwi pins row0 as a statement local). +0dc/+224 row1 loads now byte-positioned; ours even reproduces the gobj self-overwrite `lwz rX,44(rX)`. 87.6→89.7.
- `4c80ceea8` D (half): `neg_spacing = -row_spacing` hoisted above lb_8000B1CC → fsubs at target's pre-call +254 (the sink was single-use forward-prop dragging the subtract into the post-call fneg). Residual: target sinks ONLY the fneg past the bl (subtract result crosses in callee-save f30; its row1.y operand is volatile f0). opcode 89.6→92.3.
- comma probe (REVERTED): `-(0, row_spacing)` with neg post-call produced the EXACT target window (fsubs pre-call/callee-save result, fneg post-call) but minted +2 instructions globally (Δ0→2, alignment collapse) — prop-opacity achieves the shape at a cost; the zero-cost form = MODEL GAP, cause unattributed.
- `0153dd3b7` E: PAD_STACK(64)→PAD_STACK(16) → frame BYTE-EXACT 152 (stwu/stfd×3/stmw all match), conv scratch 96/100(r1) byte-match. Residual: sp48 at 80(r1) vs 72 — 8B pad-placement transposition inside the correct frame (ours: pad16 wholly below sp48; target: ~8B below + ~8B above). PAD_STACK(8) ships in matched mnDiagram3_80246F2C (file precedent).

**A re-measure verdict:** residual now DOMINATED by the cascade — 46 of 73 diff lines register-only (54 opcode-aligned reg-differs), one coherent callee-save relabel family {r26↔r27↔r28↔r29} + {f30↔f31}; plus 3 sp48 stack lines + the 1 fneg/bl transposition + ~8 reloc lines downstream of it. No register chasing done (per doctrine + budget). checkdiff's own guidance names the next levers: decl-order / loop-counter-reuse / discard-liveness nudges.

**Banked residuals for the next driver (8024714C @ 89.7):**
1. fneg/bl transposition: mechanism KNOWN (prop must skip the subtract while the scheduler sinks only the fneg); the comma spelling reproduces it but costs +2 instrs elsewhere — find the zero-cost spelling (may interact with the decl-order lever: with f30/f31 swapped, RA may flip row1.y to volatile f0 and force the target emission naturally).
2. sp48@80 vs 72: try splitting the pad around sp48 (8B local declared before sp48 + PAD_STACK(8) after) or decl-order moves; pure byte accounting, graph-inert.
3. Callee-save relabel: decl-order permutation (sp48/data/gobj/row0/archive/row_spacing/neg_spacing/i) — the InputProc band model applies (locals number in REVERSE decl order).

---

## Iteration 3 (driver 1) — 80247008 data linking, EXEMPLAR-FIRST (user ruling)

### THE EXEMPLAR PATTERN (review contract — extracted BEFORE applying)

Exemplars (fully-linked TUs, `metadata.complete` in report.json, .data fuzzy 100): **ftparts** (named .data objects THEN assert strings — mndiagram3's exact shape), **mngallery** (same mn module, same `"Can't get user_data.\n"` ASSERTREPORT string, all-string .data), **eflib** (named object BETWEEN string pools — proves emission-order rule).

1. **Named .data objects** = plain (non-static, non-const) initialized file-scope definitions in the .c, in ADDRESS ORDER, placed so source position matches retail emission order (ftparts.c:30-32; eflib.c:1042 carries the in-tree comment "// must be placed here for data ordering reasons..."). Objects preceding all strings go at top-of-file after includes.
2. **Assert/OSReport strings** = BARE literals at the macro call sites. NEVER struct-wrapped, NEVER named externs, NEVER base+offset math. The compiler emits them into .data after the named definitions; MWCC addresses both off the section anchor naturally.
3. **symbols.txt**: named objects `scope:global` with TRUE sizes (no string-swallowing); each string = the compiler's local id: `@NNN = .data:0xADDR; // type:object size:0xS scope:local data:string` (ftparts @225/@230/@404; @ numbers are per-TU local symbol ids from the actual build — read them from the compiled object).
4. **Header**: externs stay in the TU header (mndiagram3.static.h), like ftparts' globals.
5. **Struct shapes model only the real object.** EXEMPLAR-WINS conflict resolution: the prior session's StatTable tail char arrays (x50/x68/x78, string-swallowing) are NON-canonical — drop them; `mnDiagram3_803EEC4C` true size = 0x60 (48 u16 indices; reference bytes end at +0x60, strings start there).

### Reference data (byte-verified from build/GALE01/obj/melee/mn/mndiagram3.o .data dump)
- `mnDiagram3_803EEC10` AnimLoopSettings `{ 10.0F, 19.0F, -0.1F }` (41200000 41980000 BDCCCCCD)
- `mnDiagram3_803EEC1C` AnimLoopSettings `{ 0.0F, 199.0F, 0.0F }` (00000000 43470000 00000000)
- `mnDiagram3_803EEC28` PosTable `{ {3.3F,.5F,0}, {-2.0F,.57F,0}, {8.0F,.57F,0} }` (40533333/3F000000/0, C0000000/3F11EB85/0, 41000000/3F11EB85/0 — all 10 encodings python-struct-verified)
- `mnDiagram3_803EEC4C` u16[48]: 62..79, 7A 7A 7A 7C 7C 7C 7C 7C, 7A 7A 7A FFFF 7C 7B 7E 7E, 7E 7E 7D 7D 7D 7B 7B 7B
- Strings (4-aligned tail): 0x803EECAC "Can't get user_data.\n" (0x16), 0x803EECC4 "mndiagram3.c" (0xD), 0x803EECD4 "user_data" (0xA)
- BEFORE state: .data fuzzy 38.76 (208B), matched_data 16/272, function 97.22

### Iteration-3 RESULT (data linking APPLIED)

- **mnDiagram3_80247008: 97.22 → 100.00** (instruction-identical; checkdiff + report.json agree)
- **TU .data section: 38.76 → 100.0** (byte-identical 208B; our object now byte-matches the retail dump including string placement at 0x9C/0xB4/0xC4)
- matched_data 16 → 224 of 272 (residual = .sdata2 40B @ 71.875 + .sbss, out of scope)
- All protected functions HOLD (5×100, 8024714C 89.7, 80245BA4 90.53, fn_802461BC 98.42); build exit 0
- Commit: `f66cc758a` (src + static.h + symbols.txt, upstream-visible wording)
- @330/@331/@332 local ids did NOT shift when the definitions were added (predicted risk, did not materialize)
- Housekeeping: `#define __FILE__ "jobj.h"` block (now lines ~411/439) is PRE-EXISTING (campaign tip has it) and LOAD-BEARING (produces the matching .sdata "jobj.h"/"jobj" assert strings); no builtin-macro warning in the build log. Left as is.

## THE DATA-LINKING RECIPE (generalizable; first instance = f66cc758a)

1. **SURVEY**: `report.json` → units with `metadata.complete` (fully linked); filter to ones using the same macro family (HSD_ASSERT/ASSERTREPORT/OSReport) and a `.data` section. Read 2-3: how objects are defined, where strings sit, symbols.txt entry style. (Exemplars here: ftparts = named-objects-then-strings; mngallery = all-strings; eflib = emission-order comment.)
2. **PATTERN** (write it down first — review contract): plain initialized globals in the .c at the position matching retail emission order; bare string literals at macro sites; symbols.txt true sizes + `@NNN scope:local data:string` entries; externs stay in the TU header; structs model only the real object.
3. **APPLY**: byte-derive initializers from the reference object dump (`build/GALE01/obj/.../<tu>.o`, python-struct-verify every float); define; fix struct shapes; build; objdump our `.o` to confirm byte-identity + read the ACTUAL local @ ids; THEN write symbols.txt; configure+ninja (symbols.txt feeds the expected-side split).
4. **SECTION-GATE**: report.json before/after — the unit's `.data` fuzzy + matched_data must improve; every sibling function must hold; protected set hard-stop.

**Transfer targets**: mndiagram2.c is in the IDENTICAL extern state (mnDiagram2_803EEAD0/_803EEB60 UND, reference defines them, @-strings after — same shape); its strings: 0x60-blob + "Can't get user_data.\n" family. Apply the same recipe when that TU's campaign opens.

---

## Iteration 4 (driver 2) — 8024714C relabel endgame: decl-order toolkit exhausted

**Result: 89.7 → 90.23** | opcode 92.3 (unchanged) | line-edit 73 → 55 | register-only diff lines 46 → 27 | hunks 36 → 28 | Δ0 | frame byte-exact 152. Commit stack (both gate-passed individually, 11/11 protected checks; .data/.sdata hold 100):
- `2e9c415e8` popup-block (l465) decl swap `popup` ↔ `popup_jobj` (declare `popup_jobj` first): 89.72→90.10 (+0.38). Fixed the region-1 `popup_jobj` relabel (was the 17-vote r26→r31 spread; now byte-matches r26). Found by `debug mutate decl-orders --scope ...l465c4 --strategy all`.
- `c4b2b04d4` function-top `int i` promoted to position 0: 90.10→90.23 (+0.14). Composes with the popup swap; cut region-1 callee-save family lines. (`demote data` reaches the same 90.23 — same canonical order.)

### THE ONE QUESTION — ANSWERED (oracle: exhaustive decl-order across ALL scopes)

**The relabel endgame does NOT fully land via the band/decl-order toolkit, and the f30/f31 swap does NOT fix the fneg/bl transposition for free.** Decisive evidence — `debug mutate decl-orders --strategy all` run on EVERY decl scope, both substrates:
- function-top (8 locals): only `promote i`/`demote data` = +0.14%. **`swap row_spacing <-> neg_spacing` = WORSE (-0.05%) on both substrates** — the float relabel is NOT decl-reachable and the one move touching float decl order REGRESSES.
- popup-block l465 (2 locals): `swap` = +0.38% (committed).
- loop-block l495 (4 locals, `d/scroll/stat_idx/base`): fully INERT.
- l517 (`fi/text`): dependency-blocked (text depends on fi). l524 (`val/type_idx/limit`, 3 locals): INERT.

**fneg/bl transposition mechanism (CONFIRMED by inspection, +254 window):** target `fsubs f30,f0,f30` (row_spacing → CALLEE-SAVE f30, survives the lb_8000B1CC call) then `bl` then `fneg f29,f30` POST-call. Ours `fsubs f0,f0,f31` (row_spacing region-2 value → VOLATILE f0, dead after the immediately-following fneg) so `fneg f29,f0` must precede the call. The transposition is DIRECTLY coupled to row_spacing's region-2 value coloring to f30 vs f0. The f30↔f31 swap WOULD close it — but it is unreachable by decl order (regresses), so the "free fix" hypothesis is **REFUTED for the decl-order/per-region-local toolkit.** The comma form `-(0,row_spacing)` (iter-2 banked) reproduces the EXACT target window but costs +2 instructions — the target shape exists, the zero-cost spelling does not within this toolkit.

### Residual @ 90.23 (27 register-only lines + the float cluster)

All structural levers (Δ1, comparison-form, load-interleave, frame, popup-decl, counter-band) are now LANDED. Remaining residual is coloring-dominated:
1. **Region-1 GPR family (+038..+1f4):** gobj↔r29/r27, archive↔r27/r29, data/row1 coloring. The popup_jobj spread is FIXED; what remains is the gobj/archive/data/row0/row1 callee-save permutation. Not decl-reachable (all scopes enumerated). Permuter-territory or deeper IG intervention.
2. **f30/f31 swap (+0e0/+104/+17c/+194/+1cc/+1e4/+228) + fneg/bl (+254..+260) + float-setup scheduling (+288..+2c4):** the float-coloring wall. row_spacing wants callee-save f30 throughout; ours inverts f30/f31 at the first GetTranslationY pair. NOT decl-reachable; comma-form = +2 cost. THE remaining high-line-count cluster.
3. **Region-2 GPR (+204/+208/+2e8/+2c4/+318):** scroll/row0/stat_idx coloring + the `d`-copy walker (target `mr r30,r31` keeps a row_labels walking-ptr in r30; ours in r28 — both walk, pure coloring).
4. **sp48@80 vs 72 (+258 + the +288/+294/+2a0/+2ac stack reads):** 8B frame-layout transposition inside the byte-exact 152 frame; iteration-2 banked as "pure byte accounting, graph-inert" + entangled with the float-setup scheduling in that cluster (necessary-not-sufficient there). NOT attempted (low EV, build budget).

**Verdict:** 8024714C is now a COLORING-DOMINATED endgame (27 register lines, no structural lever left in the decl-order axis). The next driver should NOT re-run decl-order (exhaustive, both substrates). Real levers left: (a) tuned remote permuter on the region-1/region-2 GPR families + the f30/f31 float wall; (b) deeper `debug inspect tiebreak`/`intervene` IG what-ifs to find a non-decl source nudge for row_spacing→f30. Both are higher-cost than this iteration's budget allowed.

---

## MAP 3 — mnDiagram3_80245BA4 (90.53%) — iteration 5 (driver 2), MAP ONLY (no builds)

**Baseline anchors:** match 90.53 | opcode 88.9 | line-edit 414 / sim -5.9 (cascade artifact, see below) | line Δ **1** (expected 463, current 464 — **ours 1 LONG**) | hunks 14. Classification `inline-boundary-toolchain-artifact` is a **FALSE FLAG**: the "reference calls <self+0xNNN> but current omits" heuristic misreads the bl-display under a 1-instr shift cascade — every call reloc pairs 1:1 in identical order on both sides (verified through the whole diff). The 122 "data/symbol reloc" lines are cascade-inflated offset shifts, NOT a section-anchor ceiling — **no BSS/anchor ceiling to subtract** (all reloc symbols pair exactly; .data linking from f66cc758a holds here).

Source: `src/melee/mn/mndiagram3.c:42-270`. 23 function-top locals + PAD_STACK(8). The 5-row stat-page builder: wrap-compare → row-spacing getters → 5-iteration loop {name-mode title/names | fighter-mode icons} → value-format chain (Time/Distance/Percentage/IconOnly/default) → icon_id tail.

### Δ1 — FULLY ATTRIBUTED (five contributors, net +1)

| Site | Ours | Target | Δ |
|------|------|--------|---|
| +0dc | `stw r0,140(r1)` — **spills max_percentage (9999999) to stack** | keeps it in r14 | +1 |
| +498 | `lwz r0,140(r1)` — reloads the spill before `cmplw` | `cmplw r3,r14` direct | +1 |
| +0e4/+0e8 | `addi r14,r19,36` + `addi r20,r19,48` — **hoists &PosTable.xC/.x18 into 2 callee-saves** (in-loop `addi r4,r14,0` copies ×3 match target's ×3 in-loop `addi r4,r24,36/48`) | derives per-call from kept base r24 | +2 |
| (absent) | folds +108 into `lhz r23,108(r15)` | `addi r20,r20,108` hoisted | −1 |
| +528 | `lhz` direct to callee-save r23, copies coalesced | `lhz r3` + `addis r0,r3,0` + `addi r17,r3,0` (the `int r17 = icon_id` copy persists) | −2 |

Root: ours hoists the two loop-invariant PosTable pointers → 2 extra callee-saves live → 9999999 spills. **One mechanism (materialization-placement) drives +4 of the 5 contributors and most of the r14-r27 relabel cascade.**

### Per-site map (reloc-stripped; S# = structural, downstream noise excluded)

| Site | Offsets | Expected | Current | Mechanism / 714C-catalogue verdict |
|------|---------|----------|---------|------------------------------------|
| **S1** | +044..+068 | `li r0,24/21; clrlwi r0,r0,24; add r3,r3,r4; cmpw r3,r0; subf r0,r0,r3` | `li r4,..; add r0,r0,r3; clrlwi r3,r4,24; cmpw r0,r3; subf r0,r3,r0` | **(u8) wrap-compare — 714C lever C FIRES.** Target truncates limit FIRST (self-trunc tell `clrlwi r0,r0`). Source line 76 has `u8 limit` w/o self-trunc; 714C's matched spelling = `int limit` + `limit = (u8) limit;`. Verbatim transfer. |
| **S2** | +06c..+094 | `lwz r14(jobjs[6]); assert; lwz r15(jobjs[7]); lfs f27,60(r14); assert` — interleaved | both `lwz` hoisted adjacent (+06c/+074) | **jobj re-read — 714C lever B FIRES.** Source line 96 caches `row1 = data->jobjs[7]`; re-read `data->jobjs[7]` inside the GetTranslationY arg (714C: row1 re-read, row0 stays cached). Count-neutral, 1-slot rotation. |
| **S3** | +0b4..+0fc | one base r24 kept; consts r14=9999999, r15=5999999, r21=99999999 + high-parts r18/r19/r22 kept for re-materialize-at-use; `add r20,r24,r0; addi r20,r20,108` | hoists &PosTable.xC/.x18 (r14/r20); spills 9999999; base r19 dies (overwritten by 99999999); no +108 addi | **Materialization-placement cluster (Δ1 root).** Candidate spellings: (a) inline `(Vec3*)(base+0x24)/(base+0x30)` at the 3 lb_8000B1CC call sites (dispform-L1 inline-base-cast), (b) comma-LICM-defeat `(0, ...)` (PROVEN in this module: 802427B4 a527c0227), (c) per-iteration local. |
| **S4** | +18c..+198 | `addi r4,r3,0` (GetNameText result → arg) | `mr r4,r3` | **copy-init mr signature FIRES** (law-list item). `char* name_str = GetNameText(entity)` (line 137) — needs the addi-form copy spelling (intermediate-copy with persisting web). 1-2 lines. |
| **S5** | +2ec vs +2f4 | rank==25 `beq +3f4` = **falls INTO the value-format chain** (whose IsIconOnly arm at +4bc `bne +5e0` then exits to loop tail) | rank==25 `beq +5e4` = jumps STRAIGHT to loop tail (`goto next`, line 172) | **Control-flow/branch-join divergence — NOT in 714C catalogue.** Behavior-equivalent (chain's IsIconOnly arm catches icon-only stats after 4 pure predicate calls) but codegen differs. Source fix: restructure lines 168-191 so rank==25 falls through to the chain (e.g. icon path guarded by `IsIconOnly && (GetAggRank(sp48), sp48[0] != 0x19)`, chain as the else). |
| **S6** | +0b4/+428 vs +0d0/+420 | `lis 92; addi -29313` = **5999999** (0x5B8D7F) | `lis 93; addi -29313` = **6065535** (0x5C8D7F) | **SOURCE CONSTANT BUG, byte-verified.** Line 109 `max_time = 0x5C8D7F;` must be `0x5B8D7F` (5999999 = 99min 59s 999ms). Semantic correctness fix + 2 sites. The other caps verify: 0x98967F=9999999 ✓, 0x5F5E0FF=99999999 ✓. |
| **S8** | +51c..+528 | `lhz r3,0(r20); addis r0,r3,0; cmplwi r0,65535; addi r17,r3,0` | `lhz r23,108(r15); cmplwi r23,65535` | **Intermediate-copy persistence**: source lines 235-236 (`u16 icon_id; int r17 = icon_id`) exist but coalesce in ours. Needs the persisting spelling; r17-analog used later at the 6368 call (+5d8 ✓ both). Δ−2 contributor. |
| **S9** | +0bc/+0d4/+144-158/+554-578 etc. | f30=row_spacing, f31=neg_spacing, f29=f64-magic, f27=divider (f28=icon_x ✓ matches) | f31=row_spacing, f30=neg_spacing, f27=magic, f29=divider | **Float family {f30↔f31}+{f27↔f29} — the 714C float wall EXTENDED.** 714C verdict: not decl-reachable. Free statement-order lever first: reorder lines 106-110 (max_*/divider/neg_spacing assignment order) to mirror target materialization (fsubs, lfd magic, lfs divider, fneg). Else bank as coloring. |
| **S11** | frame | **240**, locals perfectly packed 40..128 (16+16+16+20+12+8, ZERO pad → no hidden stack object; the 80243434 stack-object idiom does NOT apply) | **264** (Δ24): locals 60..152, 4B gap at 140 = the spill slot, + PAD_STACK(8) + 12B | **Frame/E family.** Expected to largely self-resolve after S3 (spill slot dies); then drop PAD_STACK(8) and re-measure. Do LAST. |
| S10 | spread | — | — | GPR relabel cascade r14-r27 (~50 lines), downstream of S3/S5/S8. Matched already: r28=value_text, r29=data, r30=i, r31=stat_type. Don't chase. |
| S12 | +554..+578 | fneg AFTER stw/lfs window ordering near 5ACC | fneg f2 earlier | 714C +288-window analog; downstream of S9 + frame. |

Catalogue items checked and **already correct** (no action): prototype-visibility double-mask (rlwinm. pairs +370-384 shape-match), inline-return (u8) caller-casts (`clrlwi r27,r3,24` after GetRankedName/Fighter ✓ both), lbz operand order in the wrap block, the two-6B98 + converge-at-icon_id control shape.

### Ranked levers for iteration 6 (the FIX session)

1. **S6 constant**: `0x5C8D7F → 0x5B8D7F` (line 109). Mechanically certain, semantic fix, zero risk. Do first, commit alone.
2. **S3 un-hoist PosTable ptrs** (spelling ladder: inline-base-cast → comma-LICM → per-iter local): frees 2 callee-saves → un-spills 9999999 → fixes Δ1 + 4 sites + releases the relabel cascade. Highest yield.
3. **S5 rank==25 restructure** (fall into chain): 1-instr site but unlocks the +2d4..+3f4 alignment.
4. **S1 limit spelling** (714C lever C verbatim: `int limit` + self-trunc).
5. **S2 row1 re-read** (714C lever B verbatim).
6. **S8/S4 copy spellings** (intermediate-copy persistence; after the big ones).
7. **S9 statement-order of lines 104-110**, then re-measure floats; **S11 frame last** (drop PAD_STACK(8) after S3).
8. After structure: one `decl-orders --strategy all` pass (23 locals ≈ 69 candidates) — per 714C iteration-4 precedent, run it on the POST-structural substrate only.

### Doc feedback (for docs/mndiagram-inputproc-campaign.md)

- **False-flag classification under Δ-shift cascades**: `inline-boundary-toolchain-artifact` + "reference calls <self+0xNNN> but current omits that call" fired on a pure 1-instr shift cascade with identical call sets. Suggested doctrine line: *"verify the call-reloc SETS pair 1:1 before believing an inline-boundary classification; under line-Δ≠0 the self+offset bl display inflates both the reloc count and the omitted-call heuristic."*
- **Constant-divergence check belongs in the opening map**: a `lis` high-part off by 1 (92 vs 93, same addi low) is a 2-line diff that is actually a SOURCE CONSTANT BUG (0x5C8D7F vs 0x5B8D7F). Cheap to byte-verify during mapping; high-value (correctness, not just match).
- The Δ-attribution-by-contributors table format (5 rows summing to +1) made the register-pressure root (hoisted pointers → spill) provable without a build; recommend it as the standard Δ≠0 procedure.

---

## Iteration 6 (driver 2) — 80245BA4 fix ladder, 90.53 → 93.74

**Result: 90.53 → 93.74** (+3.2) | Δ1 → Δ2 (through 3-short mid-ladder) | line-edit 414 → 158 / sim −5.9 → 59.5 | hunks 14 → 47 (preamble slot-ripple, rename-class). 6 builds, 6 commits, all 11/11 protected checks, .data 100 held throughout.

### Rung ledger (mechanism checks)

1. `f740f1f28` **S6 constant**: `max_time = 0x5B8D7F`. Match FLAT (both lis sites are also register-relabeled; the fix flips them only when the cascade settles — expected). Semantic correctness banked.
2. `aef384713` **S3 (Δ1 root)**: inline-base-cast `(Vec3*)(base+0x24/0x30)` at the three lb_8000B1CC sites. 90.53→92.30. **Mechanism FIRED in full**: r14/r20 hoists vanished, the 9999999 spill (stw/lwz) dissolved, all 3 call sites emit `addi r4,r24,36/48` byte-exact, base landed in r24 = target's register. **Cascade re-roll count: 6 callee-saves snapped register-exact (r14=9999999, r15=5999999, r21=99999999, r23=data-walker, r25=0x4330, r30=i) from 0 before.** Δ went 1-long → 3-short (the predicted −4). CAVEAT: checkdiff WARNED "false progress" on the opcode-similarity collapse (88.9→60.5) — that was the Δ-shift aligner artifact; the register-exact evidence overruled it. First spelling (inline-base-cast) won; comma/per-iter never needed.
3. `d76bfcaad` **S5 (rank==25 branch-join)**: restructured so rank==25 falls into the value chain (goto-form; icon path guarded by `!= 0x19`, exits via `goto icons`). Match FLAT at 92.30 (Δ3 artifact) but branch topology verified target-exact by inspection (+2e8 beq → chain join, same target as the icon check). Also: pre-commit hook blocked on the pre-existing `*(int*)(sp28+0xC)` my re-indent touched → `M2C_FIELD(sp28, int*, 0xC)` (build-neutral, verified).
4. `30c308c01` **S1+S2 (714C verbatim transfers)**: `int limit` + `limit = (u8) limit;` self-trunc AND row1 re-read through `data->jobjs[7]` in the getter arg (row1 local deleted). 92.30→93.93, hunks 13→9. **S2 window BYTE-IDENTICAL (r14/r15/f27 register-exact); S1 sequence exact (li/clrlwi/add/cmpw/subf) except the 2 lbz dest registers.** Both 714C levers transfer CLEAN.
5. `18479d89c` **table-restore + add-flip**: the orphaned `u16* table` decl restored as the +0x36-advanced pointer (`table = stat_table + 0x36`, `*table`) + `val = scroll + offset`. 93.93→93.74 (−0.2) BUT Δ 3→2 (the +108 instruction restored), line-edit 317→158 (sim 18.7→59.5 — function twice as aligned), `add r3,r3,r4` byte-match, lhz now `0(r20)` = target's exact base register/form. The −0.2 = preamble slot-ripple from a remaining association-order diff. Committed per structure-over-match doctrine + the checkdiff NOTE.

### Residual @ 93.74 (banked, ranked for next driver)

1. **Address-association order (3 lines)**: ours `slwi r3; addi r20,r3,108; add r20,r24,r20` = (idx2+108)+base; target `slwi r0; add r20,r24,r0; ... addi r20,r20,108` = (base+idx2)+108 SPLIT (the addi sits at +0f0 AFTER the const bank). stat_table went single-use → MWCC folded+reassociated. Candidate: a spelling where base+idx2 keeps its own web (second stat_table use, or self-increment `table = stat_table; table += 0x36;` two-statement form — untested, build budget).
2. **S8 copies (the Δ2)**: target `lhz r3` volatile + `addis r0,r3,0` + `addi r17,r3,0`; ours lhz straight to callee-save (coalesced). Per the fold law (copies of provably-equal values FOLD), the present spelling cannot persist — needs a conversion-node spelling (type experiments: `int icon_id`, `u32 check = icon_id`, compare-on-copy variants). NOT attempted per the law-conditions gate.
3. **2 lbz dest swap** (S1 residual): saved_selection→r4 / scroll_offset→r3 in target, inverted in ours. Register-only; the add now matches.
4. **S9 float family {f30↔f31}+{f27↔f29}**: untouched. The free statement-order lever (reorder lines 104-110 to mirror target's materialization: fsubs / lfd magic / lfs divider / fneg) is UNTRIED — first move next iteration.
5. **S4 copy-init mr** (+18c, 1-2 lines): `addi r4,r3,0` vs `mr r4,r3` for the GetNameText result. Untried.
6. **S11 frame 264 vs 240** + PAD_STACK(8): untouched per DO-NOT (re-derive after structure settles — the spill slot is already gone, so the 24B gap shape has changed; re-measure first).
7. **GPR relabel residual**: r16/r18/r19/r20-class high-part/walker permutation — downstream; plus the exhaustive `decl-orders --strategy all` pass (23 function-top locals + block scopes) NOT YET RUN — the 714C protocol says run it once on the settled substrate.

**Next-driver opening move**: S9 statement-order + the decl-orders pass (both cheap), then the association-order spelling, then S8 type experiments. The function is no longer Δ-blocked or pressure-blocked; it is in last-mile territory (assoc-order + copies + floats + frame).

---

## Iteration 7 (driver 3) — 80245BA4 ladder, 93.74 → 94.07

**Result: 93.74 → 94.07** (+0.33) | Δ2 (held) | real register-only diffs 45 → ~5 (rest = Δ2-shift reloc cascade, false-flag) | 3 commits, all 11/11 protected checks, .data/.sdata 100 held. The S9 float wall is now the SINGLE dominant residual (confirmed coloring ceiling, both decl-order and statement-order exhausted).

### Rung ledger (mechanism checks)

1. **Rung 1 (S9 float statement-order): NEGATIVE — BYTE-INERT.** Reordering the float-assignment block (lines 102-110: row_spacing/divider/neg_spacing/max_* in every contiguous permutation) produced a BYTE-IDENTICAL diff (match flat 93.74). MWCC reorders independent stores freely; the {f30↔f31}+{f27↔f29} swap is a coloring decision, NOT statement-reachable. The S9 hint's "fsubs/lfd-magic/lfs-divider/fneg" target order is unreachable because the f64-magic constant has NO source statement (conjured by `(f32)i`) — its preamble materialization order vs `divider` (line 105) is IRO-scheduled by loop-body first-occurrence (divider used line 119 before magic line 137), not source-reachable. **Confirms the 714C iter-4 verdict carries to this substrate.**
2. `5b1f4260e` **Rung 2 (address-association) + Rung 3 (S8 conversion-node), COMMITTED TOGETHER**: 93.74→94.07.
   - **Rung 2 (+0.22, the named state-file lever):** two-statement table form — DELETE the `u16* stat_table` intermediate, write `table = (u16*)(base + ((int)stat_type << 1)); table += 0x36;`. Forces the `base+idx` add to bind FIRST: `slwi r0,r31,1` (was `slwi r3`) + `add r16,r24,r0` (base+idx) now byte-match target's `slwi r0`/`add r20,r24,r0`. **CAVEAT — the +108 OVER-FOLDS**: with `table` loop-invariant single-use, MWCC folds `+0x36` into the lhz displacement → `lhz 108(r16)`, DROPPING target's standalone `addi r20,r20,108`+`lhz 0(r20)` (−1 instr, locally short). The self-increment two-statement form (the census candidate) AND the direct one-expression form BOTH over-fold identically — TESTED 3 spellings (`table=stat_table;table+=0x36`, direct, `(u16*)base+stat_type`). The committed-+108 form (baseline `stat_table+0x36`, +int-icon = 93.85) has association WRONG `(idx+108)+base` but lhz 0 committed. **The target wants BOTH base+idx-first AND +108-committed — NOT co-reachable: forcing base+idx-first (2 statements) lets the 2nd statement's +108 fold; one-expression reassociates to idx+108-first. This is a register-life wall (base+idx must color to a callee-save that gets +108 added IN PLACE — the 714C lhzu-class condition).** Picked the higher-scoring base+idx form (94.07 > 93.85). The over-fold is locally −1 instr but globally compensated by Rung 3's +1 copy → net Δ2.
   - **Rung 3 (+0.11, S8 conversion-node):** `int icon_id` (was `u16`) at the icons-block readback defeats the icon_id→r17 copy coalesce — adds `mr r18,r0` (the persistent-copy node) and RECOVERS the over-fold's dropped instruction (Δ3→Δ2). Does NOT fully reach target's `lhz r3,0; addis r0,r3,0; addi r17,r3,0` (load-volatile + two copies) because the icon_id LOAD is entangled with the table over-fold (`lhz r0,108(r16)`). `u32 check = icon_id` (census candidate) and `r17=icon_id` after the branch BOTH inert/worse (check coalesces; reorder −0.03). **S8 is gated on the +108 commit — same wall as Rung 2.**
3. `84d54e728` **Close-out frame: drop PAD_STACK(8)**, match FLAT 94.07. MWCC's NATURAL frame is 248B (no pad); target is 240B. The PAD_STACK(8) was pure over-reservation on top of the natural 248. Removing it: frame 256→248 (uniform local shift +16→+8 vs target). **The residual 8B is a low-frame compiler temp DOWNSTREAM of the float/over-fold codegen (the stack-object idiom does NOT apply — locals pack identically to target, just 8B higher base); it should drop to 240 when the float wall resolves. Removed non-shippable PAD_STACK; correct per doctrine.**

### Rung 4 (2 lbz dests) + Close-out decl-orders: BOTH NEGATIVE
- **2 lbz dests** (saved_selection→r4/scroll_offset→r3 target, inverted ours): operand swap `offset+scroll` → `add r3,r4,r3` form changes but dests STILL swapped + −0.02; decl swap `offset`-first → loads reorder but dests still wrong + load-order now wrong, −0.03. **Pure coloring tiebreak, not operand/decl reachable.**
- **`decl-orders --strategy all` (the 714C close-out protocol, on the settled substrate): NO ordering improves ≥0.05%** (all 22 adjacent swaps flat; `divider↔icon_x_offset` −0.03). **Exhausts the decl-order axis; the float wall is confirmed NOT decl-reachable here (matches 714C iter-4).** TOOL PAPERCUT (issue #572): `debug mutate decl-orders` throws AstWalkError on this fn — the `M2C_FIELD(sp28,int*,0xC)` macro's `int*` arg makes tree-sitter emit a decl-enclosing ERROR node. WORKAROUND (in #572): temporarily expand to `*(int*)((s8*)sp28+0xC)` (build-identical), run, restore.

### Residual @ 94.07 (banked, ranked for next driver)

1. **S9 float family {f30↔f31 row_spacing/neg_spacing}+{f27↔f29 divider/magic} — THE dominant residual (~14 sites).** CONFIRMED coloring ceiling: statement-order BYTE-INERT (rung 1), `decl-orders --strategy all` no-win (this iter), the float-pair decl swap −0.05 (714C iter-4, both substrates), comma-form = +2 cost (714C iter-2). row_spacing colors f31-not-f30 (ours) vs f30 (target); the FIRST-colored float gets f31 (fresh-descending pick). NOT source-reachable in the no-permuter axis. Real levers left: tuned remote permuter (campaign DO-NOT) or `debug inspect tiebreak`/`intervene` IG what-ifs for row_spacing→f30 (higher cost).
2. **Table +108 commit + S8 copies (ENTANGLED, the register-life wall):** target `add base,idx`+`addi +108`+`lhz 0(r20)` AND `lhz r3,0; addis r0; addi r17`. Co-reachability blocked (see Rung 2 caveat). Cracking the +108 commit (base+idx → callee-save with in-place +108) unblocks BOTH; candidate = comma-defeat on the `*table` address-mode fold (untried, +2-cost risk per 714C), or an IG intervene forcing base+idx to a callee-save.
3. **2 lbz dest swap** (S1 residual): coloring tiebreak, operand/decl-inert (this iter).
4. **Frame residual 8B** (248 vs 240): downstream of S9/over-fold; re-derive after the float wall.
5. **S4 copy-init mr** (+18c): `addi r4,r3,0` vs `mr r4,r3` for GetNameText result — UNTRIED (low EV, register-only).
6. **GPR relabel** (r16↔r20 icon-var, r18/r19/r20 high-parts): downstream of S9/over-fold.

**Verdict:** 80245BA4 is now a COLORING-DOMINATED endgame at 94.07 — the structural levers (assoc-order, conversion-node, frame-pad) are LANDED; the dominant residual (S9 float wall) is a confirmed coloring ceiling exhausted on BOTH the statement-order and decl-order axes by two drivers. Next real lever is permuter (campaign DO-NOT) or IG-intervene — both above this iteration's budget. The table-+108/S8 entanglement is a register-life wall; the comma-defeat spelling is the one untried structural candidate (with the 714C +2-cost caveat).

## Driver-3 Entries (fn_802461BC)

(Reserved — fn_802461BC at 98.42 is LAST per TU ordering. 8024714C register endgame queues on permuter channels.)
