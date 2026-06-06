# Structure Search Scored Variants Design

## Problem

Issue #446 reports that `melee-agent debug search structure` generates source
variants that are not campaign-executable. The command can retain candidate
source files for declaration order, control flow, case order, and statement
order, but the default payload often leaves `baseline_percent`,
`match_percent`, and `delta` unset. Agents then have to transfer and score each
candidate by hand, and generated-order ranking can hide that all candidates are
worse than baseline.

The fix is not another source-transform family. Issue #444 owns the deeper
helper-inline/source-lifetime transform harness. This design only scores and
ranks the variants that structure search already produces.

## Goals

- Score retained structure-search source variants against the real translation
  unit by default from the CLI.
- Report a fresh baseline percent, candidate percent, delta, compile status,
  and checkdiff structural movement for each scored candidate.
- Preserve read-only working tree semantics: candidate scoring may temporarily
  build candidate source under the repo lock, but it must restore the original
  source file, object, and `report.json`.
- Keep module-level tests fast with injectable score runners.
- Ensure every unscored generated candidate carries a concrete
  `unscored_reason`.

## Non-Goals

- Do not apply candidates to source files.
- Do not create new source-transform families.
- Do not solve helper-inline/source-lifetime register cascades from issue #444.
- Do not rely on `checkdiff --no-build` for fuzzy match percent; that command
  intentionally suppresses stale report percentages.

## Architecture

`tools/melee-agent/src/search/structure.py` remains the orchestration and
payload module. It gains a small scoring contract:

- `StructureScoreResult` captures baseline percent, candidate percent, delta,
  compile status, optional checkdiff status, optional checkdiff structural
  metrics, and failure reason.
- `run_structure_search(..., score_runner=None, score_variants=False)` generates
  candidates first, then scores candidates with retained source when a runner is
  provided and scoring is enabled.
- If scoring is disabled or impossible, generated variants keep their retained
  source paths and receive `unscored_reason`.

The real scorer lives in a new
`tools/melee-agent/src/search/structure_scoring.py` module to avoid importing
the large debug CLI module from the search payload layer. The scorer:

1. Resolves the function unit and source path from `build/GALE01/report.json`.
2. Acquires the shared repo build/checkdiff lock.
3. Saves the original source, current build object, `report.json`, and the
   function's checkdiff history file.
4. Builds the original source and regenerates `report.json` once to obtain the
   fresh baseline percent.
5. Runs no-build checkdiff for baseline structural metrics.
6. For each retained candidate, writes the candidate text to the real source
   path, runs `ninja build/GALE01/src/<unit>.o`, regenerates `report.json`,
   reads the candidate percent, runs `checkdiff.py --format json --no-build`
   with `CHECKDIFF_NO_LOCK=1` and `CHECKDIFF_NO_FINGERPRINT=1`, and computes
   delta from the fresh baseline.
7. Restores the saved source, object, `report.json`, and checkdiff history in
   `finally`.

Child build/report/checkdiff commands run through a process-group timeout path
so descendant compiler processes are killed before the scorer restores files and
releases the repo lock.

This uses `checkdiff --no-build` only for structural metrics such as
`opcode_similarity`, `line_delta`, and `hunk_count`; the fuzzy percent always
comes from the freshly regenerated objdiff report.

## CLI Contract

`debug search structure` gains:

```bash
--score / --no-score
--score-timeout SECONDS
```

CLI default is `--score`. The module default remains unscored unless a caller
explicitly provides a score runner, which keeps unit tests and library callers
cheap. `--no-score` preserves the previous fast source-generation behavior but
with explicit `unscored_reason: "scoring disabled"`.

## Payload Contract

Scored variants include:

```json
{
  "status": "ok",
  "compile_status": "ok",
  "checkdiff_status": "ok",
  "baseline_percent": 98.48,
  "match_percent": 98.00,
  "final_match_percent": 98.00,
  "delta": -0.48,
  "metadata": {
    "structural": {
      "opcode_similarity": 0.97,
      "line_delta": 0,
      "hunk_count": 4,
      "opcode_similarity_delta": -0.01,
      "line_delta_delta": 0,
      "hunk_count_delta": 1
    }
  }
}
```

Unscored variants include:

```json
{
  "status": "unscored",
  "compile_status": "failed",
  "checkdiff_status": null,
  "unscored_reason": "candidate compile failed: ..."
}
```

When compile/report scoring succeeds but no-build checkdiff fails, the variant
still reports `baseline_percent`, `match_percent`, `final_match_percent`, and
`delta`, with `compile_status: "ok"`, `checkdiff_status: "failed"`, and an
`unscored_reason` explaining the structural-metric failure.

`stop_condition.kind` is:

- `improved` when any scored variant reaches 100% or improves over baseline.
- `candidates-generated` when generated variants remain unscored, with reasons.
- `no-improvement` when all generated variants are scored and none improve.

## Testing

Fast unit tests cover score application, ranking by scored percent, explicit
unscored reasons, compile-failure payloads, and stop-condition behavior.

CLI smoke tests monkeypatch the scorer builder and `run_structure_search` to
verify `--score` is default and `--no-score` disables it. Real toolchain tests
are limited to command help and Python compilation; full real-TU scoring is
covered by the scorer's isolated subprocess/restore unit tests with fake
subprocess calls.
