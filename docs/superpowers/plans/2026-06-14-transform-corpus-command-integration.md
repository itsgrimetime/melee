# Transform Corpus Command Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make guarded transform-corpus probes usable from directed search, source-shape scoring commands, frame-transform search, and agent-facing docs/capabilities.

**Architecture:** Add a small shared adapter that validates family filters, caps and deduplicates generated `TransformProbe` objects, and converts them to the existing `LifetimeLayoutProbe` scoring shape while preserving transform metadata. Directed search uses a transform-corpus proposal helper after diagnosis-resolved anchors. Scoring commands keep current defaults and append transform-corpus probes only when `--include-transform-corpus` or `--transform-family` opts in.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `src.search.directed` and `src.mwcc_debug.pressure_explorer` modules.

---

## Files

- Create: `tools/melee-agent/src/search/directed/transform_probe_adapter.py`
- Modify: `tools/melee-agent/src/mwcc_debug/pressure_explorer/__init__.py`
- Modify: `tools/melee-agent/src/search/directed/run.py`
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`
- Modify: `.claude/capabilities-brief.md`
- Modify: `docs/CAPABILITIES.md`
- Modify: `tools/melee-agent/tests/search/directed/test_run_source_shape.py`
- Add or modify: `tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py`
- Modify: `tools/melee-agent/tests/test_pressure_explorer.py`
- Modify: `tools/melee-agent/tests/test_coalesce_search.py`
- Modify: `tools/melee-agent/tests/test_select_order_search.py`
- Modify: `tools/melee-agent/tests/test_frame_transform_search.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`
- Modify: `tools/melee-agent/tests/test_capabilities.py`

## Task 1: Failing Adapter Tests

**Files:**
- Create: `tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py`
- Create: `tools/melee-agent/src/search/directed/transform_probe_adapter.py`

- [ ] **Step 1: Add tests for transform probe conversion**

Add `test_transform_probe_adapter.py` with focused tests that construct
`TransformProbe` objects directly and assert conversion to `LifetimeLayoutProbe`:

```python
import pytest

from src.search.directed.transform_probe_adapter import (
    TransformProbeConfigError,
    adapted_transform_lifetime_probes,
    filter_transform_probes,
    normalize_transform_families,
    transform_probe_key,
    transform_probe_to_lifetime_probe,
)
from src.search.directed.transform_corpus import TransformProbe


def _probe(family_id: str = "assert_macro_expansion_shape") -> TransformProbe:
    return TransformProbe(
        probe_id=f"{family_id}@0",
        family_id=family_id,
        family_label="assert macro expansion",
        mutator_key="collapse_hsd_assert",
        semantic_risk="medium",
        source_region="assertion",
        expected_compiler_effect="change assert helper shape",
        generated_probe_form="collapse explicit __assert to HSD_ASSERTMSG",
        target_assignments=("ig1->r3",),
        span=(10, 20),
        payload={"line": 42},
        candidate_text="void demo(void) {}\n",
    )


def test_transform_probe_to_lifetime_probe_preserves_metadata() -> None:
    converted = transform_probe_to_lifetime_probe(_probe())
    data = converted.to_dict()

    assert converted.label == "transform-corpus-assert_macro_expansion_shape-0"
    assert converted.operator == "transform-corpus:assert_macro_expansion_shape"
    assert converted.source_text == "void demo(void) {}\n"
    assert converted.provenance["kind"] == "transform-corpus"
    assert converted.provenance["family_id"] == "assert_macro_expansion_shape"
    assert converted.provenance["mutator_key"] == "collapse_hsd_assert"
    assert converted.provenance["probe_id"] == "assert_macro_expansion_shape@0"
    assert converted.provenance["span"] == [10, 20]
    assert converted.provenance["payload"] == {"line": 42}
    assert data["probe_id"] == "assert_macro_expansion_shape@0"
    assert data["family_id"] == "assert_macro_expansion_shape"
    assert data["mutator_key"] == "collapse_hsd_assert"


def test_transform_probe_key_is_stable_and_not_at_suffixed() -> None:
    assert transform_probe_key(_probe()) == "transform-corpus:assert_macro_expansion_shape:0"


def test_filter_transform_probes_accepts_empty_filter() -> None:
    probes = (_probe("assert_macro_expansion_shape"), _probe("numeric_cast_shape"))

    assert filter_transform_probes(probes, families=()) == probes


def test_filter_transform_probes_accepts_requested_families() -> None:
    probes = (_probe("assert_macro_expansion_shape"), _probe("numeric_cast_shape"))

    filtered = filter_transform_probes(probes, families=("numeric_cast_shape",))

    assert [probe.family_id for probe in filtered] == ["numeric_cast_shape"]


def test_normalize_transform_families_rejects_unknown_family() -> None:
    with pytest.raises(TransformProbeConfigError):
        normalize_transform_families(["not_a_family"])


def test_normalize_transform_families_accepts_record_only_family() -> None:
    assert normalize_transform_families(["helper_shape"]) == ("helper_shape",)


def test_adapted_transform_lifetime_probes_caps_and_dedupes() -> None:
    duplicate = _probe("numeric_cast_shape")
    probes = (_probe("assert_macro_expansion_shape"), duplicate, duplicate)

    converted = adapted_transform_lifetime_probes(
        probes,
        families=(),
        max_probes=2,
    )

    assert [probe.provenance["family_id"] for probe in converted] == [
        "assert_macro_expansion_shape",
    ]
```

- [ ] **Step 2: Add a stub adapter module so imports fail on missing functions**

Create `transform_probe_adapter.py` with no implementations beyond imports if needed:

```python
"""Adapters for using transform-corpus probes in source scoring commands."""
```

- [ ] **Step 3: Run the adapter tests and confirm failure**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py -q
```

Expected: failure because `filter_transform_probes` and
`transform_probe_to_lifetime_probe` are not implemented.

## Task 2: Implement The Shared Adapter

**Files:**
- Modify: `tools/melee-agent/src/search/directed/transform_probe_adapter.py`
- Modify: `tools/melee-agent/src/mwcc_debug/pressure_explorer/__init__.py`

- [ ] **Step 1: Implement conversion and filtering**

Implement:

```python
from __future__ import annotations

from collections.abc import Iterable
import re

from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe
from src.search.directed.transform_corpus import DEFAULT_TRANSFORM_FAMILIES, TransformProbe


class TransformProbeConfigError(ValueError):
    """Raised when transform-corpus command options are invalid."""


_VALID_FAMILY_IDS = frozenset(family.family_id for family in DEFAULT_TRANSFORM_FAMILIES)


def _probe_ordinal(probe: TransformProbe) -> str:
    if "@" in probe.probe_id:
        return probe.probe_id.rsplit("@", 1)[1]
    return "0"


def normalize_transform_families(values: Iterable[str] | None) -> tuple[str, ...]:
    families: list[str] = []
    for value in values or ():
        for item in str(value).split(","):
            family = item.strip()
            if family:
                if family not in _VALID_FAMILY_IDS:
                    raise TransformProbeConfigError(
                        f"unknown transform family {family!r}; inspect "
                        "`melee-agent debug search plan-transforms` for known families"
                    )
                families.append(family)
    return tuple(dict.fromkeys(families))


def filter_transform_probes(
    probes: Iterable[TransformProbe],
    *,
    families: Iterable[str] | None,
) -> tuple[TransformProbe, ...]:
    requested = frozenset(normalize_transform_families(families))
    if not requested:
        return tuple(probes)
    return tuple(probe for probe in probes if probe.family_id in requested)


def transform_probe_key(probe: TransformProbe) -> str:
    return f"transform-corpus:{probe.family_id}:{_probe_ordinal(probe)}"


def _safe_probe_label(probe: TransformProbe) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", probe.probe_id)
    return f"transform-corpus-{stem}"


def transform_probe_to_lifetime_probe(probe: TransformProbe) -> LifetimeLayoutProbe:
    return LifetimeLayoutProbe(
        label=_safe_probe_label(probe),
        operator=f"transform-corpus:{probe.family_id}",
        description=(
            f"{probe.family_label}: {probe.generated_probe_form}; "
            f"expected effect: {probe.expected_compiler_effect}"
        ),
        source_text=probe.candidate_text,
        provenance={
            "kind": "transform-corpus",
            "probe_id": probe.probe_id,
            "family_id": probe.family_id,
            "family_label": probe.family_label,
            "mutator_key": probe.mutator_key,
            "semantic_risk": probe.semantic_risk,
            "source_region": probe.source_region,
            "expected_compiler_effect": probe.expected_compiler_effect,
            "generated_probe_form": probe.generated_probe_form,
            "target_assignments": list(probe.target_assignments),
            "span": list(probe.span),
            "payload": dict(probe.payload),
        },
    )


def adapted_transform_lifetime_probes(
    probes: Iterable[TransformProbe],
    *,
    families: Iterable[str] | None,
    max_probes: int,
) -> list[LifetimeLayoutProbe]:
    filtered = filter_transform_probes(probes, families=families)
    out: list[LifetimeLayoutProbe] = []
    seen_text: set[str] = set()
    for probe in filtered:
        if probe.candidate_text in seen_text:
            continue
        seen_text.add(probe.candidate_text)
        out.append(transform_probe_to_lifetime_probe(probe))
        if len(out) >= max(0, max_probes):
            break
    return out
```

In `LifetimeLayoutProbe.to_dict()`, add:

```python
        if self.provenance and self.provenance.get("kind") == "transform-corpus":
            for key in ("probe_id", "family_id", "mutator_key"):
                if key in self.provenance:
                    data[key] = self.provenance[key]
```

- [ ] **Step 2: Run adapter tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py -q
```

Expected: all tests pass.

## Task 3: Directed Search Proposal Tests

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_run_source_shape.py`
- Modify: `tools/melee-agent/src/search/directed/run.py`

- [ ] **Step 1: Add tests for transform-corpus fallback**

Add tests that call `_source_shape_proposal` with a fixture source covering at
least two transform families, including one of the newly mined families. Use an
empty proof vector and assert the proposal key/provenance is transform-corpus
tagged:

```python
def test_source_shape_proposal_uses_transform_corpus_fallback() -> None:
    src = '''
void target(void)
{
    int x;
    x = 1;
    x = 2;
}
'''

    key, anchor, meta = _source_shape_proposal(
        src,
        frozenset(),
        function="target",
        unit="melee/test/target",
        force_phys={},
    )

    assert key.startswith("transform-corpus:")
    assert meta["source_shape"] is True
    assert meta["transform_corpus"] is True
    assert meta["proof_vector_planned"] is True
    assert meta["probe"]["family_id"]
    assert meta["candidate_text"] != src
```

Add a second test that passes the returned key in `tried` and asserts the next
proposal has a different key or returns `None`.

- [ ] **Step 2: Add test for diagnosis allow-list preservation**

Keep the existing diagnosis-resolved tests for `_source_shape_proposal` passing
by changing assertions only where metadata intentionally gains transform
fields. Existing expected metadata for old source-shape candidates should now
come from transform-corpus metadata, not `{"source_shape": True}` only.

- [ ] **Step 3: Run directed source-shape tests and confirm failure**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/directed/test_run_source_shape.py -q
```

Expected: failure because `_source_shape_proposal` does not accept `unit` or
`force_phys`, and still uses `_SOURCE_SHAPE_LEVER_ORDER`.

## Task 4: Implement Directed Search Fallback

**Files:**
- Modify: `tools/melee-agent/src/search/directed/run.py`

- [ ] **Step 1: Replace `_SOURCE_SHAPE_LEVER_ORDER` fallback with transform probes**

Change `_source_shape_proposal` to accept `unit` and `force_phys`, call
`generate_transform_probes`, and return metadata with `candidate_text`:

```python
def _source_shape_proposal(
    source_text: str,
    tried: frozenset,
    *,
    function: str | None = None,
    unit: str | None = None,
    force_phys: dict[int, int] | None = None,
):
    if function is None or unit is None:
        return None
    from src.search.directed.transform_corpus import generate_transform_probes
    from src.search.directed.transform_probe_adapter import transform_probe_key

    for probe in generate_transform_probes(
        source_text,
        function=function,
        unit=unit,
        force_phys=force_phys or {},
        max_per_family=3,
    ):
        key = transform_probe_key(probe)
        if key in tried:
            continue
        return (
            key,
            None,
            {
                "source_shape": True,
                "transform_corpus": True,
                "proof_vector_planned": True,
                "candidate_text": probe.candidate_text,
                "probe": {
                    "probe_id": probe.probe_id,
                    "family_id": probe.family_id,
                    "family_label": probe.family_label,
                    "mutator_key": probe.mutator_key,
                    "semantic_risk": probe.semantic_risk,
                    "source_region": probe.source_region,
                    "expected_compiler_effect": probe.expected_compiler_effect,
                    "generated_probe_form": probe.generated_probe_form,
                    "target_assignments": list(probe.target_assignments),
                    "span": list(probe.span),
                    "payload": dict(probe.payload),
                },
            },
        )
    return None
```

- [ ] **Step 2: Teach the directed apply function to consume candidate text**

In `_run_live`, keep a local `candidate_text_by_key: dict[str, str] = {}`.
After `source_shape = _source_shape_proposal(...)`, if metadata contains
`candidate_text`, store it by key before returning. In `_apply_fn`, return that
candidate text for keys in the map before any `@` suffix stripping; otherwise
keep the existing mutator path.

- [ ] **Step 3: Pass `unit` and `proof_force_phys` to `_source_shape_proposal`**

Update the `_run_live` call to:

```python
source_shape = _source_shape_proposal(
    source_text,
    tried,
    function=function,
    unit=unit,
    force_phys=proof_force_phys or {},
)
```

- [ ] **Step 4: Run directed tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/search/directed/test_run_source_shape.py -q
```

Expected: all tests pass.

## Task 5: Scoring Command Regression Tests

**Files:**
- Modify: `tools/melee-agent/tests/test_pressure_explorer.py`
- Modify: `tools/melee-agent/tests/test_coalesce_search.py`
- Modify: `tools/melee-agent/tests/test_select_order_search.py`
- Modify: `tools/melee-agent/tests/test_frame_transform_search.py`

- [ ] **Step 1: Add lifetime-layout opt-in tests**

In `test_pressure_explorer.py`, add a Typer runner test that monkeypatches
pcdump/source helpers as nearby tests do, invokes:

```bash
debug mutate lifetime-layout -f demo --pcdump baseline.txt --source-file demo.c --no-compile-probes --include-transform-corpus --transform-family comma_operator_noop_expression_shape --json
```

Assert `payload["probes"]` includes an entry whose `operator` is
`transform-corpus:comma_operator_noop_expression_shape` and whose provenance
has `kind == "transform-corpus"`.

- [ ] **Step 2: Add coalesce-search opt-in tests**

In `test_coalesce_search.py`, add a test invoking `debug coalesce-search` with
`--no-compile-probes --include-transform-corpus --transform-family
comma_operator_noop_expression_shape --json` and assert the generated `probes`
contain transform provenance. Also assert the same command without
`--include-transform-corpus` does not include a `transform-corpus:` operator.

- [ ] **Step 3: Add select-order-search opt-in tests**

In `test_select_order_search.py`, add a test invoking `debug
select-order-search` with `--no-compile-probes --include-transform-corpus
--transform-family comma_operator_noop_expression_shape --json` and assert the
JSON `probes` array includes transform provenance and the default invocation
does not.

- [ ] **Step 4: Add frame-transform-search opt-in tests**

In `test_frame_transform_search.py`, add a no-live-compiler test invoking
`debug mutate frame-transform-search` with `--no-compile-probes
--include-transform-corpus --transform-family comma_operator_noop_expression_shape
--json`. Assert `payload["probes"]` includes transform metadata and
`payload["operator_filter"]` still reports frame operators separately.

- [ ] **Step 5: Run the four test files and confirm failure**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_pressure_explorer.py tools/melee-agent/tests/test_coalesce_search.py tools/melee-agent/tests/test_select_order_search.py tools/melee-agent/tests/test_frame_transform_search.py -q
```

Expected: failures because the CLI flags are not implemented.

## Task 6: Implement Scoring Command Flags And Probe Appends

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`

- [ ] **Step 1: Add shared local helper for CLI transform probes**

Near the existing CLI source-probe helpers, add:

```python
def _append_transform_corpus_probes(
    probes: list,
    *,
    source_text: str | None,
    function: str,
    unit: str | None,
    include: bool,
    families: list[str] | None,
    force_phys: str | None,
    max_probes: int,
    default_families: tuple[str, ...] = (),
) -> list:
    enabled = include or bool(families)
    if not enabled or source_text is None or len(probes) >= max_probes:
        return probes
    from ...search.directed.transform_probe_adapter import (
        TransformProbeConfigError,
        adapted_transform_lifetime_probes,
        normalize_transform_families,
        parse_transform_force_phys,
    )
    from ...search.directed.transform_corpus import generate_transform_probes

    try:
        requested_families = normalize_transform_families(families)
        if not requested_families and default_families:
            requested_families = default_families
        force_map = parse_transform_force_phys(force_phys)
    except TransformProbeConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc

    generated = generate_transform_probes(
        source_text,
        function=function,
        unit=unit or "unknown",
        force_phys=force_map,
        max_per_family=max(1, max_probes),
    )
    remaining = max(0, max_probes - len(probes))
    probes.extend(adapted_transform_lifetime_probes(
        generated,
        families=requested_families,
        max_probes=remaining,
    ))
    return probes
```

Add `parse_transform_force_phys` to the adapter so the debug CLI does not
import parser internals from `src.search.cli`.

- [ ] **Step 2: Add flags to `mutate_lifetime_layout_cmd`**

Add `include_transform_corpus`, `transform_family`, and
`transform_force_phys` Typer options. Help text must include
`transform-corpus` and `source-shape`. After existing lifetime probes are
generated, call `_append_transform_corpus_probes(...)` with `unit` derived from
`_find_unit_for_function`.

- [ ] **Step 3: Add flags to `debug_coalesce_search_cmd`**

Add the same options. Append transform probes after split-var and
lifetime-layout probes, using the already resolved `unit` when source is found.

- [ ] **Step 4: Add flags to `debug_select_order_search_cmd`**

Add the same options. Append transform probes for the single-probe path. Leave
beam-depth composition on existing lifetime probes unless a later issue asks
for transform-corpus beam expansion.

- [ ] **Step 5: Add flags to `mutate_frame_transform_search_cmd`**

Add the same options. Append transform probes after frame-directed and
lifetime fallback probes, respecting `max_probes`. Pass the frame default
family tuple:

```python
_FRAME_TRANSFORM_CORPUS_DEFAULT_FAMILIES = (
    "assignment_expression_temp_seed",
    "string_literal_data_blob_field_shape",
    "raw_pointer_offset_struct_field_shape",
    "comma_operator_noop_expression_shape",
    "numeric_cast_shape",
    "void_to_value_return_shape",
    "global_pointer_alias_shape",
    "empty_do_while_barrier",
)
```

- [ ] **Step 6: Run scoring command tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_pressure_explorer.py tools/melee-agent/tests/test_coalesce_search.py tools/melee-agent/tests/test_select_order_search.py tools/melee-agent/tests/test_frame_transform_search.py -q
```

Expected: all new tests pass.

## Task 7: Documentation, Catalog, And Capabilities Tests

**Files:**
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`
- Modify: `tools/melee-agent/tests/test_capabilities.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `docs/source-transform-catalog.md`
- Modify: `.claude/capabilities-brief.md`
- Modify: `docs/CAPABILITIES.md`

- [ ] **Step 1: Add catalog and capability failing tests**

In `test_source_transform_catalog.py`, assert the transform-corpus entry
`reused_by` includes `debug search directed`, `debug search run`, `debug
mutate lifetime-layout --include-transform-corpus`, `debug coalesce-search
--include-transform-corpus`, `debug select-order-search
--include-transform-corpus`, and `debug mutate frame-transform-search
--include-transform-corpus`.

In `test_capabilities.py`, extend `test_search_relevance_regression` with:

```python
assert "debug search plan-transforms" in [
    c.name for c in cap.run_search("transform corpus source-shape probes", REPO)
]
assert any(
    c.name in {"debug mutate lifetime-layout", "debug coalesce-search", "debug select-order-search"}
    for c in cap.run_search("transform corpus pressure coalesce select order", REPO)
)
assert "debug mutate frame-transform-search" in [
    c.name for c in cap.run_search("transform corpus frame source-shape", REPO)
]
```

- [ ] **Step 2: Run catalog/capability tests and confirm failure**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_source_transform_catalog.py tools/melee-agent/tests/test_capabilities.py -q
```

Expected: failure until docs/help/catalog text is updated.

- [ ] **Step 3: Update source transform catalog**

Update `source_transform_catalog.py` notes/reused_by to include the new
surfaces and opt-in flag names. Update `docs/source-transform-catalog.md` with
a short "Command availability" section and examples for planning, directed,
scoring, and frame-transform paths.

- [ ] **Step 4: Regenerate capabilities artifacts**

Run:

```bash
melee-agent capabilities generate
```

Expected: `.claude/capabilities-brief.md` and `docs/CAPABILITIES.md` update if
help text changed.

- [ ] **Step 5: Run catalog/capability tests**

Run:

```bash
python -m pytest tools/melee-agent/tests/test_source_transform_catalog.py tools/melee-agent/tests/test_capabilities.py -q
```

Expected: all tests pass.

## Task 8: Full Verification And Issue Resolution

**Files:**
- All modified files

- [ ] **Step 1: Run focused test set**

Run:

```bash
python -m pytest \
  tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py \
  tools/melee-agent/tests/search/directed/test_run_source_shape.py \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/test_coalesce_search.py \
  tools/melee-agent/tests/test_select_order_search.py \
  tools/melee-agent/tests/test_frame_transform_search.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  tools/melee-agent/tests/test_capabilities.py \
  -q
```

Expected: all tests pass.

- [ ] **Step 2: Run py_compile and whitespace checks**

Run:

```bash
python -m py_compile \
  tools/melee-agent/src/search/directed/transform_probe_adapter.py \
  tools/melee-agent/src/search/directed/run.py \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py
git diff --check
```

Expected: no output from `git diff --check`, no py_compile errors.

- [ ] **Step 3: Run CLI smoke checks**

Run help checks:

```bash
melee-agent debug mutate lifetime-layout --help | rg -- '--include-transform-corpus|--transform-family|--transform-force-phys'
melee-agent debug coalesce-search --help | rg -- '--include-transform-corpus|--transform-family|--transform-force-phys'
melee-agent debug select-order-search --help | rg -- '--include-transform-corpus|--transform-family|--transform-force-phys'
melee-agent debug mutate frame-transform-search --help | rg -- '--include-transform-corpus|--transform-family|--transform-force-phys'
melee-agent capabilities search "transform corpus source-shape probes"
```

Expected: each help command prints the new flags; capabilities search prints
`debug search plan-transforms` and at least one new scoring surface.

- [ ] **Step 4: Ask independent subagent for diff review**

Ask an independent Codex subagent to review the final diff for provenance loss,
changed default behavior, unbounded probe counts, and missing no-live-compiler
tests. Fix valid findings and re-run the focused tests.

- [ ] **Step 5: Commit, install, and resolve issues**

Run:

```bash
git status --short
git add docs/superpowers/specs/2026-06-14-transform-corpus-command-integration-design.md \
  docs/superpowers/plans/2026-06-14-transform-corpus-command-integration.md \
  tools/melee-agent/src/search/directed/transform_probe_adapter.py \
  tools/melee-agent/src/search/directed/run.py \
  tools/melee-agent/src/cli/debug/__init__.py \
  tools/melee-agent/src/mwcc_debug/source_transform_catalog.py \
  docs/source-transform-catalog.md \
  .claude/capabilities-brief.md \
  docs/CAPABILITIES.md \
  tools/melee-agent/tests/search/directed/test_transform_probe_adapter.py \
  tools/melee-agent/tests/search/directed/test_run_source_shape.py \
  tools/melee-agent/tests/test_pressure_explorer.py \
  tools/melee-agent/tests/test_coalesce_search.py \
  tools/melee-agent/tests/test_select_order_search.py \
  tools/melee-agent/tests/test_frame_transform_search.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  tools/melee-agent/tests/test_capabilities.py
git commit -m "Wire transform-corpus probes into search commands"
python -m pip install -e /Users/mike/code/melee/tools/melee-agent
```

Resolve #683, #684, #685, and #686 with the commit hash after verification.
Leave #682, #681, #671, and #618 open unless their external/tracking status
changes.
