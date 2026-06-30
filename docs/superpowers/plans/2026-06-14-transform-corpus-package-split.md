# transform_corpus Package Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 6756-line `tools/melee-agent/src/search/directed/transform_corpus.py` into a flat `transform_corpus/` package (16 focused modules) and mirror its 6109-line test file into a `transform_corpus/` test package (14 files) — a pure, behavior-preserving relocation.

**Architecture:** A deterministic carve-out tool (`tools/melee-agent/dev/tc_split.py`, already written and validated during planning) computes the symbol→module assignment by AST reachability, emits each module (faithful line-block extraction that preserves decorators and leading comments) with a computed import header, and emits the mirrored test files. The package `__init__.py` re-exports the public API so every import site is unchanged. Correctness is proven by the existing test suite (321 cases) passing identically and ruff's F821 (undefined-name) gate.

**Tech Stack:** Python 3.11, pytest, ruff (CI gate: `ruff check src/ tests/ --select F821`). No new runtime dependencies.

---

## Critical Context (read before any task)

1. **Worktree.** All work happens in `/Users/mike/code/melee-tc-refactor` (branch `refactor/transform-corpus-package`, off `master`). Subagents MUST operate here, not in `/Users/mike/code/melee`.

2. **The editable `.pth` pins the MAIN checkout onto `sys.path`.** Every command MUST prefix `PYTHONPATH` and assert the worktree wins, or you will silently test the wrong code:
   ```bash
   cd /Users/mike/code/melee-tc-refactor/tools/melee-agent
   export PYTHONPATH=/Users/mike/code/melee-tc-refactor/tools/melee-agent
   python -c "import src; assert 'melee-tc-refactor' in src.__file__, src.__file__; print('OK', src.__file__)"
   ```

3. **Run tests with coverage off** (`addopts` forces `--cov`, which is slow and irrelevant here):
   ```bash
   python -m pytest <targets> -o addopts="" -p no:cacheprovider -q
   ```

4. **Three PRE-EXISTING test failures** exist on the clean baseline (verified at `2b6aa3d12`), unrelated to this refactor (they raise `FileNotFoundError` — missing environment fixture):
   - `tests/search/directed/test_run_source_shape.py::test_source_shape_proposal_skips_explicit_zero_return_for_named_void_function`
   - `tests/search/test_structure.py::test_loop_shape_expanded_helper_replaces_scan_and_goto_heavy_skips_helper`
   - `tests/search/test_structure.py::test_loop_shape_expanded_covers_actual_mndiagram_visible_scans`

   Final verification confirms the SAME three (and only those) fail afterward — i.e., **no new failures**. Do not try to fix them.

5. **The carve-out tool** `tools/melee-agent/dev/tc_split.py` already exists in the worktree (untracked) and was validated end-to-end during planning (built the package + test package; 321 tests passed; F821 clean; `DEFAULT_TRANSFORM_FAMILIES` ids identical). It is a disposable scaffold — **do not commit it** (it parses the monolith and becomes non-functional post-split) and remove it in the final task. Its commands:
   ```
   python dev/tc_split.py check          # assert 300 symbols each assigned once
   python dev/tc_split.py summary        # per-source-module symbol/LOC table
   python dev/tc_split.py test-summary   # per-test-file count table
   python dev/tc_split.py build-package  # write transform_corpus/ package, remove monolith
   python dev/tc_split.py build-tests    # write test package, remove monolith test file
   python dev/tc_split.py list <m>       # symbols assigned to source module m
   python dev/tc_split.py emit <m>       # full text of source module m (for inspection)
   ```

6. **`git add` SPECIFIC paths only** — never `git add -A`/`git add .` (it would stage the untracked `dev/` scaffold).

7. **CI gate is `ruff check ... --select F821` only** — not import-sorting or formatting. The monolith itself is not import-sorted/format-clean today, so do NOT run `ruff format`/`--fix` (that would add unrelated reformatting churn). The only lint requirement is F821-clean (no undefined names).

---

## File Structure

### Source package: `tools/melee-agent/src/search/directed/transform_corpus/`

| Module | ~LOC | Responsibility |
|---|---|---|
| `__init__.py` | ~30 | Re-export shim: the 7 public symbols + `__all__`. |
| `models.py` | ~45 | Public dataclasses: `TransformFamily`, `TransformCluster`, `TransformExperimentPlan`, `TransformProbe`. |
| `common.py` | ~360 | 39 helpers used by ≥2 families (text/line records, blanking, spans, type/signature normalization, simple struct layout). |
| `registry.py` | ~740 | `DEFAULT_TRANSFORM_FAMILIES`, `_FAMILY_BY_ID`, `_FAMILY_IDS_BY_MUTATOR`, `plan_transform_experiments` + plan helpers. |
| `orchestrator.py` | ~370 | `generate_transform_probes`, `_iter_full_source_anchors`, `_iter_target_function_anchors`, dispatch helpers. |
| `register_steering.py` | ~1580 | 9 iterators (decl rotation/demote, loop-counter reuse/split, byte-widen, FPR product, node-set-delta, concrete/body) + 3 dead-but-kept helpers. |
| `contract_signature.py` | ~600 | Unused-trailing-parameter contract editing + `_Contract*` dataclasses. |
| `type_cast.py` | ~850 | Pointer-assignment/call casts, vector-alias, type-cast compatibility (merged: `_iter_type_cast_compatibility_anchors` delegates to the pointer-cast iterators). |
| `struct_field_access.py` | ~485 | Raw-index struct field, raw pointer offset, data-table indirection. |
| `helper_extract.py` | ~290 | Helper inline / extract / shape. |
| `float_literal.py` | ~240 | Global float-literal replacement. |
| `local_reuse.py` | ~205 | Same-type local lifetime reuse. |
| `statement_order.py` | ~165 | Independent statement reordering. |
| `pragma_codegen.py` | ~120 | `dont_inline` pragma wrapper. |
| `return_tail_call.py` | ~60 | Return tail-call rewrite. |
| `string_data_field.py` | ~50 | String data-field anchors. |
| `pointer_alias.py` | ~45 | Global pointer-alias rewrite. |

`check` asserts all **300 top-level symbols** are assigned to exactly one module. Import DAG (validated acyclic): `models ← common ← {families, registry} ← orchestrator`; `registry → models`; only `orchestrator` imports the families. (Per-module LOC above are approximate — the tool is the source of truth; run `python dev/tc_split.py summary` for exact symbol counts.)

> **Bare module-level statement caveat (one case).** The monolith has exactly one top-level statement that is not a named symbol: the `for` loop (monolith L704-710) that populates `_FAMILY_IDS_BY_MUTATOR`. The tool models named symbols only; `emit()`'s gap-capture attaches this loop to the *following* symbol's block (`_MNDIAGRAM_COLORING_TARGETS`, also `registry`), so it correctly lands in `registry.py` after the dict it fills. This is verified (57 entries populated post-split) but relies on placement, so Task 2 asserts the dict is non-empty. If a future edit inserts a named symbol between the loop and `_MNDIAGRAM_COLORING_TARGETS`, re-check placement.

### Test package: `tools/melee-agent/tests/search/directed/transform_corpus/`

14 files mirroring the modules (helpers co-located with their family). Counts include co-located helper functions:

`test_registry.py` (16) · `test_orchestrator.py` (17, incl. scheduler + generic E2E) · `test_register_steering.py` (30) · `test_struct_field_access.py` (7) · `test_helper_extract.py` (6) · `test_pragma_codegen.py` (6) · `test_contract_signature.py` (5) · `test_float_literal.py` (5) · `test_local_reuse.py` (5) · `test_type_cast.py` (4) · `test_statement_order.py` (4) · `test_pointer_alias.py` (2) · `test_return_tail_call.py` (2) · `test_string_data_field.py` (1). Total preserves **98 test functions / 321 collected cases**.

> **Deviation from spec:** the spec's sequencing described an incremental in-package `_legacy.py` carve-out as a safe *manual* approach, and listed `pointer_cast`/`type_compat` as separate modules. This plan supersedes both: it uses the validated deterministic generator (atomic, proven) and merges `pointer_cast`+`type_compat` into `type_cast.py` (they are directly coupled). End state and public contract are exactly as the spec requires.

---

## Task 1: Pre-flight — confirm baseline and tool

**Files:** none modified.

- [ ] **Step 1: Confirm worktree + pin**

```bash
cd /Users/mike/code/melee-tc-refactor/tools/melee-agent
export PYTHONPATH=/Users/mike/code/melee-tc-refactor/tools/melee-agent
python -c "import src; assert 'melee-tc-refactor' in src.__file__, src.__file__; print('OK', src.__file__)"
```
Expected: `OK /Users/mike/code/melee-tc-refactor/tools/melee-agent/src/__init__.py`

- [ ] **Step 2: Baseline target suite (the safety net)**

```bash
python -m pytest tests/search/directed/test_transform_corpus.py -o addopts="" -p no:cacheprovider -q
```
Expected: `321 passed`

- [ ] **Step 3: Confirm the tool and its assignment**

```bash
python dev/tc_split.py check
python dev/tc_split.py summary
python dev/tc_split.py test-summary
```
Expected: `OK: 300 symbols each assigned to exactly one module`; summary lists 16 source modules; test-summary lists 14 test files summing to 110 symbols (98 tests + 12 helpers).

- [ ] **Step 4: Record the 3 known pre-existing failures (so later "no new failures" is meaningful)**

```bash
python -m pytest tests/search/directed/test_run_source_shape.py tests/search/test_structure.py -o addopts="" -p no:cacheprovider -q 2>&1 | tail -5
```
Expected: exactly the 3 failures listed in Critical Context #4. No commit in this task.

---

## Task 2: Generate the source package

**Files:**
- Delete: `src/search/directed/transform_corpus.py`
- Create: `src/search/directed/transform_corpus/__init__.py` + 16 modules

- [ ] **Step 1: Generate**

```bash
cd /Users/mike/code/melee-tc-refactor/tools/melee-agent
export PYTHONPATH=/Users/mike/code/melee-tc-refactor/tools/melee-agent
python dev/tc_split.py build-package
```
Expected: `wrote package with 16 modules + __init__.py; removed src/search/directed/transform_corpus.py`

- [ ] **Step 2: F821 gate (the CI check)**

```bash
python -m ruff check src/search/directed/transform_corpus/ --select F821
```
Expected: `All checks passed!`

- [ ] **Step 3: All 16 modules import**

```bash
python -c "
import importlib
for m in ['models','common','registry','orchestrator','contract_signature','register_steering','float_literal','pointer_alias','string_data_field','return_tail_call','struct_field_access','helper_extract','local_reuse','pragma_codegen','type_cast','statement_order']:
    importlib.import_module(f'src.search.directed.transform_corpus.{m}')
print('all 16 modules import OK')"
```
Expected: `all 16 modules import OK`

- [ ] **Step 4: Existing (still-monolithic) test file passes against the new package**

The test file is unchanged in this task and imports only the public API, so it validates the package:
```bash
python -m pytest tests/search/directed/test_transform_corpus.py -o addopts="" -p no:cacheprovider -q
```
Expected: `321 passed`

- [ ] **Step 5: Public-API equivalence + downstream importers**

```bash
python -c "
from src.search.directed.transform_corpus import DEFAULT_TRANSFORM_FAMILIES as F
from src.search.directed.transform_corpus import registry as R
assert len(R._FAMILY_IDS_BY_MUTATOR) > 0, 'EMPTY _FAMILY_IDS_BY_MUTATOR — the bare module-level loop landed in the wrong module (see caveat)'
print(len(F), 'families;', len(R._FAMILY_IDS_BY_MUTATOR), 'mutator->family entries;', [x.family_id for x in F][:3], '...')"
python -m pytest tests/test_transform_corpus_cli.py tests/test_source_transform_catalog.py tests/search/directed/test_transform_probe_adapter.py -o addopts="" -p no:cacheprovider -q
```
Expected: `36 families; 57 mutator->family entries; [...]`; downstream tests all pass.

- [ ] **Step 6: Commit (specific paths only)**

```bash
git add src/search/directed/transform_corpus/ src/search/directed/transform_corpus.py
git commit -m "refactor: split transform_corpus.py into a package (source)"
```
(`git add` of the deleted monolith path stages its deletion.) Confirm `git status` shows `dev/` still untracked and nothing else stray.

---

## Task 3: Mirror the test file into a test package

**Files:**
- Delete: `tests/search/directed/test_transform_corpus.py`
- Create: `tests/search/directed/transform_corpus/__init__.py` + 14 `test_*.py`

- [ ] **Step 1: Generate**

```bash
cd /Users/mike/code/melee-tc-refactor/tools/melee-agent
export PYTHONPATH=/Users/mike/code/melee-tc-refactor/tools/melee-agent
python dev/tc_split.py build-tests
```
Expected: `wrote 14 test files; removed tests/search/directed/test_transform_corpus.py`

- [ ] **Step 2: F821 on the test package**

```bash
python -m ruff check tests/search/directed/transform_corpus/ --select F821
```
Expected: `All checks passed!`

- [ ] **Step 3: Full count preserved (no test dropped)**

```bash
python -m pytest tests/search/directed/transform_corpus/ -o addopts="" -p no:cacheprovider -q
```
Expected: `321 passed` (identical count to baseline — proves no test was lost or duplicated).

- [ ] **Step 4: Commit (specific paths only)**

```bash
git add tests/search/directed/transform_corpus/ tests/search/directed/test_transform_corpus.py
git commit -m "refactor: mirror transform_corpus tests into a package"
```

---

## Task 4: Finalize — full verification and scaffold cleanup

**Files:**
- Delete: `tools/melee-agent/dev/` (the scaffold)
- Modify: `docs/superpowers/specs/2026-06-14-transform-corpus-refactor-design.md` (status → Implemented)

- [ ] **Step 1: Full directed-search + downstream suite — confirm NO NEW failures**

```bash
cd /Users/mike/code/melee-tc-refactor/tools/melee-agent
export PYTHONPATH=/Users/mike/code/melee-tc-refactor/tools/melee-agent
python -m pytest tests/search/ tests/test_transform_corpus_cli.py tests/test_source_transform_catalog.py -o addopts="" -p no:cacheprovider -q 2>&1 | tail -6
```
Expected: `3 failed, 958 passed, 3 skipped` — and the 3 failed are EXACTLY the pre-existing ones from Critical Context #4. If any OTHER test fails, stop and investigate.

- [ ] **Step 2: F821 over the whole refactored surface**

```bash
python -m ruff check src/search/directed/transform_corpus/ tests/search/directed/transform_corpus/ --select F821
```
Expected: `All checks passed!`

- [ ] **Step 3: Remove the scaffold**

```bash
rm -rf /Users/mike/code/melee-tc-refactor/tools/melee-agent/dev
```

- [ ] **Step 4: Mark the spec implemented**

Edit `docs/superpowers/specs/2026-06-14-transform-corpus-refactor-design.md`: change the `Status:` line to `Implemented (refactor/transform-corpus-package)`.

- [ ] **Step 5: Commit (run from the worktree ROOT — `docs/` is at the repo root, NOT under `tools/melee-agent`, so a `git add docs/...` from the `tools/melee-agent` cwd of earlier steps would fail with "pathspec does not exist")**

```bash
cd /Users/mike/code/melee-tc-refactor
git add docs/superpowers/specs/2026-06-14-transform-corpus-refactor-design.md
git commit -m "docs: mark transform_corpus split implemented"
git status --short   # expect: clean (no untracked dev/, no stray files)
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** package conversion (Task 2) ✓; `__init__` re-export shim ✓ (generated by tool, validated: downstream importers + family-id equivalence pass); per-family modules ✓ (16, validated); shared `common.py` ✓; test mirror (Task 3) ✓; verification recipe with PYTHONPATH pin ✓; equivalence guard ✓ (family-id snapshot + 321-case suite). Spec deviations (atomic generator vs `_legacy`; `type_cast` merge) documented above.
- **Placeholder scan:** none — every step has exact commands and expected output, all run during planning.
- **Consistency:** module names match between the File Structure table, the tool's assignment, and the import DAG; test counts sum to 98 functions / 321 cases; the same 3 pre-existing failures are referenced in Tasks 1 and 4.
- **Proven:** the full source+test generation was dry-run in the worktree (then reverted): F821 clean, 321 split-tests pass, downstream green, only the 3 pre-existing failures remain.
