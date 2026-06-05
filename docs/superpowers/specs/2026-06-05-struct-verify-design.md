# struct verify — struct-offset discrepancy detection (design + plan)

Date: 2026-06-05
Status: READY — independent Codex review complete (2 passes). Pass 1 found 2
blockers + 4 concerns; pass 2 verdict PROCEED-WITH-CHANGES, all folded in.
Author: Claude (Opus 4.8), reviewed by Codex (codex-cli 0.135.0)

## 1. Problem & evidence

Many decomp mismatches are not register/codegen ceilings but **wrong struct
layouts**: the C accesses `ptr->field`, MWCC emits the wrong displacement, and
the function diffs. These are high-leverage because one struct fix cascades to
every function that touches the struct.

Concrete, measured on `extern/dolphin/src/dolphin/thp/THPDec.c` (whole TU is
`NonMatching`, 6/24 functions matched, 88.6% fuzzy):

- `__THPRestartDefinition` is **100% opcode-identical** (line_delta 0) yet fails
  only because `RST`/`nMCU`/`currMCU` are emitted at `0x740`/`0x742`/`0x744`
  but the target has them at `0x900`/`0x8fc`/`0x8fe` (`THPDec.s:2057/2065/2070`).
- The `__THPHuffDecodeDCTCompY/U/V` trio read `components[i].predDC` at element
  offset `+0`; target is `+6`, component stride `0x2c` (`THPDec.s:5569-5571`).
  Nested `THPComponent` layout is wrong, confirmed across all three.

A throwaway positional-alignment probe (reusing `checkdiff --format json`) found
both bugs across 4 functions, but only caught `line_delta == 0` functions. No
existing tool aggregates these.

## 2. Review outcome (what changed)

Codex verified assumptions against the code and flagged two blockers that
reshape v1:

- **Auto base-register inference is not viable for v1.** The struct pointer is
  frequently aliased into a callee-save (`__THPReadHuffmanTableSpecification`:
  `r3→r28`, `THPDec.c:742`/`THPDec.s:1386`), cast from a scalar arg and moved
  (`THPDec_80331340`: `s32 arg0`→ptr, `r3→r31`, `THPDec.c:605-623`), or an
  interior/global pointer (`&__THPInfo->components[i]`, `THPDec.c:1808-1832`).
  → **v1 takes explicit `--struct TYPE --base rN`.** Auto-inference (minimal
  dataflow over `mr`/`addi reg,arg,0`/casts/globals) is deferred to phase 2.
- **No reusable, nesting-aware offset→field resolver exists.**
  `tools/melee-agent/src/cli/struct.py` omits `extern/dolphin/include` from its
  search paths (`:25-32`,`:103-110`), its parser matches `struct {name} {` but
  THP uses typedef tags `_THPFileInfo`/`_THPComponent` (`thp.h:27,36`), and
  `struct offset` only reports the closest top-level field (nested = printed
  suggestion only, `:270-300`) via CLI side-effects (no API).
  → **A real layout resolver is a v1 prerequisite, not a reuse.**

## 3. Goal / non-goals

**Goal (v1):** given a function (or a TU = set of functions) **plus explicit
`--struct TYPE --base rN`**, detect load/store displacement discrepancies on the
named base register, map each current displacement to its source field (incl.
nested struct + array element via a new resolver), aggregate across the TU, and
report `field: current → expected (n functions, confidence)`. Human applies the
header edit.

**Non-goals (v1):** auto base-register inference; auto-applying header edits
(`--apply`); proposing the exact repad/reorder; from-scratch reconstruction;
type inference from access width. All deferred.

## 4. Architecture

Three pieces. (3a) and (3c) are reusable libraries; (3b) is the command.

### 4a. checkdiff extension (`tools/checkdiff.py`)

checkdiff classifies diffs in `classify_asm_diff` (`:1981`) with a displacement
template in `_paired_stack_delta` (`:1439`); `_asm_body` strips the
`+offset:`/byte prefix (`:407-415`); JSON assembled at `:3394-3408`.

Add `_paired_struct_offset_delta(ref_body, our_body)` → `{base_reg, mnemonic,
ref_disp, cur_disp}` when two aligned instructions have **same mnemonic, same
base register, differing displacement**, excluding `r1` (stack), `r2`/`r13`
(sda). Wire it in over aligned instruction pairs and emit
`offset_discrepancies: [...]` into the classification dict (a new **optional**
key — do **not** touch `primary`, so existing classifications are unchanged).

**Alignment correctness (Codex item 1):** the existing `SequenceMatcher`
(`:2260`,`:2520`) runs on **full normalized lines including the `+offset:`
prefix**, which shifts under insert/delete — so aligning on full lines does NOT
fix `line_delta != 0`. Align instead on **`_asm_body(line)`** (or a parsed
`(mnemonic, operand-shape)` key) and **skip relocation lines**
(`_is_relocation_line`, `:418`). Within each `equal`/equal-length `replace`
block, pair positionally; skip `insert`/`delete`.

**Duplicate-body guard (Codex confirmation item 2):** positional pairing inside
a `replace` block mispairs identical bodies — THP has clusters of repeated
`stw r0, 0x0(r28)` (`THPDec.s:1413,1417,1422,1427,1432,1437,1442,1447`). Only
emit a discrepancy when the pairing is unambiguous: require the immediately
neighboring aligned instructions (the `equal` context bounding the block, or the
adjacent pair within it) to match, and suppress emission when the same body
appears multiple times in the block with differing displacements (can't tell
which maps to which). Better to under-report than mispair.

### 4b. New command `melee-agent struct verify <function|TU> --struct TYPE (--base rN | --base-map FILE) [--json]`

**The base register is PER-FUNCTION, not TU-wide (Codex confirmation item 1a).**
A single `--base r3` is wrong for the TU: `__THPReadHuffmanTableSpecification`
holds the struct in `r28` and derives an interior base `r7 = r28 + index` for
`huffmanTabs[tab_index]` (`THPDec.s:1390,1396-1411,1455-1463`); applying `r3`
there would mismap unrelated `r3` uses.

1. Resolve TU → functions. `report.py` flattens and discards the unit mapping
   (`:37-54`,`:72-80`,`:145-173`) → **add a `functions_for_unit()` helper**.
   Batch builds (`--no-build` after one warm build); **skip attempt history
   writes** for verify runs (`:2270-2288`,`:3382`).
2. Per-function base resolution:
   - single function: `--base rN` required;
   - TU: `--base-map` (function → reg) for known cases; functions absent from
     the map are processed only if their base is unambiguously the first-arg reg
     at entry, else **warn + skip** (do not guess).
   - Interior-pointer bases (`r = base + index` for an array element, e.g.
     `huffmanTabs[i]`) are **out of scope for v1 → warn + skip**; revisit with
     dataflow in phase 5.
3. For each in-scope function: run checkdiff JSON, read `offset_discrepancies`
   for that function's base reg.
4. Map `cur_disp` (and `ref_disp` when resolvable) → field path via the resolver
   (4c).
5. Aggregate: per field `{current → expected, #functions, functions[],
   confidence}`. Collapse per-array-element consistent deltas
   (`components[*].predDC +0→+6`). Flag conflicts and skipped functions.

### 4c. New reusable layout resolver (`tools/melee-agent/src/.../layout.py`)

Build the resolver `struct offset` should have been (Codex item 3), exposing a
pure function `resolve(struct_type, abs_offset) -> {path, type, size,
elem_index}` (recursive into nested structs, array-aware, e.g.
`0x864 → components[1].predDC`). `struct offset` becomes a thin CLI over it.

**Strategy — compile-derived, NOT hand-parsed (Codex confirmation item 1b).**
`thp.h` pulls in `dolphin/os.h` → `dolphin/types.h`, bringing `ATTRIBUTE_ALIGN`,
primitive typedefs, MWERKS absolute-address decls and a deep include tree
(`thp.h:4`, `os.h:4`, `types.h:5-13,25`). Regex/naive C parsing cannot handle
this and would also have to re-derive the GameCube/MWCC ABI alignment exactly.
Instead, **derive the layout from the compiler**: compile a tiny probe TU
(`#include` the header; declare one instance of the struct) with the project's
MWCC + `-g`, then read the struct's member offsets from DWARF. This inherits the
exact ABI layout and resolves all includes/macros/typedefs for free. The mwcc
debug-build path already exists (`debug dump` / `mwcc_debug`); reuse it.
Acceptance gate = the Phase-0 golden offsets. Fallback if DWARF is impractical:
preprocess (`mwcceppc -E`) then parse the flattened struct — still ABI-aware via
a layout pass, never naive regex on raw headers.

## 5. Implementation plan (phased)

**Phase 0 — fixtures (no code):** snapshot THPDec per-function fuzzy %; record
golden answers — **all** adjacent tail fields, not just the 3 obvious ones
(Codex item 5): the deltas are a layout reconciliation (`0x70/0x72`,`0x78`,
`0x8d4`,`0x8f0-0x904`, `THPDec.s:1007/1015/1483/2089`), so capture the full
expected field→offset map for `THPFileInfo` tail + `THPComponent`. Also capture
the **base-map** for THPDec functions (which reg holds the struct, which are
interior/aliased and must warn-skip), plus three adversarial fixtures (Codex
confirmation item 3): (a) aliased base `__THPReadHuffmanTableSpecification`
(`r28`/interior `r7`) → expect warn+skip, no false findings; (b) duplicate-body
cluster (the repeated `stw r0,0x0(r28)`) → expect no mispaired discrepancy;
(c) known-field-vs-known-field → expect `ambiguous`, not a silent fix.

**Phase 1 — layout resolver (4c) + tests.** Prerequisite for everything else.
Golden: `0x900→RST`, `0x8fc→nMCU`, `0x864→components[1].predDC`.

**Phase 2 — checkdiff extension (4a) + tests.** `_paired_struct_offset_delta`
(unit: offset-only, same/diff base, r1/r2/r13 exclusion, `+2` halfword reloc).
Body-level alignment; emit `offset_discrepancies`; assert existing
classifications unchanged on sampled functions; assert
`checkdiff __THPRestartDefinition --json` contains the 3 discrepancies.

**Phase 3 — `struct verify` command (4b).** `functions_for_unit()` helper;
no-build batching; aggregation + confidence/disambiguation (§6); human table +
`--json`.

**Phase 4 — dogfood/validation.** `struct verify THPDec --struct THPFileInfo
--base-map thp.bases`; apply the `THPFileInfo`/`THPComponent` fixes by hand;
`python configure.py && ninja`;
confirm cascade (`__THPRestartDefinition`→100%, Y/U/V improve; no regressions via
matched-set report.json diff). Acceptance test for the tool.

**Phase 5 (deferred):** auto base-register inference (dataflow); layout-edit
proposal; `--apply`.

## 6. Confidence & disambiguation (Codex item 4)

- **Keep singletons** (RST/nMCU/currMCU are each one store) — at *lower*
  confidence, not dropped.
- Confidence high when `cur_disp` maps to a known field AND ≥1 function agrees;
  cross-function agreement raises it.
- When **both** `cur_disp` and `ref_disp` map to known but **different** fields,
  mark **ambiguous** (could be a deliberate different-field access, not a bug) —
  surface, don't silently merge.
- Conflicts (same field, different expected across functions) flagged.

## 7. Testing

- Unit: layout resolver (nested/array/typedef/extern paths);
  `_paired_struct_offset_delta`; relocation-line skipping.
- Golden: `struct verify THPDec --struct THPFileInfo --base-map thp.bases --json`
  contains RST/nMCU/currMCU + `components[*].predDC` with correct
  current/expected, and lists the aliased/interior functions as warn-skipped.
- Regression: existing checkdiff classifications unchanged on sampled functions
  (incl. register-ceiling `__THPHuffDecodeDCTCompU` — must NOT report offset
  findings, its diffs are register-only).
- Acceptance: Phase 4 cascade.

## 8. Open questions

- Resolver: how to pick the right struct when a `.c` defines several? `--struct`
  is explicit in v1, so deterministic — but the resolver still needs a header
  search order; confirm `extern/dolphin/include/dolphin/thp/thp.h` is found.
- Is report-only v1 worth it, or does the manual delta→pad/reorder step negate
  value? (Phase 4 will answer empirically on THPFileInfo.)
