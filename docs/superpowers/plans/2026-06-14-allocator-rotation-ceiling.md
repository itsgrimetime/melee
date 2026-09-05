# Allocator Rotation Ceiling Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conservative read-only `debug solve allocator-ceiling` command that classifies exhausted allocator-rotation evidence as actionable, bounded, incomplete, or practical ceiling.

**Architecture:** Put all verdict logic in a pure `mwcc_debug.allocator_ceiling` helper, then keep the Typer command thin: load JSON evidence files, validate function scope, call the helper, print text/JSON, and map status to existing solve-style exit codes. Tests drive the helper first, then the CLI.

**Tech Stack:** Python 3.11, Typer, pytest, existing `src.cli.debug.solve_app` command group.

---

## File Structure

- Create `tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`: pure evidence flattening, function-scope validation, verdict classification, and text rendering helpers.
- Create `tools/melee-agent/tests/test_allocator_ceiling.py`: helper unit tests and `CliRunner` CLI tests with synthetic #704-style JSON.
- Modify `tools/melee-agent/src/cli/debug/__init__.py`: register `debug solve allocator-ceiling`, load evidence JSON files, call the helper, and map status to exit codes.
- Modify `docs/CAPABILITIES.md`: regenerate or minimally update the command inventory after CLI registration if the inventory generator changes it.

### Task 1: Classifier Tests

**Files:**
- Create: `tools/melee-agent/tests/test_allocator_ceiling.py`

- [ ] **Step 1: Write the failing helper tests**

Create `tools/melee-agent/tests/test_allocator_ceiling.py` with these tests:

```python
import json

import pytest

from src.mwcc_debug.allocator_ceiling import (
    EvidenceFormatError,
    EvidenceFunctionMismatch,
    classify_allocator_ceiling,
    flatten_evidence_items,
)


def _solve_delta(function="fn_test"):
    return {
        "function": function,
        "class_id": 0,
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": function,
            "blocker": "structurally-different-virtual",
            "missing_virtuals": [{"target_ig": 40}],
        },
    }


def _bare_delta(function="fn_test"):
    return {
        "kind": "node-set-delta",
        "function": function,
        "blocker": "structurally-different-virtual",
        "missing_virtuals": [{"target_ig": 40}],
    }


def _force_match(function="fn_test"):
    return {
        "function": function,
        "force_vector_verify": {
            "ran": True,
            "union": {"status": "match", "returncode": 0},
        },
    }


def _node_wrong(function="fn_test"):
    return {
        "function": function,
        "status": "exhausted",
        "wrong_register_exhausted": True,
        "objective_counts": {"wrong-register": 6},
        "exhaustive": True,
    }


def _transform_negative(function="fn_test"):
    return {
        "function": function,
        "validation_summary": {
            "stop_condition": "exhausted-negative-evidence",
            "evaluated_probes": 6,
            "remaining_probe_ids": [],
            "outcomes": {"negative-evidence": 6},
        },
        "node_set_delta_summary": {
            "provided": True,
            "missing_count": 3,
            "bindable_count": 2,
            "skipped_count": 1,
            "omitted_count": 0,
        },
    }


def test_practical_ceiling_requires_all_negative_proofs():
    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "target-only-allocator-rotation"
    assert result["source_shape_exhausted"] is True
    assert result["wrong_register_exhausted"] is True
    assert result["node_set_delta"]["blocker"] == "structurally-different-virtual"
    assert result["force_vector"]["union_status"] == "match"
    assert result["exit_code"] == 3


def test_positive_proof_wins_over_negative_evidence():
    improved = dict(_node_wrong(), status="improved", best_checkdiff_delta=0.25)

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), improved, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    assert result["positive_proofs"]
    assert result["exit_code"] == 0


def test_bounded_transform_omitted_probe_blocks_ceiling():
    transform = _transform_negative()
    transform["node_set_delta_summary"]["omitted_count"] = 1

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), transform],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "transform-corpus omitted 1 node-set probe" in result["bounded_reasons"]
    assert result["exit_code"] == 4


def test_skipped_unbindable_transform_evidence_does_not_block_ceiling():
    transform = _transform_negative()
    transform["node_set_delta_summary"]["skipped_count"] = 2

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), transform],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["skipped_source_evidence_count"] == 2


def test_missing_force_vector_is_incomplete_not_ceiling():
    result = classify_allocator_ceiling(
        [_solve_delta(), _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert "force-phys verification with union status match" in result["missing_evidence"]
    assert result["exit_code"] == 3


def test_force_vector_no_match_is_incomplete():
    force = _force_match()
    force["force_vector_verify"]["union"]["status"] = "no_match"

    result = classify_allocator_ceiling(
        [_solve_delta(), force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["union_status"] == "no_match"
    assert "force-phys verification with union status match" in result["missing_evidence"]


def test_function_mismatch_rejected_in_nested_payload():
    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling(
            [_solve_delta("other_fn"), _force_match(), _node_wrong()],
            function="fn_test",
        )


def test_bare_node_set_delta_payload_counts_as_required_delta():
    result = classify_allocator_ceiling(
        [_bare_delta(), _force_match(), _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["node_set_delta"]["function"] == "fn_test"


def test_bounded_candidate_limit_blocks_ceiling():
    node = dict(_node_wrong(), stop_reason="candidate-limit")

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), node, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "candidate-limit" in " ".join(result["bounded_reasons"])
    assert result["exit_code"] == 4


def test_bounded_budget_blocks_ceiling():
    node = dict(_node_wrong(), stop_condition={"kind": "budget-exhausted"})

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), node, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "budget-exhausted" in " ".join(result["bounded_reasons"])


@pytest.mark.parametrize("union_status", ["inconclusive", "timeout", "failed"])
def test_force_vector_non_match_statuses_are_incomplete(union_status):
    force = _force_match()
    force["force_vector_verify"]["union"]["status"] = union_status

    result = classify_allocator_ceiling(
        [_solve_delta(), force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["union_status"] == union_status


def test_function_mismatch_rejected_in_summary_payload():
    transform = _transform_negative()
    transform["validation_summary"]["function"] = "other_fn"

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling(
            [_solve_delta(), _force_match(), _node_wrong(), transform],
            function="fn_test",
        )


def test_flatten_rejects_invalid_scalar_evidence():
    with pytest.raises(EvidenceFormatError):
        flatten_evidence_items([123])


def test_flatten_rejects_invalid_scalar_inside_list():
    with pytest.raises(EvidenceFormatError):
        flatten_evidence_items([[{"function": "fn_test"}, "bad"]])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_allocator_ceiling.py
```

Expected: fail with `ModuleNotFoundError: No module named 'src.mwcc_debug.allocator_ceiling'`.

- [ ] **Step 3: Commit after implementation task, not now**

Do not commit failing tests alone unless the implementation is delayed. The next task supplies the module.

### Task 2: Pure Classifier Module

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`
- Test: `tools/melee-agent/tests/test_allocator_ceiling.py`

- [ ] **Step 1: Implement the pure helper**

Create `tools/melee-agent/src/mwcc_debug/allocator_ceiling.py`:

```python
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class EvidenceFunctionMismatch(ValueError):
    """Raised when evidence names a function different from the requested one."""


class EvidenceFormatError(ValueError):
    """Raised when an evidence payload is not a JSON object or list of objects."""


def flatten_evidence_items(items: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, list):
            out.extend(flatten_evidence_items(item))
        elif isinstance(item, Mapping):
            out.append(dict(item))
        else:
            raise EvidenceFormatError(
                "evidence must be a JSON object or a list of JSON objects"
            )
    return out


def classify_allocator_ceiling(
    evidence: Iterable[Mapping[str, Any]],
    *,
    function: str,
) -> dict[str, Any]:
    items = flatten_evidence_items(evidence)
    _validate_function_scope(items, function=function)

    positive = _positive_proofs(items)
    bounded = _bounded_reasons(items)
    node_delta = _node_set_delta(items)
    force_vector = _force_vector_status(items)
    wrong_register = _wrong_register_exhausted(items)
    transform_exhausted = _transform_exhausted(items)
    skipped_count = _skipped_source_evidence_count(items)

    missing: list[str] = []
    if node_delta is None:
        missing.append("solve-coloring structurally-different-virtual node_set_delta")
    if force_vector.get("union_status") != "match":
        missing.append("force-phys verification with union status match")
    if not wrong_register:
        missing.append("node-set-split exhaustive all-wrong-register evidence")
    if not transform_exhausted:
        missing.append("transform-corpus exhausted negative validation evidence")

    if positive:
        status = "actionable"
        reason = "positive-proof"
        exit_code = 0
    elif bounded:
        status = "bounded"
        reason = "bounded-evidence"
        exit_code = 4
    elif not missing:
        status = "practical-ceiling"
        reason = "target-only-allocator-rotation"
        exit_code = 3
    else:
        status = "incomplete"
        reason = "missing-required-evidence"
        exit_code = 3

    return {
        "function": function,
        "status": status,
        "terminal_reason": reason,
        "exit_code": exit_code,
        "positive_proofs": positive,
        "source_shape_exhausted": bool(transform_exhausted),
        "node_set_delta": node_delta,
        "force_vector": force_vector,
        "wrong_register_exhausted": bool(wrong_register),
        "bounded_reasons": bounded,
        "missing_evidence": missing,
        "skipped_source_evidence_count": skipped_count,
        "evidence_count": len(items),
        "next_steps": _next_steps(
            function=function,
            status=status,
            bounded=bounded,
            missing=missing,
        ),
    }
```

Add the helper functions referenced above in the same module. Keep them private and schema-based:

```python
def _validate_function_scope(items: list[dict[str, Any]], *, function: str) -> None:
    for idx, item in enumerate(items):
        for name in _function_names(item):
            if name != function:
                raise EvidenceFunctionMismatch(
                    f"evidence item {idx} is for {name}, not {function}"
                )


def _function_names(item: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("function",):
        value = item.get(key)
        if isinstance(value, str) and value:
            names.add(value)
    for key in (
        "node_set_delta",
        "plan",
        "request",
        "validation_summary",
        "node_set_delta_summary",
        "force_vector_verify",
    ):
        nested = item.get(key)
        if isinstance(nested, Mapping):
            value = nested.get("function")
            if isinstance(value, str) and value:
                names.add(value)
    return names
```

Implement `_positive_proofs`, `_bounded_reasons`, `_node_set_delta`, `_force_vector_status`, `_wrong_register_exhausted`, `_transform_exhausted`, `_skipped_source_evidence_count`, and `_next_steps` to satisfy the Task 1 tests. Positive proof must detect:

```python
if item.get("byte_match") is True:
    ...
if item.get("status") == "improved":
    ...
if isinstance(item.get("best_checkdiff_delta"), (int, float)) and item["best_checkdiff_delta"] > 0:
    ...
if any(result.get("outcome") == "retained-source-improvement" for result in item.get("validation", []) or []):
    ...
if item.get("validation_summary", {}).get("stop_condition") == "retained-source-improvement":
    ...
```

Bounded evidence must detect `stop_reason in {"candidate-limit", "budget-exhausted"}`, `stop_condition.kind` with the same values, transform `remaining_probe_ids`, `node_set_delta_summary.omitted_count`, and `node_set_delta_summary.capped_count`.

`_node_set_delta` must accept both wrapper payloads (`{"node_set_delta": {...}}`) and bare payloads (`{"kind": "node-set-delta", "blocker": "structurally-different-virtual", ...}`).

Transform exhaustion is true only when `validation_summary.stop_condition == "exhausted-negative-evidence"`, `remaining_probe_ids` is empty, and no omitted/capped node-set probes are present.

- [ ] **Step 2: Run helper tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_allocator_ceiling.py
```

Expected: all Task 1 tests pass.

- [ ] **Step 3: Commit helper and tests**

Run:

```bash
git add tools/melee-agent/src/mwcc_debug/allocator_ceiling.py tools/melee-agent/tests/test_allocator_ceiling.py
git commit -m "feat: classify allocator rotation ceiling evidence"
```

### Task 3: CLI Wiring

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Modify: `tools/melee-agent/tests/test_allocator_ceiling.py`

- [ ] **Step 1: Add failing CLI tests**

Append these tests to `tools/melee-agent/tests/test_allocator_ceiling.py`:

```python
from typer.testing import CliRunner

from src.cli import debug as cli_debug


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_allocator_ceiling_cli_json_practical_ceiling(tmp_path):
    evidence_path = _write_json(
        tmp_path / "evidence.json",
        [_solve_delta(), _force_match(), _node_wrong(), _transform_negative()],
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
        "--json",
    ])

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["status"] == "practical-ceiling"
    assert payload["terminal_reason"] == "target-only-allocator-rotation"


def test_allocator_ceiling_cli_text_lists_next_steps(tmp_path):
    evidence_path = _write_json(tmp_path / "evidence.json", [_solve_delta()])
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert "allocator-ceiling fn_test: incomplete" in result.output
    assert "force-phys verification with union status match" in result.output


def test_allocator_ceiling_cli_rejects_mixed_function(tmp_path):
    evidence_path = _write_json(tmp_path / "evidence.json", [_solve_delta("other_fn")])
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
        "--json",
    ])

    assert result.exit_code == 2
    assert "not fn_test" in result.output


def test_allocator_ceiling_cli_accepts_multiple_evidence_files(tmp_path):
    solve_path = _write_json(tmp_path / "solve.json", _bare_delta())
    rest_path = _write_json(
        tmp_path / "rest.json",
        [_force_match(), _node_wrong(), _transform_negative()],
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(solve_path),
        "--evidence", str(rest_path),
        "--json",
    ])

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["status"] == "practical-ceiling"
    assert payload["evidence_count"] == 4


@pytest.mark.parametrize("payload", [123, [{"function": "fn_test"}, "bad"]])
def test_allocator_ceiling_cli_rejects_invalid_evidence_shape(tmp_path, payload):
    evidence_path = _write_json(tmp_path / "bad.json", payload)
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 2
    assert "evidence must be a JSON object" in result.output


def test_allocator_ceiling_cli_rejects_missing_file(tmp_path):
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(tmp_path / "missing.json"),
    ])

    assert result.exit_code == 2
    assert "could not read --evidence" in result.output
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_allocator_ceiling.py -k cli
```

Expected: fail because `allocator-ceiling` is not registered.

- [ ] **Step 3: Add the command**

In `tools/melee-agent/src/cli/debug/__init__.py`, add imports inside the command body and register near the existing `solve_coloring_cmd` / `solve_node_set_split_cmd` functions:

```python
@solve_app.command("allocator-ceiling")
def solve_allocator_ceiling_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function these evidence files target."),
    ],
    evidence: Annotated[
        list[Path],
        typer.Option(
            "--evidence",
            "-e",
            help="JSON evidence file from solve-coloring, node-set-split, plan-transforms, or force-phys-from-diff.",
        ),
    ],
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Classify exhausted allocator-rotation evidence without compiling."""
    from ...mwcc_debug.allocator_ceiling import (
        EvidenceFormatError,
        EvidenceFunctionMismatch,
        classify_allocator_ceiling,
        flatten_evidence_items,
        render_allocator_ceiling_text,
    )

    if not evidence:
        typer.echo("--evidence is required", err=True)
        raise typer.Exit(2)

    payloads: list[dict[str, Any]] = []
    for path in evidence:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            typer.echo(f"could not read --evidence {path}: {exc}", err=True)
            raise typer.Exit(2) from exc
        try:
            payloads.extend(flatten_evidence_items([loaded]))
        except EvidenceFormatError as exc:
            typer.echo(f"invalid --evidence {path}: {exc}", err=True)
            raise typer.Exit(2) from exc

    try:
        result = classify_allocator_ceiling(payloads, function=function)
    except (EvidenceFunctionMismatch, EvidenceFormatError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    if json_out:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(render_allocator_ceiling_text(result))
    raise typer.Exit(int(result["exit_code"]))
```

Add `render_allocator_ceiling_text(result: Mapping[str, Any]) -> str` to the helper module. It should print the status, terminal reason, bounded reasons, missing evidence, positive proofs, and next steps.

- [ ] **Step 4: Run CLI tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_allocator_ceiling.py
```

Expected: pass.

- [ ] **Step 5: Commit CLI wiring**

Run:

```bash
git add tools/melee-agent/src/cli/debug/__init__.py tools/melee-agent/src/mwcc_debug/allocator_ceiling.py tools/melee-agent/tests/test_allocator_ceiling.py
git commit -m "feat: add allocator ceiling solve command"
```

### Task 4: Capability And Smoke Coverage

**Files:**
- Modify if generated: `docs/CAPABILITIES.md`
- Test: `tools/melee-agent/tests/test_capabilities.py`

- [ ] **Step 1: Check command discovery**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli capabilities search "allocator rotation ceiling"
```

Expected: output includes `debug solve allocator-ceiling`.

- [ ] **Step 2: Regenerate capabilities only if the docs are stale**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli capabilities generate
```

If `docs/CAPABILITIES.md` changes, inspect the diff and include it in the next commit. If only generated timestamps or unrelated noise changes, do not commit unrelated churn.

- [ ] **Step 3: Add no separate capability test unless discovery fails**

If Step 1 fails to find the command, update `TASK_ALIASES` in `tools/melee-agent/src/cli/capabilities.py`:

```python
"allocator rotation ceiling": ["debug solve allocator-ceiling"],
"source shape exhausted": ["debug solve allocator-ceiling"],
```

Then add an assertion to `tools/melee-agent/tests/test_capabilities.py` using the existing search test style.

- [ ] **Step 4: Commit capability changes if any**

Run:

```bash
git status --short docs/CAPABILITIES.md tools/melee-agent/src/cli/capabilities.py tools/melee-agent/tests/test_capabilities.py
git add docs/CAPABILITIES.md tools/melee-agent/src/cli/capabilities.py tools/melee-agent/tests/test_capabilities.py
git commit -m "docs: surface allocator ceiling capability"
```

Skip this commit if there are no changes.

### Task 5: Final Verification And Issue Closure

**Files:**
- No new source files unless tests fail.

- [ ] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_allocator_ceiling.py tools/melee-agent/tests/search/solver/test_cli_solve.py tools/melee-agent/tests/test_node_set_split.py
```

Expected: all pass.

- [ ] **Step 2: Run static compile and diff checks**

Run:

```bash
python -m compileall -q tools/melee-agent/src
git diff --check
```

Expected: both pass.

- [ ] **Step 3: Run command-level smoke**

Use a temporary JSON evidence file and the implementation checkout's package path:

```bash
tmpdir=$(mktemp -d)
cat > "$tmpdir/evidence.json" <<'JSON'
[
  {
    "function": "mnDiagram2_Create",
    "node_set_delta": {
      "function": "mnDiagram2_Create",
      "kind": "node-set-delta",
      "blocker": "structurally-different-virtual",
      "missing_virtuals": [{"target_ig": 40}]
    }
  },
  {
    "function": "mnDiagram2_Create",
    "force_vector_verify": {
      "ran": true,
      "union": {"status": "match", "returncode": 0}
    }
  },
  {
    "function": "mnDiagram2_Create",
    "status": "exhausted",
    "wrong_register_exhausted": true,
    "objective_counts": {"wrong-register": 6},
    "exhaustive": true
  },
  {
    "function": "mnDiagram2_Create",
    "validation_summary": {
      "stop_condition": "exhausted-negative-evidence",
      "evaluated_probes": 6,
      "remaining_probe_ids": [],
      "outcomes": {"negative-evidence": 6}
    },
    "node_set_delta_summary": {
      "provided": true,
      "missing_count": 3,
      "bindable_count": 2,
      "skipped_count": 1,
      "omitted_count": 0
    }
  }
]
JSON
PYTHONPATH=tools/melee-agent python -m src.cli debug solve allocator-ceiling \
  -f mnDiagram2_Create \
  --evidence "$tmpdir/evidence.json" \
  --json
```

Expected: exit code `3` and JSON status `practical-ceiling`.

- [ ] **Step 4: Refresh editable install and run installed smoke**

Run from `/Users/mike/code/melee`:

```bash
python tools/worktree-doctor.py --fix
/opt/homebrew/bin/python3.11 - <<'PY'
import src.cli, pathlib
print(pathlib.Path(src.cli.__file__).resolve())
PY
```

Expected: the printed path is under `/Users/mike/code/melee/tools/melee-agent/src/cli/__init__.py`.

Then rerun the same synthetic smoke through `/opt/homebrew/bin/melee-agent`:

```bash
/opt/homebrew/bin/melee-agent debug solve allocator-ceiling \
  -f mnDiagram2_Create \
  --evidence "$tmpdir/evidence.json" \
  --json
```

Expected: exit code `3`, JSON status `practical-ceiling`, and the import-path check above points to the current `/Users/mike/code/melee` checkout.

- [ ] **Step 5: Resolve #704 only**

Run:

```bash
DECOMP_AGENT_ID=codex-issue-resolver-3-20260614e melee-agent issue resolve 704 --note "fixed allocator-ceiling classifier in <commit>; synthetic #704 evidence classifies as practical-ceiling"
```

Do not resolve #699 unless a real candidate byte-matches. Leave #618 open as canonical blocked/tracking.

## Self-Review

- Spec coverage: function-scope validation, force-vector proof requirement, bounded transform accounting, status schema, exit codes, CLI, tests, and smoke checks are covered.
- Placeholder scan: no deferred-work markers or unspecified error handling remain.
- Type consistency: helper returns plain JSON-serializable dictionaries; CLI consumes `exit_code` as an integer and renders text through the helper.
