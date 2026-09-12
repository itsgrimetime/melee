# Scalar Expression Transform Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make issue #691 source-actionable by adding conservative, tested scalar-expression transform-corpus mutators for boolean accumulators, zero comparisons, ABS folds, and MIN/MAX spelling.

**Architecture:** Reuse the existing transform-corpus flow.  Anchors identify exact scalar edit sites, mutators apply exact-text replacements, and `transform_corpus.py` maps mutator keys to family metadata plus generic planner exposure.

**Tech Stack:** Python 3.11, pytest, Typer CLI, existing `src.search.directed` modules.

---

## Files

- Modify: `tools/melee-agent/src/search/directed/anchors.py`
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`

## Task 1: Failing Tests

- [ ] Add metadata tests in `tools/melee-agent/tests/search/directed/test_transform_corpus.py` asserting these family/mutator pairs are concrete:
  - `bool_int_accumulator_shape` -> `rewrite_bool_accumulator_as_int`
  - `zero_compare_logical_not` -> `rewrite_zero_compare_logical_not`
  - `abs_macro_expression_fold` -> `rewrite_abs_ternary_to_macro`
  - `minmax_macro_ternary_shape` -> `rewrite_minmax_macro_to_ternary`
- [ ] Add a fixture test in `test_transform_corpus.py` where `generate_transform_probes` emits one probe for each of the four families and the candidate text contains the expected replacement.
- [ ] Add unsafe fixture tests in `test_transform_corpus.py` showing `ABS(next())`-style and `MAX(next(), limit)`-style duplicated evaluation is rejected.
- [ ] Add a fixture or adapter test proving a scalar family can be requested independently through an existing `--transform-family` consumer.  Do not add `--transform-family` to `debug search plan-transforms`; that command does not expose this option.
- [ ] Add direct mutator tests in `tools/melee-agent/tests/search/directed/test_mutators.py` for exact-line replacement and missing-payload rejection for the four new mutator keys.
- [ ] Run `python -m pytest tools/melee-agent/tests/search/directed/test_mutators.py tools/melee-agent/tests/search/directed/test_transform_corpus.py -q` and confirm the new tests fail before production code changes.

## Task 2: Anchors And Mutators

- [ ] In `anchors.py`, add private scalar helpers for simple expression safety, top-level zero comparison detection, ternary ABS detection, MIN/MAX macro detection, and bool accumulator detection.
- [ ] Add four anchor iterators yielding exact payloads for `rewrite_bool_accumulator_as_int`, `rewrite_zero_compare_logical_not`, `rewrite_abs_ternary_to_macro`, and `rewrite_minmax_macro_to_ternary`.
- [ ] Register those iterators in `iter_source_shape_anchors`.
- [ ] In `mutators.py`, add four exact-text mutator functions that return `None` when cited payload text is missing or unchanged.
- [ ] Register the four mutator keys in `_DISPATCH`.
- [ ] Run the Task 1 focused test command and iterate until it passes.

## Task 3: Family Wiring And Catalogue

- [ ] In `transform_corpus.py`, replace the empty mutator keys and `record-only` generated forms for the four #691 families with the concrete mutator keys and narrow generated-probe descriptions.
- [ ] Add the four family ids to the generic fallback cluster so `plan-transforms` and directed search can emit them when anchors are present.  Keep the existing adapter-level family filtering for commands that already expose `--transform-family`.
- [ ] Extend `generate_transform_probes(..., families=...)` so requested families are included in the allow-list before probe generation.  Update `_append_transform_corpus_probes` to pass normalized requested families into generation before adapter filtering.
- [ ] In `source_transform_catalog.py`, add the four mutator keys to `DIRECTED_MUTATOR_KEYS` and update notes so these families are described as backed by executable mutators.
- [ ] In `docs/source-transform-catalog.md`, revise the record-only summary and known examples to state these scalar-expression families now have concrete guarded mutators.
- [ ] Update `tools/melee-agent/tests/test_source_transform_catalog.py` to expect the four new concrete forms.

## Task 4: Verification And Review

- [ ] Run `python -m pytest tools/melee-agent/tests/search/directed/test_mutators.py tools/melee-agent/tests/search/directed/test_transform_corpus.py tools/melee-agent/tests/test_source_transform_catalog.py -q`.
- [ ] Run a shell-level smoke for `python -m src.cli debug search plan-transforms` with a temp source fixture, `--write-probes`, and `--json`, confirming at least one written scalar probe path.
- [ ] Run a shell-level smoke through an existing filtered consumer, such as `python -m src.cli debug mutate lifetime-layout ... --transform-family zero_compare_logical_not --no-compile-probes --json`, confirming the emitted transform-corpus provenance contains only the requested scalar family.
- [ ] Run `python -m py_compile tools/melee-agent/src/search/directed/anchors.py tools/melee-agent/src/search/directed/mutators.py tools/melee-agent/src/search/directed/transform_corpus.py tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`.
- [ ] Run `git diff --check`.
- [ ] Ask an independent Codex subagent to review the final diff for spec compliance and semantic safety, then fix any valid findings.
- [ ] Commit the implementation, docs, spec, and plan on `master`.
- [ ] Refresh the editable `melee-agent` install from `/Users/mike/code/melee/tools/melee-agent`.
- [ ] Resolve issue #691 only after tests, smoke checks, review, and install verification pass.
