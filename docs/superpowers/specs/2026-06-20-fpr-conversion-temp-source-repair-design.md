# FPR Conversion Temp Source Repair Design

## Problem

Issue #862 reports a retained `mnDiagram_DrawCellNumber` baseline that satisfies four of six protected FPR assignments, but the next repair path loses source actionability for the remaining pcode-only conversion temp:

- `ig46` is reported as `fsubs f46,f45,f44`, with no direct source variable.
- The actual source owner is the cast fragment in `col_offset = y_spacing * (f32) col`, visible through the consumer local `ig32` whose first-def operands include `f46`.
- Existing source planning sees the raw `fsubs` and prefers an unrelated subtraction owner, `row_offset_adj = row_offset - 0.4f`, so it proposes the wrong hunk.
- Compact validation evidence drops full `target_score.virtuals`, forcing downstream agents to reopen raw validator output or rescore retained wrong-register candidates to see partial six-register progress.

The fix must stay in the existing source-transform tooling. It should not add a parallel search command.

## Chosen Approach

Extend the existing synthetic FPR owner-split path in `tools/melee-agent/src/search/directed/window_order_source.py`.

When a pcode-only FPR temp has opcode `fsub`/`fsubs`, first look for local source attributions whose first-def operands consume the target temp. If a consumer local has a simple assignment containing a cast fragment such as `(f32) col`, materialize that cast fragment as the synthetic source owner before falling back to the generic arithmetic subtraction owner.

This keeps existing behavior for true subtraction temps while steering int-to-float conversion temps to the source expression that actually owns the pcode conversion sequence.

## Alternatives Considered

1. Add a new `mwcc-debug` subcommand for conversion temps.
   This would duplicate planning, scoring, and validation already present in `plan-transforms` and node-set tooling.

2. Require callers to pass `--var col_offset`.
   This was already tried in the issue report and exhausted as wrong-register; it also does not identify the cast fragment that owns `ig46`.

3. Teach `first-divergence` to emit source hunks directly.
   First-divergence should remain diagnostic. Source mutation belongs in `window_order_source` and transform-corpus/node-set planners.

## Requirements

- For `fsubs f46,f45,f44` with a source attribution map containing consumer local `ig32` whose first-def operands include `f46`, generate a synthetic owner split for `(f32) col` in `col_offset = y_spacing * (f32) col`.
- Prefer the conversion consumer split over unrelated generic subtraction owners.
- Preserve generic FPR subtraction owner behavior when no conversion consumer exists.
- Allow simple scalar cast expressions such as `(f32) col` to be introduced as typed node-set bindings, while continuing to reject calls, assignments, comma expressions, increments, and empty expressions.
- Surface compact `target_score.virtuals` evidence from transform validation payloads and node-set candidate rows when available.
- Add regression tests before production changes.

## Data Flow

1. `explain_virtuals` provides source attributions for the contested temp and related locals.
2. `plan_window_order_source_probes` receives fallback leads and the attribution map.
3. `_fpr_temp_owner` parses the raw pcode expression.
4. For `fsub`/`fsubs`, the new conversion owner finder scans source-attributed local consumers whose first-def operands include the target temp.
5. Matching consumer assignments are split at the cast fragment, producing a normal synthetic source probe with diff metadata.
6. `plan-transforms --validate-command <score-source wrapper>` can score generated candidates; validation evidence carries the target-score virtual map.

## Testing

Focused unit tests cover:

- conversion-temp owner split prefers `col_offset = y_spacing * (f32) col` over `row_offset_adj = row_offset - 0.4f`;
- existing FPR subtraction owner split still works without consumer attribution;
- `(f32) col` is safe for typed binding, while unsafe expressions remain rejected;
- node-set summary rows preserve `target_score` when candidate scoring supplies it;
- transform validation evidence includes `target_score.virtuals` from validator JSON.

Command-level smoke checks cover `melee-agent debug search plan-transforms --help` and `melee-agent debug solve node-set-split --help`.
