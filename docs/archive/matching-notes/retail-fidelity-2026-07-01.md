# Retail-compiler fidelity cross-check: mwcc-debug vs mwcc-retro

Task: verify whether "proven exhausted" conclusions on `mnDiagram_DrawCellValue`,
`mnDiagram2_CreateStatRow`, and `mnVibration_Think` -- derived from `mwcc-debug`
(patched-DLL pcdump) -- actually reflect retail `mwcceppc.exe` GC/1.2.5n
behavior, by cross-checking with `mwcc-retro` (retrowin32+gdb against the
unmodified retail binary).

## Headline correction to the task's own framing (checked first)

The task description frames `mwcc-debug` as running "a DEBUG-BUILD DLL of the
compiler, not the actual retail mwcc_233_163n (GC/1.2.5n) compiler". This is
not accurate, and it matters for how much weight to put on the rest of this
investigation:

- `tools/mwcc_debug/README.md` and `tools/mwcc_debug.c` (header comment)
  describe `lmgr326b.dll` as a replacement license-manager stub DLL, not a
  recompiled/debug build of the compiler. `mwcceppc.exe` itself is untouched
  on disk.
- Verified directly in this worktree: `build/compilers/GC/1.2.5n/mwcceppc.exe`
  is the same 1,651,200-byte retail binary used for every normal `ninja`
  build in this repo (the one this project matches against). There is a
  `mwcceppc_old.exe` alongside it, but per
  `build/compilers/GC/1.2.5n/README.md` that is a pre-Ninji-scheduler-fix
  legacy copy kept for reference, unrelated to "debug" tooling, and is not
  what `ninja`/`mwcc-debug` invoke.
- What `lmgr326b.dll` actually does (`tools/mwcc_debug/mwcc_debug.c` lines
  1-12, `tools/mwcc_debug/README.md`): patches one byte in retail's own
  `copts.debuglisting` init (0x42C8E1) so the compiler's own already-
  compiled-in, normally-dormant IR-optimizer/backend logging fires, and
  installs jump hooks over PPC-backend listing stubs that call the retail
  binary's own intact `formatoperands` (0x4C4BF0). In plain `dump`/`pcdump`
  mode (no `MWCC_DEBUG_FORCE_*` env vars set) this does not change codegen --
  it only turns on logging of decisions the retail compiler was always
  making.
- The only documented retail-fidelity caveat in this DLL is explicit and
  narrow: the `force-phys` / `force-iter-first` / `force-coalesce` /
  `force-remat` / `force-interfere` / `force-schedule` / `force-no-cse`
  intervention features are explicitly commented (mwcc_debug.c ~line 1479)
  as producing "a DLL-patched artifact. NOT what real MWCC would emit from
  any C source. Use for hypothesis testing only." That caveat is about
  those specific override modes (used to test "is the target register
  assignment reachable at all"), not about observational pcdump in general.

So the correct framing is: `mwcc-debug` observation-mode pcdumps ARE retail
GC/1.2.5n compiler output (same binary, dormant logging turned on). The
genuine open question this session was asked to resolve is narrower than "is
mwcc-debug even the real compiler" (yes) -- it's "does anything about running
it under wibo/the DLL shim change codegen versus running the unmodified exe
under a completely different execution substrate (x86 emulation via
retrowin32+gdb)". `docs/superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md`
cites exactly one prior confirmed case of such a divergence project-wide:
`ftCo_Shouldered` (r27-vs-r30), outside this campaign's three functions. This
session re-tests it directly on Draw/CreateStatRow/Think.

## Tool scope limitation discovered (blocks axis (c) as originally specified)

`tools/mwcc_retro/README.md` and `.claude/skills/mwcc-retro/SKILL.md`, confirmed
again in `docs/mwcc-retro.md`:

> "Backend introspection on GC/1.2.5n is a follow-on (#542); for backend on
> 1.2.5n use the `mwcc-debug` DLL pcdump path."

`melee-agent debug retro dump --phases backend` only produces
register-allocator/PCode/stack-map dumps when `--compiler 1.1` is passed
(the older GC/1.1 compiler, not the one this project matches against).
On `--compiler 1.2.5n` (the default, and the only correct choice for this
project), `mwcc-retro` currently produces front-end IRO pass traces only --
no regalloc dispense order, no PCode backend passes, no stack maps, for the
actual retail 1.2.5n binary.

Consequence for the three assigned sub-questions:

- (a) Draw's CSE canonicalization order for the two fmuls -- answerable.
  This is a front-end IRO question (CSE is a front-end optimizer pass) and
  front-end tracing works against real 1.2.5n via the emulator.
- (b) CreateStatRow/GetStatValue u8-param assume-clean convention --
  partially answerable. Parameter binding/widening decisions are visible in
  the front-end IR: the front-end trace shows whether retail's IR-builder
  ever materializes a widen/mask node for `is_name_mode`/`stat_type` before
  the value reaches the callee, which is the causally relevant part of
  "assume-clean" (the backend consequence -- zero `clrlwi` at the call sites --
  is a mechanical readout of whatever the IR handed it).
- (c) mnVibration_Think's register-allocator dispensing order -- NOT
  answerable with retail 1.2.5n fidelity by this tool as it exists today.
  This is purely a backend/regalloc question, and 1.2.5n backend
  introspection is explicitly unimplemented (tracked as issue #542 in the
  tool's own docs). The only backend cross-check available compares against
  GC/1.1, a materially different compiler build from the one Melee matches
  against, so a GC/1.1 regalloc dispense order is not evidence about 1.2.5n's
  dispense order. I did not attempt a 1.1-vs-1.2.5n substitution and present
  it as if it answered (c); that would misrepresent what the tool can show.
  This axis remains open and is exactly the #542 follow-on's job once it
  lands -- flagging as a real gap rather than manufacturing an answer.

I still ran the `verify` parity gate and attempted front-end dumps for all
three functions to extract what fidelity signal the tool can give today (see
below), and to leave a clean path for whoever picks up #542.

## Fidelity gate (`melee-agent debug retro verify`)

```
PASS [parity] .o byte-parity (src/melee/mn/mnvibration.c)
```

The emulated retail compile of the control TU (`mnvibration.c`) produced a
byte-identical `.o` to the normal wibo/MWCC build. This is the tool's own
authoritative fidelity gate -- it passed, so front-end dumps can be trusted
as genuine retail 1.2.5n behavior (subject to the backend-scope limitation
above).

## Function identity corrections made during this investigation

- `mnDiagram_DrawCellValue` = `0x80241E78` (formerly named
  `mnDiagram_DrawCellNumber` before a rename pass) -- confirmed against
  `config/GALE01/symbols.txt:12748`. This is the correct target and matches
  the campaign's known Draw f26/f28 wall
  (`mndiagram_banked_coloring_ceilings.md`,
  `mndiagram_codex_loop_draw_sort_source_exhausted.md`).
- `mnVibration_Think` = `0x802487A8` (`config/GALE01/symbols.txt:12795`).
  This is a DIFFERENT function from `mnVibration_80248644`, which is
  `mnVibration_RefreshNameRows` (`symbols.txt:12793`) -- the function all of
  the existing `docs/mwcc-debug-mnvibration-*.md` handoff docs and
  `docs/mwcc-allocator-algorithm.md`'s worked dispense-order example describe.
  Those docs' "verified via colorgraph hook" scroll_offset/r36-vs-r27 material
  is about `RefreshNameRows`, not `Think`. I did not find a
  `mwcc-debug`-derived force-phys/coloring writeup specifically for
  `mnVibration_Think` in this worktree's docs; any campaign claim of a
  "proven exhausted" register-dispense conclusion for `Think` specifically
  needs a fresh citation, separate from the well-documented
  `RefreshNameRows` material -- they are not the same finding.

## Tooling mechanics noted in passing

- `melee-agent debug retro dump` serializes globally through a single
  `_port_lock()` (`tools/mwcc_retro/mwcc_retro_debugger.py`, hardcoded gdb
  port 9001, lock file under `$TMPDIR`) -- only one retrowin32+gdb session
  can run at a time per machine/session. Launching multiple `retro dump`
  invocations concurrently does not parallelize; they queue.
- Emulated retail compiles under this tool are "diagnosis-grade" slow per its
  own docs, and this session ran under extreme host contention (load average
  210+ on a 10-core machine, ~13 other parallel agents building/checkdiffing
  concurrently at the same time), so a single front-end dump took many
  minutes of wall clock.

## RESULT: (a) mnDiagram_DrawCellValue CSE canonicalization -- retail confirms front-end does NOT reorder; wall is backend-only

Ran `mwcc-retro` front-end IRO trace against the real retail GC/1.2.5n binary
(`build/compilers/GC/1.2.5n/mwcceppc.exe`, the same exe used for every normal
build) via retrowin32+gdb, for `src/melee/mn/mndiagram.c` /
`mnDiagram_DrawCellValue`. Extracted trace:
`build/mwcc_retro/src_melee_mn_mndiagram/mnDiagram_DrawCellValue/iro-trace-manual-extract.txt`
(99599 lines, 62 pass-dumps, source lines 2325-2392).

Target source (`src/melee/mn/mndiagram.c:2367-2369`):
```c
col_offset = y_spacing * (f32) col;
row_offset = y_offset * (f32) row;
row_offset_adj = row_offset - 0.4f;
```

Tracked the two `EMUL` (float multiply) IR nodes for `col_offset` and
`row_offset` through every one of the ~15 front-end optimizer passes
(BuildflowGraph -> ScalarizeClassDataMembers -> CopyAndConstantPropagation ->
LoopUnroller -> FindLoops -> CommonSubs (x2 -- 2 optimizer iterations) ->
RemoveUnreachable/RedundantJumps/Labels/JumpChaining (x3) -> RebuildCondExpressions
-> RewriteBitFieldTemps -> terminal "After IRO_Optimizer"):

- Immediately before the 2nd `IRO_CommonSubs` pass: `col_offset`'s multiply
  is IR node 352, `row_offset`'s is node 361 (col before row, matching
  source order).
- Immediately after that `IRO_CommonSubs` pass: node 364 (col_offset) / node
  373 (row_offset) -- same relative order, renumbered only because of
  unrelated node insertions elsewhere in the function.
- At the terminal pass "After IRO_Optimizer" (the very last front-end state
  before backend/PCode generation): node 364 `EMUL 363 361` -> assigned to
  `col_offset` (node 365); node 373 `EMUL 372 370` -> assigned to
  `row_offset` (node 377). Still col-before-row.

**CommonSubs never touches this pair** -- they are not shared subexpressions
(`y_spacing * col` vs `y_offset * row`, no overlapping operands), so there is
nothing for CSE to canonicalize between them. Across all 62 pass-dumps, in
both optimizer iterations, on the genuine retail 1.2.5n binary running under
a completely independent execution substrate (x86 emulation, not the
wibo/DLL path), **the two multiplications keep the exact C statement order
from declaration through to hand-off to the backend.** There is no
front-end reordering, canonicalization, or fusion event anywhere in the
trace for this pair.

**Verdict on the task's hypothesis (a):** the debug-DLL-derived claim in
`mndiagram_codex_loop_draw_sort_source_exhausted.md` /
`mndiagram_banked_coloring_ceilings.md` -- "MWCC's CSE canonicalizes the two
products into a fixed PCode order independent of source statement order" --
is **not falsified, but it was mis-attributed to CSE.** Retail's real
front-end CSE pass does not reorder or canonicalize these two nodes at all;
they stay in source order the whole way through the optimizer. Whatever
produces the fixed f26<->f28 assignment (col_offset -> target f28 / ours f26,
row_offset -> target f26 / ours f28, reversed) must be happening entirely in
the **backend register allocator** (coloring/dispense order over IR nodes
that are already in a stable, source-order-preserving sequence by the time
the backend sees them), not in a front-end CSE-driven reordering as the
"canonicalizes... independent of source order" phrasing implied. This
distinction matters because it rules out "try more source-statement
reorderings hoping to dodge CSE" as a lever (26 shapes were already tried and
failed for exactly this reason -- there was never a front-end reordering to
dodge) and confirms the wall is squarely backend/coloring, consistent with
`mndiagram_banked_coloring_ceilings.md`'s own conclusion via a completely
independent method (retail-via-emulation vs. debug-DLL-via-wibo).

**No retail-vs-debug-DLL divergence found for this function.** Both
execution paths run the identical `mwcceppc.exe` bytes; the front-end
behavior observed here is consistent with (not contradicting) everything the
debug-DLL pcdump path showed. The prior "proven exhausted" conclusion for
Draw's 26 source-shape attempts stands, now cross-validated on a second,
independent execution substrate for the front-end portion of the pipeline.
Backend-level (register coloring) cross-validation remains blocked by the
mwcc-retro 1.2.5n backend gap (issue #542) -- see above.

## RESULT: (b) CreateStatRow/GetStatValue u8 assume-clean convention -- retail front-end confirms single-widen, no per-call re-mask; consistent with debug-DLL backend finding

Ran `mwcc-retro` front-end IRO trace against retail `mwcceppc.exe` for
`src/melee/mn/mndiagram2.c`, covering both `mnDiagram2_GetStatValue` and
`mnDiagram2_CreateStatRow`. Extracted traces:
`build/mwcc_retro/src_melee_mn_mndiagram2/mnDiagram2_CreateStatRow/iro-trace-manual-extract.txt`
(122700 lines) and `/tmp/getstatvalue_trace.txt` (51696 lines, not copied
into the tree since GetStatValue wasn't the named target function, but
derived from the same official run).

At the terminal front-end pass ("After IRO_Optimizer", i.e. what the backend
receives) for `mnDiagram2_CreateStatRow`:

```
   1: Operand is_name_mode <ind> <immind> <reffed>
   2: EINDIRECT 1 <reffed>
   3: ETYPCON 2 <reffed>              <- the ONLY widen: u8 is_name_mode -> int mode
   4: Operand mode <assigned> ...
   6: EASS 5 3                          (mode = (int) is_name_mode;)
...
 372: Operand mode <ind> <immind> <reffed>
 373: EINDIRECT 372 <reffed>           <- plain reload, no re-widen/mask node
 374: Operand mnDiagram2_GetStatValue <reffed>
 375: Funccall 374(373,371,369) <reffed>   (mode passed raw to all 7 call sites)
```

Checked all 7 `mnDiagram2_GetStatValue` call sites in the terminal pass
(nodes 372-373, 432-433, 446-447, 907-908, 970-971, 1039-1040, 1128-1129) --
**every one loads `mode` with a plain `EINDIRECT`, no `ETYPCON`/mask node in
between.** The widen happens exactly once, at the `is_name_mode`->`mode`
assignment; after that, `mode` is treated as an ordinary already-typed `int`
local for the rest of the function, with zero extra front-end conversion
inserted per call.

On the callee side, `mnDiagram2_GetStatValue`'s own read of its `is_name_mode`
parameter (`if ((u8) is_name_mode)`, source line 459 etc.) is similarly a
bare `Operand is_name_mode -> EINDIRECT -> ETYPCON` with no additional
masking logic -- the front-end does not defensively re-clean the incoming
register.

**Verdict on task hypothesis (b):** this is exactly consistent with (does not
contradict) the debug-DLL-derived backend finding in
`createstatrow_assume_clean_wall.md` (target passes `is_name_mode` RAW with
zero `clrlwi` at all 7 call sites -- MWCC backend assume-clean). The
front-end IR shows *why* structurally: there is only ever one conversion
node for this value in the whole function (the initial widen into `mode`),
so there is nothing left at the PCode/backend level for a `clrlwi` to
re-clean even if the backend wanted to -- the front-end already collapsed
per-call redundant conversions before backend codegen, on the **real**
retail 1.2.5n binary, independently of the debug-DLL/wibo path. No
retail-vs-debug-DLL divergence found. This closes axis (b) as a genuine,
now doubly-cross-validated compiler convention rather than a debug-DLL
artifact -- the exhaustive 3-axis source-level test in
`createstatrow_assume_clean_wall.md` (register-steering, assume-dirty-vs-clean
typing, K&R prototype-less calling convention) was testing a real, retail-
confirmed compiler behavior, not chasing a wibo-specific mirage.

## RESULT: (c) mnVibration_Think register-allocator dispensing order -- confirmed not testable; front-end trace captured as a sanity check only

Ran the front-end IRO trace against retail `mwcceppc.exe` for
`src/melee/mn/mnvibration.c` / `mnVibration_Think` anyway (saved to
`build/mwcc_retro/src_melee_mn_mnvibration/mnVibration_Think/iro-trace.txt`,
618420 lines, full TU). The trace is unremarkable: `mnVibration_Think`'s
front-end IR construction, propagation, and 2 CommonSubs iterations proceed
normally with no anomalies, matching the current source
(`src/melee/mn/mnvibration.c:679-798`) structurally (the initial
`cur_menu != 0x13` early-return, the 4-iteration port loop, the 4-iteration
pad-status loop). This is a sanity check only, not a regalloc cross-check --
as documented above, `mwcc-retro` has no GC/1.2.5n backend port (issue #542
in the tool's own docs), so it cannot show register-allocator
priority/cost/adjacency, PCode passes, or the coloring/dispense sequence for
the retail 1.2.5n compiler. The only backend mwcc-retro can show is GC/1.1,
a different compiler build not used for matching, so it would not answer
"does retail 1.2.5n's dispense order match what mwcc-debug showed" even if
run.

Current checkdiff state for `mnVibration_Think` (read from a concurrent
sibling worktree's cached run, not re-verified independently to avoid
duplicating the parallel `wall-mnvib-think` effort): 97.0% match,
`backend-ceiling` classification, `normalized_diff_lines=3`, frame matches
exactly (128/128, delta 0). The dominant residual is a callee-save register
swap (r23<->r24) plus a related `gobj`/`data` pointer register reassignment
(r30 vs r25/r26), i.e. a pure coloring/coalescing question -- squarely the
kind of thing axis (c) asked about, and squarely the kind of thing this
tool cannot yet independently verify against retail.

**Verdict on task hypothesis (c): genuinely open, not resolved either way.**
I did not find (in this worktree's docs) an existing `mwcc-debug`-derived
force-phys/colorgraph writeup specifically naming `mnVibration_Think`'s
dispense order the way `docs/mwcc-allocator-algorithm.md` and the
`mwcc-debug-mnvibration-*.md` docs do for the sibling function
`mnVibration_RefreshNameRows` (0x80248644) -- see the function-identity note
above. If such a "proven exhausted via force-phys" conclusion exists for
`Think` specifically (created by one of the other parallel wall-mnvib-think
agents), it has NOT been retail-cross-checked by this session, and cannot be
until #542 lands. This is the one sub-question this investigation could not
answer either way; flagging it plainly rather than fabricating a comparison
using GC/1.1 data or the RefreshNameRows material (which is about a
different function).

## Bottom line

Two of three assigned axes produced a decisive, non-manufactured result:
retail GC/1.2.5n (run via an independent execution substrate, x86 emulation
via retrowin32+gdb, fidelity-gate-verified byte-identical `.o` output against
the normal wibo build) **agrees with** what the debug-DLL pcdump path showed
for both Draw's front-end CSE behavior (a) and CreateStatRow's u8
assume-clean widening pattern (b). No retail-vs-debug-DLL divergence was
found for either. This substantiates (does not reopen) the existing "proven
exhausted" conclusions for both functions, while correcting the mechanism
attribution for Draw: the wall is backend register-coloring, not front-end
CSE canonicalization (front-end never reorders the two products at all, in
either direction) -- a refinement worth updating in
`mndiagram_codex_loop_draw_sort_source_exhausted.md` /
`mndiagram_banked_coloring_ceilings.md`.

The third axis (c, mnVibration_Think's register-dispense order) could not be
tested: it is a pure backend question, and `mwcc-retro`'s GC/1.2.5n backend
support does not exist yet (tracked as the tool's own issue #542). No
GC/1.1-substitute comparison was used to manufacture an answer. This is the
one piece of the three-function sweep that remains a genuine gap, not a
finding either way -- worth a dedicated follow-up once #542 lands, or via a
from-scratch Tier-3-style binary hook extension of `mwcc-debug` itself
(analogous to what already exists for colorgraph interferer dumps) that
specifically compares retail-vs-DLL register assignment output byte-for-byte
on this function, if #542 is not imminent.

Also worth noting for whoever next uses `mwcc-retro`: `melee-agent debug
retro dump`'s internal 600s subprocess timeout (`tools/melee-agent/src/cli/
debug/retro.py:128`) is too short for large TUs (`mndiagram.c` at 2958 lines
took ~13 minutes wall time under this session's heavy host contention) and,
on timeout, leaks the child `retrowin32`+`gdb` processes (SIGKILL only
reaches the immediate `mwcc_retro_debugger.py` python3 child, not its own
`subprocess.Popen` children) -- I hit this 3 times and had to manually `kill`
the orphaned pair each time. Bypassing the CLI and invoking
`tools/mwcc_retro/mwcc_retro_debugger.py` directly with a long/no external
timeout avoided the issue and is what ultimately produced the successful
dumps in this session. Per the ground rules for this session I did not file
a tooling issue for this -- flagging it here for the record instead.
