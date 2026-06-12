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
| **mnDiagram3_8024714C** | 0x378 (888B) | **86.64%** | OPEN — main target. See Map 2. |
| mnDiagram3_80245BA4 | 0x618 (1560B) | 90.56% | OPEN — not yet mapped (driver task) |
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

## Driver-2 Entries

(Reserved — driver 2 to append 80245BA4 map and any fn_802461BC notes here.)
