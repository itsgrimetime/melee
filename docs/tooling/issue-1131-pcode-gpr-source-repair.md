# Issue 1131: pcode-only GPR bool/mask source repair

## Scope

Issue #1131 needs plan-transforms to stop terminalizing class-0 GPR
boolean/mask residuals as a bare unresolved source region. This pass implements
a bounded transform-corpus family, not the deeper virtual-attribution bridge.

The family is `pcode_only_gpr_bool_mask_temp_repair`. It is available from the
generic fallback plan and the existing mnDiagram-style GPR coloring cluster,
and it is force-class gated to class 0.

## Transform Design

The family scans the selected function body for bounded, single-evaluation
source spans:

- Scalar mask predicates, including `if (inputs & CONST)`,
  `else if (inputs & CONST)`, `if ((inputs & CONST) && other)`, and
  `if (inputs_repeat & CONST)`.
- Negated JObj dirty flag masks such as
  `if (!(jobj->flags & JOBJ_MTX_INDEP_SRT))`.
- Direct translate setter calls where a dirty-wrapper spelling is visible in
  the source/TU, such as a file-local `mnVibration_JObjSetTranslateX/Y/Z` or
  `HSD_JObjSetTranslateX/Y/ZWithMtxDirty`.

Predicate probes introduce a scalar temp declaration in the enclosing block's
declaration area, assign the temp immediately before the condition, and replace
only the mask operand. `else if` probes are rewritten as a nested
`else { temp; temp = expr; if (temp) { ... } }` block so the inserted statement
does not break the `if` chain. Dirty flag probes bind the inner mask and use
`if (!temp)`.

All probes use exact validated-span replacement and carry `source_hunks` in the
probe payload. Predicate temps require a unique normalized mask expression, but
translate-call substitutions are allowed at repeated call spellings because the
validated span offset identifies the exact statement. Duplicate normalized mask
expressions, multi-mask conditions, unsafe expressions, missing dirty wrappers,
and unresolved spans are reported as family diagnostics and zero-probe reasons.

## Terminal Proof

`plan-transforms --validate-command ... --json` now summarizes scored
`pcode_only_gpr_bool_mask_temp_repair` candidates. When all scored candidates
produce no retained source improvement and no target hit, the JSON includes:

- `terminal_proof`
- `terminal_blockers`
- exhausted family id
- evaluated candidate count
- retained source and pcdump paths when provided by the validator
- target score
- source hunks
- source regions and strategy
- a concrete source-level handoff

This is the matcher ledger handoff for issue #1131 when the bounded C probes do
not move the residual force-phys targets.

## Tests

Focused coverage was added for:

- Generic mask predicate, negated dirty-flag predicate, and dirty-wrapper call
  materialization with `source_hunks`.
- `else if (inputs & CONST)` materialization through a valid nested `else`
  block.
- Ambiguous duplicate mask predicates returning zero probes with
  `ambiguous-source-region`.
- Executable registry metadata and planner inclusion.
- Validation-summary terminal proof/no-hit output with retained source, pcdump,
  target score, and source-level handoff.

## Matcher Handoff

For `fn_80247510`, run:

```bash
melee-agent debug search plan-transforms \
  -f fn_80247510 \
  -u melee/mn/mnvibration \
  --force-phys 112:5,174:4,177:0,196:6,242:0,247:3 \
  --transform-family pcode_only_gpr_bool_mask_temp_repair \
  --write-probes /tmp/issue-1131-probes \
  --json
```

Then score retained candidates with the existing `debug target score-source`
workflow, or pass the equivalent score command through `--validate-command` to
collect validation results in this JSON. Keep a candidate only if it improves
fresh checkdiff or produces a new target-register hit. If all candidates score
flat/no-hit, copy the `terminal_proof` from the validation summary into the
matcher ledger.

Validated issue #1131 run:

- Generated 12 bounded full-unit probes for `fn_80247510`: six shifted
  controller mask predicate temps and six cursor JObj translate dirty-wrapper
  substitutions.
- All probes carried `source_hunks`, retained source paths, retained pcdump
  paths, and force-phys `target_score` entries for
  `112:5,174:4,177:0,196:6,242:0,247:3`.
- Predicate-temp probes scored as no-hit/neutral against the requested targets.
- Dirty-wrapper substitutions scored as target-hit active experiments:
  `matched=2/6`, hitting `IG177->r0` and `IG242->r0`.

Matcher ledger classification: `active experiment`. The exact source-shape
idea is to try retaining one cursor translate dirty-wrapper call substitution,
starting with the first upward-navigation X translation:

```c
mnVibration_JObjSetTranslateX(cursor_jobj, temp_x);
```

This is not a terminal proof because the bounded family found scored candidates
that hit requested target registers.
