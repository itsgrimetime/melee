# Final-review timeout cleanup report

## Change

`debug target score-source` now owns its root-level `pcdump_score_*` file and
unique scratch discard object through one best-effort `finally` block. The
block runs after local compiler execution, missing-pcdump handling, pcdump
reads, and propagated timeout errors. It suppresses cleanup-only `OSError`s,
so it does not alter the existing timeout result, exception, or quiet-output
behavior.

## TDD evidence

RED was run before the implementation:

```text
pytest tests/test_debug_cli_reorg.py -q -k score_source_timeout_cleans_compiler_probe_products
1 failed, 300 deselected
```

The regression mocked the process-tree runner to create both the unique
repo-root pcdump and the discard object, then raise `subprocess.TimeoutExpired`.
The existing finalization/re-raise path left the pcdump behind.

GREEN after the minimal `finally` implementation:

```text
pytest tests/test_debug_cli_reorg.py -q -k score_source_timeout_cleans_compiler_probe_products
1 passed, 300 deselected
```

The regression also confirms the original `TimeoutError`, empty quiet output,
and failed artifact manifest payload are unchanged, while both products are
absent afterward.

## Verification

| Command | Result |
| --- | --- |
| `pytest tests/test_mwcc_debug_artifacts.py -q` | Passed: 13 tests. |
| `pytest tests/test_debug_cli_reorg.py -q -k score_source` | One known pre-existing failure; 13 passed before the failure. |
| Same score-source selection excluding `test_target_score_source_remote_fallback_runs_checkdiff_guard` | Passed: 27 tests, 274 deselected. |
| `python -m py_compile tools/melee-agent/src/cli/debug/target.py tools/melee-agent/tests/test_debug_cli_reorg.py` | Passed. |
| `git diff --check` | Passed. |

Ruff was run over both edited files. It reports 57 existing violations,
including import ordering, `Optional` modernizations, and f-string cleanup in
unchanged portions of both files; no reported location overlaps this fix. The
unrelated violations were not modified.

## Concern

The full score-source subset retains its documented baseline failure in
`test_target_score_source_remote_fallback_runs_checkdiff_guard`: it expects
`structural_guard == {"ok": True}`, but the unchanged implementation also
contains three target-score fields. This cleanup fix does not alter that path.
