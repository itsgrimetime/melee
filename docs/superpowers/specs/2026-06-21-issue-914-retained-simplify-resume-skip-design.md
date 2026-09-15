# Issue 914: Retained Simplify-Order Resume and Skip Controls

## Context

`debug mutate simplify-order` can run long retained-source searches where one
candidate family becomes sticky. Issue #913 made Ctrl-C write partial JSON, but
#914 showed the next blocker: a retained no-preserve run stopped at a
`type-change ... int->unsigned int` candidate after 62 compiles and there was no
way to resume from candidate 63 or skip that family. The partial JSON also needs
to preserve enough stream state to make the next command obvious.

## Design

Add deterministic skip controls to the shared simplify-order search driver:

- `skip_first_candidates`: skip the first N unique candidate texts before any
  compile. This is the direct resume path when JSON says `summary.compiled` was
  62; the matcher can rerun with `--skip-first-candidates 62`.
- `skip_provenances`: exact provenance strings to skip.
- `skip_families`: provenance prefixes to skip, for families like
  `type-change `.

Skipping happens after cross-source text de-duplication and before the compile
counter increments. That keeps `max_candidates` as the number of candidates to
compile in the resumed run, not the original stream length. Progress output
continues to report compiled candidates only, while JSON reports skipped counts
separately.

`SearchResult` gains:

- `skipped_count`
- `skip_reasons`: a small list of `{"provenance": ..., "reason": ...}` records
- `candidate_stream_position`: count of unique, non-duplicate candidates seen in
  the stream, including skipped and compiled candidates
- `last_provenance`: updated before candidate generation hands off to compile,
  so interrupts during generation, compile, or parsing still identify the active
  candidate when possible

The CLI exposes:

- `--skip-first-candidates N`
- repeatable `--skip-provenance TEXT`
- repeatable `--skip-family PREFIX`

JSON output adds a `resume` object containing those inputs plus
`skipped_count`, `candidate_stream_position`, and `next_skip_first_candidates`.
The top-level `summary` also includes `skipped` and `candidate_stream_position`.
If every candidate in the bounded run is skipped or filtered without any compile
or ranking, JSON uses terminal blocker
`retained-candidates-skipped-or-exhausted`.

## Rejected Alternatives

Do not persist resume cursors to disk yet. The candidate stream is deterministic
for a fixed source, options, and tooling commit, and explicit skip flags are
easier to inspect, paste, and audit.

Do not special-case `type-change`. Family skipping is generic and handles future
sticky adapters without more command-specific code.

Do not change per-candidate timeout behavior in this feature. Timeout and child
process cleanup are separate concerns; this feature gives agents a recovery path
when a candidate is sticky or expensive.

## Tests

Core tests in `test_mwcc_debug_simplify_search.py`:

- skipping the first N unique candidates compiles only later candidates and
  reports skipped count/stream position
- exact provenance and family prefix skips happen before compile and do not
  consume `max_candidates`
- interrupt metadata reports the active candidate provenance even after skipped
  candidates

CLI tests in `test_mwcc_debug_simplify_search_cli.py`:

- `--skip-first-candidates` and `--skip-family` are passed into `search`
- retained JSON includes `resume` metadata and skip summary
- an all-skipped retained JSON run emits a terminal blocker instead of looking
  like a silent no-progress search

Command smoke:

- run the retained #914 command with `--skip-first-candidates 62 --max-candidates
  3` and verify it emits populated JSON that starts after the sticky candidate.

## Scope Guard

Only touch simplify-order search/CLI/tests. Leave unrelated dirty files in the
shared checkout unstaged. Do not modify the mutation adapters except if a test
requires reading their provenance conventions.
