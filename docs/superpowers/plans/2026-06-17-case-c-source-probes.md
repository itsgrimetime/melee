# Case C Source Probes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add directed source probes for first-divergence Case C reports in #769 and #770.

**Architecture:** Extend existing transform families rather than adding a new CLI. FPR temp simplify-order probes live in `register_steering.py`; implicit indexed-address probes live in `indexed_byte_address.py`; dispatch, registry, and orchestrator metadata stay in the existing transform corpus.

**Tech Stack:** Python 3.11, pytest, `melee-agent debug select-order-search`, transform-corpus `Anchor`/validated-span mutators.

---

### Task 1: Add FPR Case C Probes

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/register_steering.py`
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py`

- [x] **Step 1: Write failing tests**

Add `test_coloring_register_steering_emits_case_c_fpr_temp_order_probes` for the combined source shape:

```c
typedef float f32;
void mnDiagram_DrawCellNumber(unsigned char row) {
    f32 base;
    f32 y_offset;
    f32 rowf;
    f32 row_offset;
    f32 row_offset_adj;
    rowf = (f32) row;
    y_offset = HSD_JObjGetTranslationY(jobj2) - base;
    row_offset = y_offset * rowf;
    row_offset_adj = row_offset - 0.4f;
    HSD_JObjSetTranslateY(jobj, row_offset);
}
```

Add a second assertion or test for the split source shape:

```c
y_offset = HSD_JObjGetTranslationY(jobj2);
y_offset -= base;
row_offset = y_offset * rowf;
```

Both tests must assert strategies:

- `fpr-case-c-left-operand-temp`
- `fpr-case-c-rhs-owner-temp`
- `fpr-case-c-product-owner-temp`

They must assert `payload["target_local"] == "y_offset"` and candidate text
uses the source type `f32`.

Add a rejection test where the adjusted expression uses `table[i]`, `obj->x`,
`++idx`, or a second call operand; assert no `steer_fpr_case_c_temp_order` probe
is emitted.

Add `test_coloring_register_steering_case_c_key_is_directly_emitted` in
`test_orchestrator.py` so a probe generated through `generate_transform_probes`
has mutator key `steer_fpr_case_c_temp_order`.

- [x] **Step 2: Verify the tests fail**

Run:

```bash
PYTHONPATH=tools/melee-agent /opt/homebrew/bin/python3.11 -m pytest \
  tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py::test_coloring_register_steering_emits_case_c_fpr_temp_order_probes \
  tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py::test_coloring_register_steering_case_c_key_is_directly_emitted -q
```

Expected: FAIL because the strategy and direct key do not exist.

- [x] **Step 3: Implement detector, mutator, and metadata**

In `register_steering.py`, add a narrow detector for top-level FPR locals that
feed a later FPR product assignment. Support both combined `target = call() -
local;` and split `target = call(); target -= local;` forms. Emit anchors under
`steer_fpr_case_c_temp_order` with replacement snippets shaped like:

```c
f32 y_offset_left_fpr;
y_offset_left_fpr = HSD_JObjGetTranslationY(jobj2);
y_offset = y_offset_left_fpr - base;
```

```c
f32 y_offset_rhs_fpr;
y_offset_rhs_fpr = HSD_JObjGetTranslationY(jobj2) - base;
y_offset = y_offset_rhs_fpr;
```

```c
f32 y_offset_owner_fpr;
y_offset = HSD_JObjGetTranslationY(jobj2);
y_offset -= base;
y_offset_owner_fpr = y_offset;
row_offset = y_offset_owner_fpr * rowf;
```

Add `_steer_fpr_case_c_temp_order()` in `mutators.py` as a thin
`_replace_validated_span` wrapper, add it to `_DISPATCH`, list it in
`registry.py`, and add it to `_DIRECT_REGISTER_STEERING_KEYS` in
`orchestrator.py`.

- [x] **Step 4: Verify tests pass**

Run the command from Step 2 plus `test_registry.py::test_coloring_register_steering_metadata_is_executable`. Expected: PASS.

### Task 2: Add Sort Implicit Address Case C Probes

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/indexed_byte_address.py`
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus/registry.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py`
- Test: `tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py`

- [x] **Step 1: Write failing tests**

Add `test_indexed_byte_address_temp_emits_implicit_address_case_c_probes`. The fixture must include:

```c
typedef unsigned char u8;
struct MnDiagramData { u8 sorted_names[120]; };
extern struct MnDiagramData mnDiagram_804A076C;
u32 mnDiagram_SumNameKOs(int slot);
void mnDiagram_SortNamesByKOs(void) {
    struct MnDiagramData* assets = (struct MnDiagramData*) &mnDiagram_804A076C;
    u32 totals[120];
    u8* dst_iter;
    u8* dst = assets->sorted_names;
    u32* tp;
    int i;
    int n;
    u8 temp;
    dst_iter = dst;
    tp = totals;
    for (n = 0; n < 120; n++, dst_iter++, tp++) {
        *dst_iter = (u8) n;
        *tp = mnDiagram_SumNameKOs(n & 0xFF);
    }
    dst[i] = temp;
}
```

Assert strategies:

- `indexed-byte-implicit-direct-store-base`
- `indexed-byte-implicit-store-index-temp`
- `indexed-byte-implicit-init-loop-indexed-store`

Assert no strategy materializes `&mnDiagram_804A076C.sorted_names[i]`.
Assert the first emitted strategies for this family put
`indexed-byte-implicit-direct-store-base` and
`indexed-byte-implicit-store-index-temp` before
`indexed-byte-implicit-init-loop-indexed-store`. Assert the loop rewrite
preserves `tp++` and `*tp = mnDiagram_SumNameKOs(n & 0xFF);`.

Update `test_registry.py` to include new mutator keys.

- [x] **Step 2: Verify the tests fail**

Run:

```bash
PYTHONPATH=tools/melee-agent /opt/homebrew/bin/python3.11 -m pytest \
  tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py::test_indexed_byte_address_temp_emits_implicit_address_case_c_probes \
  tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py::test_indexed_byte_address_temp_metadata_is_executable -q
```

Expected: FAIL because the strategies and registry keys do not exist.

- [x] **Step 3: Implement anchors and mutators**

In `indexed_byte_address.py`, prove `dst` comes from an alias/global byte-array
field using existing `_global_aliases()` and `_direct_global_base_for_field()`
logic. Emit same-line indexed rewrites first:

```c
mnDiagram_804A076C.sorted_names[i] = temp;
```

```c
int sorted_names_store_idx_probe;
sorted_names_store_idx_probe = i;
dst[sorted_names_store_idx_probe] = temp;
```

Then emit the init-loop implicit indexed variant:

```c
for (n = 0; n < 120; n++, tp++) {
    dst[n] = (u8) n;
    *tp = mnDiagram_SumNameKOs(n & 0xFF);
}
```

Add dispatcher functions in `mutators.py` that call `_replace_validated_span`,
and register the keys in `registry.py`. Wire
`_iter_indexed_byte_address_temp_anchors()` so final-store same-line probes are
yielded before the init-loop indexed-store variant.

- [x] **Step 4: Verify tests pass**

Run the command from Step 2. Expected: PASS.

### Task 3: Run Focused Verification and Resolve Issues

**Files:**
- No production edits expected.

- [x] **Step 1: Run focused tests**

```bash
PYTHONPATH=tools/melee-agent /opt/homebrew/bin/python3.11 -m pytest \
  tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py -q
```

Expected: all tests pass.

- [x] **Step 2: Run syntax and whitespace checks**

```bash
PYTHONPATH=tools/melee-agent /opt/homebrew/bin/python3.11 -m compileall -q \
  tools/melee-agent/src/search/directed tools/melee-agent/src/search/directed/transform_corpus
git diff --check -- \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/search/directed/transform_corpus/indexed_byte_address.py \
  tools/melee-agent/src/search/directed/transform_corpus/register_steering.py \
  tools/melee-agent/src/search/directed/transform_corpus/registry.py \
  tools/melee-agent/src/search/directed/transform_corpus/orchestrator.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_indexed_byte_address.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_register_steering.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_registry.py \
  tools/melee-agent/tests/search/directed/transform_corpus/test_orchestrator.py
```

Expected: both commands exit 0.

- [x] **Step 3: Run filed-function smokes from a clean source baseline**

Before smoke tests, check:

```bash
git -C /Users/mike/.codex/worktrees/eeff/melee status --short src/melee/mn/mndiagram.c
```

If it is dirty from generated probe leftovers, use a clean worktree or restore
only the generated probe leftovers after confirming they are not user work.

Run no-compile and compiled `debug select-order-search` for:

- `mnDiagram_DrawCellNumber`, class 1, target `f33<f39`, force `39:26,33:28`;
- `mnDiagram_SortNamesByKOs`, class 0, target `r34<r44`, force `34:27,44:25`.

Rerun `debug inspect first-divergence` on the best ranked candidate or record
the unchanged first-divergence artifact if all new probes miss. Expected: new
probes appear in no-compile output; compiled variants are `ok` or produce
actionable diagnostics; notes include force-phys, opcode-shape, frame, and
first-divergence before/after evidence.

- [x] **Step 4: Commit, refresh install, resolve**

Stage only touched spec/plan/code/test files, commit to `master`, run:

```bash
/opt/homebrew/bin/python3.11 -m pip install -e tools/melee-agent
```

Verify `/opt/homebrew/bin/melee-agent` imports from
`/Users/mike/code/melee/tools/melee-agent/src`, resolve #769/#770 with evidence,
and confirm `melee-agent issues list` is empty or only blocked/in-actionable
issues remain.
