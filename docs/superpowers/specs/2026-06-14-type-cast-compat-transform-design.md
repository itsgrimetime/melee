# Type And Cast Compatibility Transform-Corpus Design

## Goal

Make three record-only type-spelling families executable in narrow, locally proven cases:

- `redundant_pointer_cast_elision`
- `callback_cast_elision`
- `vector_alias_type_shape`

## Scope

Pointer and callback cast probes only elide explicit casts in a target function body. They do not insert casts. Pointer casts support call arguments and simple assignments where local source context proves both sides of the cast are redundant: the callee formal or assignment target already requires the cast type, and the casted expression is already declared with that same type. Callback casts are intentionally call-argument-only.

Vector alias probes only rewrite local type spelling between two source-local aliases with identical simple struct layout, for example:

```c
typedef struct Vec3 { f32 x; f32 y; f32 z; } Vec3;
typedef struct Point3d { f32 x; f32 y; f32 z; } Point3d;
```

The vector alias probe rewrites a focused target function local declaration type token, not function signatures, field accesses, or headers outside the candidate source.

## Safety Rules

The analyzer requires all proof to be present in the candidate source text. It rejects varargs, macros/preprocessor regions, macro-defined type tokens, volatile-qualified types, casts inside comments/strings, address-taking of function names, function-pointer table initializers, and any case where declarations outside the candidate source would need edits.

Pointer cast elision is allowed when a local prototype or definition proves the callee formal at that argument index has the same normalized pointer type as the cast and target-body local declarations prove the casted expression already has that same normalized pointer type. Assignment cast elision is allowed only when target-body local declarations prove both the left-hand side and the casted expression have that same normalized pointer type. Any target-body typedef, local variable, function-pointer declaration, or `struct`/`union`/`enum` tag definition that shadows a participating type token blocks the probe.

Callback cast elision is allowed only when a source-local typedef or function-pointer formal proves an identical function-pointer signature and none of the callback signature's type tokens are macro-defined or shadowed in the target body. It is intentionally limited to call arguments; table entries and callback storage are left record-only.

Vector alias spelling is allowed only when both aliases are source-local `typedef struct` definitions with identical field type/name sequences, the target token is a standalone local declaration type token, and the replacement does not shadow another local type name or change an externally visible function declaration.

All mutators validate exact source spans. A stale span returns `None`; there is no fallback text search.

## Integration

The implementation adds these concrete mutator keys:

- `elide_redundant_pointer_cast`
- `elide_callback_cast`
- `rewrite_vector_alias_type`

Full-source anchor generation lives in `transform_corpus.py` because local prototypes, typedefs, and target body spans must be inspected together. Probe payloads include the cast type, expression, proof source, callee/argument index when applicable, source and destination type names, and target function.

## Tests

Regression tests must prove:

- metadata and catalog counts move all three families out of record-only status,
- pointer call-argument casts and pointer assignment casts can be elided when local types match,
- callback call-argument casts can be elided when a local function-pointer typedef/formal signature matches,
- vector alias local declaration type spelling can be rewritten when layouts match,
- unsafe cases are rejected: varargs, missing prototype, incompatible pointer expression type, volatile types, macro/preprocessor cases, target-body typedef and struct-tag shadowing, function address-taking, function-pointer table initializers, non-identical vector layouts, local alias-name shadowing, comments/strings/preprocessor regions, and stale spans,
- command-level `plan-transforms --write-probes --json` can emit all three type/cast family candidates from a single fixture.
