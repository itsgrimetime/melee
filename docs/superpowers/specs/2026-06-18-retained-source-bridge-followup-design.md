# Retained Source Bridge Follow-up Design

## Context

Issues #794, #795, and #796 are one follow-up cluster from the select-order
guard-repair bridge work. Matching agents now get useful retained candidate
sources, but three downstream paths still lose actionable evidence:

- `debug search structure --source-file <retained.c>` rejects retained full-TU
  source files because scoring expects `--source-file` to be the real TU path.
- Inline-boundary drift summaries can point at comments or declarations instead
  of executable source statements.
- Terminal window-order bridge output does not preserve single-probe sources
  under `--campaign-dir`, and it does not provide a bounded next lane for
  structural-near or stack-layout variants.

## Approach

Use existing scoring and select-order summary APIs. Do not add a new CLI command.

1. Structure scoring should resolve the real TU from `report.json` by function,
   then treat `--source-file` as either the real TU or a retained full-TU
   candidate. Candidate bytes are still written into the real TU only inside the
   existing repo lock and restore block.
2. Inline-boundary drift summaries should expose executable anchors:
   comment-only and declaration/prototype lines are filtered out, and the drift
   payload reports an `executable_source_lines` list plus call lines derived from
   that executable subset.
3. Select-order single-probe runs should honor `--campaign-dir` by writing
   generated sources under that directory instead of a temporary directory.
4. Source-bridge summaries should add a `terminal_next_lane` when leads are
   terminal but ranked variants include structural-near or stack-layout sources.
   The lane does not invent a match. It records preserved source paths,
   candidate register deltas, frame deltas, and recommended bounded recombine or
   frame-repair actions using existing commands and retained candidates.

## Error Handling

Retained source scoring keeps the existing restore discipline: original source,
object, report, and checkdiff history are restored in `finally`. Missing retained
source files remain unscored with a clear reason. If no retained candidates or
no terminal bridge variants are present, summaries retain current behavior.

## Testing

Regression tests cover:

- scoring a retained full-TU source whose path differs from the real report TU;
- inline-boundary localization ignoring comments and prototypes;
- source-bridge terminal lane emission for indexed-byte plus stack-layout
  variants;
- `select-order-search --campaign-dir` single-probe source retention.
