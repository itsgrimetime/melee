# Node-Set Planning Diagnostics Design

Date: 2026-06-18
Issues: #783, #784, #785

## Problem

Three node-set/source-transform reports share one theme: the tooling is close to actionable, but it can still emit invalid split candidates, spend unbounded time planning recursive source probes, and hide the residual evidence needed after a wrong-register outcome.

- #783: `debug solve node-set-split --var j` can generate retained sources where a synthetic `j_split_*` local is declared in one loop/block and referenced outside that declaration scope.
- #784: `debug search plan-transforms` with a node-set delta can hang in write-only planning before writing probe files.
- #785: wrong-register node-set rows do not surface the achieved register/coupled residuals or retain the compile-ok candidate source.

## Goals

- Generated node-set alias/lifetime candidates must not reference synthetic locals outside their declaration block.
- Plan-transform generation for node-set deltas must stay bounded in write-only mode and avoid recursive combo expansion.
- Wrong-register node-set summaries must include row-level target/achieved register data and a retained compile-ok source path.
- Exhausted runs containing only wrong-register and compile-failed outcomes must report a terminal source-shape stop condition.
- Source-line scoped node-set deltas must prefer the innermost same-name declaration when nested shadowing is present.

## Non-Goals

- No new CLI command.
- No change to register allocation semantics or objective evaluation.
- No attempt to solve backend-only residuals; this only makes the stop condition and residuals inspectable.

## Selected Design

1. Add a source-scope validation guard in `node_set_split.py` for synthetic locals produced by alias/lifetime edits. The guard finds the declaration's containing brace block and rejects candidates if any use of that synthetic name falls outside the block or before the declaration.

2. Keep source-line scope anchoring for repeated locals and prefer the innermost containing declaration after exact declaration-line matches. This prevents an inner use line from anchoring to an outer same-name local.

3. Bound node-set delta planning by disabling combo expansion in recursive introduce-binding and transform-corpus generation paths. Single explicit `node-set-split` keeps combo candidates available, but write-only `plan-transforms` and coupled composition use non-combo split families.

4. Retain compile-ok wrong-register candidate sources under `build/mwcc_debug_cache/probes/node_set_split/wrong_register/`. Add `source_retained`, `target_ig`, `target_reg`, `target_reg_num`, `achieved_reg`, `achieved_register`, and `coupled_registers` to candidate rows where available.

5. Mark no-pending candidate sets as terminal when every evaluated row is either wrong-register or compile-failed and at least one wrong-register residual exists.

## Alternatives Considered

- Add a new `--scope` or `--source-line` option for #783. This may still be useful later, but it does not prevent invalid generated C from any other automatic path.
- Add only a CLI timeout to #784. That would stop the hang, but still leaves planning able to spend the whole budget before producing any bounded probe set.
- Leave wrong-register details nested under `objective`. That technically preserves data, but agents need row-level fields and retained source paths to classify and replay residuals.

## Acceptance Criteria

- Unit tests reject an out-of-scope synthetic split-local source shape.
- Unit tests prove source-line node-set scope selection prefers the innermost same-name declaration.
- Unit tests prove introduce-binding planning can call split generation without invoking combo expansion.
- Unit tests prove wrong-register summaries expose achieved registers and retained source paths.
- Unit tests prove mixed wrong-register/compile-failed exhaustion emits a terminal reason.
- CLI smoke checks for `debug solve node-set-split --help` and `debug search plan-transforms --help` still pass.
