# Source Lifetime And Downhill Hunk Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve #807 and #808 by making source-lifetime pure-helper handling and select-order downhill hunk repair source-actionable.

**Architecture:** Extend existing probe generators instead of adding a new command. `pressure_explorer` owns source-lifetime helper metadata; `search.structure` and `search.cli` pass helper overrides through; `debug select-order-search` adds subtractive repair probes only inside guard repair.

**Tech Stack:** Python, Typer CLI, pytest, existing `LifetimeLayoutProbe` and select-order scoring helpers.

---

### Task 1: Source-Lifetime Pure Helper Metadata

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/pressure_explorer/__init__.py`
- Modify: `tools/melee-agent/src/search/structure/__init__.py`
- Modify: `tools/melee-agent/src/search/cli/__init__.py`
- Test: `tools/melee-agent/tests/test_pressure_explorer.py`
- Test: `tools/melee-agent/tests/search/test_structure.py`
- Test: `tools/melee-agent/tests/search/test_cli_smoke.py`

- [ ] Write failing tests for default `GetNameText` repeated-helper reuse, explicit `ExternalPure=u8` override, and CLI pass-through of `--pure-helper`.
- [ ] Run the focused tests and confirm they fail because the helper is still blocked or the CLI option is unknown.
- [ ] Replace the one-entry read-only helper set with return-type metadata and pass optional helper overrides from structure/CLI callers.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Downhill Hunk Subtractive Guard Repair

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/__init__.py`
- Test: `tools/melee-agent/tests/test_select_order_search.py`

- [ ] Write failing tests for a pure helper that generates per-hunk revert probes and for a select-order guard-repair campaign that scores one of those probes.
- [ ] Run the focused tests and confirm failure because no subtractive probes exist.
- [ ] Add a small source diff helper that emits `LifetimeLayoutProbe` rows for individual hunk reverts and local `u8`/`int` declaration variants.
- [ ] Feed those probes into guard repair before generic probes, preserving existing ledger and scoring fields.
- [ ] Run the focused select-order tests and confirm they pass.

### Task 3: Verification And Queue Closure

**Files:**
- Issue queue only, no source files.

- [ ] Run focused pytest coverage for pressure explorer, structure, CLI smoke, and select-order search.
- [ ] Run CLI smoke checks for `debug search structure --help` and `debug select-order-search --help`.
- [ ] Refresh the editable `melee-agent` install from `/Users/mike/code/melee`.
- [ ] Resolve #807 and #808 with notes naming the commit and tests.
- [ ] Verify `master` state and issue queue state before final response.
