# Scheduler-Order Source Realizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded scheduler-order source-realizer transform family that materializes source probes from an explicit two-instruction scheduler-order target.

**Architecture:** Reuse `TransformProbe` and exact-span mutators. Keep the first slice targeted at `debug search plan-transforms`, not a full `debug solve scheduler-order` workflow. The target parser models mixed-opcode instruction pairs; the source realizer only emits conservative exact-span probes when the caller supplies a unique, safe source window.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `src.search.directed` transform-corpus modules.

---

### Task 1: Parser And Order Predicate

**Files:**
- Add: `tools/melee-agent/src/mwcc_debug/scheduler_order_realizer.py`
- Add: `tools/melee-agent/tests/test_scheduler_order_realizer.py`

- [x] Add dataclasses for scheduler-order instructions, targets, and evaluation results.
- [x] Parse mapping, JSON string, or path inputs with `kind == "scheduler-order-target"`, required `function`, required `target_first` and `target_second`, optional decimal/hex `code_offset`, and optional `desired_order`.
- [x] Reject malformed `desired_order` with `ValueError`, including non-string/unhashable elements.
- [x] Evaluate parsed asm lines for mixed-opcode pairs, supporting opcode, exact operands, substring operands, and optional code offsets.
- [x] Return explicit `target-order`, `observed-order`, `missing`, and `ambiguous` statuses.

### Task 2: Source Probe Family

**Files:**
- Modify: `tools/melee-agent/src/search/directed/mutators.py`
- Modify: `tools/melee-agent/src/search/directed/transform_corpus.py`
- Modify: `tools/melee-agent/src/mwcc_debug/source_transform_catalog.py`
- Modify: `tools/melee-agent/tests/search/directed/test_transform_corpus.py`
- Modify: `tools/melee-agent/tests/test_source_transform_catalog.py`

- [x] Add `scheduler_order_source_realizer` metadata to `DEFAULT_TRANSFORM_FAMILIES`.
- [x] Register exact-span mutators:
  - `scheduler_anchor_iv_init_before_bias`
  - `scheduler_split_float_cast_temp`
  - `scheduler_empty_barrier_before_float_cast`
- [x] Add `iter_scheduler_order_source_anchors()` for explicit `source_region.contains` windows.
- [x] Require each source-region string to identify one ordered window inside the target function; abstain when the window is ambiguous or unsafe.
- [x] Emit bounded #708-style probes in order:
  - IV init boundary anchor
  - split `f32 fi = (f32) i;`
  - empty `do { } while (0);` barrier before the float cast
- [x] Respect `max_per_family` caps.
- [x] Update source-transform catalog counts and directed mutator inventory.

### Task 3: CLI Plumbing

**Files:**
- Modify: `tools/melee-agent/src/search/cli/__init__.py`
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [x] Add `debug search plan-transforms --scheduler-order-target <json-file>`.
- [x] Make `--force-phys` optional when a scheduler-order target is provided.
- [x] Pass the parsed target into `generate_transform_probes()`.
- [x] When invoked with only a scheduler-order target and no force-phys/node-set evidence, emit only scheduler-order probes.
- [x] Add CLI smoke coverage that writes scheduler-order candidate files and records target assignments such as `mr before lfd`.

### Task 4: Verification

- [x] Run focused parser tests:

```bash
PYTHONPATH=tools/melee-agent pytest tools/melee-agent/tests/test_scheduler_order_realizer.py -q
```

- [x] Run focused transform and CLI tests:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py -k scheduler_order \
  tools/melee-agent/tests/search/test_cli_smoke.py -k scheduler_order \
  -q
```

- [x] Run affected suite:

```bash
PYTHONPATH=tools/melee-agent pytest \
  tools/melee-agent/tests/test_scheduler_order_realizer.py \
  tools/melee-agent/tests/search/directed/test_transform_corpus.py \
  tools/melee-agent/tests/search/test_cli_smoke.py \
  tools/melee-agent/tests/test_source_transform_catalog.py \
  -q
```

- [x] Run static checks:

```bash
python -m compileall -q tools/melee-agent/src
git diff --check
```

- [x] Smoke the installed entrypoint with a real `mnDiagram3_8024714C` scheduler target and verify it emits exactly three scheduler-order probes.
- [x] Request independent Codex spec and code-quality review.
- [ ] Commit, refresh editable `melee-agent`, resolve #708, release #699, and leave #618 open as a data-bank issue.

### Deferred

- Do not implement `debug solve scheduler-order` in this slice. A verified solver should come after the transform-corpus path proves useful and can reuse real compile/checkdiff extraction.
- Keep #699 open unless a future change produces a verified byte-match candidate for `mnDiagram2_Create`.
