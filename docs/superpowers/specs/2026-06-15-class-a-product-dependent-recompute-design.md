# Class A Product-Dependent Recompute Design

## Goal

Issue #715 identifies five residual classes that the current transform corpus does
not crack. The highest-priority class is in-place coupled register recolor: two
same-class virtuals need different colors, but existing node-set split probes add
a new virtual and can grow the callee-save set or frame.

This slice adds one guarded Class A source-edit lever under the existing
`coloring_register_steering` family. It targets source shaped like
`mnDiagram_80241E78`:

```c
row_offset = y_offset * (f32) row;
row_offset_adj = row_offset - 1.0f;
```

The new probe recomputes the product at the dependent assignment:

```c
row_offset = y_offset * (f32) row;
row_offset_adj = (y_offset * (f32) row) - 1.0f;
```

The intent is to perturb MWCC CSE, live-range ownership, and first-use
tie-breaks without declaring a new local.

## Non-Goals

- Do not add a new CLI command.
- Do not change source files in `src/melee` by default.
- Do not resolve the #699 umbrella unless the resulting workflow also proves
  the broader umbrella criteria.
- Do not claim this transform is generally semantics-preserving for all floating
  programs. It is a decompilation search probe whose candidate must compile and
  score before use.
- Do not add unbounded expression rewriting. This change only handles one
  assignment-to-assignment pattern.

## Existing Evidence

On the current `mnDiagram_80241E78` source, the direct recompute variant compiles
and improves the function from `95.136185` to `99.06615`, reducing the structural
truth gate to `normalized_diff_lines=0` with the same frame size. Pairing the
same recompute with existing declaration-order steering probes did not produce a
byte match in a bounded manual check. This is useful evidence that the lever is
real, but it is not enough by itself to resolve #715; the issue's stop condition
still requires a verified `match=true` candidate produced through the new family.

## Selected Design

Add one direct mutator key to `coloring_register_steering`:

- `steer_fpr_dependent_product_recompute`

The analyzer works inside the target function body and emits exact-span payloads
only for a two-assignment region:

```c
    lhs = product_left * product_right;
    dependent = lhs +/- constant;
```

or the equivalent `constant +/- lhs` dependent form. The replacement duplicates
the original product expression into the dependent assignment. It emits two
bounded variants:

1. same-order recompute:

   ```c
   lhs = product_left * product_right;
   dependent = (product_left * product_right) +/- constant;
   ```

2. dependent-first recompute:

   ```c
   dependent = (product_left * product_right) +/- constant;
   lhs = product_left * product_right;
   ```

The dependent-first form is the "joint first-use reorder" piece of Class A: it
changes source-visible first-use pressure without adding an alias local. A
commuted-product variant is intentionally left out of this first slice because
manual evidence on `mnDiagram_80241E78` made that form worse and grew the frame.

The mutator itself is a span-validated replacement like the existing concrete
register-steering mutators. All proof lives in the analyzer; stale spans or
non-unique spans abstain.

## Safety And Abstain Rules

The analyzer must be narrower than the existing top-declaration steering gate so
that unrelated declarations such as `void** joint_data;` do not block the exact
product proof. It should still abstain aggressively:

- the function body must not contain preprocessor lines,
- both assignments must be top-level statements in the target function body,
- the product assignment must be a simple assignment statement, not declaration
  initialization or compound assignment,
- the dependent assignment must immediately follow the product assignment,
- the product target and dependent target must each have exactly one top-level
  scalar floating declaration in the function body,
- supported target/dependent types are `float`, `f32`, `double`, and `f64`,
- both product operands must be simple identifier or casted-identifier terms;
  at least one operand must reference a declared floating scalar local/parameter
  or an allowed scalar input cast such as `(f32) row`,
- reject calls, member access, indexed access, address-takes, nested operators,
  `++`, `--`, ternaries, commas, assignments inside operands, and macro-like
  statements,
- reject if the product target appears in either product operand,
- reject if either target name is shadowed by another declaration anywhere in
  the target body,
- reject if raw identifier mentions differ from literal/comment-blanked mentions
  for the edited variables,
- reject if the exact two-line span is not unique.

Floating recompute is a medium-risk search probe because it can change FP
exception timing and NaN/signed-zero behavior in abstract C. That is acceptable
for transform-corpus candidates because the workflow compiles and scores them;
the generated candidate is never applied automatically.

## Probe Ordering

For `coloring_register_steering`, product-dependent recompute should be emitted
before broad alias declaration swaps when present. Existing node-set-delta probes
already take first priority when explicit delta evidence is supplied; this new
lever should then appear before blind declaration-order probes so the real
`mnDiagram_80241E78` target is visible with the default `max_per_family=3`.

Recommended order for non-delta concrete steering:

1. `steer_fpr_dependent_product_recompute`
2. `steer_rotate_local_decl_window`
3. `steer_demote_local_decl_to_first_use`
4. `steer_reuse_dead_top_level_loop_counter`
5. `steer_split_reused_loop_counter`
6. `steer_widen_byte_local_type`
7. existing alias keys

## Testing

Add regression coverage for:

- metadata/catalog includes `steer_fpr_dependent_product_recompute`,
- a `mnDiagram_80241E78`-shaped fixture emits the recompute probe under
  `coloring_register_steering` despite an unrelated `void**` declaration,
- the generated candidate duplicates the product expression, does not add a
  local declaration, and carries strategy metadata,
- the dependent-first variant appears before same-order recompute when budget is
  one,
- the exact mutator rejects stale spans,
- default-budget ordering emits the recompute probe before blind declaration
  steering,
- negative cases for non-FPR locals, declaration initializers, nested statements,
  non-adjacent dependent assignments, calls, member/index access, dependent
  expressions with multiple uses of the source local, address-takes, shadowed
  declarations, and preprocessor-bearing bodies,
- a CLI `plan-transforms --source-file --write-probes --json` smoke for
  `mnDiagram_80241E78` writes a recompute probe file.

## Resolution Gate

#715 may only be resolved if at least one listed function gets a verified
`match=true` candidate through the new Class A family. If the implemented
family only improves a candidate or produces bounded negative evidence, leave
#715 open with a note describing the added family, the scored result, and the
remaining residual class.
