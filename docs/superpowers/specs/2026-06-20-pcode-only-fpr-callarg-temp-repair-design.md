# Pcode-Only FPR Call-Arg Temp Repair Design

## Context

Issue #874 covers `mnDiagram_DrawCellNumber` after the expression-scored
`coloring_register_steering@4` retained partial. The remaining target includes
an FPR call-argument temp that exists only in retained pcode:

- `f33=fmuls f35,f32` can be moved to the desired physical register with the
  existing force path.
- `f34=fsubs f52,f51` collapses into physical `f1` through `fmr f1,f34`, and
  the old `trace-copy` path returned copy-not-found because it only looked for
  GPR `mr` copies.

The matcher needs two reusable lanes:

1. FPR-aware copy tracing that can prove a pcode-only call-argument copy such as
   `fmr f1,f34`.
2. Ranked retained-source probes that alter the source shape around the
   `HSD_JObjReqAnimAll(jobj, (f32) digit)` argument and preserve the existing
   expression-score and structural-guard validation workflow.

The requested `superpowers:brainstorming` skill path was unavailable in this
checkout, so the implementation used the local fix-procedure plan/review flow
plus an independent Codex review before commit.

## Design

Extend `tools/melee-agent/src/mwcc_debug/copy_trace.py` so all copy discovery
accepts a register class. The GPR default remains `mr rTO,rFROM`; the FPR path
uses `fmr fTO,fFROM`, renders operands with `f` prefixes, and keeps the old JSON
shape while adding non-breaking metadata fields:

- `register_class`
- `from_token`
- `to_token`
- `copy_opcode`

Then add a transform-corpus family, `pcode_only_fpr_callarg_temp_repair`, rather
than a standalone one-off command. This keeps the repair lane inside
`debug search plan-transforms`, where the matcher already receives ranked
probes, optional validation, `expression_score`, structural guard output, and
terminal-blocker summaries.

The family scans `HSD_JObjReqAnimAll` calls whose animation argument is a cast
or immediately assigned FPR local. It emits concrete source variants that try
the common MWCC call-argument materialization shapes:

- dematerialize an otherwise-dead existing local into a direct cast argument
- use an assignment expression in the call argument
- preserve the existing local assignment while passing a direct cast
- reuse an earlier dead FPR local
- introduce a scoped FPR temp with assignment or initialization form

When validation finds no retained-source improvement, the search summary reports
`exhausted-pcode-only-fpr-callarg-temp-repair` rather than silently collapsing
the lane into generic select-order exhaustion.

## Non-Goals

This does not force a physical call-argument register directly, and it does not
generate edits from arbitrary unmapped pcode expressions. It only emits source
variants with precise source spans and relies on the existing compiler-backed
validation pipeline to rank or reject them.
