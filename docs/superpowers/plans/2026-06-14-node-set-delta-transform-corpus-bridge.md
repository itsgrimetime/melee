# Node-set-delta Transform-corpus Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `debug search plan-transforms` consume `debug solve coloring` node-set-delta evidence and emit bounded, materialized `coloring_register_steering` probes through the normal transform-corpus validation path.

**Architecture:** Add an optional node-set-delta input to transform-corpus and the CLI. The transform-corpus layer reuses existing guarded `node_set_split` `CandidatePatch` generators, wraps their full patched source as `TransformProbe.candidate_text`, and reports skipped unbindable evidence. The CLI only reads JSON, passes it through, writes candidates using the existing payload helper, and exposes a top-level summary for all-unbindable deltas.

**Tech Stack:** Python 3, Typer CLI, pytest, existing `src.search.directed.transform_corpus`, `src.mwcc_debug.node_set_split`, and `src.search.cli`.

---

## File Structure

- Modify `tools/melee-agent/src/search/directed/transform_corpus.py`
  - Add node-set-delta probe generation helpers.
  - Add two materialized-candidate mutator keys to `coloring_register_steering` metadata.
  - Add optional `node_set_delta` parameter to `generate_transform_probes`.
  - Prioritize node-set-delta probes ahead of blind steering when evidence is supplied.
- Modify `tools/melee-agent/src/search/cli/__init__.py`
  - Add `--node-set-delta` to `plan-transforms`.
  - Load JSON payloads.
  - Attach top-level `node_set_delta_summary` when supplied.
- Modify `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
  - Add the two keys to `DIRECTED_MUTATOR_KEYS`.
  - Document that the new keys are materialized transform-corpus probes, not standalone `apply_mutator` dispatch functions.
- Modify `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
  - Unit-test generation, ordering, skipped evidence, and absent-node-set unchanged behavior.
- Modify `tools/melee-agent/tests/search/test_cli_smoke.py`
  - CLI-smoke `--node-set-delta`, probe writing, validation, and all-unbindable summary.
- Modify `tools/melee-agent/tests/test_source_transform_catalog.py`
  - Catalog metadata coverage.

## Task 1: Transform-corpus Node-set-delta Probe Generation

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`

- [ ] **Step 1: Add failing unit tests for single, coupled, skipped, and absent behavior**

Append these tests near the existing coloring-register-steering tests in `tools/melee-agent/tests/search/directed/test_transform_corpus.py`:

```python
def _node_set_delta_payload() -> dict:
    return {
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 36,
                "current_register": "r25",
                "desired_registers": ["r27"],
                "source": {"kind": "local", "expression": "gobj", "name": "gobj"},
                "source_action": "Split gobj before use.",
            },
            {
                "target_ig": 49,
                "current_register": "r29",
                "desired_registers": ["r25"],
                "source": {
                    "kind": "field-load",
                    "expression": "data->is_name_mode",
                    "base_var": "data",
                    "field_offset": 72,
                },
                "source_action": "Split data field load before use.",
            },
            {
                "target_ig": 51,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {"kind": "implicit-temp", "expression": "add r51,r45,r63"},
                "source_action": "Implicit temp cannot bind directly.",
            },
        ],
    }


def _node_set_delta_source() -> str:
    return (
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Data { int pad0; int is_name_mode; int selected; } Data;\n"
        "void mnDiagram2_Create(HSD_GObj* gobj, Data* data) {\n"
        "    int i;\n"
        "    int j;\n"
        "    int selected;\n"
        "    use(gobj);\n"
        "    selected = data->selected;\n"
        "    for (i = 0; i < 2; i++) {\n"
        "        sink(i, selected);\n"
        "    }\n"
        "    j = data->is_name_mode;\n"
        "    sink(gobj, data, j);\n"
        "}\n"
    )


def test_node_set_delta_none_preserves_existing_steering_order() -> None:
    source = _node_set_delta_source()

    without_arg = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 49: 25},
        max_per_family=3,
    )
    with_none = generate_transform_probes(
        source,
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 49: 25},
        node_set_delta=None,
        max_per_family=3,
    )

    assert [probe.mutator_key for probe in with_none] == [
        probe.mutator_key for probe in without_arg
    ]
    assert [probe.candidate_text for probe in with_none] == [
        probe.candidate_text for probe in without_arg
    ]


def test_node_set_delta_single_and_coupled_probes_precede_blind_steering() -> None:
    probes = generate_transform_probes(
        _node_set_delta_source(),
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 49: 25},
        node_set_delta=_node_set_delta_payload(),
        max_per_family=3,
    )

    steering = [
        probe for probe in probes if probe.family_id == "coloring_register_steering"
    ]
    assert steering
    assert steering[0].mutator_key == "steer_node_set_delta_coupled_split"
    assert {probe.mutator_key for probe in steering} >= {
        "steer_node_set_delta_split",
        "steer_node_set_delta_coupled_split",
    }
    assert all("node_set_delta" in probe.payload for probe in steering[:2])
    assert "ig36:r25->r27" in steering[0].target_assignments
    assert "ig49:r29->r25" in steering[0].target_assignments


def test_node_set_delta_reports_unbindable_missing_virtuals() -> None:
    probes = generate_transform_probes(
        _node_set_delta_source(),
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={36: 27, 49: 25, 51: 27},
        node_set_delta=_node_set_delta_payload(),
        max_per_family=3,
    )

    node_set = [
        probe for probe in probes
        if probe.mutator_key.startswith("steer_node_set_delta")
    ]
    assert node_set
    skipped = node_set[0].payload["node_set_delta"]["skipped_missing_virtuals"]
    assert any(entry["target_ig"] == 51 for entry in skipped)
    assert node_set[0].span[0] <= node_set[0].span[1]


def test_node_set_delta_all_unbindable_emits_no_materialized_probes() -> None:
    delta = {
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 51,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {"kind": "implicit-temp", "expression": "add r51,r45,r63"},
            }
        ],
    }

    probes = generate_transform_probes(
        _node_set_delta_source(),
        function="mnDiagram2_Create",
        unit="melee/mn/mndiagram2",
        force_phys={51: 27},
        node_set_delta=delta,
        max_per_family=3,
    )

    assert "steer_node_set_delta_split" not in {probe.mutator_key for probe in probes}
    assert "steer_node_set_delta_coupled_split" not in {
        probe.mutator_key for probe in probes
    }
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  -k 'node_set_delta'
```

Expected: FAIL because `generate_transform_probes` does not accept
`node_set_delta`.

- [ ] **Step 3: Implement node-set-delta helpers and metadata**

In `tools/melee-agent/src/search/directed/transform_corpus.py`, import the
needed types:

```python
from dataclasses import asdict
from typing import Any, Iterable, Mapping
```

Keep existing imports that already exist; only add missing names. Update the
`coloring_register_steering` `mutator_keys` tuple by appending:

```python
"steer_node_set_delta_coupled_split",
"steer_node_set_delta_split",
```

Add helpers near the register-steering helpers:

```python
def _desired_register_label(request) -> str:
    current = request.current_reg or "?"
    target = request.target_reg or "?"
    return f"ig{request.target_ig}:{current}->{target}"


def _merge_touched_ranges(
    ranges: tuple[tuple[int, int], ...],
    source_text: str,
) -> tuple[int, int]:
    valid = [
        (max(0, int(start)), min(len(source_text), int(end)))
        for start, end in ranges
        if int(start) <= int(end)
    ]
    if not valid:
        return (0, len(source_text))
    return (min(start for start, _end in valid), max(end for _start, end in valid))


def _missing_virtual_target_ig(entry: object) -> int | None:
    if not isinstance(entry, Mapping):
        return None
    try:
        return int(entry.get("target_ig"))
    except (TypeError, ValueError):
        return None


def _skipped_node_set_entries(delta: Mapping[str, Any], requests: list) -> list[dict]:
    bound = {request.target_ig for request in requests}
    skipped: list[dict] = []
    missing = delta.get("missing_virtuals")
    if not isinstance(missing, list):
        return skipped
    for entry in missing:
        target_ig = _missing_virtual_target_ig(entry)
        if target_ig is None or target_ig in bound:
            continue
        item = dict(entry) if isinstance(entry, Mapping) else {"raw": entry}
        item["blocked_reason"] = "no bindable source variable"
        skipped.append(item)
    return skipped


def _normalize_node_set_delta_for_transform(delta: Mapping[str, Any]) -> dict[str, Any]:
    nested = delta.get("node_set_delta")
    if isinstance(nested, Mapping):
        merged = dict(nested)
        for key in ("function", "class_id"):
            if key not in merged and key in delta:
                merged[key] = delta[key]
        return merged
    return dict(delta)
```

Add a generator helper:

```python
def _iter_node_set_delta_steering_probes(
    source_text: str,
    *,
    function: str,
    node_set_delta: Mapping[str, Any],
    remaining: int,
) -> list[tuple[Anchor, str, tuple[str, ...]]]:
    if remaining <= 0:
        return []
    from src.mwcc_debug.node_set_split import (
        generate_coupled_node_set_split_patches,
        generate_node_set_split_patches,
        requests_from_node_set_delta,
    )

    normalized = _normalize_node_set_delta_for_transform(node_set_delta)
    requests = requests_from_node_set_delta(normalized, source_text=source_text)
    skipped = _skipped_node_set_entries(normalized, requests)
    out: list[tuple[Anchor, str, tuple[str, ...]]] = []
    seen: set[str] = set()

    def append_patch(mutator_key: str, patch, reqs: list) -> None:
        if len(out) >= remaining or patch.patched_source in seen:
            return
        seen.add(patch.patched_source)
        span = _merge_touched_ranges(patch.touched_ranges, source_text)
        labels = tuple(_desired_register_label(req) for req in reqs)
        payload = {
            "span_text": source_text[span[0]:span[1]],
            "replacement_text": patch.patched_source[span[0]:span[1]],
            "strategy": mutator_key,
            "node_set_delta": {
                "requests": [asdict(req) for req in reqs],
                "skipped_missing_virtuals": skipped,
                "patch_candidate_id": patch.candidate_id,
                "patch_summary": patch.summary,
                "hunk": patch.hunk,
                "touched_ranges": [list(item) for item in patch.touched_ranges],
            },
        }
        out.append((
            Anchor(mutator_key=mutator_key, span=span, payload=payload),
            patch.patched_source,
            labels,
        ))

    coupled_requests = requests[:3]
    if len(coupled_requests) >= 2:
        for patch in generate_coupled_node_set_split_patches(
            source_text,
            function,
            coupled_requests,
            max_read_sites=2,
            max_per_ig=3,
            max_candidates=remaining,
        ):
            append_patch(
                "steer_node_set_delta_coupled_split",
                patch,
                coupled_requests,
            )
            if len(out) >= remaining:
                return out

    for request in requests:
        for patch in generate_node_set_split_patches(
            source_text,
            function,
            request,
            max_read_sites=2,
        ):
            append_patch("steer_node_set_delta_split", patch, [request])
            if len(out) >= remaining:
                return out
    return out
```

Adjust `generate_transform_probes` signature:

```python
def generate_transform_probes(
    source_text: str,
    *,
    function: str,
    unit: str,
    force_phys: Mapping[int, int],
    families: IterableABC[str] | None = None,
    max_per_family: int = 3,
    node_set_delta: Mapping[str, Any] | None = None,
) -> tuple[TransformProbe, ...]:
```

Before existing concrete steering loops, append node-set-delta probes:

```python
    if node_set_delta is not None and "coloring_register_steering" in allowed:
        remaining = max_per_family - counts.get("coloring_register_steering", 0)
        for anchor, candidate_text, target_assignments in _iter_node_set_delta_steering_probes(
            source_text,
            function=function,
            node_set_delta=node_set_delta,
            remaining=remaining,
        ):
            append_probe(
                family_id="coloring_register_steering",
                anchor=anchor,
                candidate_text=candidate_text,
                target_assignments_override=target_assignments,
            )
```

To support that call, extend the local `append_probe` helper with an optional
override:

```python
    def append_probe(
        *,
        family_id: str,
        anchor: Anchor,
        candidate_text: str,
        target_assignments_override: tuple[str, ...] | None = None,
    ) -> None:
        family = _FAMILY_BY_ID[family_id]
        region, target_assignments = _region_for_family(plan, family_id)
        if target_assignments_override is not None:
            target_assignments = target_assignments_override
        ...
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  -k 'node_set_delta or coloring_register_steering'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add tools/melee-agent/src/search/directed/transform_corpus.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py
git commit -m "feat: emit node-set-delta transform probes"
```

## Task 2: CLI `plan-transforms --node-set-delta` and Top-level Summary

**Files:**
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify: `tools/melee-agent/src/search/cli/__init__.py`

- [ ] **Step 1: Add failing CLI smoke tests**

Append near other `plan-transforms` smoke tests:

```python
def test_search_plan_transforms_accepts_node_set_delta_and_writes_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text(
        "typedef struct HSD_GObj HSD_GObj;\n"
        "typedef struct Data { int selected; int is_name_mode; } Data;\n"
        "void mnDiagram2_Create(HSD_GObj* gobj, Data* data) {\n"
        "    int selected;\n"
        "    selected = data->selected;\n"
        "    sink(gobj, selected);\n"
        "}\n"
    )
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "mnDiagram2_Create",
            "class_id": 0,
            "missing_virtuals": [
                {
                    "target_ig": 36,
                    "current_register": "r25",
                    "desired_registers": ["r27"],
                    "source": {"expression": "gobj", "name": "gobj"},
                }
            ],
        }
    }))
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "36:27",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "2",
            "--write-probes", str(probes_dir),
            "--validate-command",
            f"{sys.executable} -c \"print('match=false')\" {{candidate_path}}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["node_set_delta_summary"]["provided"] is True
    assert payload["node_set_delta_summary"]["bindable_count"] == 1
    probes = [
        probe for probe in payload["probes"]
        if probe["mutator_key"] == "steer_node_set_delta_split"
    ]
    assert probes
    assert Path(probes[0]["candidate_path"]).is_file()
    assert payload["validation_summary"]["stop_condition"] == "exhausted-negative-evidence"


def test_search_plan_transforms_reports_all_unbindable_node_set_delta(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram2.c"
    source.write_text("void mnDiagram2_Create(void) { sink(); }\n")
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 51,
                "current_register": "r29",
                "desired_registers": ["r27"],
                "source": {"kind": "implicit-temp", "expression": "add r51,r45,r63"},
            }
        ],
    }))

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram2_Create",
            "--unit", "melee/mn/mndiagram2",
            "--force-phys", "51:27",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "2",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    summary = payload["node_set_delta_summary"]
    assert summary["provided"] is True
    assert summary["bindable_count"] == 0
    assert summary["skipped_count"] == 1
    assert summary["skipped_missing_virtuals"][0]["target_ig"] == 51
```

- [ ] **Step 2: Run CLI smoke tests and verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -k 'node_set_delta'
```

Expected: FAIL because `--node-set-delta` is not a recognized option.

- [ ] **Step 3: Implement CLI option, loader, and summary**

In `tools/melee-agent/src/search/cli/__init__.py`, add helpers near
`_transform_plan_payload`:

```python
def _load_node_set_delta(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"could not read --node-set-delta: {exc}") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("--node-set-delta must contain a JSON object")
    return payload


def _node_set_delta_summary(payload: dict | None, probes) -> dict | None:
    if payload is None:
        return None
    nested = payload.get("node_set_delta")
    if isinstance(nested, dict):
        delta = nested
    else:
        delta = payload
    missing = delta.get("missing_virtuals")
    missing_count = len(missing) if isinstance(missing, list) else 0
    node_set_probes = [
        probe for probe in probes
        if str(getattr(probe, "mutator_key", "")).startswith("steer_node_set_delta")
    ]
    skipped: list[dict] = []
    for probe in node_set_probes:
        meta = probe.payload.get("node_set_delta")
        if isinstance(meta, dict):
            for entry in meta.get("skipped_missing_virtuals") or []:
                if isinstance(entry, dict) and entry not in skipped:
                    skipped.append(entry)
    if not node_set_probes and isinstance(missing, list):
        skipped = [
            dict(entry, blocked_reason="no bindable source variable")
            for entry in missing
            if isinstance(entry, dict)
        ]
    return {
        "provided": True,
        "missing_count": missing_count,
        "bindable_count": max(0, missing_count - len(skipped)),
        "skipped_count": len(skipped),
        "skipped_missing_virtuals": skipped,
    }
```

Add the Typer option to `plan_transforms_cmd`:

```python
    node_set_delta_path: Annotated[
        Optional[Path],
        typer.Option(
            "--node-set-delta",
            help="JSON node_set_delta payload from `debug solve coloring --json`.",
        ),
    ] = None,
```

Load and pass the payload:

```python
    node_set_delta = _load_node_set_delta(node_set_delta_path)
    ...
        probes = generate_transform_probes(
            source_path.read_text(),
            function=function,
            unit=unit,
            force_phys=force_phys_map,
            max_per_family=max_per_family,
            node_set_delta=node_set_delta,
        )
```

After `_transform_plan_payload(...)`, attach summary:

```python
    summary = _node_set_delta_summary(node_set_delta, probes)
    if summary is not None:
        payload["node_set_delta_summary"] = summary
```

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  -k 'node_set_delta or plan_transforms'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add tools/melee-agent/src/search/cli/__init__.py \
  tools/melee-agent/tests/search/test_cli_smoke.py
git commit -m "feat: pass node-set-delta to plan-transforms"
```

## Task 3: Catalog and Metadata Integration

**Files:**
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`

- [ ] **Step 1: Add failing catalog assertions**

In `test_coloring_register_steering_metadata_is_executable`, extend the expected
tuple:

```python
        "steer_node_set_delta_coupled_split",
        "steer_node_set_delta_split",
```

In `tools/melee-agent/tests/test_source_transform_catalog.py`, add:

```python
def test_plan_transforms_catalog_documents_node_set_delta_materialized_probes() -> None:
    entry = _entry("debug search plan-transforms / directed")

    assert "steer_node_set_delta_coupled_split" in entry.concrete_forms
    assert "steer_node_set_delta_split" in entry.concrete_forms
    assert any(
        "node_set_delta" in note and "materialized" in note
        for note in entry.notes
    )
```

- [ ] **Step 2: Run catalog tests and verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py::test_coloring_register_steering_metadata_is_executable \
  tools/melee-agent/tests/test_source_transform_catalog.py::test_plan_transforms_catalog_documents_node_set_delta_materialized_probes
```

Expected: FAIL until catalog lists the new concrete forms and note.

- [ ] **Step 3: Update catalog**

In `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`, append to
`DIRECTED_MUTATOR_KEYS`:

```python
    "steer_node_set_delta_coupled_split",
    "steer_node_set_delta_split",
```

Add this note in the plan-transforms catalog entry:

```python
            "node_set_delta materialized probes wrap guarded node-set-split CandidatePatch sources; they are transform-corpus probe keys, not standalone apply_mutator dispatch keys.",
```

- [ ] **Step 4: Run catalog tests and verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py::test_coloring_register_steering_metadata_is_executable \
  tools/melee-agent/tests/test_source_transform_catalog.py::test_plan_transforms_catalog_documents_node_set_delta_materialized_probes
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add tools/melee-agent/src/mwcc_debug/source_transform_catalog.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/test_source_transform_catalog.py
git commit -m "docs: catalog node-set-delta transform probes"
```

## Task 4: Verification, Installed CLI Smoke, and Issue Disposition

**Files:**
- No planned code edits.
- May update automation memory: `$CODEX_HOME/automations/issue-resolver/memory.md`

- [ ] **Step 1: Run focused test set**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py
```

Expected: PASS.

- [ ] **Step 2: Run compileall and whitespace check**

Run:

```bash
python -m compileall -q tools/melee-agent/src
git diff --check
```

Expected: both pass with no output from `git diff --check`.

- [ ] **Step 3: Run command-level plan-transforms smoke**

Create a temporary solve payload and run:

```bash
tmpdir=$(mktemp -d build/mwcc_debug_cache/issue699-node-set-delta-smoke.XXXXXX)
python - <<'PY' "$tmpdir/delta.json"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
    "node_set_delta": {
        "kind": "node-set-delta",
        "function": "mnDiagram2_Create",
        "class_id": 0,
        "missing_virtuals": [
            {
                "target_ig": 36,
                "current_register": "r25",
                "desired_registers": ["r27"],
                "source": {"expression": "gobj", "name": "gobj"},
            }
        ],
    }
}, indent=2))
PY
melee-agent debug search plan-transforms \
  --function mnDiagram2_Create \
  --unit melee/mn/mndiagram2 \
  --force-phys 36:27 \
  --node-set-delta "$tmpdir/delta.json" \
  --max-per-family 2 \
  --write-probes "$tmpdir/probes" \
  --validate-command "python -c \"print('match=false')\" {candidate_path}" \
  --json > "$tmpdir/result.json"
python - <<'PY' "$tmpdir/result.json"
import json, pathlib, sys
payload = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert payload["node_set_delta_summary"]["provided"] is True
assert any(p["mutator_key"].startswith("steer_node_set_delta") for p in payload["probes"])
print("node-set-delta smoke ok")
PY
```

Expected: prints `node-set-delta smoke ok`.

- [ ] **Step 4: Run real reporter validation for #699**

Use the reporter worktree solve output if available. Otherwise regenerate it:

```bash
reporter=/Users/mike/code/melee/.claude/worktrees/mndiagram-802427B4-investigation
tmpdir=$(mktemp -d "$reporter/build/mwcc_debug_cache/issue699-node-delta-validate.XXXXXX")
(cd "$reporter" && /opt/homebrew/bin/melee-agent debug solve coloring -f mnDiagram2_Create --json > "$tmpdir/solve.json") || true
(cd "$reporter" && /opt/homebrew/bin/melee-agent debug search plan-transforms \
  --function mnDiagram2_Create \
  --unit melee/mn/mndiagram2 \
  --force-phys 36:27,49:25,51:27 \
  --node-set-delta "$tmpdir/solve.json" \
  --max-per-family 6 \
  --write-probes "$tmpdir/probes" \
  --validate-command "/opt/homebrew/bin/melee-agent debug dump local {candidate_path} --unit-source src/melee/mn/mndiagram2.c --function mnDiagram2_Create --diff --no-cache-sync" \
  --json > "$tmpdir/result.json")
python - <<'PY' "$tmpdir/result.json"
import json, pathlib, sys
payload = json.loads(pathlib.Path(sys.argv[1]).read_text())
summary = payload.get("validation_summary") or {}
print(json.dumps({
    "probes": len(payload.get("probes", [])),
    "stop_condition": summary.get("stop_condition"),
    "outcomes": summary.get("outcomes"),
    "node_set_delta_summary": payload.get("node_set_delta_summary"),
}, indent=2))
PY
```

Expected: command completes. If validation reports byte match or retained
source improvement equivalent to byte match, resolve #699. If it reports only
negative evidence, add a note and release #699.

- [ ] **Step 5: Refresh editable install**

Because `tools/melee-agent` changed, run:

```bash
python tools/worktree-doctor.py --fix
/opt/homebrew/bin/melee-agent debug search plan-transforms --help >/tmp/issue699-help.txt
```

Expected: doctor/fix completes and `/opt/homebrew/bin/melee-agent` imports the
current master code.

- [ ] **Step 6: Resolve or release issue #699**

If real validation byte-matched:

```bash
commit=$(git rev-parse --short HEAD)
candidate_id=$(python - <<'PY' "$tmpdir/result.json"
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text())
for result in payload.get("validation", []):
    if result.get("outcome") == "retained-source-improvement":
        print(result.get("probe_id") or "unknown-probe")
        break
else:
    print("unknown-probe")
PY
)
DECOMP_AGENT_ID=codex-issue-resolver-3-20260614b melee-agent issue resolve 699 \
  --note "Fixed in ${commit}: plan-transforms now consumes node_set_delta and generated candidate ${candidate_id} reached byte_match."
```

If real validation did not byte-match:

```bash
commit=$(git rev-parse --short HEAD)
validation_note=$(python - <<'PY' "$tmpdir/result.json"
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text())
summary = payload.get("validation_summary") or {}
node = payload.get("node_set_delta_summary") or {}
count = sum(
    1 for probe in payload.get("probes", [])
    if str(probe.get("mutator_key", "")).startswith("steer_node_set_delta")
)
print(
    f"generated {count} node-set probes; "
    f"validation_summary={summary.get('stop_condition')}; "
    f"outcomes={summary.get('outcomes')}; "
    f"node_set_delta_summary={node}"
)
PY
)
DECOMP_AGENT_ID=codex-issue-resolver-3-20260614b melee-agent issue note 699 \
  --note "Implemented node-set-delta transform bridge in ${commit}. Real mnDiagram2_Create validation ${validation_note}; no byte_match, so #699 remains open."
DECOMP_AGENT_ID=codex-issue-resolver-3-20260614b melee-agent issue release 699
```

If `issue note` is unavailable, use `issue resolve` only for a byte-match and
otherwise `issue release 699` after recording the evidence in automation memory.

- [ ] **Step 7: Final git status**

Run:

```bash
git status --short --branch
git rev-parse --short HEAD
```

Expected: only unrelated pre-existing `.playwright-mcp/` may remain untracked.
