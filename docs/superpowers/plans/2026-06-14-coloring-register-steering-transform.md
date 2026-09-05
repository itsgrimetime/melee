# Coloring Register-Steering Transform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a named executable transform-corpus family for mndiagram register-coloring/source-steering residuals.

**Architecture:** Keep existing guarded source analyzers and mutators as the safety boundary. Add a new family plus alias mutator keys so mndiagram force-phys runs emit distinguishable `coloring_register_steering` probes while reusing proven exact source edits.

**Tech Stack:** Python 3.11, Typer/Rich CLI, pytest, existing `src.search.directed` transform-corpus modules.

---

### Task 1: Red Tests

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`

- [ ] Add a metadata test asserting `coloring_register_steering` exists, has concrete alias mutator keys, has non-empty risk/effect fields, and is present in catalog docs.
- [ ] Add a planner test:

```python
def test_plan_transform_experiments_names_mndiagram_coloring_cluster() -> None:
    plan = plan_transform_experiments(
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={58: 4, 35: 29},
    )
    assert {cluster.cluster_id for cluster in plan.clusters} == {
        "mndiagram_coloring_register_steering"
    }
    cluster = plan.clusters[0]
    assert cluster.target_assignments == ("ig35->r29", "ig58->r4")
    assert cluster.family_ids == ("coloring_register_steering",)
    assert [family.family_id for family in plan.families] == [
        "coloring_register_steering"
    ]
```

- [ ] Add a negative planner test showing a non-mndiagram function with force-phys still uses `generic_allocator_shape`.
- [ ] Add a probe-generation test with a source fixture containing adjacent local declarations, an initialized declaration, and a repeated loop counter, then assert `steer_reorder_local_decls`, `steer_split_decl_init`, and `steer_reuse_loop_counter_scope` are all emitted under the default `max_per_family=3` cap.
- [ ] Add rejection tests proving steering-only declaration anchors reject qualified locals, `static` locals, non-loop `s16`/`s32` locals, duplicate exact declaration lines, and preprocessor-bearing target bodies.
- [ ] Add alias mutator tests that compare each alias key to the underlying guarded mutator on a valid anchor and assert stale anchors return `None`.
- [ ] Add an adapter de-dupe test proving that when a `coloring_register_steering` probe and base-family probe share `candidate_text`, `adapted_transform_lifetime_probes()` keeps the first steering probe.
- [ ] Add a CLI dry-compiler smoke by adapting `test_search_run_directed_force_phys_emits_transform_corpus_candidate`: use `function="mnDiagram2_Create"` and a source fixture with adjacent local declarations, then assert the telemetry includes `applied_mutator` starting with `transform-corpus:coloring_register_steering`.
- [ ] Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q -k 'coloring_register_steering or directed_force_phys_emits_transform_corpus_candidate or source_transform_catalog'
```

Expected: failures for missing family, alias keys, planner cluster, and CLI telemetry.

### Task 2: Family And Planner

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Test: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`

- [ ] Add `coloring_register_steering` to `DEFAULT_TRANSFORM_FAMILIES` with alias mutator keys:

```python
("steer_reorder_local_decls", "steer_split_decl_init",
 "steer_reuse_loop_counter_scope", "steer_change_counter_width",
 "steer_reuse_same_type_local_lifetime")
```

- [ ] Add a helper that identifies mndiagram coloring targets:

```python
def _is_mndiagram_coloring_target(function: str, unit: str, force_phys: Mapping[int, int]) -> bool:
    if not force_phys:
        return False
    if function in _MNDIAGRAM_COLORING_TARGETS:
        return True
    return function.startswith("mnDiagram") and "/mn/" in f"/{unit}/"
```

- [ ] Update `plan_transform_experiments()` so matching targets return a single `mndiagram_coloring_register_steering` cluster before the generic fallback.
- [ ] Run the planner tests from Task 1 and verify they pass while existing `ftCo_8009E7B4` cluster tests still pass.

### Task 3: Alias Mutators And Probe Materialization

**Files:**
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Test: `tools/melee-agent/tests/search/directed/test_mutators.py`
- Test: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`

- [ ] In `mutators.py`, register each `steer_*` key as the existing guarded implementation:

```python
"steer_reorder_local_decls": _reorder_local_decls,
"steer_split_decl_init": _split_decl_init,
"steer_reuse_loop_counter_scope": _reuse_loop_counter_scope,
"steer_change_counter_width": _change_counter_width,
"steer_reuse_same_type_local_lifetime": _reuse_same_type_local_lifetime,
```

- [ ] In `transform_corpus.py`, add a base-to-alias mapping:

```python
_REGISTER_STEERING_ALIASES = {
    "reorder_local_decls": "steer_reorder_local_decls",
    "split_decl_init": "steer_split_decl_init",
    "reuse_loop_counter_scope": "steer_reuse_loop_counter_scope",
    "change_counter_width": "steer_change_counter_width",
    "reuse_same_type_local_lifetime": "steer_reuse_same_type_local_lifetime",
}
```

- [ ] Add target-body steering anchor enumeration for source keys that are not produced by `iter_source_shape_anchors()`:

```python
def _iter_register_steering_body_anchors(body_text: str) -> Iterable[Anchor]:
    if the target body contains a preprocessor directive, yield nothing
    collect unique top-level unqualified local declarations
    collect reorder anchors only for uninitialized adjacent declarations
    collect split anchors only for initialized unqualified locals
    collect counter-width anchors only when the next non-empty line is for (var = ...)
    yield anchors round-robin by category
```

Use the same payload contracts as `resolve_anchor()`: `first_line`/`second_line`, `decl_line`/`var`/`type`/`init`, and `decl_line`/`from`/`to`.
- [ ] Add a small helper that, when `coloring_register_steering` is allowed and a source anchor key appears in the mapping, applies the alias mutator and appends a `coloring_register_steering` probe with the alias key.
- [ ] Call that helper for steering-only anchors and in both existing target-body and full-source anchor loops before regular family append logic so the steering probe is first and survives adapter text de-duplication.
- [ ] Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  -q -k 'coloring_register_steering or alias'
```

Expected: pass.

### Task 4: Catalog And CLI Smoke

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [ ] Add the alias mutator keys to `DIRECTED_MUTATOR_KEYS` and update headline/concrete counts if the tests require exact counts.
- [ ] Update the source-transform catalog docs with one row for `coloring_register_steering`, listing the five alias keys and the expected register-coloring effect.
- [ ] Add or update CLI smoke assertions so a dry `search run --directed-force-phys` fixture produces `transform-corpus:coloring_register_steering`.
- [ ] Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q -k 'coloring_register_steering or directed_force_phys_emits_transform_corpus_candidate or source_transform_catalog'
```

Expected: pass.

### Task 5: Verification And Resolution

**Files:**
- Review all changed files.

- [ ] Run focused transform-corpus, mutator, CLI, and catalog tests.
- [ ] Run the broader directed-search smoke set that has caught prior transform-corpus regressions:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_mutators.py \
  tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q
```

- [ ] Run:

```bash
PYTHONPATH=tools/melee-agent python -m compileall -q \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py
git diff --check
```

- [ ] Run command-level smoke checks:

```bash
PYTHONPATH=tools/melee-agent melee-agent debug search plan-transforms \
  --function mnDiagram2_Create --unit melee/mn/mndiagram2 \
  --directed-force-phys 0:58:4,0:35:29 --json
```

- [ ] Request independent Codex review of the implementation. Fix any blockers.
- [ ] Commit the feature with the spec/plan/docs, refresh the editable install, run installed CLI smoke, resolve #698, and resolve or explicitly leave #699 open depending on whether an actual byte-match candidate was verified.
