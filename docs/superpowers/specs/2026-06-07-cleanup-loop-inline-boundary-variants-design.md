# Cleanup Loop and Inline Boundary Variants Design

## Context

Two open tooling issues ask for source-emitting variants rather than advisory
reports:

- #497: `source-lifetime` needs cleanup-loop zero/index/cursor role probes for
  repeated `row_labels[i]` free/null loops such as `fn_802461BC`.
- #498: `structure-search` needs an `inline-boundary` axis that retains and
  scores bounded source candidates instead of reporting
  `future_axes inline-boundary=not-implemented`.

Both issues fit the existing `debug search structure` pipeline: generate
candidate source files, score them through the existing structure scorer, and
rank the retained variants.

## Approaches Considered

1. **Focused source generators in existing modules.** Add cleanup-loop probes to
   `pressure_explorer.generate_source_lifetime_probes` and add an
   `inline-boundary` axis in `search.structure`. This is recommended because it
   reuses scoring, retained-source output, and ranking without inventing a new
   harness.
2. **Extend `patterns inlines` only.** This would improve advisory text, but it
   would not produce source candidates or checkdiff scores, so it would not
   unblock the reported campaigns.
3. **Build a generic helper-extraction engine.** This could cover more future
   inline cases, but it is too broad for these concrete reports and risks
   producing unsafe source rewrites.

## Design

### Cleanup-Loop Source-Lifetime Probes

Add a targeted `cleanup-loop-role-shape` family to source-lifetime probes. It
detects bounded `for` loops whose body checks an indexed pointer slot, calls a
cleanup function on the same slot, and assigns that slot to `NULL`.

For each safe loop, emit bounded variants:

- **slot base temp:** load the repeated slot base such as `array` into a typed
  local and keep indexed access through that base.
- **slot counter role:** wrap the loop with a scoped counter local, then write
  the resulting counter value back to the original loop counter after the loop.
- **value temp:** load `array[i]` into a local, check/free that local, then null
  the original slot.
- **slot cursor:** introduce `HSD_Text**`-style cursor iteration with
  `for (i = 0, cursor = array; i < bound; i++, cursor++)`. The cursor
  declaration is placed at the top of a new block wrapping the original loop, so
  the candidate remains C89-safe even when the loop appears after executable
  statements.
- **null sentinel:** introduce a typed `NULL` local and reuse it in the check
  and store.
- **all-repeated-loop application:** for repeated loops with the same slot
  family and cleanup callee, emit a bounded null-sentinel candidate that applies
  the same store/check rewrite to all matching loops in the target function, in
  addition to first-loop-only candidates.

Each variant includes provenance: slot expression, index variable, bound,
cleanup callee, source line, and variant kind. When repeated cleanup loops are
found, the generator emits at least one all-repeated-loop candidate before the
per-occurrence variants so capped structure-search runs score the coordinated
source shape. Per-occurrence variants follow so first-loop-only candidates still
exist.

The initial implementation will use a callee-specific type mapping for
`HSD_SisLib_803A5CC4`: slots passed to this cleanup are treated as `HSD_Text*`
values and `HSD_Text**` cursors. Other cleanup callees are skipped until a safe
type source is available.

### Inline-Boundary Structure Axis

Add `inline-boundary` to `SUPPORTED_STRUCTURE_AXES`. The axis scans source and
emits retained source variants for conservative classes:

- **axis setter wrapper selection:** when file-local fake `HSD_JObjSetTranslate*`
  wrappers exist, replace direct `HSD_JObjSetTranslateX/Y/Z` calls in the target
  function with the matching fake wrapper. If the fake wrapper definition
  appears after the target function, the candidate also inserts a matching
  `static inline` prototype immediately before the target function. This avoids
  implicit extern calls and later `static inline` conflicts.
- **call argument tempization:** reuse existing `call-argument-tempization`
  lifetime probes but tag them as inline-boundary candidates.
- **gobj user-data cast:** convert simple `data = gobj->user_data;` assignments
  to explicit typed casts when the lhs declaration type is known.
- **SisLib cleanup helper extraction:** for the same cleanup loop shape, insert a
  small static inline helper before the target function and replace one cleanup
  body with a helper call on `&array[i]`.

The axis returns `AxisSummary(axis="inline-boundary", status="evaluated")` when
it retains candidates, and a blocked summary with family metadata when none are
safe. `future_axes` should no longer list `inline-boundary` once the axis is
implemented.

## Data Flow

`debug search structure --axis inline-boundary` resolves the source file, calls
`generate_inline_boundary_variants`, writes candidate `.c` files under
`build/structure-search/<function>/inline-boundary`, then optionally scores them
through the existing `score_structure_variants` path.

`debug search structure --axis source-lifetime` continues to use
`generate_source_lifetime_variants`; the only change is that its targeted probe
families now include cleanup-loop role-shape candidates.

## Safety

All generators are local, bounded, and syntax-preserving:

- They only rewrite inside a located target function except for helper
  extraction and wrapper prototype insertion. Helper extraction inserts a single
  file-local static inline helper immediately before that function; wrapper
  selection may insert a matching `static inline` prototype before the function
  when the wrapper definition appears later in the file.
- They skip regions containing preprocessor directives.
- They require the cleanup slot expression to be identical across null-check,
  cleanup call, and null store.
- They emit retained candidates for scoring rather than applying source edits to
  the working tree.

## Testing

Regression coverage will include:

- Direct cleanup-loop probe generation for slot-base, cursor, counter,
  value-temp, and null-sentinel variants, plus all-repeated-loop candidates.
- Source-lifetime structure search retaining cleanup-loop variants under small
  caps.
- Inline-boundary axis support, retained candidate files, axis-wrapper variants,
  user-data cast variants, SisLib helper extraction, and removal of the
  `future_axes inline-boundary` placeholder.
- CLI smoke for `debug search structure --axis inline-boundary` on
  `mnDiagram3_80245BA4`, including a scored run over a small candidate cap so
  at least one generated variant reports `compile_status == "ok"` and
  `checkdiff_status == "ok"`.
