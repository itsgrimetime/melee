# Cross-Parent Role Bindings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provenance-bound v2 color-target schema that resolves reviewed cross-parent role ambiguities and propagates those bindings only to structurally identical candidate namespaces.

**Architecture:** Keep v1 semantic reanchoring unchanged. V2 loads two strict parent bindings, validates them against the exact retained source and pcdump bytes, and records them in immutable objective provenance. Candidate evaluation reuses a binding only for a parent artifact or an exact versioned structural-namespace witness; all other cases use ordinary semantic reanchoring and remain fail-closed on ambiguity.

**Tech Stack:** Python 3, dataclasses, PyYAML, SHA-256, existing role descriptors/reanchoring, colorgraph profiles, pytest, Typer/Rich CLI goldens.

## Global Constraints

- Continue accepting `delta-minimize-color-target.v1` exactly as today.
- Do not change generic `role_cost()` or make raw IG equality identity evidence.
- V2 binds both parent maps to exact retained source and pcdump SHA-256 hashes.
- V2 maps are total for `force_phys`, injective, and baseline-side identity maps.
- A reviewed mapping may choose only a viable minimum-cost semantic candidate for its canonical baseline role.
- A hybrid inherits a parent binding only when its versioned structural namespace witness matches exactly.
- Structural witnesses exclude assigned physical registers, interference edges, spills, and live ranges.
- Any viable candidate without a proven role map prevents exact frontier publication.
- Malformed or tampered v2 evidence fails closed and is never reinterpreted as v1.
- Objective and candidate cache semantics must be version-bumped so pre-v2 evidence is not reused.

---

### Task 1: Strict v2 schema and retained-parent binding validation

**Files:**
- Modify: `tools/melee-agent/src/search/delta_minimize/objectives.py`
- Test: `tools/melee-agent/tests/search/delta_minimize/test_objectives.py`

**Interfaces:**
- Extend `LoadedColorTarget` with `schema_version: str`, `baseline_side: str | None`, and `parent_role_bindings: Mapping[str, ParentRoleBinding]`.
- Add frozen `ParentRoleBinding(source_sha256: str, pcdump_sha256: str, canonical_to_parent: Mapping[int, int])`.
- Add `COLOR_TARGET_SCHEMA_V2 = "delta-minimize-color-target.v2"` and `ROLE_NAMESPACE_SCHEMA = "delta-minimize-role-namespace.v1"`.
- Add `_reviewed_parent_reanchor(target_spec, parent, binding) -> role_reanchor.ReanchorResult`.
- Preserve the public signatures of `load_color_target()` and `infer_objective_manifest()`.

- [ ] **Step 1: Add failing strict-schema tests**

Add tests that construct a v2 YAML with both sides and assert:

```python
loaded = load_color_target(target_path, function="fn")
assert loaded.schema_version == "delta-minimize-color-target.v2"
assert loaded.baseline_side == "left"
assert dict(loaded.parent_role_bindings["right"].canonical_to_parent) == {64: 64, 78: 78}
```

Parametrize rejection of missing/extra fields, missing side, non-lowercase or
non-64-character hashes, partial or extra canonical keys, duplicate mapped IGs,
non-identity baseline mapping, and baseline dump bytes whose hash differs from
the baseline-side `pcdump_sha256`. Keep a v1 compatibility test unchanged.

- [ ] **Step 2: Verify RED**

Run:

```bash
cd tools/melee-agent
python -m pytest --no-cov -q \
  tests/search/delta_minimize/test_objectives.py \
  -k 'v2 or parent_role_binding'
```

Expected: FAIL because v2 is unsupported and `ParentRoleBinding` is absent.

- [ ] **Step 3: Implement the strict loader**

Use exact field sets:

```python
_TARGET_V2_FIELDS = frozenset({
    "schema_version", "function", "class_id", "baseline_side",
    "baseline_dump", "force_phys", "coalesce_preservation",
    "parent_role_bindings",
})
_PARENT_BINDING_FIELDS = frozenset({
    "source_sha256", "pcdump_sha256", "canonical_to_parent",
})
```

Parse integer map keys with the existing canonical decimal rules. Require the
two exact sides, exact canonical keys, unique destinations, valid SHA-256 text,
and identity on `baseline_side`. Hash `baseline_dump` bytes and compare them to
the bound side before returning. V1 returns empty bindings and no baseline side.

- [ ] **Step 4: Add failing retained-parent validation tests**

Build the duplicate-role fixture so ordinary `_require_complete_reanchor()`
returns `ambiguous-color-target`. Supply a v2 binding and assert inference uses
the reviewed `64 -> 64`, `78 -> 78` mappings. Add failures for source hash,
pcdump hash, absent mapped IG, wrong class, non-minimum semantic match, and a
mapping collision with the full profile role map. Assert automatic derivation
and v1 remain ambiguous on the duplicate fixture.

- [ ] **Step 5: Verify RED, then implement parent validation**

Run the new tests and confirm they fail at the existing semantic reanchor.
Implement `_reviewed_parent_reanchor()` so it:

```python
return role_reanchor.ReanchorResult(
    class_id=target.class_id,
    force_phys={parent_ig: target.force_phys[canonical]
                for canonical, parent_ig in binding.canonical_to_parent.items()},
    diagnostics={},
    matched={parent_ig: canonical
             for canonical, parent_ig in binding.canonical_to_parent.items()},
)
```

Before constructing the result, verify exact source/dump hashes, existing
descriptors, one-to-one maps, and that each selected descriptor has the minimum
`role_matcher.role_cost()` among viable parent descriptors for the canonical
baseline descriptor. Use reviewed reanchors for v2 parent target checks and
overlay their raw-IG-to-canonical entries onto conflict-free full profile maps.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
cd tools/melee-agent
python -m pytest --no-cov -q tests/search/delta_minimize/test_objectives.py
python -m ruff check src/search/delta_minimize/objectives.py \
  tests/search/delta_minimize/test_objectives.py
```

Expected: all tests and lint pass.

Commit: `feat: bind reviewed parent allocator roles`

---

### Task 2: Persist v2 provenance and propagate exact namespace bindings

**Files:**
- Modify: `tools/melee-agent/src/search/delta_minimize/objectives.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/evaluator.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/run.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/store.py`
- Test: `tools/melee-agent/tests/search/delta_minimize/test_evaluator.py`
- Test: `tools/melee-agent/tests/search/delta_minimize/test_run.py`
- Test: `tools/melee-agent/tests/search/delta_minimize/test_store.py`

**Interfaces:**
- Add `_structural_namespace_witness(compile, class_id) -> Mapping[str, Any] | None` in `objectives.py` and import it in `evaluator.py`.
- Extend explicit v2 target provenance with `schema_version`, `baseline_side`, `baseline_dump`, `baseline_dump_sha256`, `parent_role_bindings`, and `namespace_schema`.
- Bump `OBJECTIVE_MANIFEST_SCHEMA` and `OBJECTIVE_INPUTS_SCHEMA` by one version.
- Bump the candidate evidence/parser semantic version used in cache keys.
- Keep result and CLI schemas unchanged unless a test proves a serialized field is required there.

- [ ] **Step 1: Add failing objective round-trip and tamper tests**

Assert a v2 objective round-trips through `_objective_from_dict()` with both
bindings and the witness schema in provenance. Parametrize tampering of either
hash, either role map, baseline side, namespace schema, and an added/removed
field. Assert each fails with `corrupt-objective-manifest`. Assert changing any
binding changes the content-addressed target/objective epoch.

- [ ] **Step 2: Verify RED, then implement immutable provenance**

Run:

```bash
cd tools/melee-agent
python -m pytest --no-cov -q tests/search/delta_minimize/test_run.py \
  tests/search/delta_minimize/test_store.py -k 'binding or provenance or cache'
```

Expected: FAIL because current provenance validation accepts only v1 shapes.
Serialize mappings with canonical decimal string keys and strict side ordering.
Update `_validate_target_provenance()` and donor-context validation to recognize
exact v2 provenance, while retaining both existing v1 provenance shapes.

- [ ] **Step 3: Add failing structural-witness tests**

Create compiles where only assigned registers, interference edges, spill state,
or live ranges differ and assert the witness stays equal. Create separate cases
where virtual count, normalized per-IG def/use identity, decision/simplify
traversal, coalesce mappings, or forced overrides differ and assert inequality
or `None`. Assert the witness payload begins with:

```python
{"schema_version": "delta-minimize-role-namespace.v1", "class_id": 0}
```

- [ ] **Step 4: Verify RED, then implement the witness**

Build the witness from the final valid colorgraph/simplify/coalesce sections and
`role_descriptor.build_descriptors()`. Normalize every tuple/list to immutable,
deterministic JSON-compatible values. Do not include assigned registers,
interference, spill flags, or live ranges.

- [ ] **Step 5: Add failing candidate propagation tests**

Cover these cases in `test_evaluator.py`:

1. A candidate pcdump hash equal to a reviewed parent consumes that binding.
2. A hybrid with an equal structural witness inherits that parent's map even
   when duplicate semantic roles make ordinary reanchor ambiguous.
3. If both parent witnesses match, their canonical mappings must agree.
4. A changed witness falls back to ordinary reanchor.
5. Ambiguous fallback makes the viable candidate incomplete and blocks exact
   frontier publication.
6. A hash match with changed source evidence does not reuse a binding.

- [ ] **Step 6: Verify RED, then implement candidate propagation**

In `_color_axis()`, extract and validate v2 provenance. Prefer an exact
source+pcdump-bound parent map, then an exactly matching parent namespace
witness. Convert canonical-to-parent maps to raw-IG-to-canonical maps. Overlay
only conflict-free mappings on the existing donor/candidate graph maps. If no
binding is proven, retain the current semantic reanchor path unchanged. Never
use raw IG equality by itself.

- [ ] **Step 7: Bump cache semantics and verify GREEN**

Update objective/input/evidence semantic versions and cache tests so older
payloads are rejected rather than migrated. Run:

```bash
cd tools/melee-agent
python -m pytest --no-cov -q \
  tests/search/delta_minimize/test_evaluator.py \
  tests/search/delta_minimize/test_run.py \
  tests/search/delta_minimize/test_store.py
python -m ruff check \
  src/search/delta_minimize/objectives.py \
  src/search/delta_minimize/evaluator.py \
  src/search/delta_minimize/run.py \
  src/search/delta_minimize/store.py \
  tests/search/delta_minimize/test_evaluator.py \
  tests/search/delta_minimize/test_run.py \
  tests/search/delta_minimize/test_store.py
```

Expected: all tests and lint pass.

Commit: `feat: propagate proven allocator namespaces`

---

### Task 3: Integration, documentation, and real-case acceptance

**Files:**
- Modify: `tools/melee-agent/tests/search/delta_minimize/test_integration.py`
- Modify: `tools/melee-agent/tests/search/delta_minimize/test_cli.py`
- Modify: `tools/melee-agent/tests/golden/debug_cli_help/debug__search__delta-minimize.txt`
- Modify: `docs/superpowers/specs/2026-07-11-two-frontier-delta-minimizer-design.md`
- Modify: `docs/superpowers/plans/2026-07-11-two-frontier-delta-minimizer.md`
- Modify: the closest existing delta-minimize user documentation discovered by `rg -n "delta-minimize" docs tools/melee-agent/README*`

**Interfaces:**
- CLI remains `--target PATH`; no new option is added.
- Help explicitly names v1 semantic reanchoring and v2 reviewed cross-parent bindings.
- Integration fixture contains two descriptor-identical role pairs and exact parent hashes.

- [ ] **Step 1: Add the failing integration case**

Extend the hermetic integration fixture so v1 fails with
`ambiguous-color-target` and v2 enumerates all legal masks with complete
four-axis evidence. Assert both endpoints are byte-exact, every viable mask is
complete, and the exact frontier is published reproducibly.

- [ ] **Step 2: Verify RED, implement only integration wiring, and update help**

Run:

```bash
cd tools/melee-agent
python -m pytest --no-cov -q \
  tests/search/delta_minimize/test_integration.py \
  tests/search/delta_minimize/test_cli.py
```

Expected before wiring/docs: the v2 integration or help golden fails. Keep CLI
parsing unchanged; update help text and golden output only.

- [ ] **Step 3: Update design and operator documentation**

Amend the original v1 schema section with the v2 YAML and exact fail-closed
rules from the approved issue #1238 spec. Update Section 15.3 so the retained
acceptance command uses the reviewed v2 target and requires every viable mask
to have a proven mapping. Do not rewrite unrelated design history.

- [ ] **Step 4: Run focused and adjacent suites**

Run:

```bash
cd tools/melee-agent
python -m pytest --no-cov -q \
  tests/search/delta_minimize \
  tests/test_opcode_graph.py \
  tests/test_colorgraph_profile.py \
  tests/test_objobject_profile.py \
  tests/test_stack_home_profile.py \
  tests/test_delta_score_source_evidence.py \
  tests/test_mwcc_debug_inspect_parser.py
python -m ruff check src/search/delta_minimize tests/search/delta_minimize
```

Expected: all focused tests and lint pass.

- [ ] **Step 5: Run the retained real case**

Create an untracked v2 target using the four retained hashes from the approved
spec and reviewed identity maps for IGs 64 and 78. Run the branch-local CLI on
the frozen wrapper/direct sources with `--max-candidates 64`. Expected: exit 0,
status `matched`, `joint-zero`, or `frontier`, all viable masks complete, and no
`ambiguous-color-target`. Preserve the result under an ignored build directory;
do not commit retained source or pcdump artifacts.

- [ ] **Step 6: Verify repository build and commit**

Run from repository root:

```bash
python configure.py && ninja
git diff --check
```

Expected: build succeeds and diff check is clean.

Commit: `test: prove cross-parent delta role bindings`
