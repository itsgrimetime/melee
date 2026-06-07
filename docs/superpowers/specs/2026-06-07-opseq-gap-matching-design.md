# Gap-Tolerant opseq + Derive-From-Target Design

## Problem

`opseq` (the `table-typer opseq` opcode-sequence search) only matches **direct,
unbroken** opcode sequences. Today it has exactly one kind of wildcard — the
operand wildcard `_` and named register variables that bind a register
consistently across a single instruction (`addi x,y,_`). There is no way to
tolerate *instructions between* the meaningful opcodes.

This bites in two concrete ways, both confirmed as the real friction:

1. **Scheduler / register noise breaks the run.** The instruction scheduler
   reorders code and register coloring inserts `mr`/spill/reload/address-calc
   noise between the opcodes that actually carry meaning. Two functions that do
   the same C-level thing — a float compare-and-branch (`lfs … fcmpo … bge`), a
   counted loop (`… bdnz`), a jump table (`… mtctr; bctr`), an epilogue
   (`lwz r0; mtlr; … blr`) — have *different filler* between the landmarks, so a
   contiguous-only matcher misses exactly the structurally-similar reference
   functions the user most wants to find.

2. **Patterns are hard to author.** Even when gaps are supported, the user has
   to know which sequence to search for and guess how many filler instructions
   to allow. That authoring burden is itself a barrier to using the tool.

No existing capability fills this gap. `patterns similar` operates on **C source**
features (API calls, loop patterns, array accesses) and requires an
already-decompiled function, so it cannot run on the raw asm you are stuck on.
`mismatch opcode` is an expected-vs-actual diff classifier, unrelated. Operating
on **raw asm** is `opseq`'s unique niche, so extending it here is net-new, not a
rebuild.

## Goals

- Tolerate a bounded number of "don't care" instructions between landmark
  opcodes (absorbs scheduler/register noise) — friction (1).
- Auto-generate a gap-tolerant, **editable** pattern from a target function (or
  a line range within it), removing the authoring burden — friction (2).
- Preserve specificity: gaps must not collapse precision into a flood of
  irrelevant matches.
- Stay one self-contained, fast Go binary; keep `opseq` a single tool.

## Non-Goals (YAGNI for v1)

- Alternation (`(beq|bne)`), opcode sets/classes, anchors (`^`/`$`) — the user
  did not cite these as friction. Noted as possible future work.
- A separate opaque similarity-ranking engine (LCS / k-gram Jaccard). Its one
  good idea — ranking — is folded into this design as a result sort key, not a
  parallel matching system.
- A persisted opcode-frequency cache. The frequency table is computed in-memory
  from the asm scan that already happens each run.
- A `--no-branch-gap` strict mode (gaps that may not span branches). Noted as
  future; gaps span branches by default in v1.

## Design

Four components, all inside `tools/table-typer`. Components 1 is independently
useful and ships first as its own milestone; Components 2–4 build the
derive-from-target experience on top of it.

### Component 1 — Bounded-gap matcher (ships first; this is the "A" milestone)

Extend the opseq pattern grammar with **gap tokens** that compose with the
existing operand `_` wildcard and named register variables:

- `*` — a gap of `0..CAP` instructions between adjacent landmarks, where
  `CAP` defaults to `6` (override with `--gap-cap N`).
- `*{m,n}` — an explicit gap of `m..n` instructions.
- `*{m,}` — `m` up to a hard ceiling (`32`) that bounds backtracking.
- `?` — exactly one instruction (sugar for `*{1,1}`).

An "instruction" is a non-label asm line. Label lines (`.L_…`) continue to be
skipped and **do not count** toward a gap's budget, consistent with current
behavior. Leading and trailing gaps are allowed. Gaps may span branch
instructions and labels by default.

Matching semantics: when the matcher reaches a gap token between landmark
`op[j]` and `op[j+1]`, it scans forward, respecting the gap's `[m,n]` window, for
a position where `op[j+1]` (and the remainder of the pattern) matches. This is a
bounded backtracking match — worst case is the product of window sizes, which is
small because gaps are bounded.

**Implementation note (correctness-critical):** the current matcher mutates a
single `vars` map for register-variable binding. With backtracking, a failed
branch must not leak bindings. The matcher must **snapshot/restore** (or pass a
copy of) `vars` at each backtrack point so a register variable bound on a
discarded path does not poison a later path.

This component, on its own, lets a user hand-write `lfs, *{0,3}, fsubs, bne` and
is shippable/useful before any derive logic exists.

### Component 2 — Corpus opcode-frequency

During the existing asm scan, tally `opcode → count` over all instruction lines
(strip operands; skip labels and directives). Held in-memory for the duration of
the invocation; no on-disk cache. Used by Component 3 to rank ops by rarity.

### Component 3 — Derive-from-target (`opseq --like <func>[:start-end]`)

1. Locate `<func>`'s asm from the `.fn` declarations already parsed. If a
   `:start-end` line range is given, restrict to that window — this directly
   serves the "stuck on one spot" case behind friction (1).
2. Extract the target's instruction stream in order (opcodes; labels marked but
   not emitted as landmarks).
3. **Landmark selection — control-flow anchored + rarity:**
   - **Always keep** control-flow opcodes as structural anchors: all branch
     forms (`b`, `beq`, `bne`, `blt`, `ble`, `bgt`, `bge`, `bl`, `bctr`,
     `bctrl`, `bdnz`, `bdz`, `bclr`/`blr` variants…) plus `mtctr` and `mtlr`.
     These are precisely what make loop / return / switch shapes come through.
   - **Rarity fill:** of the remaining (non-control-flow) ops, keep the rarest
     by corpus frequency (Component 2), up to a total landmark cap
     (`--max-landmarks`, default `12`, counting both anchors and rarity fill),
     so the distinctive instructions survive and ubiquitous filler (`mr`, `nop`,
     `li`, `addi`, …) drops out naturally without a hand-curated denylist. If the
     anchor set alone already meets or exceeds the cap, no rarity fill is added.
   - Everything not kept collapses into a gap.
4. **Emit the pattern:** landmarks in order, with `*{0, gap+slack}` between
   consecutive landmarks, where `gap` is the observed filler count and `slack`
   defaults to `2` (`--slack N`). Lower bound `0` tolerates the scheduler
   removing/relocating filler; upper bound tolerates a few extra instructions.
   The derived pattern is **printed** before results so it is transparent and
   hand-editable.
5. v1 derives **opcode-only** landmarks (no operands): operands vary across
   structural cousins, so binding them would over-constrain. `--with-operands`
   opts into including register-variable binding for callers who want it.
6. Run the derived pattern through Component 1 and print results.

### Component 4 — Result ranking

Replace the current size-only sort with: **primary sort by total gap-slack
actually consumed** (the tightest structural match first), then by function size
ascending (current behavior as tiebreak). Keep the existing `--candidates`
matched/unmatched filter. For each hit, report the matched span (start/end
lines) so the user can judge how tight the match is.

## CLI Surface

- `opseq <pattern>` — unchanged invocation, now accepts gap tokens (`*`,
  `*{m,n}`, `*{m,}`, `?`). Backwards compatible: patterns with no gap tokens
  behave exactly as before.
- `opseq --like <func>` / `opseq --like <func>:start-end` — derive a pattern and
  run it. The derived pattern is always printed.
- Flags: `--gap-cap N` (default 6), `--slack N` (default 2, derive mode),
  `--max-landmarks N` (default 12, derive mode), `--with-operands` (derive mode,
  default off), plus existing `--candidates`.

## Testing

Go tests in `tools/table-typer` (new `*_test.go`):

- **Matcher:** gap windows (`*`, `*{m,n}`, `*{m,}`, `?`), label skipping inside
  gaps not counting toward budget, leading/trailing gaps, the hard ceiling, and
  — critically — register-variable `vars` snapshot/restore correctness under
  backtracking (a binding on a failed branch must not leak).
- **Frequency:** opcode tally over a small fixture asm set.
- **Landmark selection:** derive on a known function, assert control-flow ops
  are kept and ubiquitous filler is dropped (golden pattern).
- **End-to-end:** derive from a known matched function and assert the run finds
  itself plus at least one known structural cousin; assert backwards
  compatibility on a gap-free pattern.

## Risks & Mitigations

- **Precision collapse from gaps** → gaps are bounded by default (`CAP`), results
  are ranked by least slack consumed, and control-flow anchoring keeps the
  structural skeleton specific.
- **Backtracking blowup** → bounded gaps plus a hard ceiling on `*{m,}`.
- **Register-var binding corrupted by backtracking** → explicit snapshot/restore
  of `vars`; covered by a dedicated test.
- **Landmark heuristic picks poorly** → thresholds (`--gap-cap`, `--slack`,
  landmark cap) are tunable, the derived pattern is printed for hand-editing, and
  manual pattern mode (Component 1) is always available as the fallback.

## Build Sequencing

1. Component 1 (bounded-gap matcher) + matcher tests — independently useful;
   users can hand-author gap patterns immediately.
2. Components 2 + 3 + 4 (frequency, derive-from-target, ranking) + tests.
3. Update `.claude/skills/opseq/SKILL.md` (document gap tokens and `--like`) and
   regenerate the capability index (`melee-agent capabilities generate`).
