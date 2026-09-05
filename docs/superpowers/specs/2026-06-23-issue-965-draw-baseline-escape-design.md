# Issue #965 Design: Draw Post-Ceiling Baseline Escape

## Context

`mnDiagram_DrawCellNumber` is at an expression-scored FPR allocator ceiling. The
current retained baseline source has three live FPR targets:

- `row_offset` IG37 currently in f28, expected f26;
- `col_offset` IG32 currently in f26, expected f28; and
- the digit-call FPR temp IG46 expected f26.

The known search lanes are already closed:

- allocator-ceiling reports `practical-ceiling` with terminal reason
  `expression-scored-fpr-allocator-ceiling`;
- expression-interferer repair reports
  `post_bridge_terminal_summary.kind ==
  no-expression-progress-after-row-fsubs-and-support-orders`; and
- retained-frontier triage reports `all-known-frontiers-exhausted` for Draw.

Issue #965 asks for a new post-current-source-shape layer. It must not retry the
exhausted row-fsubs, support-order, product-owner, sink-owner, guarded-motion, or
retained select-order families. It should instead generate a bounded ranked set
of broader alternate source baselines, retain `.c` candidates for scoring, and
emit a terminal when the generated post-ceiling family set is scored without
expression progress.

## Options Considered

### Recommended: Add a Dedicated `debug search baseline-escape` Layer

Add a pure `mwcc_debug.post_ceiling_baseline_escape` module and expose it through
`melee-agent debug search baseline-escape`. The command consumes the three
artifacts above, resolves the retained source baseline from those artifacts when
`--source-file` is omitted, writes bounded candidate source files when
`--write-probes` is provided, and classifies optional score JSON files.

This is the lowest-risk integration because it leaves allocator-ceiling,
expression-interferer, and retained-frontier closure behavior intact. It also
gives matching agents a concrete next command after the current terminal stack.

### Alternative: Reopen `expression-interferer-repair` Source Generation

The expression-interferer generator already owns row/product families. Reopening
it for broader baselines would blur the meaning of its post-bridge terminal and
risk regenerating the same families #963 just closed.

### Alternative: Extend `plan-transforms`

`plan-transforms` is a general transform-corpus executor, but #965 needs to
consume allocator-ceiling plus expression-interferer plus retained-frontier
closure evidence and produce a terminal schema specific to post-ceiling baseline
escape. A dedicated command can still reuse its validation pattern without
overloading transform-family planning.

## Design

Add `tools/melee-agent/src/mwcc_debug/post_ceiling_baseline_escape.py`.

The module is pure except for an explicit file-writing wrapper. It exposes
`generate_baseline_escape_candidates`, `generate_baseline_escape_candidate_files`,
and `classify_baseline_escape_scores`.

`generate_baseline_escape_candidates` accepts source text, a function name, and
the parsed allocator-ceiling, expression-interferer, and retained-frontiers
payloads. It returns:

- `status`: `generated` when candidates are available, `blocked` when required
  evidence or source anchors are missing, or `terminal` when score payloads close
  the lane;
- `kind`: `post-ceiling-baseline-escape`;
- `evidence`: normalized artifact evidence and target-expression anchors;
- `families`: emitted family names;
- `candidates`: ranked candidate metadata, source hunks, validation metadata, and
  optional source text; and
- `terminal_summary` only when score payloads prove no post-ceiling candidate
  made expression progress.

The command accepts:

- `--function/-f`;
- `--source-function` optional source-level function name when the scoring
  function uses an alias;
- `--source-file` optional retained baseline source;
- `--allocator-ceiling-json`;
- `--expression-interferer-json`;
- `--retained-frontiers-json`;
- repeatable `--score-json`;
- `--target` score-source target JSON used for validation command hints;
- `--cflags-from` or `--unit-source` source used by score-source for build
  context;
- `--expression-baseline` pcdump used to enable expression scoring;
- `--expression-source` source path for expression-score attribution;
- `--max-candidates`;
- `--write-probes`;
- `--include-source`; and
- `--json/--text`.

When `--source-file` is omitted, source resolution searches the retained-frontier
terminal frontiers for a `source_file` matching the requested function. This is
required for Draw because the repo source still uses the address-style symbol in
some checkouts while the retained mwcc-debug source uses
`mnDiagram_DrawCellNumber`.
The full source-resolution order is explicit `--source-file`,
allocator-ceiling `expression_interferer_terminal.source_generation.source_file`,
expression-interferer `source_generation.source_file`, retained-frontier
`source_file`, then retained candidate `source_retained`, `source_file`, or
`path` fields.

## Candidate Families

The first version emits only broader post-ceiling families:

- `post_ceiling_statement_grouping`: wraps the paired row/column offset
  calculations in C89-valid scoped blocks or materializes paired row/column owner
  baselines together. This changes source grouping rather than retrying an
  individual row/product owner.
- `post_ceiling_call_temp_materialization`: materializes helper-call input and
  call-argument temps around `mn_GetDigitCount`, `HSD_JObjReqAnimAll`, and
  translate calls. This targets helper-call lifetime boundaries instead of the
  already exhausted product-owner probes.
- `post_ceiling_paired_owner_baseline`: changes visible local ownership on both
  row and column sides in one baseline, including deliberate lower-match
  exploratory candidates with recoverable source hunks.

Each candidate includes validation metadata naming the current target anchors
and instructing matchers to score with the existing expression-score workflow.
The generator deduplicates by full source text and respects `--max-candidates`.
Candidate metadata includes a `novelty_reason`. Generation rejects candidates
whose family overlaps the exhausted or suppressed families reported by the
allocator-ceiling or expression-interferer evidence. This keeps the command from
reopening row/product/sink/guarded-motion lanes under new labels.

The command may emit validation hints for existing transform-corpus call-argument
families instead of reproducing every callarg temp transformation locally. Direct
source candidates remain bounded to the broader post-ceiling families above.

## Score Classification

`classify_baseline_escape_scores` reads score JSON payloads from
`debug target score-source` or compatible summaries. It extracts `expression_score`
recursively, then classifies each scored candidate as:

- `expression-progress` if any targeted expression anchor matched;
- `structural-preserving` if no expression anchor moved but structural evidence
  says the candidate remained a normalized structural match;
- `recoverable-downhill` if match percentage or structural evidence regressed but
  the source hunk is retained for broader baseline exploration; or
- `unscoreable` when no compatible score data is present.

When every generated candidate has a score payload and none has expression
progress, the output includes:

```json
{
  "terminal_summary": {
    "status": "terminal",
    "kind": "no-post-ceiling-draw-source-family",
    "terminal_blocker": "current-source-shape-ceiling",
    "terminal_reason": "no-post-ceiling-draw-source-family/current-source-shape-ceiling"
  }
}
```

Retained-frontier triage should recognize that terminal reason so later scans can
suppress this lane. It needs an explicit extractor for the post-ceiling terminal
summary, not only a reason-string addition. The retained-frontier terminal should
include function, family id, suppression family, attempted/final force targets
when known, terminal reason, candidate and scored counts, and the best expression
score fields available from the score classification.

## Tests

Add focused tests for the pure module and CLI:

- artifact evidence normalization accepts the live #965 terminal stack;
- source resolution can use a retained-frontier `source_file`;
- candidate generation emits only the new post-ceiling families and writes `.c`
  files;
- score classification reports expression progress when an expression anchor
  matches;
- all-generated/all-scored/no-expression-progress emits the post-ceiling
  terminal summary; and
- retained-frontier triage treats the terminal summary as a terminal frontier.

Command-level smoke should run `debug search baseline-escape --json
--write-probes` against fixture artifacts and a tiny retained source.

## Out of Scope

This does not compile or score candidates itself. Existing `debug target
score-source` workflows remain responsible for validation and `.pcdump` capture.
This also does not change allocator-ceiling proof logic or reopen exhausted
expression-interferer families.
