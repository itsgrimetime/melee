# Issue #1121 Select-Order Li and Pointer-Walk Probes Plan

## Scope

Issue #1121 asks `melee-agent` to turn the `mnDiagram2_Create` select-order
diagnostics into bounded retained C probes for two source-visible source levers:

- the threshold literal feeding a `li` first definition, targeting `IG36->r27`;
- the row `JObj` pointer-walk address expression, targeting `IG51->r27`.

The result is complete only when the original workflow produces retained source
candidates with `source_hunks`, retained source, retained pcdumps, and
`target_score`, or a populated terminal proof showing the bounded family was
exhausted with a concrete source-level next handoff.

## Root Cause

The retained Case-C window-order planner could continue from indexed-byte
source candidates, but two source-attribution families were missing:

1. `li rN,imm` first definitions had no source bridge back to local literal
   assignments or declaration initializers, so threshold constants stopped at an
   unsupported source-attribution diagnostic.
2. implicit address temps for pointer-walk call arguments could see a pcode
   `add`, but they did not rank the matching C argument expression such as a
   casted byte-pointer walk. The planner therefore named a synthetic temp gap
   instead of emitting executable C probes.

The validator also lacked a generic `score-source` path for force-phys target
YAML files, so retained full-unit candidates could be compiled and retained but
not scored with the requested virtual-to-register assignments in the same
workflow.

## Implementation

1. Add reusable literal-owner discovery for `li` first definitions in
   `window_order_source.py`. Rank local assignments and declaration initializers
   by immediate value, local reads, and nearby paired literals, then materialize
   bounded temp-introduction probes with source diffs and source hunks.

2. Add reusable pointer-walk argument discovery for implicit address-temp
   `add` producers. Rank safe casted byte-pointer arguments by callee,
   argument index, base expression, shift, offset, and source locality; emit
   rejected diagnostics for unsafe expressions instead of silently dropping the
   family.

3. Preserve the new ranked candidate metadata through the transform-corpus
   continuation and CLI retained-candidate summaries so validated runs keep the
   source evidence needed by matchers.

4. Extend `debug target score-source` to recognize target YAML files with a
   `force_phys` mapping. The generic path compiles the full-unit retained
   source, retains the pcdump, and emits a `target_score` summary using the
   existing force-phys scoring primitives.

5. Commit the design and acceptance note with the feature. The implementation
   was plan-reviewed by an independent Codex subagent before the production
   change and validated against the original reporter workflow afterward.

## Regression Tests

Add coverage for:

- synthetic `li` literal-owner materialization and exhausted-family terminal
  diagnostics;
- synthetic pointer-walk add materialization, unsafe-expression rejection, and
  exhausted-family terminal diagnostics;
- transform-corpus continuation rows for both new probe families;
- retained summary preservation of the new ranked-candidate evidence; and
- generic `score-source` force-phys target scoring from a synthetic pcdump,
  proving the validator is not hardcoded to the `mnDiagram2_Create` artifact.

## Acceptance

The validated #1121 reporter workflow produces two retained full-function C
probes under `build/diagnostics/issue1121-probes-validated/`:

- `retained_gpr_case_c_window_order_continuation@0.c` for the threshold literal
  family, with retained pcdump
  `retained_gpr_case_c_window_order_continuation@0.pcdump.txt` and
  `target_score.total = 2000000`;
- `retained_gpr_case_c_window_order_continuation@1.c` for the pointer-walk
  address family, with retained pcdump
  `retained_gpr_case_c_window_order_continuation@1.pcdump.txt` and
  `target_score.total = 2000328`.

Both candidates preserve source hunks and both score `matched = 0` of the two
requested assignments. The accepted result is therefore terminal proof:
`ranked-indexed-byte-window-order-probes-exhausted`.

The next source-level handoff is no longer "add another unsupported family".
The remaining work is a coupled source model that can change the live-range or
interference shape around the threshold literal and row pointer-walk together:
target-aware live-range anchors, interference shaping, implicit-index
normalization or aliasing, implicit-base aliasing, address-side/value-side temp
splits, or a coupled address/value transform.
