# Transform Corpus Mutator Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make issues #673-#680 source-actionable by adding conservative,
well-tested transform-corpus anchors and mutators for the mined families that
were previously record-only.

**Architecture:** Keep the existing text-safe directed search design. Anchors
identify exact source spans, mutators apply one deterministic exact-text edit,
and `transform_corpus.py` maps mutator keys to families plus higher-level
function/proof guards.

**Tech Stack:** Python 3.11, pytest, Typer CLI, existing `src.search.directed`
modules.

---

## Files

- Modify: `tools/melee-agent/src/search/directed/anchors.py`
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`

## Task 1: Failing Tests For Metadata And Mutators

- [ ] Add tests in `test_transform_corpus.py` that assert the requested family
      ids have non-empty concrete `mutator_keys` and `generated_probe_form`
      strings without `record-only`.
- [ ] Add focused mutator tests in `test_mutators.py` for:
      `wrap_comma_noop_assignment_rhs`, `insert_empty_do_while_barrier`,
      `fold_assignment_expression_seed`, `elide_numeric_cast`,
      `swap_simple_switch_cases`, `collapse_hsd_assert`,
      `return_tail_call_value`, `replace_string_literal_with_data_field`,
      `introduce_global_pointer_alias`, and
      `rewrite_raw_pointer_offset_field`.
- [ ] Add unsafe rejection tests for absent payloads and the main guard class
      for each mutator.
- [ ] Include review-driven proof tests: numeric cast elision must have a
      same-type source-local prototype; assert collapse must emit
      `HSD_ASSERTMSG` and prove the asserted file basename; return-contract
      must edit a `static void` signature to the helper scalar return type; data
      and raw-struct rewrites must reject duplicate strings and unknown layout
      offsets.
- [ ] Run:
      `python -m pytest tools/melee-agent/tests/search/directed/test_mutators.py tools/melee-agent/tests/search/directed/test_transform_corpus.py -q`
      and confirm the new tests fail for missing behavior before production
      code is edited.

## Task 2: Anchors And Exact-Text Mutators

- [ ] Implement narrow anchor iterators in `anchors.py`, keeping them private
      and adding them to `iter_source_shape_anchors`.
- [ ] Implement matching private mutator functions in `mutators.py` and add
      each key to `_DISPATCH`.
- [ ] Keep each mutator exact-text based. It must return `None` if payload
      source is missing or if the replacement would be identical.
- [ ] Run the focused tests from Task 1 and iterate until they pass.

## Task 3: Family Wiring And Proof Guards

- [ ] Add the new mutator keys to the corresponding `TransformFamily`
      metadata in `transform_corpus.py`.
- [ ] Add the requested family ids to the generic fallback cluster only as
      proof-gated families. Low-risk syntax-local families may emit from body
      anchors; high-risk return/data/global/raw-struct families must not emit
      unless their local proof helper succeeds.
- [ ] Add target-function guards in `generate_transform_probes` for return
      forwarding, numeric-cast prototype equivalence, assert file/message
      equivalence, and proof-backed data/struct/global transforms that need
      full-source context.
- [ ] Add planner tests that materialize at least one candidate for each
      requested issue family from focused fixture source.
- [ ] Run:
      `python -m pytest tools/melee-agent/tests/search/directed/test_transform_corpus.py -q`
      and confirm green.

## Task 4: Catalogue And CLI Smoke

- [ ] Update `docs/source-transform-catalog.md` to describe the newly concrete
      forms and revise the concrete mutator count.
- [ ] Update `test_source_transform_catalog.py` for the new concrete forms.
- [ ] Run focused catalogue tests:
      `python -m pytest tools/melee-agent/tests/test_source_transform_catalog.py -q`.
- [ ] Run a command-level smoke with a temp fixture:
      `melee-agent debug search plan-transforms -f <fixture-fn> --unit <fixture-unit> --force-phys ig1=r3 --source-file <fixture.c> --write-probes <tmpdir> --json`
      and confirm the JSON contains materialized probes and written candidate
      paths for the new families.

## Task 5: Review, Resolve, And Install

- [ ] Ask an independent Codex subagent to review the diff for semantic safety
      and missing tests.
- [ ] Fix any valid review issues.
- [ ] Run final verification:
      `python -m pytest tools/melee-agent/tests/search/directed/test_mutators.py tools/melee-agent/tests/search/directed/test_transform_corpus.py tools/melee-agent/tests/test_source_transform_catalog.py -q`
      plus `python -m py_compile` for the modified modules and `git diff --check`.
- [ ] Commit the code and docs on `master`.
- [ ] Refresh the editable install from
      `/Users/mike/code/melee/tools/melee-agent`.
- [ ] Resolve only the issues whose requested family has a tested,
      materialized probe path.
