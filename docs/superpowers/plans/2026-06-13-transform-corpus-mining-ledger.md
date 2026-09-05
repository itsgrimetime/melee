# Transform Corpus Mining Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a transform-corpus mining ledger so commit/function source transitions are scanned once and can be reviewed without duplicate work.

**Architecture:** Add a small SQLite-backed mining module with per-function ledger keys derived from commit, file, function, before hash, after hash, and analyzer version. Add a Typer command group that creates jobs, claims tasks, completes/fails tasks, and reports job/ledger state. Reuse `mwcc_debug.source_patch.find_function_definitions` for conservative function splitting.

**Tech Stack:** Python, sqlite3, Typer, pytest, local git subprocesses.

---

## Files

- Create: `tools/melee-agent/src/source_transform_mining.py`
  - SQLite schema, data classes, git scanner, per-function transition extraction, task lifecycle.
- Create: `tools/melee-agent/src/cli/transform_corpus.py`
  - Typer commands for `melee-agent transform-corpus mine ...`.
- Modify: `tools/melee-agent/src/cli/__init__.py`
  - Register the new top-level command group.
- Create: `tools/melee-agent/tests/test_source_transform_mining.py`
  - Unit tests for ledger keys, multi-function commit splitting, duplicate skipping, and lifecycle updates.
- Create: `tools/melee-agent/tests/test_transform_corpus_cli.py`
  - CLI smoke test for command discoverability and create-job output.

## Task 1: Ledger and Scanner Tests

- [x] **Step 1: Write failing tests**

Add tests that create a temporary git repo with one commit changing two C functions, then assert `create_job()` creates two pending tasks. Add a second `create_job()` over the same range and assert it creates zero tasks and reports two skipped ledger hits.

- [x] **Step 2: Run failing tests**

Run: `PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_source_transform_mining.py`

Expected: import failure for `src.source_transform_mining`.

- [x] **Step 3: Implement minimal module**

Create `source_transform_mining.py` with `TransformMiningStore`, `create_job()`, `claim_task()`, `complete_task()`, `fail_task()`, `job_status()`, and `ledger_stats()`.

- [x] **Step 4: Run module tests**

Run: `PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_source_transform_mining.py`

Expected: all tests pass.

## Task 2: CLI Wiring Tests

- [x] **Step 1: Write failing CLI tests**

Add a Typer runner test that `melee-agent transform-corpus mine --help` is visible and that `create-job --db <tmp> --repo <tmp_repo> --range HEAD` prints created/skipped counts.

- [x] **Step 2: Run failing CLI tests**

Run: `PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_transform_corpus_cli.py`

Expected: command is not registered.

- [x] **Step 3: Implement CLI command group**

Create `cli/transform_corpus.py`, register it in `cli/__init__.py`, and map command options to the store.

- [x] **Step 4: Run CLI tests**

Run: `PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_transform_corpus_cli.py`

Expected: all tests pass.

## Task 3: Focused Verification

- [x] **Step 1: Run focused tests**

Run: `PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_source_transform_mining.py tools/melee-agent/tests/test_transform_corpus_cli.py`

Expected: all tests pass.

- [x] **Step 2: Run related catalogue tests**

Run: `PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_source_transform_catalog.py tools/melee-agent/tests/search/directed/test_transform_corpus.py`

Expected: all tests pass.

- [x] **Step 3: Run static checks**

Run: `PYTHONPATH=tools/melee-agent python -m py_compile tools/melee-agent/src/source_transform_mining.py tools/melee-agent/src/cli/transform_corpus.py`

Expected: exit code 0.

Run: `git diff --check`

Expected: exit code 0.

---

## Mining Sweep Results: job `88baa039` (2026-06-13)

**Scope:** commit range `af6f07f43..upstream/master`, filter `[Mm]atch|100%`,
analyzer `source-transform-mining-v1`.

**Final job state:** `completed`, 9306/9306 tasks processed, 0 pending, 0
assigned (no stranded claims). Existing-function transitions were reviewed
individually (one claim at a time, `--existing-only`); no bulk completion was
used for existing-function tasks. There were no addition-only tasks to retire.

**Classification totals (authoritative, from the ledger DB):**

| result_kind | count |
| --- | ---: |
| not-useful | 7936 |
| example-for-existing-family | 1053 |
| new-family-candidate | 317 |

The 317 `new-family-candidate` rows fragmented across ~190 distinct
`family_id` aliases (Opus reviewers coined many one-off names). Consolidating
past the aliases yields the clusters below.

### Promoted to record-only families (10)

Each cluster is repeated (consolidated count shown), bounded, behavior-aware,
distinct from the prior 24 families, and a single coherent source-shape lever.
All are promoted as record-only `TransformFamily` entries (no mutator yet) in
`src/search/directed/transform_corpus.py`, with catalogue notes in
`src/mwcc_debug/source_transform_catalog.py`, example blocks in
`docs/source-transform-catalog.md`, and drift-test coverage in
`tests/test_source_transform_catalog.py` (directed family count 24 -> 34;
catalogue technique count 152 -> 162; mutator/concrete-form count unchanged at
11). Directed corpus: 24 -> 34 families.

| Promoted family | ~count | Consolidated alias names | Distinct from |
| --- | ---: | --- | --- |
| `assert_macro_expansion_shape` | 25 | assert_macro_expansion_shape, conditional_assert_macro_fold | (new) |
| `assignment_expression_temp_seed` | 28 | assignment_expression_temp_seed, chained_assignment_expression_shape, chained_assignment_field_address_choice, chained_assignment_shared_zero_shape | scoped_alias / temp_sink_hoist |
| `string_literal_data_blob_field_shape` | 17 | string_literal_data_blob_field_shape/_reference, string_literal_blob_offset_shape, string_literal_(to/vs)_data_blob_offset, string_literal_field_reference_shape, string_literal_named_symbol_shape, string_symbol_literal_replacement, global_string_literal_shape, typed_data_symbol_reference_shape, assert_message_literal_vs_symbol, assert_source_string_shape | global_float_literal_shape (string analog) |
| `raw_pointer_offset_struct_field_shape` | 16 | raw_pointer_offset_struct_field_shape, byte_offset_cast_to_struct_field, byte_pointer_cast_to_typed_index, typed_struct_pointer_cast_overlay, untyped_base_pointer_retype, field_group_overlay_struct_shape, adjacent_scalar_fields_to_typed_struct_shape, aggregate_base_pointer_shape, alias_pointer_member_access_shape, alias_vs_direct_member_access_shape, bitfield_extract_member_shape, bitfield_member_index_shape, bitmask_op_to_bitfield_member, reinterpret_cast_store_shape, struct_field_pointer_walk | raw_index_struct_field_shape (offset/cast vs index-load) |
| `comma_operator_noop_expression_shape` | 12 | comma_operator_noop_expression_shape, no_op_comma_operand_shape, noop_comma_expression_shape, comma_operator_rhs_expression_shape, comma_operator_rhs_field_access, comma_operator_regalloc_anchor | (new; pre-normalized) |
| `numeric_cast_shape` | 12 | numeric_cast_elision, redundant_numeric_cast_elision, explicit_float_cast_operand_shape, int_to_float_unsigned_cast_shape, integer_widening_cast_call_arg, unsigned_division_cast, signed_compare_rhs_cast_shape, integer_compare_cast_(elision/shape), explicit_integer_argument_cast, cast_typedef_spelling_shape, widened_param_compensating_cast | redundant_pointer_cast_elision / callback_cast_elision (numeric vs pointer) |
| `void_to_value_return_shape` | 11 | void_to_value_return_shape, wrapper_return_passthrough, return_value_forwarding_wrapper_shape, tail_call_return_(forwarding/propagation/value), forward_call_return_value, void_tail_call_return_(drop/elision), return_type_void_to_scalar, return_hoisted_loop_local, explicit_live_value_return | explicit_zero_return (forward value vs append 0) |
| `global_pointer_alias_shape` | 9 | global_pointer_alias_shape, global_pointer_alias_indirection, global_subobject_field_address_shape, global_address_member_alias_shape, global_array_index_shape, field_address_pointer_cache, alternate_type_pointer_alias | scoped_alias / data_table_indirection_shape |
| `empty_do_while_barrier` | 9 | empty_do_while_barrier, empty_if_noop_barrier, empty_conditional_noop_branch, empty_predicate_anchor, empty_probe_branch_reload, self_assignment_noop_barrier, self_assignment_field_barrier | reload_branch_scope (brace-only scope) |
| `switch_case_order_default_shape` | 7 | switch_case_order_default_shape, switch_noop_case_order_shape, empty_switch_case_shape | (new; pre-normalized) |

### Left ledger-only (not promoted), with reasons

- **PAD_STACK / stack-padding cluster (~33):** `pad_stack_frame_size_shape`
  (12), `pad_stack_array_shape` (6), and ~15 sibling pad-stack/padding-array/
  unused-local-padding aliases. Per the project rule, PAD_STACK-only changes map
  to existing stack/layout tooling (`debug mutate frame-transform-search`
  `frame-reservation-pad-stack` and `debug inspect stack-homes`), not a new
  directed transform family.
- **Non-loop integer width / signedness (~9):** `local_integer_width_shape`,
  `local_integer_width_cast_shape`, `integer_local_signedness_shape`,
  `narrow_scalar_local_widening`, `parameter_(integer/type)_width_shape`,
  `narrow_index_mask_shape`, `integer_literal_signedness_suffix`. Overlaps the
  existing `counter_type_shape` family and the `type-change` / `type-width`
  mutator/operator surfaces; a refinement of existing type-width tooling rather
  than a new bounded family.
- **Single-use temp inline/fold (~10):** `single_use_temp_inline(_fold)`,
  `intermediate_temp_inline_fold`, `subexpression_(extract_temp/temp_materialization)`,
  `arith_subexpr_(temp_reassoc/hoist_to_use)`, `arithmetic_temp_fold_inline`,
  `literal_temp_materialization`, `relay_temp_forward`. Fuzzy inverse of
  `assignment_expression_temp_seed` and overlaps `temp_sink_hoist`/`scoped_alias`;
  kept as a watch-list cluster pending a cleaner boundary.
- **Unrepeated singleton tail (~80, count == 1 each):** bounded and plausibly
  reusable, but not yet *repeated*; e.g. `guard_clause_to_nested_if`,
  `if_nest_to_goto_flatten`, `divide_to_reciprocal_multiply`,
  `modulo_subtract_rewrite`, `commutative_operand_(swap/order_swap)`,
  `compare_operand_order_swap`, `loop_(reversal_countdown/construct/decrement)_form_shape`,
  `count_down_while_to_for_loop`, `inline_keyword_storage_shape`,
  `volatile_qualifier_toggle`, `register_qualifier_hint`,
  `copy_source_from_prior_destination`, `dead_store_scratch_rematerialization`,
  `struct_(assign_vs_fieldwise_copy/copy_field_word_expansion/value_copy_field_load)`,
  `union_reinterpret_cast_materialize`, `parameter_(order_swap/reuse_as_accumulator)`,
  `local_buffer_to_parameter_hoist`, `local_to_pointer_parameter_promotion`,
  `accessor_macro_vs_function_shape`, `sizeof_allocation_size_adjustment`, etc.
  Retained as recorded candidates so a future mining pass can confirm repetition
  before promotion.
- **Mislabeled existing-family examples (~28):** candidate rows whose `family_id`
  is already one of the prior 24 families (e.g. `vector_alias_type_shape`,
  `function_codegen_pragma_shape`, `global_float_literal_shape`,
  `redundant_pointer_cast_elision`, `callback_cast_elision`,
  `minmax_macro_ternary_shape`, `unused_trailing_parameter`,
  `raw_index_struct_field_shape`, `data_table_indirection_shape`,
  `explicit_zero_return`, `zero_compare_logical_not`, `abs_macro_expression_fold`,
  `bool_int_accumulator_shape`, `independent_statement_order`). These already have
  a corpus home; the `new-family-candidate` label is a reviewer mislabel and was
  left as-is (completed rows are not re-litigated).
