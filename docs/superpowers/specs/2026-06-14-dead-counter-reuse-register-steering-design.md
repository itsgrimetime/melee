# Dead Counter Reuse Register Steering Design

## Goal

Issue #699 remains open after adding declaration-window rotation, declaration
demotion, and reused-counter splitting because real `mnDiagram2_Create`
validation still produces only negative evidence. The next concrete
`coloring_register_steering` lever should target the current diagnostic:
source lifetime / callee-save shape, especially branch-local or later-loop
counter reuse.

The feature adds one narrow transform-corpus mutator:

- `steer_reuse_dead_top_level_loop_counter`

This is a source-local, C89-safe register-steering edit. It does not add new
declarations and does not change public search commands.

## Current Context

`mnDiagram2_Create` has a top-level `for (i = 0; i < 15; i++)` loop followed by
a later top-level `j = 0; do { ... j++; scroll++; } while (j < 10);` loop. The
baseline checkdiff is not purely register-only: it has one control-flow/source
shape line delta plus many register-only diffs and a callee-save swap. Current
diagnostics recommend source lifetime/callee-save shape rather than more
force-vector probing.

The existing `reuse_loop_counter_scope` mutator only removes a nested
redeclaration so an outer counter is reused. It does not cover this real shape:
an earlier top-level loop counter is dead after its loop, while a later
top-level loop uses a different same-type counter.

## Approaches Considered

1. Add a broad loop-shape normalizer that converts `do` loops to `for` loops
   and rewrites increment placement. This could address the one-line structural
   mismatch but has a large semantic surface because `do` loops execute at
   least once and `for` loops may not.
2. Add allocator-side force or select-order search expansion. The current
   diagnostics already say the relevant force vector is satisfied and that the
   remaining issue is source lifetime/callee-save shape, so this would spend
   effort in the wrong layer.
3. Add a narrow top-level dead-counter reuse source transform. This directly
   targets the reported function shape, preserves C89 declaration placement,
   and can be tested with exact-span proof guards. This is the selected
   approach.

## Selected Design

Add `steer_reuse_dead_top_level_loop_counter` as a direct
`coloring_register_steering` key. The analyzer works inside one target function
body. It finds:

- an earlier top-level loop whose counter is assigned in the loop header before
  use,
- a later top-level loop or `do` loop that assigns a different same-type counter
  before use,
- both counters declared once as uninitialized top-level `int`, `s32`, `u32`,
  `s16`, or `u16`,
- no uses of the earlier counter after the earlier loop and before the later
  loop,
- no uses of the later counter between its declaration and the selected later
  loop except the selected prelude assignment and later loop header/body,
- no uses of either counter after the later loop.

For the motivating pattern:

```c
    int j;
    int i;

    for (i = 0; i < 15; i++) {
        sink(i);
    }

    j = 0;
    do {
        use(j);
        j++;
    } while (j < 10);
```

the candidate becomes:

```c
    int i;

    for (i = 0; i < 15; i++) {
        sink(i);
    }

    i = 0;
    do {
        use(i);
        i++;
    } while (i < 10);
```

The accepted `do` shape is deliberately narrow. The later loop prelude must be
an immediate top-level assignment line `later = init;` followed only by blank
lines or comments before `do {`. Any executable statement, declaration,
preprocessor line, label, or macro-looking statement between the assignment and
the `do` line rejects the probe. The replacement is one contiguous exact span
from the later counter declaration line through the later loop. That lets the
mutator remove the later declaration and rewrite the prelude and loop in one
validated splice. Simple top-level `for` support uses one contiguous span from
the later counter declaration line through the `for` loop, but `do`-prelude
reuse candidates are emitted before simple later-`for` candidates so the real
`mnDiagram2_Create` lever is visible under the default budget.

## Safety Rules

The proof uses comment/string/char-literal blanking for identifier analysis but
splices original source text. Across the exact transformed span, raw identifier
spans for both counters must equal the spans found in blanked text; this
rejects counter mentions in comments or string/char literals instead of trying
to rewrite or preserve them. Control-flow and macro-looking barrier checks are
applied to the earlier loop, the selected later prelude/loop, and the region
between those loops. The broader exact span may include unrelated setup
statements that are not rewritten. It rejects:

- preprocessor lines in the function body or transformed region,
- labels, `goto`, `case`, `default`, `break`, or `continue` in either loop
  region,
- macro-looking all-caps statement calls in the transformed region,
- address-takes of either counter,
- member-name false positives such as `obj->i`,
- any nested or duplicate declaration of either counter name anywhere in the
  function body,
- any mention of the reused earlier counter inside the later loop prelude or
  later loop region before rewriting,
- any mention of the later counter outside the selected later-loop prelude,
  header, and body,
- any mention of either counter after the later loop,
- any non-comment, non-blank statement between a `do`-loop prelude assignment
  and the `do` line,
- duplicate exact span text,
- declaration-order-only pairing. Pairing is based on loop order, because
  `mnDiagram2_Create` declares `j` before `i` even though the `i` loop is the
  earlier loop.

The transform is intentionally top-level only. Nested branch-local variants can
be added later with separate proof rules if this direct lever is insufficient.

## Probe Ordering

Default-budget visibility is part of the feature. For the real
`mnDiagram2_Create` source, `plan-transforms --max-per-family 3` must emit a
`steer_reuse_dead_top_level_loop_counter` candidate. The concrete steering
generation order becomes:

1. `steer_rotate_local_decl_window`
2. `steer_demote_local_decl_to_first_use`
3. `steer_reuse_dead_top_level_loop_counter`
4. `steer_split_reused_loop_counter`
5. existing alias keys when budget remains

This avoids the current failure mode where default-budget validation sees only
rotate/demote/rotate candidates.

## Integration

Update:

- `DEFAULT_TRANSFORM_FAMILIES` metadata for `coloring_register_steering`,
- `_DIRECT_REGISTER_STEERING_KEYS`,
- mutator dispatch in `mutators.py`,
- a new dead-counter-reuse anchor generator in `transform_corpus.py`,
- `_iter_concrete_register_steering_body_anchors` so it interleaves the new
  generator into the default-budget concrete steering order,
- source-transform catalog counts and key lists,
- transform-corpus generation tests,
- exact-span mutator tests,
- CLI probe-writing smoke tests.

No CLI options or new command surfaces are added. Existing consumers should see
the candidate through the normal `transform_probe_adapter` and directed-search
proposal paths.

## Testing

Regression coverage should include:

- metadata includes the new direct key,
- exact-span mutator applies the whole-region counter reuse and rejects stale
  spans,
- a synthetic fixture emits rotate, demote, and dead-counter reuse under
  `max_per_family=3`,
- a fixture shaped like `mnDiagram2_Create` emits the dead-counter reuse key
  under default budget,
- unsafe fixtures reject old-counter mentions inside the later loop,
  later-counter mentions before or after the selected later loop, member
  access, counter mentions in comments/literals, nested declarations,
  address-takes, macro-looking statements, labels, preprocessor lines,
  executable statements between a `do` prelude assignment and `do`, post-loop
  uses of either counter, and duplicate spans,
- consumer coverage proves the new candidate retains stable transform-corpus
  provenance through `transform_probe_adapter` or an existing directed-search
  smoke,
- installed CLI smoke writes the candidate and validates real
  `mnDiagram2_Create` probes with `debug dump local --diff`.

## Resolution Gate

Resolve #699 only if the implemented candidate reaches the issue's stated stop
condition: a produced candidate reaches `checkdiff_gate=byte_match` or an
equivalent command-level byte-match check for a coloring residual. If the new
candidate compiles but does not byte-match, leave #699 open with evidence and
release the claim.
