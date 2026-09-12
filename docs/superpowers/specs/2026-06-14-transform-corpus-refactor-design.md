# Design: Split `transform_corpus.py` into a `transform_corpus/` package

- **Date:** 2026-06-14
- **Status:** Implemented; landed on master 2026-06-15 (regenerated against current master to fold in 4 families added since the design base: parameter_area, fp_reassoc, named_zero_local, ranked_cursor_iv)
- **Worktree/branch:** `refactor/tc-split-relanded` (regenerated off current master); original review branch `refactor/transform-corpus-package`
- **Author:** decomp tooling session

## Problem

`tools/melee-agent/src/search/directed/transform_corpus.py` is 6756 lines
(241 KB) at the `2b6aa3d12` base. It holds 218 top-level functions, 21 classes,
and 61 module-level constants, with 29 anchor/probe "entry-point" generators
(31 `_iter_*` helpers in total). `DEFAULT_TRANSFORM_FAMILIES` registers 36
transform-family metadata entries; the generators that implement the families
with concrete mutators cluster into ~13 source-transform concerns. A single
file this size is hard for
both humans and agents to reason about and edit safely: unrelated families sit
adjacent, helper ownership is unclear, and any change forces the reader to hold
the whole file in context. This is the actively-developed area of directed
search, so the cost compounds.

## Goals

- Split the module into a flat `transform_corpus/` **package** of focused,
  single-concern modules.
- Preserve **100% of observable behavior** — this is a pure mechanical,
  byte-faithful relocation of code. No logic edits, no public renames, no
  opportunistic cleanups.
- Keep every existing import site and string module-path reference working with
  **zero edits outside the package** (and the mirrored tests).
- Split the equally-unwieldy 6109-line test file (98 test functions, 321
  collected cases) to mirror the new layout.

## Non-Goals (Out of Scope)

- Any behavior/logic change or bug fix.
- Renaming public symbols or changing function signatures.
- Further decomposing `register_steering` (kept as one coherent module).
- Touching unrelated modules, the mutator/anchor infrastructure, or the CLI.
- Changing the pytest/coverage configuration.

## Decisive Finding: the external contract is tiny

The complete surface that anything outside the file depends on:

| Symbol | Imported by |
|---|---|
| `DEFAULT_TRANSFORM_FAMILIES` | `transform_probe_adapter.py`, `source_transform_catalog.py`, tests |
| `generate_transform_probes` | `cli/debug/__init__.py`, `search/cli/__init__.py`, `run.py`, tests |
| `plan_transform_experiments` | `search/cli/__init__.py`, tests |
| `TransformProbe` | `transform_probe_adapter.py` (production code; **not** the tests) |
| `TransformFamily` / `TransformCluster` / `TransformExperimentPlan` | no current external importer — re-exported for API completeness |

The tests import only the first three (`DEFAULT_TRANSFORM_FAMILIES`,
`generate_transform_probes`, `plan_transform_experiments`).

Plus one **string** reference to the module path in
`source_transform_catalog.py:389`: `implementation="src.search.directed.transform_corpus"`
— a descriptive `str` field that is never imported/`importlib`'d, so it has no
behavioral dependency; it stays accurate because the package import path equals
the old module path.

The test suite (`tests/search/directed/test_transform_corpus.py`, 6109 lines, 98
test functions / 321 collected cases) reaches **only** the public API — no
private helper is imported anywhere outside the file.

**Consequence:** converting the `.py` file into a `transform_corpus/` package
directory whose `__init__.py` re-exports those public symbols keeps every
`from src.search.directed.transform_corpus import ...` statement, the
`from ...search.directed import transform_corpus` + attribute-access pattern, and
the module-path string all working unchanged. The package import path is
identical to the old module import path.

## Target Architecture

Flat package mirroring the existing flat layout of `src/search/directed/`
(`anchors.py`, `mutators.py`, `scorer.py`, ...). Approximate LOC in parentheses.

```
src/search/directed/transform_corpus/
  __init__.py            # re-export shim ONLY: public API symbols
  models.py              # the 4 public dataclasses: TransformFamily, TransformCluster,
                         #   TransformExperimentPlan, TransformProbe
  registry.py     (~620) # DEFAULT_TRANSFORM_FAMILIES, _FAMILY_BY_ID,
                         #   _FAMILY_IDS_BY_MUTATOR, plan_transform_experiments + plan helpers
  common.py       (~560) # ~49 helpers used by >=2 families: text/line records, brace
                         #   depths, literal/comment/preprocessor blanking, span utils,
                         #   type/signature normalization, simple struct layout
  orchestrator.py (~400) # generate_transform_probes, _iter_full_source_anchors,
                         #   _iter_target_function_anchors, _family_ids_for_anchor,
                         #   _region_for_family, _requested_family_ids, append_* logic
  register_steering.py   (~1370)  # 9 iterators: decl window-rotation/demote, dead/reused
                         #   loop-counter, byte-local widen, FPR dependent product,
                         #   node-set-delta steering, concrete + register-steering body
  float_literal.py       (~240)
  pointer_alias.py       (~45)
  struct_field_access.py (~485)   # raw-index struct field, raw pointer offset, data-table
  contract_signature.py  (~600)   # unused trailing parameter contract editing
  type_compat.py         (~640)   # vector alias type, type-cast compatibility
  helper_extract.py      (~290)   # helper inline / extract / shape
  local_reuse.py         (~205)
  statement_order.py     (~165)
  pragma_codegen.py      (~120)
  pointer_cast.py        (~210)
  return_tail_call.py    (~60)
  string_data_field.py   (~52)
```

### Import DAG (acyclic by construction)

```
models   <-  common  <-  family modules  <-  orchestrator
registry (imports models)            <-  orchestrator
__init__ imports from registry, models, orchestrator
```

- `models.py` imports nothing internal.
- `common.py` imports only `models` (if needed) + stdlib/external.
- Each family module imports `common`, `models`, and external deps it uses
  — directly, where used. Each module's external-import set is derived from AST
  usage, not hand-listed. The current top-of-file external imports are:
  `Anchor` + `iter_source_shape_anchors` (from `anchors`); `apply_mutator`
  (from `mutators`); `SchedulerOrderTarget` + `iter_scheduler_order_source_anchors`
  + `parse_scheduler_order_target` (from `mwcc_debug.scheduler_order_realizer`);
  and `find_function` + `find_function_definitions` (from `mwcc_debug.source_patch`).
- `orchestrator.py` imports `models`, `registry`, `common`, and every family
  module (it is the single place that fans out to the iterators).
- `__init__.py` imports the public names and lists them in `__all__`.

No family module imports another family module or the orchestrator; no family
imports `registry`. This guarantees no import cycles.

## Symbol-Assignment Rule (deterministic)

Every top-level symbol moves to exactly one module by this rule, applied in
order:

1. The 4 public dataclasses → `models.py`. The `_Contract*` dataclasses are used
   only by the contract family, so they are co-located in
   `contract_signature.py` (not `models.py`).
2. `DEFAULT_TRANSFORM_FAMILIES`, the `_FAMILY_*` lookups, and
   `plan_transform_experiments` + helpers used only by planning → `registry.py`.
3. `generate_transform_probes` + the two top-level `_iter_*_source/target_*`
   fan-out generators + dispatch helpers → `orchestrator.py`.
4. A symbol reachable from exactly one family's entry points → that family
   module.
5. A symbol reachable from two or more family modules → `common.py`.

The AST reachability analysis used to derive the family clusters and the
shared-helper set is reproducible (walk each `_iter_*` entry point's call
closure over top-level names). All counts and LOC figures in this spec are
snapshots at `2b6aa3d12` and are approximate; because the file is actively
edited on master (see Risk e), the plan regenerates the exact per-module
assignment list **and** all counts from the file as-is at implementation time.

## Public API preservation (`__init__.py`)

```python
"""Source-transform corpus and bounded probe planner for directed search."""
from src.search.directed.transform_corpus.models import (
    TransformFamily, TransformCluster, TransformExperimentPlan, TransformProbe,
)
from src.search.directed.transform_corpus.registry import (
    DEFAULT_TRANSFORM_FAMILIES, plan_transform_experiments,
)
from src.search.directed.transform_corpus.orchestrator import (
    generate_transform_probes,
)

__all__ = [
    "TransformFamily", "TransformCluster", "TransformExperimentPlan",
    "TransformProbe", "DEFAULT_TRANSFORM_FAMILIES",
    "plan_transform_experiments", "generate_transform_probes",
]
```

## Test split

`tests/search/directed/test_transform_corpus.py` (97 flat, family-prefixed test
functions) → a `tests/search/directed/transform_corpus/` package mirroring the
modules:

```
tests/search/directed/transform_corpus/
  __init__.py
  test_registry.py          # family metadata + plan_transform_experiments tests
  test_orchestrator.py      # end-to-end generate_transform_probes behavior
  test_register_steering.py # test_coloring_register_steering_*, test_node_set_delta_*
  test_contract_signature.py# test_unused_trailing_parameter_* / contract tests
  test_float_literal.py  test_pointer_cast.py  test_statement_order.py
  test_helper_extract.py test_local_reuse.py   test_struct_field_access.py
  ... (mirror remaining families)
```

Test imports are unchanged — every test still imports the public API from
`src.search.directed.transform_corpus`. Tests are partitioned by their existing
name prefix; no test body is edited. Any test that spans multiple families
(e.g. metadata sweeps) lands in `test_registry.py`.

## Verification strategy

The 98-test-function suite (321 collected cases) is the safety net. Because the
editable install pins the **main checkout** onto `sys.path` (see Risks), all
verification MUST pin the worktree:

```bash
cd /Users/mike/code/melee-tc-refactor/tools/melee-agent
export PYTHONPATH=/Users/mike/code/melee-tc-refactor/tools/melee-agent
# 0. Assert we are testing the worktree, not the main checkout:
python -c "import src; assert 'melee-tc-refactor' in src.__file__, src.__file__; print('OK', src.__file__)"
# 1. Run the suite with coverage disabled for speed:
python -m pytest tests/search/directed/ -o addopts="" -q
```

Procedure:

1. **Baseline (before any change):** record the target suite green on the
   worktree branch tip (HEAD, currently `f57db47a4`) immediately before the
   first carve-out commit. (Source and tests are byte-identical to the
   `2b6aa3d12` base, so this equals the base content; pin to the branch tip
   rather than the pre-doc commit to avoid confusion.) Expected: 321 passed.
2. **Incremental:** after each module is carved out, run the suite; a green run
   means that slice preserved behavior. Import errors immediately surface a
   miscategorized helper (Risk c).
3. **Final equivalence guards:** assert the `DEFAULT_TRANSFORM_FAMILIES` family
   ids and `generate_transform_probes` output on a representative input are
   byte-identical before vs. after (snapshot compare), in addition to the full
   suite passing.
4. Run the broader `tests/search/` + `tests/test_transform_corpus_cli.py` +
   `tests/test_source_transform_catalog.py` to confirm no downstream importer
   regressed.

## Risks & Mitigations

- **(a) Editable `.pth` dangles to the main checkout.** `_editable_impl_melee_agent.pth`
  and `_melee_decomp_agent.pth` both append `/Users/mike/code/melee/tools/melee-agent`
  to `sys.path`, so a naive `pytest` in the worktree tests the *main* checkout.
  *Mitigation:* every command prepends `PYTHONPATH=<worktree>/tools/melee-agent`
  and asserts `src.__file__` contains `melee-tc-refactor` before trusting
  results (PYTHONPATH precedes site `.pth` paths).
- **(b) Circular import.** *Mitigation:* the strict layered DAG above
  (no family imports another family/orchestrator/registry) plus incremental
  per-module test runs.
- **(c) A shared helper miscategorized as family-private (or vice-versa).**
  *Mitigation:* derive assignment from AST reachability, not by hand; a wrong
  call raises `NameError`/`ImportError` on the very next test run.
- **(d) Large diff obscures review.** *Mitigation:* the change is a pure move;
  reviewers can confirm via the green suite and the snapshot equivalence guard.
  Sequence commits per-module so each is independently green.
- **(e) Concurrent development drift.** `transform_corpus.py` is a hotspot — it
  grew by hundreds of lines on master *during the authoring of this spec* (the
  main checkout already holds further uncommitted WIP). A long-running refactor
  will collide with concurrent edits at merge time. *Mitigation:* execute the
  whole split in one focused pass on this branch; do not let it sit. At merge
  time, expect a reconciliation pass (the split is a clean move, so a merge can
  be reconstructed by re-applying concurrent hunks to the new module homes). If
  feasible, coordinate so the split lands before the next large edit to the file.

## Sequencing (high level; detailed steps in the implementation plan)

A module file and a package directory of the same name **cannot coexist**, so
there is no "thin `transform_corpus.py` shim alongside the package" — the file
becomes the package in one move. The transition uses an in-package `_legacy.py`
holding-pen so every step keeps `import src.search.directed.transform_corpus`
working and independently testable:

1. **Package shell:** move the entire current file verbatim to
   `transform_corpus/_legacy.py`; add `transform_corpus/__init__.py` that
   re-exports the public symbols from `._legacy`; delete `transform_corpus.py`.
   Verify green — this alone proves the package conversion is behavior-neutral.
2. **Carve out, one module at a time** (serially, since they share `_legacy.py`):
   `models.py`, then `common.py`, then `registry.py`, then each family module
   (smallest first to validate the pattern), updating `_legacy.py` to import the
   moved names from their new home. Verify green after each carve-out.
3. **Orchestrator + cleanup:** move `generate_transform_probes` + the fan-out
   generators + dispatch helpers into `orchestrator.py`; `_legacy.py` is now
   empty → delete it; finalize `__init__.py` re-exports + `__all__`.
4. **Test split:** mirror the test file into the test package (parallelizable —
   separate files, no shared holding-pen).
5. **Final verification:** full target suite + downstream importers
   (`tests/search/`, `test_transform_corpus_cli.py`,
   `test_source_transform_catalog.py`) + the equivalence-guard snapshot.

The end state is the package above; `transform_corpus.py` and `_legacy.py` no
longer exist.
