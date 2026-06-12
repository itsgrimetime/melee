# Four Tooling Ideas — Full Exploration

**Date:** 2026-06-11  
**Branch:** `wip/inputproc-experiment`

A comprehensive exploration of four tooling directions to aid matching, based on
insights from the mutation-class × feature-gap correlation experiment.

## Idea 1: Score-source for Continuous Metrics

### What It Is

Replace (or augment) the scalar mwcc-debug score blend in the permuter with
**multi-dimensional AST-level perturbation metrics** extracted from the source
diff against base.c. Instead of "which pass was applied" (a categorical label),
use continuous variables: Δ local variable count, Δ statement count, Δ nesting
depth, whether the mutation touches control flow vs expressions vs types, etc.

### Why It Might Work

The categorical analysis found η² = 0.014 — the pass name explains almost nothing
about score impact. But the *same pass* produces wildly different AST
perturbations depending on context. If those perturbations are what the compiler
actually responds to, continuous metrics should correlate better because they're
*direct* measures of what changed, not proxy labels.

For example: `perm_temp_for_expr` can add 1 var and 1 stmt (score 1215, barely
different from base) or restructure 6+ expressions (score 67195, register chaos).
The categorical approach treats these as the "same class." A continuous metric
would record Δvars=1 vs Δvars=6 and see the difference.

### How to Do It

**The external scorer already exists** (`CustomCommandScorer` in `scorer.py`).
It's configured in `settings.toml` and receives:
- `PERMUTER_C_FILE` — candidate source path
- `PERMUTER_TARGET_O` — target .o for comparison
- `PERMUTER_CAND_O` — candidate .o via argv

The scorer can:
1. Diff candidate C source against base.c using pycparser AST comparison
2. Extract perturbation metrics: Δlocal_vars, Δstmts, Δmax_nesting, Δblock_count
3. Compile through production wibo + score via checkdiff or built-in Scorer
4. Output a *blended* score: `byte_match_score + α·f(|Δvars|) + β·f(|Δstmts|) + ...`

The α/β coefficients are tuned so that large, unnecessary perturbations are
penalized but necessary ones aren't. The permuter already penalizes large byte
differences; this adds "you changed more code than you needed to" as an
additional signal.

### Feasibility

**High.** The infrastructure is in place:

| Component | Status |
|---|---|
| `CustomCommandScorer` interface | Ready (`scorer.py:331`) |
| Base source comparison | Diff via `permuter.py:diff()` or pycparser AST diff |
| Compilation pipeline | `compile.sh` works |
| Byte score (checkdiff/permuter scorer) | Ready |

Estimated effort: **2-3 hours** to write a scorer script, wire it into settings.toml,
and tune the blend coefficients on a representative sample.

### Risk

The continuous metrics might also be noisy. If the compiler's response to "add a
statement and a variable" is path-dependent on *which* statement and *where*,
then even continuous metrics won't explain the variance well. The question is
whether they explain more than η²=0.014 — that's a low bar.

### Verdict

**Worth building.** Low effort, high information value. Even if it doesn't improve
the permuter's search, it produces the dataset needed to answer "do continuous
metrics correlate better than categorical labels?" definitively.

---

## Idea 2: Interactive Diff Diagnosis

### What It Is

A single command that reads checkdiff `--format json` output and produces a
structured, unified, actionable diagnosis of what's wrong with the current
match, with specific source-level recommendations tied to known lever classes.

### What Already Exists

The exploration found an **extensive but scattered** diagnostic pipeline:

- **checkdiff classification** (`checkdiff.py:classify_asm_diff`) — detects
  signature-type-mismatch, register-only diffs, indexed-struct-pointer-materialization,
  PAD_STACK, stack frame/slot layout, inline-boundary artifacts, and more.

- **frame_taxonomy.py** — normalizes frame diagnostics into closability tiers
  with `next_command` recommendations.

- **guidance.py** (`debug inspect guide`) — ranked suggestions for allocator
  issues (interference, spill, param-iter-ceiling, rank).

- **diagnose/ceiling command** (`debug inspect diagnose`) — cast audit, decl-order
  enumeration, value-numbering ceiling detection, frame hints, coupled force-phys
  guidance, tiebreak guidance. Auto-verifies cast removals.

- **signature_audit** (`suggest signatures`) — audits call-prep signatures
  against source, generates `PatchDescriptor` with source-line-level patches.

- **stuck command** (`debug inspect stuck`) — composes function status, pcdump
  analysis, guidance, casts, frame hints, decl-order results, next steps.

### What's Missing

**A. No unified "read JSON → structured diagnosis" tool.** The classification is
rich but consumed piecemeal — different commands extract different sub-fields.
There is no `melee-agent debug target explain-diff path/to/checkdiff.json` that
returns a complete machine-readable and human-readable diagnosis.

**B. Several patterns detected in checkdiff have no downstream consumer:**
- `indexed-struct-pointer-materialization` — detected and formatted in checkdiff
  but no CLI command acts on it
- `array-element-store-addressing-mode` — detected as part of `backend-ceiling`
  but has no CLI surface
- `instruction-sequence` — has no structured recommendation at all

**C. No cross-referencing between checkdiff classification and pcdump analysis.**
The `stuck` command composes them but doesn't deeply cross-reference. For example:
"checkdiff says `register-only` (21 paired diffs) + pcdump says `interference`
(virtual r35 blocked by r28)" → combined recommendation "shrink live range of r35
by moving its last use earlier or inserting a temporary."

**D. No "what to try next" ranking.** The existing guidance gives recommendations
but doesn't rank them by expected impact or cost. A doctor agent has to guess.

### How to Build It

```python
def diagnose_from_checkdiff(checkdiff_json_path):
    data = json.loads(Path(checkdiff_json_path).read_text())
    
    diagnosis = {
        "primary_classification": data["classification"]["primary"],
        "summary": format_summary(data),
        "structural": data["structural"],
        "register_only_count": count_register_only(data),
        "frame_issues": frame_taxonomy.classify(data["classification"]),
        "indexed_struct_hints": data["classification"].get(
            "indexed_struct_pointer_materialization"),
        "recommendations": rank_recommendations(data),
    }
    
    for rec in diagnosis["recommendations"]:
        rec["lever_class"] = map_to_lever_class(rec)
        rec["expected_impact"] = estimate_impact(rec)
        rec["cost_seconds"] = estimate_cost_seconds(rec)
        rec["command"] = format_command(rec)
    
    return diagnosis
```

The `rank_recommendations` function maps each checkdiff signal to a prioritized
list, for example:

| Signal | Rank | Recommendation | Cost |
|---|---|---|---|
| register-only diffs > 10 | 1 | `debug target match-iter-first --regs gpr-volatile` | ~5s |
| PAD_STACK present | 2 | Replace with natural C (array/volatile) | ~30s |
| indexed-struct-pointer | 3 | Split first field into scalar local | ~60s |
| signature-type-mismatch | 4 | `suggest signatures` on callees | ~30s |
| frame discrepancy > 0 | 5 | `debug inspect frame-reservations` | ~20s |

### Feasibility

**Medium-High.** Most of the building blocks exist. The work is:
1. Write the `explain-diff` CLI command that reads checkdiff JSON and composes
   the existing detectors into a unified output
2. Fill the gaps for patterns with no downstream consumer
3. Add the cross-reference with pcdump analysis when available
4. Add the impact/cost ranking layer

Estimated effort: **4-6 hours** for the unified command. The value is in making
the existing diagnostic infrastructure *addressable by a single command* instead
of requiring the user to know which of 8 different commands to run depending on
what checkdiff says.

### Verdict

**Strongly worth building.** The diagnostic infrastructure is rich but scattered.
A unified `explain-diff` command would be the highest-leverage tooling addition
available. It doesn't require new science — just integration.

---

## Idea 3: Production .o Regalloc Telemetry

### What It Is

Extract register coloring information from production .o files via disassembly
analysis, bypassing the patched mwcc-debug DLL entirely.

### The Exploration Verdict

**Not feasible.** This is a hard no for the specific goal of per-virtual register
coloring vectors.

The fundamental problem: **production .o files contain only physical registers
(r0-r31).** The virtual register IDs (r32+) are an internal compiler bookkeeping
detail discarded after register allocation. The mapping "virtual r35 → physical
r28" exists only in the compiler's internal state at the moment of allocation.

Concretely:
- **No virtual IDs in .o files** — instruction encodings reference r3, r28, etc.
  with no record they were ever called r35.
- **No allocation trace** — colorgraph decisions, simplify order, coalescing all
  happen inside the compiler and are only captured by the patched DLL hooks.
- **checkdiff can detect *that* register allocation differs** (by comparing
  paired instructions with matching opcodes but different registers) but **cannot
  tell *which virtual* is involved** or *why* the allocator chose differently.

What checkdiff CAN provide without pcdump:
- Counts of register-only diffs
- Classification (register-allocation vs signature-type-mismatch vs ...)
- Callee-save swap detection
- Volatile target register identification

This is useful guidance but fundamentally summary-level — no deeper than what
`checkdiff --format json` already produces.

### Feasibility

**Impossible without the debug compiler.** The patched mwcc-debug DLL is a hard
prerequisite for any virtual-level register analysis.

### What To Do Instead

Fix the DLL installation in worktrees. The root cause was a scoping issue in the
patcher (needs `--dll` with the right DLL path). In this worktree, the fix was:

```bash
cd build/compilers/GC/1.2.5n
cp mwcceppc.exe mwcceppc_debug.exe
python3 /Users/mike/code/melee-harness/mwcc_debug/patch_mwcceppc_for_wibo.py \
  mwcceppc.exe mwcceppc_debug.exe \
  --dll /Users/mike/code/melee-harness/mwcc_debug/MWDBG326.dll
```

This should be automated into `debug dump setup` or a `--fix` flag on `doctor`.

### Verdict

**Dead end for the original goal.** The only path to register coloring vectors
is the patched debug compiler. Fix the setup automation instead.

---

## Idea 4: Permuter Online Bandit / Blacklist

### What It Is

An adaptive mutation weight adjustment system that runs the permuter in batches,
observes which passes produce the best-scoring candidates in each batch, and
dynamically adjusts mutation weights for the next batch. Over time, destructive
passes are suppressed and effective passes are amplified — per function.

### Architecture Constraints Found

The permuter architecture is **entirely static** for weights. Key blockers:

| Issue | Detail |
|---|---|
| Weights frozen at startup | `Permuter.randomization_weights` is never mutated |
| Randomizer created per-Candidate | `Candidate.from_source()` creates a fresh `Randomizer` with stale weights |
| `keep_prob` (default 0.6) | When kept, the old Randomizer (with old weights) is reused |
| Multiprocessing | Workers get pickled copies of the Permuter — weight updates don't propagate |
| No weight-update interface | `Randomizer.methods` is private with no setter |

### A Viable Minimal Implementation (Single-Threaded)

The single-threaded main loop (`main.py:468-484`) is tractable:

```python
# In post_score() — already receives result with mutations and score
if result.mutations is not None:
    pass_stats.record(result.mutations["mnDiagram_InputProc"], score)

# Every N iterations, adjust weights
if context.iteration % 50 == 0 and pass_stats.n_applications > 10:
    new_weights = pass_stats.compute_weights(strategy="exp3")
    permuter.randomization_weights.update(new_weights)
    # Also update the active Randomizer if it exists
    if permuter._cur_cand is not None:
        for pass_name, weight in new_weights.items():
            permuter._cur_cand.randomizer.set_weight(pass_name, weight)
```

Tracking would need:
- Per-pass sliding window of last M scores
- Average score relative to batch average (positive = better than average)
- Weight adjustment: `weight' = weight · exp(η · mean_reward)` with normalization
- Epsilon-greedy exploration: `P(uniform) = ε`

### The Big Problem: Multiprocessing

Multi-threaded and network modes (the default for any serious permuter run) make
this significantly harder. Workers have pickled copies of Permuters with their
own Randomizers. Weight updates would need:
1. A new IPC message type (`UpdateWeights`) on `worker_task_queue`
2. `multiprocess_worker` to unpack and apply weight updates between iterations
3. Stats aggregation back through `feedback_queue`

This is doable but adds ~double the implementation complexity.

### The Deeper Question: Would It Even Help?

The experiment found η² = 0.014 for category labels. The bandit operates at the
*pass* level, which has slightly more signal (a few passes with |d| > 0.5). But:

- The bandit needs enough iterations per pass to estimate its effect. With
  30 passes and a 500-iteration permuter run, the average is ~17 samples per pass
  — barely enough for reliable estimation.
- The signal-to-noise ratio is poor. The same pass on different AST contexts
  produces vastly different results (score 1215 vs 67195 for `perm_temp_for_expr`).
  The bandit will converge slowly — perhaps too slowly to help within a typical
  permuter run.
- The pass that helps *early in search* (when the source is far from target) may
  be destructive *late in search* (when the source is near-match). The bandit
  would need to adapt to the search stage, not just the function.

### A More Targeted Alternative: Pass Blacklisting

Instead of full bandit optimization, a simpler and more robust idea: **allow the
user to blacklist specific passes** via settings.toml when the permuter is run
on a near-match function.

From the experiment data:
- `perm_sameline` — best score 10820 (vs base 1190). Always destructive.
- `perm_randomize_external_type` — best score 11105. Always destructive.
- `perm_struct_ref` — best score 8795. Almost always destructive.
- `perm_empty_stmt` — best score 4675. No good variants.

These passes produce such uniformly poor scores on near-match functions that
running them is a waste of iterations. A `blacklisted_passes = ["perm_sameline", "perm_randomize_external_type"]` setting would skip them entirely.

The `RandomizerFailure` mechanism already supports this: if a pass always raises
`RandomizationFailure`, it's skipped. But these passes succeed — they just
produce terrible results. The bandit or blacklist would suppress them after
observing consistent failure.

### Feasibility

**Medium** for the minimal version (single-threaded pass blacklist + weight
adjustment). **Hard** for the full multiprocess bandit.

The **pass blacklist approach** is ~1 hour and provides immediate value. The
**full online bandit** is ~8-12 hours due to the multiprocessing plumbing.

### Verdict

**The full bandit is probably not worth building** — the signal-to-noise ratio
from the experiment data suggests very slow convergence. The pass counts per
run (N=17/pass on average) are too low for reliable multi-armed bandit
estimation.

**The pass blacklist IS worth building** — it's simple and has immediate benefit
for near-match functions. The experiment data tells us which passes to
blacklist by default.

---

## Synthesis: What to Build, in Order

| Priority | Idea | Effort | Impact | Risk |
|---|---|---|---|---|
| 1 | **Unified diff diagnosis** (Idea 2) | 4-6h | High — integrates 8+ existing tools into one command | Low — all pieces exist |
| 2 | **Continuous metrics scorer** (Idea 1) | 2-3h | Medium — proves or disproves the metric approach | Low — standalone script |
| 3 | **Pass blacklist** (Idea 4 subset) | 1h | Low-Medium — saves iterations on near-match | None |
| 4 | **Fix pcdump setup automation** (Idea 3's real fix) | 30min | Medium — unblocks pcdump in worktrees | None |
| 5 | **Full online bandit** (Idea 4 full) | 8-12h | Low-Medium — signal is weak, convergence uncertain | High — effort may not pay off |

## Actionable Next Step

The highest-leverage single action is to build the unified diff diagnosis command
(`debug target explain-diff` or similar). It doesn't require new analysis — just
integration of the existing rich diagnostic pipeline into a single addressable
surface. The checkdiff classification is already comprehensive; what's missing
is a command that reads it and says "here's what's wrong and here's the ranked
list of things to try."
