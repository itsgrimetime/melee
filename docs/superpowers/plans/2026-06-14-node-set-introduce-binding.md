# Node-Set Introduce-Binding Split Realizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `node_set_delta` entries with safe unbindable source expressions produce typed node-set split candidates instead of being dropped as unbindable.

**Architecture:** Keep existing bindable-local parsing and split families intact. Add conservative introduce-binding metadata and patch generation inside `tools/melee-agent/src/mwcc_debug/node_set_split.py`, then route the new family through the existing solve CLI and transform-corpus probe bridge.

**Tech Stack:** Python 3.11, pytest, Typer CLI tests, existing `CandidatePatch`, `StatementSpan`, and node-set split helpers.

---

## File Structure

- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
  - Add request metadata for introducible expressions.
  - Add safe type/expression admission helpers.
  - Add introduce-binding patch generation and mixed coupled composition.
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
  - Route blocked-but-introducible single requests through candidate generation.
  - Build coupled requests from bindable plus introducible entries.
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
  - Materialize introduce-binding probes through the node-set delta bridge.
- Modify: `tools/melee-agent/src/search/cli/__init__.py`
  - Classify introducible entries as materializable rather than skipped when a probe exists.
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
  - Register the introduced-binding node-set probe key in directed transform metadata.
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`
  - Keep catalog counts and node-set materialized probe key expectations in sync.
- Modify: `tools/melee-agent/tests/test_node_set_split.py`
  - Unit coverage for request parsing, patch generation, rejection, and mixed coupled composition.
- Modify: `tools/melee-agent/tests/search/solver/test_cli_solve.py`
  - CLI route coverage for field-expression deltas.
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
  - Transform-corpus smoke coverage for introduced-binding probes.

## Task 1: Add Failing Unit Tests

**Files:**
- Modify: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Add request metadata test**

Add a test below `test_request_from_node_set_delta_does_not_bind_field_expression_name`:

```python
def test_request_from_node_set_delta_records_introducible_field_expression() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    int out;\n"
        "    out = entries[i].stat_value;\n"
        "    use(out);\n"
        "}\n"
    )
    delta = {
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 42,
            "current_register": "r29",
            "desired_registers": ["r27"],
            "source": {"kind": "field-load", "expression": "entries[i].stat_value"},
        }],
    }

    req = request_from_node_set_delta(delta, source_text=source)

    assert req is not None
    assert req.var_name is None
    assert req.blocked_reason is not None
    assert req.source_expression == "entries[i].stat_value"
    assert req.source_type == "int"
    assert req.source_kind == "field-load"
```

- [ ] **Step 2: Add introduce-binding candidate tests**

Add tests that import and exercise `generate_node_set_introduce_binding_patches`:

```python
def test_generate_node_set_introduce_binding_patches_splits_field_expression() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    int out;\n"
        "    out = entries[i].stat_value;\n"
        "    use(out);\n"
        "}\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 42,
            "current_register": "r29",
            "desired_registers": ["r27"],
            "source": {"kind": "field-load", "expression": "entries[i].stat_value"},
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    assert patches
    assert patches[0].candidate_id.startswith("node-split-introduce-binding-ig42-")
    candidate_text = "\n".join(patch.patched_source for patch in patches)
    assert "int stat_value_bind_42_0;" in candidate_text
    assert "stat_value_bind_42_0 = entries[i].stat_value;" in candidate_text
    assert "out = stat_value_bind_42_0;" in candidate_text
    assert "stat_value_bind_42_0_split_42_0" in candidate_text
```

```python
def test_generate_node_set_introduce_binding_patches_handles_initialized_declaration() -> None:
    source = (
        "typedef struct Entry { int stat_value; } Entry;\n"
        "void fn_test(Entry* entries, int i) {\n"
        "    int out = entries[i].stat_value;\n"
        "    use(out);\n"
        "}\n"
    )
    req = request_from_node_set_delta({
        "function": "fn_test",
        "class_id": 0,
        "missing_virtuals": [{
            "target_ig": 42,
            "desired_registers": ["r27"],
            "source": {"kind": "field-load", "expression": "entries[i].stat_value"},
        }],
    }, source_text=source)

    patches = generate_node_set_introduce_binding_patches(
        source, "fn_test", req, max_bind_sites=1, max_read_sites=1
    )

    bind_only = next(
        patch for patch in patches
        if patch.candidate_id.endswith("-bind-site0")
    )
    assert "int stat_value_bind_42_0 = entries[i].stat_value;" in bind_only.patched_source
    assert "int out = stat_value_bind_42_0;" in bind_only.patched_source
```

- [ ] **Step 3: Add rejection and coupled tests**

Add tests for no type/call/lvalue rejection, address-of cursor binding, FPR
typed expression binding, original-source hunk generation, and one bindable
plus one introduced coupled request.

- [ ] **Step 4: Run the new tests and verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_node_set_split.py::test_request_from_node_set_delta_records_introducible_field_expression \
  tools/melee-agent/tests/test_node_set_split.py::test_generate_node_set_introduce_binding_patches_splits_field_expression \
  tools/melee-agent/tests/test_node_set_split.py::test_generate_node_set_introduce_binding_patches_handles_initialized_declaration \
  -q
```

Expected: FAIL because request metadata and generator do not exist yet.

## Task 2: Implement Core Introduce-Binding Generator

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Extend `NodeSetSplitRequest`**

Add optional fields with defaults:

```python
source_expression: str | None = None
source_type: str | None = None
source_kind: str | None = None
```

- [ ] **Step 2: Record introducible metadata during request parsing**

In `_request_from_missing_virtual`, when `_bindable_source_name` returns `None`,
populate expression/kind/type. Infer type from source text using a new helper
that accepts only delta-provided safe types, plain assignments, and initialized
declarations.

- [ ] **Step 3: Add `generate_node_set_introduce_binding_patches`**

Generate binding sources for safe expression occurrences. Emit an explicit
binding-only `CandidatePatch` for each safe site, then call
`generate_node_set_split_patches` on each bound source with a synthetic request
whose `var_name` is the introduced temp. Prefix each returned candidate ID and
summary with introduce-binding context. Rebuild every final hunk and touched
range against the original source.

- [ ] **Step 4: Update coupled generation**

Teach `generate_coupled_node_set_split_patches` to call a small dispatcher that
uses the existing split generator for bindable requests and the new generator
for introducible requests.

- [ ] **Step 5: Run unit tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_node_set_split.py -q
```

Expected: PASS.

## Task 3: Route CLI And Transform Paths

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/search/cli/__init__.py`
- Modify: `tools/melee-agent/tests/search/solver/test_cli_solve.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [ ] **Step 1: Add failing CLI and transform tests**

Update the existing field-expression CLI test so it expects generated candidate
work rather than an immediate blocked summary. Add a transform smoke test where
`plan-transforms --node-set-delta` writes a `steer_node_set_delta_introduce_binding_split`
probe for `entries[i].stat_value`.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/solver/test_cli_solve.py::test_solve_node_set_split_blocks_field_expression_delta \
  tools/melee-agent/tests/search/test_cli_smoke.py::test_search_plan_transforms_reports_all_unbindable_node_set_delta \
  -q
```

Expected: FAIL under the updated expectations.

- [ ] **Step 3: Import and call the introduce-binding generator**

In `debug solve node-set-split`, if the request has no `var_name` but carries
`source_expression` and `source_type`, generate introduce-binding patches
instead of exiting immediately. For coupled mode, build requests from a helper
that includes bindable and introducible entries.

- [ ] **Step 4: Route transform probes**

In `transform_corpus`, include introducible requests in the node-set request
list and emit `steer_node_set_delta_introduce_binding_split` for single
introduced-binding patches. Preserve skipped/capped metadata for entries that
still cannot be materialized.

- [ ] **Step 5: Update transform catalog metadata**

Add `steer_node_set_delta_introduce_binding_split` to directed transform
metadata and catalog tests. Increment the expected concrete-form count in
`test_source_transform_catalog.py`.

- [ ] **Step 6: Run focused CLI tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/solver/test_cli_solve.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -q
```

Expected: PASS.

## Task 4: Verification, Commit, Install Refresh

**Files:**
- Modify: tracked files from Tasks 1-3 only.

- [ ] **Step 1: Run focused verification**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_node_set_split.py \
  tools/melee-agent/tests/search/solver/test_cli_solve.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -q
python -m compileall -q tools/melee-agent/src
git diff --check
melee-agent debug solve node-set-split --help >/tmp/node-set-split-help.txt
melee-agent debug search plan-transforms --help >/tmp/plan-transforms-help.txt
```

Expected: all commands exit 0.

- [ ] **Step 2: Commit**

Run:

```bash
git add docs/superpowers/specs/2026-06-14-node-set-introduce-binding-design.md \
  docs/superpowers/plans/2026-06-14-node-set-introduce-binding.md \
  tools/melee-agent/src/mwcc_debug/node_set_split.py \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/src/search/cli/__init__.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py \
  tools/melee-agent/tests/test_node_set_split.py \
  tools/melee-agent/tests/search/solver/test_cli_solve.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py
git commit -m "feat: add node-set introduce-binding splits"
```

- [ ] **Step 3: Refresh editable install and resolve issue**

Run:

```bash
python -m pip install -e tools/melee-agent
python - <<'PY'
import src.cli, pathlib
print(pathlib.Path(src.cli.__file__).resolve())
PY
DECOMP_AGENT_ID=codex-issue-resolver-3-20260614g melee-agent issue resolve 707 --note "fixed in <commit>"
```

Expected: import path points inside `/Users/mike/code/melee/tools/melee-agent`.
