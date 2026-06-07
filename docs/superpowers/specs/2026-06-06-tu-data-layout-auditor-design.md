# TU Data-Layout Auditor — Design / Spec

Status: design approved (high-level); revised twice per Codex review 2026-06-06.

## Problem

In the Melee decompilation, many functions in `NonMatching` TUs fail to match
not because of `.text` codegen but because the **file-local data**
(`.data`/`.bss`/`.sdata`/`.sdata2`/`.rodata` statics and literal pools) the
function references is laid out differently than the target. The function's
relocations then resolve to the wrong/anonymous symbol (objdiff shows
`...data.0`, `@286`, or a split sub-symbol) and the function is flagged
mismatched even when the `.text` bytes could be identical.

This is pervasive (`mnevent`, `ftCo_ThrownKirby`, `groldyoshi`) and under-tooled:
`mwcc-debug` is codegen/register, `struct verify` is struct field offsets,
`symbol-layout-analyzer.py` inspects ONE symbol's neighborhood. Nothing audits a
whole TU's data layout against the target object.

### Concrete evidence (mnevent: ref object vs our object)

| target `obj/...mnevent.o` | current `src/...mnevent.o` | discrepancy |
|---|---|---|
| `mnEvent_803EF758` size **0x30** (one object) | four objects `_758`+`_764`+`_770`+`_77C` (0xC each) | **split** |
| `mnEvent_803EF788` size **0xA** | size **0xC** | **size-mismatch** |
| `mnEvent_804A0908` (.bss) size **0x10** | size **0x4** | **size-mismatch** (BSS tentative) |
| `.sdata` `_5030,_5038,_5040,_5044` | `_5040` lands in the `_5030` slot; `_5030/_5038` absent | **reorder + missing** |

Confirmed via `nm -S` on both objects; not visible from source names (which
already equal the symbols.txt addresses). **The compiled objects are ground
truth for layout.**

## Goal / Non-goals

- GOAL: a read-only **analyzer** that, for a TU, reports every data-layout
  discrepancy (split / merge / size-mismatch / reorder / binding / missing /
  anonymous / gap-change), each with source location, confidence, and a concrete
  suggested change.
- GOAL: TU-agnostic; works on any `<file.c>` via the same logic.
- NON-GOAL (this phase): auto-applying fixes (documented phase 2).
- NON-GOAL: `.text` codegen ceilings (separate tooling).

## Approach (object-vs-object primary; static degraded/advisory)

The comparison is between two compiled objects, read with **pyelftools**
(already a `checkdiff.py` dependency — no dtk/nm requirement):

- TARGET layout + TU membership = the **reference object**
  `build/GALE01/obj/<unit>.o` (`checkdiff.py` `ref_obj`, line 3163). Its
  `.data/.bss/.sdata/.sdata2/.rodata` symbols define which data belongs to the TU
  and the target sizes/offsets/binding.
- CURRENT layout = the **our object** `build/GALE01/src/<unit>.o`
  (`checkdiff.py` `our_obj`, line 3164/3207).
- symbols.txt = absolute-address anchor + production names + a size **cross-check**
  (curated). The object diff is the authority; symbols.txt resolves names/addrs.
- source file = declaration line numbers + const/static/type, for suggestions.
- Object size = ELF `st_size`; target size = ref-object `st_size` (cross-checked
  vs symbols.txt). **Never** `next_addr - addr` (that is padded extent).

**Section-relative offsets vs absolute addresses.** Both objects expose
section-relative `st_value`. The core diff aligns target and current intervals by
section-relative offset directly (no absolute needed). For human-readable output
only, each section is anchored to absolute addresses via symbols.txt: pick a
symbol present in both the ref object and symbols.txt, set
`section_base = symtxt_addr - ref_offset`, then `absolute = section_base + offset`.

**name-magic caveat.** `checkdiff --name-magic` (default on) post-processes
*our* object to rename anonymous `.sdata2 @N` to production names
(checkdiff.py:3245-3252). The auditor reads objects as-is and notes that current
`.sdata2` *names* may be post-processed; **offsets/sizes remain authoritative**.

**Degraded mode (no/stale ref or our object).** Fall back to
source-declaration-computed sizes, marked **advisory/low-confidence**. It cannot
reliably detect reorder, generated literals, anonymous pools, or BSS tentative
sizes, so it is **excluded from acceptance/golden tests**. Never uses
next-address size. Address-encoded source names are used here only as fallback
identity hints.

Rejected: address-encoded names as primary current layout (trivially equal to
symbols.txt when correct); pure-static-only (blind to compiled reorders,
anonymous data, BSS tentative size); symbols.txt as sole target (misses the
real object's anonymous/generated symbols).

## Components (small, independently testable)

1. **`layout_common` (NEW shared module)**: extract `Symbol`,
   `parse_symbol_line`, `load_symbols`, `finding()` from
   `symbol-layout-analyzer.py` into an importable module (the hyphenated filename
   is not importable). The existing single-symbol tool imports from it unchanged.
2. **Object reader (NEW)**: read a `.o`'s data-section symbols via pyelftools →
   `(section, offset, size, name, binding, type)`, including local / `STT_NOTYPE`
   / anonymous (`@N`, `...data.N`) entries. Used for BOTH ref and our objects.
3. **Object path resolver (NEW)**: from `<file.c>` derive `obj_path` and the
   `ref`/`our` `.o` paths exactly as `checkdiff.py` does; `--object`/`--ref-object`
   overrides; clear error if absent (→ degraded).
4. **Source decl mapper (NEW)**: map symbol name → declaration line(s),
   const/static, best-effort declared type/array size. Handles "one source blob
   covering many target sub-symbols" (base+offset usage) — no 1:decl:1:symbol
   assumption.
5. **Interval model + comparator (NEW)**: per section, build target intervals
   `[off, off+size)` from the ref object and current intervals from our object;
   model inter-object **gaps** as explicit intervals in BOTH. Classify by overlap:
   - multiple current objects inside one target ⇒ **split**
   - one current object covering multiple targets ⇒ **merge/blob**
   - same start, different size ⇒ **size-mismatch**
   - target range with **no** current symbol ⇒ **missing** (source never modeled
     this generated/literal/pool data)
   - target range covered by an `@N`/`...data.N`/wrong-named current symbol ⇒
     **anonymous / name-mismatch**
   - current object in the offset slot the target assigns to another name ⇒
     **reorder/misplacement**
   - binding/scope differs (global vs local/static) ⇒ **binding-mismatch**
   - a gap whose size changed, or a real object overlapping an expected gap ⇒
     **gap-change** (otherwise gaps are not findings). Zero-size labels ignored
     as anchors unless referenced.
6. **Suggester (NEW)**: per class → concrete source change (merge N statics into
   one sized object; resize array/type; reorder decls; model the missing
   literal/blob; fix const/static), with the source line and confidence.
7. **Reporter/CLI (NEW)**: `python tools/tu_data_layout.py <file.c> [--json]
   [--root] [--object PATH] [--ref-object PATH]`; grouped by section; each finding
   = kind + message + suggestion + source line + confidence (high from objects,
   advisory from degraded); nonzero exit if discrepancies found.

## Data flow

`<file.c>` → resolve ref/our `.o` paths → object reader ×2 (target & current
intervals) + load symbols.txt (anchor/names) + source mapper (lines) → interval
comparator → suggester → reporter. Degraded path: skip object readers, use
declaration sizes (advisory), emit a freshness/confidence warning.

## Output (text) — must produce for mnevent (high confidence)

```
.data  src/melee/mn/mnevent.c  [ref obj/.../mnevent.o vs our src/.../mnevent.o]
  [split]   target mnEvent_803EF758 (0x30) emitted as 4 objects
            _758/_764/_770/_77C (0xC each), declared mnevent.c:83-86.
            -> model one 0x30 object; reference sub-fields by offset.
  [size]    mnEvent_803EF788: our 0xC vs target 0xA (mnevent.c:89). -> [0xA].
.bss
  [size]    mnEvent_804A0908: our 0x4 vs target 0x10 (mnevent.c).
.sdata
  [reorder] mnEvent_804D5040 in the target slot of _5030; [missing] target
            _5030/_5038 unmodeled in source.
```

## Error handling

- Missing symbols.txt / source file → clear error, nonzero exit.
- ref/our `.o` missing → degraded (advisory) mode + explicit warning; continue.
- **Staleness:** if our `.o` mtime is older than the `.c` (or its depfile inputs
  when available) → warn "object may be stale, rebuild for high confidence";
  if mtimes can't be compared → "freshness unknown".
- pyelftools missing → clear actionable error (it is a checkdiff dep).
- Unparseable declaration → "skipped, could not parse"; never crash.
- Symbol with no source decl (generated/literal) → reported as missing/anonymous,
  not an error.

## Testing

- Unit tests on the interval comparator with synthetic target/current interval
  sets: one per class (split, merge, size, reorder, binding, missing, anonymous,
  gap-change).
- Object-reader unit test against a checked-in tiny fixture `.o` (skip-if-absent).
- Acceptance on `mnevent.c` (real ref+our objects, high-confidence mode): must
  report the `_758` split, `_788` size, `_804A0908` BSS size, and the `.sdata`
  reorder/missing. **Degraded mode is excluded from acceptance/golden tests.**
- Generalization: a second TU (`ftCo_ThrownKirby` `.sdata2` / `groldyoshi`)
  surfaces its known data issues.
- Golden-output test for the mnevent report (high-confidence mode only).

## Generalization

TU-agnostic via `<file.c>`; the comparator is pure interval math over two ELF
objects. One suggestion will be hand-validated by applying it and re-running
checkdiff (proves output is actionable).

## Resolved review questions (Codex 2026-06-06, two rounds)

1. Address-encoded names = identity hints / degraded fallback only; current and
   target layouts come from the `.o` objects.
2. Split/merge = interval overlap with real `st_size` + explicit gaps; missing
   (no current symbol) distinguished from anonymous/name-mismatch.
3. Objects are primary via pyelftools (no dtk/nm); ref = `obj/`, our = `src/`.
4. New `tools/tu_data_layout.py` + extracted `layout_common` shared module.
5. Added: ref-object-based TU-range/membership; object-table ingestion for both
   objects; gap/padding modeling; binding/scope comparison; BSS tentative
   handling; name-magic caveat; absolute/relative anchor rule; staleness
   detection; degraded mode barred from acceptance tests.
