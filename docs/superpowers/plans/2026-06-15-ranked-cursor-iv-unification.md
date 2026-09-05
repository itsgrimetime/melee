# Ranked Cursor IV Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guarded transform-corpus family that emits `mnDiagram2_GetRankedFighter` cursor/value IV unification probes for #715 Class D.

**Architecture:** Keep the existing `TransformFamily` plus exact `Anchor`/mutator pipeline. Add a new family selected by `plan_transform_experiments()` for `mnDiagram2_GetRankedFighter`, generate full-source exact edit anchors from a narrow pattern recognizer, and apply them through the existing batch exact-edit mutator.

**Tech Stack:** Python, pytest, Typer CLI smoke tests, `melee-agent debug search plan-transforms`, local `mwcc_debug` compile/checkdiff.

---

### Task 1: Metadata And Planner Routing

**Files:**
- Modify: `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/tests/test_source_transform_catalog.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `/Users/mike/code/melee/docs/source-transform-catalog.md`

- [ ] **Step 1: Write failing metadata and routing tests**

Add assertions to `test_default_corpus_names_required_transform_families()`:

```python
    assert "ranked_cursor_iv_unification" in family_ids
```

Add a new routing test:

```python
def test_plan_transform_experiments_routes_ranked_fighter_to_cursor_iv_family() -> None:
    plan = plan_transform_experiments(
        function="mnDiagram2_GetRankedFighter",
        unit="melee/mn/mndiagram2",
        force_phys={},
    )

    assert plan.source_file == "src/melee/mn/mndiagram2.c"
    assert [family.family_id for family in plan.families] == [
        "ranked_cursor_iv_unification"
    ]
    assert plan.clusters[0].cluster_id == "ranked_cursor_iv_unification"
```

Update `test_directed_catalog_tracks_dispatch_and_families()`:

```python
    assert {
        "unify_ranked_cursor_value_accumulator",
        "reuse_rank_pointer_return_field",
    } <= set(DIRECTED_MUTATOR_KEYS)
    assert entry.technique_count == 40
    assert entry.concrete_form_count == 62
```

Update `test_catalog_has_expected_headline_counts()`:

```python
    assert summary["techniques"] == 168
    assert summary["concrete_forms"] == 115
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py::test_default_corpus_names_required_transform_families \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py::test_plan_transform_experiments_routes_ranked_fighter_to_cursor_iv_family \
  tools/melee-agent/tests/test_source_transform_catalog.py::test_catalog_has_expected_headline_counts \
  tools/melee-agent/tests/test_source_transform_catalog.py::test_directed_catalog_tracks_dispatch_and_families \
  -q
```

Expected: the first test fails because the family is absent; the second fails
because planner routing is absent.

- [ ] **Step 3: Add family metadata and planner route**

In `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus.py`,
add this `TransformFamily` to `DEFAULT_TRANSFORM_FAMILIES`:

```python
    TransformFamily(
        family_id="ranked_cursor_iv_unification",
        label="ranked cursor/value IV unification",
        mutator_keys=(
            "unify_ranked_cursor_value_accumulator",
            "reuse_rank_pointer_return_field",
        ),
        semantic_risk="medium",
        source_region_selector=(
            "selection-sort cursor loops with an indexed max-value read and "
            "a cursor-derived selected-value accumulator"
        ),
        expected_compiler_effect=(
            "unify indexed selection reads with the existing cursor/value IV "
            "so MWCC can share the holder instead of materializing a separate "
            "base-plus-index value read"
        ),
        generated_probe_form=(
            "rewrite the selected-value comparison to use and update the "
            "cursor accumulator, or reuse the rank pointer for the final field return"
        ),
        keywords=("ranked", "cursor", "iv", "selection", "accumulator"),
    ),
```

In `plan_transform_experiments()`, add a branch before the mndiagram coloring
branch:

```python
    elif function == "mnDiagram2_GetRankedFighter":
        clusters = (
            TransformCluster(
                cluster_id="ranked_cursor_iv_unification",
                label="ranked fighter cursor/value IV unification",
                source_regions=(
                    "selection-sort maxIdx update loop",
                    "rank pointer tail return",
                ),
                target_assignments=("cursor-value accumulator",),
                family_ids=("ranked_cursor_iv_unification",),
                rationale=(
                    "Probe Class D source shapes that replace indexed reads "
                    "with the existing cursor/value accumulator."
                ),
            ),
        )
```

In `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`,
add both mutator keys to `DIRECTED_MUTATOR_KEYS` and update the directed
catalog counts through the existing summary machinery. In
`/Users/mike/code/melee/docs/source-transform-catalog.md`, update the headline
counts, directed table count, directed family list, directed concrete-form
count, and paragraph text to mention `ranked_cursor_iv_unification`.

In `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`, update
`plan_transforms_cmd()` so an omitted or empty `--force-phys` produces an empty
`force_phys_map = {}`. Keep nonempty force-phys strings parsed through
`_parse_directed_force_phys()`.

- [ ] **Step 4: Re-run metadata tests**

Run the pytest command from Step 2.

Expected: both tests pass.

### Task 2: Mutator And Probe Generation

**Files:**
- Modify: `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/search/directed/mutators.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus.py`

- [ ] **Step 1: Write failing generation tests**

Add a fixture and positive test:

```python
def _ranked_cursor_iv_source() -> str:
    return (
        "typedef unsigned long long u64;\n"
        "typedef unsigned char u8;\n"
        "typedef struct Entry { u8 name; u64 value; } Entry;\n"
        "u8 target(u8 rank) {\n"
        "    Entry entries[25];\n"
        "    u64 baseVal;\n"
        "    Entry* base;\n"
        "    Entry* ptr;\n"
        "    Entry* curr;\n"
        "    int i;\n"
        "    int k;\n"
        "    int maxIdx;\n"
        "    int neg1;\n"
        "    base = entries;\n"
        "    i = 0;\n"
        "    neg1 = -1;\n"
        "    do {\n"
        "        k = i + 1;\n"
        "        curr = &entries[k];\n"
        "        maxIdx = i;\n"
        "        baseVal = base->value;\n"
        "        while (k < 25) {\n"
        "            if (curr->value != (u64) neg1) {\n"
        "                if (curr->value > entries[maxIdx].value ||\n"
        "                    baseVal == (u64) neg1)\n"
        "                {\n"
        "                    maxIdx = k;\n"
        "                }\n"
        "            }\n"
        "            curr++;\n"
        "            k++;\n"
        "        }\n"
        "        base++;\n"
        "        i++;\n"
        "    } while (i < 25);\n"
        "    ptr = &entries[rank];\n"
        "    if (ptr->value == (u64) -1) {\n"
        "        return 25;\n"
        "    }\n"
        "    return entries[rank].name;\n"
        "}\n"
    )
```

```python
def test_ranked_cursor_iv_unification_materializes_value_and_return_probes() -> None:
    probes = generate_transform_probes(
        _ranked_cursor_iv_source(),
        function="target",
        unit="melee/mn/mndiagram2",
        force_phys={},
        families=("ranked_cursor_iv_unification",),
        max_per_family=4,
    )

    ranked = [
        probe for probe in probes
        if probe.family_id == "ranked_cursor_iv_unification"
    ]
    assert [probe.mutator_key for probe in ranked] == [
        "unify_ranked_cursor_value_accumulator",
        "reuse_rank_pointer_return_field",
    ]
    assert "curr->value > baseVal ||" in ranked[0].candidate_text
    assert "                    if (baseVal != (u64) neg1) {\n" in ranked[0].candidate_text
    assert "                        baseVal = curr->value;\n" in ranked[0].candidate_text
    assert "return ptr->name;" in ranked[1].candidate_text
```

Add stale-span coverage:

```python
def test_ranked_cursor_iv_mutator_rejects_stale_span() -> None:
    probe = generate_transform_probes(
        _ranked_cursor_iv_source(),
        function="target",
        unit="melee/mn/mndiagram2",
        force_phys={},
        families=("ranked_cursor_iv_unification",),
        max_per_family=1,
    )[0]
    stale = _ranked_cursor_iv_source().replace(
        "curr->value > entries[maxIdx].value",
        "curr->value >= entries[maxIdx].value",
    )

    assert apply_mutator(probe.mutator_key, Anchor(probe.mutator_key, probe.span, probe.payload), stale) is None
```

Add guard coverage for preprocessor and non-adjacent update:

```python
@pytest.mark.parametrize(
    "source",
    (
        _ranked_cursor_iv_source().replace(
            "    Entry entries[25];\n",
            "#if 1\n    Entry entries[25];\n#endif\n",
        ),
        _ranked_cursor_iv_source().replace(
            "                    maxIdx = k;\n",
            "                    use(curr);\n                    maxIdx = k;\n",
        ),
        _ranked_cursor_iv_source().replace(
            "        base++;\n"
            "        i++;\n",
            "        use(baseVal);\n"
            "        base++;\n"
            "        i++;\n",
        ),
    ),
)
def test_ranked_cursor_iv_unification_rejects_unsafe_shapes(source: str) -> None:
    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/mn/mndiagram2",
        force_phys={},
        families=("ranked_cursor_iv_unification",),
        max_per_family=4,
    )

    assert "ranked_cursor_iv_unification" not in {probe.family_id for probe in probes}
```

- [ ] **Step 2: Run failing generation tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py::test_ranked_cursor_iv_unification_materializes_value_and_return_probes \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py::test_ranked_cursor_iv_mutator_rejects_stale_span \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py::test_ranked_cursor_iv_unification_rejects_unsafe_shapes \
  -q
```

Expected: tests fail because the mutators and analyzer do not exist.

- [ ] **Step 3: Add mutator dispatch**

In `/Users/mike/code/melee/tools/melee-agent/src/search/directed/mutators.py`,
add:

```python
def _unify_ranked_cursor_value_accumulator(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one ranked selection loop to use/update the cursor value accumulator."""
    return _apply_exact_edits(anchor, source_text)


def _reuse_rank_pointer_return_field(anchor: Anchor, source_text: str) -> Optional[str]:
    """Rewrite one ranked tail return to use the already-materialized rank pointer."""
    return _apply_exact_edits(anchor, source_text)
```

Register both keys in `_DISPATCH`.

- [ ] **Step 4: Add analyzer anchors**

In `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus.py`,
add `_iter_ranked_cursor_iv_unification_anchors(source_text, function, span)`.
It should emit two `Anchor` objects with `edits` payloads:

```python
Anchor(
    mutator_key="unify_ranked_cursor_value_accumulator",
    span=(condition_start, update_end),
    payload={
        "strategy": "ranked-cursor-value-accumulator",
        "edits": [
            {
                "kind": "indexed-value-to-accumulator",
                "start": indexed_start,
                "end": indexed_end,
                "span_text": "entries[maxIdx].value",
                "replacement_text": "baseVal",
            },
            {
                "kind": "update-accumulator-after-max",
                "start": insert_at,
                "end": insert_at,
                "span_text": "",
                "replacement_text": "\n                    baseVal = curr->value;",
            },
        ],
    },
)
```

and:

```python
Anchor(
    mutator_key="reuse_rank_pointer_return_field",
    span=(return_start, return_end),
    payload={
        "strategy": "ranked-rank-pointer-return-field",
        "edits": [
            {
                "kind": "rank-return-field",
                "start": return_start,
                "end": return_end,
                "span_text": "return entries[rank].name;",
                "replacement_text": "return ptr->name;",
            },
        ],
    },
)
```

Call the iterator from `_iter_full_source_anchors()`.

- [ ] **Step 5: Re-run generation tests**

Run the pytest command from Step 2.

Expected: all selected generation tests pass.

### Task 3: CLI Smoke And Live Candidate Validation

**Files:**
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/tests/search/test_cli_smoke.py`

- [ ] **Step 1: Run focused unit tests**

Add `test_search_plan_transforms_writes_ranked_cursor_probes_without_force_phys`
to `/Users/mike/code/melee/tools/melee-agent/tests/search/test_cli_smoke.py`.
Use a temporary `mnDiagram2_GetRankedFighter` source shaped like
`_ranked_cursor_iv_source()`, call `plan-transforms` without `--force-phys`,
write probes, and assert both ranked-cursor mutator keys are present with
candidate files.

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/test_cli_smoke.py::test_search_plan_transforms_writes_ranked_cursor_probes_without_force_phys \
  -q
```

Expected: all tests in the module pass.

- [ ] **Step 2: Run CLI plan smoke on the real source path**

Run:

```bash
rm -rf build/issue715-ranked-cursor-probes
melee-agent debug search plan-transforms \
  -f mnDiagram2_GetRankedFighter \
  -u melee/mn/mndiagram2 \
  --source-file src/melee/mn/mndiagram2.c \
  --max-per-family 4 \
  --write-probes build/issue715-ranked-cursor-probes \
  --json
```

Expected: JSON includes `ranked_cursor_iv_unification`, at least one probe with
`unify_ranked_cursor_value_accumulator`, and a written candidate under
`build/issue715-ranked-cursor-probes/`.

- [ ] **Step 3: Compile/checkdiff generated candidates**

Run every generated ranked-cursor candidate through local debug dump and keep
the best result:

```bash
for candidate in $(find build/issue715-ranked-cursor-probes -name '*.c' | sort); do
  echo "=== $candidate ==="
  melee-agent debug dump local \
    "$candidate" \
    --unit-source src/melee/mn/mndiagram2.c \
    -f mnDiagram2_GetRankedFighter \
    --diff \
    --no-cache-sync \
    --checkdiff-timeout 90
done
```

Expected: commands complete and print checkdiff output. If any candidate reports
`match=true`, #715 can be resolved. If not, record the best result and leave
#715 open.

### Task 4: Finish

**Files:**
- Modify: `/Users/mike/code/melee/docs/superpowers/specs/2026-06-15-ranked-cursor-iv-unification-design.md`
- Modify: `/Users/mike/code/melee/docs/superpowers/plans/2026-06-15-ranked-cursor-iv-unification.md`
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/search/directed/mutators.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/search/cli/__init__.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `/Users/mike/code/melee/tools/melee-agent/tests/test_source_transform_catalog.py`
- Modify: `/Users/mike/code/melee/docs/source-transform-catalog.md`

- [ ] **Step 1: Run targeted verification**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/test_cli_smoke.py::test_search_plan_transforms_writes_concrete_coloring_register_steering_probes \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Refresh editable install**

Run:

```bash
python tools/worktree-doctor.py --fix
/opt/homebrew/bin/melee-agent debug search plan-transforms \
  -f mnDiagram2_GetRankedFighter \
  -u melee/mn/mndiagram2 \
  --source-file src/melee/mn/mndiagram2.c \
  --max-per-family 2 \
  --json
```

Expected: `/opt/homebrew/bin/melee-agent` imports `/Users/mike/code/melee/tools/melee-agent/...` and the JSON includes `ranked_cursor_iv_unification`.

- [ ] **Step 3: Commit and resolve**

Stage only the docs, tests, and `tools/melee-agent` files changed by this plan:

```bash
git add \
  docs/superpowers/specs/2026-06-15-ranked-cursor-iv-unification-design.md \
  docs/superpowers/plans/2026-06-15-ranked-cursor-iv-unification.md \
  docs/source-transform-catalog.md \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/search/cli/__init__.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py
git commit -m "feat: add ranked cursor IV probes"
```

If live validation produced `match=true`, resolve #715:

```bash
commit=$(git rev-parse --short HEAD)
melee-agent issue resolve 715 --note "fixed in $commit: added ranked_cursor_iv_unification and verified mnDiagram2_GetRankedFighter match=true"
```

If live validation did not match, leave #715 open and add a note instead:

```bash
commit=$(git rev-parse --short HEAD)
melee-agent issue note 715 "Added ranked_cursor_iv_unification in $commit; candidates compile but did not match mnDiagram2_GetRankedFighter. Remaining Class D residual needs backend or combined source-shape work."
```
