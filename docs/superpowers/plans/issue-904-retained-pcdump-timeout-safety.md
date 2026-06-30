# Issue #904: retained pcdump handoff and timeout restore safety

## Scope and constraints

- Review target: `/Users/mike/code/melee`, current dirty worktree.
- Do not assume the uncommitted edits are ours. Preserve the existing dirty files:
  - `tools/melee-agent/src/cli/debug/__init__.py`
  - `tools/melee-agent/src/cli/scratch/__init__.py`
  - `tools/melee-agent/src/cli/sync/production.py`
  - `tools/melee-agent/src/search/solver/solve.py`
  - `tools/melee-agent/tests/search/solver/test_solve.py`
  - `tools/melee-agent/tests/test_scratch.py`
  - `docs/matching-tooling-postmortem-2026-06-15.md`
- This plan only covers production/test changes to make later; it does not make them now.

## Reviewed code paths

- `tools/melee-agent/src/cli/debug/__init__.py`
  - `pcdump_local` at lines ~18547-19848
  - `score_source` and `_score_source_compile_source_rel` at lines ~20461-20840
  - `_score_source_candidate_real_tree` at lines ~25731-26230
  - source restore helpers at lines ~24715-25065
  - select-order retained scoring at lines ~38413-40390
  - source-bridge summary/handoff helpers at lines ~31168-32520
- `tools/melee-agent/src/search/cli/__init__.py`
  - `_run_triage_score_command`, `_combine_candidate_pair`, `combine_cmd` at lines ~2609-2970 and ~3313-3428
- `tools/melee-agent/src/mwcc_debug/diff_capture.py`
  - `compile_source_variant` and `_run_with_process_group_timeout` at lines ~186-290 and ~601-720
- `tools/melee-agent/src/mwcc_debug/local_safety.py`
  - retained-candidate lane detection and unsafe UE `wibo` refusal.
- Existing tests reviewed:
  - `tools/melee-agent/tests/test_debug_cli_reorg.py` unsafe retained lane and real-TU staging tests around lines ~5543-6044
  - `tools/melee-agent/tests/test_select_order_search.py` source-bridge, pcdump preservation, timeout, and restore tests around lines ~5320-5705 and ~9162-9969
  - `tools/melee-agent/tests/search/test_cli_smoke.py` combine tests around lines ~2428-2541
  - `tools/melee-agent/tests/test_pressure_explorer.py` real-TU staging/restore tests around lines ~5992-6350

## Root cause

There are three related failures.

1. `debug target score-source` is the safe continuation lane for retained sources because `_score_source_compile_source_rel` stages non-`src/` candidates through the real TU under the source-scoring lock and restores in `finally`. But `score_source` reads its generated `pcdump_score_*.txt` and immediately unlinks it. A successful recombine score can therefore prove an IG hit but leaves no retained pcdump for the next protected continuation.

2. `debug search combine` delegates scoring to `--score-command` and stores the result under `score_result.parsed_json`, but it does not promote handoff fields such as `pcdump_path`, `target_score`, or a continuation command to the combination row. Even if `score-source` starts emitting a retained pcdump, combine users would still have to dig into nested scorer JSON unless combine lifts those fields.

3. `debug select-order-search` currently skips `_select_order_source_bridge_summary` entirely on command timeout and emits `source_bridge_summary.status = "skipped-timeout"`. That hides ranked retained candidates, pcdump paths, score commands, and recombine/continuation actions exactly when a partial timeout result is the only available frontier. The command-level restore guard is present, but success JSON does not report `source_restored`, so timeout/hang safety is not externally verifiable.

Secondary safety point: direct `debug dump local retained.c --unit-source src/...` compiles the retained candidate path directly. After a UE `wibo`, `score-source` has related-prefix guards for sibling retained candidates and the real TU, but `pcdump_local` only guards the exact `src_rel`. The fix should steer continuation away from redumping retained candidates by making the safe `score-source` path retain pcdumps. Adding related-prefix refusal to same-TU `dump local` is useful as a belt-and-suspenders guard, but it must not break internal generated-candidate compile workflows without careful tests.

## Regression tests first

1. Add a `score-source` retained-pcdump test in `tools/melee-agent/tests/test_debug_cli_reorg.py`.
   - Arrange a retained candidate under `build/diagnostics/.../combine-1-3.c`, a real source `src/melee/mn/sample.c`, and `--cflags-from src/melee/mn/sample.c`.
   - Monkeypatch `_run_with_process_group_timeout` to assert the real TU contains retained source text while compiling and to write the pcdump file named by `MWCC_DEBUG_PCDUMP_PATH`.
   - Invoke `debug target score-source ... --json --retain-pcdump` or the chosen option name.
   - Assert JSON includes `pcdump_path`, the file exists, its text is the fake pcdump, the compile command used `-c src/melee/mn/sample.c`, and the live TU is restored.
   - Why: prevents recurrence of the IG44-hit handoff gap while proving the pcdump comes from the safe real-TU staging lane.

2. Add a `search combine` handoff propagation test in `tools/melee-agent/tests/search/test_cli_smoke.py`.
   - Extend or add a combine test whose score script prints JSON with `score`, `target_score`, `pcdump_path`, and optionally `structural_guard`.
   - Assert the combination row promotes `pcdump_path` and `target_score` to first-class fields while retaining `score_result.parsed_json`.
   - Assert a generated continuation/score command in the row includes the combined source path and uses `score-source` with pcdump retention.
   - Why: prevents successful recombine candidates from burying or losing the retained pcdump handoff.

3. Add a `select-order-search` successful-candidate pcdump retention test in `tools/melee-agent/tests/test_select_order_search.py`.
   - Use a generated or manual `.c` candidate, monkeypatch `compile_source_variant` to return candidate pcdump text and `_select_order_source_score` to return a usable real score.
   - Assert each successful `.c` variant has `pcdump_path`, the file exists beside the retained source, `objective.pcdump_path` matches, and `source_bridge_summary`/terminal lane includes the same path.
   - This is partly covered by helper-level tests, but add CLI-level coverage if absent for the exact generated/guard-repair path.
   - Why: protects the select-order half of the issue, not only the pure helper serialization.

4. Add a timeout partial source-bridge test in `tools/melee-agent/tests/test_select_order_search.py`.
   - Build on `test_select_order_search_marks_source_score_deadline_error_as_timeout`.
   - Ensure a scored retained candidate has `pcdump_path`, then force a timeout via structural guard error or command deadline.
   - Assert payload status remains `timeout`/`partial`, but `source_bridge_summary` is a partial computed summary with ranked probes/actions and pcdump paths, not only `skipped-timeout`.
   - Assert `source_restored` is true in success JSON.
   - Why: prevents timeout frontiers from becoming non-actionable JSON.

5. Add a timeout restore safety test for live TU residue in `tools/melee-agent/tests/test_select_order_search.py`.
   - Create a real source under fake `DEFAULT_MELEE_ROOT`.
   - Monkeypatch candidate scoring to mutate the live TU and return a timeout-shaped `_SourceCandidateRealScore` or raise `TimeoutError`.
   - Invoke `select-order-search --json` with a tiny timeout/forced timeout path.
   - Assert the command exits with timeout or failure as expected, the JSON reports restore status, `_ACTIVE_SOURCE_RESTORES` is empty, and the live source bytes equal the original.
   - Why: directly covers the `ll_probe_iter_0` dirty-source symptom.

6. Optional but recommended: add a same-TU retained `dump local` lane guard test in `tools/melee-agent/tests/test_debug_cli_reorg.py`.
   - Simulate an uninterruptible `wibo` for a sibling candidate in the same `build/diagnostics/...` directory and/or for the real TU.
   - Invoke `debug dump local retained.c --unit-source src/... --function ... --output ... --no-cache-sync`.
   - Assert it refuses before launching `Popen`.
   - Why: prevents a known unsafe redump lane if users bypass the new safe handoff.

## Production changes

1. Extend `debug target score-source`.
   - Add an option such as `--retain-pcdump/--no-retain-pcdump`, defaulting to false unless JSON ergonomics strongly justify default true.
   - Add an optional `--pcdump-output PATH` if callers need deterministic destinations; otherwise choose a path near the candidate for repo-contained candidates, for example `<candidate>.pcdump.txt`, or under `build/mwcc_debug_cache/score-source/`.
   - After reading `pcdump_text`, write it to the retained path before unlinking the transient `pcdump_score_*.txt`.
   - In JSON output, include `pcdump_path` and possibly `pcdump_retention_error`. Do not include this in `--quiet`.
   - Preserve existing failure behavior: on unsafe lane or missing pcdump, do not create a fake `pcdump_path`; include `unsafe_local_pcdump_lane` as today.

2. Update source-bridge score command hints.
   - In `_select_order_bridge_score_command_hint`, append the new pcdump retention option.
   - In `_copy_survived_continuation_handoff`, append the same option to the `score-retained-source` route.
   - If a variant already has `pcdump_path`, prefer using that path directly in continuation routes so users do not redump at all.

3. Promote combine scorer handoff fields.
   - Add a small helper in `tools/melee-agent/src/search/cli/__init__.py`, e.g. `_score_result_handoff_fields(score_result)`.
   - When `_combine_candidate_pair` receives parsed scorer JSON, copy first-class fields such as `pcdump_path`, `target_score`, `structural_guard`, `structural_guard_error`, `unsafe_local_pcdump_lane`, and `score` onto the combination row.
   - Add a continuation/handoff object for successful rows:
     - source path: generated combined `.c`
     - pcdump path: promoted `pcdump_path` when present
     - score command: safe `score-source` command with retained pcdump option
     - unsafe-lane terminal blocker when scorer JSON reports `unsafe_local_pcdump_lane`.
   - Keep `score_result` unchanged for backward compatibility.

4. Make select-order timeout summaries partial instead of empty.
   - Replace the `timed_out ? {"status": "skipped-timeout"}` branches with a helper that attempts `_select_order_source_bridge_summary(...)` using the variants already scored.
   - Annotate the returned summary with `partial: true`, `timed_out: true`, and `timeout_error`.
   - Fall back to the old skipped-timeout shape only if summary construction itself fails.
   - Include `source_restored` and `source_restore_error` in success JSON, not just failure JSON.

5. Tighten restore status around command-level source guards.
   - Keep `_select_order_close_source_restore(command_source_restore)` before summary construction.
   - Ensure every early exit after `command_source_restore` construction uses the same close helper. The obvious existing early exit at no probes manually closes; audit for any other `raise typer.Exit` after line ~38754.
   - If success JSON cannot verify restore, exit nonzero as today, but include variants and ledgers in the failure JSON.

6. Optional direct-dump guard.
   - Add related-prefix unsafe lane detection to `pcdump_local` when `same_tu_probe` is true:
     - exact retained source
     - retained source parent directory
     - `unit_src_rel`
   - On unsafe, exit 125 with the formatted process list before `Popen`.
   - Be careful: `compile_source_variant` uses same-TU probe dumps internally. This guard should only refuse when a UE process already exists, not change normal behavior.

## Verification commands

Run focused tests first:

```bash
pytest tools/melee-agent/tests/test_debug_cli_reorg.py -k "score_source and pcdump"
pytest tools/melee-agent/tests/search/test_cli_smoke.py -k "combine"
pytest tools/melee-agent/tests/test_select_order_search.py -k "pcdump or timeout or restore"
```

Then run the broader relevant suites if the focused tests pass:

```bash
pytest tools/melee-agent/tests/test_debug_cli_reorg.py tools/melee-agent/tests/test_select_order_search.py tools/melee-agent/tests/search/test_cli_smoke.py
```

No `python configure.py && ninja` is required for this tooling-only change unless implementation touches build integration outside `tools/melee-agent`.

## Acceptance criteria

- A successful `score-source --json` retained candidate can provide a durable `pcdump_path` without a second `debug dump local` invocation.
- A successful `debug search combine --score-command ...` result exposes `pcdump_path` and continuation metadata at the combination row level.
- Successful select-order candidates, including guard-repair candidates, expose retained `.c` and `.pcdump.txt` paths.
- Timeout select-order JSON remains actionable: it reports partial source-bridge/continuation lanes from already-scored variants and reports source restore status.
- Timeout/hang/unsafe-lane paths do not leave `src/melee/mn/mndiagram.c` or any staged real TU dirty.
