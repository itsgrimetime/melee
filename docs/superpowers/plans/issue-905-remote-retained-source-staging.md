# Fix 905: Remote retained-source staging for diagnostics candidates

## Scope

Issue #905 is about tooling, not Melee source matching. The failure path is:

1. `debug target score-source <retained diagnostics .c> --cflags-from src/... --retain-pcdump --json` is correctly stopped by the #904 unsafe local pcdump lane guard when an unreaped UE `wibo` already exists.
2. The attempted manual fallback, `debug dump remote build/diagnostics/.../gr1-0024...c --output ... --timeout 90 --no-pull`, exits 66 because the Windows checkout does not contain that local retained diagnostics source.
3. The matcher has no remote score-source path that can upload/stage the retained source, compile it as the real TU, score the returned pcdump, and emit either `pcdump_path`/`target_score`/guard data or a terminal blocker.

This plan intentionally does not edit production or test files. It was written against the current dirty checkout in `/Users/mike/code/melee`; do not revert unrelated dirty files.

## Reviewed Code

- `tools/melee-agent/src/cli/debug/__init__.py:2270` has `_resolve_src_relative`, which proves the local `.c` file exists and returns a repo-relative path, but does not make that file available on the remote host.
- `tools/melee-agent/src/cli/debug/__init__.py:2356` defines `debug dump remote`. It resolves one `c_file`, builds a Windows `ssh` command, and passes that relative path directly to `run_pcdump.ps1` at `tools/melee-agent/src/cli/debug/__init__.py:2845`. There is no `--unit-source`, no retained-source upload, and no staging/cleanup contract.
- `tools/mwcc_debug/win/run_pcdump.ps1:277` joins the received source path under the remote repo and exits 66 at `tools/mwcc_debug/win/run_pcdump.ps1:279` when it does not exist. It then compiles `$srcAbs` directly at `tools/mwcc_debug/win/run_pcdump.ps1:287`.
- Local retained-source behavior already exists in `score-source`: `_score_source_should_stage_through_unit` at `tools/melee-agent/src/cli/debug/__init__.py:20446` and `_score_source_compile_source_rel` at `tools/melee-agent/src/cli/debug/__init__.py:20460` copy a non-`src/` candidate into the real `src/...` TU, compile that real TU path, and restore the source.
- The #904 unsafe-lane guard includes retained sibling/diagnostics prefixes through `_score_source_related_prefixes` and `_score_source_unsafe_lane_payload` at `tools/melee-agent/src/cli/debug/__init__.py:20352`.
- `score-source` parses and scores a pcdump, retains it, and optionally includes the structural guard at `tools/melee-agent/src/cli/debug/__init__.py:20761` through `tools/melee-agent/src/cli/debug/__init__.py:20875`.
- `debug dump local --unit-source` already distinguishes probe source from real TU flags/cache identity at `tools/melee-agent/src/cli/debug/__init__.py:18880` and compiles the probe with the real TU settings at `tools/melee-agent/src/cli/debug/__init__.py:18990`.
- Existing tests to extend are in `tools/melee-agent/tests/test_debug_cli_reorg.py`: remote command construction around line 4902, local unsafe-lane tests around line 5336, and local retained diagnostics staging around line 5927.

## Root Cause

The root cause is an asymmetric staging contract. Local `score-source` knows that a retained diagnostics candidate is not a real build edge and stages it through the source TU named by `--cflags-from`. Remote `debug dump remote` only knows how to compile a path that already exists in the Windows checkout. It receives `build/diagnostics/.../gr1-0024...c`, asks the remote repo for that exact file, and the PowerShell script fails before compilation.

The second gap is orchestration: `debug target score-source` can report an unsafe local lane, but it cannot continue by using `debug dump remote` internally. A human or matcher has to try the remote dump manually, and the manual dump lacks retained-source staging.

## Implementation Approaches

### Approach A: Copy retained candidates to the same remote `build/diagnostics/...` path

Upload the local retained source to the remote checkout at the same relative path, create parent directories, and compile that path directly.

Pros:
- Smallest conceptual change to the failing command.
- Does not temporarily overwrite `src/...`.

Cons:
- It does not actually use the real TU path. Quote-include behavior can differ from `src/melee/...`.
- Cache identity and diagnostics are tied to `build/diagnostics/...`, not the real unit.
- The PowerShell script hardcodes standard flags and does not derive per-unit build details from arbitrary diagnostics paths.

Verdict: reject. It fixes the missing file symptom but not the retained-source semantics.

### Approach B: Stream retained source over SSH stdin and stage it into the real remote TU

Local CLI resolves the retained source and real unit (`--unit-source` for `debug dump remote`, `--cflags-from` for `score-source`). If the source is non-`src/` and the unit is `src/...`, it sends the retained source bytes to `run_pcdump.ps1` over stdin and passes the real `src/...` path as the script argument. The PowerShell script, under its existing lock, backs up the real TU bytes, writes the staged bytes to that TU, compiles, emits the pcdump, and restores the original bytes in `finally`.

Pros:
- Mirrors local `_score_source_compile_source_rel`.
- Preserves real TU include behavior and compile identity.
- Avoids Windows command-line/env-size limits by streaming source over stdin.
- One remote lock owns staging, compile, DLL restore, source restore, and lock release.
- Gives `score-source` one helper to reuse for remote fallback.

Cons:
- Briefly mutates the remote checkout/worktree.
- Requires careful PowerShell `finally` cleanup and tests around restore.

Verdict: recommended.

### Approach C: Create a temporary remote worktree/copy for each retained candidate

Create or clone a separate remote worktree per candidate, write the retained source into that worktree's real TU path, compile, then delete it.

Pros:
- Strongest isolation from the remote master/worktree checkout.
- Cleanup failure cannot leave the primary remote checkout dirty.

Cons:
- Slow and disk-heavy for a fallback path that may run many candidates.
- More branch/worktree sync complexity.
- Duplicates existing remote lock/sync responsibilities.

Verdict: overkill for this issue.

## Recommended Design

Implement Approach B.

### 1. Add a shared remote pcdump helper in `tools/melee-agent/src/cli/debug/__init__.py`

Introduce an internal helper, for example `_run_remote_pcdump(...)`, that centralizes remote command construction and execution for both `debug dump remote` and remote score-source:

- Inputs: `source_rel`, `compile_source_rel`, optional `stage_source_path`, `timeout`, `host`, `remote_script`, `branch`, `no_pull`, force/debug override options, and whether to capture or stream stderr.
- If `stage_source_path` is set, read bytes locally and launch `ssh` with `stdin=subprocess.PIPE`.
- The helper must have an explicit stdin contract:
  - streaming `debug dump remote` path writes all staged bytes to `proc.stdin`,
    closes stdin, then reads stdout in the existing loop;
  - captured `score-source` path may use `communicate(input=...)`;
  - both paths handle `BrokenPipeError` as a remote failure with stderr/stdout
    tails where available.
- Set env vars with `_cmd_set_env`:
  - `MWCC_DEBUG_TIMEOUT_SECS`
  - existing force/debug env vars
  - `MWCC_DEBUG_NO_PULL` when requested
  - `MWCC_DEBUG_BRANCH` when requested
  - `MWCC_DEBUG_STAGE_SOURCE_STDIN=1`
  - `MWCC_DEBUG_STAGE_SOURCE_LABEL=<local retained rel>` for diagnostics only
- Pass `compile_source_rel` as the PowerShell script argument, not the retained source path.
- Preserve the existing stdout streaming behavior for `debug dump remote`, but allow score-source to capture the pcdump text in memory.

### 2. Extend `debug dump remote`

Add options:

- `--unit-source`: real same-TU source file to compile through, matching local `debug dump local --unit-source`.
- Optional alias `--cflags-from` can point to the same parameter for users coming from `score-source`.
- Optional `--function` for inference and better diagnostics.

Resolution rules:

- If `c_file` resolves under `src/`, default `compile_source_rel = source_rel`.
- If `c_file` is non-`src/` and `--unit-source` is provided, compile through that unit and stage the retained source bytes.
- If `c_file` is non-`src/` and no unit is provided, infer the unit conservatively by reading the candidate:
  - if `--function` is supplied, map that function through `_find_unit_for_function` first;
  - otherwise use `src.mwcc_debug.source_patch.find_function_definitions` and map every report-backed definition through `_find_unit_for_function`;
  - accept only when all report-backed definitions resolve to exactly one unit, which allows static helpers before the real function and multiple functions from the same TU;
  - fail with a clear `BadParameter` telling the user to pass `--unit-source` when there is no report-backed definition or more than one unit.

Cache behavior:

- Treat any staged source as a diagnostic run.
- If no `--output` is supplied, write to a scratch pcdump path instead of the canonical `build/mwcc_debug_cache/<unit>.txt`.
- Never update the baseline cache or its content-hash sidecar for staged/retained remote runs.

This makes the exact failing manual command work when inference succeeds, while also providing an explicit `--unit-source src/melee/mn/mndiagram.c` path.

### 3. Extend `run_pcdump.ps1`

Add a retained-source staging contract:

- Document env vars:
  - `MWCC_DEBUG_STAGE_SOURCE_STDIN=1`
  - `MWCC_DEBUG_STAGE_SOURCE_LABEL=<diagnostic source label>`
- After repo sync and after the real source path is resolved, if staging is enabled:
  - Read raw stdin bytes via `[Console]::OpenStandardInput()`.
  - Fail with a clear code, likely 66 or 64, if no staged source bytes are provided.
  - Backup original `$srcAbs` bytes with `[System.IO.File]::ReadAllBytes`.
  - Write staged bytes to `$srcAbs`.
  - Emit stderr diagnostics showing the retained label and real TU path.
- Initialize staged-source backup variables before post-lock work and wrap source staging, DLL install, compile, pcdump emission, source restore, DLL restore, and lock release in one outer `try/finally`.
- Ensure source restore runs before removing the lock:
  - If original bytes were backed up, write them back with `[System.IO.File]::WriteAllBytes`.
  - Restore even when staging succeeds but compile setup fails, compile fails, pcdump is missing, stdout emission fails, or the script exits nonzero after partial output.

Keep staging under the existing remote lock so concurrent remote pcdump runs cannot observe a half-staged source.

### 4. Add remote score-source fallback

Add explicit score-source options, preserving current default behavior:

- `--remote`: score through the remote pcdump backend directly.
- `--remote-fallback`: use remote only when the local unsafe-lane guard blocks the local pcdump compile.
- `--remote-host`, `--remote-script`, `--remote-branch`, `--remote-no-pull` mirroring `debug dump remote`.

Behavior:

- Normal local score-source remains unchanged unless `--remote` or `--remote-fallback` is supplied.
- `--remote` must bypass local `wibo` and local debug compiler discovery entirely. Move local tool resolution until after deciding that a local compile will actually run.
- `--remote-fallback` should use the local path by default when there is no unsafe local lane; the fallback only invokes remote when `_score_source_unsafe_lane_payload` blocks local pcdump.
- When `--remote-fallback` is triggered by an unsafe lane, remote fallback must not be blocked by local compiler setup that would otherwise be needed only for local pcdump execution.
- On unsafe local lane with `--remote-fallback`, call the shared remote pcdump helper with:
  - `source_rel=<retained diagnostics rel>`
  - `compile_source_rel=<cflags_unit_rel>`
  - `stage_source_path=<local retained source path>` when `_score_source_should_stage_through_unit(...)` is true
- Parse and score the returned pcdump with the existing `parse_pcdump`, `parse_hook_events`, `find_function`, `score_function`, and `_score_source_target_details` logic.
- Honor `--retain-pcdump` and `--pcdump-output`; write the remote pcdump to the same retained path contract currently used locally.
- If `--checkdiff-guard` is set, run the existing local structural guard after remote scoring. This is safe because it uses `ninja`/`checkdiff`, not local `wibo`.
- JSON success payload should include:
  - `score`
  - `target_score`
  - `pcdump_path` when retained
  - `structural_guard` / `structural_guard_error` when requested
  - `remote_fallback` metadata: `used`, `reason`, `host`, `source`, `compile_source`, `staged_source`, `returncode`
  - the original `unsafe_local_pcdump_lane` when fallback was triggered by it

Failure payload:

- If remote fallback cannot produce a pcdump or cannot stage/restore, return `score = 2**30` and include:
  - `error`
  - `returncode`
  - `stderr_tail` / `stdout_tail` where available
  - `terminal_blocker = "remote-retained-source-staging-failed"` or `"remote-pcdump-failed"`
  - `remote_fallback` metadata
  - original `unsafe_local_pcdump_lane`

This satisfies the issue stop condition: after local unsafe-lane blocking, the tool either scores the staged candidate remotely or emits a populated terminal blocker without requiring manual reboot.

## Regression Tests First

Add these tests before production changes.

1. `test_dump_remote_retained_source_stages_stdin_through_unit_source`
   - Location: `tools/melee-agent/tests/test_debug_cli_reorg.py`.
   - Create a temp repo with `src/melee/mn/sample.c` and `build/diagnostics/case/candidate.c`.
   - Monkeypatch `DEFAULT_MELEE_ROOT`, `_resolve_src_relative`, and `subprocess.Popen`.
   - Invoke `debug dump remote build/diagnostics/case/candidate.c --unit-source src/melee/mn/sample.c --output <tmp> --no-pull`.
   - Assert the remote command sets `MWCC_DEBUG_STAGE_SOURCE_STDIN=1`, passes `src/melee/mn/sample.c` to PowerShell, sends the retained source bytes on stdin, and writes the pcdump output.

2. `test_dump_remote_retained_source_infers_unit_from_candidate_function`
   - Candidate source defines a function known to `_find_unit_for_function`.
   - Omit `--unit-source`.
   - Assert the command still compiles `src/<unit>.c` and stages the candidate.
   - Add a companion ambiguous/no-unit test that fails with a clear `--unit-source` hint.
   - Add unit-inference matrix coverage:
     - static helper before a report-backed function is accepted;
     - multiple report-backed functions from the same unit are accepted;
     - multiple report-backed functions from different units fail with the `--unit-source` hint;
     - explicit `--function` takes precedence over first-definition heuristics.

3. `test_dump_remote_staged_source_skips_default_cache`
   - Invoke staged `debug dump remote` without `--output`.
   - Monkeypatch the scratch path if needed.
   - Assert canonical `build/mwcc_debug_cache/<unit>.txt` and its content-hash sidecar are not created or overwritten.

4. `test_run_pcdump_script_supports_stdin_staging_and_restore`
   - Static test, matching the existing PowerShell script tests.
   - Assert `run_pcdump.ps1` documents `MWCC_DEBUG_STAGE_SOURCE_STDIN`, reads `[Console]::OpenStandardInput()`, backs up `$srcAbs`, writes staged bytes before compile, restores original bytes in `finally`, and releases the lock after restore.
   - Assert restore ordering by checking the source restore block appears before the lock removal block and that staging/compile/output are inside the same cleanup region.

5. `test_target_score_source_remote_fallback_scores_retained_candidate_when_local_lane_unsafe`
   - Local guard returns an unsafe lane.
   - Local pcdump runner must not be called.
   - Fake the remote pcdump helper to return a pcdump containing the requested function.
   - Monkeypatch scoring to return a small score.
   - Invoke `debug target score-source <retained> --cflags-from src/melee/mn/sample.c --target <json> --remote-fallback --retain-pcdump --json`.
   - Assert JSON includes `score`, `target_score`, `pcdump_path`, `remote_fallback.used=true`, and the original `unsafe_local_pcdump_lane`.

6. `test_target_score_source_remote_fallback_runs_checkdiff_guard`
   - Same as test 5, with `--checkdiff-guard`.
   - Monkeypatch `_score_source_candidate_real_tree` to return structural guard data.
   - Assert the guard appears in the JSON payload.

7. `test_target_score_source_remote_fallback_reports_terminal_blocker`
   - Local guard returns unsafe.
   - Fake remote helper returns exit 66 or no pcdump.
   - Assert JSON returns penalty score, `terminal_blocker`, remote return code/stderr tail, `remote_fallback` metadata, and the original unsafe-lane payload.

8. `test_target_score_source_remote_mode_skips_local_tool_discovery`
   - Invoke `score-source --remote --json`.
   - Monkeypatch `_find_wibo` and `_find_compiler_dir` to fail if called.
   - Fake the remote pcdump helper to return a valid pcdump and assert scoring succeeds.

9. `test_target_score_source_remote_fallback_uses_local_when_lane_safe`
   - Invoke `score-source --remote-fallback --json` with no unsafe lane.
   - Assert the local compile runner is used and the remote helper is not called.

Suggested focused test command:

```bash
python -m pytest tools/melee-agent/tests/test_debug_cli_reorg.py \
  -k 'dump_remote_retained or target_score_source_remote_fallback or run_pcdump_script'
```

## Implementation Order

1. Add the tests above and confirm they fail for the intended reasons.
2. Refactor remote command construction into a helper without changing existing behavior.
3. Add `run_pcdump.ps1` stdin staging and restore.
4. Add `debug dump remote --unit-source` plus retained-source inference and staged cache-skipping.
5. Add `score-source --remote` / `--remote-fallback` using the shared remote pcdump helper.
6. Run focused pytest.
7. Run existing related tests:

```bash
python -m pytest tools/melee-agent/tests/test_debug_cli_reorg.py \
  -k 'dump_remote or target_score_source'
```

8. If feasible, run one live smoke test against a harmless small TU with `--output <scratch>` and `--no-pull`, then a retained candidate with `--unit-source`.

## Acceptance Criteria

- The exact #905 class of retained diagnostics source no longer dies at remote exit 66 solely because the retained file is local-only.
- `debug dump remote <retained.c> --unit-source src/... --output ...` stages retained text remotely, compiles the real TU path, writes the pcdump, and restores the remote source.
- `debug target score-source <retained.c> --cflags-from src/... --remote-fallback --retain-pcdump --json` can continue after local `unsafe_local_pcdump_lane` and returns `pcdump_path` plus `target_score`.
- If remote fallback fails, JSON contains a populated terminal blocker with enough detail to stop the matcher cleanly.
- Staged remote runs do not update the canonical pcdump cache.
- Existing local score-source behavior and unsafe-lane guard behavior remain unchanged by default.
