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

Five components, all inside `tools/table-typer`. Component 0 (normalized asm
model) plus Component 1 (gap matcher) are independently useful and ship first as
the "A" milestone; Components 2–4 build the derive-from-target experience on top.

### Component 0 — Normalized asm model (foundational)

Before any matching, parse each asm file once into **per-function bodies**
delimited by `.fn …`/`.endfn`. Each body is a struct of: function name, matched
status, size, and an ordered slice of **instruction records** `{opcode,
operands, srcLine}`. Label lines (`.L_…`) and directives are recorded as
position markers but are **not** instruction records, so gap budgets and
indexing count only real instructions.

All three downstream consumers operate on this in-memory model rather than on raw
file-line slices. This is what makes the rest correct and bounded:

- **Matching never crosses a function boundary** — a match is attempted within a
  single body's instruction slice, and results are attributed to that body. (The
  current file-wide `matchLines(lines[i:])` can already bleed past `.endfn`;
  gaps would make that far worse.)
- **Label skipping is structural, not ad-hoc** — because records already exclude
  labels, the recursive matcher indexes instructions directly and never has to
  re-derive a `skip` offset or risk EOF over-reads.
- **Corpus frequency and derive get the data they need up front** — frequency is
  tallied over all records in one pass, available before landmark selection.

### Component 1 — Bounded-gap matcher (ships first; part of the "A" milestone)

Extend the opseq pattern grammar with **gap tokens** that compose with the
existing operand `_` wildcard and named register variables. **Brace bounds use
`..`, not a comma**, so the existing top-level comma split that separates tokens
keeps working unmodified (`lfs,*{0..3},fsubs` splits cleanly into four tokens):

- `*` — a gap of `0..CAP` instructions between adjacent landmarks, where
  `CAP` defaults to `6` (override with `--gap-cap N`).
- `*{m..n}` — an explicit gap of `m..n` instructions.
- `*{m..}` — `m` up to the hard ceiling.
- `?` — exactly one instruction (sugar for `*{1..1}`).

**Bounds and validation:** *every* gap upper bound — explicit or default — is
clamped to a hard ceiling (`32`); a pattern whose explicit upper bound exceeds it
is rejected with a clear error (prevents `*{0..500}`-style combinatorial
blowups). A pattern **must begin and end with a concrete landmark token** —
leading and trailing gaps are rejected. This removes a whole class of
function-boundary and overlapping-start problems and costs nothing in practice
(derived patterns are bookended by landmarks anyway).

An "instruction" is an instruction record from Component 0; labels are already
excluded and never count toward a gap's budget. Within a gap, branches may be
spanned by default.

Matching semantics: matching runs over a single function body's instruction
records (never across bodies) and returns the **best (tightest) alignment** per
body, not merely the first success: `{ok, slackConsumed, startSrcLine,
endSrcLine, bindings}`, where `slackConsumed` is the total instructions absorbed
by gaps. A first-success/greedy walk can lock onto a valid-but-loose alignment
while a tighter one exists in the same body, corrupting the ranking and reported
span — so the matcher evaluates viable gap branches with memoized DP keyed by
`(instrIndex, patternIndex, bindings-signature)` to keep the bounded backtracking
from re-exploring states.

**Implementation note (correctness-critical):** register-variable binding lives
in a shared `vars` map that `matchOp` mutates operand-by-operand. Snapshot/restore
at gap branch points alone is **not sufficient** — a single failed candidate
instruction can leak a partial binding. `vars` must be treated as immutable match
state: clone it before *every* candidate `matchOp` attempt and commit only the
bindings of the chosen alignment.

This component, on its own, lets a user hand-write `lfs,*{0..3},fsubs,bne` and is
shippable/useful before any derive logic exists.

### Component 2 — Corpus opcode-frequency

Tally `opcode → count` over all instruction records in the Component 0 model
(one pass; operands stripped, labels/directives already excluded). Held in-memory
for the invocation; no on-disk cache. Derive mode is therefore explicitly
two-phase: build the model and the frequency table first, *then* select landmarks
and match — frequencies are available before landmark selection, not mid-scan.
Used by Component 3 to rank ops by rarity.

### Component 3 — Derive-from-target (`opseq --like <func>[:start-end]`)

1. Locate `<func>`'s body in the Component 0 model. If a `:start-end` range is
   given, restrict to that window — this directly serves the "stuck on one spot"
   case behind friction (1). **Range coordinates are absolute asm-file line
   numbers** (the same coordinate opseq itself prints and `extract get` shows),
   validated to fall within the function's body; an out-of-range value is a clear
   error.
2. Take the target's instruction records in order (labels already excluded).
3. **Landmark selection — control-flow anchored + rarity:**
   - **Always keep** control-flow opcodes as structural anchors: all branch
     forms (`b`, `beq`, `bne`, `blt`, `ble`, `bgt`, `bge`, `bl`, `bctr`,
     `bctrl`, `bdnz`, `bdz`, `bclr`/`blr` variants…) plus `mtctr` and `mtlr`.
     These are precisely what make loop / return / switch shapes come through.
   - **Rarity fill:** of the remaining (non-control-flow) ops, keep the rarest
     by corpus frequency (Component 2), filling toward a total landmark target
     (`--max-landmarks`, default `12`), so distinctive instructions survive and
     ubiquitous filler (`mr`, `nop`, `li`, `addi`, …) drops out naturally without
     a hand-curated denylist.
   - **Cap precedence (resolves the anchors-vs-cap tension):** control-flow
     anchors are always retained even if they alone exceed `--max-landmarks`; the
     cap governs only how much rarity fill is added (zero fill once anchors meet
     or exceed it). A branch-heavy selection therefore yields a longer, *more*
     specific pattern, not dropped anchors. If that range is too branch-dense to
     be useful, the user narrows it with `:start-end`.
   - Everything not kept collapses into a gap.
4. **Emit the pattern:** landmarks in order, with `*{0..gap+slack}` between
   consecutive landmarks, where `gap` is the observed filler count and `slack`
   defaults to `2` (`--slack N`). Lower bound `0` tolerates the scheduler
   removing/relocating filler; the upper bound tolerates a few extra. The derived
   pattern is **printed** before results so it is transparent and hand-editable.
5. **Specificity guard (against over-matching):** a pattern made only of common
   control-flow opcodes (e.g. `cmpwi,beq,bl,b`) with slack gaps matches a huge
   share of functions. Before running, estimate selectivity from the landmarks'
   corpus frequencies; if the pattern lacks any sufficiently-rare non-control-flow
   landmark, the derive step (a) prefers retaining the rarest available non-CF op
   even past the nominal fill target, and (b) warns, reporting the rarest
   landmark's corpus frequency as a selectivity proxy, so the user knows the
   result is broad rather than precise.
6. v1 derives **opcode-only** landmarks (no operands): operands vary across
   structural cousins, so binding them would over-constrain. `--with-operands`
   opts in by emitting register operands as **consistency variables** (matching
   the existing operand semantics — same physical register reused across
   landmarks → same variable, enforcing the reuse *pattern*, not literal register
   names), while immediates, displacements, and labels are emitted as `_`.
7. Run the derived pattern through Component 1 and print results.

### Component 4 — Result ranking

Each result is the **best alignment per function** from Component 1 (so the same
logical match is never reported from multiple overlapping start lines).
**Primary sort by `slackConsumed`** (the tightest structural match first), then by
function size ascending (current behavior as tiebreak). Keep the existing
`--candidates` matched/unmatched filter. For each hit, report the matched span
(`startSrcLine`–`endSrcLine`) so the user can judge how tight the match is.

## Operand grammar (clarification of existing + new semantics)

The current matcher has **no literal operands**: a non-`_` operand token is a
*consistency variable* — its first occurrence binds whatever register/value
appears there, and later occurrences of the same token must match that binding.
`_` is don't-care. This spec preserves that exactly; it does not add literal
operand matching (noted as possible future work). `--with-operands` derivation
(above) emits register operands as such consistency variables and everything else
as `_`, so derived patterns match the register-*reuse* shape, not specific
registers.

## CLI Surface

- `opseq <pattern>` — unchanged invocation, now accepts gap tokens (`*`,
  `*{m..n}`, `*{m..}`, `?`). Backwards compatible: patterns with no gap tokens
  behave exactly as before.
- `opseq --like <func>` / `opseq --like <func>:start-end` — derive a pattern and
  run it. The derived pattern is always printed.
- Flags: `--gap-cap N` (default 6), `--slack N` (default 2, derive mode),
  `--max-landmarks N` (default 12, derive mode), `--with-operands` (derive mode,
  default off), plus existing `--candidates`.
- **Shell-safety:** `*`, `?`, and `{…}` are shell glob/brace metacharacters, so
  patterns must be quoted (`melee-agent opseq 'lfs,*{0..3},fsubs'`). All docs and
  usage text will show quoted patterns, and the command emits a helpful error
  when the received argument count suggests an unquoted pattern was expanded by
  the shell.

## Testing

Go tests in `tools/table-typer` (new `*_test.go`):

- **Parser:** `*{m..n}`/`*{m..}`/`*`/`?` tokenize correctly under the top-level
  comma split; explicit upper bound over the ceiling is rejected; a pattern with
  a leading or trailing gap is rejected.
- **Matcher:** gap windows, labels inside gaps not counting toward budget, the
  hard ceiling, and — critically — register-variable `vars` correctness under
  backtracking (a binding from a failed *single-instruction* candidate, not just
  a failed gap branch, must not leak).
- **Function boundary:** a pattern that would only match by spanning `.endfn`/`.fn`
  must NOT match (Component 0 confines matching to one body).
- **Best-vs-greedy ranking:** a body admitting both a loose and a tight alignment
  reports the tight one (correct `slackConsumed` and span).
- **Overlapping starts:** a body where the alignment is reachable from several
  filler start lines yields exactly one deduplicated result.
- **Frequency:** opcode tally over a small fixture asm set.
- **Landmark selection:** derive on a known function — assert control-flow ops
  are kept, ubiquitous filler is dropped, anchors are retained even past the cap,
  and the specificity guard warns on an all-common-branch pattern (golden
  pattern).
- **`--with-operands`:** derived register operands bind as consistency variables;
  immediates/labels become `_`.
- **End-to-end / back-compat:** derive from a known matched function and assert
  the run finds itself plus at least one known structural cousin; assert a
  gap-free pattern behaves exactly as the pre-change tool.

## Risks & Mitigations

- **Precision collapse from gaps** → gaps bounded by default (`CAP`), no
  leading/trailing gaps, results ranked by least slack, control-flow anchoring +
  the specificity guard keep patterns selective.
- **Over-matching from common-branch-only derived patterns** → specificity guard
  reports a rarest-landmark frequency proxy, retains the rarest non-CF landmark,
  and warns.
- **Backtracking / large-gap blowup** → every upper bound clamped to the hard
  ceiling, oversized patterns rejected, memoized DP avoids re-exploring states.
- **Matching across function boundaries** → Component 0 confines every match to a
  single function body; covered by a boundary test.
- **Register-var binding corrupted by backtracking** → `vars` cloned before every
  candidate match (not just gap branches); covered by a dedicated test.
- **Landmark heuristic picks poorly** → thresholds (`--gap-cap`, `--slack`,
  `--max-landmarks`) are tunable, the derived pattern is printed for hand-editing,
  and manual pattern mode (Component 1) is always the fallback.

## Build Sequencing

1. Component 0 (normalized asm model) + Component 1 (bounded-gap matcher) +
   parser/matcher/boundary tests — independently useful; users can hand-author
   gap patterns immediately.
2. Components 2 + 3 + 4 (frequency, derive-from-target, ranking) + tests.
3. Update `.claude/skills/opseq/SKILL.md` (document gap tokens and `--like`) and
   regenerate the capability index (`melee-agent capabilities generate`).
