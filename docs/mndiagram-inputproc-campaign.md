# mnDiagram_InputProc Register-Allocation Campaign
## Methodology Record — 52-iteration study, 94.53 → 98.67

### Final State

- **Match: 98.67%** (opcode 99.4%, Δ1, hunks 6)
- Source commit: `7a17d3dc5`
- Function: `mnDiagram_InputProc` in `src/melee/mn/mndiagram.c`
- Starting point: 94.53% (post-decompilation baseline)

Remaining delta: one extra `li r25,0` (+048) — the fusion/zero-cluster wall (see §4).
Register residual: ~868 differing lines, all register-only.

---

## 1. Original Structure Recovered

m2c's decompilation was correct in control flow but missed several structural choices
the original compiler saw. The campaign recovered them in order:

**Find-walk inline helpers** (iterations 25-26, +1.72pp):
The nav arms' find loops are inlined helper functions in the original.
m2c expanded them into per-arm home writes. Restoring:
- `mnDiagram_FindPrevName` / `mnDiagram_FindNextName` — u8 return, `(u8) found` arg
  threads the return truncation through GetNameText's existing call idiom.
- `mnDiagram_FindPrevFighter` / `mnDiagram_FindNextFighter(sorted, cur)` — pointer-walk
  variants with `mn_IsFighterUnlocked(*p) == 0` loops.
- Helper return type and caller cast form matter: `s32` return + `found = (u8) helper()`
  caller cast produces target's clrlwi/mr pair at the merge site.
- Dedicated lf-arm Prev helpers with wrap-truncation (`return (u8) cur`) closed the
  lf-wrap family (iteration-41).

**0x10-arm cursor inlines** (iterations 27-29, +0.59pp deliberate substrate):
The nc/nr arms are `mnDiagram_GetVisibleNameFrom(sorted, (u8) cursor_pos, (u8) col)` calls.
Key: cast-at-arg not cast-on-local (raw local + cast at the arg site vs `(u8)col` glued to
the load produces different lhzu emission). fc/fr arms are NOT GetVisibleFighterFrom —
the soup shape matches the target (rotation difference would shorten the function).

**Buttons field shape** (iteration-38 theory, -39 commit, +0.67pp substrate):
`Menu_GetAllInputs()` inline bypassed in favor of the sibling idiom (mnmainrule.c:121 pattern):
```c
u32 input = mn_80229624(4);
((s32 *) &mn_804A04F0.buttons)[1] = input;
((s32 *) &mn_804A04F0.buttons)[0] = (count2 = 0);
```
This is the key structural move: it makes count2's home-init = the buttons-hi zero node,
which fires the fusion web and the M1 entry-deferral mechanism simultaneously.

**u64 store supplier temps** (iteration-41, +0.50pp):
With the field-shape in place, the entry trio (sorted/input/base) needed creation-order
control. The u64-form supplier temps naturally give input the correct creation slot.

**Cast restoration** (iterations 17-19, +0.50pp):
m2c dropped `(u8)` truncation casts. The original kept them at:
- `GetNameText((u8) found)` in find-result arms
- `found = (u8) found;` in hit branches
- `cur != (u8) found` compare sites in each nav arm variant

These casts correspond to `clrlwi` instructions in the target that the decompiler omitted.

**Variable web assignments** recovered across iterations 30-49 via the band model (§2):
count2 demotion, cur unmerge, B-pair decl order, role swaps, rider-move, dead anchors,
zero-arg and intermediate-copy lifts.

---

## 2. Allocator Model

MWCC GC/1.2.5n uses a SIMPLIFY-based graph-coloring allocator with these measured rules:

**Band ordering (the dominant lever):**
Locals number in REVERSE declaration order (~r33-56). Temps number in first-use/emission
order (~r57-110). IRO-exit promotion temps start at r111+, numbered by variable first-use
(earliest first-use = lowest @-number = HIGHEST ig-index = pops EARLIEST in descending sweeps).

Within a promoted variable: regions number in REVERSE node order (latest region = highest
ig in the band = pops first).

The promotion pass fires on loop-CARRIED variables (counter++, i++, found--) with multiple
disjoint live regions. Loop outputs (col_result*, row_result*) are never promoted.

*Evidence: /tmp/retro23, /tmp/retro51input; freshly measured at each substrate change.*

**Pop order (finishing sweep):**
SIMPLIFY runs ascending-index sweeps over eligible nodes (degree < k=29), pushing onto the
stack; pops reverse. Front members pop first. Pop order within a sweep = DESCENDING ig-index.

The key pop-order rule: IRO @-temps (ig >= 111) outrank every home local by number, so
count2-as-home (last-declared) pops 9th in the front group while count2-as-@-temp pops 5th.
The full front sequence (current graph) = `58, 175, 180, 177, 106(megaweb), 41, 39, 38, 37, 32`.

**Pick rule (per-pop register assignment):**
Volatiles first (low), then reuse dispensed callee-saves ascending from lowest, then fresh
descending (r31 → r30 → ...). The zero-web's fresh dispense anchors the pool: every pop
after it reuses r23 ascending unless blocked by a same-arm simultaneous live range.

**Coalesce:**
Same-value coalescing follows copy edges (backend COALESCE map). A copy edge exists only
if both operands are temp-class; home-class virtuals are excluded. The canonical-zero
channel: the first li in entry B4 (the buttons-hi store-unit zero, r183) picks up all
downstream literal-zero clients via `mr r102,r183` etc. Count2's zero-init `li r35,0`
is a separate node; its range overlaps r183's, blocking same-value merge.

---

## 3. Lever-Class Catalogue

Each class is stated with a one-line evidence pointer and its limits.

**Band-lift (dead-anchor placement):**
`var = <any-live-value>;` on a path-disjoint, provably-dead branch is DCE'd (zero
instructions emitted) but anchors the variable's FIRST-USE position for the promotion's
band ordering. Proven: count's dead decl-init (iter-34 D-NEW-1), ptr3's 0xC00-branch
anchor (iter-36 dn_f ring). Limit: statement-temp webs (no variable identity) are
unreachable; the dead value must be live at that point to avoid DCE of the branch itself.

**Safe-zone law (entry-region lifts):**
Copy-propagated entry lifts are safe when the lifted value is propagated to an immediate
at the use site (no live range across the front sweep). Examples: `i = 0; SetupProc(..., i)`
(iter-48, +0.17pp), `cur = 1; audio(cur)` (iter-49, +0.01pp). Unsafe: nav-arm-tail lifts
are dead-store eliminated before they mint a band (iter-49 B/C inert).

**Copy-propagated immediate lift (head-window law):**
The head-window usable region = pre-front statements with downstream temp regions.
Once a literal is lifted and copy-propped into an immediate at the call, no live range
exists across the front and the band shift is free. Window is site-specific and can be
exhausted once all head-window literals are lifted.

**Intermediate-copy persistence law:**
`row5 = call; found = row5;` — if row5 has its own web elsewhere (via prior uses), the
copy persists and renumbers downstream temps. Unlike `found2 = call; found = found2;` (fresh
temp, copy-propagated, byte-identical) or tail-position dead-stores (DCE'd). Site-specific:
dn_f fired at commit `7a17d3dc5`; rt_f/dn_n siblings inert on the current graph.

**Operand-flip (comparison form):**
`if (0 < row3)` vs `if (row3 > 0)` produces different instruction selection in some
contexts. Evidence: iter-45 +0.25pp (`row3 > 0` → `0 < row3` in the 0xC00-fighter arm).
Pattern: leading operand affects the emitted branch form; grep for mismatched cmpi/cmpwi
one-operand forms vs target.

**Dead-anchor + band placement (rider-move):**
Moving which variable "rides" the zero-web dispense: having count walk the fighter-count
loop (iter-34, D-NEW-1) moved the zero dispense to count's band, freeing r23 for all
post-dispense nav walkers. Evidence: census 103→90 post-commit.

**Web-split / merge (per-region split):**
Splitting m2c-merged locals (col_result/row_result/steps/row — iterations 3-12) snaps
web extents to target values when the original had per-region variables. Gate: opcode
similarity must hold (col_result/row_result/steps/row PASS; found/cur/col/i/ptr/ptr2 FAIL
because the original shared them — they are body-relevant merges). The gate is mandatory:
body-gate failures indicate the original shared the variable, not split it.

---

## 4. Wall Statements (final form, per never-claim rule)

**Fusion/zero-cluster wall (~11 CS sites + Δ1):**
Ours mints two zero IR nodes in entry B4 (conversion-hi r183 + count2-home r35); the
original had one (count2's home-init = the buttons-hi zero node directly). Every downstream
literal-zero client coalesces to r183 (canonical-zero channel), not r35; count2 appears
nowhere in the COALESCE map. The triple requirement for a single zero node: (a) opaque to
front-end const-prop, (b) register-class (no stack home), (c) materializes as li not load.
Spellings tried across pairwise combinations: union local (a)+(c), fails (b) via stack home;
read-back (a)+(b), fails (c) via lwz; literal inits, fail (a); u64>>32, fails as __shr2u
library call; halves-stores, IRO const-props. Not found with all 8 spelling classes tried.
Mechanism: ours has no opaque-to-front-end, register-class zero path that doesn't either
stack-home (aggregates) or IRO-normalize (scalars). The sibling function mnCount_HandleUserInput
(matched 100%) uses a named `long long x` holder — opaque at the IR level, but aggregates
stack-home in MWCC.

**lhzu/fr-ring wall (~15-20 CS sites + Δ1 structural):**
Target emits `lhzu r3,2(r29)` at +168 (load hovered_selection with r29 pre-incremented
from &mn_804A04F0). Our r29 is clobbered by the lf_n ptr walk at +180; any pointer-walk
spelling reduces our instruction count below the target (ours 784 → 783 with lhzu, target
785), widening Δ1 → Δ2. The fusion fires (iter-27 confirmed lhzu reachable at +90 with the
right r29 life), but the target's lhzu site (+168, fc arm) requires r29 to be dead after it —
a register-life condition not reachable from the current r29 allocation without instruction-
count cost. Not found with pointer-walk, field-type, or IRO analyses; Δ arithmetic blocks it.

**found↔row2 temp-band cycle (~12 CS sites):**
The dn_n/rt_n/dn_f/rt_f found-merge webs are statement-temp-banded (pop ~iter 305, before
every variable band and the r23 dispense). Target has them in the found variable band (after
steps/walker/anchor). The cycle requires the found-merge web to gain a variable identity —
the s32-return + caller-cast refactors measured worse in iterations 25-26. 28,812 variants
enumerated across 4 consecutive graphs (arrangement/arg-shape/derivation spellings for all 5
nav regions); zero sub-base candidates. Not found; exhaustive within these axes.

**nc anchor transposition (~6 CS sites):**
The +094 `addi r28-vs-r27` site is a temp-class web (no variable identity). Dead-anchor
tool cannot reach statement-temp webs. Permuter-random territory only; no manual lever found
across sessions 46-52.

**nr-head load-order (+0f4, ~2 CS sites):**
Volatile-pick positional site; characterized iteration-35, no C lever found in 3 sessions.

---

## 5. Process Doctrine

**Gates before any build:**
Body gate enforced throughout: opcode similarity ≥ threshold, line Δ ≤ threshold, hunks ≤
threshold, match ≥ current. Any edit that fails the gate is reverted before proceeding.
Body similarity (opcode metric) is the primary gate — register sites inflate line-count
comparisons; use skeleton aligner for confident region-level census.

**Substrate relativity:**
After each committed graph change, previously-proven walls get one cheap re-test before
being relied upon. Cost-benefit verdicts can invert on a new substrate (iter-30:
count2-home cracked on recipe graph after failing on old graph). The lever that cracks a
wall may be free on the new substrate even if all its individual mechanism classes were
measured dead before.

**Probe hygiene (r14-r17 rule):**
Fingerprint webs with r14-r17 forces ONLY (unused low regs, no pool conflicts). Pool-register
forces (e.g. 118:25) perturb coalescing and produce false split readings — a force-phys to
r25 blocked coalesce of a different web, making iteration-21 see a phantom two-web split that
was actually one web. r14-r17 forces are diagnostic-only and must not be committed.

**Permuter triage discipline:**
- Always run the full-file diff, not just the main-body diff — helper/preamble changes
  (inline_fn wrappers, dropped pragmas, static→inline changes) hide in the preamble.
- Score ≠ match% proximity; a score-improvement candidate may gate-fail (extra instruction,
  structure regression). Meter every candidate at gate boundaries before committing.
- Stale-base doctrine: after each commit, stop all channels, re-bootstrap base.c (the
  bootstrap ALWAYS drops the NULL pragma — add `#pragma _permuter define NULL 0` at line 2,
  verify locally before submitting). Submit fresh jobs with the new base score.
- Pre-classified family inventory (this campaign's 6): F1=row-split-0x10, F2=inline_fn,
  F3=type-change, F4=row-split-unsafe-zone, F5=entry-band-addition, F6=arithmetic/dead/comma.
  Tally, don't re-derive. Meter only if no family token and no net instruction insertion.

**Oracle-before-search:**
Before spending source-edit budget on a lever class, use force-phys (r14-r17) to verify the
web's composition, and use forced-front probes to bound the order channel's value on the
current graph. The same-compiler unforced object is the baseline for forced-debug comparisons
(not the retail ninja build; retail reads ~5pp higher than debug on this function).

**Macro enumeration doctrine:**
Finite arrangement/arg-shape/derivation enumerations are definitive once complete. Do not
re-run on a graph unless a commit changes the CONTROL FLOW of the enumerated region (not
just bands or substitution spellings). For this campaign: 28,812 variants / 4 graphs /
0 wins on the found↔row2 cycle — exhaustive.

**Listening-post cadence (post-campaign):**
The tuned coder1 channel (`mnDiagram_InputProc_tuned-coder1-20260611-065847`, cast/expand/
type weights, 16t) is the listening post. Harvest at low cadence. Gate ≥98.67 (Δ1, hunks 6,
opcode 99.4). No new triage class anticipated; stop if 150k+ iterations without a non-family
candidate. Reopen conditions: see §6.

---

## Iteration Ledger (match progression)

```
94.53 → 94.6   init count at decl
94.6  → 94.7   split col/row_result + reorder decls (nav webs snapped)
94.7  → 95.0   restore (u8) found casts in up_n/dn_n/up_f/dn_f
95.0  → 95.2   restore (u8) compare casts in lf_f/rt_f + up_n/dn_n/rt_n
95.2  → 95.4   hoist entering_menu=0 before Diagram* load (stb order)
95.4  → 96.60  find-walk inline helpers, name arms (FindPrevName/FindNextName)
96.60 → 97.02  find-walk inline helpers, fighter arms (FindPrevFighter/FindNextFighter)
97.02 → 97.08  FindNextFighter decl order
97.08 → 97.75  prev-helper merge casts + steps-walk ptr split
97.75 → 97.16  [deliberate substrate: nc/nr GetVisibleNameFrom restoration]
97.16 → 97.28  count2 home demotion + B-pair decl order
97.28 → 97.30  merge nav cur into walk index i
97.30 → 97.43  ptr/ptr2 role swap in name-arm steps walks
97.43 → 97.55  walk fighter count loop with count (rider-move)
97.55 → 97.58  merge nav steps into row2
97.58 → 97.68  FindPrevFighter p-decl-first
97.68 → 97.74  ptr3 dead band anchor (dn_f ring)
97.74 → 96.70  [field-shape buttons stores, substrate migration]
96.70 → 96.87  dedicated cur walker for nav arms
96.87 → 97.37  u64 buttons store fires M1 entry deferral
97.37 → 97.49  dedicated lf-arm Prev helpers (wrap truncation)
97.49 → 97.93  pass nc col through cur (walker band-lift)
97.93 → 98.18  comparison form flip (0 < row3)
98.18 → 98.45  0xC00-fighter clamp count band-lift
98.45 → 98.62  zero-arg web lift in 0x10 arm (i=0 SetupProc arg)
98.62 → 98.63  second head-window immediate lift (cur=1 audio arg)
98.63 → 98.67  dn_f found via row5 intermediate-copy
```
