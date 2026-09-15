# Design: `data-match` skill

**Date:** 2026-06-18
**Status:** Approved (design); pending implementation plan
**Author:** session brainstorm (derived from ribbanya / Robin Avery PRs #2736, #2738, #2739)

## Summary

Add a Claude Code skill, `data-match`, that drives an agent through matching the
**data sections** of a Melee translation unit — `.data`, `.rodata`, `.sdata`,
`.sdata2`, `.bss`, `.sbss` — including fixing data ordering, symbol scope/type,
split / anonymous / missing / mis-sized objects, and translation-unit
boundaries. It is a **pure markdown playbook** that wraps the existing
`melee-agent layout audit` CLI plus the normal build/diff loop; it ships no new
tooling.

## Background & motivation

Every existing decomp skill (`decomp`, `decomp-fixup`, `understand`, the `mwcc-*`
family) targets **code/function** matching. Data-section matching has no guide,
yet it is a distinct discipline: the bytes are usually correct, but the
*ordering*, *symbol scope*, *object boundaries*, and *owning object file* are
wrong. Getting them right is a finite, classifiable toolkit, not one-off
cleverness.

Three merged PRs by ribbanya on the `pr/data` branch (#2736, #2738, #2739, all
titled "Improve data matches") demonstrate the full toolkit on real TUs. The
techniques also appear ~28 times across `docs/discord-knowledge/` but only as
buried tribal knowledge with no actionable workflow.

Critically, the mechanical diagnosis is already half-built: `melee-agent layout
audit <file>` reports data-layout discrepancies and emits a **closed vocabulary**
of discrepancy classes, each with a one-line hint. The skill's value-add is the
*nuance those hints omit*, the symptom→lever decision tree, the TU-split
sub-flow, and the verification discipline.

## Scope

**In scope:** diagnosing and fixing data-section layout for a TU — ordering,
scope/type, split/anonymous/missing/size discrepancies, and splitting a merged
source file into the real object-file boundaries.

**Out of scope (YAGNI):**
- No new CLI or generator tooling. The skill wraps `layout audit`, `configure.py`/`ninja`, `tools/checkdiff.py`, and `melee-agent attempts`/`issue`.
- No register-allocation / instruction-scheduling / coloring work — that stays with `/decomp` and the `mwcc-*` skills.
- The skill does not auto-infer struct semantics or true values; it points the agent to where reverse-engineering judgment is required and stops cleanly.

## Skill identity

- **Name / invocation:** `data-match`, invoked `/data-match <file-or-module>`. Parallels `/decomp`, `/understand`, `/decomp-fixup`.
- **Location:** `.claude/skills/data-match/SKILL.md` (plus optional reference files under the same dir if the catalog grows large).
- **Frontmatter `description` (triggering text):** "Use when matching the data sections (.data/.rodata/.sdata/.sdata2/.bss/.sbss) of a Melee TU — fixing data ordering, symbol scope, split/anonymous/missing objects, sizes, and translation-unit boundaries — after code matches or whenever `layout audit` reports discrepancies."

## Entry states & "done" definition

**Entry states the skill handles:**
1. Code/text of a TU matches but its data sections still mismatch.
2. A merged source file needs splitting into the real object-file boundaries.
3. Any time `melee-agent layout audit` is non-empty for a TU.

**Done = all three of:**
1. `melee-agent layout audit <file> --check-binding` returns **clean**, AND
2. `python configure.py && ninja` **builds green**, AND
3. The TU's data sections reach 100% in the standard diff check (`report.json` per-object fuzzy match; `tools/checkdiff.py` for the TU's functions).

**Necessary-but-not-sufficient nuance (must be stated in the skill):** an empty
`layout audit` proves the *shape, order, scope, and naming* are correct but does
**not** prove the byte *values* are correct. The objdiff/`report.json` data
comparison in (3) is the real done signal; audit-clean alone is not.

## Workflow (the core loop)

1. **Preconditions.** Run `python tools/worktree-doctor.py --fix`. Verify the
   target isn't already matched upstream (`git fetch upstream` + check the file)
   per the "verify against fresh upstream" norm. Capture the baseline
   (`layout audit` output + current `report.json` match for the object).
2. **Diagnose.** `melee-agent layout audit <file> --check-binding [--json]`.
   Record the full discrepancy list.
3. **Triage.** Map each discrepancy through the decision tree (below) to a lever.
4. **Apply.** Make the source / `symbols.txt` / `splits.txt` / `configure.py`
   edit for that lever.
5. **Re-audit + verify.** Re-run `layout audit` (it should shrink toward empty);
   keep `ninja` green; confirm the object's data match improved. Loop 2–5.
6. **Record / stop.** `melee-agent attempts record …` for meaningful steps. On a
   genuine reverse-engineering blocker, file an issue
   (`melee-agent issue report …`) and document what is known. **Never** claim
   "done" below a full match; **never** label data "unmatchable" — the source
   provably exists because it compiled from C.

## Decision tree: `layout audit` class → lever + omitted nuance

The spine of the skill. `layout audit` emits exactly these classes (verified
from live output on `gmregtyfall.c` and `grpushon.c`):

- **`[reorder]`** ("at offset X (target Y)") → reorder declarations to match
  target address order. **Nuance:** for *uninitialized* objects (`.bss`/`.sbss`
  tentative defs), declare **high address → low address** because MWCC emits
  unreferenced tentative defs in reverse declaration order. If the consuming
  code's reference order cannot be changed, insert an **ordering function**
  instead.
- **`[missing]`** ("target object absent in current object") → if it's a pooled
  float/string literal, add an **ordering function** (`static void
  order_sdata2(void) { (void) 0.5f; (void) "obj"; … }`) that references each
  literal in target order — *not* a real named symbol. If it's a real constant,
  define it with its actual value (e.g. `Vec3 const x = { 0.0f, 100.0f, 0.0f };`).
- **`[split]`** ("split into N current objects") → **struct overlay**: declare
  one struct of the target size with any trailing padding as a **named field**
  (`struct { HSD_ImageDesc x0[2][2]; u8 x60[0xC]; }`), and reference sub-fields
  (`obj.x0[i][j]`). Replaces the `array + separate bss_pad` anti-pattern.
- **`[size-mismatch]`** ("size X vs target Y") → resize the type, or split a
  string / sub-object out of an over-large struct (the `leak.c` case, where
  strings modeled as struct members were actually separate `.data` literals).
- **`[anonymous]`** ("covered by anonymous symbol(s)") → give the data a named
  declaration matching the production symbol.
- **`--check-binding` mismatch** → flip `scope:global` → `scope:local` (and
  correct `data:4byte` → `data:float`/right type) in `symbols.txt` for
  anonymous compiler-pool constants, which have no external linkage.

## Technique catalog (embedded reference)

Each entry: *what / when / how / example-from-PR / pitfall.*

1. **Ordering function** — a `static void order_<section>(void)` whose body is
   `(void) <literal>;` statements, one per pooled constant, in target order.
   Pins MWCC's literal-pool emission order. *Example:* `order_sdata2` in
   `gmregenddisp.c`, `order_data` in `leak.c`. *Pitfall:* leaves a dummy
   function in `.text`; only safe in `NonMatching` TUs — mark it `/// @todo …
   order hack` and remove/replace it before the TU is code-matched. For floats
   use `(void) 0.5f;`; for strings `(void) "str";`.
2. **Struct overlay with named pad** — bundle an array and its trailing padding
   into one named struct so it emits as a single object of the target size.
   *Example:* `struct ImageDesc_Array` in `gmregtyfall.c`. *Pitfall:* reference
   via the named field, not the old symbol.
3. **Scope & type correction** — `symbols.txt` `scope`/`data` fixes for anonymous
   pool constants. *Example:* the `gm_804DAA00…` `.sdata2` block flipped
   `global`→`local`, `4byte`→`float` in #2739.
4. **Declaration reorder (tentative-def quirk)** — declare uninitialized globals
   high→low address. *Example:* the `gm_804D67xx` block in `gmregtyfall.c`.
5. **Define-the-const** — replace `extern` placeholders with real typed
   definitions carrying the actual values; move them to the correct file
   position. *Example:* `grPushOn_803B8440…` Vec3s and `light_configs` moved
   later in `grpushon.c`.
6. **Resize / split-string-out** — correct an over-modeled struct; pull
   inline-modeled strings back out into separate literals. *Example:*
   `HSD_LeakChecker` shrunk 0x208→0x20 in `leak.c`.
7. **TU split + section re-attribution** — see sub-flow below. *Example:*
   `gm_1A4C.c` → `gm_1A7A.c` + `gmregenddisp.c`.

Plus the supporting habit: replace numeric float literals with named macros
(`M_PI_F`, `M_TAU_F`, `M_PI_2`) so identical constants dedup consistently in the
pool (value-neutral, readability + stability). Add macros to `src/MSL/math.h`
when missing.

## TU-split sub-flow ("linking")

When a single source file actually corresponds to two or more original object
files (data pools merge and can never match otherwise):

1. Edit `config/GALE01/splits.txt`: replace the one TU block with two, splitting
   every section range (`.text`/`.data`/`.bss`/`.sdata`/`.sbss`/`.sdata2`) at the
   real boundary address.
2. Edit `configure.py`: replace the single `Object(NonMatching, "…")` with one
   entry per new TU.
3. Rename / duplicate the header; update `gm_unsplit.h` (or the module's unsplit
   aggregator) and `// IWYU pragma: export` lines.
4. Move functions, file-local statics, and data definitions into the correct new
   file. Shared inline helpers move to the shared header.
5. Re-attribute stray section bytes between adjacent TUs in `splits.txt` when an
   object's true owner is the neighbor (e.g. `.rodata 0x803B8740` moved
   itkyasarin→ittincle in #2736).
6. Re-audit each new TU and verify both build.

## Worked example (appendix in the skill)

The `gm_1A4C.c` → `gm_1A7A.c` + `gmregenddisp.c` split from #2739, taken from
merged-and-mismatched to audit-clean, so an agent can see one full end-to-end run
including the splits.txt/configure.py/header edits and the ordering functions.

## Verification & anti-claim discipline (baked into the skill)

- Verify against a **fresh upstream** before starting (avoid duplicating merged work).
- "Done" requires build-green **and** objdiff/`report.json` data match, not just audit-clean.
- Never propose accepting a sub-100% data result as "good enough"; never write that data is "unmatchable" / "below the source" / "no C lever" — the C provably exists. When levers are exhausted, the state is *suspended with the wall characterized and remaining levers named*, kept in the pool — not closed.
- Ordering functions are acknowledged `@todo` scaffolds; the skill states they must be removed/replaced before the TU is code-matched.

## Skill file structure

- `.claude/skills/data-match/SKILL.md` — frontmatter + the workflow, decision
  tree, technique catalog, TU-split sub-flow, worked example, and verification
  section. If the catalog + example make the file long, split the worked example
  and/or catalog into sibling reference files the SKILL.md links to (mirrors how
  larger skills are organized).

## Resolved judgment calls

- **Name:** `data-match` (chosen over `match-data` / `data-layout` / `link-tu`).
- **Ordering-function scaffolds:** permitted and documented as `@todo` hacks
  valid only in `NonMatching` TUs, rather than forbidden.
- **Verification strictness:** require build-green + objdiff data improvement, not
  audit-clean alone.

## Implementation notes

The deliverable is a markdown skill (no code). Validation of the skill itself:
(a) it triggers on a data-matching request and on `layout audit`-non-empty
situations; (b) a dry run on a known data-mismatched TU produces the right
lever per discrepancy class and reaches audit-clean + build-green. Follow the
repo's existing SKILL.md conventions (frontmatter `name`/`description`, imperative
workflow, `melee-agent capabilities search` audit-first reminder, tooling-issue
gate) as seen in `decomp` and `understand`.
