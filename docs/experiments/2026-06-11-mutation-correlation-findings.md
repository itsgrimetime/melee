# Mutation-Class × Feature-Gap Correlation — Findings

**Date:** 2026-06-11  
**Function:** `mnDiagram_InputProc` (3140 B, 98.67%)  
**Branch:** `wip/inputproc-experiment`  
**Permuter patches:** `/Users/mike/code/decomp-permuter` (4 files, ~40 lines)  
**Experiment scripts:** `tools/experiments/`

## Summary

We tested the hypothesis that **which mutation class a permuter variant uses correlates
detectably with the structure of the resulting byte-diff** — i.e., that observing the
feature gap could steer the permuter toward mutation classes likely to close that
gap. The answer is **no at category granularity (η² = 0.014), with some signal at
individual pass granularity (3 passes with |d| > 0.5).**

## What We Built

### Permuter Patches (decomp-permuter)

Four files patched in the decomp-permuter source:

| File | Change |
|------|--------|
| `src/randomizer.py` | `Randomizer.randomize()` now returns the method `__name__` |
| `src/candidate.py` | `Candidate.randomize_ast()` returns `Dict[fn, pass_name]`; `CandidateResult.mutations` field |
| `src/permuter.py` | Threads mutations through `_eval_candidate()`, stamps `Result.mutations` |
| `src/main.py` | Writes `mutation.txt` per output directory; `--save-all` flag saves every variant |

The patches are small (~40 lines total), zero-overhead when unused, and the
`--save-all` flag was a critical addition — on near-match functions, virtually no
random variants beat the base score, so the permuter's default "save only winners"
policy produces zero data points. `--save-all` makes it output every compiled variant.

### Labeled Dataset

476 compiled and scored variants across 29 of 30 mutation passes, each tagged with
its mutation class (via `mutation.txt`), source diff (`diff.diff`), and source
(`source.c`).

### Analysis Pipeline

Scoring via decomp-permuter's `Scorer`, checkdiff JSON analysis,
per-category/per-pass ANOVA and Cohen's d computations.

## Results

### ANOVA: Mutation Category × Score Impact

| Category | N | Best | Median | Mean | η² contribution |
|---|---|---|---|---|---|
| assignment | 41 | 1265 | 4390 | 5502 | |
| decl_order | 11 | 1550 | 4575 | 6111 | |
| expr | 77 | 1595 | 4880 | 8657 | |
| inline_struct | 17 | 2200 | 4010 | 5454 | |
| noop | 88 | 1215 | 6325 | 7555 | |
| stmt_order | 16 | 2230 | 6600 | 6682 | |
| temp_var | 198 | 1215 | 6390 | 7576 | |
| type_change | 27 | 1655 | 6540 | 7740 | |

**F(7, 467) = 1.0, η² = 0.0143** — category explains only 1.4% of score variance.

### Pass-Level Effect Sizes (Cohen's d from grand mean)

Only 3 passes have |d| > 0.5, and none approach d > 1.0:

| Pass | d | Interpretation |
|------|---|---|
| perm_condition | +0.87 | Consistently large perturbations |
| perm_add_sub | +0.60 | Large perturbations |
| perm_factor_shift | -0.56 | Tends toward smaller perturbations |
| perm_remove_ast | +0.52 | Large perturbations |
| perm_sameline | +0.46 | Moderate-large |
| perm_randomize_external_type | +0.50 | Moderate-large |

Most passes cluster near d ≈ 0, indistinguishable from random.

## Interpretation

### What Was Disproved

The strong steering hypothesis — *"observe the feature gap → predict which mutation
class is most likely to close it"* — does **not** hold for this function at category
granularity. The compiler's path-dependence dominates: the same `perm_temp_for_expr`
can produce a near-match variant (score 1215) or a register-chaos variant (score
67195) depending on where in the AST it fires.

### What Was Partially Confirmed

Pass-level effect sizes show some structure. `perm_condition` and `perm_add_sub` are
consistently destructive (large perturbations), while `perm_factor_shift` and
`perm_duplicate_assignment` tend to produce smaller perturbations. A pass-level
steering table (not category-level) might have power at scale.

### Root Cause

The independent variable (mutation class name) is a **poor proxy for the actual
perturbation** applied to the AST. Two calls to `perm_temp_for_expr` differ in:
which expression is captured, where the assignment is inserted, whether a variable
is reused, and whether the replacement is all-occurrences or partial. These fine-
grained choices dominate the compiler's response, and they're invisible to a
categorical label.

## Infrastructure Value

The `--save-all` flag and mutation tracking are genuinely useful additions to the
permuter. They enable running the permuter on near-match functions and inspecting
the full output surface, building intuition about what each mutation pass actually
does in practice. Recommend keeping these patches permanently.

## Future Directions

### 1. Continuous Perturbation Metrics (Most Promising)

Replace the categorical pass label with **AST-level change metrics** extracted from
the source diff:

- Δ local variable count
- Δ statement count
- Δ maximum nesting depth
- Δ basic-block count (inferred from brace structure)
- Statement insertion vs deletion vs rearrangement flag
- Expression-only vs declaration-only vs mixed flag

These continuous variables should correlate with score impact because they're
*direct* measures of what changed, not proxy labels. The experiment to check: build
a linear model `score ~ Δvars + Δstmts + Δnesting + is_rearrangement` and measure
R². If R² > 0.3, continuous metrics are a viable steering signal.

### 2. Pass-Level Steering Table

Rather than steering by category, collect per-pass effect sizes across many
functions and build a lookup table: "for residual type X, `perm_reorder_decls`
typically improves score by Y%." This is the historical-knowledge approach the
user explicitly warned against, but the effect-size data from this experiment is a
seed for it.

### 3. PCDUMP-Based Multi-Dimensional Gap Analysis

Get the mwcc-debug pcdump working (suspected wibo/DLL version issue in this
worktree; the 6KiB vs 23KiB DLL size difference suggests the build system
produced a different artifact) and extract per-virtual-register coloring vectors.
The feature space there is richer than scalar score, but the experiment complexity
is much higher.
