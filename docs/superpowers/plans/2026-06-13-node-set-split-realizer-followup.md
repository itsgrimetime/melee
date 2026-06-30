# Node Set Split Realizer Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `debug solve node-set-split` temp source handling and add bounded decl-order, per-loop rename, and simple reassociation candidate families.

**Architecture:** Keep the CLI surface unchanged. Put source candidate generation in `tools/melee-agent/src/mwcc_debug/node_set_split.py`; keep CLI orchestration in `tools/melee-agent/src/cli/debug/__init__.py`. All candidates continue through the existing pcdump objective gate before checkdiff scoring.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing Melee `mwcc_debug` source helpers.

---

### Task 1: Repo-Local Candidate Temp Directory

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/search/solver/test_cli_solve.py`

- [ ] **Step 1: Write the failing CLI path test**

Add a test that monkeypatches `_node_set_split_compile_signature` and records
candidate paths. The test invokes:

```python
runner.invoke(debugcli.debug_app, [
    "solve", "node-set-split",
    "-f", "fn_test",
    "--class", "gpr",
    "--ig", "40",
    "--target-reg", "r30",
    "--var", "holder",
    "--json",
])
```

Assert every non-baseline path is under
`tmp_path / "build" / "mwcc_debug_cache" / "probes" / "node_set_split"` and
that the per-run directory is cleaned after command completion.

- [ ] **Step 2: Verify the test fails**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/solver/test_cli_solve.py::test_solve_node_set_split_uses_repo_local_probe_dir -q
```

Expected: FAIL because candidate paths currently use the system temp directory.

- [ ] **Step 3: Implement repo-local temp directory**

In `solve_node_set_split_cmd`, replace:

```python
with tempfile.TemporaryDirectory(prefix="node_set_split_") as temp_name:
```

with parent creation under `DEFAULT_MELEE_ROOT / "build" / "mwcc_debug_cache" / "probes" / "node_set_split"` and:

```python
with tempfile.TemporaryDirectory(
    prefix="node_set_split_",
    dir=probe_root,
) as temp_name:
```

- [ ] **Step 4: Verify the test passes**

Run the same single test and confirm PASS.

### Task 2: Declaration-Order Candidate Family

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Write failing decl-order tests**

Add a positive test where `holder` is one of several locals and assert a
candidate ID beginning with `node-split-decl-order-holder-ig40-` is generated.
Add a dependency test where moving an initialized declaration would place it
before a dependency and assert no unsafe candidate appears.

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_node_set_split.py::test_generate_node_set_split_patches_emits_decl_order_candidates tools/melee-agent/tests/test_node_set_split.py::test_generate_node_set_split_patches_skips_decl_order_initializer_dependency -q
```

Expected: FAIL because only alias and lifetime candidates exist.

- [ ] **Step 3: Implement decl-order generation**

Import `build_decl_order_candidates_for_scope`, `explain_decl_reorder_skip`,
`get_decl_names_by_scope`, and `reorder_decls_in_function_scope`. For scopes
containing `request.var_name`, build `strategy="all"` candidates, keep bounded
labels involving the requested variable, skip orders with a non-empty
`explain_decl_reorder_skip`, and append unique `CandidatePatch` instances.

- [ ] **Step 4: Verify the decl-order tests pass**

Run the two focused tests and confirm PASS.

### Task 3: Per-Loop Rename Candidate Family

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Write failing per-loop rename tests**

Add a positive test with two simple loops that independently assign and read
`holder`; assert a `node-split-loop-rename-holder-ig40-` candidate adds
`holder_loop_40_0` and `holder_loop_40_1`. Add negative tests for address-taking,
read-after-loop, loop-header/update use, carried value before first assignment,
and nested block use.

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_node_set_split.py -k 'per_loop_rename' -q
```

Expected: FAIL because the family does not exist.

- [ ] **Step 3: Implement conservative loop rename generation**

Add small helpers in `node_set_split.py` to find simple top-level `for` and
`while` blocks, reject unsafe loops, insert same-type declarations beside the
original declaration, and replace whole-word occurrences inside each accepted
loop body only.

- [ ] **Step 4: Verify the per-loop tests pass**

Run the focused per-loop tests and confirm PASS.

### Task 4: Simple Integer Reassociation Candidate Family

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Write failing reassociation tests**

Add a positive test for `holder = idx + base;` that expects a
`node-split-reassoc-holder-ig40-` candidate with `holder = base + idx;`.
Add negative tests for calls, casts, field/member operands, array operands,
compound assignments, and three-term additions.

- [ ] **Step 2: Verify the tests fail**

Run the new reassociation tests by name. Expected: FAIL because the family does
not exist.

- [ ] **Step 3: Implement reassociation generation**

Add a helper that scans direct assignment statements for exactly two safe
operands joined by `+`, swaps operands, and appends unique patches.

- [ ] **Step 4: Verify the reassociation tests pass**

Run the focused reassociation tests and confirm PASS.

### Task 5: Integration Verification and Commit

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/search/solver/test_cli_solve.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Run narrow tests**

```bash
python -m pytest tools/melee-agent/tests/search/solver/test_cli_solve.py tools/melee-agent/tests/test_node_set_split.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run CLI smoke checks**

```bash
python -m src.cli debug solve node-set-split --help
python -m src.cli debug solve node-set-split -f fn_test --ig 40 --target-reg r30 --var holder --json
```

The help command exits 0. The explicit `fn_test` command may exit 2 because the
function does not exist in real `report.json`; that smoke confirms command
dispatch and option parsing.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-13-node-set-split-realizer-design.md docs/superpowers/plans/2026-06-13-node-set-split-realizer-followup.md tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/src/mwcc_debug/node_set_split.py tools/melee-agent/tests/search/solver/test_cli_solve.py tools/melee-agent/tests/test_node_set_split.py
git commit -m "Fix node-set split source realization"
```
