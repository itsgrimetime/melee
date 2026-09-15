# Coloring Register-Steering Transform-Corpus Design

## Goal

Teach directed transform planning about the mndiagram register-coloring residual class so `plan-transforms` and `search run --directed-force-phys` no longer fall back to an unnamed generic allocator-shape bucket for those reports.

## Scope

Add one executable transform family, `coloring_register_steering`, for source edits that are already guarded by the directed-search transform corpus and are known to affect MWCC virtual-register ordering, live-range overlap, and allocator tie-breaks:

- adjacent declaration order rotation,
- declaration initializer split,
- nested loop-counter reuse,
- `int`/`s32` counter spelling changes,
- same-type local lifetime reuse.

The feature does not invent an unbounded register allocator solver and does not mark a residual solved unless a produced candidate actually scores as a byte match. It makes the actionable levers visible and runnable so matching agents can search the right family instead of getting only generic structural families.

## Planner Behavior

When a force-phys proof vector targets a known mndiagram coloring residual, the planner emits a named `mndiagram_coloring_register_steering` cluster instead of `generic_allocator_shape`. The cluster records all supplied force-phys assignments and selects only `coloring_register_steering`.

The first known function set is:

- `mnDiagram2_Create`
- `mnDiagram2_GetRankedFighter`
- `mnDiagram3_80245BA4`
- `mnDiagram_8024227C`
- `mnDiagram2_GetAggregatedFighterRank`

The detection can also accept other `mnDiagram*` functions with a force-phys vector because the cluster is conservative: it only enables pre-existing guarded source mutators, and those mutators still abstain when no safe anchor is present.

## Probe Generation

The family uses alias mutator keys so scoring telemetry can distinguish register-steering probes from the older structural families even when the underlying guarded edit is the same source change. Alias keys are thin dispatcher entries over existing mutators:

- `steer_reorder_local_decls`
- `steer_split_decl_init`
- `steer_reuse_loop_counter_scope`
- `steer_change_counter_width`
- `steer_reuse_same_type_local_lifetime`

`generate_transform_probes()` materializes alias probes only when the active plan includes `coloring_register_steering`. That avoids adding duplicate candidates to generic plans while ensuring a force-phys mndiagram run emits operators like `transform-corpus:coloring_register_steering`.

The existing source-shape iterator already discovers loop-counter reuse and same-type lifetime reuse. Declaration order, initializer split, and counter-width edits currently come from diagnosis-time `resolve_anchor()` and are not corpus-enumerated. This feature adds a steering-only, target-body anchor enumerator for adjacent local declarations, initialized declarations, and `s16`/`s32` counter declarations so the new family can actually materialize those source-level register-steering levers without requiring an external diagnosis variable name.

The steering-only declaration enumerator is deliberately narrower than general C parsing: it only considers unique, top-level target-body local declarations; rejects preprocessor-bearing bodies; rejects qualified declarations such as `const`, `static`, `volatile`, `extern`, `register`, and `inline`; swaps only uninitialized adjacent declarations; splits only unqualified initialized locals; and toggles `s16`/`s32` width only when the next non-empty line is a `for (<var> = ...)` loop using that local as a loop counter.

## Safety

All alias probes reuse the existing exact mutator validation. Source-shape aliases such as loop-counter reuse and same-type lifetime reuse also reuse the existing anchor analyzers. Steering-only declaration anchors are constrained as described above and still pass through the existing exact text mutators, so stale or non-unique spans abstain. The implementation must not loosen safety checks around declaration swaps, initializer splits, loop-counter reuse, counter-width toggles, or same-type lifetime reuse.

The transform family is medium risk because its purpose is code-generation steering, but each emitted candidate is still a source-preserving edit according to the existing analyzer contract.

## Integration

`debug search plan-transforms --json` must show the named cluster and the new family for mndiagram force-phys inputs. `debug search run --directed-force-phys` must be able to compile and score at least one `transform-corpus:coloring_register_steering` candidate when the source contains a matching anchor.

Existing command integration for `--include-transform-corpus` on coalesce, select-order, and frame-transform searches is left intact. The editable install must be refreshed after the change because this modifies `tools/melee-agent`.

## Tests

Regression coverage must prove:

- the new family is in the metadata/catalog and exposes concrete alias mutator keys,
- mndiagram force-phys planning returns `mndiagram_coloring_register_steering`, not `generic_allocator_shape`,
- generated probes for a mndiagram fixture materialize `coloring_register_steering` candidates from declaration-order, initializer-split, and loop-counter anchors,
- transform-probe adaptation keeps the steering probe when a base-family probe has duplicate candidate text and the steering probe was emitted first,
- alias mutator keys produce the same validated source edits as their underlying guarded mutators and return `None` for stale anchors,
- `search run --directed-force-phys` emits/scoring-telemeters a `transform-corpus:coloring_register_steering` candidate in a mocked dry-compiler run,
- generic non-mndiagram force-phys planning continues to use the bounded fallback.
