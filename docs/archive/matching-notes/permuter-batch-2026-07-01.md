# Real-match-scored permuter batch from structurally-different seeds

Agent: permuter-batch-agent, worktree wall/permuter-batch.
Task: launch decomp-permuter runs seeded from GENUINELY different bodies
(fresh m2c re-decompile / ghidra second opinion / twin-transplant), not
hand-edits of the current nd=0 hand-refined source, on the headline walls:
mnDiagram_DrawCellValue (0x80241E78), mnDiagram2_CreateStatRow (0x8024469C),
mnVibration_Think (0x802487A8), and time-permitting mnDiagram_DrawGridValues
(0x8024227C) / mnDiagram3_PopulateRankings (0x80245BA4).

This axis was explicitly RECORDED AS UNTRIED in
`mndiagram_banked_coloring_ceilings.md` ("REAL-MATCH-scored permuter (correct
objective, won't be fooled by the hack — untried this session)").

## Baselines (this worktree, confirmed via tools/checkdiff.py)

| Function | Address | Baseline match% | Classification |
|---|---|---|---|
| mnDiagram_DrawCellValue | 0x80241E78 | 99.9% | normalized-structural-match (FPR f26<->f28 swap) |
| mnDiagram2_CreateStatRow | 0x8024469C | 97.9% | instruction-sequence |
| mnVibration_Think | 0x802487A8 | 97.0% | backend-ceiling |
| mnDiagram_DrawGridValues | 0x8024227C | 96.4% | normalized-structural-near-match |
| mnDiagram3_PopulateRankings | 0x80245BA4 | 95.8% | instruction-sequence |

## Environment notes / blockers hit

- decomp.me (local server auto-detect: nzxt-discord.local, 10.200.0.1,
  localhost:8000) was UNREACHABLE this session -> `melee-agent scratch create`
  (server-side m2c) does not work here. Worked around with the fully-local
  path from the first-pass-decomp skill: `python -m m2c.main --knr --pointer
  left --target ppc-mwcc-c --context build/ctx.c --function <fn>
  build/GALE01/asm/melee/mn/<tu>.s` (context via `python tools/m2ctx/m2ctx.py
  --quiet -p`). This is a genuine local m2c re-decompile, independent of any
  human-refined source, exactly the "abandon the nd=0 anchor" seed needed.
- `melee-agent extract get <fn> --create-scratch` is currently broken:
  `ModuleNotFoundError: No module named 'src.cli.extract.api_helpers'`. Did
  not file (direct-investigation session per ground rules); routed around it
  via the local m2c path above.
- `melee-agent ghidra decompile` hit `ghidra.framework.store.LockException`
  under concurrent use (single shared Ghidra project, 14 other agents active)
  -- serializing the calls (one at a time) succeeded for all 3 headline fns.
- Machine was under extreme shared load this session (`uptime` load average
  ~200, 14 parallel agents each running their own ninja/mwcc builds). Every
  `tools/checkdiff.py` call and every `melee-agent debug permute bootstrap`
  call queued behind repo-wide file locks (`checkdiff` build lock keyed by
  worktree path; a separate "permuter bootstrap source staging lock" shared
  across ALL worktrees since bootstrap temporarily stages the seed over the
  real TU path). Typical wait: 5-15 minutes per bootstrap/checkdiff call this
  session, vs the documented ~6500 iters/5min steady-state throughput once a
  permuter loop is actually running. Budgeted accordingly: fewer, longer
  unattended runs rather than tight iteration.
- m2c's raw output is NOT directly compilable against project headers (it
  emits `void*` params it then dereferences with `->field`, `bitwise f32`
  casts, `NULL` after preprocessing-collapse, raw `unkNN` offsets instead of
  named struct fields). Each seed required hand-mapping m2c's raw-offset
  accesses back onto the named struct fields (Diagram/Diagram2/MnVibrationData
  in src/melee/mn/types.h and mnvibration.c) to get a COMPILING seed, while
  deliberately preserving the seed's structural shape (inlined accessor
  bodies + goto-threaded loops instead of the hand-refined named-helper-call
  form). This is the expected cost of this axis; noted for any follow-up.
- decomp-permuter's `import.py` flattens/preprocesses the TU into `base.c`
  (macro-expanded, `NULL`->stripped, headers inlined) at BOOTSTRAP time. If
  the seed file is edited after bootstrap, the run permutes a STALE base
  unless re-bootstrapped (confirms prior memory note
  `permuter_verify_correctness_and_wall_classes.md`). Caught this on
  DrawCellValue (fixed a signature mismatch in the seed after bootstrap
  completed) and patched `base.c`/`base.o` directly rather than repeating the
  ~8min re-bootstrap wait a second time.
- Real-match scoring confirmed configured: `settings.toml` in each function's
  decomp-permuter dir has `objdump_command = "melee-agent debug target
  dtk-objdump"` (project's own dtk-based objdump, not decomp-permuter's
  default), and `compile.sh` was auto-patched by `melee-agent debug permute
  fix-compile` to invoke `build/tools/wibo build/compilers/GC/1.2.5n/mwcceppc.exe`
  (the SAME compiler invocation checkdiff/ninja use) rather than wine. This is
  the local-wibo real-compiler path, not a proxy/force-phys score. Candidates
  will additionally be triaged against the real tree with `melee-agent debug
  permute triage <perm_dir> -f <fn>` before any claim of improvement (per
  `permuter_verify_correctness_and_wall_classes.md`: permuter score optimizes
  byte-distance, not behavioral correctness -- NEVER apply blind).

## Twin-transplant (seed family c) -- N/A for all 3 headline functions

Checked every function in mndiagram.c / mndiagram2.c / mndiagram3.c /
mnvibration.c for a matched sibling with sufficiently analogous logic to
literally copy-and-adapt:

- **mnDiagram2_CreateStatRow**: no sibling row-drawer in mndiagram2.c.
  `mnDiagram2_UpdateHeader` (100% matched) shares the HSD_SisLib text-creation
  idiom but not the dynamic-table-index/row-loop shape -- not a valid twin.
- **mnDiagram3_PopulateRankings**: unique in mndiagram3.c; no other
  rank/sort-drawing function exists in that TU to transplant from.
- **mnVibration_Think**: `mnDiagram2_Think` / `mnDiagram3_Think` are the only
  same-shaped ("Think" GObj-proc callback) siblings project-wide, but their
  branch/exit shape and lack of the per-port linked-list-walk loop make them
  structurally unrelated -- not a valid twin.

Seed family (c) is explicitly SKIPPED for all 3 headline functions (no forced
substitute used) -- see individual sections below for what was substituted
(ghidra decompile as the second alternative-structure seed instead).

## Per-function seed results

### mnDiagram_DrawCellValue (0x80241E78) -- baseline 99.9%

Seed (a) fresh m2c re-decompile: `python -m m2c.main ... --function
mnDiagram_DrawCellValue build/GALE01/asm/melee/mn/mndiagram.s`. Genuinely
different structure from the hand-refined 99.9% source: m2c's (and,
independently, Ghidra's) output INLINES `HSD_JObjSetTranslateX/Y` and
`HSD_JObjAddAnimAll` into raw flag-check + `translate.x/y` store + a manual
`HSD_JObjSetMtxDirtySub` dirty-bit dance, and threads the digit loop with a
`goto loop_60` rather than a `for`. Confirms these accessor helpers really do
get inlined at `-O4` (consistent with the ~99.9% baseline already using this
shape implicitly via its own inlining, but the RAW inlined form differs
enough in temp/variable structure to be a genuinely different starting point
for the allocator).

Seed (b) ghidra decompile (`melee-agent ghidra decompile 0x80241E78 --raw`):
structurally the SAME inlining pattern as m2c (also raw
`*(uint*)(iVar4+0x14) & 0x2000000` flag checks), confirming this is the
"true" inlined shape rather than an m2c artifact. Not pursued as a separate
permuter seed since it's materially the same shape as (a); logged as
corroboration.

Seed (c) twin-transplant: N/A (see above).

**Bootstrapped seed (a) into decomp-permuter** (fixed m2c's `void* arg0`
used with `->field` derefs by mapping to the real `Diagram*` struct fields
from `src/melee/mn/types.h`; fixed the header-declared signature
`void mnDiagram_DrawCellValue(void* arg0, u8, u8, int)` mismatch; replaced
post-preprocessing-stripped `NULL` with `0`). Base score (byte-distance,
decomp-permuter's own objdump metric) = **6795** vs the near-0 residual the
hand-refined 99.9% source has -- confirms this seed lands FAR from the
target in byte-space, exactly the "escape the local optimum, accept
80-90%-equivalent starting score" mode requested. `-j 3`, started
~02:56 local. Best-so-far tracked in the running log
`/tmp/permbatch-seeds/permuter_run_DrawCellValue.log`.

### mnDiagram2_CreateStatRow (0x8024469C) -- baseline 97.9%

Seed (a) fresh m2c re-decompile. Notably different from hand-refined source
in TWO structural ways: (1) m2c resolves `mnDiagram2_803EEAD0` struct-field
accesses directly (`mnDiagram2_803EEAD0.label_pos`, `.icon_pos`, etc) whereas
the current 97.9% source deliberately keeps a raw `char* base` pointer-math
walk (per an explicit code comment: "rewriting these accesses through the
named struct fields changes MWCC's addressing-mode selection and regresses
the match (tested)") -- i.e. the m2c seed reintroduces exactly the addressing
form the human explicitly moved away from, making it a genuine alternative
addressing-mode family for the permuter to explore, not a strict regression
by construction. (2) m2c's predicate checks (`IsDistanceStat`/`IsTimeStat`/
etc, which the hand-refined source calls as named helper functions) come back
INLINED as raw `stat_type` range comparisons with `goto block_NN` threading
-- i.e. at `-O4` these one-line predicate helpers are inlined away entirely,
a genuinely different call-boundary shape than the current source's
named-call form.

Seed (c) twin-transplant: N/A (see above).

**Bootstrapped seed (a)** (mapped m2c's raw `unk28/unk2C/unk30/unk4C/unk74/
unk9C` offsets onto `Diagram2` struct fields `icon_parent/row0_ref/row1_ref/
row_labels[]/row_values[]/row_icons[]` from `types.h`; fixed `bitwise f32`
casts m2c emits for `Vec3` component reads down to plain `.x`/`.y`/`.z`).
Compiled clean on FIRST bootstrap attempt (base.o present immediately,
unlike DrawCellValue which needed a signature fix-up cycle). Base score =
**7825**. `-j 3`, started ~03:07 local.

### mnVibration_Think (0x802487A8) -- baseline 97.0%

Seed (a) fresh m2c re-decompile. Same per-port linked-list-walk loop shape
as current source (both use nested `do{}while` walks), but m2c represents
the `MnVibrationData` struct as a raw `void*` with `*(temp_r31 +
(var_r23+6))` byte-offset arithmetic instead of the named `data->x6[port_idx]`
array access, and represents the two nearly-identical inline list-walks
(port_child walk and disconnected/active_child walk -- previously flagged in
project memory as a "repeated inline zeroer asymmetric regalloc" pattern
candidate) with slightly different temp-variable numbering than the current
source's hand-unified form. This is a genuinely different register-pressure
starting point for exactly the class of wall (asymmetric inline-zeroer
regalloc) this function is banked under.

Seed (c) twin-transplant: N/A (see above; mnDiagram2_Think/mnDiagram3_Think
are not valid twins).

**Bootstrapped seed (a)** (mapped m2c's `gobj->user_data->unk68` /
`*(temp_r31+...)` raw derefs onto `MnVibrationData` fields `jobjs[23]`,
`x6[port_idx]`, `x0[port_idx+2]` from the struct in mnvibration.c; fixed
`mnVibration_804D6C28->unk2C` to `((MnVibrationData*)
mnVibration_804D6C28->user_data)->jobjs[...]`). Compiled clean on first
bootstrap attempt. Base score = **4690**. `-j 2` (kept lower given 3
concurrent permuter runs + heavy shared-host load), started ~03:12 local.

### mnDiagram_DrawGridValues / mnDiagram3_PopulateRankings -- time-permitting

Not reached this session within the time/host-load budget after getting the
3 headline seeds running and monitored; m2c-fresh seeds for both were
generated locally (`/tmp/permbatch-seeds/m2c_DrawGridValues.c`,
`m2c_PopulateRankings.c`) but not yet hand-fixed to compile or bootstrapped.
See "Follow-up" section.

## Live run status / results

(updated as the monitoring windows report in)
