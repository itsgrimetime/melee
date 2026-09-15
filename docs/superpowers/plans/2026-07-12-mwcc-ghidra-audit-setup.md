# MWCC Ghidra Audit Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a discoverable, bounded, self-validating setup path for the exact GC/1.2.5n compiler Ghidra project.

**Architecture:** A focused Python runner owns Ghidra detection, native-architecture preflight, exact compiler identity, process-group timeout, project validation, and retained repair. A Ghidra Java post-script emits the accepted validation marker. The existing shell entry point delegates to a new `debug retro ghidra-setup` CLI leaf.

**Tech Stack:** Python 3.11, Typer, Ghidra headless/Java `GhidraScript`, pytest, existing `_run_with_process_group_timeout` and Ghidra install detection.

## Global Constraints

- Compiler SHA-256: `ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`.
- Default project directory/name/program: `tools/mwcc_debug/ghidra_project`, `mwcceppc`, `/mwcceppc.exe`.
- Default Ghidra analysis timeout is 300 seconds; outer wall timeout is 420 seconds.
- macOS requires a host-native Ghidra `decompile` executable.
- Reuse/import requires exact executable SHA and function count greater than zero; `.rep` existence is insufficient.
- `--repair` retains invalid `.gpr`, `.rep`, and `.lock` artifacts under one `.invalid-YYYYmmddTHHMMSSZ` suffix.
- The shell entry point delegates to branch-local Python and contains no second implementation.

---

### Task 1: Bounded validated MWCC Ghidra runner

**Files:**
- Create: `tools/melee-agent/src/mwcc_debug/ghidra_mwcc_setup.py`
- Create: `tools/mwcc_debug/scripts/MwccAuditStatus.java`
- Create: `tools/melee-agent/tests/test_ghidra_mwcc_setup.py`

**Interfaces:**
- Produce `EXPECTED_COMPILER_SHA256` with the exact global value.
- Produce immutable `MwccGhidraSetupResult` fields: `status`, `ghidra_install`, `headless_path`, `native_decompiler_path`, `compiler_path`, `compiler_sha256`, `project_dir`, `project_name`, `program_path`, `function_count`, `elapsed_seconds`, `quarantined_paths`; `to_dict()` uses schema `mwcc-ghidra-setup.v1`.
- Produce `setup_mwcc_ghidra(*, melee_root, project_dir, analysis_timeout, wall_timeout, repair, detect_install=..., runner=..., now=...)`.
- Produce `MwccGhidraSetupError(reason, details)` with stable reasons.

- [ ] **Step 1: Write failing runner tests**

Create tests for host-native preflight, exact compiler SHA, missing-project import plus validation, valid-project idempotence, empty `.rep` rejection, retained repair with one suffix, process timeout, exit-zero `Analysis timed out` rejection, exact marker SHA/positive count, and stable result JSON. The fake validation output is exactly:

```text
MWCC_AUDIT_STATUS {"sha256":"ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c","function_count":3248}
```

Run `python -m pytest --no-cov -q tools/melee-agent/tests/test_ghidra_mwcc_setup.py`; expect import failure before implementation.

- [ ] **Step 2: Implement `MwccAuditStatus.java`**

Create a no-package `MwccAuditStatus extends GhidraScript`. Require exactly one expected-SHA argument and non-null program. Compare `currentProgram.getExecutableSHA256()` case-insensitively, require `currentProgram.getFunctionManager().getFunctionCount() > 0`, throw on mismatch, and print the exact `MWCC_AUDIT_STATUS` JSON marker.

- [ ] **Step 3: Implement preflight and process classification**

Resolve `support/analyzeHeadless`, compiler, script, and host-native decompiler. Hash the compiler before launch. Use only the injected process-group runner with `wall_timeout`. Reject nonzero exit, runner timeout, `Analysis timed out`, cancellation, or `Abort due to Headless analyzer error`.

- [ ] **Step 4: Implement validation, import, and repair**

Validation command:

```text
analyzeHeadless PROJECT_DIR mwcceppc -process mwcceppc.exe -noanalysis
  -scriptPath SCRIPT_DIR -postScript MwccAuditStatus.java EXPECTED_SHA
```

Import command:

```text
analyzeHeadless PROJECT_DIR mwcceppc -import COMPILER
  -analysisTimeoutPerFile ANALYSIS_TIMEOUT
```

Create a missing project directory. Validate any existing canonical project artifact before reuse. Without repair, invalid state raises `invalid-existing-project`. With repair, move every present canonical `.gpr`, `.rep`, and `.lock` to the same injected UTC suffix using `os.replace`, then import and validate. Return `ready`, `imported`, or `repaired` accurately.

- [ ] **Step 5: Verify and commit Task 1**

Run:

```bash
python -m pytest --no-cov -q tools/melee-agent/tests/test_ghidra_mwcc_setup.py
python -m ruff check tools/melee-agent/src/mwcc_debug/ghidra_mwcc_setup.py tools/melee-agent/tests/test_ghidra_mwcc_setup.py
git diff --check
```

Commit the three Task 1 files as `feat: validate MWCC Ghidra audit projects`.

---

### Task 2: CLI, compatibility launcher, and discoverability

**Files:**
- Modify: `tools/melee-agent/src/cli/debug/retro.py`
- Modify: `tools/melee-agent/src/cli/capabilities.py`
- Modify: `tools/melee-agent/tests/test_retro_cli.py`
- Modify: `tools/melee-agent/tests/test_capabilities.py`
- Modify: `tools/mwcc_debug/scripts/setup_ghidra.sh`
- Create: `tools/melee-agent/tests/test_mwcc_ghidra_setup_script.py`
- Modify: `.claude/skills/mwcc-retro/SKILL.md`
- Modify: `docs/mwcc-retro.md`

**Interfaces:**
- Consume Task 1 `setup_mwcc_ghidra()` and `MwccGhidraSetupError`.
- Produce `melee-agent debug retro ghidra-setup [--project-dir PATH] [--analysis-timeout 300] [--wall-timeout 420] [--repair] [--json]`.
- Produce branch-local shell delegation using `PYTHONPATH=tools/melee-agent python -m src.cli`.

- [ ] **Step 1: Write failing surface tests**

Add tests that retro help lists the command, exact defaults reach the runner, JSON renders the result schema, invalid existing state prints the `--repair` retry, capability search finds `MWCC Ghidra compiler audit`, and the shell launcher forwards `--repair --json` plus branch-local `PYTHONPATH` to a fake Python. Run the named tests and verify RED.

- [ ] **Step 2: Add Typer command and rendering**

Validate positive timeouts, resolve relative project directories against the Melee root, and call Task 1. JSON is `json.dumps(result.to_dict(), sort_keys=True)`. Text reports status, exact hash, count, project, Ghidra/native paths, elapsed seconds, and quarantine paths. Stable setup errors exit 4; `invalid-existing-project` includes an exact retry with `--repair`.

- [ ] **Step 3: Delegate shell and add discoverability**

Replace shell implementation with repo-root discovery and:

```bash
PYTHONPATH="${MELEE_ROOT}/tools/melee-agent${PYTHONPATH:+:${PYTHONPATH}}" \
  python -m src.cli debug retro ghidra-setup "$@"
```

Map capability aliases `MWCC Ghidra compiler audit` and `stripped compiler callsite audit` to the new command. Update the mwcc-retro skill and docs to prohibit archived hard-coded Ghidra paths and require the CLI before compiler audits.

- [ ] **Step 4: Verify Task 2**

Run focused tests covering the new runner/surfaces plus existing `test_retro_cli.py`, `test_capabilities.py`, `test_ghidra_detect.py`, and `test_ghidra_project.py`; run scoped Ruff, `bash -n tools/mwcc_debug/scripts/setup_ghidra.sh`, and `git diff --check`.

- [ ] **Step 5: Run real acceptance**

From `tools/melee-agent`, run branch-local CLI with `--melee-root ../../.. --project-dir build/ghidra-audit-1239-acceptance --analysis-timeout 300 --wall-timeout 420 --json`. First run must be `imported` with exact SHA and positive count; second run must be `ready` with the same SHA/count and no import analysis. Confirm no Java/decompiler child remains, then run `python configure.py && ninja` at the worktree root.

- [ ] **Step 6: Commit Task 2**

Commit the Task 2 files as `feat: expose bounded MWCC Ghidra setup`.

After both tasks, independently review the branch against the design, rerun verification, merge to `master`, resolve #1239 with the modern import evidence, and recheck #1240.
