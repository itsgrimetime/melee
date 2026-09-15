# Issue 897 Plan

## Steps

1. Add regression coverage for the invalid self-scaled row-adjust transform.
   Keep the existing `y_offset` distinct-local case valid.
2. Add expression-aware lifetime-layout objective tests:
   pressure/frame improvements with `0/2` expression progress must become
   exploratory, while actual expression improvement remains improved.
3. Add CLI plumbing for opt-in expression scoring:
   `--expression-target`, `--expression-baseline`, `--expression-source`, and
   `--expression-reg-class`.
4. Reuse the existing target-spec and expression-anchor scorer against compiled
   lifetime-layout probe pcdumps.
5. Attach candidate `expression_score` to JSON variants and include expression
   matched/targeted/delta fields in `pressure_score`.
6. Verify against the issue 897 reporter artifacts:
   expression generation emits semantically valid source, and compiled
   lifetime-layout variants with no anchor progress are not marked improved.

## Review Notes

An independent Codex subagent reviewed the issue evidence and confirmed two
root causes: the direct-row transform ignored temporal mutation of
`row_offset`, and lifetime-layout ranked frame/pressure wins without
expression-anchor progress.
