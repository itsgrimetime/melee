# Unused Trailing Parameter Transform-Corpus Design

## Goal

Make `unused_trailing_parameter` executable for narrow, self-contained static functions where the candidate source text contains every signature and direct call site that must change.

## Scope

The transform family gains two concrete probes:

- `remove_unused_trailing_parameter`: remove the final formal from a static target function when the body does not reference that parameter, and remove the corresponding final argument from every direct local call.
- `add_unused_trailing_parameter`: append `int unused` to a static target function and append `0` to every direct local call.

Both probes update the target definition and every source-local prototype for the target function. The probes do not edit headers, other translation units, function pointer types, callback tables, exported functions, or macro bodies. Because these probes edit source outside the target function body, they are marked as full-unit probes and must be scored through a full-unit candidate path rather than target-function transfer.

## Safety Rules

The analyzer only emits probes when the target function definition is `static`, non-varargs, and directly parseable from the candidate source. Non-static and `extern` functions are rejected because cross-TU callers may exist outside the candidate source.

Every source-local declaration for the target must be parseable, non-varargs, non-`extern`, and have the same parameter count as the definition. For removal, the trailing declaration parameter must have the same normalized type as the definition's trailing parameter. For addition, every declaration receives the same appended `int unused` parameter. If `unused` is already a target parameter name, the add probe is rejected rather than inventing another spelling.

Every direct call in every function body in the candidate source must be parseable and have the current target arity. Removal deletes the final argument; addition appends `0`. This includes expression call sites such as `return helper(x, 0) + 1;`, nested call arguments such as `sink(helper(x, 0));`, and multiple calls on one line. Calls inside comments, strings, or preprocessor directives do not count as proof. Any preprocessor directive that mentions the target function rejects the probe.

Zero-arity transitions are explicit. Removing the sole parameter changes declarations and definitions to `helper(void)` and calls to `helper()`. Adding to `helper(void)` changes declarations and definitions to `helper(int unused)` and calls to `helper(0)`.

The analyzer rejects address-taking, function-pointer/callback use, table initializers, indirect references, local shadows, macro-defined target names, varargs, non-trailing changes, unparseable call arguments, comments or string literals inside updated argument lists, and any remaining identifier reference to the target that is not one of the updated signatures or direct calls.

All edits are represented as exact source spans. The mutator validates every span before applying edits, sorts edits from right to left, and returns `None` if any span is stale.

## Scoring Contract

Generated probes include `requires_full_unit_source: true` in provenance and payload. Transform-probe adapters preserve that flag when converting probes to `LifetimeLayoutProbe`.

Search commands that compile generated transform probes must honor this flag. When a generated probe requires full-unit source and the original unit source path is known, the command passes `unit_source` to `compile_source_variant` so `debug dump local` compiles the whole candidate file with the correct unit context. Real-tree match-percent scoring must likewise apply the full candidate file to the resolved unit source instead of using `transfer_candidate`, which would drop prototype and caller edits.

If a command cannot determine the unit source for a full-unit probe, it marks the variant failed with a clear error instead of compiling a partial target-function transfer.

## Integration

The implementation adds these mutator keys:

- `remove_unused_trailing_parameter`
- `add_unused_trailing_parameter`

Anchor generation lives in `transform_corpus.py` alongside the other full-source analyzers because it must inspect the target function, source-local declarations, direct calls, and whole-file references together. Probe payloads include the parameter name, parameter type, parameter index, mode, proof source, `requires_full_unit_source`, `updated_call_sites`, and the exact edit list. Each `updated_call_sites` entry records the caller function, call span, old argument count, new argument count, and replacement text.

## Tests

Regression tests must prove:

- metadata and catalog docs move `unused_trailing_parameter` out of record-only status,
- removing a trailing unused parameter updates a static definition, local prototype, and all direct local call sites,
- adding a trailing unused parameter updates a static definition, local prototype, and all direct local call sites,
- stale multi-edit spans return `None`,
- unsafe cases are rejected: non-static/exported functions, `extern` declarations, used trailing parameters, varargs, mismatched prototypes, missing or unparseable call sites, required header/cross-TU edits that are not self-contained in the candidate source, address-taking, function-pointer storage, macro/preprocessor references, target-name shadowing, comments/strings in edited argument lists, and any remaining non-call reference to the target,
- command-level `plan-transforms --write-probes --json` can emit both add and remove candidates from focused fixtures,
- scoring paths for generated transform probes preserve full-unit edits by passing `unit_source` and by applying full candidate source during real-tree match-percent scoring.
