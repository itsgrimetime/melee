# Retail MWCC Backend/Register-Allocation Tracer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build exact retail GC/1.2.5n backend/register-allocation tracing under `melee-agent debug retro backend`, with versioned allocator facts, summaries, and retail-vs-debug fidelity reports.

**Architecture:** Extend the existing `tools/mwcc_retro` and `melee-agent debug retro` workflow. Land the consumer schema, fixture, normalizer, summaries, parity gate, verifier, and CLI first; then complete the GC/1.2.5n address/struct confidence map and gdb-side backend event collection behind hard validation gates. Retail GC/1.2.5n is authoritative; GC/1.1 remains a donor/regression input only.

**Tech Stack:** Python 3, Typer, pytest, retrowin32 gdb stub, stdlib JSON/dataclasses, existing `mwcc_debug` pcdump parsers, existing `tools/mwcc_retro` PE/table helpers.

---

## Scope Check

This is one subsystem: a retail backend/regalloc fact producer. The lifetime-pressure explorer is a separate consumer and must only depend on the normalized `functions[].regalloc.classes[]` allocator-facts subset, not raw gdb events.

## File Structure

Create:

- `tools/mwcc_retro/backend_schema.py`: schema constants, validation helpers, fixture load/write helpers for `backend-trace.v1.json`.
- `tools/mwcc_retro/backend_summary.py`: `regalloc-summary.txt` and `backend-summary.txt` generation from normalized traces.
- `tools/mwcc_retro/backend_fidelity.py`: normalized retail-vs-debug comparison and fidelity report serialization.
- `tools/mwcc_retro/backend_identity.py`: function identity resolution and collision-safe output paths.
- `tools/mwcc_retro/object_parity.py`: raw object-byte parity gate for normal retail path vs retrowin32.
- `tools/mwcc_retro/struct_map.py`: required backend/regalloc table keys, confidence validation, and struct-map serialization.
- `tools/mwcc_retro/backend_events.py`: JSONL event parsing and event-to-schema normalization helpers.
- `tools/mwcc_retro/backend_discovery.py`: address/operand extraction helpers for GC/1.2.5n backend map work.
- `tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json`: consumer-contract fixture.
- `tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl`: raw-event fixture for the normalizer.
- `tools/melee-agent/tests/test_retro_backend_schema.py`
- `tools/melee-agent/tests/test_retro_backend_summary.py`
- `tools/melee-agent/tests/test_retro_backend_fidelity.py`
- `tools/melee-agent/tests/test_retro_backend_identity.py`
- `tools/melee-agent/tests/test_retro_object_parity.py`
- `tools/melee-agent/tests/test_retro_struct_map.py`
- `tools/melee-agent/tests/test_retro_backend_events.py`
- `tools/melee-agent/tests/test_retro_backend_cli.py`

Modify:

- `tools/melee-agent/src/cli/debug/retro.py`: add `backend` and `verify-backend` commands, route `dump --phases backend --compiler 1.2.5n` through the same implementation, write new outputs.
- `tools/mwcc_retro/mwcc_retro_debugger.py`: add backend-trace mode, gdb event emission, and required invariant checks.
- `tools/mwcc_retro/port_table.py`: promote confidence-gated GC/1.2.5n backend entries from partial evidence into validated table entries only when proven.
- `tools/mwcc_retro/tables/gc_125n.json`: add validated backend/regalloc entries after discovery gates pass.
- `tools/mwcc_retro/README.md`
- `docs/mwcc-retro.md`
- `docs/mwcc-retro-usage.md`
- `.claude/skills/mwcc-retro/SKILL.md`
- `tools/melee-agent/tests/golden/debug_cli_help/debug__retro.txt`
- add new golden files for `debug__retro__backend.txt` and `debug__retro__verify-backend.txt`.

Run Python tests from `tools/melee-agent/`. Run build/checkdiff commands from the repo root `/Users/mike/.codex/worktrees/71b5/melee`.

---

### Task 0: Audit Existing Capabilities And Lock Reuse Boundary

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-retail-mwcc-backend-regalloc-tracer.md` only if the capability surface changes before execution.

- [ ] **Step 1: Run the audit-first capability search**

Run from repo root:

```bash
melee-agent capabilities search "retail mwcc backend register allocation tracer"
```

Expected output includes these existing capabilities:

```text
mwcc-debug
mwcc-inspect
mwcc-retro
debug suggest register-tiebreak
```

- [ ] **Step 2: Record what is reused**

Use these existing pieces:

- `mwcc-retro`: retrowin32 setup, gdb launcher shape, retail compiler table loading, frontend IRO tracing, existing GC/1.1 backend/regalloc trace shape, and current `debug retro dump` command plumbing.
- `mwcc-debug`: patched debug-DLL pcdump/colorgraph facts and existing parsers for the fidelity adapter.
- `mwcc-inspect`: context only for frontend IR/source attribution questions; do not duplicate its Windows inspector workflow.
- `debug suggest register-tiebreak`: downstream source-lever suggestion logic; do not duplicate tiebreak/source experiment ranking in this producer.

- [ ] **Step 3: Record what is new**

Build only the missing producer pieces:

- exact retail GC/1.2.5n backend/regalloc event collection;
- `backend-trace.v1.json` consumer schema and validator;
- `functions[].regalloc.classes[]` allocator-facts subset;
- `regalloc-summary.txt` and `backend-summary.txt`;
- raw object-byte parity gate for trusting retrowin32 output;
- retail-vs-debug fidelity reports that compare facts without treating legitimate divergence as command failure.

- [ ] **Step 4: Stop if a newer command already covers the target**

If the capability search lists an existing command that already emits exact retail GC/1.2.5n backend/regalloc facts with color decisions, blocked candidates, coalescing, simplify/select order, and a stable JSON schema, update this plan to extend that command instead of adding `debug retro backend`.

---

### Task 1: Consumer Schema And Minimal Fixture

**Files:**
- Create: `tools/mwcc_retro/backend_schema.py`
- Create: `tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json`
- Create: `tools/melee-agent/tests/test_retro_backend_schema.py`

- [ ] **Step 1: Write the consumer-contract fixture**

Create `tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json`:

```json
{
  "schema_version": "mwcc-retro-backend-trace.v1",
  "tool_version": "test",
  "compiler": {
    "family": "MWCC",
    "version": "GC/1.2.5n",
    "retail": true
  },
  "source": {
    "tu": "src/melee/test/unit.c",
    "function": "test_fn",
    "mwcc_command_hash": "sha256:fixture"
  },
  "functions": [
    {
      "name": "test_fn",
      "identity": {
        "requested": "test_fn",
        "canonical_name": "test_fn",
        "symbol_name": "test_fn",
        "source_name": "test_fn",
        "aliases": [],
        "source_file": "src/melee/test/unit.c"
      },
      "blocks": [
        {
          "id": "B0",
          "order": 0,
          "succ": ["B1"],
          "pred": [],
          "labels": ["L0"]
        },
        {
          "id": "B1",
          "order": 1,
          "succ": [],
          "pred": ["B0"],
          "labels": ["L1"]
        }
      ],
      "pcode": {
        "passes": [
          {
            "id": "before_register_coloring",
            "name": "BEFORE REGISTER COLORING",
            "instructions": [
              {
                "id": "p0",
                "block_id": "B0",
                "order": 0,
                "opcode": "mr",
                "operands": "r32,r3",
                "normalized": "mr v,arg0"
              },
              {
                "id": "p1",
                "block_id": "B0",
                "order": 1,
                "opcode": "addi",
                "operands": "r33,r32,4",
                "normalized": "addi v,v,imm"
              }
            ]
          }
        ],
        "instruction_identity_note": "instruction ids are stable only within this trace"
      },
      "regalloc": {
        "classes": [
          {
            "class_id": 0,
            "class_name": "gpr",
            "registers": {
              "physical_count": 32,
              "allocatable": [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 31, 30, 29, 28, 27],
              "initial_volatile": [3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
              "reserved": [0, 1, 2],
              "fixed": [
                {
                  "phys": 1,
                  "reason": "stack_pointer"
                },
                {
                  "phys": 2,
                  "reason": "toc"
                }
              ],
              "precolored": [
                {
                  "ig_id": 3,
                  "phys": 3,
                  "reason": "incoming_arg"
                }
              ],
              "nonvolatile_dispense_order": [31, 30, 29, 28, 27],
              "model_boundary": [
                {
                  "name": "LR",
                  "reason": "outside-v1-allocator-facts"
                }
              ]
            },
            "nodes": [
              {
                "ig_id": 32,
                "virtual": {
                  "kind": "r",
                  "number": 32
                },
                "first_def": {
                  "pass_id": "before_register_coloring",
                  "block_id": "B0",
                  "instruction_id": "p0",
                  "opcode": "mr",
                  "operands": "r32,r3",
                  "normalized": "mr v,arg0"
                },
                "source_attribution": {
                  "status": "attributed",
                  "symbol": "arg0",
                  "line": 10,
                  "confidence": "high"
                },
                "live": {
                  "blocks": ["B0", "B1"],
                  "intervals": [
                    {
                      "block_id": "B0",
                      "start": 0,
                      "end": 1
                    }
                  ],
                  "confidence": "observed"
                },
                "degree": 1,
                "flags": [],
                "coalesce": {
                  "root_ig_id": 32,
                  "aliases": [40]
                },
                "simplify_order": 1,
                "select_order": 1,
                "assigned_phys": 31,
                "spill": {
                  "spilled": false,
                  "reason": null
                },
                "color_status": "colored",
                "coalesced_into": null,
                "color_decision_ref": "gpr-c0"
              },
              {
                "ig_id": 33,
                "virtual": {
                  "kind": "r",
                  "number": 33
                },
                "first_def": {
                  "pass_id": "before_register_coloring",
                  "block_id": "B0",
                  "instruction_id": "p1",
                  "opcode": "addi",
                  "operands": "r33,r32,4",
                  "normalized": "addi v,v,imm"
                },
                "source_attribution": {
                  "status": "ambiguous",
                  "symbol": null,
                  "line": null,
                  "confidence": "low",
                  "candidates": ["tmp_a", "tmp_b"]
                },
                "live": {
                  "blocks": ["B0"],
                  "intervals": [
                    {
                      "block_id": "B0",
                      "start": 1,
                      "end": 1
                    }
                  ],
                  "confidence": "observed"
                },
                "degree": 1,
                "flags": [],
                "coalesce": {
                  "root_ig_id": 33,
                  "aliases": []
                },
                "simplify_order": 0,
                "select_order": 0,
                "assigned_phys": 30,
                "spill": {
                  "spilled": false,
                  "reason": null
                },
                "color_status": "colored",
                "coalesced_into": null,
                "color_decision_ref": "gpr-c1"
              },
              {
                "ig_id": 40,
                "virtual": {
                  "kind": "r",
                  "number": 40
                },
                "first_def": {
                  "pass_id": "before_register_coloring",
                  "block_id": "B0",
                  "instruction_id": "p0",
                  "opcode": "mr",
                  "operands": "r40,r32",
                  "normalized": "mr alias,root"
                },
                "source_attribution": {
                  "status": "unattributed",
                  "symbol": null,
                  "line": null,
                  "confidence": "unavailable"
                },
                "live": {
                  "blocks": ["B0"],
                  "intervals": [],
                  "confidence": "observed"
                },
                "degree": 0,
                "flags": ["coalesced_away"],
                "coalesce": {
                  "root_ig_id": 32,
                  "aliases": []
                },
                "simplify_order": null,
                "select_order": null,
                "assigned_phys": 31,
                "spill": {
                  "spilled": false,
                  "reason": null
                },
                "color_status": "coalesced_alias",
                "coalesced_into": 32,
                "color_decision_ref": null
              }
            ],
            "edges": [
              {
                "a": 32,
                "b": 33,
                "kind": "interference",
                "confidence": "observed",
                "provenance": "interferencegraph"
              }
            ],
            "coalesce": {
              "mappings": [
                {
                  "alias": 40,
                  "root": 32,
                  "root_phys": 31,
                  "confidence": "observed",
                  "provenance": "coalesce_alias"
                }
              ]
            },
            "non_allocatable_state": {
              "status": "model-boundary",
              "notes": ["CR/LR/CTR not modeled in v1 allocator facts"]
            },
            "simplify_order": [33, 32],
            "select_order": [33, 32],
            "color_decisions": [
              {
                "id": "gpr-c0",
                "ig_id": 32,
                "iter": 1,
                "assigned_phys": 31,
                "node_state_before_select": {
                  "precolored": false,
                  "coalesced": false,
                  "spill_marked": false,
                  "rematerialized": false
                },
                "reserved_or_precolored_filtered": [0, 1, 2],
                "available_phys_ordered": [3, 4, 5, 31, 30],
                "blocked_candidates": [
                  {
                    "phys": 3,
                    "reason": "interferer-assigned-phys",
                    "holder_ig_id": 33,
                    "holder_assigned_phys": 3,
                    "provenance": "interference_edge"
                  }
                ],
                "candidate_phys_ordered": [31, 30],
                "chosen_source": "nonvolatile_dispense",
                "volatile_pool_before": [3, 4, 5],
                "volatile_pool_after": [3, 4, 5, 31],
                "nonvolatile_dispense_before": {
                  "next": 31,
                  "remaining": [31, 30, 29]
                },
                "nonvolatile_dispense_after": {
                  "consumed": 31,
                  "remaining": [30, 29]
                },
                "tie_rule": "top_down_nonvolatile_dispense",
                "blocked_by": [
                  {
                    "ig_id": 33,
                    "phys": 3
                  }
                ],
                "decision_rule": "lowest_available_or_nonvolatile_dispense",
                "confidence": "observed",
                "provenance": "colorgraph"
              },
              {
                "id": "gpr-c1",
                "ig_id": 33,
                "iter": 0,
                "assigned_phys": 30,
                "node_state_before_select": {
                  "precolored": false,
                  "coalesced": false,
                  "spill_marked": false,
                  "rematerialized": false
                },
                "reserved_or_precolored_filtered": [0, 1, 2],
                "available_phys_ordered": [3, 4, 5, 31, 30],
                "blocked_candidates": [],
                "candidate_phys_ordered": [30],
                "chosen_source": "nonvolatile_dispense",
                "volatile_pool_before": [3, 4, 5],
                "volatile_pool_after": [3, 4, 5, 30],
                "nonvolatile_dispense_before": {
                  "next": 30,
                  "remaining": [30, 29]
                },
                "nonvolatile_dispense_after": {
                  "consumed": 30,
                  "remaining": [29]
                },
                "tie_rule": "top_down_nonvolatile_dispense",
                "blocked_by": [],
                "decision_rule": "lowest_available_or_nonvolatile_dispense",
                "confidence": "observed",
                "provenance": "colorgraph"
              }
            ]
          }
        ]
      }
    }
  ],
  "struct_map": {
    "schema_version": "mwcc-retro-struct-map.v1",
    "entries": []
  }
}
```

- [ ] **Step 2: Write failing schema tests**

Create `tools/melee-agent/tests/test_retro_backend_schema.py`:

```python
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_schema  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"


def test_minimal_backend_trace_fixture_validates():
    data = json.loads(FIXTURE.read_text())
    errors = backend_schema.validate_backend_trace(data)
    assert errors == []


def test_colored_node_without_decision_is_invalid():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    cls["nodes"][0]["color_decision_ref"] = None
    errors = backend_schema.validate_backend_trace(data)
    assert any("colored node 32 missing color_decision_ref" in e for e in errors)


def test_coalesced_alias_may_have_null_select_and_decision():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    alias = next(n for n in cls["nodes"] if n["ig_id"] == 40)
    assert alias["select_order"] is None
    assert alias["color_decision_ref"] is None
    errors = backend_schema.validate_backend_trace(data)
    assert errors == []


def test_color_decision_requires_pressure_fields():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision.pop("blocked_candidates")
    errors = backend_schema.validate_backend_trace(data)
    assert any("color decision gpr-c0 missing blocked_candidates" in e for e in errors)


def test_register_metadata_requires_initial_pool_and_boundaries():
    data = json.loads(FIXTURE.read_text())
    regs = data["functions"][0]["regalloc"]["classes"][0]["registers"]
    regs.pop("initial_volatile")
    regs.pop("model_boundary")
    errors = backend_schema.validate_backend_trace(data)
    assert any("registers missing initial_volatile" in e for e in errors)
    assert any("registers missing model_boundary" in e for e in errors)


@pytest.mark.parametrize("field", ["edges", "coalesce", "non_allocatable_state", "simplify_order", "select_order"])
def test_class_level_consumer_fields_are_required(field):
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    cls.pop(field)
    errors = backend_schema.validate_backend_trace(data)
    assert any(f"gpr missing {field}" in e for e in errors)


def test_duplicate_color_decision_ids_are_invalid():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    cls["color_decisions"].append(dict(cls["color_decisions"][0]))
    errors = backend_schema.validate_backend_trace(data)
    assert any("duplicate color decision id gpr-c0" in e for e in errors)


def test_color_decision_requires_id_and_provenance():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision.pop("id")
    decision.pop("provenance")
    errors = backend_schema.validate_backend_trace(data)
    assert any("color decision missing id" in e for e in errors)
    assert any("color decision <missing-id> missing provenance" in e for e in errors)


def test_color_decision_ig_must_match_colored_node_ref():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision["ig_id"] = 99
    errors = backend_schema.validate_backend_trace(data)
    assert any("colored node 32 decision gpr-c0 has ig_id 99" in e for e in errors)


def test_edge_and_coalesce_references_must_exist():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    cls["edges"][0]["b"] = 99
    cls["coalesce"]["mappings"][0]["root"] = 98
    errors = backend_schema.validate_backend_trace(data)
    assert any("edge references missing node 99" in e for e in errors)
    assert any("coalesce mapping references missing root 98" in e for e in errors)


def test_empty_register_metadata_is_invalid():
    data = json.loads(FIXTURE.read_text())
    regs = data["functions"][0]["regalloc"]["classes"][0]["registers"]
    regs["allocatable"] = []
    regs["initial_volatile"] = []
    regs["nonvolatile_dispense_order"] = []
    errors = backend_schema.validate_backend_trace(data)
    assert any("registers allocatable must be non-empty" in e for e in errors)
    assert any("registers initial_volatile must be non-empty" in e for e in errors)
    assert any("registers nonvolatile_dispense_order must be non-empty" in e for e in errors)
```

- [ ] **Step 3: Run the schema tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_schema.py -v
```

Expected: fail with `ImportError` or `AttributeError` because `backend_schema` does not exist yet.

- [ ] **Step 4: Implement schema validation**

Create `tools/mwcc_retro/backend_schema.py`:

```python
"""Schema helpers for mwcc-retro backend trace v1."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "mwcc-retro-backend-trace.v1"
STRUCT_MAP_SCHEMA_VERSION = "mwcc-retro-struct-map.v1"

REQUIRED_TOP = ("schema_version", "compiler", "source", "functions")
REQUIRED_REGISTER_FIELDS = (
    "physical_count",
    "allocatable",
    "initial_volatile",
    "reserved",
    "fixed",
    "precolored",
    "nonvolatile_dispense_order",
    "model_boundary",
)
REQUIRED_CLASS_FIELDS = (
    "class_id",
    "class_name",
    "registers",
    "nodes",
    "edges",
    "coalesce",
    "non_allocatable_state",
    "simplify_order",
    "select_order",
    "color_decisions",
)
REQUIRED_NODE_FIELDS = (
    "ig_id",
    "virtual",
    "first_def",
    "source_attribution",
    "live",
    "degree",
    "flags",
    "coalesce",
    "simplify_order",
    "select_order",
    "assigned_phys",
    "spill",
    "color_status",
    "coalesced_into",
    "color_decision_ref",
)
REQUIRED_COLORED_DECISION_FIELDS = (
    "id",
    "ig_id",
    "iter",
    "assigned_phys",
    "node_state_before_select",
    "reserved_or_precolored_filtered",
    "available_phys_ordered",
    "blocked_candidates",
    "candidate_phys_ordered",
    "chosen_source",
    "tie_rule",
    "decision_rule",
    "confidence",
    "provenance",
)
VALID_COLOR_STATUS = {
    "colored",
    "coalesced_alias",
    "spilled",
    "precolored",
    "uncolored",
}


def load_backend_trace(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def write_backend_trace(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _missing(mapping: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [key for key in keys if key not in mapping]


def validate_backend_trace(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in _missing(payload, REQUIRED_TOP):
        errors.append(f"top-level missing {key}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION}, got {payload.get('schema_version')!r}"
        )
    compiler = payload.get("compiler") or {}
    if compiler.get("version") != "GC/1.2.5n" or compiler.get("retail") is not True:
        errors.append("compiler must describe retail GC/1.2.5n")
    functions = payload.get("functions")
    if not isinstance(functions, list) or not functions:
        errors.append("functions must be a non-empty list")
        return errors
    for fn_idx, fn in enumerate(functions):
        if not isinstance(fn, dict):
            errors.append(f"function[{fn_idx}] must be an object")
            continue
        regalloc = fn.get("regalloc") or {}
        classes = regalloc.get("classes")
        if not isinstance(classes, list) or not classes:
            errors.append(f"function {fn.get('name', fn_idx)} missing regalloc classes")
            continue
        for cls in classes:
            errors.extend(_validate_class(fn.get("name", "<unknown>"), cls))
    return errors


def _validate_class(fn_name: str, cls: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    class_name = cls.get("class_name", cls.get("class_id", "<unknown>"))
    for key in _missing(cls, REQUIRED_CLASS_FIELDS):
        errors.append(f"{fn_name}:{class_name} missing {key}")
    regs = cls.get("registers")
    if not isinstance(regs, dict):
        errors.append(f"{fn_name}:{class_name} missing registers")
    else:
        for key in _missing(regs, REQUIRED_REGISTER_FIELDS):
            errors.append(f"{fn_name}:{class_name} registers missing {key}")
        for key in ("allocatable", "initial_volatile", "nonvolatile_dispense_order"):
            if isinstance(regs.get(key), list) and not regs[key]:
                errors.append(f"{fn_name}:{class_name} registers {key} must be non-empty")
    nodes = cls.get("nodes")
    decisions = cls.get("color_decisions")
    edges = cls.get("edges")
    simplify_order = cls.get("simplify_order")
    select_order = cls.get("select_order")
    if not isinstance(nodes, list):
        errors.append(f"{fn_name}:{class_name} nodes must be a list")
        nodes = []
    if not isinstance(edges, list):
        errors.append(f"{fn_name}:{class_name} edges must be a list")
        edges = []
    if not isinstance(simplify_order, list):
        errors.append(f"{fn_name}:{class_name} simplify_order must be a list")
    if not isinstance(select_order, list):
        errors.append(f"{fn_name}:{class_name} select_order must be a list")
    if not isinstance(decisions, list):
        errors.append(f"{fn_name}:{class_name} color_decisions must be a list")
        decisions = []
    node_by_id: dict[int, dict[str, Any]] = {}
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("ig_id"), int):
            ig_id = int(node["ig_id"])
            if ig_id in node_by_id:
                errors.append(f"{fn_name}:{class_name} duplicate node ig_id {ig_id}")
            node_by_id[ig_id] = node

    decision_by_id: dict[str, dict[str, Any]] = {}
    seen_decisions: set[str] = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            errors.append(f"{fn_name}:{class_name} color decision must be object")
            continue
        raw_id = decision.get("id")
        if raw_id is None:
            errors.append(f"{fn_name}:{class_name} color decision missing id")
            decision_id = "<missing-id>"
        else:
            decision_id = str(raw_id)
            if decision_id in seen_decisions:
                errors.append(f"{fn_name}:{class_name} duplicate color decision id {decision_id}")
            seen_decisions.add(decision_id)
            decision_by_id[decision_id] = decision
        for key in _missing(decision, REQUIRED_COLORED_DECISION_FIELDS):
            errors.append(f"{fn_name}:{class_name} color decision {decision_id} missing {key}")
        ig_id = decision.get("ig_id")
        if isinstance(ig_id, int) and ig_id not in node_by_id:
            errors.append(f"{fn_name}:{class_name} color decision {decision_id} references missing node {ig_id}")
        if not isinstance(decision.get("blocked_candidates", []), list):
            errors.append(f"{fn_name}:{class_name} color decision {decision_id} blocked_candidates must be a list")
        for blocked in decision.get("blocked_candidates", []):
            holder = blocked.get("holder_ig_id") if isinstance(blocked, dict) else None
            if isinstance(holder, int) and holder not in node_by_id:
                errors.append(f"{fn_name}:{class_name} color decision {decision_id} blocked candidate holder {holder} missing")

    for edge in edges:
        if not isinstance(edge, dict):
            errors.append(f"{fn_name}:{class_name} edge must be object")
            continue
        for endpoint in ("a", "b"):
            ig_id = edge.get(endpoint)
            if ig_id not in node_by_id:
                errors.append(f"{fn_name}:{class_name} edge references missing node {ig_id}")

    coalesce = cls.get("coalesce")
    if not isinstance(coalesce, dict) or not isinstance(coalesce.get("mappings"), list):
        errors.append(f"{fn_name}:{class_name} coalesce.mappings must be a list")
        mappings = []
    else:
        mappings = coalesce["mappings"]
    for mapping in mappings:
        if not isinstance(mapping, dict):
            errors.append(f"{fn_name}:{class_name} coalesce mapping must be object")
            continue
        alias = mapping.get("alias")
        root = mapping.get("root")
        if alias not in node_by_id:
            errors.append(f"{fn_name}:{class_name} coalesce mapping references missing alias {alias}")
        if root not in node_by_id:
            errors.append(f"{fn_name}:{class_name} coalesce mapping references missing root {root}")

    for node in nodes:
        if not isinstance(node, dict):
            errors.append(f"{fn_name}:{class_name} node must be object")
            continue
        node_id = node.get("ig_id", "<missing-ig>")
        for key in _missing(node, REQUIRED_NODE_FIELDS):
            errors.append(f"{fn_name}:{class_name} node {node_id} missing {key}")
        status = node.get("color_status")
        if status not in VALID_COLOR_STATUS:
            errors.append(f"{fn_name}:{class_name} node {node_id} invalid color_status {status!r}")
        if status == "colored":
            ref = node.get("color_decision_ref")
            if ref is None:
                errors.append(f"{fn_name}:{class_name} colored node {node_id} missing color_decision_ref")
            elif str(ref) not in decision_by_id:
                errors.append(f"{fn_name}:{class_name} colored node {node_id} references missing color decision {ref}")
            elif decision_by_id[str(ref)].get("ig_id") != node_id:
                errors.append(
                    f"{fn_name}:{class_name} colored node {node_id} decision {ref} "
                    f"has ig_id {decision_by_id[str(ref)].get('ig_id')}"
                )
            if node.get("select_order") is None:
                errors.append(f"{fn_name}:{class_name} colored node {node_id} missing select_order")
        if status == "coalesced_alias":
            if node.get("coalesced_into") is None:
                errors.append(f"{fn_name}:{class_name} coalesced alias {node_id} missing coalesced_into")
            elif node.get("coalesced_into") not in node_by_id:
                errors.append(f"{fn_name}:{class_name} coalesced alias {node_id} references missing root {node.get('coalesced_into')}")
            if node.get("assigned_phys") is None:
                errors.append(f"{fn_name}:{class_name} coalesced alias {node_id} missing inherited assigned_phys")
    return errors
```

- [ ] **Step 5: Run schema tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_schema.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/mwcc_retro/backend_schema.py \
  tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json \
  tools/melee-agent/tests/test_retro_backend_schema.py
git commit -m "feat(retro): add backend trace schema contract"
```

---

### Task 2: Regalloc And Backend Summary Writers

**Files:**
- Create: `tools/mwcc_retro/backend_summary.py`
- Create: `tools/melee-agent/tests/test_retro_backend_summary.py`

- [ ] **Step 1: Write failing summary tests**

Create `tools/melee-agent/tests/test_retro_backend_summary.py`:

```python
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_summary  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"


def test_regalloc_summary_includes_colored_and_coalesced_nodes():
    trace = json.loads(FIXTURE.read_text())
    text = backend_summary.render_regalloc_summary(trace)
    assert "function test_fn" in text
    assert "class gpr(0)" in text
    assert "ig=32 virt=r32 phys=r31 status=colored" in text
    assert "ig=40 virt=r40 phys=r31 status=coalesced_alias root=32" in text
    assert "blocked=33:r3" in text


def test_backend_summary_lists_passes_and_edges():
    trace = json.loads(FIXTURE.read_text())
    text = backend_summary.render_backend_summary(trace)
    assert "BACKEND TRACE test_fn" in text
    assert "BEFORE REGISTER COLORING" in text
    assert "edge 32 -- 33" in text
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_summary.py -v
```

Expected: fail because `backend_summary` does not exist.

- [ ] **Step 3: Implement summary writers**

Create `tools/mwcc_retro/backend_summary.py`:

```python
"""Human-readable summaries for normalized mwcc-retro backend traces."""
from __future__ import annotations

from typing import Any


def _virt(node: dict[str, Any]) -> str:
    v = node.get("virtual") or {}
    return f"{v.get('kind', '?')}{v.get('number', '?')}"


def _decision_map(cls: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(dec.get("id")): dec
        for dec in cls.get("color_decisions", [])
        if isinstance(dec, dict) and dec.get("id") is not None
    }


def _blocked_summary(decision: dict[str, Any] | None) -> str:
    if not decision:
        return "blocked=-"
    pairs: list[str] = []
    for item in decision.get("blocked_by", []):
        ig = item.get("ig_id")
        phys = item.get("phys")
        if ig is not None and phys is not None:
            pairs.append(f"{ig}:r{phys}")
    return "blocked=" + (",".join(pairs) if pairs else "-")


def render_regalloc_summary(trace: dict[str, Any]) -> str:
    out: list[str] = [f"schema {trace.get('schema_version')}", ""]
    for fn in trace.get("functions", []):
        out.append(f"function {fn.get('name')}")
        for cls in (fn.get("regalloc") or {}).get("classes", []):
            class_name = cls.get("class_name")
            class_id = cls.get("class_id")
            out.append(f"  class {class_name}({class_id})")
            decisions = _decision_map(cls)
            for node in cls.get("nodes", []):
                ref = node.get("color_decision_ref")
                decision = decisions.get(str(ref)) if ref is not None else None
                status = node.get("color_status")
                root = node.get("coalesced_into")
                root_text = f" root={root}" if root is not None else ""
                out.append(
                    "    "
                    f"ig={node.get('ig_id')} virt={_virt(node)} "
                    f"phys=r{node.get('assigned_phys')} status={status}{root_text} "
                    f"degree={node.get('degree')} simplify={node.get('simplify_order')} "
                    f"select={node.get('select_order')} {_blocked_summary(decision)}"
                )
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_backend_summary(trace: dict[str, Any]) -> str:
    out: list[str] = []
    for fn in trace.get("functions", []):
        out.append(f"BACKEND TRACE {fn.get('name')}")
        for p in (fn.get("pcode") or {}).get("passes", []):
            out.append(f"pass {p.get('id')}: {p.get('name')}")
            for inst in p.get("instructions", []):
                out.append(
                    f"  {inst.get('id')} {inst.get('block_id')} "
                    f"{inst.get('opcode')} {inst.get('operands')}"
                )
        for cls in (fn.get("regalloc") or {}).get("classes", []):
            out.append(f"regalloc class {cls.get('class_name')}({cls.get('class_id')})")
            for edge in cls.get("edges", []):
                out.append(
                    f"  edge {edge.get('a')} -- {edge.get('b')} "
                    f"{edge.get('confidence')} {edge.get('provenance')}"
                )
    return "\n".join(out).rstrip() + "\n"
```

- [ ] **Step 4: Run summary tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_summary.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/mwcc_retro/backend_summary.py \
  tools/melee-agent/tests/test_retro_backend_summary.py
git commit -m "feat(retro): summarize backend allocator facts"
```

---

### Task 3: Raw Event Normalizer

**Files:**
- Create: `tools/mwcc_retro/backend_events.py`
- Create: `tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl`
- Create: `tools/melee-agent/tests/test_retro_backend_events.py`

- [ ] **Step 1: Write a raw event fixture**

Create `tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl`:

```jsonl
{"event":"function_start","function":"test_fn","identity":{"requested":"test_fn","canonical_name":"test_fn","symbol_name":"test_fn","source_name":"test_fn","aliases":[],"source_file":"src/melee/test/unit.c"}}
{"event":"block","function":"test_fn","id":"B0","order":0,"succ":["B1"],"pred":[],"labels":["L0"]}
{"event":"block","function":"test_fn","id":"B1","order":1,"succ":[],"pred":["B0"],"labels":["L1"]}
{"event":"pcode_instruction","function":"test_fn","pass_id":"before_register_coloring","pass_name":"BEFORE REGISTER COLORING","id":"p0","block_id":"B0","order":0,"opcode":"mr","operands":"r32,r3","normalized":"mr v,arg0"}
{"event":"regclass","function":"test_fn","class_id":0,"class_name":"gpr","registers":{"physical_count":32,"allocatable":[3,4,5,31,30],"initial_volatile":[3,4,5],"reserved":[0,1,2],"fixed":[],"precolored":[],"nonvolatile_dispense_order":[31,30,29],"model_boundary":[]}}
{"event":"node","function":"test_fn","class_id":0,"node":{"ig_id":32,"virtual":{"kind":"r","number":32},"first_def":{"pass_id":"before_register_coloring","block_id":"B0","instruction_id":"p0","opcode":"mr","operands":"r32,r3","normalized":"mr v,arg0"},"source_attribution":{"status":"unattributed","symbol":null,"line":null,"confidence":"unavailable"},"live":{"blocks":["B0","B1"],"intervals":[],"confidence":"observed"},"degree":1,"flags":[],"coalesce":{"root_ig_id":32,"aliases":[40]},"simplify_order":1,"select_order":1,"assigned_phys":31,"spill":{"spilled":false,"reason":null},"color_status":"colored","coalesced_into":null,"color_decision_ref":"gpr-c0"}}
{"event":"node","function":"test_fn","class_id":0,"node":{"ig_id":33,"virtual":{"kind":"r","number":33},"first_def":{"pass_id":"before_register_coloring","block_id":"B0","instruction_id":"p0","opcode":"mr","operands":"r33,r3","normalized":"mr tmp,arg0"},"source_attribution":{"status":"unattributed","symbol":null,"line":null,"confidence":"unavailable"},"live":{"blocks":["B0"],"intervals":[],"confidence":"observed"},"degree":1,"flags":[],"coalesce":{"root_ig_id":33,"aliases":[]},"simplify_order":0,"select_order":0,"assigned_phys":30,"spill":{"spilled":false,"reason":null},"color_status":"colored","coalesced_into":null,"color_decision_ref":"gpr-c1"}}
{"event":"node","function":"test_fn","class_id":0,"node":{"ig_id":40,"virtual":{"kind":"r","number":40},"first_def":{"pass_id":"before_register_coloring","block_id":"B0","instruction_id":"p0","opcode":"mr","operands":"r40,r32","normalized":"mr alias,root"},"source_attribution":{"status":"unattributed","symbol":null,"line":null,"confidence":"unavailable"},"live":{"blocks":["B0"],"intervals":[],"confidence":"observed"},"degree":0,"flags":["coalesced_away"],"coalesce":{"root_ig_id":32,"aliases":[]},"simplify_order":null,"select_order":null,"assigned_phys":31,"spill":{"spilled":false,"reason":null},"color_status":"coalesced_alias","coalesced_into":32,"color_decision_ref":null}}
{"event":"edge","function":"test_fn","class_id":0,"edge":{"a":32,"b":33,"kind":"interference","confidence":"observed","provenance":"interferencegraph"}}
{"event":"coalesce_mapping","function":"test_fn","class_id":0,"mapping":{"alias":40,"root":32,"root_phys":31,"confidence":"observed","provenance":"coalesce_alias"}}
{"event":"simplify_order","function":"test_fn","class_id":0,"order":[33,32]}
{"event":"select_order","function":"test_fn","class_id":0,"order":[33,32]}
{"event":"color_decision","function":"test_fn","class_id":0,"decision":{"id":"gpr-c0","ig_id":32,"iter":1,"assigned_phys":31,"node_state_before_select":{"precolored":false,"coalesced":false,"spill_marked":false,"rematerialized":false},"reserved_or_precolored_filtered":[0,1,2],"available_phys_ordered":[3,4,5,31],"blocked_candidates":[{"phys":3,"reason":"interferer-assigned-phys","holder_ig_id":33,"holder_assigned_phys":3,"provenance":"interference_edge"}],"candidate_phys_ordered":[31],"chosen_source":"nonvolatile_dispense","volatile_pool_before":[3,4,5],"volatile_pool_after":[3,4,5,31],"nonvolatile_dispense_before":{"next":31,"remaining":[31,30]},"nonvolatile_dispense_after":{"consumed":31,"remaining":[30]},"tie_rule":"top_down_nonvolatile_dispense","blocked_by":[{"ig_id":33,"phys":3}],"decision_rule":"lowest_available_or_nonvolatile_dispense","confidence":"observed","provenance":"colorgraph"}}
{"event":"color_decision","function":"test_fn","class_id":0,"decision":{"id":"gpr-c1","ig_id":33,"iter":0,"assigned_phys":30,"node_state_before_select":{"precolored":false,"coalesced":false,"spill_marked":false,"rematerialized":false},"reserved_or_precolored_filtered":[0,1,2],"available_phys_ordered":[3,4,5,30],"blocked_candidates":[],"candidate_phys_ordered":[30],"chosen_source":"nonvolatile_dispense","volatile_pool_before":[3,4,5],"volatile_pool_after":[3,4,5,30],"nonvolatile_dispense_before":{"next":30,"remaining":[30]},"nonvolatile_dispense_after":{"consumed":30,"remaining":[]},"tie_rule":"top_down_nonvolatile_dispense","blocked_by":[],"decision_rule":"lowest_available_or_nonvolatile_dispense","confidence":"observed","provenance":"colorgraph"}}
```

- [ ] **Step 2: Write failing event-normalizer tests**

Create `tools/melee-agent/tests/test_retro_backend_events.py`:

```python
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_events, backend_schema  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl"


def test_jsonl_events_normalize_to_backend_trace():
    events = backend_events.load_events(FIXTURE)
    trace = backend_events.normalize_events(
        events,
        compiler={"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
        source={
            "tu": "src/melee/test/unit.c",
            "function": "test_fn",
            "mwcc_command_hash": "sha256:events",
        },
        tool_version="test",
    )
    assert trace["schema_version"] == backend_schema.SCHEMA_VERSION
    assert trace["functions"][0]["name"] == "test_fn"
    cls = trace["functions"][0]["regalloc"]["classes"][0]
    assert [n["ig_id"] for n in cls["nodes"]] == [32, 33, 40]
    assert cls["edges"] == [
        {"a": 32, "b": 33, "kind": "interference", "confidence": "observed", "provenance": "interferencegraph"}
    ]
    assert cls["coalesce"]["mappings"][0]["alias"] == 40
    assert cls["simplify_order"] == [33, 32]
    assert cls["select_order"] == [33, 32]
    assert cls["nodes"][2]["color_status"] == "coalesced_alias"
    assert cls["color_decisions"][0]["blocked_candidates"][0]["holder_ig_id"] == 33
    assert backend_schema.validate_backend_trace(trace) == []


def test_allocator_event_before_regclass_is_rejected():
    events = backend_events.load_events(FIXTURE)
    regclass_idx = next(i for i, event in enumerate(events) if event["event"] == "regclass")
    node_idx = next(i for i, event in enumerate(events) if event["event"] == "node")
    events[regclass_idx], events[node_idx] = events[node_idx], events[regclass_idx]
    with pytest.raises(ValueError, match="regclass must precede node"):
        backend_events.normalize_events(
            events,
            compiler={"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
            source={
                "tu": "src/melee/test/unit.c",
                "function": "test_fn",
                "mwcc_command_hash": "sha256:events",
            },
            tool_version="test",
        )
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_events.py -v
```

Expected: fail because `backend_events` does not exist.

- [ ] **Step 4: Implement raw event normalizer**

Create `tools/mwcc_retro/backend_events.py`:

```python
"""Normalize mwcc-retro backend JSONL events into backend-trace.v1."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import backend_schema


def load_events(path: str | Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in Path(path).read_text().splitlines():
        stripped = line.strip()
        if stripped:
            events.append(json.loads(stripped))
    return events


def normalize_events(
    events: list[dict[str, Any]],
    *,
    compiler: dict[str, Any],
    source: dict[str, Any],
    tool_version: str,
) -> dict[str, Any]:
    functions: dict[str, dict[str, Any]] = {}
    class_index: dict[tuple[str, int], dict[str, Any]] = {}

    def ensure_fn(name: str) -> dict[str, Any]:
        if name not in functions:
            functions[name] = {
                "name": name,
                "identity": {
                    "requested": name,
                    "canonical_name": name,
                    "symbol_name": name,
                    "source_name": name,
                    "aliases": [],
                    "source_file": source.get("tu"),
                },
                "blocks": [],
                "pcode": {
                    "passes": [],
                    "instruction_identity_note": "instruction ids are stable only within this trace",
                },
                "regalloc": {"classes": []},
            }
        return functions[name]

    def ensure_pass(fn: dict[str, Any], pass_id: str, pass_name: str) -> dict[str, Any]:
        for existing in fn["pcode"]["passes"]:
            if existing["id"] == pass_id:
                return existing
        created = {"id": pass_id, "name": pass_name, "instructions": []}
        fn["pcode"]["passes"].append(created)
        return created

    def register_class(fn_name: str, class_id: int, class_name: str, registers: dict[str, Any]) -> dict[str, Any]:
        key = (fn_name, class_id)
        if key in class_index:
            raise ValueError(f"duplicate regclass for {fn_name} class {class_id}")
        cls = {
            "class_id": class_id,
            "class_name": class_name,
            "registers": registers,
            "nodes": [],
            "edges": [],
            "coalesce": {"mappings": []},
            "non_allocatable_state": {
                "status": "model-boundary",
                "notes": [],
            },
            "simplify_order": [],
            "select_order": [],
            "color_decisions": [],
        }
        ensure_fn(fn_name)["regalloc"]["classes"].append(cls)
        class_index[key] = cls
        return cls

    def class_for_event(kind: str, fn_name: str, class_id: int) -> dict[str, Any]:
        key = (fn_name, class_id)
        if key not in class_index:
            raise ValueError(f"regclass must precede {kind} for {fn_name} class {class_id}")
        return class_index[key]

    for event in events:
        fn_name = event["function"]
        fn = ensure_fn(fn_name)
        kind = event["event"]
        if kind == "function_start":
            fn["identity"] = event.get("identity", fn["identity"])
        elif kind == "block":
            fn["blocks"].append({
                "id": event["id"],
                "order": event["order"],
                "succ": event.get("succ", []),
                "pred": event.get("pred", []),
                "labels": event.get("labels", []),
            })
        elif kind == "pcode_instruction":
            p = ensure_pass(fn, event["pass_id"], event["pass_name"])
            p["instructions"].append({
                "id": event["id"],
                "block_id": event["block_id"],
                "order": event["order"],
                "opcode": event["opcode"],
                "operands": event["operands"],
                "normalized": event.get("normalized", ""),
            })
        elif kind == "regclass":
            register_class(fn_name, int(event["class_id"]), event["class_name"], event["registers"])
        elif kind == "node":
            cls = class_for_event(kind, fn_name, int(event["class_id"]))
            cls["nodes"].append(event["node"])
        elif kind == "edge":
            cls = class_for_event(kind, fn_name, int(event["class_id"]))
            cls["edges"].append(event["edge"])
        elif kind == "coalesce_mapping":
            cls = class_for_event(kind, fn_name, int(event["class_id"]))
            cls["coalesce"]["mappings"].append(event["mapping"])
        elif kind == "simplify_order":
            cls = class_for_event(kind, fn_name, int(event["class_id"]))
            cls["simplify_order"] = event["order"]
        elif kind == "select_order":
            cls = class_for_event(kind, fn_name, int(event["class_id"]))
            cls["select_order"] = event["order"]
        elif kind == "color_decision":
            cls = class_for_event(kind, fn_name, int(event["class_id"]))
            cls["color_decisions"].append(event["decision"])

    trace = {
        "schema_version": backend_schema.SCHEMA_VERSION,
        "tool_version": tool_version,
        "compiler": compiler,
        "source": source,
        "functions": list(functions.values()),
        "struct_map": {
            "schema_version": backend_schema.STRUCT_MAP_SCHEMA_VERSION,
            "entries": [],
        },
    }
    errors = backend_schema.validate_backend_trace(trace)
    if errors:
        if any("missing regalloc classes" in err for err in errors):
            raise ValueError("backend trace has no allocator classes")
        raise ValueError("backend trace failed validation: " + "; ".join(errors))
    return trace
```

- [ ] **Step 5: Run event tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_events.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add tools/mwcc_retro/backend_events.py \
  tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl \
  tools/melee-agent/tests/test_retro_backend_events.py
git commit -m "feat(retro): normalize backend trace events"
```

---

### Task 4: Function Identity And Output Paths

**Files:**
- Create: `tools/mwcc_retro/backend_identity.py`
- Create: `tools/melee-agent/tests/test_retro_backend_identity.py`

- [ ] **Step 1: Write failing identity tests**

Create `tools/melee-agent/tests/test_retro_backend_identity.py`:

```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_identity  # noqa: E402


def test_output_dir_includes_path_safe_unit_and_function_hash():
    out = backend_identity.output_dir_for(
        root=Path("/repo"),
        src="src/melee/mn/mndiagram.c",
        function="mnDiagram_UpdateScrollArrows",
        command="mwcceppc -c src/melee/mn/mndiagram.c",
    )
    text = out.as_posix()
    assert text.startswith("/repo/build/mwcc_retro/src_melee_mn_mndiagram-")
    assert "mnDiagram_UpdateScrollArrows-" in text


def test_identity_matches_aliases_not_runtime_address():
    identity = backend_identity.FunctionIdentity(
        requested="fn_80240000",
        canonical_name="mnDiagram_UpdateScrollArrows",
        symbol_name="mnDiagram_UpdateScrollArrows",
        source_name="mnDiagram_UpdateScrollArrows",
        aliases=("fn_80240000", "static_mnDiagram_UpdateScrollArrows"),
        source_file="src/melee/mn/mndiagram.c",
    )
    assert identity.matches("mnDiagram_UpdateScrollArrows")
    assert identity.matches("fn_80240000")
    assert not identity.matches("0x80240000")
```

- [ ] **Step 2: Run identity tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_identity.py -v
```

Expected: fail because `backend_identity` does not exist.

- [ ] **Step 3: Implement identity helpers**

Create `tools/mwcc_retro/backend_identity.py`:

```python
"""Function identity and output path helpers for backend tracing."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FunctionIdentity:
    requested: str
    canonical_name: str
    symbol_name: str | None
    source_name: str | None
    aliases: tuple[str, ...]
    source_file: str

    def matches(self, seen_name: str) -> bool:
        if seen_name.startswith("0x"):
            return False
        names = {
            self.requested,
            self.canonical_name,
            self.symbol_name or "",
            self.source_name or "",
            *self.aliases,
        }
        return seen_name in names

    def to_dict(self) -> dict:
        return {
            "requested": self.requested,
            "canonical_name": self.canonical_name,
            "symbol_name": self.symbol_name,
            "source_name": self.source_name,
            "aliases": list(self.aliases),
            "source_file": self.source_file,
        }


def path_slug(text: str, *, max_len: int = 72) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return (slug or "unnamed")[:max_len]


def short_hash(text: str, *, n: int = 10) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def output_dir_for(*, root: Path, src: str, function: str, command: str) -> Path:
    unit_key = f"{src}\n{command}"
    unit = f"{path_slug(Path(src).with_suffix('').as_posix())}-{short_hash(unit_key)}"
    fn = f"{path_slug(function)}-{short_hash(function)}"
    return Path(root) / "build" / "mwcc_retro" / unit / fn
```

- [ ] **Step 4: Run identity tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_identity.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tools/mwcc_retro/backend_identity.py \
  tools/melee-agent/tests/test_retro_backend_identity.py
git commit -m "feat(retro): add backend trace identity helpers"
```

---

### Task 5: Object Parity Gate

**Files:**
- Create: `tools/mwcc_retro/object_parity.py`
- Create: `tools/melee-agent/tests/test_retro_object_parity.py`

- [ ] **Step 1: Write failing parity tests**

Create `tools/melee-agent/tests/test_retro_object_parity.py`:

```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import object_parity  # noqa: E402


def test_hash_file_records_size_and_sha256(tmp_path):
    p = tmp_path / "a.o"
    p.write_bytes(b"abc")
    h = object_parity.hash_file(p)
    assert h.path == p
    assert h.size == 3
    assert h.sha256.startswith("ba7816bf")


def test_compare_objects_reports_match(tmp_path):
    a = tmp_path / "a.o"
    b = tmp_path / "b.o"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    result = object_parity.compare_objects(a, b)
    assert result.matched is True
    assert result.reference.sha256 == result.retro.sha256


def test_compare_objects_reports_mismatch(tmp_path):
    a = tmp_path / "a.o"
    b = tmp_path / "b.o"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    result = object_parity.compare_objects(a, b)
    assert result.matched is False
    assert result.reference.sha256 != result.retro.sha256
```

- [ ] **Step 2: Run parity tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_object_parity.py -v
```

Expected: fail because `object_parity` does not exist.

- [ ] **Step 3: Implement object hash comparison**

Create `tools/mwcc_retro/object_parity.py`:

```python
"""Raw object-byte parity helpers for mwcc-retro backend tracing."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ObjectHash:
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class ObjectParityResult:
    matched: bool
    reference: ObjectHash
    retro: ObjectHash

    def to_dict(self) -> dict:
        return {
            "matched": self.matched,
            "reference": {
                "path": str(self.reference.path),
                "size": self.reference.size,
                "sha256": self.reference.sha256,
            },
            "retro": {
                "path": str(self.retro.path),
                "size": self.retro.size,
                "sha256": self.retro.sha256,
            },
        }


def hash_file(path: str | Path) -> ObjectHash:
    p = Path(path)
    data = p.read_bytes()
    return ObjectHash(path=p, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def compare_objects(reference: str | Path, retro: str | Path) -> ObjectParityResult:
    ref = hash_file(reference)
    ret = hash_file(retro)
    return ObjectParityResult(matched=ref.sha256 == ret.sha256, reference=ref, retro=ret)
```

- [ ] **Step 4: Run parity tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_object_parity.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tools/mwcc_retro/object_parity.py \
  tools/melee-agent/tests/test_retro_object_parity.py
git commit -m "feat(retro): add object parity result model"
```

---

### Task 6: Struct Map Confidence Validation

**Files:**
- Create: `tools/mwcc_retro/struct_map.py`
- Create: `tools/melee-agent/tests/test_retro_struct_map.py`

- [ ] **Step 1: Write failing struct-map tests**

Create `tools/melee-agent/tests/test_retro_struct_map.py`:

```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import struct_map  # noqa: E402


def test_required_gc125n_backend_keys_validate():
    table = {
        "compiler": "1.2.5n",
        "entries": {
            key: {
                "va": 0x400000 + i,
                "confidence": "live-invariant",
                "provenance": "fixture",
            }
            for i, key in enumerate(struct_map.REQUIRED_GC125N_BACKEND_KEYS)
        },
        "structs": {
            name: {
                "confidence": "manual-disassembly-confirmed",
                "fields": fields,
            }
            for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items()
        },
    }
    assert struct_map.validate_required_backend_map(table) == []


def test_missing_required_key_reports_error():
    table = {"compiler": "1.2.5n", "entries": {}, "structs": {}}
    errors = struct_map.validate_required_backend_map(table)
    assert any("missing required backend entry codegen_start" in e for e in errors)
    assert any("missing required struct IGNode" in e for e in errors)


def test_low_confidence_required_key_reports_error():
    table = {
        "compiler": "1.2.5n",
        "entries": {
            "codegen_start": {
                "va": 0x4351C0,
                "confidence": "byte-correlate",
                "provenance": "fixture",
            }
        },
        "structs": {},
    }
    errors = struct_map.validate_required_backend_map(table)
    assert any("codegen_start confidence byte-correlate below required gate" in e for e in errors)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_struct_map.py -v
```

Expected: fail because `struct_map` does not exist.

- [ ] **Step 3: Implement struct-map validator**

Create `tools/mwcc_retro/struct_map.py`:

```python
"""Confidence gates for retail GC/1.2.5n backend/regalloc maps."""
from __future__ import annotations

from typing import Any

ACCEPTED_REQUIRED_CONFIDENCE = {
    "live-invariant",
    "operand-extract-confirmed",
    "manual-disassembly-confirmed",
    "dll-seed-confirmed",
}

REQUIRED_GC125N_BACKEND_KEYS = (
    "codegen_start",
    "codegen_end",
    "pcode_pass_boundary",
    "backend_block_list",
    "pcbasicblocks",
    "interference_matrix",
    "coalesce_alias",
    "interferencegraph",
    "n_ignodes",
    "used_vreg_gpr",
    "used_vreg_fpr",
    "build_interference_matrix",
    "real_coalesce",
    "build_adjacency_vectors",
    "simplifygraph",
    "colorgraph",
    "frame_locals",
    "final_scheduler",
)

REQUIRED_STRUCT_FIELDS: dict[str, dict[str, int]] = {
    "IGNode": {
        "next": 0x00,
        "ig_idx": 0x0C,
        "degree": 0x0E,
        "assignedReg": 0x10,
        "flags": 0x12,
        "arraySize": 0x14,
        "array": 0x16,
    },
    "PCode": {
        "opcode": 0x14,
    },
}


def validate_required_backend_map(table: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    entries = table.get("entries") or {}
    structs = table.get("structs") or {}
    for key in REQUIRED_GC125N_BACKEND_KEYS:
        entry = entries.get(key)
        if not entry:
            errors.append(f"missing required backend entry {key}")
            continue
        conf = entry.get("confidence")
        if conf not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"{key} confidence {conf} below required gate")
        if not isinstance(entry.get("va"), int) or entry.get("va") <= 0:
            errors.append(f"{key} missing positive va")
    for name, fields in REQUIRED_STRUCT_FIELDS.items():
        struct = structs.get(name)
        if not struct:
            errors.append(f"missing required struct {name}")
            continue
        conf = struct.get("confidence")
        if conf not in ACCEPTED_REQUIRED_CONFIDENCE:
            errors.append(f"struct {name} confidence {conf} below required gate")
        actual = struct.get("fields") or {}
        for field, offset in fields.items():
            if actual.get(field) != offset:
                errors.append(
                    f"struct {name}.{field} expected offset {offset:#x}, got {actual.get(field)!r}"
                )
    return errors
```

- [ ] **Step 4: Run struct-map tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_struct_map.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tools/mwcc_retro/struct_map.py \
  tools/melee-agent/tests/test_retro_struct_map.py
git commit -m "feat(retro): validate backend struct map confidence"
```

---

### Task 7: Fidelity Comparator

**Files:**
- Create: `tools/mwcc_retro/backend_fidelity.py`
- Create: `tools/melee-agent/tests/test_retro_backend_fidelity.py`

- [ ] **Step 1: Write failing fidelity tests**

Create `tools/melee-agent/tests/test_retro_backend_fidelity.py`:

```python
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_fidelity, backend_schema  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"


def test_compare_trace_to_itself_all_equal():
    trace = json.loads(FIXTURE.read_text())
    report = backend_fidelity.compare_backend_traces(trace, trace)
    assert report["summary"]["different"] == 0
    assert report["summary"]["equal"] > 0


def test_compare_detects_assignment_difference():
    retail = json.loads(FIXTURE.read_text())
    debug = json.loads(FIXTURE.read_text())
    debug["functions"][0]["regalloc"]["classes"][0]["nodes"][0]["assigned_phys"] = 29
    report = backend_fidelity.compare_backend_traces(retail, debug)
    assert report["summary"]["different"] == 1
    assert report["different"][0]["field"] == "assigned_phys"
    assert report["different"][0]["ig_id"] == 32


def test_render_fidelity_text_reports_data_not_failure():
    retail = json.loads(FIXTURE.read_text())
    debug = json.loads(FIXTURE.read_text())
    debug["functions"][0]["regalloc"]["classes"][0]["nodes"][0]["assigned_phys"] = 29
    report = backend_fidelity.compare_backend_traces(retail, debug)
    text = backend_fidelity.render_fidelity_text(report)
    assert "different: 1" in text
    assert "ig=32 assigned_phys retail=31 debug=29" in text
```

- [ ] **Step 2: Run fidelity tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_fidelity.py -v
```

Expected: fail because `backend_fidelity` does not exist.

- [ ] **Step 3: Implement fidelity comparator**

Create `tools/mwcc_retro/backend_fidelity.py`:

```python
"""Retail-vs-debug backend trace comparison."""
from __future__ import annotations

from typing import Any


def _nodes(trace: dict[str, Any]) -> dict[tuple[str, int, int], dict[str, Any]]:
    out: dict[tuple[str, int, int], dict[str, Any]] = {}
    for fn in trace.get("functions", []):
        fn_name = fn.get("name")
        for cls in (fn.get("regalloc") or {}).get("classes", []):
            class_id = int(cls.get("class_id", -1))
            for node in cls.get("nodes", []):
                out[(fn_name, class_id, int(node["ig_id"]))] = node
    return out


def compare_backend_traces(retail: dict[str, Any], debug: dict[str, Any]) -> dict[str, Any]:
    retail_nodes = _nodes(retail)
    debug_nodes = _nodes(debug)
    report: dict[str, Any] = {
        "schema_version": "mwcc-retro-backend-fidelity.v1",
        "summary": {
            "equal": 0,
            "retail_only": 0,
            "debug_only": 0,
            "different": 0,
            "not_comparable": 0,
        },
        "equal": [],
        "retail_only": [],
        "debug_only": [],
        "different": [],
        "not_comparable": [],
    }
    for key in sorted(set(retail_nodes) | set(debug_nodes)):
        r = retail_nodes.get(key)
        d = debug_nodes.get(key)
        fn_name, class_id, ig_id = key
        if r is None:
            report["debug_only"].append({"function": fn_name, "class_id": class_id, "ig_id": ig_id})
            report["summary"]["debug_only"] += 1
            continue
        if d is None:
            report["retail_only"].append({"function": fn_name, "class_id": class_id, "ig_id": ig_id})
            report["summary"]["retail_only"] += 1
            continue
        for field in ("assigned_phys", "color_status", "degree", "simplify_order", "select_order"):
            if r.get(field) == d.get(field):
                report["equal"].append({"function": fn_name, "class_id": class_id, "ig_id": ig_id, "field": field})
                report["summary"]["equal"] += 1
            else:
                report["different"].append({
                    "function": fn_name,
                    "class_id": class_id,
                    "ig_id": ig_id,
                    "field": field,
                    "retail": r.get(field),
                    "debug": d.get(field),
                })
                report["summary"]["different"] += 1
    return report


def render_fidelity_text(report: dict[str, Any]) -> str:
    s = report["summary"]
    out = [
        "backend fidelity report",
        f"equal: {s['equal']}",
        f"retail_only: {s['retail_only']}",
        f"debug_only: {s['debug_only']}",
        f"different: {s['different']}",
        f"not_comparable: {s['not_comparable']}",
        "",
    ]
    for diff in report.get("different", []):
        out.append(
            f"ig={diff['ig_id']} {diff['field']} "
            f"retail={diff['retail']} debug={diff['debug']}"
        )
    return "\n".join(out).rstrip() + "\n"
```

- [ ] **Step 4: Run fidelity tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_fidelity.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tools/mwcc_retro/backend_fidelity.py \
  tools/melee-agent/tests/test_retro_backend_fidelity.py
git commit -m "feat(retro): compare backend trace fidelity"
```

---

### Task 8: Backend CLI Skeleton And Output Writing

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Create: `tools/melee-agent/tests/test_retro_backend_cli.py`
- Modify: `tools/melee-agent/tests/golden/debug_cli_help/debug__retro.txt`
- Create: `tools/melee-agent/tests/golden/debug_cli_help/debug__retro__backend.txt`
- Create: `tools/melee-agent/tests/golden/debug_cli_help/debug__retro__verify-backend.txt`

- [ ] **Step 1: Write failing CLI tests**

Create `tools/melee-agent/tests/test_retro_backend_cli.py`:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


def test_retro_backend_help_lists_exact_retail_language():
    r = runner.invoke(app, ["debug", "retro", "backend", "--help"])
    assert r.exit_code == 0
    assert "exact retail GC/1.2.5n backend/regalloc trace" in r.output
    assert "--verify-debug" in r.output


def test_retro_verify_backend_help():
    r = runner.invoke(app, ["debug", "retro", "verify-backend", "--help"])
    assert r.exit_code == 0
    assert "Compare a retail backend trace to mwcc-debug" in r.output


def test_backend_command_writes_trace_outputs(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    fixture = Path(__file__).resolve().parents[3] / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
    trace = json.loads(fixture.read_text())

    def fake_run_backend_trace(**kwargs):
        out = kwargs["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        return retro.BackendOutcome(exit_code=0, trace=trace, fidelity=None)

    monkeypatch.setattr(retro, "_run_backend_trace", fake_run_backend_trace)
    monkeypatch.setattr(retro, "_ensure_setup", lambda *_args, **_kwargs: None)

    r = runner.invoke(app, [
        "debug", "retro", "backend",
        "src/melee/test/unit.c",
        "-f", "test_fn",
        "-O", str(tmp_path),
    ])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "backend-trace.v1.json").exists()
    assert (tmp_path / "regalloc-summary.txt").exists()
    assert (tmp_path / "backend-summary.txt").exists()
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_cli.py -v
```

Expected: fail because `backend` and `verify-backend` commands are not registered.

- [ ] **Step 3: Add CLI dataclass and output writer imports**

Modify `tools/melee-agent/src/cli/debug/retro.py` near the existing `DumpOutcome` dataclass:

```python
@dataclass
class BackendOutcome:
    exit_code: int
    trace: dict | None = None
    fidelity: dict | None = None
    missing: list[str] = field(default_factory=list)
```

Add imports inside new helper functions, not at module top, to keep existing CLI import time low:

```python
from tools.mwcc_retro import backend_fidelity, backend_schema, backend_summary
```

- [ ] **Step 4: Add backend output writer helper**

Add to `tools/melee-agent/src/cli/debug/retro.py`:

```python
def _write_backend_outputs(out_dir: Path, trace: dict, fidelity: dict | None = None) -> None:
    from tools.mwcc_retro import backend_fidelity, backend_schema, backend_summary

    out_dir.mkdir(parents=True, exist_ok=True)
    errors = backend_schema.validate_backend_trace(trace)
    if errors:
        raise RuntimeError("backend trace schema errors: " + "; ".join(errors))
    backend_schema.write_backend_trace(out_dir / "backend-trace.v1.json", trace)
    (out_dir / "regalloc-summary.txt").write_text(
        backend_summary.render_regalloc_summary(trace)
    )
    (out_dir / "backend-summary.txt").write_text(
        backend_summary.render_backend_summary(trace)
    )
    if fidelity is not None:
        (out_dir / "backend-fidelity.json").write_text(
            json.dumps(fidelity, indent=2, sort_keys=True) + "\n"
        )
        (out_dir / "backend-fidelity.txt").write_text(
            backend_fidelity.render_fidelity_text(fidelity)
        )
```

- [ ] **Step 5: Add backend trace runner stub**

Add to `tools/melee-agent/src/cli/debug/retro.py`:

```python
def _run_backend_trace(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    verify_debug: bool,
    melee_root: Path,
) -> BackendOutcome:
    raise RuntimeError(
        "retail GC/1.2.5n backend trace runtime is not wired yet; "
        "schema and CLI plumbing are installed"
    )
```

This is intentionally not the final behavior. Later tasks replace it with parity, gdb runtime, and normalizer wiring before live validation.

- [ ] **Step 6: Register `backend` and `verify-backend` commands**

Add to `tools/melee-agent/src/cli/debug/retro.py` after `dump_cmd`:

```python
@retro_app.command("backend")
def backend_cmd(
    src: str = typer.Argument(..., help="TU source path, e.g. src/melee/mn/mndiagram.c"),
    fn: str = typer.Option(..., "-f", "--function"),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
    verify_debug: bool = typer.Option(
        False,
        "--verify-debug",
        help="Also compare the retail backend trace to the mwcc-debug pcdump.",
    ),
):
    """Emit an exact retail GC/1.2.5n backend/regalloc trace."""
    active_root = _resolve_melee_root(melee_root)
    _ensure_setup(active_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    try:
        outcome = _run_backend_trace(
            src=src,
            fn=fn,
            out_dir=out_dir,
            verify_debug=verify_debug,
            melee_root=active_root,
        )
        if outcome.trace is not None:
            _write_backend_outputs(out_dir, outcome.trace, outcome.fidelity)
    except RuntimeError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2)
    raise typer.Exit(outcome.exit_code)


@retro_app.command("verify-backend")
def verify_backend_cmd(
    src: str = typer.Argument(..., help="TU source path used for trace generation"),
    fn: str = typer.Option(..., "-f", "--function"),
    trace_path: Path = typer.Option(
        None,
        "--trace",
        help="Existing backend-trace.v1.json. Defaults to the generated output path.",
    ),
    melee_root: Path = typer.Option(None, "--melee-root"),
):
    """Compare a retail backend trace to mwcc-debug pcdump facts."""
    active_root = _resolve_melee_root(melee_root)
    out_dir = _resolve_output_dir(None, melee_root=active_root, src=src, fn=fn)
    trace_file = trace_path or (out_dir / "backend-trace.v1.json")
    if not trace_file.exists():
        typer.secho(f"backend trace not found: {trace_file}", fg="red", err=True)
        raise typer.Exit(2)
    typer.echo(f"backend trace: {trace_file}")
    typer.echo("mwcc-debug comparison wiring lands with the fidelity adapter task")
    raise typer.Exit(0)
```

- [ ] **Step 7: Run CLI tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_cli.py -v
```

Expected: pass.

- [ ] **Step 8: Refresh CLI help golden files**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_debug_cli_help_golden.py -k retro -v
```

Expected: fail and print the command to refresh golden files, or show diff paths.

Use the repo's existing golden update workflow. If the test has no update flag, run:

```bash
melee-agent debug retro --help > tests/golden/debug_cli_help/debug__retro.txt
melee-agent debug retro backend --help > tests/golden/debug_cli_help/debug__retro__backend.txt
melee-agent debug retro verify-backend --help > tests/golden/debug_cli_help/debug__retro__verify-backend.txt
```

Then rerun:

```bash
cd tools/melee-agent
python -m pytest tests/test_debug_cli_help_golden.py -k retro -v
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add tools/melee-agent/src/cli/debug/retro.py \
  tools/melee-agent/tests/test_retro_backend_cli.py \
  tools/melee-agent/tests/golden/debug_cli_help/debug__retro.txt \
  tools/melee-agent/tests/golden/debug_cli_help/debug__retro__backend.txt \
  tools/melee-agent/tests/golden/debug_cli_help/debug__retro__verify-backend.txt
git commit -m "feat(retro): add backend trace cli surface"
```

---

### Task 9: Backend Discovery Utilities

**Files:**
- Create: `tools/mwcc_retro/backend_discovery.py`
- Create: `tools/melee-agent/tests/test_retro_backend_discovery.py`
- Modify: `tools/mwcc_retro/port_table.py`

- [ ] **Step 1: Write failing discovery tests**

Create `tools/melee-agent/tests/test_retro_backend_discovery.py`:

```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_discovery  # noqa: E402


def test_scan_abs32_operands_finds_data_reference():
    blob = b"\x8b\x0d\x88\x30\x58\x00" + b"\x90" * 8
    refs = backend_discovery.scan_abs32_operands(blob, base_va=0x400000, lo=0x580000, hi=0x590000)
    assert refs == [{"site_va": 0x400002, "target_va": 0x583088}]


def test_rank_candidate_rejects_ambiguous_refs():
    candidates = [
        {"site_va": 0x1, "target_va": 0x583088},
        {"site_va": 0x2, "target_va": 0x583088},
    ]
    result = backend_discovery.unique_operand_target(candidates, 0x583088)
    assert result is None


def test_rank_candidate_accepts_unique_ref():
    candidates = [{"site_va": 0x1, "target_va": 0x583088}]
    result = backend_discovery.unique_operand_target(candidates, 0x583088)
    assert result == {"site_va": 0x1, "target_va": 0x583088}
```

- [ ] **Step 2: Run discovery tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_discovery.py -v
```

Expected: fail because `backend_discovery` does not exist.

- [ ] **Step 3: Implement operand extraction helpers**

Create `tools/mwcc_retro/backend_discovery.py`:

```python
"""Backend address discovery helpers for retail MWCC GC/1.2.5n."""
from __future__ import annotations

import struct
from typing import Any


def scan_abs32_operands(blob: bytes, *, base_va: int, lo: int, hi: int) -> list[dict[str, int]]:
    refs: list[dict[str, int]] = []
    for off in range(0, max(len(blob) - 3, 0)):
        val = struct.unpack_from("<I", blob, off)[0]
        if lo <= val < hi:
            refs.append({"site_va": base_va + off, "target_va": val})
    return refs


def unique_operand_target(candidates: list[dict[str, Any]], target_va: int) -> dict[str, Any] | None:
    hits = [c for c in candidates if c.get("target_va") == target_va]
    if len(hits) != 1:
        return None
    return hits[0]


def confidence_entry(*, va: int, provenance: str, confidence: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "va": va,
        "provenance": provenance,
        "confidence": confidence,
        "evidence": evidence,
    }
```

- [ ] **Step 4: Run discovery tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_discovery.py -v
```

Expected: pass.

- [ ] **Step 5: Add port-table integration note in code**

Modify `tools/mwcc_retro/port_table.py` near `BACKEND_PARTIAL_125N` to add a code comment that active 1.2.5n backend entries must pass `struct_map.validate_required_backend_map` before being moved from `backend_partial` to `entries`.

Use this exact comment:

```python
# Backend entries move from `backend_partial` into active `entries` only after
# backend_discovery evidence plus struct_map.validate_required_backend_map() pass.
# A byte-correlated address by itself is not enough for the 1.2.5n backend tracer.
```

- [ ] **Step 6: Commit**

```bash
git add tools/mwcc_retro/backend_discovery.py \
  tools/mwcc_retro/port_table.py \
  tools/melee-agent/tests/test_retro_backend_discovery.py
git commit -m "feat(retro): add backend address discovery helpers"
```

---

### Task 10: Backend Runtime Wiring And Parity Gate

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Modify: `tools/mwcc_retro/mwcc_retro_debugger.py`
- Create: `tools/melee-agent/tests/test_retro_backend_runtime.py`

- [ ] **Step 1: Write failing runtime tests with subprocess monkeypatching**

Create `tools/melee-agent/tests/test_retro_backend_runtime.py`:

```python
import json
from pathlib import Path


def test_run_backend_trace_invokes_parity_before_launcher(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    fixture = Path(__file__).resolve().parents[3] / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"
    trace = json.loads(fixture.read_text())
    calls = []

    monkeypatch.setattr(retro, "_run_object_parity_for_backend", lambda **kw: calls.append("parity") or {"matched": True})
    monkeypatch.setattr(retro, "_launch_backend_events", lambda **kw: calls.append("launch") or tmp_path / "events.jsonl")
    monkeypatch.setattr(retro.backend_events, "load_events", lambda path: calls.append("load") or [])
    monkeypatch.setattr(retro.backend_events, "normalize_events", lambda *args, **kw: calls.append("normalize") or trace)

    outcome = retro._run_backend_trace(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        verify_debug=False,
        melee_root=Path.cwd(),
    )
    assert outcome.exit_code == 0
    assert outcome.trace == trace
    assert calls == ["parity", "launch", "load", "normalize"]


def test_run_backend_trace_stops_on_failed_parity(monkeypatch, tmp_path):
    import src.cli.debug.retro as retro

    monkeypatch.setattr(retro, "_run_object_parity_for_backend", lambda **kw: {"matched": False})
    outcome = retro._run_backend_trace(
        src="src/melee/test/unit.c",
        fn="test_fn",
        out_dir=tmp_path,
        verify_debug=False,
        melee_root=Path.cwd(),
    )
    assert outcome.exit_code == 2
    assert outcome.trace is None
```

- [ ] **Step 2: Run runtime tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_runtime.py -v
```

Expected: fail because `_run_backend_trace` is still the stub.

- [ ] **Step 3: Import backend modules in `retro.py`**

Add near other `tools.mwcc_retro` imports in `tools/melee-agent/src/cli/debug/retro.py`:

```python
from tools.mwcc_retro import backend_events  # noqa: E402
```

- [ ] **Step 4: Add parity and launcher helpers**

Add to `tools/melee-agent/src/cli/debug/retro.py`:

```python
def _run_object_parity_for_backend(*, src: str, melee_root: Path) -> dict:
    """Run the raw .o byte-parity gate for backend tracing."""
    raise RuntimeError("backend object parity gate is not wired")


def _launch_backend_events(*, src: str, fn: str, out_dir: Path, melee_root: Path) -> Path:
    """Launch retrowin32+gdb backend event tracing and return JSONL path."""
    raise RuntimeError("backend event launcher requires validated 1.2.5n struct map")
```

The runtime tests monkeypatch `_run_object_parity_for_backend`; the committed helper must not return a synthetic pass. Step 7 replaces the hard failure with the real raw object-byte parity gate before this task is committed. The launcher remains hard-failing until Task 11 validates the struct map.

- [ ] **Step 5: Replace `_run_backend_trace` stub**

Replace `_run_backend_trace` in `tools/melee-agent/src/cli/debug/retro.py` with:

```python
def _run_backend_trace(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    verify_debug: bool,
    melee_root: Path,
) -> BackendOutcome:
    parity = _run_object_parity_for_backend(src=src, melee_root=melee_root)
    if not parity.get("matched"):
        return BackendOutcome(exit_code=2, trace=None, fidelity=None)
    try:
        events_path = _launch_backend_events(
            src=src,
            fn=fn,
            out_dir=out_dir,
            melee_root=melee_root,
        )
    except RuntimeError:
        raise
    events = backend_events.load_events(events_path)
    trace = backend_events.normalize_events(
        events,
        compiler={"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
        source={
            "tu": src,
            "function": fn,
            "mwcc_command_hash": "sha256:" + __import__("hashlib").sha256(src.encode()).hexdigest(),
        },
        tool_version="mwcc-retro-dev",
    )
    fidelity = None
    if verify_debug:
        fidelity = {"schema_version": "mwcc-retro-backend-fidelity.v1", "summary": {}}
    return BackendOutcome(exit_code=0, trace=trace, fidelity=fidelity)
```

- [ ] **Step 6: Run runtime tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_runtime.py -v
```

Expected: pass.

- [ ] **Step 7: Replace parity helper with real object parity compile**

Modify `_run_object_parity_for_backend` to call the existing `_ninja_cmd_for_unit`, redirect `-o` to two temp object paths, drop `-MMD`, and run normal wibo path plus retrowin32 path. Use `tools.mwcc_retro.object_parity.compare_objects` for the result. Keep the implementation small and preserve the returned dict shape.

Add this code:

```python
def _run_object_parity_for_backend(*, src: str, melee_root: Path) -> dict:
    import shlex
    import subprocess
    import tempfile

    from tools.mwcc_retro import object_parity, setup as _setup

    setup_result = _setup.ensure_for_root(melee_root, force=False)
    cmd = _ninja_cmd_for_unit(src, melee_root=melee_root)
    parts = shlex.split(cmd)
    compiler = str(melee_root / parts[0])
    args = [p for p in parts[1:] if p != "-MMD"]
    with tempfile.TemporaryDirectory() as td:
        ref = Path(td) / "reference.o"
        retro_obj = Path(td) / "retro.o"

        def with_output(path: Path) -> list[str]:
            local = list(args)
            if "-o" in local:
                local[local.index("-o") + 1] = str(path)
            else:
                local += ["-o", str(path)]
            return local

        wibo = melee_root / "build/tools/wibo"
        sjis = melee_root / "build/tools/sjiswrap.exe"
        if sjis.exists():
            normal_cmd = [str(wibo), str(sjis), compiler] + with_output(ref)
        else:
            normal_cmd = [str(wibo), compiler] + with_output(ref)
        subprocess.run(normal_cmd, cwd=melee_root, check=True, capture_output=True, timeout=300)
        subprocess.run(
            [str(setup_result.retrowin32_bin), compiler] + with_output(retro_obj),
            cwd=melee_root,
            check=True,
            capture_output=True,
            timeout=300,
        )
        return object_parity.compare_objects(ref, retro_obj).to_dict()
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_runtime.py tests/test_retro_object_parity.py -v
```

Expected: pass. If monkeypatched tests fail because `ensure_for_root` is called unexpectedly, adjust the monkeypatch in tests to cover `_run_object_parity_for_backend` as in Step 1.

- [ ] **Step 9: Commit**

```bash
git add tools/melee-agent/src/cli/debug/retro.py \
  tools/melee-agent/tests/test_retro_backend_runtime.py
git commit -m "feat(retro): wire backend runtime parity gate"
```

---

### Task 11: Gdb-Side Backend Event Emission

**Files:**
- Modify: `tools/mwcc_retro/mwcc_retro_debugger.py`
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Modify: `tools/melee-agent/tests/test_retro_backend_runtime.py`
- Modify: `tools/mwcc_retro/tables/gc_125n.json`
- Modify: `tools/mwcc_retro/port_table.py`
- Test: `tools/melee-agent/tests/test_retro_struct_map.py`
- Live commands from repo root.

- [ ] **Step 1: Add launcher diagnostics tests**

Append to `tools/melee-agent/tests/test_retro_backend_runtime.py`:

```python
def test_launch_backend_events_writes_launch_log_on_nonzero(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        assert kwargs["env"]["RETRO_SOURCE"] == "src/melee/test/unit.c"
        assert kwargs["env"]["RETRO_FUNCTION"] == "test_fn"
        return subprocess.CompletedProcess(cmd, 7, stdout="launcher stdout\n", stderr="launcher stderr\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher failed"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    launch_log = tmp_path / "launch.log"
    assert "launcher stdout" in launch_log.read_text()
    assert "launcher stderr" in launch_log.read_text()


def test_launch_backend_events_deletes_partial_events_on_abort(monkeypatch, tmp_path):
    import subprocess

    import pytest
    import src.cli.debug.retro as retro
    from tools.mwcc_retro import setup as retro_setup

    class SetupResult:
        retrowin32_bin = tmp_path / "retrowin32"

    monkeypatch.setattr(retro_setup, "ensure_for_root", lambda root, force=False: SetupResult())
    monkeypatch.setattr(retro, "_retro_tables_dir", lambda root: tmp_path)
    monkeypatch.setattr(
        retro,
        "_ninja_cmd_for_unit",
        lambda src, melee_root: "build/compilers/GC/1.2.5n/mwcceppc.exe -c source.c -o source.o",
    )

    def fake_run(cmd, **kwargs):
        (tmp_path / "backend-events.v1.jsonl").write_text('{"event":"backend_marker"}\n')
        return subprocess.CompletedProcess(cmd, 0, stdout="[retro] ABORT: missing colorgraph\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="backend event launcher aborted"):
        retro._launch_backend_events(
            src="src/melee/test/unit.c",
            fn="test_fn",
            out_dir=tmp_path,
            melee_root=Path.cwd(),
        )

    assert not (tmp_path / "backend-events.v1.jsonl").exists()
```

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_runtime.py::test_launch_backend_events_writes_launch_log_on_nonzero \
  tests/test_retro_backend_runtime.py::test_launch_backend_events_deletes_partial_events_on_abort -v
```

Expected: fail because `_launch_backend_events` still hard-raises before launching.

- [ ] **Step 2: Add backend mode environment variables and diagnostics to launcher**

Modify `_launch_backend_events` in `tools/melee-agent/src/cli/debug/retro.py` so it calls `mwcc_retro_debugger.py` with `--phases backend --compiler 1.2.5n` and returns `out_dir / "backend-events.v1.jsonl"`.

Use this implementation:

```python
def _launch_backend_events(*, src: str, fn: str, out_dir: Path, melee_root: Path) -> Path:
    import os
    import subprocess

    from tools.mwcc_retro import setup as _setup

    table = _retro_tables_dir(melee_root) / "gc_125n.json"
    setup_result = _setup.ensure_for_root(melee_root, force=False)
    mwcc_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    mwcc_args = _ninja_cmd_for_unit(src, melee_root=melee_root)
    mwcc_args = mwcc_args.split(" ", 1)[1] if " " in mwcc_args else mwcc_args
    mwcc_exe = str(mwcc_dir / "mwcceppc.exe")
    launcher = melee_root / "tools" / "mwcc_retro" / "mwcc_retro_debugger.py"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        str(launcher),
        "-e",
        str(setup_result.retrowin32_bin),
        "-a",
        f"{mwcc_exe} {mwcc_args}",
        "--table",
        str(table),
        "--out",
        str(out_dir),
        "--phases",
        "backend",
        "--compiler",
        "1.2.5n",
        fn,
    ]
    env = os.environ.copy()
    env["RETRO_SOURCE"] = src
    env["RETRO_FUNCTION"] = fn
    proc = subprocess.run(
        cmd,
        cwd=melee_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
        env=env,
    )
    launch_log = out_dir / "launch.log"
    launch_log.write_text(
        "COMMAND: " + " ".join(cmd) + "\n"
        f"RETRO_SOURCE: {src}\n"
        f"RETRO_FUNCTION: {fn}\n"
        f"EXIT: {proc.returncode}\n"
        "\nSTDOUT:\n" + proc.stdout +
        "\nSTDERR:\n" + proc.stderr,
        encoding="utf-8",
    )
    events = out_dir / "backend-events.v1.jsonl"
    combined = proc.stdout + "\n" + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(
            f"backend event launcher failed with exit {proc.returncode}; "
            f"see {launch_log}\n{_tail(combined)}"
        )
    if "[retro] ABORT:" in combined:
        events.unlink(missing_ok=True)
        raise RuntimeError(f"backend event launcher aborted; see {launch_log}\n{_tail(combined)}")
    if not events.exists():
        raise RuntimeError(f"backend event launcher produced no events: {events}; see {launch_log}\n{_tail(combined)}")
    return events


def _tail(text: str, *, lines: int = 20) -> str:
    return "\n".join(text.splitlines()[-lines:])
```

- [ ] **Step 3: Run launcher diagnostics tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_runtime.py::test_launch_backend_events_writes_launch_log_on_nonzero \
  tests/test_retro_backend_runtime.py::test_launch_backend_events_deletes_partial_events_on_abort -v
```

Expected: pass.

- [ ] **Step 4: Add event writer helpers to gdb script**

In `tools/mwcc_retro/mwcc_retro_debugger.py`, add below `RetroContext`:

```python
def _jsonl_append(path, obj):
    import json
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def _backend_events_path(out_dir):
    return os.path.join(out_dir, "backend-events.v1.jsonl")
```

- [ ] **Step 5: Add required backend table validation inside gdb mode**

In `run_in_gdb`, before backend tracing starts for compiler `1.2.5n`, validate required keys using the host-side `struct_map` module:

```python
    if phases == "backend" and compiler == "1.2.5n":
        sys.path.insert(0, str(PKG_ROOT.parent.parent))
        from tools.mwcc_retro import struct_map
        errors = struct_map.validate_required_backend_map(table)
        if errors:
            print("[retro] ABORT: backend map confidence gate failed")
            for err in errors:
                print(f"[retro]   {err}")
            _continue_to_exit(gdb)
            return
        _enable_backend_tracing(gdb, cad, table, out_dir, fn)
        return
```

Remove or bypass the previous message that said 1.2.5n backend is not populated once this function exists.

- [ ] **Step 6: Add `_enable_backend_tracing` skeleton**

Add this function to `tools/mwcc_retro/mwcc_retro_debugger.py`:

```python
def _enable_backend_tracing(gdb, cad, table, out_dir, fn):
    """Observe retail GC/1.2.5n backend/regalloc state and emit JSONL events."""
    e = table["entries"]
    events_path = _backend_events_path(out_dir)
    if os.path.exists(events_path):
        os.remove(events_path)
    _jsonl_append(events_path, {
        "event": "function_start",
        "function": fn,
        "identity": {
            "requested": fn,
            "canonical_name": fn,
            "symbol_name": fn,
            "source_name": fn,
            "aliases": [],
            "source_file": os.environ.get("RETRO_SOURCE", ""),
        },
    })

    required = ["codegen_start", "colorgraph", "simplifygraph", "interferencegraph"]
    missing = [key for key in required if key not in e or not e[key].get("va")]
    if missing:
        print(f"[retro] ABORT: backend trace missing entries {missing}")
        _continue_to_exit(gdb)
        return

    class _CodegenStart(gdb.Breakpoint):
        def stop(self):
            _jsonl_append(events_path, {
                "event": "backend_marker",
                "function": fn,
                "marker": "codegen_start",
                "pc": int(gdb.parse_and_eval("$pc")),
            })
            return False

    _CodegenStart(f"*{e['codegen_start']['va']:#x}")
    _continue_to_exit(gdb)
```

This produces only a marker until the next steps add PCode, graph, simplify, and colorgraph readers. It must remain behind the struct-map gate so live users do not get complete-looking allocator facts.

- [ ] **Step 7: Complete event readers with fixture-backed gates**

Add readers in the order below. After each reader, update `tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl` only with the new event family and add one assertion to `tools/melee-agent/tests/test_retro_backend_events.py` that proves the normalized `functions[].regalloc.classes[]` field is populated.

Reader acceptance checks:

- Function/backend markers: `function_start`, `backend_marker`; test that marker-only JSONL raises `ValueError("backend trace has no allocator classes")` in `normalize_events`.
- Block/PCode pass events: `block`, `pcode_instruction`; test that `pcode.passes[0].instructions[0].id == "p0"`.
- Register class metadata: `regclass`; test that `registers.allocatable`, `registers.initial_volatile`, `registers.fixed`, `registers.precolored`, and `registers.model_boundary` are preserved exactly.
- IG nodes and edges: `node`, `edge`; test that an edge references two existing nodes and `backend_schema.validate_backend_trace` rejects an edge to a missing node.
- Coalesce mappings: `coalesce_mapping`; test that node `40` has `color_status == "coalesced_alias"` and `coalesced_into == 32`.
- Simplify/select order: `simplify_order`, `select_order`; test that both class-level order arrays are non-empty and match node-level `simplify_order`/`select_order` values for colored nodes.
- Color decisions with structured pressure fields: `color_decision`; test that `blocked_candidates[0].holder_ig_id == 33`, `candidate_phys_ordered == [31]`, and `provenance == "colorgraph"`.

For each reader, use read-before-dereference checks:

```python
def _ptr_in_expected_range(ptr):
    return 0x400000 <= int(ptr) < 0x700000
```

If a reader sees an invalid pointer, impossible class id, negative count, or list cycle, emit `[retro] ABORT: ...` to stdout, remove `backend-events.v1.jsonl` if it exists, and return through `_continue_to_exit(gdb)`. `_launch_backend_events` treats the abort marker as a controlled failure, deletes partial events again on the host side, and prevents marker-only or partially aborted runs from being normalized into `backend-trace.v1.json`.

Run after each reader:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_events.py tests/test_retro_backend_schema.py -v
```

Expected: pass before moving to the next reader family.

- [ ] **Step 8: Promote validated table entries**

After live discovery, update `tools/mwcc_retro/tables/gc_125n.json` so `entries` contains every key from `struct_map.REQUIRED_GC125N_BACKEND_KEYS`, each with accepted confidence. Add `structs.IGNode` and `structs.PCode` with accepted confidence and fields.

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_struct_map.py -v
```

Expected: pass.

- [ ] **Step 9: Live matched-function trace**

From repo root:

```bash
melee-agent debug retro setup
melee-agent debug retro backend src/melee/lb/lbarq.c -f lbArq_80014ABC --verify-debug
```

Expected:

- exits 0;
- writes `backend-events.v1.jsonl`;
- writes `backend-trace.v1.json`;
- writes `regalloc-summary.txt`;
- writes `backend-summary.txt`;
- writes `backend-fidelity.json` and `.txt`;
- `backend-trace.v1.json` passes `backend_schema.validate_backend_trace`.

If `lbArq_80014ABC` is not present in the current tree, pick a matched function from the same TU using:

```bash
melee-agent extract list --max-match 1.00 --module lb | head -20
```

Record the chosen function in the implementation commit message.

- [ ] **Step 10: Commit**

```bash
git add tools/mwcc_retro/mwcc_retro_debugger.py \
  tools/melee-agent/src/cli/debug/retro.py \
  tools/mwcc_retro/tables/gc_125n.json \
  tools/mwcc_retro/port_table.py \
  tools/melee-agent/tests/test_retro_struct_map.py
git commit -m "feat(retro): trace retail backend allocator events"
```

---

### Task 12: Debug-DLL Adapter For Fidelity Verification

**Files:**
- Modify: `tools/mwcc_retro/backend_fidelity.py`
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Create: `tools/melee-agent/tests/test_retro_backend_debug_adapter.py`

- [ ] **Step 1: Write failing debug adapter tests**

Create `tools/melee-agent/tests/test_retro_backend_debug_adapter.py`:

```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_fidelity  # noqa: E402

PCDUMP = REPO / "tools/melee-agent/tests/fixtures/mwcc_debug/fn_80247510_pcdump.txt"


def test_debug_pcdump_adapter_produces_trace_shape():
    trace = backend_fidelity.trace_from_mwcc_debug_pcdump(
        PCDUMP.read_text(),
        function="fn_80247510",
        source="src/melee/mn/mnvibration.c",
    )
    assert trace["schema_version"] == "mwcc-retro-backend-trace.v1"
    assert trace["compiler"]["retail"] is False
    fn = trace["functions"][0]
    assert fn["name"] == "fn_80247510"
    cls = fn["regalloc"]["classes"][0]
    assert cls["nodes"]
    colored = next(node for node in cls["nodes"] if node["color_status"] == "colored")
    assert colored["color_decision_ref"] is not None
    decisions = {decision["id"]: decision for decision in cls["color_decisions"]}
    decision = decisions[colored["color_decision_ref"]]
    assert decision["provenance"] == "mwcc-debug-pcdump"
    assert "blocked_by" in decision
    assert decision["confidence"] == "debug-adapter"
    assert backend_schema.validate_backend_trace(trace) != []
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_debug_adapter.py -v
```

Expected: fail because `trace_from_mwcc_debug_pcdump` is missing.

- [ ] **Step 3: Implement debug adapter using existing parsers**

Add to `tools/mwcc_retro/backend_fidelity.py`:

```python
def trace_from_mwcc_debug_pcdump(text: str, *, function: str, source: str) -> dict[str, Any]:
    from src.mwcc_debug.colorgraph_parser import find_function, parse_hook_events

    events = find_function(parse_hook_events(text), function)
    classes: list[dict[str, Any]] = []
    if events is not None:
        for section in events.colorgraph_sections:
            nodes = []
            decisions = []
            for d in section.decisions:
                decision_id = f"debug-c{section.class_id}-{d.ig_idx}"
                nodes.append({
                    "ig_id": d.ig_idx,
                    "virtual": {"kind": "r" if section.class_id == 0 else "f", "number": d.ig_idx},
                    "first_def": {},
                    "source_attribution": {"status": "unattributed", "symbol": None, "line": None, "confidence": "unavailable"},
                    "live": {"blocks": [], "intervals": [], "confidence": "unavailable"},
                    "degree": d.degree,
                    "flags": [],
                    "coalesce": {"root_ig_id": d.ig_idx, "aliases": []},
                    "simplify_order": None,
                    "select_order": d.iter_idx,
                    "assigned_phys": d.assigned_reg,
                    "spill": {"spilled": bool(d.flags & 0x01), "reason": None},
                    "color_status": "spilled" if d.flags & 0x01 else "colored",
                    "coalesced_into": None,
                    "color_decision_ref": decision_id,
                })
                decisions.append({
                    "id": decision_id,
                    "ig_id": d.ig_idx,
                    "iter": d.iter_idx,
                    "assigned_phys": d.assigned_reg,
                    "node_state_before_select": {
                        "precolored": False,
                        "coalesced": False,
                        "spill_marked": bool(d.flags & 0x01),
                        "rematerialized": False,
                    },
                    "reserved_or_precolored_filtered": [],
                    "available_phys_ordered": [],
                    "blocked_candidates": [],
                    "candidate_phys_ordered": [],
                    "chosen_source": "unknown-debug-adapter",
                    "tie_rule": "unknown-debug-adapter",
                    "decision_rule": "debug-pcdump-observed-assignment",
                    "confidence": "debug-adapter",
                    "provenance": "mwcc-debug-pcdump",
                    "blocked_by": [
                        {"ig_id": idx, "phys": phys}
                        for idx, phys in d.interferers
                    ],
                })
            classes.append({
                "class_id": section.class_id,
                "class_name": "gpr" if section.class_id == 0 else "fpr",
                "registers": {
                    "physical_count": 32,
                    "allocatable": [],
                    "initial_volatile": [],
                    "reserved": [],
                    "fixed": [],
                    "precolored": [],
                    "nonvolatile_dispense_order": [],
                    "model_boundary": [],
                },
                "nodes": nodes,
                "edges": [],
                "coalesce": {"mappings": []},
                "non_allocatable_state": {"status": "model-boundary", "notes": ["debug adapter partial"]},
                "simplify_order": [],
                "select_order": [d.ig_idx for d in section.decisions],
                "color_decisions": decisions,
            })
    return {
        "schema_version": "mwcc-retro-backend-trace.v1",
        "tool_version": "mwcc-debug-adapter",
        "compiler": {"family": "MWCC", "version": "GC/1.2.5n-debug-dll", "retail": False},
        "source": {"tu": source, "function": function, "mwcc_command_hash": "debug-adapter"},
        "functions": [
            {
                "name": function,
                "identity": {
                    "requested": function,
                    "canonical_name": function,
                    "symbol_name": function,
                    "source_name": function,
                    "aliases": [],
                    "source_file": source,
                },
                "blocks": [],
                "pcode": {"passes": [], "instruction_identity_note": "debug adapter partial"},
                "regalloc": {"classes": classes},
            }
        ],
    }
```

- [ ] **Step 4: Wire `--verify-debug` to adapter**

Modify `_run_backend_trace` so when `verify_debug` is true it resolves a pcdump through existing debug CLI helpers, adapts it with `trace_from_mwcc_debug_pcdump`, and calls `compare_backend_traces`.

Use:

```python
    if verify_debug:
        import importlib
        debug_cli = importlib.import_module("src.cli.debug")
        pcdump_path = debug_cli._resolve_pcdump_path(None, fn, melee_root, require_fresh=False)
        debug_trace = backend_fidelity.trace_from_mwcc_debug_pcdump(
            pcdump_path.read_text(encoding="utf-8"),
            function=fn,
            source=src,
        )
        fidelity = backend_fidelity.compare_backend_traces(trace, debug_trace)
```

- [ ] **Step 5: Run adapter and fidelity tests**

Run:

```bash
cd tools/melee-agent
python -m pytest tests/test_retro_backend_debug_adapter.py tests/test_retro_backend_fidelity.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add tools/mwcc_retro/backend_fidelity.py \
  tools/melee-agent/src/cli/debug/retro.py \
  tools/melee-agent/tests/test_retro_backend_debug_adapter.py
git commit -m "feat(retro): compare backend trace with mwcc-debug"
```

---

### Task 13: Documentation And Skill Updates

**Files:**
- Modify: `docs/mwcc-retro.md`
- Modify: `docs/mwcc-retro-usage.md`
- Modify: `tools/mwcc_retro/README.md`
- Modify: `.claude/skills/mwcc-retro/SKILL.md`

- [ ] **Step 1: Check live-validation evidence before removing limitations**

Before replacing existing text that says exact retail GC/1.2.5n backend tracing is unavailable, verify that Task 11 Step 9 has passed and that Task 14 Steps 2, 3, and 4 have either passed or are documented as blocked with a `melee-agent issue report` command. If those commands have not run yet, add new docs sections that describe the command as experimental and keep existing limitation language intact.

- [ ] **Step 2: Update `docs/mwcc-retro.md` command section**

Add this block under Quick workflow:

```markdown
# Exact retail GC/1.2.5n backend/register-allocation trace
melee-agent debug retro backend src/melee/mn/mndiagram.c -f mnDiagram_UpdateScrollArrows

# Also compare against the patched debug-DLL pcdump facts
melee-agent debug retro backend src/melee/mn/mndiagram.c -f mnDiagram_UpdateScrollArrows --verify-debug
```

Add an output table row for:

```markdown
| `backend-trace.v1.json` | Normalized retail backend/regalloc facts, including `functions[].regalloc.classes[]` consumer subset | Backend GC/1.2.5n |
| `backend-events.v1.jsonl` | Raw chronological gdb events | Backend GC/1.2.5n |
| `regalloc-summary.txt` | Compact diff-friendly allocator summary | Backend GC/1.2.5n |
| `backend-fidelity.json` / `.txt` | Retail-vs-debug-DLL comparison | `--verify-debug` |
```

- [ ] **Step 3: Update `docs/mwcc-retro-usage.md` interpretation section**

Add:

```markdown
## Interpreting backend-trace.v1.json

Consumer tools should read `functions[].regalloc.classes[]`, not
`backend-events.v1.jsonl`. Numeric `ig_id` values are compile-scoped. Cross-source
comparisons should use first-def signatures, source attribution, and role
descriptors.

For normal colored GPR/FPR nodes, `color_decisions[]` includes ordered available
phys sets, blocked candidates with holder identity, volatile pool state,
nonvolatile dispense state, and the tie rule. Coalesced-away nodes appear as
explicit node rows with `color_status: "coalesced_alias"` and `coalesced_into`.
```

- [ ] **Step 4: Update `tools/mwcc_retro/README.md`**

Add the `backend` and `verify-backend` commands to the Commands section and mention the hard raw object-byte parity gate.

- [ ] **Step 5: Update `.claude/skills/mwcc-retro/SKILL.md` after validation evidence exists**

If Task 14 Steps 2, 3, and 4 passed, replace the current "Backend (GC/1.1 only today)" limitation in Quick Workflow with:

```markdown
# Exact retail 1.2.5n backend/regalloc trace
melee-agent debug retro backend src/melee/mn/mndiagram.c -f mnDiagram_UpdateScrollArrows

# Compare exact retail facts to the debug-DLL pcdump facts
melee-agent debug retro backend src/melee/mn/mndiagram.c -f mnDiagram_UpdateScrollArrows --verify-debug
```

Keep the GC/1.1 command as a donor/regression note, not as the target backend path.

If one of the live validations is blocked, keep the current limitation text and add a short blocked note with the exact issue id reported in Task 14 Step 5.

- [ ] **Step 6: Run docs grep checks**

Run:

```bash
rg -n "Backend \\(GC/1\\.1 only today\\)|1\\.2\\.5n backend is follow-on|use the DLL pcdump path for backend on 1\\.2\\.5n" docs tools/mwcc_retro .claude/skills/mwcc-retro/SKILL.md
```

Expected after successful live validation: no stale statements in current workflow docs claim 1.2.5n backend is unavailable. If a historical spec or findings doc appears, leave it unless it is a current workflow doc. Expected after a documented blocker: current workflow docs retain a limitation note and include the reported issue id.

- [ ] **Step 7: Commit**

```bash
git add docs/mwcc-retro.md docs/mwcc-retro-usage.md \
  tools/mwcc_retro/README.md .claude/skills/mwcc-retro/SKILL.md
git commit -m "docs(retro): document retail backend tracer"
```

---

### Task 14: Live Validation And Tooling Issue Reporting

**Files:**
- Modify if needed: `docs/mwcc-retro-usage.md`
- Generated outputs under `build/mwcc_retro/` are not committed.

- [ ] **Step 1: Ensure substrate is installed**

Run from repo root:

```bash
melee-agent debug retro setup
```

Expected: retrowin32 and cadmic paths printed, setup exits 0.

If setup fails because a tool is missing or a vendor build fails, report it:

```bash
melee-agent issue report "mwcc-retro setup failed during backend tracer validation" \
  --tool mwcc-retro --kind bug \
  --body "Command: melee-agent debug retro setup. Include the failing stdout/stderr and this worktree path."
```

- [ ] **Step 2: Validate matched function**

Run:

```bash
melee-agent debug retro backend src/melee/lb/lbarq.c -f lbArq_80014ABC --verify-debug
```

Expected:

- exit 0;
- `backend-trace.v1.json`, `backend-events.v1.jsonl`, `regalloc-summary.txt`, `backend-summary.txt`, `backend-fidelity.json`, and `backend-fidelity.txt` exist under `build/mwcc_retro/...`;
- `backend-fidelity.json` may report differences as data; default exit remains 0.

If the function name is absent, find a matched replacement:

```bash
melee-agent extract list --max-match 1.00 --module lb | head -20
```

Use the selected replacement in the validation note.

- [ ] **Step 3: Validate register-allocation-only mismatch**

Try:

```bash
melee-agent debug retro backend src/melee/mn/mnvibration.c -f mnVibration_80248644 --verify-debug
```

Expected: exit 0 and a `regalloc-summary.txt` that includes GPR or FPR decisions with structured blockers.

If that function is no longer present, choose a current high-percent regalloc residual:

```bash
rg -n "register allocation|regalloc|minor register" src/melee src/sysdolphin | head -30
```

Record the selected function and source path in the final validation note.

- [ ] **Step 4: Validate motivating mnDiagram case**

First resolve the current name:

```bash
rg -n "UpdateScrollArrows|ScrollArrows" src/melee config/GALE01/symbols.txt
```

If the function exists as `mnDiagram_UpdateScrollArrows`, run:

```bash
melee-agent debug retro backend src/melee/mn/mndiagram.c -f mnDiagram_UpdateScrollArrows --verify-debug
```

If it has a different current symbol, run the same command with the resolved symbol and record the mapping in `docs/mwcc-retro-usage.md`.

- [ ] **Step 5: Report hangs or missing affordances**

For any hang, interrupt it and report:

```bash
melee-agent issue report "mwcc-retro backend trace hung during validation" \
  --tool mwcc-retro --kind bug --function <function-name> \
  --body "Command, last visible output, timeout elapsed, worktree path, and whether backend-events.v1.jsonl was partially written."
```

For any confidence blocker, report:

```bash
melee-agent issue report "mwcc-retro backend tracer blocked by low-confidence retail struct field" \
  --tool mwcc-retro --kind bug --function <function-name> \
  --body "Missing/ambiguous field, candidate VAs/offsets, invariant that failed, and why no safe trace was emitted."
```

- [ ] **Step 6: Run focused test suite**

Run:

```bash
cd tools/melee-agent
python -m pytest \
  tests/test_retro_backend_schema.py \
  tests/test_retro_backend_summary.py \
  tests/test_retro_backend_events.py \
  tests/test_retro_backend_identity.py \
  tests/test_retro_object_parity.py \
  tests/test_retro_struct_map.py \
  tests/test_retro_backend_fidelity.py \
  tests/test_retro_backend_cli.py \
  tests/test_retro_backend_runtime.py \
  tests/test_retro_backend_debug_adapter.py \
  tests/test_retro_cli.py \
  tests/test_retro_trace_summary.py \
  tests/test_debug_cli_help_golden.py -k "retro or debug__retro" \
  -v
```

Expected: pass.

- [ ] **Step 7: Run repo-level build**

Run from repo root:

```bash
python configure.py && ninja
```

Expected: build passes.

- [ ] **Step 8: Commit validation/docs adjustments**

If validation required docs updates, commit them:

```bash
git add docs/mwcc-retro-usage.md docs/mwcc-retro.md
git commit -m "docs(retro): record backend tracer validation commands"
```

If no docs updates were needed, do not create an empty commit.

---

## Final Verification Checklist

- [ ] `python tools/worktree-doctor.py --fix` passes or reports no blocker.
- [ ] `melee-agent debug retro backend --help` documents exact retail GC/1.2.5n backend tracing.
- [ ] Consumer fixture validates with `backend_schema.validate_backend_trace`.
- [ ] Live matched-function trace exits 0 and emits all required output files.
- [ ] Live regalloc-mismatch trace exits 0 and includes structured color-decision pressure facts.
- [ ] `mnDiagram_UpdateScrollArrows` or its resolved current symbol is validated or blocked with evidence.
- [ ] `--verify-debug` writes fidelity reports and does not fail solely because retail/debug facts differ.
- [ ] Focused pytest suite passes.
- [ ] `python configure.py && ninja` passes.
- [ ] Any tooling bugs or hangs encountered are reported with `melee-agent issue report`.
