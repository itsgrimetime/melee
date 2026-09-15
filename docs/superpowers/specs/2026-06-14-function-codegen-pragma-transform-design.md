# Function Codegen Pragma Transform-Corpus Design

## Goal

Make `function_codegen_pragma_shape` executable for one narrow MWCC pragma shape: wrapping exactly one target function with a `#pragma push` / `#pragma dont_inline on` / `#pragma pop` pair, or removing that exact pair.

## Scope

This feature does not generate arbitrary compiler directives. The supported add form is:

```c
#pragma push
#pragma dont_inline on
<target function>
#pragma pop
```

The remove form only strips the exact immediate wrapper above. It does not remove unrelated pragmas, nested push/pop groups, comments, or directives separated from the function by other text.

## Safety Rules

The target function must be a focused single function definition resolved by `find_function`. The add probe is rejected if the function body or adjacent lines contain preprocessor directives, existing pragmas, labels, `case`, or `default`, because those shapes make directive scope ambiguous. The add probe also rejects functions with more than a small bounded number of non-empty body lines. The remove probe requires the exact wrapper to be immediately adjacent to the function and only removes those wrapper lines.

The mutators validate their cited source spans exactly. A stale span returns `None`; there is no fallback replacement elsewhere in the file.

## Integration

`function_codegen_pragma_shape` gets two concrete mutator keys:

- `add_dont_inline_pragma_pair`
- `remove_dont_inline_pragma_pair`

The full-source anchor generator lives in `transform_corpus.py`, next to the other source-spanning transform families. Probe payloads record the pragma kind, inserted/removed span, target function, and whether the probe adds or removes the wrapper. Common `TransformProbe` fields continue to provide `family_id`, `mutator_key`, and `probe_id`.

## Tests

Regression tests must prove:

- metadata and catalog counts move the family out of record-only status,
- safe wrapper insertion emits a candidate with push/dont_inline/pop around exactly the target function,
- exact wrapper removal emits the original unwrapped function,
- direct mutators reject stale spans,
- add probes reject preprocessor, existing pragma, label, case/default, and large body cases, and
- command-level `plan-transforms --write-probes --json` can emit the pragma family candidate.
