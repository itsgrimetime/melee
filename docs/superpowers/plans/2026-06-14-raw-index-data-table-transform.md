# Raw Index And Data Table Transform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add guarded executable probes for raw indexed struct-field rewrites and source-local data-table indirection rewrites.

**Architecture:** Reuse the directed transform-corpus full-source anchor path. Add exact-span mutators, extend the existing simple struct-layout proof helpers, and add a narrow source-local immutable pointer-table analyzer. Keep both families high risk and abstain on ambiguous layout, mutability, or scope.

**Tech Stack:** Python 3.11, pytest, `src.search.directed.transform_corpus`, `src.search.directed.mutators`, existing source-transform catalog tests.

---

### Task 1: Red Tests And Metadata

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`

- [x] Add metadata tests asserting `data_table_indirection_shape.mutator_keys == ("rewrite_data_table_indirection",)` and `raw_index_struct_field_shape.mutator_keys == ("rewrite_raw_index_struct_field",)`.
- [x] Assert both families no longer include `record-only` in `generated_probe_form`.
- [x] Update catalog count expectations from 96 to 98 total concrete forms and from 43 to 45 directed concrete forms.
- [x] Add required directed mutator keys `rewrite_raw_index_struct_field` and `rewrite_data_table_indirection`.
- [x] Add mutator unit tests:

```python
def test_rewrite_raw_index_struct_field_validates_span() -> None:
    src = "void f(void) {\n    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);\n}\n"
    span_text = "*(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10)"
    start = src.index(span_text)
    anchor = Anchor(
        "rewrite_raw_index_struct_field",
        (start, start + len(span_text)),
        {
            "span_text": span_text,
            "replacement_text": "entries[i].voice_id",
        },
    )

    assert apply_mutator("rewrite_raw_index_struct_field", anchor, src) == (
        "void f(void) {\n    value = entries[i].voice_id;\n}\n"
    )


def test_rewrite_raw_index_struct_field_rejects_stale_span() -> None:
    src = "void f(void) {\n    value = entries[i].voice_id;\n}\n"
    anchor = Anchor(
        "rewrite_raw_index_struct_field",
        (0, 3),
        {
            "span_text": "*(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10)",
            "replacement_text": "entries[i].voice_id",
        },
    )

    assert apply_mutator("rewrite_raw_index_struct_field", anchor, src) is None


def test_rewrite_data_table_indirection_validates_span() -> None:
    src = "void f(void) {\n    value = table_b[idx];\n}\n"
    span_text = "table_b[idx]"
    start = src.index(span_text)
    anchor = Anchor(
        "rewrite_data_table_indirection",
        (start, start + len(span_text)),
        {
            "span_text": span_text,
            "replacement_text": "sOuterTable[1][idx]",
        },
    )

    assert apply_mutator("rewrite_data_table_indirection", anchor, src) == (
        "void f(void) {\n    value = sOuterTable[1][idx];\n}\n"
    )
```

- [x] Add positive raw-index fixture:

```c
typedef unsigned char u8;
typedef int s32;
typedef struct Entry {
    u8 pad0[0x10];
    s32 voice_id;
    s32 entity;
} Entry;

void target(Entry* entries, s32 i, s32 value) {
    value = *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x10);
    *(s32*) ((u8*) entries + i * sizeof(Entry) + 0x14) = value;
}
```

Assert two `raw_index_struct_field_shape` probes rewrite to `entries[i].voice_id` and `entries[i].entity = value`, include `access_kind` values `load` and `store`, and carry `field_offset`, `field_type`, `field_name`, `struct_type`, `base`, `index_expr`, and `proof_source == "source-local-struct-layout"`.

- [x] Add raw-index unsafe fixtures rejecting:
  - struct typedef after target,
  - implicit alignment gap (`u8 pad[1]; s32 field;`),
  - mismatched cast type,
  - index scale not equal to `sizeof(Entry)` or recovered struct size,
  - non-pointer base parameter,
  - complex index expression such as `i + 1`,
  - preprocessor-hidden struct declaration,
  - bitfield member,
  - duplicate field proof at same offset/type.
- [x] Add positive data-table fixture:

```c
typedef int s32;
extern s32 table_a[];
extern s32 table_b[];
extern s32 table_c[];
static s32* const sOuterTable[] = { table_a, table_b, table_c };

void target(s32 idx, s32 value) {
    value = table_b[idx];
}
```

Assert one `data_table_indirection_shape` probe rewrites to `sOuterTable[1][idx]` and carries `table_symbol`, `element_symbol`, `table_index`, `index_expr`, `element_type`, and `proof_source == "source-local-immutable-table"`.

- [x] Add data-table unsafe fixtures rejecting:
  - mutable table declaration `static s32* sOuterTable[]`,
  - duplicate element `table_b` in the initializer,
  - missing top-level direct-symbol declaration,
  - table declaration after target,
  - write `table_b[idx] = value`,
  - address-take `use(&table_b)`,
  - reassignment `table_b = other`,
  - outer table write `sOuterTable[1] = table_c`,
  - complex index expression `idx + 1`,
  - local shadow of `table_b` or `sOuterTable`,
  - local table declaration inside a helper,
  - preprocessor-hidden table declaration.
- [x] Add CLI smoke using unfiltered `plan-transforms --source-file fixture.c --write-probes --json` and asserting candidate files exist for both new family ids.
- [x] Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q -k 'raw_index_struct_field or data_table_indirection or source_transform_catalog'
```

Expected: failures for missing mutator keys, missing dispatch entries, missing probes, and stale catalog counts.

### Task 2: Mutators And Catalog Wiring

**Files:**
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`

- [x] Add `_rewrite_raw_index_struct_field(anchor, source_text)` returning `_replace_validated_span(anchor, source_text)`.
- [x] Add `_rewrite_data_table_indirection(anchor, source_text)` returning `_replace_validated_span(anchor, source_text)`.
- [x] Register both functions in `_DISPATCH`.
- [x] Update `DEFAULT_TRANSFORM_FAMILIES`:
  - `data_table_indirection_shape.mutator_keys = ("rewrite_data_table_indirection",)`,
  - `raw_index_struct_field_shape.mutator_keys = ("rewrite_raw_index_struct_field",)`,
  - update generated probe text to remove record-only wording.
- [x] Add both family ids to the generic fallback cluster if they are not already present.
- [x] Add both mutator keys to `DIRECTED_MUTATOR_KEYS`.
- [x] Update source-transform catalog notes and docs to describe the narrow first slice and keep broader historical examples marked as still manual when they require alias/table inference.
- [x] Run the focused metadata/mutator tests from Task 1. Expected: metadata and dispatch tests pass, probe-generation tests still fail until analyzers exist.

### Task 3: Raw Indexed Struct Field Analyzer

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Test: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`

- [x] Replace `_simple_struct_field_offsets()` with a richer helper that returns one simple layout proof per typedef struct visible before the target. The helper should:
  - parse only top-level `typedef struct Tag { ... } Name;`,
  - ignore declarations inside functions,
  - blank disabled preprocessor regions, literals, and comments,
  - support `u8 pad[N];`,
  - support scalar or pointer fields with a single declarator,
  - compute field offsets and total size using explicit scalar sizes only,
  - reject implicit alignment gaps by requiring each field offset to be naturally aligned,
  - mark the whole struct unsupported on unions, bitfields, arrays other than `u8` padding, multi-declarators, unknown types, or duplicate `(offset, normalized_type)` proofs.
- [x] Keep `_iter_raw_pointer_offset_anchors()` working by reading the new layout proof map.
- [x] Add `_iter_raw_index_struct_field_anchors(source_text, span)` and wire it into `_iter_full_source_anchors()`.
- [x] The analyzer should scan the target body with comments/literals/preprocessor regions blanked and match:

```text
*(TYPE*) ((u8*) BASE + INDEX * sizeof(STRUCT) + OFFSET)
*(TYPE*) ((u8*) BASE + INDEX * SCALE + OFFSET)
```

- [x] Base must be a pointer parameter whose normalized type is `STRUCT`.
- [x] Index must be a simple identifier or integer literal.
- [x] Scale must be `sizeof(STRUCT)` or a literal equal to recovered struct size.
- [x] Offset and cast type must exactly match one recovered field proof.
- [x] Load probe span is only the raw expression; replacement is `base[index].field`.
- [x] Store probe span is only the raw expression on the left-hand side; replacement is `base[index].field`.
- [x] Payload must include `span_text`, `replacement_text`, `access_kind`, `base`, `index_expr`, `scale`, `field_offset`, `field_type`, `field_name`, `struct_type`, `struct_size`, `proof_source`, and `target_function`.
- [x] Run focused raw-index tests and fix until green.

### Task 4: Data Table Indirection Analyzer

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Test: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`

- [x] Add a dataclass for source-local immutable table proofs with table symbol, element type, element symbols, declaration span, and element indexes.
- [x] Add `_source_local_data_tables(source_text, before_offset)` that:
  - scans only source before the target function,
  - blanks disabled preprocessor regions, literals, and comments,
  - rejects declarations inside functions,
  - matches `static TYPE* const TABLE[] = { elem_a, elem_b };` and `const TYPE* const TABLE[] = { elem_a, elem_b };`,
  - requires every initializer element to be a simple identifier,
  - rejects duplicate element symbols,
  - requires visible top-level direct-symbol declarations before the target,
  - rejects local table declarations.
- [x] Add full-source identity guards that reject a table proof when the unblanked searchable source has:
  - `&TABLE` or `&ELEMENT`,
  - assignments to `TABLE[...]`,
  - assignments to `ELEMENT`,
  - local shadows of either symbol in the target body.
- [x] Add `_iter_data_table_indirection_anchors(source_text, span)` and wire it into `_iter_full_source_anchors()`.
- [x] The analyzer should scan only target function read expressions `element[index]`, not assignment LHS writes.
- [x] Index must be a simple identifier or integer literal.
- [x] Replacement is `table_symbol[element_index][index]`.
- [x] Payload must include `span_text`, `replacement_text`, `table_symbol`, `element_symbol`, `table_index`, `index_expr`, `element_type`, `proof_source`, `target_function`, and `declaration_span`.
- [x] Run focused data-table tests and fix until green.

### Task 5: Verification, Review, Commit

**Files:**
- Review all changed files.

- [x] Run focused tests:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q -k 'raw_index_struct_field or data_table_indirection or source_transform_catalog'
```

- [x] Run broader affected suite:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_coalesce_search.py \
  tools/melee-agent/tests/test_select_order_search.py \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/test_frame_transform_search.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py \
  tools/melee-agent/tests/search/directed/test_scorer.py \
  tools/melee-agent/tests/test_source_transform_catalog.py -q
```

- [x] Run compile/static checks:

```bash
PYTHONPATH=tools/melee-agent python -m compileall -q \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py
git diff --check
```

- [x] Run command-level smoke with `/opt/homebrew/bin/melee-agent debug search plan-transforms --write-probes --json` on a temp source containing both raw-index and data-table fixtures.
- [x] Request independent implementation review and fix blockers.
- [x] Commit the spec, plan, tests, implementation, and docs.
- [x] Refresh editable install with:

```bash
/opt/homebrew/opt/python@3.11/bin/python3.11 -m pip install -e /Users/mike/code/melee/tools/melee-agent
/opt/homebrew/opt/python@3.11/bin/python3.11 - <<'PY'
import src, src.launcher
print(src.__file__)
print(src.launcher.__file__)
PY
```

- [x] Run installed CLI smoke and resolve issue #690 with the commit hash.

### Verification Notes

- Focused regressions: `39 passed, 303 deselected`.
- Broader affected suite: `595 passed`.
- Static checks: `compileall` on changed Python modules and `git diff --check`.
- CLI smoke: `/opt/homebrew/bin/melee-agent debug search plan-transforms --source-file ... --write-probes --json` materialized `raw_index_struct_field_shape` and `data_table_indirection_shape`.
- Independent implementation review found two guard gaps; both are fixed with regressions for tail-padded raw-index literal scales and non-top-level data-table direct declarations.
