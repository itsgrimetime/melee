# Source-Lifetime Helper-Inline Transform Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `source-lifetime` structure-search axis that emits ranked retained source transforms for helper-inline/source-lifetime register cascades and verifies the issue #444 seed set.

**Architecture:** Extend `pressure_explorer` with targeted source-lifetime probe families, then adapt those probes into `StructureVariant` rows under a new optional `debug search structure --axis source-lifetime` axis. Reuse the existing structure scorer for real-TU compile, baseline/candidate/delta, checkdiff status, retained source, and structural metrics; add opcode-shape preservation metadata and source-lifetime-specific ranking.

**Tech Stack:** Python 3, Typer CLI, pytest, existing `tools/melee-agent` search and mwcc-debug modules.

---

## File Structure

- Modify `tools/melee-agent/src/mwcc_debug/pressure_explorer.py`
  - Add source-lifetime targeted probe families.
  - Add read-only helper safety gate.
  - Add `generate_source_lifetime_probes()`.
  - Add helper-inline lifetime operator constants.
- Modify `tools/melee-agent/src/search/structure.py`
  - Add optional `source-lifetime` axis.
  - Add axis summary metadata for per-family blockers.
  - Add source-lifetime ranking boost for opcode-shape-preserving candidates.
- Modify `tools/melee-agent/src/search/structure_scoring.py`
  - Add `opcode_shape_preserved` to structural metrics when opcode similarity is present.
- Modify `tools/melee-agent/src/cli/debug.py`
  - Add `helper-inline-lifetime` focus.
  - Route that focus through the source-lifetime probe generator.
- Modify `tools/melee-agent/src/search/cli.py`
  - Update axis help text if it enumerates supported axes.
- Tests:
  - `tools/melee-agent/tests/test_pressure_explorer.py`
  - `tools/melee-agent/tests/search/test_structure.py`
  - `tools/melee-agent/tests/search/test_structure_scoring.py`
  - `tools/melee-agent/tests/search/test_cli_smoke.py`

---

### Task 1: Targeted Source-Lifetime Probe Families

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/pressure_explorer.py`
- Test: `tools/melee-agent/tests/test_pressure_explorer.py`

- [ ] **Step 1: Write failing tests for targeted probes**

Add tests near the existing lifetime-layout probe tests:

```python
def test_source_lifetime_for_condition_field_reload_probe() -> None:
    source = textwrap.dedent("""\
        s32 fn_803ACD58(CardState* state)
        {
            s32 i;
            s32 size;
            for (i = 0; size = state->x8, i < (0x2F + state->x24 + size) / size; i++) {
                sink(i, size);
            }
            return 0;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_803ACD58",
        max_probes=8,
    )

    by_operator = {probe.operator: probe for probe in probes}
    assert "for-condition-field-reload" in by_operator
    probe = by_operator["for-condition-field-reload"]
    assert "size = state->x8" not in _for_condition_line(probe.source_text)
    assert probe.provenance["kind"] == "for-condition-field-reload"
    assert any(row["operator"] == "for-condition-field-reload" for row in summaries)
```

```python
def test_source_lifetime_repeated_helper_result_reuse_probe() -> None:
    source = textwrap.dedent("""\
        s32 fn_803AC7DC(CardState* state, s32 i)
        {
            s32 total = 0;
            s32 extra = 0;
            total += fn_803AC634(state, i);
            if (extra < (s32) fn_803AC634(state, i)) {
                extra = (s32) fn_803AC634(state, i);
            }
            return total + extra;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_803AC7DC",
        max_probes=8,
    )

    probe = next(probe for probe in probes if probe.operator == "repeated-helper-result-reuse")
    assert "s32 ll_probe_helper_result_0 = (s32) fn_803AC634(state, i);" in probe.source_text
    assert probe.source_text.count("fn_803AC634(state, i)") == 1
    assert probe.provenance["callee"] == "fn_803AC634"
```

```python
def test_source_lifetime_helper_result_dematerialize_probe() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 result;
            result = fn_803AC634(state, i);
            sink(result);
            return result;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(probe for probe in probes if probe.operator == "helper-result-dematerialize")
    assert "result = fn_803AC634(state, i);" not in probe.source_text
    assert "sink(fn_803AC634(state, i));" in probe.source_text
    assert "return fn_803AC634(state, i);" in probe.source_text
```

```python
def test_source_lifetime_simple_helper_inline_body_probe() -> None:
    source = textwrap.dedent("""\
        static inline s32 helper(CardState* state, s32 i)
        {
            return state->x4C[i] + 1;
        }

        s32 fn_80000000(CardState* state, s32 i)
        {
            return helper(state, i);
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    probe = next(probe for probe in probes if probe.operator == "simple-helper-inline-body")
    assert "return state->x4C[i] + 1;" in probe.source_text
    assert "return helper(state, i);" not in probe.source_text
```

```python
def test_source_lifetime_rejects_unsafe_helper_call_rewrites() -> None:
    source = textwrap.dedent("""\
        s32 fn_80000000(CardState* state, s32 i)
        {
            s32 a = mutating_helper(state, i);
            s32 b = mutating_helper(state, i);
            return a + b;
        }
    """)

    probes, summaries = generate_source_lifetime_probes(
        source,
        "fn_80000000",
        max_probes=8,
    )

    assert "repeated-helper-result-reuse" not in {probe.operator for probe in probes}
    blocked = [row for row in summaries if row["operator"] == "repeated-helper-result-reuse"]
    assert blocked
    assert blocked[0]["blocker"] == "callee-not-read-only"
```

Include this local helper in the test file:

```python
def _for_condition_line(source: str) -> str:
    return next(line for line in source.splitlines() if line.strip().startswith("for ("))
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
cd tools/melee-agent
PYTEST_ADDOPTS=--no-cov python -m pytest tests/test_pressure_explorer.py \
  -k 'source_lifetime' -q
```

Expected: failures because `generate_source_lifetime_probes` does not exist.

- [ ] **Step 3: Implement probe generator constants and summaries**

In `pressure_explorer.py`, add:

```python
SOURCE_LIFETIME_TARGETED_OPERATORS = (
    "for-condition-field-reload",
    "repeated-helper-result-reuse",
    "helper-result-dematerialize",
    "simple-helper-inline-body",
)

SOURCE_LIFETIME_GENERIC_OPERATORS = (
    "declaration-order",
    "loop-counter-hoist",
    "loop-counter-type",
    "temp-introduction",
    "temp-removal",
    "declaration-use-distance",
    "block-scope",
    "call-argument-tempization",
    "expression-shape",
)

HELPER_INLINE_LIFETIME_OPERATORS = (
    *SOURCE_LIFETIME_TARGETED_OPERATORS,
    *SOURCE_LIFETIME_GENERIC_OPERATORS,
)

_READ_ONLY_SOURCE_LIFETIME_HELPERS = frozenset({"fn_803AC634"})
```

Add:

```python
def generate_source_lifetime_probes(
    source_text: str,
    function: str,
    *,
    max_probes: int = 12,
) -> tuple[list[LifetimeLayoutProbe], list[dict]]:
    max_probes = max(0, int(max_probes))
    if max_probes == 0:
        return [], []
    targeted_budget = max(1, (max_probes + 1) // 2)
    targeted_generators = (
        ("for-condition-field-reload", _probe_for_condition_field_reload),
        ("repeated-helper-result-reuse", _probe_repeated_helper_result_reuse),
        ("helper-result-dematerialize", _probe_helper_result_dematerialize),
        ("simple-helper-inline-body", _probe_simple_helper_inline_body),
    )
    targeted: list[LifetimeLayoutProbe] = []
    summaries: list[dict] = []
    for operator, generator in targeted_generators:
        candidates, summary = generator(source_text, function)
        summaries.append(summary)
        for probe in candidates:
            if len(targeted) < targeted_budget:
                _append_probe(targeted, probe)
            else:
                summary["retained_candidates"] = targeted_budget
                break
    generic = generate_lifetime_layout_probes(
        source_text,
        function,
        max_probes=max_probes,
        operator_filter=SOURCE_LIFETIME_GENERIC_OPERATORS,
    )
    probes: list[LifetimeLayoutProbe] = []
    for probe in [*targeted, *generic]:
        _append_probe(probes, probe)
        if len(probes) >= max_probes:
            break
    return probes, summaries
```

Each targeted generator returns `(list[LifetimeLayoutProbe], summary_dict)`.
The summary shape must be:

```python
{
    "operator": operator,
    "status": "generated" | "blocked",
    "candidate_count": len(probes),
    "blocker": None | "callee-not-read-only" | "helper-body-too-complex" | "...",
    "reason": "...",
}
```

- [ ] **Step 4: Implement `for-condition-field-reload`**

Add a conservative regex over the target function body that matches:

```c
for (i = 0; size = state->x8, i < expr_using_size; i++)
```

Emit at least one C89-compatible variant that keeps the reload in the `for`
clauses instead of moving it into the loop body:

```c
for (i = 0, size = state->x8; i < expr_using_size; i++, size = state->x8) {
    ...
}
```

The implementation must skip the candidate if the touched `for` header is
unbalanced, if the reload RHS contains `++`, `--`, `?`, or assignment, or if the
touched region crosses a preprocessor directive. Do not emit a body-tail reload
candidate because `continue` statements can skip that reload relative to the
original comma-expression condition.

- [ ] **Step 5: Implement helper call safety and helper-call probes**

Add `_helper_call_is_read_only(callee, source, function)`:

```python
def _helper_expression_is_pure(expr: str) -> bool:
    return (
        _helper_call_args_are_simple(expr)
        and not re.search(r"\b[A-Za-z_]\w*\s*\(", expr)
    )

def _helper_call_is_read_only(callee: str, source: str, function: str) -> bool:
    if callee in _READ_ONLY_SOURCE_LIFETIME_HELPERS:
        return True
    body_expr = _simple_helper_expression_body(source, callee)
    return body_expr is not None and _helper_expression_is_pure(body_expr)
```

Also add `_helper_call_args_are_simple(args_text)` and require it for every
helper-call rewrite and inline expansion. The argument text must be balanced and
must reject side effects or address/lifetime-sensitive forms: `++`, `--`, `=`,
`?`, `&local`, comma operators outside nested calls, macro-like arguments, and
arguments containing preprocessor directives. If the helper call appears in a
statement that is not a simple assignment, return, call statement, or safely
block-wrapped `case` arm, skip the candidate and record a family summary
blocker.

The same side-effect checks apply to same-TU helper bodies. `_simple_helper_expression_body`
only identifies a single-expression helper; it is not enough by itself to prove
the helper is read-only. Any helper body expression containing side-effecting
operators, assignments, address-taking of locals, unknown nested calls, or
preprocessor text must be rejected for reuse, dematerialization, and inline-body
expansion.

Implement:

- `_probe_repeated_helper_result_reuse`
  - Find repeated identical `callee(args)` strings in a same basic statement
    region.
  - Require `_helper_call_is_read_only` and `_helper_call_args_are_simple`.
  - Insert `s32 ll_probe_helper_result_0 = (s32) callee(args);` before the first
    statement in the region. If that first statement is directly under a
    `case`/`default` label, either wrap that case arm in braces and put the
    declaration at the top of the new block, or skip with
    `blocker="case-arm-declaration-unsafe"`.
  - Replace later occurrences with `ll_probe_helper_result_0`, leaving the first
    call in the declaration.
- `_probe_helper_result_dematerialize`
  - Find `name = callee(args);` where `name` is used one or two times in later
    simple statements.
  - Require `_helper_call_is_read_only` and `_helper_call_args_are_simple`.
  - Remove the assignment and replace those simple uses with `callee(args)`.
- `_probe_simple_helper_inline_body`
  - Parse a same-TU helper signature and a single `return expr;` body.
  - Require balanced simple call arguments through `_helper_call_args_are_simple`.
  - Require `_helper_expression_is_pure` for the helper return expression before
    substituting actual arguments.
  - Replace one `helper(actuals)` call in the target function with the helper
    expression with parameter identifiers substituted by actual argument text.

- [ ] **Step 6: Verify Task 1 passes**

Run:

```bash
cd tools/melee-agent
PYTEST_ADDOPTS=--no-cov python -m pytest tests/test_pressure_explorer.py \
  -k 'source_lifetime or helper_inline_lifetime or lifetime_layout_cli_focuses_b4_tree_loop_probe_families' -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 1**

Stage only:

```bash
git add tools/melee-agent/src/mwcc_debug/pressure_explorer.py \
        tools/melee-agent/tests/test_pressure_explorer.py
git commit -m "Add source lifetime probe families"
```

---

### Task 2: Structure Search Axis And Shape-Aware Scoring

**Files:**
- Modify: `tools/melee-agent/src/search/structure.py`
- Modify: `tools/melee-agent/src/search/structure_scoring.py`
- Modify: `tools/melee-agent/src/search/cli.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`
- Test: `tools/melee-agent/tests/search/test_structure_scoring.py`

- [ ] **Step 1: Write failing structure-axis tests**

Add to `tests/search/test_structure.py`:

```python
def test_run_structure_search_source_lifetime_axis_emits_retained_candidates(tmp_path: Path) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "s32 fn_803AC7DC(CardState* state, s32 i)\\n"
        "{\\n"
        "    s32 total = 0;\\n"
        "    total += fn_803AC634(state, i);\\n"
        "    if (total < (s32) fn_803AC634(state, i)) {\\n"
        "        total = (s32) fn_803AC634(state, i);\\n"
        "    }\\n"
        "    return total;\\n"
        "}\\n"
    )

    payload = run_structure_search(
        "fn_803AC7DC",
        source_path,
        tmp_path / "structure",
        axes=("source-lifetime",),
        max_candidates=2,
        score_variants=False,
    )

    assert payload["axes"][0]["axis"] == "source-lifetime"
    assert payload["axes"][0]["status"] == "evaluated"
    assert payload["axes"][0]["metadata"]["families"]
    assert payload["variants"]
    assert all(row["axis"] == "source-lifetime" for row in payload["variants"])
    assert all(Path(row["source_retained"]).exists() for row in payload["variants"])
```

```python
def test_source_lifetime_axis_prioritizes_targeted_probes_under_small_cap(tmp_path: Path) -> None:
    source_path = tmp_path / "demo.c"
    source_path.write_text(
        "s32 fn_803ACD58(CardState* state)\\n"
        "{\\n"
        "    s32 i;\\n"
        "    s32 size;\\n"
        "    s32 total;\\n"
        "    for (i = 0; size = state->x8, i < (0x2F + state->x24 + size) / size; i++) {\\n"
        "        total += i;\\n"
        "    }\\n"
        "    return total;\\n"
        "}\\n"
    )

    payload = run_structure_search(
        "fn_803ACD58",
        source_path,
        tmp_path / "structure",
        axes=("source-lifetime",),
        max_candidates=1,
        score_variants=False,
    )

    assert payload["variants"][0]["operator"] == "for-condition-field-reload"
```

```python
def test_source_lifetime_ranking_prefers_shape_preserved_candidate() -> None:
    ranked = rank_structure_variants([
        StructureVariant(
            axis="source-lifetime",
            operator="helper-result-dematerialize",
            label="shape-break",
            status="ok",
            final_match_percent=99.0,
            delta=1.0,
            metadata={"structural": {"opcode_shape_preserved": False}},
        ),
        StructureVariant(
            axis="source-lifetime",
            operator="repeated-helper-result-reuse",
            label="shape-preserved",
            status="ok",
            final_match_percent=98.0,
            delta=0.5,
            metadata={"structural": {"opcode_shape_preserved": True}},
        ),
    ])

    assert [variant.label for variant in ranked] == ["shape-preserved", "shape-break"]
```

- [ ] **Step 2: Write failing scorer metadata test**

Add to `tests/search/test_structure_scoring.py`:

```python
def test_structural_metrics_include_opcode_shape_preserved() -> None:
    structural = scoring_mod._structural_with_deltas(
        {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
        {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
    )

    assert structural["opcode_shape_preserved"] is True

    structural = scoring_mod._structural_with_deltas(
        {"opcode_similarity": 1.0},
        {"opcode_similarity": 0.98},
    )

    assert structural["opcode_shape_preserved"] is False
```

- [ ] **Step 3: Verify tests fail**

Run:

```bash
cd tools/melee-agent
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tests/search/test_structure.py::test_run_structure_search_source_lifetime_axis_emits_retained_candidates \
  tests/search/test_structure.py::test_source_lifetime_axis_prioritizes_targeted_probes_under_small_cap \
  tests/search/test_structure.py::test_source_lifetime_ranking_prefers_shape_preserved_candidate \
  tests/search/test_structure_scoring.py::test_structural_metrics_include_opcode_shape_preserved -q
```

Expected: failures because the axis and metadata do not exist.

- [ ] **Step 4: Add axis summary metadata support**

In `AxisSummary`, add:

```python
metadata: dict[str, Any] = field(default_factory=dict)
```

Keep `to_dict()` omitting empty metadata by filtering `{}`.

- [ ] **Step 5: Add `source-lifetime` axis**

In `run_structure_search`, add an `if axis == "source-lifetime"` block that:

1. Blocks with `source-unavailable` when source is unavailable.
2. Calls `generate_source_lifetime_variants(...)`.
3. Appends the returned summary and variants.

Implement `generate_source_lifetime_variants` in `structure.py`:

```python
def generate_source_lifetime_variants(
    source: str,
    function: str,
    output_dir: Path,
    *,
    baseline_percent: float | None,
    max_candidates: int,
) -> tuple[AxisSummary, list[StructureVariant]]:
    from src.mwcc_debug.pressure_explorer import generate_source_lifetime_probes

    probes, family_summaries = generate_source_lifetime_probes(
        source,
        function,
        max_probes=max_candidates,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = []
    command = (
        f"melee-agent debug search structure -f {function} "
        f"--axis source-lifetime --max-candidates {max_candidates}"
    )
    for probe in probes[:max_candidates]:
        path = output_dir / f"{_safe_candidate_label(probe.label)}.c"
        path.write_text(probe.source_text, encoding="utf-8")
        variants.append(StructureVariant(...))
    if not variants:
        return AxisSummary(
            axis="source-lifetime",
            status="blocked",
            blocker="no-source-lifetime-candidates",
            reason="no safe source-lifetime helper-inline probe generated",
            metadata={"families": family_summaries},
        ), []
    return AxisSummary(
        axis="source-lifetime",
        status="evaluated",
        candidate_count=len(variants),
        metadata={"families": family_summaries},
    ), variants
```

The `StructureVariant.metadata` must include `{"probe": probe.to_dict(), "live_mutation": False}`.

- [ ] **Step 6: Add shape-aware ranking and scorer metadata**

In `rank_structure_variants`, add a source-lifetime-only sort key after the
exact-match bucket and before match percent:

```python
_source_lifetime_shape_rank(variant)
```

Implement:

```python
def _source_lifetime_shape_rank(variant: StructureVariant) -> int:
    if variant.axis != "source-lifetime":
        return 0
    if variant.status != "ok":
        return 4
    if variant.unscored_reason:
        return 4 if variant.unscored_reason == SCORE_CAP_UNSCORED_REASON else 3
    if variant.compile_status not in (None, "ok"):
        return 3
    structural = variant.metadata.get("structural")
    if not isinstance(structural, dict):
        return 3
    if structural.get("opcode_shape_preserved") is True:
        return 0
    if structural.get("opcode_shape_preserved") is False:
        return 2
    return 3
```

This keeps shape-breaking scored candidates visible ahead of failed/unscored
rows while still letting exact matches rank first. Do not let non-`ok` or
score-cap source-lifetime rows use the best shape bucket. A compile-ok candidate
without structural/checkdiff metadata is still structurally unscored for this
axis and must rank behind an explicitly scored shape-breaking candidate.

In `_structural_with_deltas`, add:

```python
if "opcode_similarity" in candidate:
    try:
        structural["opcode_shape_preserved"] = float(candidate["opcode_similarity"]) >= 1.0
    except (TypeError, ValueError):
        pass
```

- [ ] **Step 7: Verify Task 2 passes**

Run:

```bash
cd tools/melee-agent
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tests/search/test_structure.py \
  tests/search/test_structure_scoring.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 2**

Stage only:

```bash
git add tools/melee-agent/src/search/structure.py \
        tools/melee-agent/src/search/structure_scoring.py \
        tools/melee-agent/src/search/cli.py \
        tools/melee-agent/tests/search/test_structure.py \
        tools/melee-agent/tests/search/test_structure_scoring.py
git commit -m "Add source lifetime structure axis"
```

---

### Task 3: CLI Focus, Seed Smoke, And Issue Resolution

**Files:**
- Modify: `tools/melee-agent/src/cli/debug.py`
- Test: `tools/melee-agent/tests/test_pressure_explorer.py`
- Test: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [ ] **Step 1: Write failing CLI focus tests**

Add to `tests/test_pressure_explorer.py`:

```python
def test_lifetime_layout_cli_focuses_helper_inline_lifetime_probe_families(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE)
    source.write_text(textwrap.dedent("""\
        s32 fn_803AC7DC(CardState* state, s32 i)
        {
            s32 total = 0;
            total += fn_803AC634(state, i);
            if (total < (s32) fn_803AC634(state, i)) {
                total = (s32) fn_803AC634(state, i);
            }
            return total;
        }
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_803AC7DC",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--focus",
            "helper-inline-lifetime",
            "--max-probes",
            "4",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["focus"] == "helper-inline-lifetime"
    assert "repeated-helper-result-reuse" in {
        probe["operator"] for probe in payload["probes"]
    }
```

Add a CLI smoke assertion to `tests/search/test_cli_smoke.py` if the file has a
structure-search help test:

```python
def test_structure_search_help_mentions_source_lifetime_axis() -> None:
    result = runner.invoke(app, ["debug", "search", "structure", "--help"])
    assert result.exit_code == 0
    assert "source-lifetime" in result.stdout
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
cd tools/melee-agent
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tests/test_pressure_explorer.py::test_lifetime_layout_cli_focuses_helper_inline_lifetime_probe_families \
  tests/search/test_cli_smoke.py -q
```

Expected: focus or help text missing.

- [ ] **Step 3: Implement CLI focus**

In `debug.py`, update `_LIFETIME_LAYOUT_FOCUSES`:

```python
"helper-inline-lifetime": HELPER_INLINE_LIFETIME_OPERATORS,
```

Because `_LIFETIME_LAYOUT_FOCUSES` is module-level, import
`HELPER_INLINE_LIFETIME_OPERATORS` wherever the existing focus constants are
imported, or change focus resolution to a lazy helper that imports the constant
before constructing the mapping. Import `generate_source_lifetime_probes` inside
`mutate_lifetime_layout_cmd` unless a module-level import is simpler and does
not introduce a cycle.

When `focus == "helper-inline-lifetime"`, generate probes with:

```python
probes, family_summaries = generate_source_lifetime_probes(
    source_text,
    function,
    max_probes=max_probes,
)
```

Add `family_summaries` to JSON payload as `source_lifetime_families`.

For other focuses, keep the existing `generate_lifetime_layout_probes` path.

- [ ] **Step 4: Run focused CLI tests**

Run:

```bash
cd tools/melee-agent
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tests/test_pressure_explorer.py::test_lifetime_layout_cli_focuses_helper_inline_lifetime_probe_families \
  tests/test_pressure_explorer.py::test_lifetime_layout_cli_focuses_b4_tree_loop_probe_families \
  tests/search/test_cli_smoke.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Run command-level smoke checks**

Run:

```bash
cd tools/melee-agent
python -m src.cli debug search structure --help
python -m src.cli debug mutate lifetime-layout --help
```

Expected: both commands exit 0 and mention the new axis/focus.

- [ ] **Step 6: Run seed no-compile listings**

Run:

```bash
for fn in fn_803AC6B8 fn_803AC7DC fn_803ACD58 it_802A7384; do
  melee-agent debug search structure -f "$fn" --axis source-lifetime \
    --no-score --max-candidates 12 --json > "/tmp/source-lifetime-$fn.json"
  python - <<PY
import json
p=json.load(open("/tmp/source-lifetime-$fn.json"))
print("$fn", p["stop_condition"]["kind"], len(p["variants"]))
assert p["axes"][0]["axis"] == "source-lifetime"
assert p["axes"][0]["status"] in {"evaluated", "blocked"}
assert p["axes"][0].get("metadata", {}).get("families")
PY
done
```

Expected: each seed returns an evaluated or blocked source-lifetime axis with
concrete family summaries. At least one of `fn_803AC7DC` or `fn_803ACD58` should
show a targeted operator in `variants`.

- [ ] **Step 7: Run bounded live scoring smoke**

Run:

```bash
for fn in fn_803AC6B8 fn_803AC7DC fn_803ACD58 it_802A7384; do
  melee-agent debug search structure -f "$fn" --axis source-lifetime \
    --max-candidates 3 --score-timeout 120 --json > "/tmp/source-lifetime-score-$fn.json"
  python - <<PY
import json
p=json.load(open("/tmp/source-lifetime-score-$fn.json"))
axis = p["axes"][0]
print("$fn", p["stop_condition"]["kind"], axis.get("status"), axis.get("reason"))
families = axis.get("metadata", {}).get("families", [])
assert families
if axis.get("status") == "blocked":
    assert axis.get("blocker")
    assert axis.get("reason")
    assert not p["variants"]
else:
    assert p["variants"]
    assert any("compile_status" in row for row in p["variants"])
    assert any(
        row.get("compile_status") == "ok"
        or row.get("unscored_reason")
        or row.get("status") != "ok"
        for row in p["variants"]
    )
PY
done
```

Expected: every reviewed seed produces retained scored rows or explicit
compile/checkdiff/no-safe-source/no-improvement reasons, with family summaries
that explain any blocked targeted operators.

- [ ] **Step 8: Run full focused test set**

Run:

```bash
cd tools/melee-agent
PYTEST_ADDOPTS=--no-cov python -m pytest \
  tests/test_pressure_explorer.py \
  tests/search/test_structure.py \
  tests/search/test_structure_scoring.py \
  tests/search/test_cli_smoke.py -q
python -m py_compile \
  src/mwcc_debug/pressure_explorer.py \
  src/search/structure.py \
  src/search/structure_scoring.py \
  src/search/cli.py \
  src/cli/debug.py
cd /Users/mike/code/melee
git diff --check
```

Expected: all tests and checks pass.

- [ ] **Step 9: Commit Task 3**

Stage only:

```bash
git add tools/melee-agent/src/cli/debug.py \
        tools/melee-agent/tests/test_pressure_explorer.py \
        tools/melee-agent/tests/search/test_cli_smoke.py
git commit -m "Wire source lifetime helper focus"
```

If Task 3 includes source changes from Task 1 or Task 2 because the worker kept
the patch atomic, stage the exact touched tooling files and keep unrelated
`src/sysdolphin/baselib/hsd_3B34.c` unstaged.

- [ ] **Step 10: Resolve issue #444 only after verification and commit**

If seed smoke satisfies the reviewed stop condition for all four #444 seed
functions, run:

```bash
melee-agent issue resolve 444 --note "fixed in <commit>: added source-lifetime structure-search axis with targeted helper-inline/source-lifetime probes, real-TU scoring, opcode-shape metadata, and seed smoke coverage"
```

Do not resolve #439.

- [ ] **Step 11: Refresh editable install**

After CLI changes are committed, run from `/Users/mike/code/melee`:

```bash
python -m pip install -e tools/melee-agent
cd /tmp
python - <<'PY'
import src.cli
import src.search.structure
print(src.cli.__file__)
print(src.search.structure.__file__)
PY
/opt/homebrew/bin/melee-agent issue list --status open
```

Expected: imports point at `/Users/mike/code/melee/tools/melee-agent/src`.
