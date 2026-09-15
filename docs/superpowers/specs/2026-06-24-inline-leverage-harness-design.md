# Inline-Leverage Measurement Harness — Design

- **Date:** 2026-06-24
- **Status:** Approved design, pre-implementation. **Revision 2** — incorporates an independent Opus 4.8 review (4 blockers + 4 majors resolved below).
- **Scope:** Fork-local tooling (`melee-agent`). Not upstream-bound.

## 1. Motivation

The working hypothesis was: "many blocked functions are resolved by inline
functions, so we should make the permuter/search better at generating realistic
inline shapes." Before building a generator, we stress-tested that premise on
`fn_8024ECCC` (`src/melee/mn/mndatadel.c`), which an upstream PR reworked with a
new `static inline mnDataDel_GetWarnData()`.

Measured (three builds in our fork):

| Variant | Match % | Note |
|---|---|---|
| Our fork (no inline) | 97.70 | blocker = data-symbol + stack + r29/r30 |
| + upstream inline **only** | 97.70 | identical fingerprint — inline is codegen-neutral |
| Upstream's **full** file | 99.62 | `normalized_diff_lines=0`, `truth=structural-match` |

The inline moved the match **0.00%**. The real lever was data/struct-overlay work;
the last 0.38% is a backend `stack-slot-layout` tie-break. What *looked* like
"PAD_STACK + `_pad` ⇒ missing inline" was a data + stack-slot problem, and the
inline was a readability refactor wearing a costume.

**Conclusion:** the inline-as-a-matching-lever population may be much smaller than
the inline-*shaped-looking* population. Measure before building. This harness is
that instrument.

## 2. Goal, estimand, and external validity

For each already-matched function that calls a real `(static) inline`, **de-inline**
the call (expand the inline body in place), recompile, and measure whether the
match regresses — **structurally**, not just in fuzzy byte-%.

**Estimand (be precise about what we measure):**
> `P(inline is a codegen lever | inline is present in a matched function)`

This is a **proxy** for the quantity we actually care about:
> `P(a missing inline is the blocker | function is blocked)`

These differ, and the gap is a known limitation (Major #5 from review):
- **Selection bias.** The corpus is functions whose inlines the author already got
  right *and which match*. Codegen-neutral readability inlines are over-represented
  here (an author can leave a neutral inline in a function that matches regardless),
  which biases the measured lever-rate **down** relative to the blocked population.
- **Mitigation / transfer check.** Report the proxy honestly as a proxy, and add a
  secondary, smaller validation against historical *blocked-then-cracked-by-inline*
  cases (contributor diffs where adding an inline moved the match) to sanity-check
  that levers found on matched code resemble real blockers. We do not claim the
  proxy equals the target; we claim it bounds and informs it.

**Primary output:** a **lever-rate**, reported two ways (strict and permissive, see
§5/§11), **bucketed by inline shape**. The shape breakdown is the decision-driving
artifact: which shapes (if any) are high-leverage enough to justify a generator.

## 3. Why this is the right instrument

- **Inverse of the generator.** Functions that *structurally* regress when
  de-inlined are the distribution a generator would need to reproduce.
- **Non-circular.** The matched version is ground truth.
- **Calibratable.** Synthetic known-neutral and known-lever fixtures (§10) let us
  detect the harness's own confounds before trusting any real number.

## 4. Non-goals (v1)

- The inline **generator** / proposer.
- The grounded inline **corpus** (header scrape, matched-code statement-run mining).
- Header-inline **retrieval**.
- Cracking `fn_8024ECCC`'s residual 0.38% (a separate decl-order/steering task).

Measure first. The generator is a follow-up project gated on this harness's output.

## 5. Architecture / pipeline

Unit of measurement = **(function, inline)**: all call sites of one inline *within
one matched function* are de-inlined together (models "this inline does not exist"
for that function). An inline used by several functions is measured once per caller.
(Limitation: if only some sites are reachable, the all-or-nothing unit can
mis-attribute; acceptable for v1, recorded.)

1. **Select corpus.** Functions with `fuzzy_match_percent == 100`. **Recompute the
   baseline in the same build pass** — do not trust the cached `report.json` value,
   which can be stale. Default scope is `--module`, not repo-wide (§9, scale).
2. **Detect.** For each corpus function, find the `inline`/`static inline`
   definitions it calls and resolve their bodies. **Detection must search the TU
   *and its transitively-included project headers*** — 195 `static inline` defs live
   across 35 headers (`include`d, shared across TUs), vs 1086 in `.c`. Record
   `def_location ∈ {tu, header}` as a first-class field. (`source_patch
   .find_function_definitions` scans a single TU's text only and is insufficient on
   its own; header resolution is required — see §7.)
3. **De-inline.** Replace every call site of that inline *within that function* with
   the inline body (params → args). **Leave the definition in place** — this is
   codegen-safe regardless of `def_location`: an unreferenced `static inline` is not
   emitted, and a def still referenced by *other* call sites in the TU is emitted
   identically to baseline. (Verify residual-liveness invariance rather than
   asserting it; flag non-`static` inline as a separate case.)
4. **Score on BOTH axes.** Compile + checkdiff. Record `delta_fuzzy` (Δ
   `fuzzy_match_percent`) **and** `delta_struct` (Δ `normalized_diff_lines`, which
   checkdiff emits). This split is essential: a de-inline that perturbs only
   register/stack *coloring* moves fuzzy-% while `normalized_diff_lines` stays 0 —
   that is a **backend tie-break, not an inline-shape lever**, and the project
   explicitly treats such things as not source-realizable. Non-compiling variants →
   `deinline_failed`.
5. **Classify.**
   - `lever` (strict) ⇔ `delta_struct > 0` (the inline boundary changes the
     *structural* diff). This is the headline lever.
   - `fuzzy_only` ⇔ `delta_fuzzy > ε` but `delta_struct == 0` (backend
     coloring/scheduling tie-break; reported separately, **not** counted as an
     inline-shape lever).
   - `neutral` ⇔ `|delta_fuzzy| ≤ ε` and `delta_struct == 0`.
   - `unsupported` ⇔ shape the de-inliner cannot faithfully express (counted for
     coverage, never silently dropped).
   - `deinline_failed` ⇔ produced non-compiling C (excluded from rate denominators).
6. **Shape-tag.** return class (`void`/`scalar`/`pointer`/`struct`), body kind
   (`single_return_expr`/`multi_statement`), arg kinds (field-access/pointer/
   literal/plain-id), statement count, call-site count, `def_location`, and
   `expansion_form` (see §6 — `value_expr` vs `statement_splice`).
7. **Aggregate.** Headline strict & permissive lever-rates + per-shape breakdown,
   with `deinline_failed`/`unsupported` reported **per bucket** (§11).

## 6. The de-inliner (the crux, and the bulk of the build)

This substitution engine is a **first-class new deliverable built on tree-sitter
(`ast_walker`)**, not an extension of an existing primitive. (The review confirmed
`helper_extract.py::inline_simple_helper_call` only emits a pre-baked
`replacement_line` for scalar, single-`return`, identifier/int-literal-arg helpers —
it cannot express pointer/struct returns, field/pointer args, or statement bodies.
We borrow its *constraint vocabulary*, not its code.)

**Two expansion forms, tracked separately because they carry different confound
risk:**
- **`value_expr`** — a value inline used in an expression/assignment, body is a
  single `return <expr>;`. Expansion substitutes the return expression with params →
  args, **introducing no new scope, no temp, and no extra parenthesization
  beyond what the grammar requires**. Low artifact risk — closest to a faithful
  inverse of MWCC's inliner.
- **`statement_splice`** — a void/statement-bodied inline called as a statement.
  Expansion splices the body, which *requires* a fresh `{ }` scope to host the
  body's locals and avoid name collisions. This new scope/decl placement is itself a
  known MWCC codegen lever (decl order, block scope), so a `statement_splice` delta
  is **expansion-form-contaminated** and is reported in its own bucket, never pooled
  with `value_expr` in the strict rate.

**The faithful-inverse problem (Blocker #1).** "Behavior-preserving" ≠
"codegen-identical to what MWCC's own inliner emitted." Source-level textual
expansion can introduce artifacts (scope, temps, decl placement, parenthesization)
that move codegen for reasons unrelated to the inline boundary, minting false
levers. Three defenses:
1. **Structural classification** (§5.5): require `delta_struct > 0` for a strict
   lever; this filters pure coloring artifacts, the largest false-lever source.
2. **Form separation** (above): `statement_splice` deltas are quarantined and
   flagged as expansion-sensitive.
3. **Identity calibration** (§10): synthetic fixtures prove a known-neutral inline
   classifies `neutral` and a known-lever inline classifies strict `lever`. As a
   stretch calibration, a round-trip (de-inline then re-collapse) that does not
   reproduce the byte-identical baseline marks that shape's engine as unfaithful and
   demotes its results to `unsupported`.

**Hygiene / `unsupported` routing.** Inlines with their own control flow, multiple
`return`s, or varargs → `unsupported`. Arguments that are used more than once in the
body and are **either side-effecting or non-trivial/expensive expressions** →
`unsupported` (duplication changes evaluation/CSE and thus codegen, even when
behavior is preserved). Every variant is compile-checked; non-compiling →
`deinline_failed`.

## 7. Reuse map (corrected per review)

| Need | Status | What we actually reuse |
|---|---|---|
| Structure: defs, call sites, bodies, params, types | reuse | `ast_walker.py` (tree-sitter, importable, confirmed). **Header-aware** def resolution is new. |
| Single-TU def listing | partial | `source_patch.find_function_definitions` — TU-only, no header resolution; insufficient alone. |
| Substitution engine | **new** | Greenfield on tree-sitter. We borrow only the *constraint vocabulary* of `helper_extract.py` (what shapes are safe), not its code. |
| Compile + score | reuse | `candidate_verify.verify_real_tree_patches` (writes patched TU, runs checkdiff, computes Δ, restores) + `tools/checkdiff.py`. NB: it overwrites the whole TU and runs a full build per variant — see scale (§9). |
| Storage | reuse | `source_transform_mining.py` SQLite ledger (new `inline_leverage` table); mirror its `skipped_ledger_hits` content-hash skip for caching. |

## 8. Data model

New table in the transform-mining SQLite ledger:

```
inline_leverage(
  id              INTEGER PRIMARY KEY,
  run_id          TEXT,
  function        TEXT,
  unit            TEXT,        -- TU path
  inline_name     TEXT,
  def_location    TEXT,        -- tu | header   (which file defines the body)
  def_file        TEXT,        -- file:line of the definition
  is_static       INTEGER,
  n_call_sites    INTEGER,     -- sites de-inlined in this function
  baseline_pct    REAL,        -- recomputed fresh in this run (NOT from report.json)
  deinlined_pct   REAL,
  delta_fuzzy     REAL,        -- baseline_pct - deinlined_pct
  baseline_ndl    INTEGER,     -- baseline normalized_diff_lines
  deinlined_ndl   INTEGER,
  delta_struct    INTEGER,     -- deinlined_ndl - baseline_ndl
  verdict         TEXT,        -- lever | fuzzy_only | neutral | unsupported | deinline_failed
  expansion_form  TEXT,        -- value_expr | statement_splice
  shape_return    TEXT,        -- void | scalar | pointer | struct
  shape_body      TEXT,        -- single_return_expr | multi_statement
  shape_args      TEXT,        -- JSON list of arg kinds
  n_statements    INTEGER,
  error           TEXT,        -- reason for failed/unsupported
  created_at      TEXT
)
```

Note: `has_control_flow` is **not** a `shape_body` value — control-flow inlines are
`unsupported` (coverage gap), never scored.

## 9. CLI surface, scale, and isolation

```
melee-agent debug measure inline-leverage [OPTIONS]

  --module TEXT       Module prefix (e.g. mn). DEFAULT (repo-wide is opt-in).
  --file PATH         One TU.
  --function TEXT     One specific function. Bypasses the fuzzy==100 filter
                      (classification is delta-based). Validation/debug use.
  --all               Explicit opt-in for a repo-wide run (see scale below).
  --epsilon FLOAT     Fuzzy threshold for the `fuzzy_only`/`neutral` split (0.05).
  --json / --report   Machine-readable / human summary.
  --run-id TEXT       Ledger label.
```

**Scale (Major #6).** There are ~18,900 `fuzzy==100` functions, and the scoring
primitive overwrites the whole TU and runs a full `ninja`+checkdiff per variant,
serially (in-place TU mutation races parallel runs — the documented worktree
hazard). Therefore:
- Default is `--module`; repo-wide requires `--all` and is expected to be a long,
  ledger-cached batch.
- **Cache** keyed on `(TU content hash, function, inline)` so re-runs skip unchanged
  units (mirror `source_transform_mining`'s skip pattern).
- Run in an **isolated worktree** (never the shared main checkout).
- Batch by TU where possible (detect all target inlines per TU, recompile once for
  detection) and document an order-of-magnitude runtime budget in the README.

## 10. Validation plan (does not depend on any mutable source file)

The motivating anchor `mnDataDel_GetWarnData` is **not in the committed tree** (it
lives only in an uncommitted upstream variant) — so validation must not depend on
it (Blocker #4).

1. **Synthetic fixtures (primary).** Hand-author a tiny TU committed under the test
   suite with: (a) a trivial accessor inline that is known codegen-neutral → must
   classify `neutral`; (b) a body-with-locals inline that is a verified structural
   lever → must classify strict `lever`. These run with no repo build dependency and
   directly calibrate the §6 confound defenses.
2. **Substitution unit tests.** param→arg substitution, capture-avoiding scope
   handling for `statement_splice`, hygienic routing of multiply-used side-effecting/
   expensive args to `unsupported`, dead-def handling — synthetic inputs, no build.
3. **Optional integration anchor.** *If* the upstream `mndatadel.c` is present, the
   `GetWarnData` de-inline (`--function fn_8024ECCC`) must classify `neutral`
   (`delta_struct == 0`, `|delta_fuzzy| ≤ ε`). Skipped (not failed) when the file is
   absent.
4. **Transfer check (Major #5).** Sample historical blocked-then-cracked-by-inline
   functions; confirm the harness, run against the pre-crack source, flags the added
   inline as a structural lever. Sanity-checks proxy→target transfer.

## 11. Output / report

Headline (per scope), with strict and permissive rates and honest coverage:
```
inline-leverage (module=mn): N (function,inline) pairs across M functions
  lever (strict, structural):    X   (xx% of scored)
  fuzzy_only (backend tie-break): F  (reported, NOT an inline-shape lever)
  neutral:                        Y
  unsupported:                    Q   (coverage gap)
  deinline_failed:                P   (excluded from denominators)
  permissive rate (lever+fuzzy_only) = ...%   ← gap vs strict = confound size
```

Per-shape breakdown — and crucially, **failed/unsupported are shown per bucket** so
a high-failure shape isn't represented by a small lucky subsample:
```
shape (return/body/form)             n   lever%  fuzzy_only%  unsupported  failed  mean Δstruct
scalar/single_return_expr/value      ..  ..%     ..%          ..           ..      ..
pointer/single_return_expr/value     ..  ..%     ..%          ..           ..      ..
void/multi_statement/splice          ..  ..%     ..%          ..           ..      ..
struct/multi_statement/splice        ..  ..%     ..%          ..           ..      ..
```

## 12. Risks & mitigations

- **Faithful-inverse confound** (Blocker #1) → structural classification, form
  separation, synthetic calibration, optional round-trip demotion (§6).
- **Header-defined inline population** (Blocker #2) → header-aware detection,
  `def_location` field, split reporting; `leave-def` proven codegen-safe by
  residual-liveness, not assumed.
- **Substitution is greenfield** (Blocker #3) → budgeted as the bulk; reuse map
  corrected; rich shapes are the hard, primary work.
- **Validation can't depend on an absent file** (Blocker #4) → synthetic fixtures.
- **Selection bias / external validity** (Major #5) → stated estimand as a proxy;
  transfer check against blocked-then-cracked cases.
- **Scale** (Major #6) → `--module` default, content-hash cache, isolated worktree,
  TU batching, documented budget.
- **Failure not missing-at-random** (Major #7) → per-bucket failed/unsupported.
- **Fuzzy/structural conflation** (Major #8) → score both axes; strict lever needs
  `delta_struct > 0`.
- **Stale cached baseline** → recompute baseline fresh in the run; never use
  `--no-build` for a variant (yields `match_percent=unknown`); pin the checkdiff JSON
  field read (`fuzzy_match_percent`).

## 13. Decisions locked

- Classify on **both** fuzzy and structural; strict `lever` requires
  `delta_struct > 0`; `fuzzy_only` reported separately as a backend tie-break.
- De-inliner is a **new tree-sitter engine**; `value_expr` and `statement_splice`
  forms tracked separately; `statement_splice` quarantined from the strict rate.
- Detection is **header-aware**; `def_location` recorded; `leave-def` retained
  (codegen-safe by residual-liveness).
- Corpus = `fuzzy==100`, baseline **recomputed fresh**. Default scope `--module`;
  repo-wide is `--all`, cached, in an isolated worktree.
- Validation uses **committed synthetic fixtures**; `GetWarnData` is an optional,
  skippable integration anchor.
- `deinline_failed` excluded from denominators; `unsupported` and failures reported
  **per shape bucket**.
- Estimand is an explicit **proxy** for the blocked-function quantity; transfer
  checked against historical inline cracks.
- Generator/corpus/retrieval remain **follow-up**, gated on this harness's output.
```
