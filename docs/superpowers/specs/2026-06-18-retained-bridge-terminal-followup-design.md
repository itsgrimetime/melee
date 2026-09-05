# Retained Bridge Terminal Follow-up Design

## Context

Issues #797, #798, and #799 are follow-ups to the retained source bridge work in
`afa79b2097c5e4624537f2cdcdbf1212ce4cd55a`. The prior change added retained
source scoring, executable inline-boundary lines, and terminal bridge actions,
but match agents found three remaining gaps:

- `debug search structure` still rejects a retained seed `--source-file` when
  generated structure-search variants are distinct files.
- Inline-boundary drift output can be correctly non-commented yet still empty,
  leaving no source-actionable fallback.
- Sort terminal bridge output can recommend stack repair without exposing a
  concrete frame-transform lane or an explicit terminal blocker.

## Design

### Retained Seed Scoring

`score_structure_variants` will distinguish two retained source roles:

- `source_path`: the seed source passed to `debug search structure --source-file`.
- `variant.source_retained`: generated candidate sources that should be scored.

When `report.json` resolves a different real TU, the seed source may still be
accepted if it is an existing `.c` file outside the canonical `src/` tree and
`src.mwcc_debug.source_patch.find_function` finds the requested function
definition in it. Prototype-only, comment-only, missing-function, and wrong
in-tree source paths remain rejected. Candidate scoring continues to patch and
restore the report-resolved real TU.

### Inline-Boundary Attribution Fallback

`_select_order_inline_boundary_drift_summary` will keep the existing localized
path when executable lines are present. If localization produces no executable
lines, it will emit:

- `source_attribution_status: "unmapped"`
- `terminal_blocker: "source-hunk-no-executable-lines"`
- `nearest_executable_source_spans`: line-numbered executable snippets from the
  parsed function body, collected without reusing the compact signature hunk.
- `opcode_drift`: the normalized drift metrics currently available from the
  structural guard. The tool will not claim an exact opcode/call hunk unless a
  guard payload provides one.
- `next_probe`: a scoring-oriented structure-search command with explicit
  `--score`, using the retained source path rather than a known call-temp repeat.

### Terminal Stack-Repair Bridge

`terminal_next_lane` will keep its existing `actions` for compatibility and add
`frame_repair_lane` when stack-layout retained candidates are present.

The lane will not run heavy frame-transform scoring inline. Instead it will:

- record each candidate's `candidate_frame_delta`, register mismatches, retained
  path, and `frame_reservation_bytes_hint`.
- emit a concrete `melee-agent debug mutate frame-transform-search` command that
  uses the retained source and writes results under a durable output directory
  when a campaign directory is available.
- surface `frame_transform_probe_evaluation` metadata if a variant already
  carries it.
- otherwise mark the lane `blocked` with
  `terminal_blocker: "frame-transform-not-materialized"` so match agents stop
  rerunning select-order recursively and run the concrete frame-transform lane.

If later frame-transform output reports a ceiling, that evaluation remains the
source of truth for `remaining_frame_delta` and `frame_delta_improvement`; these
fields are intentionally not conflated with select-order's candidate-vs-baseline
`frame_delta`.

## Testing

Add focused regressions:

- retained seed source differs from generated candidate source and scores through
  the real TU.
- wrong in-tree source and retained source missing a function definition are
  rejected.
- empty inline-boundary executable lines produce the unmapped blocker, nearest
  executable spans, and a scoring next probe.
- existing executable-line localization remains localized.
- terminal stack-layout candidates produce `frame_repair_lane` with frame delta
  hints and concrete `frame-transform-search` command metadata.

## Non-Goals

- Do not add a new CLI command.
- Do not run frame-transform scoring inline from select-order.
- Do not claim exact opcode/call hunk attribution unless the underlying guard
  already exposes exact hunk data.
