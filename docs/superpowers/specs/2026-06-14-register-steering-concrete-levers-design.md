# Register-Steering Concrete Levers Design

## Goal

Issue #699 reports that `coloring_register_steering` engages on mndiagram coloring residuals but does not yet expose enough source levers to reach byte matches. This feature adds concrete, guarded register-steering probe classes under the existing transform-corpus family without changing the solver or loosening semantic safety.

## Existing Context

The current family is mostly an alias layer. It renames existing guarded edits such as adjacent declaration swaps, initializer splitting, loop-counter reuse, counter-width toggles, and same-type lifetime reuse so directed scoring can attribute them to register steering. That made the workflow visible, but it does not cover the issue's named source-actionable levers:

- split reused loop counters into distinct locals,
- demote an uninitialized declaration closer to its first use,
- rotate a small local declaration window to change MWCC virtual-register order.

Existing coloring tools remain the diagnostic layer: `debug solve coloring`, `debug suggest register-tiebreak`, `debug inspect virtual-to-var`, `debug solve node-set-split`, and `debug mutate decl-orders`. This design only expands transform-corpus candidate generation.

## Approaches Considered

1. Extend the solver so it emits transform-corpus anchors from colorgraph variables. This is high leverage but crosses solver, pcdump, variable attribution, and source rewriting. It is too broad for this queue item.
2. Add unbounded source perturbations to `coloring_register_steering`. This may find candidates but risks producing unsafe C edits and noisy search output.
3. Add three narrow source-local probe classes with exact-span mutators and conservative abstain rules. This is the selected approach because it expands the family in the issue's requested direction while keeping tests and safety understandable.

## Selected Design

Add three direct mutator keys to `coloring_register_steering`:

- `steer_rotate_local_decl_window`
- `steer_demote_local_decl_to_first_use`
- `steer_split_reused_loop_counter`

These keys are not aliases for a base transform family. They are emitted directly by the register-steering analyzer, dispatched directly in `mutators.py`, and use span-validated replacement payloads. The family remains medium risk because these are codegen steering edits, but every emitted candidate is proof-gated and exact-span validated.

### Declaration Window Rotation

The analyzer scans the target function body only. It finds contiguous top-level local declaration windows of three uninitialized register-sized declarations in the same block. Supported declaration types are explicit scalar integer/float typedef spellings already treated as simple by this file (`char`, `s8`, `u8`, `short`, `s16`, `u16`, `int`, `s32`, `u32`, `long`, `float`, `f32`) plus pointer declarations whose type text contains `*`. It rejects aggregate-by-value typedefs such as `Vec3 pos;`, declarations with initializers, qualifiers (`static`, `extern`, `volatile`, `register`, `const`, `inline`), arrays, multi-declarators, labels, preprocessor-bearing bodies, and duplicate exact window text.

For a window:

```c
    s32 a;
    s32 b;
    HSD_GObj* gobj;
```

it emits one candidate that rotates the last line to the front:

```c
    HSD_GObj* gobj;
    s32 a;
    s32 b;
```

This gives the allocator a stronger declaration-order perturbation than adjacent swaps while preserving uninitialized declaration semantics.

### Declaration Demotion To First Use

The analyzer finds an uninitialized top-level supported declaration whose first variable mention after the declaration appears on one allowed top-level first-use line. Source is scanned with comments and string/char literals blanked for proof checks, while replacement text is taken from the original source. Allowed first-use lines are intentionally narrow:

- assignment LHS: `name = ...;`
- function-call argument/use: `callee(... name ...);`
- simple assignment RHS/use: `other = ... name ...;`

It rejects first-use lines with `++`, `--`, compound assignments to the variable, address-takes (`&name`), macro-looking all-caps calls, labels, `goto`, `case`, `default`, `return`, `break`, or `continue`. It rejects any crossed region containing a label, `goto`, preprocessor directive, macro-looking statement, nested block boundary, declaration of the same name, or any mention of the demoted variable before the destination. It also rejects destination lines inside nested blocks, duplicate exact span text, and unsupported declaration types.

For:

```c
    s32 temp;
    s32 rank;
    rank = seed + 1;
    temp = rank;
```

it emits:

```c
    s32 rank;
    rank = seed + 1;
    s32 temp;
    temp = rank;
```

This can demote a virtual-register source variable in MWCC's declaration/use ordering without changing expression evaluation.

### Reused Loop Counter Split

The analyzer detects two disjoint top-level `for` loops in the same function body that reuse a previously declared counter:

```c
    s32 i;
    for (i = 0; i < a_count; i++) {
        total += a[i];
    }
    for (i = 0; i < b_count; i++) {
        total += b[i];
    }
```

It rewrites the later loop to use a fresh counter declared immediately before that loop:

```c
    s32 i_1;
    for (i_1 = 0; i_1 < b_count; i_1++) {
        total += b[i_1];
    }
```

The proof is intentionally narrow:

- the original counter must be declared once as a top-level uninitialized `int`, `s32`, `u32`, `s16`, or `u16`,
- loops must be top-level in the target body and not nested in branches,
- the selected later loop body must contain only simple identifier uses of the counter, not address-takes, increments outside the loop header, macro/preprocessor lines, string literals, labels, `goto`, `continue`, or `break`,
- the original counter must not be used between the previous loop end and selected loop start, except in the selected loop header/body,
- the original counter must not be used after the selected loop,
- the generated fresh name must not already exist in the function body,
- exact span validation must reject stale candidates.

This covers the common source-preserving "same counter reused for disjoint loops" pattern while abstaining from nested-loop semantics.

## Integration

The new anchors are produced only when `coloring_register_steering` is allowed by the active plan. Existing generic transform families should not receive these new mutator keys. `plan-transforms --write-probes --json` must materialize the new candidates for a mndiagram force-phys fixture. The transform-probe adapter and existing search commands consume them through existing transform-corpus provenance.

Budgeting must not let the older alias probes starve the new concrete levers. Within `coloring_register_steering`, probe generation should interleave categories and reserve the first available slots for distinct mutator keys in this priority order:

1. `steer_rotate_local_decl_window`
2. `steer_demote_local_decl_to_first_use`
3. `steer_split_reused_loop_counter`
4. existing alias keys

With the default `max_per_family=3`, a fixture containing all three new concrete levers must emit all three. With a smaller budget, the prefix of that priority order is emitted deterministically. Alias probes still appear when budget remains.

The source-transform catalog gains three directed mutator keys and updates the `coloring_register_steering` row to say it now includes concrete declaration-window, declaration-demotion, and counter-split probes. Declaration-demotion and fresh counter declarations must remain in the top-level declaration prologue so generated candidates stay compatible with the repo's MWCC/C89 source shape.

## Testing

Regression coverage must include:

- metadata asserts the family has the old alias keys plus the three new keys,
- exact mutator tests for all three new keys, including stale-span rejection,
- positive probe-generation tests for declaration-window rotation, declaration demotion, and reused-loop-counter split under default `max_per_family=3`,
- rejection tests for qualified declarations, initialized declaration windows, duplicate window text, nested loops, counter uses after the selected loop, address-takes, generated-name collision, preprocessor-bearing bodies, and complex counter expressions,
- rejection tests for unsupported aggregate-by-value declarations and demotion across label/goto/macro/nested-block barriers,
- CLI `plan-transforms --source-file --write-probes --json` smoke that writes candidates for all three new mutator keys,
- broader directed-search regression tests used by recent transform-corpus changes.

## Resolution Gate

Issue #699 should only be resolved if the implementation is verified and a real or command-level search demonstrates that the new concrete `coloring_register_steering` candidates are emitted for the reported mndiagram coloring workflow. If no byte-match candidate can be verified within the run, leave #699 open with a note describing the implemented families and the remaining byte-match evidence gap.
