# Experiment: Mutation-Class × Feature-Gap Correlation

**Date:** 2026-06-11
**Status:** Spec (pre-experiment)

## Hypothesis

When the decomp-permuter generates variants of a wall function (here:
`mnDiagram_InputProc`), the **feature gap** between the variant's compiled
output and the target — measured as differences in register coloring, frame
layout, instruction selection, etc. — correlates detectably with **which
mutation class** (`perm_*` pass) was applied. If the conditional distribution
of feature-gap dimensions differs significantly across mutation classes,
steering the permuter's mutation weights by feature-gap observations could
outperform uniform random search.

## Experiment Design

### Stage 1: Patch — Mutation-Class Tracking

Add recording of which `perm_*` pass was applied per candidate (4 files
touched, ~20 lines):

| File | Change |
|------|--------|
| `randomizer.py` | `Randomizer.randomize()` returns the method `__name__` (was `-> None`) |
| `candidate.py` | `Candidate.randomize_ast()` returns `Dict[str, str]` mapping fn→pass name; `CandidateResult.mutations` field |
| `permuter.py` | `_eval_candidate()` captures the return and stamps `result.mutations` |
| `main.py` | `write_candidate()` writes `mutation.txt` per output directory |

### Stage 2: Data Generation

Run the permuter on `mnDiagram_InputProc` for 500+ iterations. For each
candidate that beats or ties the base score, we get:
- `source.c` (the variant)
- `score.txt` (byte-match distance)
- `diff.diff` (text diff vs base)
- `mutation.txt` (the `perm_*` class applied)

### Stage 3: Feature-Gap Extraction

For the top ~50 candidates (best-scoring) and ~50 random samples (control
coverage):

1. **Compile through `melee-agent debug dump local`** → pcdump.txt
2. **Extract structured feature gaps** using `debug target derive` to get the
   virtual→physical mapping, then diff against the known-good mapping for this
   function
3. **Frame/reservation mismatch** from checkdiff
4. **Per-instruction reg differences** from pcdump analysis

### Stage 4: Correlation Analysis

For the ~100 structured observations `(mutation_class, feature_gap_vector)`:

1. **Per-dimension ANOVA/Kruskal-Wallis:** does any feature-gap dimension
   separate mutation classes from each other more than within-class variance
   would predict?
2. **Effect size (Cohen's d / η²):** if significant, how large is the separation?
3. **Multivariate explored:** if univariate signal found, try LDA/QDA to see
   if mutation class is linearly separable in feature space.

### Success Criteria

- **Signal found:** ≥1 feature dimension with η² > 0.14 (large) and p < 0.05
  — indicates steering is viable
- **Weak signal:** η² 0.06–0.14 — plausible but needs larger N
- **No signal:** η² < 0.06 — mutation class doesn't predict feature gaps
  meaningfully for this compiler and function; the steering approach likely
  doesn't work

### Risk Factors

1. **Compiler nonlinearity:** small source changes cause large, discontinuous
   regalloc differences — the signal may be entirely noise
2. **Single-function generality:** InputProc is 3140 bytes with complex control
   flow; results may not transfer
3. **Mutation class granularity:** 30 passes are grouped into ~10 functional
   categories — analysis at the pass level may be underpowered
4. **pcdump cost:** ~4-8 seconds per variant → 100 variants = ~10 minutes

## Material

- **Branch:** `wip/inputproc-experiment` (forked from `pr/mn-inputproc-98pct`)
- **Permuter dir:** `/Users/mike/code/decomp-permuter/nonmatchings/mnDiagram_InputProc/`
- **Worktree:** `/Users/mike/code/melee-wip-inputproc-experiment/`
