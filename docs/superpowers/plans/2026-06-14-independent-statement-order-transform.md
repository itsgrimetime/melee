# Independent Statement-Order Transform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add conservative executable adjacent statement-order probes for locally independent assignment statements.

**Architecture:** Reuse `TransformProbe` and exact-span mutators. Add a target-body analyzer in `transform_corpus.py` that finds adjacent same-block assignment statements, computes local read/write sets, and emits `swap_independent_adjacent_statements` only when the dependency proof is complete.

**Tech Stack:** Python 3.11, pytest, existing `src.search.directed` transform-corpus modules.

---

### Task 1: Red Tests

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`

- [x] Add metadata tests asserting `independent_statement_order.mutator_keys == ("swap_independent_adjacent_statements",)`, `generated_probe_form` does not contain `record-only`, and catalog counts increase by one concrete form.
- [x] Add mutator tests for exact two-line span replacement and stale span rejection.
- [x] Add a positive corpus fixture:

```c
void target(void) {
    s32 a;
    s32 b;
    s32 x;
    s32 y;
    a = x + 1;
    b = y + 2;
}
```

Assert the probe swaps the two assignment lines, has family `independent_statement_order`, mutator key `swap_independent_adjacent_statements`, and provenance payload includes `first_writes`, `first_reads`, `second_writes`, `second_reads`, and `movement`.

- [x] Add rejection fixtures for:
  - `a = b; b = y;`
  - `a = x; b = a;`
  - `a = x; a = y;`
  - `a = global_value; b = y;`
  - `a = *ptr; b = y;`
  - `a = obj.field; b = y;`
  - `a = arr[i]; b = y;`
  - `a = later; later = y;` when `later` is declared after the candidate pair,
  - `volatile s32 a; a = x; b = y;`
  - declarations adjacent to assignments,
  - `sink(a);`,
  - `global_value = x;`,
  - `obj->field = x;`, `obj.field = x;`, `arr[i] = x;`, `*ptr = x;`,
  - `return`, `break`, `continue`, `goto`,
  - labels, `case`, `default`,
  - comments or `fallthrough` notes between/inside candidate lines,
  - target bodies containing `#if` or other preprocessor directives,
  - statements at different brace depths,
  - locals leaked from sibling blocks.
- [x] Add CLI smoke coverage for unfiltered `plan-transforms --source-file fixture.c --write-probes --json` showing `independent_statement_order` appears through the generic cluster.
- [x] Add scorer coverage that `transform-corpus:independent_statement_order:0` is treated as an order-changing edit.
- [x] Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q -k 'independent_statement_order or statement_order'
```

Expected: failures for missing mutator key, record-only metadata, missing probes, and missing CLI candidate.

### Task 2: Mutator And Metadata

**Files:**
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`

- [x] Register `swap_independent_adjacent_statements` in `_DISPATCH` as a wrapper around `_replace_validated_span`.
- [x] Update the `independent_statement_order` family metadata with the new mutator key, executable generated form, and dependency-check wording.
- [x] Add `swap_independent_adjacent_statements` to `DIRECTED_MUTATOR_KEYS` and update catalog docs/counts.
- [x] Add `independent_statement_order` to the generic fallback cluster now that it is executable.
- [x] Update `ORDER_CHANGE_MUTATORS` in both `scorer.py` and `mutators.py` to include transform-corpus independent statement-order mutation keys.

### Task 3: Analyzer

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Test: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`

- [x] Add a small statement record carrying absolute body span, line text, compound-block id, reads, writes, and payload proof.
- [x] Collect local variable names from simple unqualified, non-volatile declarations encountered earlier in the same compound block as each statement.
- [x] Reject the entire analyzer when the target body contains any preprocessor directive.
- [x] Parse only assignment statements matching `local = expression;`, with `local` in the collected local set.
- [x] Reject assignment lines with comments, calls, control-flow keywords, labels, case/default, member/pointer/array lhs, compound assignments, increment/decrement, unknown lhs, or intentional-order words.
- [x] Compute reads as identifier tokens in the RHS that are known prior same-block locals and are not the written lhs; reject if any RHS identifier is not a known prior local or if RHS contains pointer/member/array syntax.
- [x] Pair adjacent statement records only when their line spans are directly adjacent and their compound-block id matches.
- [x] Emit an anchor when writes are disjoint and neither read set intersects the other write set.
- [x] Wire `_iter_independent_statement_order_anchors()` into `_iter_full_source_anchors()`.

### Task 4: Verification

**Files:**
- Review all changed files.

- [x] Run focused statement-order tests.
- [x] Run the broader transform-corpus/search smoke set:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/test_scorer.py \
  tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q
```

- [x] Run compile/static checks:

```bash
PYTHONPATH=tools/melee-agent python -m compileall -q \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py
git diff --check
```

- [x] Run command-level smoke for unfiltered `plan-transforms --write-probes --json`.
- [x] Request independent Codex review and fix blockers.
- [ ] Commit, refresh editable `melee-agent`, run installed CLI smoke, and resolve #689.
