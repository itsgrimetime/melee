# Helper Shape Transform-Corpus Design

## Goal

Make the `helper_shape` transform family executable for narrow, source-local helper boundary experiments. Matching agents should be able to request `helper_shape` probes from `plan-transforms` and the directed-search consumers without receiving only record-only metadata.

## Scope

This change implements two guarded helper-boundary probes:

- Inline a simple file-local helper call at a target-function call site.
- Extract repeated simple target-function assignment RHS expressions into a generated file-local helper and rewrite those assignments to call it.

The feature deliberately avoids general C refactoring. It does not move complex helper bodies, preserve arbitrary declarations, infer struct layouts, or rewrite preprocessor-controlled regions. Unsafe shapes are rejected instead of emitted as candidate files.

## Helper Inlining

Inlining searches for `static` helper definitions before or elsewhere in the same source file. A helper is eligible only when it has a plain scalar return type, scalar value parameters, and a body with exactly one of these forms:

```c
return expr;
```

or:

```c
T tmp;
tmp = expr;
return tmp;
```

The helper body must have no labels, `case`/`default`, preprocessor lines, loops, branches, direct or indirect calls, multiple exits, nested braces, pointer/member access, array indexing, assignments inside the returned expression, increment/decrement, top-level comma, `&&`, or `||`. Every identifier in the returned expression must be one of the helper parameters; free identifiers are rejected so inlining cannot accidentally bind to a target-function local with the same name. Every parameter referenced in the returned expression must have the same scalar type as the helper return type, so inlining does not drop a helper-level conversion or narrowing step. Call sites are limited to one line inside the requested target function. The call line must contain exactly one call to the helper outside comments and literals. Argument substitution preserves evaluation order by accepting only bare scalar identifiers or integer literals. If a parameter is used more than once in the helper expression, the corresponding argument is still safe because the accepted argument forms are single-evaluation scalar values.

The emitted mutator replaces the call expression with a parenthesized inline expression on the same line and records the helper name, helper source span, original line, replacement line, return expression, and parameter mapping in the probe payload. These fields are required so `TransformProbe.payload` carries enough provenance for matching agents to audit why a candidate was generated.

## Helper Extraction

Extraction is intentionally narrower. It targets repeated assignment RHS expressions in the requested function body:

```c
lhs_a = arg0 + local;
lhs_b = arg0 + local;
```

An extraction probe is eligible only when at least two assignment lines in the same target body have byte-identical simple RHS text, all assigned variables have one known source-local scalar type, and every RHS identifier operand has a known scalar type from the function parameters or local declarations. The RHS may use only identifiers, integer literals, parentheses, and simple arithmetic operators. It must not contain pointer/member access, address/deref operators, side effects, calls, array indexing, assignments, top-level comma, logical short-circuiting, preprocessor text, or unsupported tokens. The generated helper is inserted immediately before the target function with a stable unique name:

```c
static T target__helper_shape_N(param_types...) {
    return rhs;
}
```

All repeated assignment lines in the target body are rewritten to call the generated helper with operands ordered by first use in the RHS. The anchor payload records the helper name, target function, RHS, operand order, operand types, replacement pairs, insertion line, and helper text. This gives matching agents a real helper-boundary variant while keeping the rewrite reversible and auditable.

## Integration

`helper_shape` moves from record-only metadata to a concrete family with two mutator keys:

- `inline_simple_helper_call`
- `extract_repeated_assignment_helper`

`iter_source_shape_anchors` remains responsible for target-body anchors. Full-source helper anchors live beside the existing full-source transform-corpus generators because inlining needs access to other file-local function definitions and extraction inserts a helper outside the target body.

`generate_transform_probes(..., families=("helper_shape",))` should produce helper probes even when the diagnostic plan falls back to the generic cluster. The generic fallback cluster should include `helper_shape` so command-level runs can find helper probes without special-casing.

The existing `TransformProbe` wrapper remains responsible for common provenance: `family_id`, `mutator_key`, `probe_id`, source span, and the stable tried key returned by `transform_probe_key(probe)`. Helper-shape tests must assert these fields in addition to helper-specific payload provenance.

## Tests

Regression coverage must prove:

- `helper_shape` is no longer record-only in family metadata and catalog docs.
- A simple static helper call in the target function produces an inline candidate.
- A helper with assign-then-return body can inline its assigned expression.
- Inline probe payloads preserve helper name, helper span, return expression, original line, replacement line, and parameter mapping.
- Inline helpers with free identifiers are rejected, including a fixture where the target function has a same-named local that would capture the free name.
- Inline helpers whose return expression would rely on a return-type conversion are rejected.
- Unsafe helper calls are rejected when substitution could duplicate side effects or when the helper body has pointer/member access, direct calls, indirect calls, branches, preprocessor lines, labels, `case`/`default`, or multiple exits.
- Repeated simple assignment RHS expressions produce one extracted helper and rewrite all repeated assignment lines.
- Extraction payloads preserve helper name, target function, RHS, operand order, operand types, insertion line, helper text, and replacement pairs.
- Extraction rejects unknown operand types, mixed assignment destination types, pointer/member access, calls, array indexing, labels, preprocessor lines, expressions with side effects, and expressions that occur only once.
- Helper probes assert common provenance: `family_id == "helper_shape"`, expected `mutator_key`, non-empty `probe_id`, source span, and stable `transform_probe_key(probe)` format.
- Command-level `plan-transforms --write-probes --json` writes helper probe files from the generic fallback cluster, and a consumer command using `--transform-family helper_shape` can filter to helper probes.
