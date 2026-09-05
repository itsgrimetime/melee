# data-match Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author a `data-match` Claude Code skill that drives an agent through matching the data sections of a Melee TU, wrapping `melee-agent layout audit`.

**Architecture:** A pure markdown skill at `.claude/skills/data-match/`. `SKILL.md` holds the trigger frontmatter, when-to-use, the workflow loop, the audit-class decision tree (the spine), and verification/anti-claim discipline. Two reference files hold the detail: `references/techniques.md` (the 7-lever catalog) and `references/tu-split.md` (the TU-split sub-flow + the `gm_1A4C` worked example). No code, no new CLI.

**Tech Stack:** Markdown only. Verification uses `melee-agent layout audit`, `python configure.py && ninja`, `grep`, and a live dry-run on a flagged TU.

**Source of content:** The approved spec at `docs/superpowers/specs/2026-06-18-data-match-skill-design.md`. Prose may be adapted from named spec sections; this plan inlines the structured, must-have elements (decision-tree rows, commands, technique list) so tasks are self-contained.

**Deviation from skill defaults (intentional):** Not run in a dedicated worktree. The deliverable only adds files under `.claude/skills/` and `docs/`; it touches no build state and races no other agent. Authored directly on `master`, matching where the spec was committed (`b54cf504b`). "Tests" are doc-appropriate (structural lint + a functional dry-run) rather than unit tests, because the artifact is prose.

---

### Task 1: Scaffold skill directory, frontmatter, and section skeleton

**Files:**
- Create: `.claude/skills/data-match/SKILL.md`
- Create: `.claude/skills/data-match/references/techniques.md`
- Create: `.claude/skills/data-match/references/tu-split.md`

- [ ] **Step 1: Create `SKILL.md` with frontmatter and empty section headers**

Write this exact content:

```markdown
---
name: data-match
description: Use when matching the data sections (.data/.rodata/.sdata/.sdata2/.bss/.sbss) of a Melee TU — fixing data ordering, symbol scope, split/anonymous/missing objects, sizes, and translation-unit boundaries — after code matches or whenever `layout audit` reports discrepancies.
---

# Melee Data-Section Matching

## When to Use This Skill

## Before You Start (audit-first + preconditions)

## The Core Loop

## Decision Tree: layout audit class → lever

## Verification & "Done"

## Never Do This (anti-claims)

## References
```

- [ ] **Step 2: Create the two reference stubs**

`references/techniques.md`:

```markdown
# data-match: technique catalog

(One entry per lever: what / when / how / example / pitfall.)
```

`references/tu-split.md`:

```markdown
# data-match: splitting a merged TU + worked example
```

- [ ] **Step 3: Verify the skill is discovered and frontmatter parses**

Run: `head -3 .claude/skills/data-match/SKILL.md`
Expected: shows `---`, `name: data-match`, and the `description:` line.

Run: `ls .claude/skills/data-match .claude/skills/data-match/references`
Expected: `SKILL.md`, `references/`, `techniques.md`, `tu-split.md` all present.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/data-match/
git commit -m "data-match skill: scaffold dir, frontmatter, section skeleton"
```

---

### Task 2: Write "When to Use" and "Before You Start"

**Files:**
- Modify: `.claude/skills/data-match/SKILL.md`

- [ ] **Step 1: Fill the "When to Use This Skill" section**

Content (adapt from spec "Entry states"). Must state the three entry states and the contrast with `/decomp`:

```markdown
## When to Use This Skill

Use `/data-match <file-or-module>` when the **data** sections of a TU mismatch,
even though the code may already match. Three entry states:

1. A TU's code/text matches but its `.data`/`.rodata`/`.sdata`/`.sdata2`/`.bss`/`.sbss` still mismatch.
2. A single source file actually corresponds to two or more original object files and must be split.
3. Any time `melee-agent layout audit <file>` is non-empty.

Use `/decomp` instead for instruction-stream / register / scheduling work. This
skill never touches register allocation — it fixes *data layout*: ordering,
scope, object boundaries, sizes, and TU ownership.
```

- [ ] **Step 2: Fill the "Before You Start" section**

```markdown
## Before You Start (audit-first + preconditions)

- **Audit-first rule.** Before building any helper, run `melee-agent capabilities search <task>`.
- Run `python tools/worktree-doctor.py --fix`; treat stale `report.json`/objects/DOL warnings as blockers.
- Verify the data isn't already matched upstream: `git fetch upstream` then check the file on `upstream/master`. Do not duplicate merged work.
- Capture a baseline: save `melee-agent layout audit <file> --check-binding` output and the object's current match in `report.json`.
```

- [ ] **Step 3: Verify required elements present**

Run: `grep -c "layout audit\|worktree-doctor\|capabilities search\|upstream" .claude/skills/data-match/SKILL.md`
Expected: `4` or more.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/data-match/SKILL.md
git commit -m "data-match skill: when-to-use and preconditions"
```

---

### Task 3: Write "The Core Loop"

**Files:**
- Modify: `.claude/skills/data-match/SKILL.md`

- [ ] **Step 1: Fill the "The Core Loop" section**

```markdown
## The Core Loop

1. **Diagnose** — `melee-agent layout audit <file> --check-binding [--json]`. Record every discrepancy.
2. **Triage** — map each discrepancy through the Decision Tree below to a lever.
3. **Apply** — make the source / `config/GALE01/symbols.txt` / `config/GALE01/splits.txt` / `configure.py` edit for that lever (see `references/techniques.md`).
4. **Re-audit + verify** — re-run `layout audit` (it should shrink toward empty); keep `python configure.py && ninja` green; confirm the object's data match improved in `report.json`.
5. **Repeat** 1–4 until the "Done" criteria are met.
6. **Record / stop** — `melee-agent attempts record <fn> --match <pct> --outcome <...>` for meaningful steps. On a genuine reverse-engineering blocker, file `melee-agent issue report ...` and document what is known. See "Never Do This".
```

- [ ] **Step 2: Verify**

Run: `grep -c "layout audit\|symbols.txt\|splits.txt\|attempts record\|issue report" .claude/skills/data-match/SKILL.md`
Expected: `5` or more.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/data-match/SKILL.md
git commit -m "data-match skill: core loop"
```

---

### Task 4: Write the Decision Tree (the spine)

**Files:**
- Modify: `.claude/skills/data-match/SKILL.md`

- [ ] **Step 1: Fill the "Decision Tree" section**

Must include all six branches with the omitted nuance (from spec "Decision tree"):

```markdown
## Decision Tree: layout audit class → lever

`layout audit` emits a closed vocabulary. For each reported class:

- **`[reorder]`** ("at offset X (target Y)") → reorder declarations to target
  address order. **Nuance:** for *uninitialized* objects (`.bss`/`.sbss`
  tentative defs) declare **high address → low address** — MWCC emits
  unreferenced tentative defs in reverse declaration order. If the consuming
  code's reference order can't change, use an **ordering function** instead.
- **`[missing]`** ("target object absent") → pooled float/string literal: add an
  **ordering function** (see techniques), *not* a real symbol. Real constant:
  define it with its value (e.g. `Vec3 const x = { 0.0f, 100.0f, 0.0f };`).
- **`[split]`** ("split into N current objects") → **struct overlay**: one struct
  of the target size with trailing padding as a **named field**; reference
  sub-fields (`obj.x0[i][j]`).
- **`[size-mismatch]`** ("size X vs target Y") → resize the type, or split a
  string / sub-object out of an over-large struct.
- **`[anonymous]`** ("covered by anonymous symbol(s)") → give the data a named
  declaration matching the production symbol.
- **`--check-binding` mismatch** → in `symbols.txt`, flip `scope:global` →
  `scope:local` and fix `data:4byte` → the real type (`data:float`) for
  anonymous compiler-pool constants (no external linkage).

Full how-to for each lever: `references/techniques.md`.
```

- [ ] **Step 2: Verify all six classes are covered**

Run:
```bash
for c in '\[reorder\]' '\[missing\]' '\[split\]' '\[size-mismatch\]' '\[anonymous\]' 'check-binding'; do
  grep -q "$c" .claude/skills/data-match/SKILL.md && echo "$c ok" || echo "$c MISSING"
done
```
Expected: six `ok` lines, no `MISSING`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/data-match/SKILL.md
git commit -m "data-match skill: audit-class decision tree"
```

---

### Task 5: Write the technique catalog (`references/techniques.md`)

**Files:**
- Modify: `.claude/skills/data-match/references/techniques.md`

- [ ] **Step 1: Write all seven lever entries + the macro habit**

Each entry follows *what / when / how / example / pitfall*. Use the spec
"Technique catalog" section as the content source. The seven headings MUST be:

```markdown
## 1. Ordering function
## 2. Struct overlay with named pad
## 3. Scope & type correction (symbols.txt)
## 4. Declaration reorder (tentative-def quirk)
## 5. Define-the-const
## 6. Resize / split-string-out
## 7. TU split + section re-attribution
## Supporting habit: named float macros
```

For entry 1, include this exact pattern and pitfall text:

```markdown
A `static void order_<section>(void)` whose body is `(void) <literal>;`
statements, one per pooled constant, in target order — pinning MWCC's
literal-pool emission order. Floats: `(void) 0.5f;`. Strings: `(void) "obj";`.
Example: `order_sdata2` in `gmregenddisp.c`; `order_data` in `leak.c`.
**Pitfall:** leaves a dummy function in `.text`; valid only in `NonMatching`
TUs. Mark it `/// @todo .sdata order hack` and remove/replace it before the TU
is code-matched.
```

For entry 2 include the concrete shape `struct { HSD_ImageDesc x0[2][2]; u8 x60[0xC]; }` (example: `ImageDesc_Array` in `gmregtyfall.c`).
For entry 3 cite the `gm_804DAA00…` `.sdata2` global→local + 4byte→float flip (#2739).
For entry 6 cite `HSD_LeakChecker` shrinking 0x208→0x20 (#2738).
For the macro habit cite `M_PI_F`/`M_TAU_F`/`M_PI_2` and adding macros to `src/MSL/math.h`.

- [ ] **Step 2: Verify the seven levers + macro habit are all present**

Run: `grep -cE '^## ' .claude/skills/data-match/references/techniques.md`
Expected: `8` (seven levers + the supporting-habit heading).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/data-match/references/techniques.md
git commit -m "data-match skill: technique catalog"
```

---

### Task 6: Write the TU-split sub-flow + worked example (`references/tu-split.md`)

**Files:**
- Modify: `.claude/skills/data-match/references/tu-split.md`

- [ ] **Step 1: Write the six-step sub-flow**

Use the spec "TU-split sub-flow" section. The six numbered steps MUST be: (1)
`splits.txt` section ranges split at the boundary address; (2) `configure.py`
one `Object(NonMatching, ...)` per new TU; (3) header rename/duplicate + update
the module unsplit aggregator (e.g. `gm_unsplit.h`) and `// IWYU pragma: export`
lines; (4) move functions, file-local statics, and data into the right file
(shared inlines to the shared header); (5) re-attribute stray section bytes
between adjacent TUs (e.g. `.rodata 0x803B8740` moved itkyasarin→ittincle in
#2736); (6) re-audit and build both.

- [ ] **Step 2: Write the worked example**

Document the `gm_1A4C.c` → `gm_1A7A.c` + `gmregenddisp.c` split from #2739:
the `splits.txt` block becoming two (with the `0x801A7FB4` text boundary and the
`.data`/`.sdata`/`.sbss`/`.sdata2` splits), the `configure.py` two-line change,
the `gm_1A4C.h` → `gm_1A7A.h` rename, moving `gm_801A7B00` and the
`fn_801A7FB4_inline` helpers, and the `gm_unsplit.h` include swap — ending at
audit-clean on both new TUs.

- [ ] **Step 3: Verify**

Run: `grep -c "splits.txt\|configure.py\|gm_unsplit\|gm_1A7A\|gmregenddisp\|IWYU" .claude/skills/data-match/references/tu-split.md`
Expected: `5` or more.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/data-match/references/tu-split.md
git commit -m "data-match skill: TU-split sub-flow and worked example"
```

---

### Task 7: Write "Verification & Done" and "Never Do This", wire References

**Files:**
- Modify: `.claude/skills/data-match/SKILL.md`

- [ ] **Step 1: Fill "Verification & Done"**

```markdown
## Verification & "Done"

Done = ALL THREE:
1. `melee-agent layout audit <file> --check-binding` returns clean, AND
2. `python configure.py && ninja` builds green, AND
3. The TU's data sections reach 100% in `report.json` (per-object fuzzy match);
   use `tools/checkdiff.py` for the TU's functions.

**Necessary but not sufficient:** an empty `layout audit` proves the *shape,
order, scope, and naming* are right — NOT the byte *values*. The
`report.json`/objdiff data comparison in (3) is the real done signal. Never
stop at audit-clean alone.
```

- [ ] **Step 2: Fill "Never Do This"**

```markdown
## Never Do This (anti-claims)

- Never propose accepting a sub-100% data result as "good enough" / "a realistic ceiling".
- Never write that data is "unmatchable", "below the source", or "has no C lever" — it compiled from C, so the source provably exists.
- When levers are exhausted, the state is SUSPENDED: characterize the wall, name the ruled-out and remaining levers, keep the TU in the pool. Do not close it.
- Ordering functions are `@todo` scaffolds — remove/replace before a TU is code-matched.
```

- [ ] **Step 3: Fill "References" links**

```markdown
## References

- `references/techniques.md` — the 7 levers in detail (what/when/how/example/pitfall).
- `references/tu-split.md` — splitting a merged TU + the `gm_1A4C` worked example.
```

- [ ] **Step 4: Verify links resolve**

Run:
```bash
cd .claude/skills/data-match && for f in references/techniques.md references/tu-split.md; do test -f "$f" && echo "$f ok" || echo "$f MISSING"; done; cd - >/dev/null
```
Expected: two `ok` lines.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/data-match/SKILL.md
git commit -m "data-match skill: verification, anti-claims, references"
```

---

### Task 8: Lint pass — placeholders, frontmatter, links

**Files:**
- (No file changes unless lint finds issues)

- [ ] **Step 1: Placeholder lint (excluding the legitimate `@todo` technique term)**

Run:
```bash
grep -rnE 'TBD|FIXME|XXX|fill in|implement later|<placeholder>' .claude/skills/data-match/ || echo "clean"
```
Expected: `clean`. (Note: `@todo`/`TODO` is intentionally allowed — it is the name of the ordering-hack marker.)

- [ ] **Step 2: Frontmatter sanity**

Run: `awk 'NR==1{print} /^name:/{print} /^description:/{print}' .claude/skills/data-match/SKILL.md`
Expected: a `---` line, a `name: data-match` line, and the `description:` line.

- [ ] **Step 3: If lint finds issues, fix inline and re-run until clean, then commit**

```bash
git add -A .claude/skills/data-match/
git commit -m "data-match skill: lint fixes" || echo "nothing to fix"
```

---

### Task 9: Functional dry-run on a flagged TU

**Files:**
- (No skill changes unless the dry-run reveals a wrong/missing branch)

- [ ] **Step 1: Pick a TU that `layout audit` currently flags**

Run: `melee-agent layout audit src/melee/gr/grpushon.c --check-binding`
Expected: non-empty output exercising `[anonymous]`, `[size-mismatch]`, `[split]`, `[reorder]`, and `[missing]`.
If `grpushon.c` is already matched (e.g. upstream was pulled), pick another data-heavy flagged TU — e.g. try `src/melee/gm/gmregtyfall.c` or scan a few with `melee-agent layout audit`.

- [ ] **Step 2: Walk each reported discrepancy through the SKILL.md decision tree**

For every line in the audit output, confirm the skill's decision tree names the
correct lever and the nuance applies (e.g. a `.sbss` `[reorder]` → "declare
high→low"; a `[missing]` float → ordering function). Write down any class the
tree fails to map.
Expected: every discrepancy maps to exactly one lever with no gaps.

- [ ] **Step 3: Apply ONE lever end-to-end to prove the loop**

Pick the easiest discrepancy (usually an `[anonymous]` → named declaration or a
`--check-binding` scope flip). Apply it per the skill, then:

Run: `melee-agent layout audit src/melee/gr/grpushon.c --check-binding`
Expected: that one discrepancy is gone (audit shorter).

Run: `python configure.py && ninja`
Expected: build succeeds.

Then revert the experimental edit (it's a skill smoke-test, not a real match):
```bash
git checkout -- src/melee/gr/grpushon.c config/GALE01/symbols.txt
```

- [ ] **Step 4: If the tree had a gap, fix SKILL.md and commit**

```bash
git add .claude/skills/data-match/SKILL.md
git commit -m "data-match skill: decision-tree fix from dry-run" || echo "no gap found"
```

---

### Task 10: Register in capabilities and final review

**Files:**
- Modify: capabilities brief (auto-generated)

- [ ] **Step 1: Regenerate the capabilities brief so `capabilities search` knows the skill**

Run: `melee-agent capabilities generate`
Then: `melee-agent capabilities search "data section matching"`
Expected: `data-match` appears in the results.

- [ ] **Step 2: (Optional) skill-reviewer pass**

Dispatch the `plugin-dev:skill-reviewer` agent on `.claude/skills/data-match/SKILL.md` for a description/triggering quality check. Apply any high-value suggestions inline.

- [ ] **Step 3: Final commit**

```bash
git add -A .claude/skills/data-match/ && git add -A docs/ 2>/dev/null
git commit -m "data-match skill: regenerate capabilities brief" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:**
- Skill identity / frontmatter → Task 1. ✓
- Entry states + when-to-use → Task 2. ✓
- Core loop (6 steps) → Task 3. ✓
- Decision tree (6 classes + nuance) → Task 4. ✓
- Technique catalog (7 levers + macro habit) → Task 5. ✓
- TU-split sub-flow + worked example → Task 6. ✓
- Verification (3-part done + audit-not-sufficient nuance) + anti-claims → Task 7. ✓
- Out-of-scope/no-new-tooling → enforced by the plan shape (no code tasks). ✓
- Discoverability → Task 10. ✓

**Placeholder scan:** No TBD/FIXME in the plan itself. The plan deliberately allows `@todo` inside the skill (technique name) and the lint in Task 8 excludes it. ✓

**Type/name consistency:** Skill name `data-match`, dir `.claude/skills/data-match/`, files `references/techniques.md` and `references/tu-split.md`, and the six audit-class tokens (`[reorder]`/`[missing]`/`[split]`/`[size-mismatch]`/`[anonymous]`/`--check-binding`) are used identically across Tasks 1–9. ✓
