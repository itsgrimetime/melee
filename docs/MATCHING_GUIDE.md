# Byte-Matching Decompilation with MWCC: A Field Guide

Distilled from ~2 months of daily work on the SSBM (GALE01) decompilation, plus
compiler reverse-engineering of `mwcceppc.exe` itself. Everything here was
*measured* — compiled, scored, and in most cases validated against a captured
snapshot of the compiler's internal state. Negative results are included
deliberately; they are most of the value.

**Scope.** Metrowerks CodeWarrior for GameCube, `mwcceppc` **1.2.5 / 1.2.5n**,
flags `-O4,p -proc gekko -fp hardware -enum int -inline auto`. Much of the
*method* generalises to any decomp; the specific laws are MWCC-1.2.x. Where a
claim is compiler-version-specific it says so.

---

## 0. The one-paragraph version

A byte-match is decided by five independent compiler stages, and a residual
belongs to exactly one of them. In rough order of how often they bite:
**register allocation** (which web gets which register), **stack frame layout**
(which objects get homes and in what order), **instruction scheduling**,
**emission/peephole**, and **data-section layout** (literal pools, `.bss`/`.sdata`
ordering, TU boundaries). Almost every hour lost was lost by sweeping source
spellings against the wrong stage. Classify first, then pick the lever that acts
on *that* stage. And measure the compiler's decision — homes, web numbers,
select order — not the match percentage, which is a lagging and non-monotonic
indicator.

---

## 1. Measurement discipline (read this before anything else)

Every single one of these cost real hours at least once.

1. **Score with a proper differ, never an eyeballed line diff.** Alignment
   shifts and relocation-name noise routinely *invert* the ranking of two
   candidates. A 219-row line diff scored 95.6% while a 172-row one scored
   93.7%.
2. **Reproduce the project's own scoring options.** A plain two-object diff
   compares *relocation names*, so anonymous literal-pool symbols (`@307`) vs
   split-era invented names (`lbl_803F9798`) read as mismatches. Locally that
   looks like 99.5–99.95% for a function that upstream counts as matched. Use
   the CI's option (for objdiff: `-c functionRelocDiffs=data_value`).
3. **A row is naming noise** iff the two instructions are identical after
   replacing the whole symbol in `SYM@ha|@l|@sda21` with a placeholder. That
   includes named float constants vs pooled literals. Branch-target operands
   differ whenever the function sits at a different offset — also noise.
4. **The percentage can DROP when the code gets closer.** Fixing one wrong
   instruction changed the diff alignment and moved 98.85% → 97.85%. Trust
   normalised row counts and known-correct instructions when shipping.
5. **Harnesses must fail loudly.** Two separate sessions were poisoned by a
   compile-and-score script that piped the compiler log through a filter,
   swallowed an error, and re-scored the **stale** `.o`. Delete the object
   before each compile, assert it re-exists, and grep the log for errors. A
   "perfectly score-neutral" result is the classic symptom.
6. **Compile in the real TU.** TU context changes register allocation. An
   online scratch (function + context header) can be permanently stuck on a
   rotation that vanishes in the real `.c` — and vice versa.
7. **Match the build's defines.** Missing `-DMUST_MATCH` made assertion macros
   fall back to `__LINE__`, so every `__assert("jobj.h", N, …)` emitted our
   header's physical line instead of retail's. Small score effect, large
   evidence effect.
8. **Bound your sweep edits to the function.** A global `str.replace` of
   `PAD_STACK(0x10);` silently damaged two other functions in the same file
   while the score output was filtered to three. Anchor replacements, and run
   an unfiltered score before committing.
9. **Score the *whole* object, always.** Never grep the sub-100 list for the
   functions you touched — a header or inline change perturbs functions you
   did not look at.
10. **Verify refactors by byte-comparing objects, not by score.** Snapshot the
    `.o`s, apply the change, recompile, compare. Acceptable residual: anonymous
    literal renumbering only.
11. **A 100% object report is not a linked-checksum proof.** Duplicate data and
    reordered BSS can survive the body/data comparison yet move symbols in the
    linked image. Set the TU to Matching and verify the original DOL checksum;
    use `dtk dol diff` and `dtk elf info` to diagnose address/layout failures.
    See the [mnitemsw case study](mnitemsw-matching-notes.md).

---

## 2. Classify the residual before you touch the source

The single highest-leverage habit. Build an instruction-**shape** census:
normalise away register numbers, branch targets **and every symbol name**, then
diff the shape histograms of target vs candidate.

| shape delta | meaning | which stage |
|---|---|---|
| 0 | pure register colouring | allocator |
| 0, but every stack displacement off by a constant | frame size/home count | frame |
| small, `mr`/`addi` inserts and deletes | copy/coalescing or param-home structure | allocator/lowering |
| two instructions transposed, same operands | scheduling tie | scheduler |
| different opcodes/immediates | genuinely wrong source | you |
| `...data.0` vs a named symbol | data anchoring / TU boundary | data |

Corollaries:

- **Uniform per-region offset delta** ⇒ intra-region order is right, you are
  moving gaps. **Mixed-sign deltas** ⇒ order is still wrong.
- **Clear structural rows before touching a rotation.** Two of ninety rows
  gated everything else in one case.
- `mr rX,r3` after a call = a compiler-generated **param home** (the original
  had no local copy — type the parameter). `addi rX,r3,0` = a **user copy**.
- `addi rX,rX,STRIDE` in a loop = a strength-reduced IV (a compiler temp — no
  nameable owner).
- Two adjacent stack arrays walked by one pointer with two displacements = one
  **aggregate** in the original.
- A repeated reload-then-store pattern = repeated *full field mentions* in the
  source (caching the field in a local kills the reloads and the match).

---

## 3. The register allocator, decoded

This is where most residuals live, and it turned out to be fully modellable.
The model below was validated against snapshots of the compiler's own coloring
state (see §9) on dozens of functions, exactly.

### 3.1 The algorithm

- **Simplify** (`Coloring_SimplifyGraph`): repeated **ascending-vreg** scans,
  removing any node whose *dynamic* degree < K; neighbours are decremented
  immediately, within the same scan; removed nodes are pushed on a LIFO stack.
  **K = 29 for GPRs, 32 for FPRs.**
- If nothing is removable it **jams**: remove the node with minimum
  `spill_cost / degree` (costs stay 0 unless a jam happened, so all-zero costs
  in a snapshot proves no jam).
- **Select order = reverse of removal order.** So the node that survives
  *longest* is selected *first*.
- **Colouring rule (write this on the wall): a selected web takes the
  LOWEST-numbered already-claimed register that none of its coloured neighbours
  hold.** Only if nothing claimed is free does it claim a fresh callee-saved,
  and fresh claims go **r31 downward** (f31 down for FPRs). Volatiles are
  `{r0, r3..r12}` / `{f0..f13}`.
- Consequence: "web X got rN with no blocker" is *normal* — rN was simply the
  minimum free. Many "wrong colour" residuals are really "the claimer of rN
  pops too late".

### 3.2 Coalesced neighbours are permanent degree

The simplify scan **skips nodes flagged Simplified *or Coalesced***. A coalesced
node therefore never decrements its neighbours, so:

```
degree in the snapshot = |precoloured neighbours| + |coalesced neighbours|
```

Coalesced-to-physical nodes are typically call-argument webs folded into
r3/r4/r5. This is the mechanism behind cross-pass survival: **+1 permanent edge
can make a web survive one extra simplify pass, pop first, and claim r31** —
and the whole callee-saved tail falls into place behind it. One match came down
to degree 21 vs 20; another to 29 vs 28.

Also: **coalescing takes the MIN vreg as root**, so no copy chain can ever
*raise* a web's rank.

The final degree snapshot is **not degree at removal**: later removals can
continue decrementing a node already on the stack. Reconstruct the live neighbors
at each scan. More permanent edges are not monotonically better: the
[mnitemsw match](mnitemsw-matching-notes.md) needed a narrow window to keep the
flag through one extra normal scan; more copies jammed simplification and let
the spill-cost fallback remove the cheap flag too early.

### 3.3 The vreg strata law — what decides rank

Within one ascending simplify scan, selection reverses the vreg order. Across
multiple scans, survival into a later scan takes precedence over vreg rank;
the low-ID original flag in the mnitemsw case study demonstrates this. Numbers
are handed out by
`CodeGen_PreallocateObjectRegisters` walking five object lists, and the bands
are contiguous and ordered (ascending vreg = later = selected earlier):

```
[parameters, in declaration order]
  < [function locals, in REVERSE declaration order]      (first-declared = highest)
  < [second and later live ranges of an existing local]
  < [optimizer/IRO temps @NNN, reverse creation order]
  < [strength-reduced IVs / LICM address temps]
  < [inline-expansion locals and temps]
  < [pure lowering temps, in instruction order]
```

The exact interleaving of the middle bands varies between functions — measure —
but the two ends are firm and they carry almost all the consequences:

- **A plain function local can NEVER outrank a compiler temp.** Declaration
  sweeps, `= NULL` initialisers, casts and carrier structs are all inert
  against a temp. Adding or reordering locals shifts the temp band along with
  them.
- **The only promotions that cross a band** are: (a) make the value a local of
  a `static inline` — the top stratum; (b) make it a *later live range* of an
  already-used variable — just above the named band; (c) wrap it in a one-field
  aggregate — the aggregate-promotion stratum, above trailing scalar temps;
  (d) force it into a pure lowering temp via a cross-type round trip.
- **Within a band, declaration order is the lever**, and *position matters, not
  just presence*: sweep every position, not one. Several matches turned on a
  variable declared second-to-last vs anywhere else. Inner-block declarations
  rank *below* the function's own (they are last in source order, and the band
  is reversed).

### 3.4 The realisation levers (ranked by how often they worked)

Each of these is instruction-neutral unless noted.

1. **Move the value into a `static inline`.** The only way to rank a source
   value above the optimizer's own temps and IVs. Byte-level confirmed many
   times (`fp3` base r5→r3; a shift walker claiming r7 ahead of a whole clique).
   Caveats: MWCC may fold a strength-reduced walker into base displacements
   inside an inline while keeping it incremental when open-coded; and an inline
   whose body is too big will simply emit a call.
2. **Out-parameter inline instead of a value-returning one.** Promotes the
   helper's locals *and* leaves `*out` as a caller web, and it **bills 0 stack
   where the return form bills 8** (measured: frame 104 → 96). A value-returning
   inline also inserts an aggregate copy through the return temp.
3. **One-field carrier struct**: `struct { float v; } x;` used as `x.v`.
   Promotes the member's web into the aggregate stratum, above trailing
   scalar-replacement temps, while staying fully registered. It works on a
   loop-hot scalar **only if the member is written once, from a distinct temp**
   — reassigning the same carrier member twice is a no-op. Not universal: in
   some functions the carrier memory-homes and costs 4–8 frame bytes. Measure.
4. **Reuse an existing variable for a second, disjoint role** instead of
   declaring a fresh local. The later live range is numbered *above* the named
   band and wins ties. This was the decisive lever in one TU where every
   declaration sweep and carrier was inert.
5. **Dead use before the first definition**, to extend a live range backwards:
   ```c
   s32 i;                       /* no initialiser! */
   (void) arr[i];               /* live-in from entry; emits nothing */
   ...
   i = 0;                       /* emitted where the target wants it */
   ```
   Working spellings: `(void) arr[v]`, `(void) &arr[v]`, `(void) -v`,
   `(void) (v != 0)`. **Inert** (folded before web creation): bare `(void) v`,
   `(void) (v*0)`, `(void) (u32) v`. Keeping the declaration initialiser kills
   it (const-prop folds the read). Placement must be **at or after** the block
   owning the temp you need the edge with.
6. **Dead indexed use with an embedded assignment**: `(void) arr[i = x];`
   *births* the array-base materialisation web at a chosen point and places the
   definition. Survives because the assignment is a side effect.
7. **Embedded definition in an expression**: `use(x = expr)` /
   `*(p = &g.f) = v;` / `dest = (T*)((u8*)p + (off = n << 1))`. Defeats the
   "temp + copy `mr`" artifact at the definition site of a virgin named local,
   and loads directly into the named web. Splitting the same assignment into
   its own statement makes the store dead, it gets propagated away, and an
   anonymous temp becomes the operand — measurably different (100% vs 97.67%).
8. **Copy-propagation ownership** (a precise, under-used lever): MWCC's copy
   propagation rewrites uses of a copy back to the source **in every operand
   except a register-to-register `MR`**. So
   ```c
   b = a;              /* MR vB, vA */
   call(b, …);         /* stays on B */
   store_through(b);   /* rewritten to A */
   ```
   splits one value's uses across two webs, decides which web owns which use,
   and *extends a live range without adding an instruction*.
9. **Staged call-argument local** whose definition is a real instruction (a
   load, not a foldable constant). It coalesces into the argument register,
   becoming a permanent-degree blocker for every web live in its window.
   Constant arguments fold away entirely; staging a value that *already*
   naturally coalesces can break its coalescing instead.
10. **Un-name a local into a nested call expression.** Named locals sit in the
    low band and select late; nested call results become high-vreg value temps
    that select early and *claim* the registers a later web then recycles.
    (Inverse direction of the other levers — use when a compiler temp needs a
    *lower* colour than available claims allow.)
11. **Split mutually exclusive values into distinct locals** (second loop gets
    its own `gobj2`/`jobj2`), which moves those webs out of the fixed
    second-range zone into declaration slots.
12. **Index, don't walk.** When a compiler-created byte-offset IV fights a named
    pointer local, rewriting `*src` with `src += 3` as `src[i*3]` makes *both*
    IVs temps ranking against each other instead of against a named local.
13. **Delete the pointer-to-global local entirely** and write `global.member` at
    every site. Every form *with* the local scored 95.6–98.9%; deleting it hit
    99.86%, because MWCC's own CSE then reproduces the target's structure
    including destructive base-register reuse. **Mixed** spelling is the worst
    of both worlds.

### 3.5 What the model says is genuinely out of reach

- A compiler temp created **inside a loop** outranks everything; nothing at
  source level renumbers it.
- Values whose webs are *all* compiler-materialised (global-address anchors,
  strength-reduced IVs, CSE temps) with **no nameable owner** — no source lever
  exists, by construction.
- **Parameter home order** ("which of arg0/arg2 homes first") did not respond to
  anything, across many functions.
- When the target's colouring requires an interference *graph* different from
  the one your source produces — verified by an inverse solver saying
  "unreachable on the fixed graph even with free renumbering" — no renumbering
  lever can help; only a structural change to the source.

But see §10 on terminal verdicts: two of the above categories have fallen to
levers that were outside the swept family.

---

## 4. The stack frame, decoded

### 4.1 The frame is the homed-object list

Not "8 bytes per inline call site" — that rule of thumb is a *symptom*. The
frame is exactly the list of objects MWCC decides to give a memory home:

- **Only some locals are homed**: address-taken, assigned from more than one
  block, or assigned from an inline's return value. Plain register-resident
  locals — including unused scalars — bill nothing.
- The homing decision itself is a pre-colouring pass: a local whose value is
  entirely copy-propagated out of the intermediate code never becomes a
  candidate, so it gets a *vestigial* home and +8 frame with no other effect.
  Removing that local (or inlining it into its uses) sheds the home.
- **Pointer locals, aggregates, block-scoped scalars, and inline call sites bill;
  plain function-scope `s32`s are free.** Block-scoped locals bill ~4 bytes each
  *even when never stored* — a frame far smaller than block-local declarations
  imply is evidence the original declared shared function-scope locals.
- Billing is **not** a simple sum. Measure; do not formula-hunt.

### 4.2 Slot order

- **Home list order = reverse declaration order**, so the *last-declared* homed
  object gets the *lowest* address; equivalently, declared later ⇒ created
  earlier ⇒ lower offset. Verified by reserving gaps: interleaving
  `UNUSED u8 unkNN[N];` between declarations reproduces a target's holes exactly.
- Params bottom; then remaining objects in LIFO creation order — inline-site
  scalar copies (grouped per declaration across sites of the same inline), then
  aggregate-bearing site clusters, then user declarations, then float-conversion
  scratch at the top.
- Arrays allocate in reverse of declaration order while aggregates go forward,
  so `Vec3 pos; u8 pad[4];` puts the pad *above* pos.
- `PAD_STACK` (a statement) lands **below** declarations; to pad *above* them use
  a declared `UNUSED u8 pad[N];`. Pads only ever push addressed locals up —
  they cannot fix an object that needs to move *down*.
- Pads and PAD_STACK inside an inline are discarded with the expansion; padding
  must bill in the caller.
- Pad values are sharply peaked: one value matches, ±8 regresses tens of rows.

### 4.3 Frame recipe that keeps working

1. Get every *object* right first (count homes, not bytes).
2. Fix declaration order for the addressed locals.
3. Trade accessor-inline sites (4 bytes, below locals) against `PAD_STACK`
   (bottom) for the final parity.

It is correct and normal to **regress the percentage** to fix a structural cause
like home count, then recover the colouring afterwards.

---

## 5. Inlining

- `-inline auto` inlines a small function once its body is visible. The
  auto-inline **caller-eat cutoff for statics is roughly 10–20 pre-expansion
  statements**; you can push a helper over the threshold by manually expanding
  part of its body, which is how to make callers emit a real `bl` without a
  pragma or a fake `_noinline` wrapper.
- `-inline auto` is **depth-1 for automatic promotion**: MWCC will not
  auto-inline a function whose own body contains an inline expansion.
- Explicit `static inline` nesting is limited by `inline_depth` (default 2).
  **`#pragma inline_depth(8)` works** and fixes the classic "nested inline body
  vanishes / massive DELETE rows" cliff. `#pragma auto_inline` is ignored.
  `#pragma inline_max_size`/`inline_max_total_size` are ignored in 1.2.5n.
- `#pragma dont_inline on` is **dual-direction**: it blocks inlining *into* the
  function as well as *of* it, and both effects sample atomically at the end of
  the definition. There is no way to keep internal inlining while blocking
  external.
- **A `static inline` defined *after* its call site does not inline** — it emits
  a real call plus an out-of-line body. Definition must precede use.
- **Inline parameter webs never coalesce with the argument**: passing a pointer
  into a `static inline` always costs an `addi` copy, and body uses cannot
  copy-propagate back across a call. A target whose accesses ride the *first
  load's* web cannot be reproduced by an inline whose body uses a parameter.
- **Inline parameter *type* controls result coalescing.** `s16 result` parameter
  plus a tail spelled `result = p->field; return result;` (assign-then-return,
  not `return p->field;`) lands the load directly in the caller's variable on
  both paths; an `int` parameter leaves a `mr` at every expansion.
- Returning-`bool` "phase" inlines do not thread a condition — the result gets
  materialised. Keep the branch textually in the caller and make helpers `void`.
- Function-pointer parameters of inlines **devirtualise** to a direct `bl` when
  the callee is extern; a *static* callee devirtualises but also emits an
  out-of-line copy (address escape).
- Out-of-line copies of `static inline`s are emitted **only when referenced** —
  a dead copy means some call site failed to expand. Check *all* callers.
  Linkers dead-strip fully-inlined static bodies, so emitting one is link-safe
  (there is in-tree precedent).
- When a shared body must reproduce *function-scope* webs, an inline cannot do
  it — use a statement **macro**. (Repo precedent exists precisely because
  "trying to use an inline function breaks inlining".)
- Constant `bool` direction parameters and `switch` on a constant argument fold
  perfectly inside inlines; a constant-condition **ternary** around two inline
  calls does *not* fold-select (cratered to 45%).

---

## 6. The instruction scheduler

Reverse-engineered exactly (54/54 instructions on a 54-instruction unrolled
block) and worth knowing because "two instructions transposed" residuals are
otherwise unfalsifiable:

- The driver switches on a CPU byte; **`-proc gekko` has no case, so the DEFAULT
  machine model is used**: width 2, a *single* integer unit, 2-stage LSU,
  3-stage FPU, 5-slot in-order retire ring, ≤2 retires/cycle, branches are
  barriers.
- Dependences are built walking each block **backward**; heights are exact
  downstream critical paths. Register lists are never pruned (conservative).
  Pointer-based loads/stores carry a wildcard flag, producing store→every-later-
  load edges with latency 2 — this is what spaces reload chains in unrolled loops.
- **Pick tie-break, in order**: (1) candidate is due and the incumbent is not;
  (2) more successors at predecessor-count 1 ("release count" — the mechanism
  behind steady-state load hoists via WAR successors); (3) larger height;
  (4) smaller opcode descriptor byte (`MR` < `STFS`/`CMP` < `ADDI`/`FADDS` <
  `LFS`/`LWZ` < `LI`), active only pre-allocation; (5) earlier textual order.
- Because the scheduler runs **before** register allocation, a "same registers,
  two instructions swapped" residual is a scheduling problem and no allocation
  lever touches it.
- **Commutative-operand order is set at lowering**, by the order the operand
  *values* were materialised. `tmp = b - c; r = tmp * a;` swaps operand
  registers versus `a * (b - c)`. A compound assignment reads its LHS first.
  `a - -b` folds to an ADD keeping SUB's operand order — the one proven late
  operand-order lever.
- Statement order drives scheduling; declaration order drives colouring. Sweep
  **both** before calling anything terminal. A full n! statement-order sweep per
  basic block is 24 compiles and has cracked cases that ~130 other variants left
  standing.
- Emission deletes dead `ADDI`/`MR`s and folds `MR`+load / `ADDI`+load into
  displacements, repositioning the folded load at the copy's slot.

### Post-allocation peephole

There is one post-allocation rule set (90 registrations over 41 opcodes). The
only `ADDI` rule folds `addi rD,rBase,i` + `addi rD,rD,j` into
`addi rD,rBase,i+j`, and **rejects when anything between the two adds uses the
first add's destination** — which makes it steerable from source. Two traps:
its preconditions require both immediates to be plain constants (a symbol `@l`
is a different operand kind, so `addi t,hi,sym@l` + `mr d,t` never folds), and a
**final scheduling pass runs after the peephole**, so you cannot infer what the
rule saw from the object file's instruction order.

---

## 7. Source-shape lever catalogue (non-allocator)

Things that change the *instruction stream*, i.e. real reconstruction evidence.

**Loops**

- Variable-bound loops unroll **only** with a counter of exactly `int`; `s32`
  never unrolls. Constant-trip loops unroll either way. Loops containing a call
  never unroll. `int` also governs **guard folding** on the 16-iterations+
  remainder clear-loop shape.
- Trip count decides the shape: 2 iterations strength-reduce, 3 fully unroll to
  displacements. A **2× partial unroll** exists for constant-trip loops with big
  bodies — its tells are two bodies per iteration, biased displacements in the
  second, and a **vestigial dead counter**. If a decomp has a hand-written
  "two halves per iteration" loop with a dead counter, it *is* a 2× unroll:
  write the plain one-body loop.
- Exit via `goto found` when the target's counter is dead at loop exit; a
  trailing `if (i == 4)` keeps the counter alive at every iteration top.
- MWCC canonicalises loop *spellings* completely — `do/while`, `while(1)+break`,
  goto ladders and `continue` forms all compile identically. Branch polarity
  (`bne exit; b top` vs `beq top`) is decided by CFG geometry: inversion fires
  whenever the target block immediately follows the `b`. The only construct that
  suppresses it in the whole binary is a switch dispatch tree.
- **`goto`/label blocks** decouple branch layout from the loop construct, and
  are sometimes the only way to reach a target's block order.
- Keep sibling loop counter *types* uniform — an `int` counter in one of three
  loops broke a shared IV-init CSE.
- Assigning **in a loop's controlling expression** —
  `for (i = 0; zero = count = 0, i < N; i++)` — gives a definition in the
  preheader (so induction-variable analysis still works) *and* makes the
  constant part of the loop (so it materialises after the body's constants).
  That resolved a hard conflict between strength reduction and hoist order.

**Access forms**

- Prefer real member/array syntax over pointer math. Not just style: a **cast**
  breaks MWCC's member path, so a constant table offset stops folding into the
  load displacement. Retyping `int[2][12]` accessed through
  `((int(*)[4][3]) x)` into a true `int[2][4][3]` folded the `0x30` into
  `lwz +0x30` — idiomatic *and* the fix.
- Retyping a global to its real struct is usually **free** (every symbol
  byte-identical) — do it when reviewers ask, but don't expect it to fix
  operand order.
- Straight-line accesses through a known stack address fold to `r1+offset`;
  in-loop accesses keep a register walker.
- Strength reduction of a stride-1 member array works fine **when no pointer
  local competes**; the "cast-index form required" rule was an artefact of a
  pointer local being present.
- Unsigned index arithmetic (`i * sizeof(...)` with `size_t` promotion) **kills
  IV strength reduction**; cast `sizeof`/`offsetof` to a signed type.
- 2-D subscripts are strength-reduced **separately** (`y<<4`, `x<<2`); if the
  target computes Horner (`(y*4+x)<<2`), write the flat row-major index.
- `!!x` vs `x != 0` as an array subscript is codegen-significant.
- Interior symbols: if the target anchors at a *parent* object with folded
  displacements, use a parent-typed local and a member path; a local holding the
  computed interior address materialises an `addi` instead.

**Pointer arithmetic operand order (swept exhaustively, 11 spellings)**

- **All pointer sums emit `add rD, rBase, rIndex`.** The frontend rewrites
  `int + ptr` → `ptr + int`; subscripts, `+=`, casts, `(void*)` laundering,
  retyping, and strength reduction all give the same order.
- **Only an integer sum preserves source order, and only with a shift**:
  `(i << 1) + base` gives index-first; `i * sizeof(T) + base` gets commuted.
  So an index-first `add` in the target is *proof* the original was an integer
  sum written offset-first — use `uintptr_t`, not a signed cast.

**Floats**

- `if (v != 0.0f)` vs `if (v)` swaps `fcmpu` operand order (real, but often
  neutral or worse away from the site that needs it).
- Float **literals** rematerialise per extended basic block; an extern `f32`
  *variable* passed as an argument gets globally promoted into a callee-saved
  FPR. Use literals where the original had them.
- Giant nested expressions vs step-by-step assignments is a real lever for float
  formulas (more live conversion temps): 95.7% vs 99.82% on the same math.
- A named temp for a **call result** can fix an `fmuls` operand order that no
  operand swap reaches. In `A * B` with calls on both sides, MWCC always
  evaluates the left call first — use a temp for whichever must precede.
- Caller-side negation of an inline's result blocks `fnmadds` fusion; move the
  negation inside. `-(c - a*b)` gives `fnmsubs+fneg` (MWCC won't commute).
- An inline return boundary blocks `fp_contract` fusion across it — a "midpoint"
  helper made `0.5f*(L+R) - L` stop contracting to `fmsubs`.
- CSE'd `(a-b)*(a-b)` promotes the difference into the volatile-temp stratum —
  an FPR-colouring lever that is also the more idiomatic spelling.

**Constants and opacity**

- MWCC treats a variable as const-known only when its reaching definition has a
  **literal** right-hand side. `x = (y = 0);` makes `x` opaque. Opacity controls
  strength-reduced IV initialisation (`slwi` vs a folded `li 0`) and which
  register a zero store recycles. A target `slwi rX,rC,K` where `rC` is provably
  0 is *evidence* the original's definition was opaque.
- `li rA,0; addi rB,rA,0` "zero recycle" only appears when the source register
  belongs to an **optimizer temp**, never a user local. (Inline origin matters
  only because inlined locals become optimizer temps.) A straight-line copy of a
  known zero between two user variables always folds to two `li`s — 18 spellings
  confirmed.
- **`(void) expr` is discarded in the frontend** for side-effect-free
  expressions and never reaches the allocator. Any lever built on it needs a
  real side effect (an embedded assignment, an indexed read). Statically-dead
  guards are the same trap.
- **Comma-expression trick**: `jobj = (pnum = f(gobj), GET_JOBJ(gobj));` delays
  the call-result home copy past the next load. A plain temp doesn't work —
  copy propagation restores the eager `mr`.
- A non-`void` function with **no return statement** keeps r3 reserved, so
  post-call scratch allocation starts at r4. Check the declared return type
  before running allocation sweeps on a "scratch tie-break". Conversely, an
  undefined return value pins r3 function-wide — if no caller reads the result,
  make the function `void` (and fix the function-pointer typedef).

---

## 8. Data, literal pools, and translation-unit boundaries

Getting a function to 100% is often *not* the hard part of linking a TU.

- **`.sdata2` float pools are laid out in order of first textual appearance**
  across the whole TU, 4- and 8-byte constants interleaved in that same order.
  Integer literals in float comparisons convert at parse time and do not defer
  discovery. Swapping the two sides of `a < 0.0f || a > 1.0f` swaps the first
  two pool entries and nothing else.
- Pin a pool with a dead ordering function that mentions every constant
  (`static void sdata2_order(void) { (void) -3.0f; (void) 4.0f; … }`). It emits
  a stub the linker dead-strips; upstream tolerates it and dozens of files use
  it. Once pinned you can reorder statements freely.
- **String literals pool where the function is *parsed* for a plain `static`,
  and where it is *expanded* for a `static inline`.** Making one helper
  non-inline moved two strings ahead of a third and made a whole `.sdata`
  section byte-exact.
- **File-scope data emits at its source position, interleaved with function
  literals.** Original files really did declare tables mid-file, between
  functions. Moving definitions to just before their consumers has repeatedly
  reproduced exact data order and let "order hack" functions be deleted.
- **`.bss`/`.sbss` ordering**: `.bss` orders by first *code use*; `.sbss` orders
  statics/locals first (declaration order) then globals (reverse declaration).
  Making TU-local variables `static` and declaring them in address order is the
  usual fix.
- **A global's address only hoists to a prologue register if its definition was
  already seen in the TU.** Tentative header definitions and `= {0}` don't
  count. `extern` declaration at the top + real definition at the bottom is the
  lever (and the float analogue exists for `const f32`).
- **All same-section data references in a TU pool onto ONE anchor at section+0.**
  There is no source spelling that anchors a function's pool mid-section.
  Therefore **a target function whose pool anchor is mid-section proves the file
  merges several original translation units.**

### Detecting false or missing TU boundaries

Independent evidence types, in rough order of strength:

1. **Section alignment.** MWCC emitted `.data` with 8-byte alignment in 623 of
   623 objects in this project. A split whose `.data` starts at a 4-aligned
   address therefore *cannot* be a TU start.
2. **Duplicate constants in one pool.** If the target pool holds the same value
   twice while other constants are shared, the object was assembled from several
   TUs — dedup only happens within one. One `.c` cannot reproduce it.
3. **`__FILE__` assert strings** are the basename of the *compiled* file, and
   asserts inside headers carry the header's name. This is ground truth for the
   original filename.
4. **Assert line numbers** too small to fit the code above them; and
   `__LINE__` gaps that constrain how much source can sit between two functions.
5. **Shared literal-pool slots.** Two objects cannot share one literal.
6. **Per-function pool ownership.** Map which function references which pool
   entry; a clean partition is a split point (this is how one file was correctly
   split in two, after which *both* pools came out byte-identical with no
   ordering hack at all).
7. Relocation **addends**: `sym+K@ha` with zero displacement where you emit
   `sym@ha` plus displacement K suggests the original had separate objects.

Merging TUs has its own trap: an **inferred *named* constant in `.sdata2` is a
split artefact**. Once definition and use land in one TU, const-propagation
duplicates it into the pool and shifts everything. Turn it back into a literal.

### Linking

- Functions must be **defined in address order**; per-symbol scoring cannot see
  ordering, the link can. Reordering also renumbers anonymous literals.
- Section-length shortfalls at the tail are linker zero-fill, not real diffs.
- Prove link-equivalence locally without linking: compare section bytes plus a
  relocation-resolving comparator (for each entry compare offset, type, target
  section, symbol value + addend). Two universal false diffs: SDA21 relocation
  offsets sit at instruction+0 in disassembler-produced targets but +2 in
  compiler objects (mask the low bits), and `.data` may be short by tail padding.
- **Regenerate the symbol table from the linked binary with the project's own
  tool rather than hand-editing it.** Doing so is a repository-wide
  canonicalisation, not per-PR noise — commit the whole result.
- **Exact bytes do not justify inventing externally visible data ownership.**
  One link was achieved by manufacturing file-scope constants to force
  relocations; the maintainer correctly replaced them with function-local
  `static const` objects and plain literals plus a pool-order seed, and the
  canonicaliser then recovered the real local names.

---

## 9. Tooling that changed the game

In descending order of impact.

1. **Capture the compiler's internal state.** Run the compiler under emulation
   with a debugger attached, break at the allocator entry points, and dump: the
   pre-colouring intermediate code, the interference graph before/after
   colouring (GPR *and* FPR), the local home list, and the stack-frame trace.
   Everything in §3 and §4 came from this. Two decisive details:
   - **Object names are recoverable** from the opaque blobs in those dumps (an
     ASCII run a few bytes in), so every virtual register can be labelled with
     its source identifier or its `@NNN` temp id. That is what made the strata
     legible.
   - Select functions **by index** when name resolution fails; indices are
     emission order and drift from `nm` order because of inlined statics.
2. **A replay/simulator for simplify + select.** Given a captured graph, replay
   the algorithm and validate it reproduces the observed colours exactly
   (routinely 100%+ of nodes across many captures). Then answer inverse
   questions in *seconds* instead of one compile each:
   - *Reachability*: force the target select order — if it yields the target
     colours, the fixed graph can realise it and the problem is order/rank.
   - *Rank hypotheses*: renumber webs under the strata constraints.
   - *Degree hypotheses*: `extra_permanent_degree = {web: ±n}`.
   - *Edge hypotheses*: exhaustive 1-, 2-, 3-edge searches.
   This turned "sweep source shapes and hope" into "the model says web X needs
   rank ≥ N and web Y must not sit in (a,b) — now find the source form".
   **Search multiple knobs at once**: a single-knob search reported "unreachable"
   on a case where a six-web vector reached the target exactly.
3. **A scheduler simulator** built from the reverse-engineered machine model,
   for delta-searching which dependence edit produces the target order.
4. **Whole-project function similarity search** (normalised instruction token
   n-grams in a vector index, ingesting several games). Its value is finding a
   **matched twin whose source you can read**, not scoring. Distance ≈ 0
   ("token-identical twin") is a near-guaranteed transplant win. It is a *shape*
   twin finder — it cannot help with register or scheduler ties.
5. **Twin scanning**: script an objdump scan of *every* target object for the
   exact construct you are stuck on, then filter to already-matched files and
   read their source. This found a 2×-unroll idiom in minutes after ~10 blind
   variants failed. And a pattern that is **unique to your function** across the
   whole binary is strong evidence there is no source construct — it is an
   allocator or scheduler tie.
6. **Parallel variant sweeps.** Always sweep; never test one shape at a time.
   Slice the source to the function body, generate variants, compile 4–5
   concurrently, score, restore in a `finally`. (And see §1.5 — a sweep harness
   that swallows compile errors is worse than no harness.)
7. **A before/after whole-object verifier** for refactors: snapshot, change,
   recompile, list every symbol below 100%. For a final audit, stash the work,
   snapshot, unstash, compare — proving every touched object is byte-identical.
8. **Type-layout index** (dump record layouts, find duplicate structs, union
   views, overlay casts) for type-cleanup candidates.
9. **Runtime verification** (emulator GDB stub, on-screen debug text, scripted
   cheat payloads) for questions the static work cannot answer — e.g. proving
   which of two internal identifier spaces a field holds, by forcing the game to
   print both.

---

## 10. Method, and the discipline of terminal verdicts

**Order of operations for a stuck function**

1. Check the project's own matching-tricks documentation. Maintainers use it.
2. Look for a **donor twin** — a matched function with the same instruction
   shape — and transplant its *source structure wholesale*: wrapper/inline split,
   accessor macros, alias pairs, declaration order, pad values. One function
   went to 100% in a single step this way after a prior session plateaued at
   97.6% grinding spellings.
3. Census the shape delta (§2) and clear all structural rows.
4. Capture, replay, and let the model tell you what property is needed
   (rank? degree? edge? home count? schedule edge?).
5. Only then hunt for the source form that produces that property.

**Rules learned the hard way**

- **Cross the levers before declaring a plateau.** Match percentage is
  *non-monotonic* in lever count: 98.31% with none, 98.76% with two, 100% with
  three. Partial recipes look exactly like noise. In another case: inline alone
  98.69%, loop shape alone 98.41%, both 100%.
- **"Proven unreachable" only covers the structural family you swept.** This
  verdict was issued and later falsified at least four times. The recurring
  failure mode: proving that *moving a definition* cannot work, when *extending a
  live range with a use* was outside the model. Before declaring anything
  terminal, walk the full lever list in §3.4.
- **Match % is a lagging indicator.** Measure the compiler's actual decision.
  Accept a regression that fixes a structural cause.
- **Two residual clusters fighting over the same register are ONE problem.**
  Fixing the loop-region web fixed a cluster 100 instructions away.
- **Web colours do not follow variable identity.** Renaming, aliasing, and
  reassigning compile to identical instructions *and* identical (wrong) colours.
  Webs are structural; MWCC canonicalises.
- **Perturbation is not progress.** A change that moves both target webs by +1
  while costing 50 unrelated rows is noise, not a lead.
- **Don't run captures concurrently, and don't edit the source while one is
  running** — the container reads the working tree live. Hours were lost to
  phantom "stalls" that reproduced on pristine code.
- When local search plateaus on a pure colour permutation, package a
  reproducible kit and hand it to the community; that class is regularly cracked
  by others.

---

## 11. Correctness is not the same as matching

Byte-scoring is blind to whole categories of real bugs. Check for them
explicitly before declaring a file done.

- **Wrong-variable bugs between zero-initialised objects are invisible.** A
  value-comparing differ scores two 4-byte `.sdata` ints that both read `0x7F`
  as equal, so a function that stored to the *wrong* one scored 100% while the
  linked binary differed by one byte. Two such bugs were found in one file this
  way. **Only the link catches these.** Recipe: byte-diff the linked binary, map
  the offset to a virtual address through the header, then diff relocation
  *target names* between the two objects.
- **Constants that are "obviously" round numbers may not be.** Four cursor
  hit-box bounds in one function were `0.2`, `-4.6`, `-1.0`, `-5.8` in the
  decomp; the shipped game uses each nudged outward by 1/10485760. Every hit box
  was slightly larger than the decompilation said. Scoring literal-pool loads by
  symbol hides this completely — read the disassembly's own `.double`
  directives. A constant that appears in your pool but *nowhere* in the target's
  is a real bug; `objdump -s -j .sdata2 | grep -c <hex>` on both settles it in
  one command.
- **Sign and structure bugs hide behind good scores**: a `1.0F - 4.0F*t`
  written as `(-4.0F*t) + 1.0F` was proven wrong because the target pool
  contained `+4.0` and *zero* occurrences of `-4.0` (and emitted `fnmsubs` where
  we emitted `fmadds`).
- **"No relocation names it" ≠ unreferenced.** MWCC reaches same-object data by
  base + displacement, so a string literal reached as
  `(char*)((u8*)&blob + 0x5B8)` has no relocation of its own. Grep the source
  for the offset.
- Data-model bugs found by reconstructing sizes and initialisers: a `GXColor[11]`
  that was really `GXColor[4]` (with two wrong entries), a symbol mis-sized so
  it swallowed its neighbours, a texture that needed 32-byte alignment (the
  4-byte pad before it was the tell).
- Audit **every** diff row whose *mnemonic or immediate* differs — as opposed to
  registers, branch targets, and uniform stack shifts. That scan is cheap and it
  is the only systematic guard.

---

## 12. Working with a real project (review and hygiene)

- **Idiomatic C beats match hacks whenever the score allows** — and it sometimes
  *outscores* the hack. Real examples where the clean form won: deleting a
  pointer-to-global local, retyping a cast array to its true dimensions,
  replacing biased-pointer arithmetic with 2-D indexing plus hoisted invariants.
- **Lint runs with warnings as errors, and the fixer edits your file.** A no-op
  self-cast used to break a CSE both failed the lint job and would have been
  auto-deleted, silently breaking the match for anyone with the pre-commit hook
  installed. A block-local copy scored identically. Read the lint config before
  choosing between equal-scoring spellings.
- **Use the project's own symbol-rename tool** rather than hand-rolling a sweep;
  it walks assembly, config, and linker scripts too. And fetch/merge upstream
  *before* renaming, or you will miss references added since you branched.
  (A rename tool that resolves the repo root from its own binary location will
  silently do nothing when run from a worktree — check `git status` in the main
  checkout.)
- **Formatter behaviour is not free of surprises.** One formatter tabulates a
  braced initialiser into columns once its items are similar enough in width
  (measured flip: a 14-character item stays one-per-line, 15 goes to columns).
  Renames therefore produce large pure-reflow diffs; say so in the PR and let the
  byte-identical objects carry the argument.
- **Comments: minimal, terse, factual.** No percentages, register lists, or
  experiment journaling in source. That detail belongs in notes. Where an
  inferred name genuinely needs an evidence trail, reviewers want it *in-repo*
  (a docs file), not in a PR comment or chat, which they treat as transient.
- **Naming: follow the binary's own strings.** Debug tables, `__FILE__` strings
  and assert text are the developers' names; invented conventions are a fallback.
  Two independent name sources can disagree with each other — that's the binary,
  not a typo. Keep self-inferred names conservative; treat a maintainer's
  supplied name as strong evidence but verify type, storage, and callers before
  applying it.
- **CI can fail for reasons that have nothing to do with your change.** One
  differential job builds the *baseline* branch first, and if the baseline's
  checked-in symbol table isn't a fixed point of the split step, the tree is
  dirtied and the checkout back to your branch aborts — for every PR that
  touches that file. Reproduce locally before believing it's yours.
- **Helper placement matters to reviewers**: an emitted function keeps one real
  definition and an ordinary declaration — never duplicate its body as
  `extern inline` to manufacture cross-TU inlining. A genuinely inferred
  inline-only helper goes in the established shared inline header for its
  semantic owner; a single-TU helper stays `static` in that file.
- **Reusing an existing accessor at raw field-access sites almost always
  regresses** (2 of ~14 candidate sites held). The originals used those helpers
  at *specific* sites; MWCC's inlining is not position-neutral. Expect loop
  bodies and call-argument positions to fail.

---

## 13. The "don't re-grind" ledger

Classes that repeatedly resisted everything. Recognise them early and either
ship with a one-line note or hand them off.

| class | signature | status |
|---|---|---|
| Compiler-IV colouring | a strength-reduced walker must outrank a named value | no source lever; needs the loop-transform pass modelled |
| Parameter-home order | `mr`/`addi` for arg0 vs arg2 homes swapped | never flipped by anything |
| Scratch/volatile tie-break | identical stream, two scratch registers traded | ~30–200 variants each, all canonicalise |
| Global-address anchor tie | `...data.0` vs a named symbol in a base register | usually a data/TU-boundary problem, not a code one |
| Stack "band mirror" | your content packs high and filler low; retail is reversed | seen 5+ times; knob still unidentified |
| Scheduler pair tie | later-ready instruction scheduled before earlier-ready | only the simulator can say whether an edge is reachable |
| Frontend CSE-pool assignment | which occurrence becomes the canonical vs a recompute | backend modelled, frontend value-numbering not |

Two of these (compiler-IV colouring, "carrier is a no-op") were later *broken*
by levers outside the swept family. Treat the table as a prior, not a proof.

---

## 14. Twenty things worth memorising

1. Classify the stage before you sweep the source.
2. Score with the project's real options; reloc-name rows are noise.
3. Delete the object before every compile.
4. Compile in the real translation unit.
5. Select order = reverse simplify order; a web takes the **lowest claimed free**
   register; fresh claims descend from r31.
6. Coalesced and precoloured neighbours are permanent degree.
7. A named local can never outrank a compiler temp — only an inline boundary,
   a second live range, or a carrier crosses bands.
8. Declaration order is a real lever, and *position* is the payload: sweep all
   of them.
9. The frame is the homed-object list; homes come from address-taken, multi-block
   assignment, or an inline's return value.
10. Home order is reverse declaration order; declared later ⇒ lower address.
11. Out-parameter inlines bill 0; value-returning ones bill 8.
12. `(void) x` is deleted; `(void) arr[i = x]` is not.
13. Loop counters must be exactly `int` to unroll a variable bound.
14. Pointer sums always emit base-first; only an integer sum with a shift
    preserves source order.
15. Literal pools follow first textual appearance; `static inline` pools at
    expansion, plain `static` at parse.
16. Duplicate constants in one pool, or a mid-section pool anchor, prove a TU
    boundary.
17. `.data` alignment can *disprove* a claimed TU boundary.
18. Cross the levers before declaring a plateau; percentage is non-monotonic.
19. "Unreachable, proven" only covers the family you swept.
20. Only the link catches wrong-variable bugs; only reading the disassembly's
    own constants catches wrong constants.

### Final JPEG decoder match (2026-09-07)

See [fn_803B6820 match learning](fn_803B6820-match-learning.md) for the measured
combination of embedded narrowing assignment, red-expression operand order,
by-reference output context, and preserved upstream pointer allocation change.
The pointer-to-pointer and pointer-to-struct variants had different frame effects;
treat frame heuristics above as hypotheses to validate, not universal rules.
