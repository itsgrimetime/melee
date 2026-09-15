# Tooling-Backtest Harness — Design

- **Date:** 2026-06-26
- **Status:** Approved design, pre-implementation. **Revision 1** — incorporates an independent Opus 4.8 review (3 blockers + 4 majors + minors, all resolved below).
- **Scope:** Fork-local tooling/measurement (`melee-agent`). Not upstream-bound.
- **Calibration reference:** `2026-06-24-inline-leverage-harness-design.md` (sibling measurement-harness; its §2 estimand and §10 fixtures are the patterns mirrored here).

---

## 1. Problem & Goal

We have 150+ CLI subcommands and ~20 skills for matching Melee functions, but no
**measurement** of what that tooling can actually solve. For a given class of matching
problem, we don't know whether our tooling would lead an agent to the fix or leave them
stuck.

This project also has a documented failure mode — the *give-up bias* — where an agent
runs an equivalence-test to *dismiss* a contributor's diff instead of *reading it for the
lever* (`fjooord_diagram_prs_improve_not_match.md`,
`debug_tooling_induces_premature_giveup.md`). Real matches found by humans via simple
levers were repeatedly written off as "ceilings."

**Goal:** Build a backtest harness that, for each historical commit that took a function
from non-matching → matching with a small isolated change, reconstructs the pre-match
state in an isolated sandbox, runs our tooling *blind to the answer*, and **scores whether
the tooling would have led an agent to that fix**. Output: a coverage matrix (lever-class
× tooling-tier) plus an auto-feedback loop that files issues and stages new pattern-DB
entries for confirmed gaps.

### Reframe vs. existing tooling
The mining tools (`mismatch backfill`, `patterns`, the source-transform mining ledger,
`audit discover-prs`) all **mine patterns out of solutions**. This harness does the
inverse: it measures whether the tooling can **rediscover a solution it is blind to**. The
mining tools become *components*; the backtest scoring loop is the new artifact.

---

## 2. Estimand & external validity (what the number actually means)

The corpus (§4) is *commits that took a function to matching with a small isolated change*
— i.e. **problems a human already solved with a small lever**. Be precise about what we
therefore measure:

**Estimand:**
> `P(tooling leads to the fix | a small-lever match for this function exists in history)`

This is a **proxy** for the quantity we actually care about:
> `P(tooling leads to the fix | function is currently blocked)`

These differ; the gap is a stated limitation:
- **Selection bias.** The corpus systematically excludes (a) functions still stuck today,
  (b) fixes that needed a large/multi-function diff, (c) dead-ends and regressions. A high
  held-out coverage number therefore means *"our tooling can rediscover the easy,
  already-won levers,"* **not** *"our tooling owns X% of the matching surface."* The
  coverage matrix (§7) must be read and labeled with this caveat.
- **Mitigation / transfer note.** We report the proxy honestly as a proxy. Where a
  blocked-then-cracked function's pre-crack source is available, the same harness can be
  pointed at it as a transfer check — but the headline metric is bounded to the
  small-historical-win population and labeled as such. We do not claim the proxy equals
  the target; we claim it bounds and informs it.

---

## 3. Validity controls (the credibility backbone)

Two ways the harness can produce false results; both designed around explicitly.

### 3.1 Contamination / circularity
The `mismatch` DB and the source-transform mining ledger were *built from history*.
Testing them against a diff they were mined from is rigged — they "succeed" by
memorization, not generalization. Every case is labeled:
- **in-corpus** — the diff (or its lever pattern) is already represented in the mined DBs.
  A *regression test*: the tooling **should** reproduce it; a failure is a pure tooling bug.
- **held-out** — the tooling has never seen this diff. The *generalization test*.

**The headline metric is held-out coverage**; in-corpus is reported separately as a
regression baseline. *(Determining in-corpus membership requires querying the mismatch DB
and the mining ledger — see §11-Q3; the exact query is a pre-plan resolution item.)*

### 3.2 Blindness — leakage prevention, and a *provable* check
The answer is literally the next commit in git history; a blind agent (or a tool that
shells to git) could `git show` it. **Prevention alone is insufficient — we must test that
prevention works** (false-positive SOLVED verdicts are the lethal failure class, §10).

- The sandbox (§9) is materialized so the **answer commit `C` is provably unreachable**
  from inside it — not merely "history truncated." The harness asserts
  `git cat-file -e C` **fails** (object absent) / `C ∉ git rev-list --all` inside the
  sandbox before any case is scored. A sandbox that fails this assertion is dropped, not
  scored.
- The ground-truth diff is held out-of-band by the harness and used only for scoring;
  it is never placed in the sandbox or shown to the tooling/agent under test.

---

## 4. Corpus construction (structural ground truth)

1. **Enumerate candidate match commits.** Recent upstream history, **all authors**.
   Commits touching `src/melee/**/*.c`. Use commit-message / PR signals (`audit
   discover-prs` exists and is reused here) as a *cheap prefilter*, confirmed by ground
   truth below.
2. **Ground truth is STRUCTURAL, not fuzzy-% (M1).** Build the touched function at `C` and
   `C~1` and read `checkdiff`'s `normalized_diff_lines`. Keep the case only if it is a
   genuine structural flip: `normalized_diff_lines == 0` at `C` and `> 0` at `C~1`. Fuzzy
   `match_percent` alone is byte-noise and is not the gate. **Recompute both baselines
   fresh in the run; never trust cached `report.json`** (documented stale-value hazard).
3. **Confound guard (M1).** A commit can move a function's match via a shared header,
   struct, build-config, or caller change — in which case the in-function `.c` hunk is
   *not* the lever and handing it to the scorer would mislabel the case. So:
   - Attribute the flip to the in-function hunk by holding everything else at `C~1` and
     applying only the function's hunk; the flip must reproduce. If it doesn't (the lever
     lives in a header/struct/caller), the case is **re-labeled** with its true lever
     locus or **excluded** as not-singular — never scored against the wrong ground truth.
4. **Small / singular filter.** Flip attributable to a single function; diff ≤ ~30 changed
   source lines; ideally a single hunk. (Thresholds are tunable parameters, fixed in the
   plan.)
5. **Label each case:** `author ∈ {us, other}`; `provenance ∈ {in-corpus, held-out}`
   (§3.1); `lever_class` (§7).

Each surviving case: `(function, C, C~1, ground_truth_diff, lever_locus, labels)`.

---

## 5. Tooling-under-test surface (bind to the live CLI, not the brief)

The auto-generated capability brief lags the real CLI (it still lists a `debug solve` and a
`transform-corpus` command that **do not exist** in the current tree — confirmed via
`melee-agent` and `python -m src.cli`). **The harness must derive its tool list from live
`--help`, and the plan must bind intent → command against the real surface**, which is:

- **Advisory (does the tooling *name* the lever?):** `mismatch search`, `debug suggest`
  ("source-shape and mismatch fixes"), `debug inspect` (pcdump explain), `opseq` (nearest
  matched neighbours; a CLI alias to `tools/table-typer`), `patterns` (idiom/wrapper
  discovery).
- **Generative (does the tooling *make* the change?):** `debug mutate`, `debug search`
  (fast+directed substrate), `debug coalesce-search`, `debug select-order-search`,
  `debug intervene` (backend allocator interventions), `debug permute`.

*(`debug search`'s exact subcommands and the mining-ledger query for §3.1 are bound in the
implementation plan, §11.)*

---

## 6. The three tiers + scoring

All tiers run **blind**, against the §9 sandbox at `C~1`. The harness scores against the
held-out ground-truth diff.

| Tier | Runs (blind, at C~1) | Verdict |
|------|----------------------|---------|
| **Advisory** (every case) | the §5 advisory set | `names-lever` / `hints-adjacent` / `silent-or-wrong` — LLM-judged vs. the real diff |
| **Generative** (every case, budgeted) | the §5 generative set | `byte-match-reproduced` / `improved-toward` / `no-progress` — scored automatically via `checkdiff` (structural + fuzzy) |
| **Blind-agent** (escalated subset) | fresh subagent, full skills, §9 sandbox, normal `/decomp` workflow | `matched` / `improved` / `stuck` — scored via `checkdiff` |

**Per-case roll-up:** `SOLVED-BY-TOOLING` / `PARTIAL` / `GAP`.

**Advisory judge hardening (M2).** The judge sees tool output + the real diff and decides
whether the tool "named the lever" — a soft, gameable comparison and the top
scoring-validity risk after leakage. Therefore: (a) the judge is **blind to the
in-corpus/held-out label** (else it anchors); (b) it is **calibrated against the Phase-0
negative controls** (§10) — it must return `silent-or-wrong` on cases where the tool
genuinely had nothing.

**Generative budget (M3).** `debug search`/`mutate`/`*-search` compile and score many
variants and have *hung* historically (catch-22 freezes in the memory record). Each
generative case gets a **hard wall-clock + iteration cap**; on exceed →
`no-progress` (never a stall). Budgets are per-tier parameters in the plan.

**Escalation policy.** The blind-agent tier is the expensive one. It runs on (a) the
`GAP`/`PARTIAL` cases from the cheap tiers, plus (b) a **held-out control sample of
cheap-tier `SOLVED` cases (target n ≈ 10–15, randomly sampled)** — the check that
"advisory named the lever" actually translates to "an agent reaches matching," which is
the single most informative result in the study.

---

## 7. Lever-class taxonomy → coverage matrix

Each ground-truth diff is classified into a lever class, reusing this project's
vocabulary: *embedded-assign temp; hoist-to-local / block-local→fn-scope; split-local /
split shared loop counter; retype (sign/width/field type); struct-overlay / data-blob as
file-local struct; literal-vs-named; decl-reorder / decl-demote; count-down /
comparison-reuse operand-flip; inline-arg / scheduler control; backend register-coloring /
coalescer tie-break (expected mostly source-unrealizable — confirming the tooling reports
these correctly is itself a result)*. Open set — new classes added as the corpus reveals
them.

**Deliverable — the coverage matrix:** for each lever class, the fraction solved by each
tier, **held-out vs in-corpus**, labeled with the §2 estimand caveat. This says precisely
which lever families the tooling owns, which it only points at, and which it's blind to.

---

## 8. Feedback loop

- **Tooling gap with a clear lever** → `melee-agent issue report` with the function, the
  missed lever, and the ground-truth diff, tagged to the tool that should have caught it.
- **Missed lever that is a clean, generalizable pattern** → **stage** (do *not* silently
  commit) a proposed `mismatch`-DB / mining-ledger entry for human review, to avoid
  polluting shared state with auto-generated noise.

A re-test/lift loop (re-run failed cases after fixes land) is **out of scope for v1**
(follow-on; depends on async resolver fixes landing).

---

## 9. Orchestration & isolation

- Implemented as a **Workflow `pipeline()`** over cases:
  `build-sandbox + classify-lever → advisory → generative → (conditional) blind-agent →
  score + emit`. Pipeline (not barrier) so a fast case scores while a slow one is still in
  the blind-agent tier.

- **Sandbox mechanics — reconciled (M4).** §3.2 requires the answer commit to be provably
  unreachable, but a plain `git worktree add … C~1` **shares the repo object store and can
  still `git show C`.** So the sandbox is **not** a plain worktree:
  - **Blind-agent tier:** a clone/worktree whose history is truncated so `C` is provably
    absent (assert per §3.2), then `python tools/worktree-doctor.py --fix` to restore the
    build tooling and `orig/GALE01/sys/main.dol` (these come from setup, not from the
    truncated history). The agent uses `/decomp` (checkdiff + source edits) and never needs
    future history.
  - **Cheap tiers:** the §5 tools don't consult git history, so a tree-export of the `C~1`
    state (no reachable `C`) suffices; the harness still holds ground truth out-of-band.
  - The shared main checkout at `/Users/mike/code/melee` is **never** built or mutated by
    the harness (documented worktree race; subagents also read the main checkout for
    relative paths — all sandbox paths are absolute).

- **Lifecycle (M4).** Sandboxes are **torn down after scoring** — they do not accumulate
  across 100–150 cases. Results are content-hash cached keyed on `(function, C)` so re-runs
  skip completed cases (mirror the mining ledger's skip pattern).

- **Concurrency / budget (M3).** Per-case sandboxes are isolated so builds can run in
  parallel, but each is a full build surface; the plan sets a concurrency cap and a
  per-tier time budget, and documents an order-of-magnitude runtime budget. (Codex-based
  tiers, if ever added, must be serialized per the sandbox-race issue — v1 uses Claude
  subagents only.)

- **Worktree traps avoided:** `Agent(isolation:"worktree")` branches off **master**, not
  the target commit (`isolation_worktree_branches_off_master.md`) — so sandboxes are
  created **explicitly** at `C~1` with absolute paths.

---

## 10. Phasing (two-sided calibration first)

- **Phase 0 — calibration (NOT just a "should-win" pilot).** Validates *both* error
  directions before any real number is trusted:
  - **Positive (false-negative guard).** ~10–15 *our own* tiny commits where the tooling
    should win → must score `SOLVED`. If the harness can't confirm a known win, the harness
    is wrong, not the tooling.
  - **Negative controls (false-positive guard, B3).** Cases whose ground-truth lever is a
    class known to be **backend-uncrackable** and is **withheld from the mined DBs** → the
    advisory/generative tiers **must** score `GAP`, not `SOLVED`. A `SOLVED` here means the
    scorer is leaking or the judge is hallucinating.
  - **Leak probe (B3).** From inside a sandbox, assert `C` is unreachable (§3.2) — the
    explicit, automated check, not a manual "looks truncated."
  - Negative controls also **calibrate the advisory judge** (§6 / M2).
- **Phase 1 — scale, gated on Phase 0 passing *both* directions.** ~100–150 held-out
  small/singular commits across all authors on the cheap tiers; blind-agent escalation on
  ~20–30 juiciest `GAP`/`PARTIAL` cases plus the §6 held-out control sample.

(Counts are starting points, tunable.)

---

## 11. Open implementation questions (for the plan)

1. **Structural flip detection** — exact `checkdiff` invocation + `normalized_diff_lines`
   parsing, and per-function (not full-repo) build to confirm `C`/`C~1` cheaply.
2. **Confound attribution** — mechanics of applying only the in-function hunk over `C~1`
   to confirm/reject the lever locus (§4.3).
3. **In-corpus determination** — exact queries against the `mismatch` DB and the
   source-transform mining ledger to decide whether a diff/lever is already represented
   (load-bearing for the headline metric; resolve *where the mined corpus lives* first).
4. **Tool-surface binding** — `debug search` subcommands and the precise advisory/
   generative invocations, bound against live `--help`.
5. **Sandbox build** — truncated-clone vs tree-export details; the `C`-unreachable
   assertion; `worktree-doctor --fix` integration.
6. **Lever classifier** — rule-based vs LLM vs hybrid; how new classes register.
7. **Advisory judge rubric** — precise `names-lever` vs `hints-adjacent` definition;
   label-blinding; negative-control calibration set.
8. **Result store & report** — likely the mining ledger / `agent_state.db`; coverage-matrix
   rendering.

---

## 12. Non-goals

- Not a new matcher / not a `permuter`/`debug search` replacement.
- Not the re-test/lift loop (follow-on).
- Not auto-committing pattern-DB entries or source — gaps are *reported* and *staged* for
  human review only.

---

## 13. Risks & mitigations (review traceability)

- **Stale tool surface** (B1) → bind to live `--help`; corrected §5; in-corpus query
  relocated to mismatch-DB + mining ledger; §11-Q3/Q4 pre-plan items.
- **Selection bias / external validity** (B2) → §2 estimand stated as an explicit proxy;
  coverage matrix labeled "small-historical-win surface," not "matching surface."
- **One-sided Phase 0 / leak undetected** (B3) → §10 two-sided calibration: negative
  controls + automated leak probe; Phase 1 gated on both.
- **Fuzzy-% ground-truth noise + header/caller confound** (M1) → structural
  (`normalized_diff_lines`) gate; fresh baseline; hunk-attribution confound guard (§4).
- **Advisory judge leakage** (M2) → label-blinded judge calibrated on negative controls.
- **Generative tiers not cheap / hangs** (M3) → per-tier wall-clock + iteration caps;
  timeout → `no-progress`; concurrency cap.
- **Sandbox ≠ blind / worktree accumulation** (M4) → §9 reconciled sandbox (provable
  `C`-absence, not a plain worktree); teardown + content-hash cache.
- **Control-sample / opseq-naming / Phase-gating minors** → §6 control-sample n; §5 opseq
  alias noted; §10 gate.
