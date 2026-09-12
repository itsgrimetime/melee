# Issue 971 Sort Call-Return Copy Source-Family Design

## Context

`mnDiagram_SortNamesByKOs` reached a lower-drift post-ceiling frontier where the indexed-byte-cache source-family probe preserved the useful `IG44->r25` hit but left `IG34` at `r0` or absent. Trace-copy evidence identified the residual as `mr r34,r64`: `r64` is the `GetNameText(post_ceiling_j_name)` call return already assigned to `r27`, while `r34` is a degree-zero copy destination. Existing post-ceiling source-family discovery only generated Sort probes for initialization writes, indexed byte caching, and swap slot materialization, so the matcher had no bounded retained-source continuation around that call-return copy shape.

## Approach

Extend `post_ceiling_baseline_escape` source-family discovery with one additional Sort dimension, `sort-call-return-copy-local`. The probe is generated directly from the original Sort comparison IF pattern rather than from a retained generated source. This keeps the handoff bounded and lets the probe appear whenever the same source neighborhood is present.

The new probe materializes the same max and j name byte cache as the existing indexed-byte-cache probe, then adds an explicit `post_ceiling_j_text_copy` local:

- `post_ceiling_j_text = GetNameText(post_ceiling_j_name);`
- `post_ceiling_j_text_copy = post_ceiling_j_text;`
- NULL checks use the copy local.

The probe metadata states that it targets `IG34->r27` while preserving `IG44->r25`.

## Terminal Handling

The Draw stale-route issue showed that once all generated source-family probes are scored with no target or expression progress, the classifier must not re-emit the same continuation routes as actionable. The terminal routing now recognizes when all expected source-family candidate IDs for a function have already been scored. In that case it skips stale continuation analysis, emits final synthesis, and marks matching discovery dimensions as `scored-terminal` with `retained-source-family-scored-no-progress`.

## Review Notes

An independent Codex reviewer checked the design before implementation. The reviewer flagged that discovery scans the original source text, not retained generated sources, and recommended composing the new probe from the original Sort IF pattern as a sibling of `sort-indexed-byte-cache`. The implemented design follows that recommendation.

## Testing

Regression coverage includes:

- Draw scored source-family rows suppress stale continuation and terminalize discovery.
- Sort final source-family discovery emits the call-return-copy dimension and probe.
- Simplify-order retained-probe interruption preserves partial records for JSON output.
