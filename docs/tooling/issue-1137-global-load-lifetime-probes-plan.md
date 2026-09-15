# Issue 1137: pcode-only global-load lifetime probes

## Scope

Issue #1137 asked the register-tiebreak workflow for
`mnDiagram2_HandleInput` to produce retained source probes for a pcode-only GPR
global-load lifetime, rather than stopping at generic guidance. The target
evidence was the `mnDiagram2_804D6C18` load boundary with requested
force-phys scores `IG97->r4` and `IG96->r6`.

This fix keeps the implementation on existing surfaces:

- transform-corpus source-probe generation
- `debug mutate lifetime-layout`
- existing local pcdump/checkdiff scoring

It does not add a new CLI command.

## Transform Design

The new transform family is
`pcode_only_gpr_global_load_lifetime_repair`, with mutator key
`steer_pcode_only_gpr_global_load_lifetime`.

The family discovers pointer globals from the selected source unit, including
include-resolved declarations, then searches only the resolved target function
body. It emits a bounded set of full-source C probes:

- `alias-first-member-use`: create an alias for the pointer global and rewrite
  the first `global->field` use through it.
- `alias-first-and-call-uses`: also rewrite nearby bare global call arguments.
- `hoist-existing-alias-init`: connect an existing later alias assignment to
  the new early alias.

Each candidate carries source hunks, the retained full source, the selected
global name/type, the strategy, and force-phys targets. Alias declarations are
inserted in the declaration block before `PAD_STACK(...)`, because `PAD_STACK`
is statement-like for the C dialect even though it appears among local
declarations. The alias assignment is emitted immediately before the first
rewritten global use, so the global load remains at the original use boundary
instead of being hoisted ahead of `PAD_STACK(...)`.

The family is registered for the mndiagram GPR coloring clusters and the
generic allocator fallback, and is force-class gated to GPR/class 0.

## Lifetime-Layout Scoring

`debug mutate lifetime-layout` now treats an explicit `--transform-family` as a
transform-only run unless other probe operators are also requested. Compiled
source probes retain:

- full source path
- retained pcdump path
- source hunks
- provenance payload
- target score parsed from `COLORGRAPH DECISIONS`

When all requested force-phys targets are not jointly recovered, the command
emits a terminal proof with retained candidates, target scores, source hunks,
pcdump paths, and a concrete source-level handoff.

## Validated Issue Run

Command:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug mutate lifetime-layout \
  -f mnDiagram2_HandleInput \
  --pcdump /Users/mike/.codex/worktrees/eeff/melee/build/diagnostics/mndiagram2_handleinput_current_1136cycle.pcdump.txt \
  --source-file src/melee/mn/mndiagram2.c \
  --compile-probes \
  --output-dir build/diagnostics/issue1137_global_load_lifetime \
  --transform-family pcode_only_gpr_global_load_lifetime_repair \
  --transform-force-phys 97:4,96:6 \
  --max-probes 6 \
  --timeout 180 \
  --json
```

The run generated and compiled three retained full-source candidates:

- `alias-first-member-use`, 2 source hunks
- `alias-first-and-call-uses`, 4 source hunks
- `hoist-existing-alias-init`, 3 source hunks

All three retained source and pcdump artifacts. The best match percentage was
`99.09210%` from `alias-first-member-use`, below the reporter baseline
`99.57895%`. Target scoring found zero hits:

- `IG97`: expected `r4`, best actual `r28`
- `IG96`: expected `r6`, best actual `r31`

The run therefore produced a terminal proof rather than a keeper.

Matcher ledger classification: `revert candidate` / terminal proof. The bounded
source shape to avoid retaining is the simple
`HSD_GObj* global_load_mnDiagram2_804D6C18_0;` alias with
`global_load_mnDiagram2_804D6C18_0 = mnDiagram2_804D6C18;` at the initial
`user_data` load and nearby `mnDiagram2_804D6C18` call arguments. The next
handoff is to try a different source-visible owner around the global-load /
`user_data` boundary rather than more simple early aliases.

## Tests

Focused coverage verifies:

- pointer-global lifetime probes materialize in a synthetic mndiagram-like
  function
- the family carries source hunks and all three strategies
- alias insertion stays before `PAD_STACK(...)`
- bare global assignments and address-taken uses are not rewritten
- lifetime-layout target scoring parses requested virtual-to-physical
  assignments from `COLORGRAPH DECISIONS`
- missing target virtuals are reported explicitly with `actual: null`
