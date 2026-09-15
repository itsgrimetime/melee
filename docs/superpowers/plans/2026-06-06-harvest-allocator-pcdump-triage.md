# harvest allocator pcdump triage - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` to implement this plan task by task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve #449 by routing register-allocator pcdump-proof rows through a
first-stage harvest triage harness.

**Architecture:** The feature is a harvest adapter around existing debug
tooling. `src.harvest` owns harness selection, pcdump preflight inclusion,
adapter command construction, and ledger translation. `debug target
match-iter-first` remains the allocator classifier.

**Tech Stack:** Python 3.11, Typer CLI command adapters, pytest regression
tests, existing pcdump cache helpers.

---

Spec: `docs/superpowers/specs/2026-06-06-harvest-allocator-pcdump-triage-design.md`
Issue: #449

## Files

- Modify: `tools/melee-agent/src/harvest.py`
- Modify: `tools/melee-agent/tests/test_harvest.py`
- Keep unrelated: `src/sysdolphin/baselib/hsd_3B34.c`

## Task 1 - Red tests

- [ ] Add a test that a `register-allocator` row with
  `source_actionability=pcdump-proof-needed` selects
  `allocator-pcdump-triage`.
- [ ] Add tests that explicit target-map harness override still wins and that
  non-`register-allocator` `mwcc-debug` rows do not select this harness.
- [ ] Add a test that the triage adapter command is exactly
  `["debug", "target", "match-iter-first", "-f", "demo_fn", "--regs", "gpr-callee,gpr-volatile,r0", "--json"]`.
- [ ] Add a test that `run_harvest("register-allocator", ...)` preflights
  `debug dump setup` and `debug dump local <source> --function <fn>` before the
  triage command when the pcdump cache is missing.
- [ ] Add a test that a `needs-move` actionability payload produces
  `status=blocked`, `blocker=allocator-target-vector`, and preserves
  `force_vector`.
- [ ] Add a test that an `already-satisfied` actionability payload produces
  `status=blocked`, `blocker=source-lifetime-callee-save-shape`.
- [ ] Add tests for `current-unknown`, non-runnable/conflicted vectors, and
  `needs-move` with `force_vector_recommended=false`.
- [ ] Add a test that a malformed or missing actionability payload produces
  `blocker=allocator-triage-unclassified` instead of
  `no-validated-candidate`.
- [ ] Add a test that `apply=True` for allocator triage still records a
  diagnostic blocker and does not attempt source application.

Run:

```bash
cd tools/melee-agent
python -m pytest \
  tests/test_harvest.py::test_allocator_pcdump_triage_selects_harness \
  tests/test_harvest.py::test_allocator_pcdump_triage_builds_match_iter_first_command \
  tests/test_harvest.py::test_run_harvest_prefetches_allocator_pcdump_triage \
  tests/test_harvest.py::test_allocator_pcdump_triage_records_target_vector_blocker \
  tests/test_harvest.py::test_allocator_pcdump_triage_records_source_lifetime_blocker \
  tests/test_harvest.py::test_allocator_pcdump_triage_unclassified_payload_is_blocked \
  -q
```

Expected before implementation: failures from missing harness selection and
missing translator.

## Task 2 - Harness selection and preflight

- [ ] Add `HARNESS_ALLOCATOR_PCDUMP_TRIAGE` and register it.
- [ ] Extend `select_harness()` for `register-allocator` pcdump-proof rows while
  preserving explicit target-map overrides.
- [ ] Extend `_needs_pcdump_preflight()` so allocator triage rows use the
  existing pcdump setup/local generation path.
- [ ] Run the Task 1 selection/preflight tests and confirm they pass.

## Task 3 - Adapter and ledger translator

- [ ] Add `_allocator_pcdump_triage_command(request)` returning
  `debug target match-iter-first -f <function> --regs gpr-callee,gpr-volatile,r0 --json`.
- [ ] Add `_allocator_pcdump_triage_result(request, command, payload)` that
  implements the spec's blocker mapping and details preservation.
- [ ] Call the translator from both `run_harvest_request()` and composed layer
  execution before normal source-candidate parsing.
- [ ] Run the full Task 1 test command and confirm it passes.

## Task 4 - Verification and issue resolution

- [ ] Run the full harvest test module:

```bash
cd tools/melee-agent
python -m pytest tests/test_harvest.py -q
```

- [ ] Run Python compile and CLI smoke checks:

```bash
python -m py_compile tools/melee-agent/src/harvest.py
cd tools/melee-agent && python -m src.cli harvest --help
cd tools/melee-agent && python -m src.cli debug target match-iter-first --help
git diff --check
```

- [ ] Stage only the spec, plan, harvest code, and harvest tests.
- [ ] Commit the feature.
- [ ] Resolve #449 only after tests and smoke checks pass.
