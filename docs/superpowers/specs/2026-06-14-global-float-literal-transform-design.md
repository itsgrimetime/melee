# Global Float Literal Transform-Corpus Design

## Goal

Make `global_float_literal_shape` executable for a narrow, source-local proof: swapping an inline floating literal with a unique named global floating constant, or replacing that constant reference with its literal spelling.

## Scope

The supported declarations are scalar constants before the target function:

```c
static const f32 lbl_804D8000 = 0.5f;
const double lbl_804D8008 = 0.75;
```

The analyzer accepts `f32`/`float` as 32-bit constants and `f64`/`double` as 64-bit constants. It rejects `volatile`, arrays, local constants inside functions, macro expressions, hexadecimal floats, integer-only literals, declarations inside comments/strings or disabled preprocessor regions, and declarations after the target function. For `f32`/`float`, the proof requires `f`/`F` literal spelling. For `f64`/`double`, the proof requires unsuffixed floating spelling. This avoids silent type-promotion and rounding ambiguity.

## Safety Rules

A declaration is usable only when its type width and target-width binary value are unique in the source-local declarations before the target function. `f32`/`float` values are normalized by their IEEE-754 32-bit representation; `f64`/`double` values are normalized by their IEEE-754 64-bit representation. Duplicate equal-valued constants of the same width are ambiguous and produce no probes for that value, even when the decimal spellings differ.

Inline literal replacement scans only the resolved target function body with comments and string/character literals blanked. It only rewrites floating-token spans whose width and normalized binary value match exactly one source-local constant. It rejects target functions where a parameter, top-level local, or nested-block local shadows that constant symbol, and it rejects static-local initializer contexts where replacing a literal with an identifier would stop being a C constant expression. Constant-to-literal replacement scans only identifier uses of that same unique constant in the target body and rejects address-taken uses such as `&lbl_804D8000` and any target-body shadow of the symbol.

Both mutators use exact span validation. If the cited source text no longer matches the candidate source, the mutator returns `None` instead of searching elsewhere.

## Integration

`global_float_literal_shape` gets two concrete mutator keys:

- `replace_float_literal_with_global_constant`
- `replace_global_float_constant_with_literal`

The full-source anchor generator lives in `transform_corpus.py` beside `string_literal_data_blob_field_shape`. Probe payloads record the symbol name, literal text, normalized value, width, proof source, mode, and target function. Common `TransformProbe` fields continue to provide `family_id`, `mutator_key`, and `probe_id`.

## Tests

Regression tests must prove:

- metadata and catalog counts move the family out of record-only status,
- f32 and f64 inline literals can be replaced with unique constants,
- constant references can be replaced with their literal spelling,
- direct mutators reject stale spans,
- duplicate target-width equal constants, suffix/type-width ambiguity, local constants, volatile declarations, hex floats, macro expressions, commented/string/disabled declarations, comment/string body literals, target-body symbol shadowing, static-local initializers, and address-taken symbol uses are rejected, and
- command-level `plan-transforms --write-probes --json` can emit a `global_float_literal_shape` candidate.
