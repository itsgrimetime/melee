# mwcc-debug roadmap — 2026-05-20

Single-page consolidation of "what's next" for the mwcc-debug toolset.
Replaces the scattered references in feedback docs, validation
studies, and `mwcc-debug-future-ideas.md`.

Items grouped by priority + dependency. Within each group, ordered
roughly by impact.

---

## Recently shipped (the floor)

For context — these landed between 2026-05-18 and 2026-05-20 and
established the current capability.

- Tree-sitter-based **nested-block-local awareness Phase 1** (this
  doc's spec: `2026-05-20-nested-block-local-awareness-design.md`).
  Bridge sees nested decls; `var-to-virtual`/`virtual-to-var` emit
  scope paths; nested bindings ship as `ambiguous-nested` confidence
  (22% accuracy on empirical study — see validation doc).
- **`debug suggest-coalesce-source`** — pair + discover modes, 5
  pattern checkers, calibration corpus (multi-holder cascade
  enumeration in `analyze_cascade`).
- **`verify-perm` 3-way merge + placeholder leak guard** —
  `inline_fn`/`noinline_fn`/etc. permuter-internals are detected
  before they corrupt real source.
- **`verify-with-name-magic`** — by-value mapping +
  `--apply-auto` + `--globalize` default-on.
- **`ceiling` auto-verify** — HIGH-severity cast suggestions get
  drop+compile+revert verification before reporting `WIN AVAILABLE`.
- **`pcdump-local`** improvements: function-scoped `--diff`,
  content-hash freshness check, force-flag-aware cache skip,
  `--keep-obj` missing-file warning, hang diagnostic for
  `--force-coalesce`.
- **`tier3-search` v2** — per-seed permuter wiring,
  `--per-seed-time`, `--total-time`, `--threshold`, `--apply-best`.
- **`checkdiff`** — JSON exit normalization, `--normalize-reloc`
  default-on for SDA21 `+2` offset folding.
- **CLI ergonomics** — `name-magic` `--globalize`,
  `suggest-casts --signedness`, `match-iter-first --auto-verify`,
  `suggest-coalesce-source` preflight, mwcc-debug skill text
  refresh.

---

## Next up: Phase 2 of nested-block-local awareness

Phase 1 surfaced nested decls in the bridge. Phase 2 lets the
mutator + decl-order enumerator act on them.

### P2.1: `mutate insert-alias` scope-aware insertion (HIGH)
- Currently: alias decl always goes at function-top; alias
  assignment at the original insertion point. C89 split logic
  added in Round 7 for cases where the local is first-assigned
  later.
- Phase 2: place alias decl at the **nearest enclosing block**
  identified by the target use's `scope_path`. Alias assignment
  stays at the use site. Lets mutators target nested-block
  locals without inflating the outer scope.
- Depends on: Phase 1's `LocalDecl.scope_byte_range` (already
  populated).

### P2.2: `enumerate-decl-orders` scope-aware (MEDIUM)
- Currently: enumerates permutations of top-level locals only.
- Phase 2: walk `BindingBasis.decls_by_scope`; enumerate swaps
  **within-scope only** (cross-scope swap would change
  semantics — illegal). Surfaces the cursor-row/jobjs[17]-block
  swap candidates the heartbeat agent's been blocked on for
  fn_80248A78.
- Depends on: P2.1 indirectly (decl reorder mechanics align with
  alias placement).

### P2.3: tier3-search seeding from compiler-temp facts (MEDIUM)
- Currently: tier3 only seeds from bridge-bound variables. With
  Phase 1 the bridge sees more, but compiler temps (no source
  binding at all) still aren't seedable.
- Phase 2: feed `suggest-coalesce-source --discover` pairs and
  `guide` compiler-temp diagnostics into tier3's seed planner.
  Targets the "found a useful pair but can't generate a seed"
  gap heartbeat flagged on fn_80248A78 (`46=50`).

### P2.4: Per-scope ordinal heuristic v2 (LOW, needs research)
- Empirical study (`docs/mwcc-debug-nested-block-validation-...md`)
  showed the v1 heuristic holds 22% of the time on nested decls.
- Phase 2 may investigate: lifetime-based scope correlation
  (virtual whose first-def block is reachable only from a
  scope-entry block belongs to that scope), or a hybrid that
  consults `extra-virtuals` red flag and per-scope use-site
  density. Until then `ambiguous-nested` is the honest label.
- Could also be punted to Phase 3 — Phase 2 work above doesn't
  block on this.

---

## Larger features (own spec each)

### `debug suggest-inlines` / extract-subroutine seed mode (HIGH)
- Source: heartbeat feedback, "Inline/extract-subroutine tooling
  gap" section.
- Enumerate repeated/helper-shaped statement groups; generate
  `static inline` candidates; transfer each into the TU; rank by
  `checkdiff` + pcdump score.
- Depends on Phase 2 nested-block awareness for placement (inline
  candidate insertion needs scope-aware decl placement).
- Seed sources: `patterns inlines`, `suggest-coalesce-source
  --discover`, `guide` compiler-temp facts, repeated pcdump
  load/store blocks, known inlined callees.
- Heartbeat agent ranks this as the next big matching unlock
  after nested-block awareness lands.

### `suggest-casts --signedness` multi-hop refinement (LOW-MEDIUM)
- Round 6 added `--signedness` detection (`cmplwi` vs `cmpwi`).
- mndiagram3 agent reported the real win was a **two-hop**
  change: `u8 limit → unsigned int limit → int limit` for
  +0.26%+0.13%. The widen-u8-to-u32 pattern catches hop 1; the
  new signedness check catches hop 2. Need to verify the
  heuristic fires on the real diff (we haven't tested on the
  mndiagram3 case yet) and surface multi-hop sequences as a
  combined recommendation.

### Relocation `+2` SDA21 normalizer — extension (LOW)
- Round 4 shipped `checkdiff --normalize-reloc`. Default-on.
- Open: agent reports some functions still have leftover
  relocation-only mismatches after the normalizer. Investigate
  whether more reloc shapes need folding (R_PPC_ADDR16_HA/LO
  pairs, etc.).

---

## Medium correctness / UX gaps

These were flagged in feedback but deferred during the 8 rounds of
fanout fixes — small enough that a dedicated spec is overkill, but
big enough to need design thought.

### Permuter `inline_fn` upstream patch (LOW)
- Round 8 shipped `verify-perm`'s placeholder-leak guard. The
  underlying bug is in decomp-permuter's randomizer
  (`get_noncolliding_name(ast, "inline_fn")` in
  `decomp-permuter/src/randomizer.py:2344`).
- Upstream patch to make the randomizer always resolve placeholders
  before persisting candidate `source.c` would be cleaner than
  catching the leak downstream. Defer until upstream contact.

### Pre-match calibration case for suggest-coalesce-source (LOW)
- Currently calibration corpus has 2 cases; the discover-mode case
  uses a **post-match** fixture that yields 0 candidates, so the
  test only checks `cascade.length >= 6` (weak regression signal).
- Flagged as a session-spawn chip earlier in this session.
- Capture a pre-match snapshot of an mn-module function (e.g.
  pre-`s32 j` reorder of mnVibration_80248644), add as case 3 with
  concrete `expected_top_priority_class` + `expected_top_pair`.

### `--force-phys` class-scoped form regression (LOW)
- Round 7 shipped `gpr:N:phys` parsing; Round 8 added a warning
  when the form is used because the DLL strips the prefix
  unconditionally and applies the override to all classes.
- Real fix needs DLL change: pass class through to the override,
  filter by class inside the hook. Out-of-scope for current
  workflow tooling work. Track on the `mwcc-debug-future-ideas`
  side.

### Ninja post-compile name-magic step (LOW)
- Round 2's name-magic `--apply-auto` is a CLI helper.
- Spawned task chip earlier this session: wire into ninja so
  every `.o` post-compile gets auto-renamed without manual
  invocation. Wider workflow change — keep deferred until name
  needs aren't satisfied by manual `--apply-auto` invocations.

---

## Small wins / docs cleanup

### `virtual-to-var --basis` symmetry (TRIVIAL)
- `var-to-virtual` has `--basis`; `virtual-to-var` doesn't.
- Either add `--basis` to `virtual-to-var` for symmetry or
  document the asymmetry in skill text.
- Round 1 of docs fixes confirmed the skill currently doesn't
  claim `virtual-to-var --basis` exists, so this is a real
  feature-add not a doc-fix.

### `debug root-identity` skill reference cleanup (TRIVIAL)
- Skill mentions `root-identity` but no such command exists.
- Either ship the command (low priority — agent hasn't said
  it's blocking) or remove the reference. The latter is what
  Round 1 confirmed; the reference is already absent from the
  in-repo skill but may still be referenced in handoff docs.

### `enumerate-decl-orders --include-low-confidence` parity (TRIVIAL)
- Round 7 added `ambiguous-nested` to `tier3-search`'s opt-in
  set. `enumerate-decl-orders` doesn't have the same opt-in;
  it only enumerates `kind=="local"` bindings regardless of
  confidence. Verify whether nested-block locals are reaching
  it now that Phase 1 surfaces them.

---

## Punted (with reasoning)

### C semantic analyzer (PUNTED)
- Spec § "Out of scope" — Phase 1 stays lexical. Resolving
  shadowing, type inference, full preprocessor expansion would
  be a multi-month effort. Tree-sitter + cursor heuristic gets
  us 90%+ of the value at 5% of the cost.

### Per-iter workingMask in colorgraph hook (PUNTED)
- `mwcc-debug-future-ideas.md` Tier 2.5 note. Would need an
  in-loop hook (much more invasive). Marginal value — we can
  already reason backwards from COLORGRAPH DECISIONS output.

### Per-function decompiled-source caching (PUNTED)
- Earlier session idea. Bridge is already fast enough with
  Phase 1's ast_walker cache; full source cache adds little.

---

## Live spawn-task chips (from this session)

These were flagged as user-facing chips during the work — they
may already be queued for spinning off into separate sessions:

1. **Pre-match calibration case for discover-mode** (suggest-coalesce-source).
   Covered above under "Medium gaps."
2. **Wire `verify-with-name-magic --apply-auto` into ninja
   post-compile** (Round 2 follow-up). Covered above under
   "Ninja post-compile name-magic step."

If you've dismissed them, they're effectively here only.

---

## How to decide what's next

- **For matching unlocks today:** P2.1 + P2.2 (mutate insert-alias
  + enumerate-decl-orders scope-aware). Heartbeat agent has been
  blocked on fn_80248A78's nested cursor block for this.
- **For broadest leverage:** `debug suggest-inlines`. But it
  depends on Phase 2 above, so don't start there yet.
- **For test corpus health:** pre-match calibration case for
  suggest-coalesce-source. Low effort, locks in a real regression
  signal.

## Source documents (kept around for detail)

- `docs/superpowers/specs/2026-05-20-nested-block-local-awareness-design.md` — Phase 1 spec, includes Phase 2 candidate list at §"Out of scope"
- `docs/superpowers/plans/2026-05-20-nested-block-local-awareness.md` — Phase 1 plan (executed)
- `docs/mwcc-debug-future-ideas.md` — broader Tier 1-7 roadmap; most items marked ✅ DONE
- `docs/mwcc-debug-nested-block-validation-2026-05-20.md` — 22% accuracy finding
- `docs/mwcc-debug-nested-block-macro-tolerance-2026-05-20.md` — 0% fallback baseline
- `decomp/mndiagram3:mwcc-debug-feedback-5-20-2026.md` — agent feedback (mostly addressed)
- `wip/mn-heartbeat:mwcc-debug-feedback-5-20-2026.md` — agent feedback (mostly addressed; "Inline/extract-subroutine tooling gap" section is the source of the `suggest-inlines` feature request)
