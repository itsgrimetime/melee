# mwcc-retro: retail-binary MWCC introspection + front-end pass tracing (issue #541)

**Date:** 2026-06-10
**Status:** Approved (adversarial design review passed, APPROVE-WITH-CHANGES incorporated)
**Issue:** #541 — Integrate cadmic/mwcc-debugger (retrowin32+gdb) and implement front-end optimizer pass tracing

## 1. Goal

Give melee-agent zero-perturbation introspection of the **retail** `mwcceppc.exe`
(GC/1.2.5n — the exact compiler melee matches against), covering the full pipeline:

- Front-end AST snapshots (initial / after-optimizations / final)
- **Front-end IRO optimizer per-pass IR dumps + pass-sequence trace** (the headline:
  unimplemented anywhere today)
- Backend PCode dumps per optimization pass
- Register-allocator priority/cost/adjacency dumps (Chaitin internals)
- Stack allocation maps (arguments/locals/temps/spills with r1+offset ranges)
- A write-capable gdb substrate usable for future interventions

This complements (not replaces) the existing patched-DLL pcdump path, which is fast
but demonstrably diverges from retail in at least one recorded case
(ftCo_Shouldered r27-vs-r30).

## 2. Established evidence (verified 2026-06-10)

| Fact | Evidence |
|---|---|
| cadmic/mwcc-debugger@bad9cea: 1742-line self-bootstrapping gdb-python script; `MwccVersion` dataclass is the whole port surface (~15 addresses + 3 AST bps + ~45 PCode bps + regalloc/frame globals); supports GC/1.1 + GC/2.6 | clone at /tmp/mwcc-debugger, full read |
| retrowin32 gdb-stub branch (encounter@11dbea5a) implements `write_addrs`/`write_registers` unconditionally in both backends; cadmic's script already requires writes (per-function `call CMangler_GetLinkName`) | branch source read |
| gdb 17.1 (homebrew, arm64 macOS) accepts `set architecture i386`; cargo 1.85 + cmake present; GC/1.1, 1.2.5, 1.2.5n compilers + lmgr326b.dll all local | local probes |
| 1.2.5 vs 1.2.5n differ by **53 bytes**: jmp redirect at VA 0x4abd9a, 2 bytes at 0x4abdb3, 46-byte stub at 0x506510 ("Hacked by Ninji 2023-07-15"). One table serves both if no entry overlaps those ranges | byte diff + PE section map |
| Retail GC/1.1 **and** 1.2.5n contain the complete IRO dump machinery (strings "Dumps for pass=%d", "Dumping function %s after %s", "Flowgraph node %d", all pass names). Per-phase dumps are dormant: every `IRO_DumpAfterPhase(name, flag)` call site passes `flag=0`. `OPT.LOG` fopen is absent from **all** retail binaries — DumpFile is set some other way | strings scans; Ninji decomp IrOptimizer.c/IroDump.c |
| Existing pcdumps already contain `IRO_Dump` output (`Starting function`, `Dumps for pass=N`, `IRO_FindLoops...`) but **zero** per-phase dumps | grep of build/mwcc_debug_cache + tests/fixtures |
| Our DLL (tools/mwcc_debug/mwcc_debug.c) documents the full 1.2.5n dump-enable recipe: `DEBUGLISTING`@0x584226 (the 0x42C8E1 patch byte is its option default), `PCFILE`@0x580610 (compiler dump FILE*), `DEBUG_GUARD`@0x5882B8, compiler's own `fopen`@0x40C690. Plus known 1.2.5n VAs usable as port ground truth: colorgraph 0x4CE2D0, simplifygraph 0x4CE400, IG builder 0x530C00, coalescer 0x530E00, formatoperands 0x4C4BF0, pcode_traverse 0x4C2560, pclistblocks stub 0x4C4BD0, debug_printf 0x44D580 | mwcc_debug.c read |
| String push-imm anchors ("Starting function %s", "Dumping function %s after %s", "Before IRO_LoopUnroller") are **unique** (1 site/binary) with uniform **+0x10 .text drift** GC/1.1→1.2.5; .data drift uniformly **−0x1000**. Independently corroborated by mwcc-inspector's bp table (0x42cd0f → 0x42cd1f) | reviewer binary scans |
| mwcc-inspector (RootCubed) ships GC/1.2.5 donor data: front-end snapshot bp 0x0042cd1f (ebx=Statement, ebp=function ObjObject), build-date detection ("Apr 23 2001" = GC/1.2.5) at `.data+0x10` via u32 at file 0x1fc, and ENode/Statement/ObjObject/Type layouts uniform across GC/1.0–1.2.5 | clone at /tmp/mwcc-inspector |
| IGNode layout in cadmic-GC/1.1 matches our independently-RE'd 1.2.5n IGNode **field-for-field**; PCode `op`@0x14 matches. **PCodeBlock 0x20–0x2C region conflicts** between the two sources (line/loop_weight/pcode_count vs codeOffset/loopWeight) — one is mislabeled; silent-failure risk | cross-read |
| Ninji MWCC decomp (git.wuffs.org/MWCC@094b96c, v7/pro7-era) provides IRO_Optimizer pass sequence (matches retail strings exactly), IroDump.c semantics, IROLinear layouts (v7-era — indicative only for 1.2.5) | clone at /tmp/mwcc-decomp |
| cadmic upstream bugs: ELABEL loader NameError (undefined `children`); `init_mwcc_version` probes VA 0x541BBC which is **zeros in 1.2.5n** (cannot detect it); hardcoded port 9001; one-function-then-quit lifecycle; module-level mutable caches | script read |
| cadmic repo has **no LICENSE** → vendor-by-clone (gitignored), never commit upstream code | repo listing |

## 3. Architecture

```
tools/mwcc_retro/                      (committed)
├── README.md                          # what/why/usage/attribution
├── mwcc_retro_debugger.py             # OUR gdb-side script (stdlib-only):
│                                      #   imports vendored cadmic module as a library,
│                                      #   replaces init_mwcc_version (build-date detection),
│                                      #   injects GC/1.2.5n MwccVersion (name-spoof "GC/1.1"),
│                                      #   monkeypatches upstream bugs (ELABEL),
│                                      #   extended run loop: front-end IRO tracing + upstream dumps,
│                                      #   in-loop bp invariants, state reset between functions
├── port_table.py                      # host-side address porter GC/1.1→1.2.5(n):
│                                      #   string-anchored push-imm scan (pure python),
│                                      #   wildcarded byte correlation (capstone, optional dep),
│                                      #   monotonicity + uniqueness-margin constraints,
│                                      #   Ninji-patch-range overlap assertion,
│                                      #   per-address provenance + confidence output
├── tables/gc_125n.json                # generated+committed port table (provenance per entry)
└── vendor/                            (gitignored; populated by `debug retro setup`)
    ├── retrowin32/                    # encounter/retrowin32 @ 11dbea5a (gdb-stub), cargo-built
    └── mwcc-debugger/                 # cadmic/mwcc-debugger @ bad9cea

tools/melee-agent/src/cli/debug/retro.py   (committed; registered via add_typer like search_app)
tools/melee-agent/tests/test_retro*.py     (committed)
docs/mwcc-retro.md                          (committed; workflow doc)
.claude/skills/mwcc-retro/SKILL.md          (committed)
```

Output layout (gitignored): `build/mwcc_retro/<unit>/<function>/`
- `frontend-NN-ast-<name>.txt` (upstream AST dumps)
- `iro-trace.txt` (raw in-band IRO per-phase dump stream)
- `iro-NN-<phase>.txt` (split per-phase IR dumps; slug rule: lowercase, runs of
  non-alphanumerics → `-`, trimmed to 60 chars; NN = 2-digit order of appearance
  within the function's trace — retail phase names contain spaces/colons/parens)
- `iro-summary.txt` (pass sequence keyed (function, pass-iteration N, phase) + per-phase
  diffs: IROLinear indices/temps appearing/disappearing = temp-creation ledger v1)
- `backend-NN-<pass>.txt`, `regalloc-<cls>-pass-N-{all,assigned}.txt`, `variables.txt` (upstream)
- `provenance.json` (true compiler identity + table + pinned SHAs + timings — dumps must
  not silently claim "GC/1.1" because of the name-spoof)

## 4. Key design decisions (review-settled)

**D1 — Version injection via name-spoof.** Our injected `MwccVersion` for 1.2.5n uses
`name="GC/1.1"` so every upstream version-conditional struct reader takes the GC/1.1
layout path. Justification: inspector ships one binary family for GC/1.0–1.2.5;
IGNode/PCode layouts cross-confirmed against our own 1.2.5n RE. Conditions: wrapper
replaces `init_mwcc_version` outright (mandatory anyway — upstream cannot detect
1.2.5n); build-date preflight ("Apr 23 2001"); `provenance.json` records the true
identity; PCodeBlock disambiguation in verify (D5).

**D2 — Front-end per-phase dumps: light up the compiler's own dump machinery.**
Recipe (proven by the DLL): `DEBUGLISTING=1`, `DEBUG_GUARD=1`, stage a filename in
scratch memory, `call fopen(0x40C690)` and store the `FILE*` into `PCFILE` — retail's
`IRO_Dump` then writes to our file. Per-phase dumps: **one-time .text patch** of the
flag test (`jz`) inside `IRO_DumpAfterPhase` (string-anchored at the unique
"Dumping function %s after %s" push site), applied at attach before first execution
(unicorn translation-cache safety). Fallback within the same strategy: bp at
`IRO_DumpAfterPhase` entry + stack write `[esp+8]=1`. Function scoping: bp at
`IRO_Optimizer` entry, read `func->name` (offset +0xA chain), set `IRO_Log`
equivalent only for the target function. To resolve whether `IRO_Log` is a distinct
global or `copts.debuglisting` itself: follow the `call` immediately after the
"Starting function" push (0x42cd86 in 1.2.5n) into `IRO_Dump`, and read the abs32
operand of its first `cmp byte` — that global is the gate. (At the push site itself
expect the `DoScalarize/DoLinearize/EarlyReturn` init movs and the
`mov eax,[eax+0xA]` name chain, not the gate test.) Rejected: re-implementing an IROLinear
pretty-printer from v7-era headers (zero 1.2.5 layout evidence). If the in-compiler
dump path somehow fails, the sanctioned fallback is lifting IROLinear offsets from
retail's own `DumpLinearNode` disassembly (string-anchored), not v7 headers.

**D3 — Single dump command, precise contracts.** No separate `trace` command.

`debug retro dump <src> -f FN [--phases all|frontend|backend] [--compiler 1.2.5n|1.1] [-O DIR] [--gdb-py HOOK.py]`
- Defaults: `--phases all`, `--compiler 1.2.5n`, output `build/mwcc_retro/<unit>/<function>/`.
- Exit codes: `0` = all requested phase streams produced; `2` = compiler-under-emulation
  failed; `3` = target function not found in TU; `4` = partial (≥1 requested phase
  stream missing/truncated — raw files kept, missing phases listed on stderr); `5` =
  safety invariant fired (read-before-write byte assert or in-loop bp invariant).
- Raw files always kept alongside summaries.

`debug retro setup [--force]`
- Idempotent; re-verifies pinned SHAs and rebuild-needed state; exit nonzero names
  the failing step. Clone URLs and pins: `https://github.com/encounter/retrowin32`
  branch `gdb-stub` checked out at `11dbea5a`; `https://github.com/cadmic/mwcc-debugger`
  checked out at `bad9cea`. After checkout, assert `git rev-parse HEAD` equals the
  pin — do NOT float to branch tip. Build command:
  `cargo build -p retrowin32 -F x86-unicorn --profile lto`.
- STOP CONDITION: pinned SHA unfetchable, or cargo build fails after one clean
  retry → halt, file issue with full output.

`debug retro verify [--unit SRC] [-f FN]`
- Defaults to the mnVibration control TU/function. Prints one PASS/FAIL line per D5
  check; exit `0` iff all *authoritative* checks pass (advisory failures printed,
  non-fatal).

**D4 — DLL fast path in scope (P5, gated).** Once the flag-test VA is known, add an
env-gated (`MWCC_DEBUG_IRO_PHASES=1`) patch to mwcc_debug.c so per-phase IRO dumps
appear in the standard wibo pcdump. Gate: cross-validate DLL per-phase dumps vs
retrowin32-retail dumps on ≥2 control functions (DLL-vs-retail fidelity doubt is the
premise of #541).

**D5 — Verification is layered, not post-hoc only.**
- In-loop first-fire invariants per ported bp: regalloc bp → coloring_class ∈ {0,1};
  AST bps → statement list parses with valid stmt_types; PCode bps → opcode index <
  opcodeinfo_size and operand kinds valid; codegen_start → function name resolves.
- Read-before-write byte assertions before every .text/.data patch (e.g. expect
  `c6 05 26 42 58 00 00` at 0x42C8DB) — `write_addrs` panics on bad addresses.
- `debug retro verify`: control-TU cross-checks vs existing pcdump DLL output.
  Each check is classed **authoritative** or **advisory**:
  - Authoritative: AFTER-REGALLOC virtual→phys map equality; regalloc node counts;
    final-code dump consistency vs the real .o.
  - Advisory (initially): block-header `LOOPWEIGHT=` equality. The DLL side is
    itself suspect (committed fixture shows `LOOPWEIGHT=-1602224128` garbage). On
    mismatch, tie-break ground truth by (i) disassembling retail's own block-header
    dump path in the pristine exe (the DLL stubbed `pclistblocks`@0x4C4BD0 — read
    which offset retail's printf loads), and/or (ii) semantic plausibility (loop
    weights follow the 1/4/16/64 LoopUsage ladder; entry block = 1; garbage loses).
    Record winner+loser per side in provenance.json; if the DLL is wrong, file a
    DLL bug and mark the DLL non-authoritative for that field.
  - Phase gates ("verify green") and the verify exit code reflect authoritative
    checks only.
- Port-table generation seeds/cross-checks against the DLL's known 1.2.5n VAs
  (colorgraph 0x4CE2D0 etc.). Element COUNTS (`nodenames_size`=75,
  `opcodeinfo_size`=468) are not anchor-portable: carry over GC/1.1 counts only
  after a bounds probe (read entries until a non-pointer/out-of-section value or
  derived table extent); in-loop invariants guard the residual risk.

**D6 — Wrapper owns process/port lifecycle.** Port allocation (or lockfile
serialization if the stub port is fixed), emulator kill on gdb failure, timeout
budget, module-state reset between functions (upstream assumes one-function-then-quit).
Parallel agents are the norm in this repo.

**D7 — capstone as `retro` optional-dep group** (precedent: `ppc-ref`). Host-side
port tool only; the gdb-embedded script stays stdlib-only. Push-imm scanning works
pure-python; capstone is for operand-class wildcarding in backend correlation, with
graceful degradation.

## 5. Phases (reordered per review: front-end decoupled from backend port)

**P0 — Substrate spike + fidelity gates.** Build retrowin32 (gdb-stub, x86-unicorn,
lto). Run cadmic AS-IS on GC/1.1 against the mnVibration control TU (mangled names
from `nm` on the .o / linkname); if GC/1.1 rejects melee's 1.2.5n-flavored unit,
fall back to a minimal fixture .c with the same flag family — the substrate probes
don't depend on which source compiles. Probe from homebrew arm64 gdb 17.1: remote
attach, memory write, **`call` injection** (the genuinely untested piece —
dummy-frame on no-symbol i386 remote). Fidelity gate: run mwcc 1.2.5n under plain
retrowin32 on a real melee TU command line (via `_ninja_cflags_for_unit`, no
wibo/sjiswrap) and **byte-compare the .o against the wibo-produced .o** (unicorn x87
semantics risk). Performance budget: record TU-compile + single-function dump
wall-clock; document. STOP CONDITIONS: .o not byte-identical → halt, file findings
(per issue stop condition, expanded); gdb `call` injection unusable → switch
function-matching to `obj.name` (+0xA) and the fopen step to a staged-stack manual
call sequence, both documented fallbacks.

**P1 — GC/1.1 integration end-to-end.** Vendoring setup command, our wrapper script
(lifecycle, invariants, monkeypatches, state reset), `debug retro setup|dump` on
GC/1.1 proxy mode, output layout + provenance, CLI tests. ACCEPT: dump on the GC/1.1
control TU produces frontend-*, backend-*, regalloc-*, variables.txt, and
provenance.json with zero invariant violations; unit + CLI tests green. (The
issue's "GC/1.1 AST dumps vs mwcc-inspect ENodes" cross-check is subsumed by D5
parse-validity invariants here plus P2's IRO_Dump line-equality check; a manual
mwcc-inspect comparison remains optional since it needs the remote Windows host.)

**P2 — Front-end IRO tracing on 1.2.5n directly** (the headline; needs no backend
table). Anchor IRO_Optimizer/IRO_DumpAfterPhase/flag-test/IRO_Log-or-debuglisting in
1.2.5n via unique strings (+ known +0x10 drift as prior, verified per-site). Dump
recipe per D2. Per-function scoping. Split `iro-trace.txt` into per-phase files;
build `iro-summary.txt` (pass-iteration-aware) + temp-ledger v1 from per-phase diffs.
Also wire the same tracing for GC/1.1 via the same string anchors (cadmic's
MwccVersion has no IRO entries) so proxy mode has parity.
ACCEPT (all binary): (a) `iro-trace.txt` for the control function contains ≥1
`Dumping function <fn> after <phase>` block and every emitted phase name appears in
the retail binary's own pass-name string set (NOT the v7 decomp — retail may
legitimately differ from the decomp's sequence); (b) the IRO_Dump preamble lines
(`Starting function` / `Dumps for pass=N` / `IRO_FindLoops...`) are line-identical
to the same function's section in the existing DLL pcdump; (c) zero per-phase
blocks for non-target functions.
STOP: if the flag-test site or the IRO_Log global resolves to 0 or ≥2 candidates
after string-anchor + drift-prior + call-target disassembly, halt P2, record the
candidate set in provenance.json, file an issue; do NOT guess-patch
(read-before-write asserts are a backstop, not a license).

**P3 — Backend table port 1.2.5n.** `port_table.py` per D5/D7 constraints
(monotonicity, uniqueness-margin, patch-range overlap assertion, DLL-VA
cross-checks, micro-context contracts like "regalloc bp reads args at esp+4/8 at end
of colorgraph"). Generate `tables/gc_125n.json` + commit. `debug retro verify`
harness green on ≥1 control TU (mnVibration fixture function class). Document any
address that resists porting with its anchor evidence; per-address manual-ghidra
fallback notes.

**P4 — variables.txt + regalloc on 1.2.5n.** Frame globals (.bss-region; −0x1000
prior does not apply to .bss — treat as fresh finds via operand extraction). Stack
maps validated against the **symbolic stack-home operands** (`name+0xNN(r1)`) in the
DLL final-code listing for the same objects (the DLL emits no dedicated stack-map
table; cf. `_pcdump_has_symbolic_stack_homes`): variables.txt r1+offset ranges must
agree for every object that appears in both.

**P5 — DLL fast path + docs/skill/memory.** D4 patch (env-gated) + cross-validation
gate: line-equality of per-phase dump streams (after normalizing the function-name
header) between the DLL path and retrowin32-retail on ≥2 control functions. On
divergence: leave `MWCC_DEBUG_IRO_PHASES` default-off, file a fidelity issue, and
proceed with P5 docs/closure — the retail path remains the reference (divergence is
the premise of #541, not a blocker for it). Then `docs/mwcc-retro.md`,
`.claude/skills/mwcc-retro/SKILL.md`, capabilities regen, memory updates, issue
#541 resolution (or explicit follow-on issues for any declared-out residue).

## 6. #541 deliverable coverage

| Issue promise | This design |
|---|---|
| Per-pass AST/IR dumps | P2 (front-end IRO per-phase), upstream AST ×3 + backend per-pass (P1/P3) |
| Transform decision traces | v1 = IRO_Dump's own decision lines (FindLoops/unroll etc.) + per-phase diffs; predicate-level traces (why CSE fired) = declared follow-on issue |
| Temp-creation ledger | v1 = per-phase IROLinear/temp diff in iro-summary; creation-ORDER ledger refinement = follow-on |
| Ground-truth stack maps | P4 variables.txt on 1.2.5n |
| Retail regalloc cost/priority dumps | P3 (cadmic's regalloc-*-{all,assigned} on 1.2.5n) |
| Intervention-capable substrate | Write-capable stub verified; CLI escape hatch `debug retro dump --gdb-py <hook.py>` (runs user hook inside the session); full intervention UX = declared follow-on |
| 1.2.5n address port | P2 (front-end anchors) + P3 (backend table) + committed provenance |

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| unicorn FP/emulation infidelity → unrepresentative dumps | P0 .o byte-parity gate (hard stop) |
| gdb `call` injection fails on this stub | P0 probe; documented manual-call + name-matching fallbacks (no `call` on hot path) |
| Wrong ported address fires silently wrong | in-loop invariants + read-before-write byte asserts + verify harness |
| PCodeBlock layout mislabel (silent bad LOOPWEIGHT/line) | explicit verify check vs DLL block headers |
| -O3/-O4 near-clone regions confuse correlation | monotonicity + uniqueness-margin + DLL-VA seeds |
| Ninji patch ranges collide with table entries | automated overlap assertion in port_table.py |
| Emulation too slow for big TUs | perf budget recorded in P0; per-function bp scoping; documented diagnosis-grade positioning |
| Port 9001 collisions / orphan emulators (parallel agents) | D6 lifecycle ownership |
| Upstream dormant/no-license | pinned vendor-by-clone, gitignored; file upstream license request, don't block |
| gdb-embedded python constraints | wrapper script stdlib-only; capstone host-side only |

## 8. Testing

- **Unit (fast, default):** PE parsing, push-imm scanner, table generation/validation
  logic against the real local exes (read-only; skip-if-missing for fresh clones/CI),
  iro-trace splitter + summarizer on fixture text, CLI arg/exit-code behavior with
  mocked subprocess.
- **Live (marker `slow`, env-gated like existing live tests):** P0 fidelity gates,
  end-to-end GC/1.1 + 1.2.5n dumps on a small control TU, verify harness.
- Fixtures: reuse
  `tools/melee-agent/tests/fixtures/role_identity/mnVibration_matched_pcdump.txt`
  as the DLL-side oracle; add a small committed iro-trace fixture once P2 produces
  one.

## 9. Non-goals

- Inner-loop search throughput (this is diagnosis-grade; the search substrate stays
  on wibo).
- GC/2.6 / other-version support beyond keeping upstream's tables intact.
- Full intervention UX (force-IRO-decision flags etc.) — substrate + escape hatch
  only; follow-on issue.
- Windows host support (existing remote paths cover that).

## 10. Follow-on issues to file at completion

1. Predicate-level transform decision traces (bp inside IRO_CommonSubs/LoopUnroller
   decision sites; needs targeted RE of pass internals).
2. Temp-creation ORDER ledger (creation-event hooks, not per-phase diffs) feeding the
   ig_idx-order investigation.
3. Intervention UX on the retro substrate (state mutation commands beyond --gdb-py).
4. Upstream license request + (if granted) true fork consolidation.
