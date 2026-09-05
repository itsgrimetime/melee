# Class A Product-Dependent Recompute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guarded `coloring_register_steering` Class A source probe that recomputes an FPR product in a dependent local assignment without adding locals.

**Architecture:** Keep the existing transform-corpus family and exact-span mutator model. Add one direct steering key, `steer_fpr_dependent_product_recompute`, produced by a narrow target-body analyzer and applied by `_replace_validated_span`. Emit dependent-first and same-order variants so search can perturb first-use pressure and CSE ownership while keeping the candidate source compilable and scoreable.

**Tech Stack:** Python, pytest, Typer CLI tests, Melee `melee-agent` directed transform corpus.

---

### Task 1: Metadata And Catalog Tests

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`
- Later implementation files: `tools/melee-agent/src/search/directed/transform_corpus.py`, `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`

- [ ] **Step 1: Write failing metadata tests**

Update `test_coloring_register_steering_metadata_is_executable()` so the expected tuple includes the new key immediately before node-set materialized keys:

```python
        "steer_widen_byte_local_type",
        "steer_fpr_dependent_product_recompute",
        "steer_node_set_delta_coupled_split",
```

Update `test_directed_catalog_tracks_dispatch_and_families()` so the set assertion includes:

```python
        "steer_fpr_dependent_product_recompute",
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py::test_coloring_register_steering_metadata_is_executable \
  tools/melee-agent/tests/test_source_transform_catalog.py::test_directed_catalog_tracks_dispatch_and_families \
  -q
```

Expected: both fail because the new mutator key is not in production metadata/catalog.

- [ ] **Step 3: Add production metadata**

In `tools/melee-agent/src/search/directed/transform_corpus.py`, add the key to the `coloring_register_steering` `mutator_keys` tuple immediately after `steer_widen_byte_local_type`.

In `_DIRECT_REGISTER_STEERING_KEYS`, add:

```python
    "steer_fpr_dependent_product_recompute",
```

In `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`, add the key to `DIRECTED_MUTATOR_KEYS` immediately after `steer_widen_byte_local_type`.

Update the catalog note for `coloring_register_steering` to mention product-dependent recompute:

```python
"coloring_register_steering aliases guarded declaration/lifetime edits and FPR product recompute probes for mndiagram force-phys register-coloring residuals.",
```

- [ ] **Step 4: Run metadata tests and verify they pass**

Run the same pytest command from Step 2.

Expected: `2 passed`.

### Task 2: Probe Generation Tests

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Later implementation file: `tools/melee-agent/src/search/directed/transform_corpus.py`

- [ ] **Step 1: Add positive generation tests**

Import the mutator dispatcher and anchor type near the top of the test file:

```python
from src.search.directed.anchors import Anchor
from src.search.directed.mutators import apply_mutator
```

Add this test near the existing `coloring_register_steering` tests:

```python
def test_coloring_register_steering_recomputes_fpr_dependent_product_before_decl_aliases() -> None:
    source = (
        "typedef unsigned char u8;\n"
        "typedef float f32;\n"
        "void mnDiagram_80241E78(u8 arg2) {\n"
        "    void** joint_data;\n"
        "    f32 y_offset;\n"
        "    f32 row_offset;\n"
        "    f32 col_offset;\n"
        "    f32 row_offset_adj;\n"
        "    u8 row = arg2;\n"
        "    row_offset = y_offset * (f32) row;\n"
        "    row_offset_adj = row_offset - 1.0f;\n"
        "    use(joint_data, row_offset, row_offset_adj, col_offset);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={33: 28, 37: 26},
        families=("coloring_register_steering",),
        max_per_family=1,
    )

    assert len(probes) == 1
    probe = probes[0]
    assert probe.mutator_key == "steer_fpr_dependent_product_recompute"
    assert probe.payload["strategy"] == "fpr-dependent-product-recompute-first"
    assert (
        "    row_offset_adj = (y_offset * (f32) row) - 1.0f;\n"
        "    row_offset = y_offset * (f32) row;"
    ) in probe.candidate_text
    assert probe.candidate_text.count("f32 ") == source.count("f32 ")
```

Add a second positive test proving same-order and rowf-style sources materialize when budget allows:

```python
def test_coloring_register_steering_recomputes_rowf_product_same_order_when_budget_allows() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_80241E78(u8 row) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    rowf = (f32) row;\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    use(row_offset, row_offset_adj);\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={33: 28, 37: 26},
        families=("coloring_register_steering",),
        max_per_family=4,
    )

    recompute = [
        probe for probe in probes
        if probe.mutator_key == "steer_fpr_dependent_product_recompute"
    ]
    assert [probe.payload["strategy"] for probe in recompute[:2]] == [
        "fpr-dependent-product-recompute-first",
        "fpr-dependent-product-recompute-same-order",
    ]
    assert (
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = (y_offset * rowf) - 0.4f;"
    ) in recompute[1].candidate_text
```

- [ ] **Step 2: Add negative and stale-span tests**

Add a parametrized rejection test:

```python
@pytest.mark.parametrize(
    ("case", "body"),
    (
        (
            "non-fpr local",
            "    int row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = row * col;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "declaration initializer",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * rowf;\n"
            "    f32 row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "non-adjacent",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * rowf;\n"
            "    use(row_offset);\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "call operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * get_rowf();\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "member operand",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * data->rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "address taken",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n"
            "    use(&row_offset);\n",
        ),
        (
            "synthetic name",
            "    f32 row_offset_split_33_0;\n"
            "    f32 row_offset_adj;\n"
            "    row_offset_split_33_0 = y_offset * rowf;\n"
            "    row_offset_adj = row_offset_split_33_0 - 1.0f;\n",
        ),
        (
            "shadowed",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "    if (ready()) {\n"
            "        f32 row_offset;\n"
            "        use(row_offset);\n"
            "    }\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n",
        ),
        (
            "preprocessor",
            "    f32 row_offset;\n"
            "    f32 row_offset_adj;\n"
            "#if 1\n"
            "    row_offset = y_offset * rowf;\n"
            "    row_offset_adj = row_offset - 1.0f;\n"
            "#endif\n",
        ),
    ),
)
def test_coloring_register_steering_rejects_unsafe_fpr_product_recompute(
    case: str,
    body: str,
) -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_80241E78(void) {\n"
        "    f32 y_offset;\n"
        "    f32 rowf;\n"
        f"{body}"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="mnDiagram_80241E78",
        unit="melee/mn/mndiagram",
        force_phys={33: 28, 37: 26},
        families=("coloring_register_steering",),
        max_per_family=12,
    )

    assert "steer_fpr_dependent_product_recompute" not in {
        probe.mutator_key for probe in probes
    }, case
```

Add a direct mutator stale-span test:

```python
def test_steer_fpr_dependent_product_recompute_rejects_stale_span() -> None:
    source = (
        "void f(void) {\n"
        "    row_offset = y_offset * rowf;\n"
        "    row_offset_adj = row_offset - 1.0f;\n"
        "}\n"
    )
    anchor = Anchor(
        mutator_key="steer_fpr_dependent_product_recompute",
        span=(source.index("    row_offset"), source.index("}\n")),
        payload={
            "span_text": "    missing = y_offset * rowf;",
            "replacement_text": "    row_offset_adj = (y_offset * rowf) - 1.0f;",
        },
    )

    assert apply_mutator("steer_fpr_dependent_product_recompute", anchor, source) is None
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  -q -k 'fpr_dependent_product_recompute or coloring_register_steering_metadata'
```

Expected: failures because generation and dispatcher support are not implemented.

### Task 3: Implement Analyzer And Mutator

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/search/directed/mutators.py`

- [ ] **Step 1: Add mutator dispatch**

In `tools/melee-agent/src/search/directed/mutators.py`, add:

```python
def _steer_fpr_dependent_product_recompute(anchor: Anchor, source_text: str) -> Optional[str]:
    """Duplicate one exact FPR product into a dependent local assignment."""
    return _replace_validated_span(anchor, source_text)
```

Add it to `_DISPATCH`:

```python
    "steer_fpr_dependent_product_recompute": _steer_fpr_dependent_product_recompute,
```

- [ ] **Step 2: Add product analyzer helpers**

In `tools/melee-agent/src/search/directed/transform_corpus.py`, near the existing register-steering regex helpers, add helper constants and functions:

```python
_REGISTER_STEERING_FPR_TYPES = frozenset({"float", "f32", "double", "f64"})
_REGISTER_STEERING_ASSIGN_RE = re.compile(
    r"^(?P<indent>[ \t]+)(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+?)\s*;\s*$"
)
_REGISTER_STEERING_DEPENDENT_RE = re.compile(
    r"^(?P<lhs>[A-Za-z_]\w*)\s*(?P<op>[+-])\s*(?P<const>(?:\d+(?:\.\d*)?|\.\d+)(?:f)?)$|"
    r"^(?P<const_left>(?:\d+(?:\.\d*)?|\.\d+)(?:f)?)\s*(?P<op_left>[+-])\s*(?P<lhs_right>[A-Za-z_]\w*)$"
)
```

Add helpers that:

- split a top-level `*` only when the RHS has exactly one top-level multiply,
- accept terms matching either `name` or `(f32) name` / `(float) name` / `(double) name` / `(f64) name`,
- reject terms containing `.`, `->`, `[`, `]`, `(` not part of the leading cast, `)`, `&`, `*` as dereference, `?`, `:`, `,`, `=`, `++`, `--`, `||`, `&&`,
- collect declaration counts from `_register_steering_decl_records(body_text)` and reject non-unique or non-FPR target/dependent declarations,
- reject `_node_set_split_synthetic_name(lhs)` and `_node_set_split_synthetic_name(dependent)`,
- reject address-takes of either target via `_counter_address_take_rejects(searchable, name)`,
- reject mismatched raw/searchable mentions via `_counter_identifier_region_rejects(searchable, body_text, lhs, dependent)`.

- [ ] **Step 3: Add anchor generator**

Add `_iter_fpr_dependent_product_recompute_anchors(body_text: str) -> list[Anchor]`.

For each adjacent pair of top-level lines:

1. Match the first line as `primary = product_left * product_right;`.
2. Match the second line as `dependent = primary +/- fp_const;` or `dependent = fp_const +/- primary;`.
3. Build `span_text` from the first line start through the second line end.
4. Emit dependent-first first:

```python
replacement_text = (
    f"{indent}{dependent} = ({product_expr}) {op} {const_text};\n"
    f"{indent}{primary} = {product_expr};"
)
```

5. Emit same-order second:

```python
replacement_text = (
    f"{indent}{primary} = {product_expr};\n"
    f"{indent}{dependent} = ({product_expr}) {op} {const_text};"
)
```

For `const - primary`, preserve the operator order:

```python
dependent = const - (product_expr);
```

Set payload fields:

```python
{
    "span_text": span_text,
    "replacement_text": replacement_text,
    "strategy": "fpr-dependent-product-recompute-first",
    "product_local": primary,
    "dependent_local": dependent,
    "product_expr": product_expr,
}
```

Use strategy `"fpr-dependent-product-recompute-same-order"` for the second variant.

- [ ] **Step 4: Wire generator priority**

In `_iter_concrete_register_steering_body_anchors`, compute recompute anchors before the broad decl-record gate:

```python
    recompute_product = _iter_fpr_dependent_product_recompute_anchors(body_text)
```

Then after the broad decl checks, yield:

```python
    yield from _interleave_anchor_groups(
        recompute_product,
        rotate,
        demote,
        reuse_dead,
        split,
        widen_byte,
    )
```

Do not let `decls is None`, duplicate non-target declarations, or unsupported unrelated top-level declarations suppress `recompute_product`; only the recompute helper's own exact proof should decide that. If broad declaration steering aborts, still yield recompute anchors.

- [ ] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q -k 'fpr_dependent_product_recompute or coloring_register_steering_metadata or directed_catalog'
```

Expected: all selected tests pass.

### Task 4: CLI Smoke And Catalog Docs

**Files:**
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `docs/source-transform-catalog.md`

- [ ] **Step 1: Update CLI smoke test**

In `test_search_plan_transforms_writes_concrete_coloring_register_steering_probes`, update the fixture to include the product pattern before the existing loop-counter fixture, then update the expected mutator order:

```python
        "    f32 y_offset;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    row_offset = y_offset * (f32) seed;\n"
        "    row_offset_adj = row_offset - 1.0f;\n"
```

Expected steering keys:

```python
    assert [probe["mutator_key"] for probe in steering] == [
        "steer_fpr_dependent_product_recompute",
        "steer_rotate_local_decl_window",
        "steer_demote_local_decl_to_first_use",
    ]
```

- [ ] **Step 2: Update catalog docs**

In `docs/source-transform-catalog.md`, update the directed concrete form counts by one and update the `coloring_register_steering` paragraph to include "FPR product-dependent recompute".

- [ ] **Step 3: Run CLI/catalog tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/test_cli_smoke.py::test_search_plan_transforms_writes_concrete_coloring_register_steering_probes \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q
```

Expected: pass.

### Task 5: Verification, Live Evidence, And Issue State

**Files:**
- No new files unless verification artifacts are intentionally saved under `/tmp`.

- [ ] **Step 1: Run focused regression set**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/test_cli_smoke.py::test_search_plan_transforms_writes_concrete_coloring_register_steering_probes \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q
```

Expected: pass.

- [ ] **Step 2: Run static checks**

Run:

```bash
python -m compileall -q tools/melee-agent/src
git diff --check
```

Expected: both exit 0.

- [ ] **Step 3: Run real plan-transforms smoke**

Run:

```bash
rm -rf /tmp/issue715-probes
python -m src.cli debug search plan-transforms \
  -f mnDiagram_80241E78 \
  -u melee/mn/mndiagram \
  --force-phys 1:33:28,1:37:26 \
  --source-file src/melee/mn/mndiagram.c \
  --max-per-family 3 \
  --write-probes /tmp/issue715-probes \
  --json > /tmp/issue715-plan.json
jq -r '.probes[] | [.probe_id,.mutator_key,.candidate_path] | @tsv' /tmp/issue715-plan.json
```

Expected: at least one row has `steer_fpr_dependent_product_recompute`, and the candidate file exists.

- [ ] **Step 4: Score generated candidates against the real function**

For each generated recompute candidate, temporarily copy it over `src/melee/mn/mndiagram.c`, run:

```bash
python tools/checkdiff.py mnDiagram_80241E78 --format json > /tmp/issue715-score.json
```

Always restore `src/melee/mn/mndiagram.c` afterward and verify:

```bash
git diff -- src/melee/mn/mndiagram.c --stat
```

Expected: source diff is empty after scoring. If any score JSON has `"match": true`, #715's stop condition is met. If none match, leave #715 open and note the bounded negative evidence.

- [ ] **Step 5: Commit implementation**

Run:

```bash
git add \
  tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/src/search/directed/mutators.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  docs/source-transform-catalog.md
git commit -m "feat: add FPR product recompute steering probes"
```

- [ ] **Step 6: Resolve or leave #715 correctly**

If Step 4 found a `match=true` candidate, run:

```bash
DECOMP_AGENT_ID=codex-issue-resolver-3-20260615 melee-agent issue resolve 715 --note "fixed in <commit>: added steer_fpr_dependent_product_recompute and verified <function> match=true via generated candidate <probe>."
```

If Step 4 did not find a match, do not resolve #715. Keep the issue claimed and continue with the next scoped Class A or Class B implementation slice from the #715 issue text.

- [ ] **Step 7: Refresh editable install**

After all tool changes are committed on `master`, run:

```bash
/opt/homebrew/bin/python3.11 -m pip install -e /Users/mike/code/melee/tools/melee-agent
/opt/homebrew/bin/python3.11 - <<'PY'
import src.cli, src.search.directed.transform_corpus
print(src.cli.__file__)
print(src.search.directed.transform_corpus.__file__)
PY
```

Expected: both imported paths are under `/Users/mike/code/melee/tools/melee-agent/src`.
