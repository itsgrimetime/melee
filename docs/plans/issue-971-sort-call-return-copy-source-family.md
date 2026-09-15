# Issue 971 Sort Call-Return Copy Source-Family Plan

## Implementation Steps

1. Add `sort-call-return-copy-local` to Sort source-family dimension specs.
2. Match the new neighborhood with the existing Sort indexed-byte comparison IF pattern.
3. Add a patcher that generates the byte-cache shape plus `post_ceiling_j_text_copy`.
4. Skip regenerating source-family probes whose candidate IDs already appear in scored retained inputs.
5. Mark skipped scored dimensions as terminal evidence instead of actionable probes.
6. Short-circuit stale continuation analysis when all expected source-family probes have already been scored.
7. Add focused regression tests for the Sort probe and Draw stale-continuation suppression.
8. Add simplify-order retained-probe interrupt handling so partial JSON survives Ctrl-C during retained checkdiff scoring.

## Verification

Run the focused post-ceiling and simplify-order interrupt tests, then smoke the affected CLI help paths and the issue queue commands before resolving the issues.
