# Signature Call-Site Localization Design

## Problem

Issue #431 reports that, after the signature-audit routing/rebucket work in
`14341a861`, a top-60 `signature-call-type` sample produced 1327 findings and
all actions rebucketed to `call-not-localized`. The live example
`fn_8019F9C4` resolves the source file and parses 101 C call sites, but the
auditor records ASM call targets such as `fn_8019F9C4+0x88` and cannot map them
back to source calls.

The missing piece is relocation-aware call target parsing. In checkdiff output,
the instruction line may show a placeholder branch target:

```text
+08c: 48 00 00 01     bl      <fn_8019F9C4+0x8c>
+08c: R_PPC_REL24     fn_80168F7C
```

The real callee is the `R_PPC_REL24` symbol. The current parser ignores that
line, treats the offset placeholder as the call target, and all source lookup
fails.

## Goals

- Resolve `bl` call targets through following same-offset `R_PPC_REL24`
  relocation lines before pairing calls or looking up source call sites.
- Preserve the displayed instruction target for diagnostics while using the
  resolved relocation target for call target ordinals.
- Add diagnostic-only source localization by overall call ordinal for
  non-relocated external calls whose target still does not match source
  spelling.
- Prevent overall-ordinal fallback from emitting automatic patch candidates.
- Rebucket unresolved function-local offset branch-link targets to a narrower
  structural reason instead of `call-not-localized`.
- Rebucket relocated calls with no matching source expression to a narrower
  generated-helper/structural reason instead of `call-not-localized`.
- Keep `call-not-localized` only for unresolved nonlocal calls.

## Non-Goals

- Do not rewrite `find_call_sites()` globally.
- Do not attempt full C/ASM control-flow reconstruction.
- Do not use overall call ordinal localization as proof for automatic source
  edits.
- Do not resolve every relocation type; this slice only needs call-site
  `R_PPC_REL24`.

## Design

`_AsmCall` gains `display_target` and `relocation_target` fields. `call_target`
continues to mean the target used for pairing and source lookup, but it now
prefers the relocation target when present:

1. Parse the `bl` instruction target as `display_target`.
2. Scan the next few raw checkdiff lines for a same-offset `R_PPC_REL24`.
3. If found, normalize that relocation symbol as `relocation_target`.
4. Set `call_target = relocation_target or display_target`.

`_call_shape_dict()` includes both `display_target` and `relocation_target` so
JSON consumers can see why a placeholder became a real callee.

`_SourceContext` gains:

- `function`: the audited function name.
- `call_sites_by_overall`: parsed source calls keyed by overall source order.

`_build_source_context()` fills both maps and filters obvious non-call parser
artifacts for signature auditing, currently `PAD_STACK` and `void`.

`_source_site_for_call()` lookup order becomes:

1. Exact `(resolved_call_target, target_ordinal)`.
2. No fallback if the unresolved display target is a function-local offset
   placeholder such as `fn_8019F9C4+0x88` with no relocation target.
3. No overall fallback for relocated calls. A relocation target with no exact
   source expression is treated as a generated-helper/structural case.
4. Overall source call ordinal fallback for non-relocated external calls, marked
   with `localization_kind="overall-ordinal"`.
5. Existing `(resolved_call_target, 1)` fallback for nonlocal calls.

Exact localization is marked `localization_kind="target-ordinal"`.

Patch generation refuses diagnostic overall-ordinal localization. It can still
emit affected call-site details and narrower audit/rebucket guidance, but not a
high-confidence `remove-call-arg-cast` patch.

Rebucket helpers receive call context. If no source site is available and the
target is an unresolved function-local offset placeholder, actions rebucket to:

```python
{
    "reason": "intra-function-branch-link",
    "work_bucket": "structural-reconstruction",
    "subcategory": "branch-link-control-flow",
}
```

Only nonlocal unresolved calls keep `call-not-localized`.

If the call has a real `R_PPC_REL24` target but no matching source expression,
actions rebucket to:

```python
{
    "reason": "relocated-call-not-in-source",
    "work_bucket": "structural-reconstruction",
    "subcategory": "relocated-helper-no-source-call",
}
```

This covers generated helper calls such as `HSD_JObjSetMtxDirtySub` that appear
in ASM but not as direct C call expressions.

## Testing

Add focused unit tests for:

- `R_PPC_REL24` resolving a placeholder `bl <caller_fn+0x20>` to a real helper
  callee, eliminating false call-target-shape mismatch and enabling exact source
  localization.
- Overall ordinal fallback localizing a nonmatching external callee to a source
  call with `localization_kind="overall-ordinal"` while refusing patch output.
- Unresolved function-local offset targets rebucketing to
  `intra-function-branch-link` without mapping to an unrelated source call.
- Call-target-shape mismatches on unresolved local offset targets using the same
  narrower rebucket.
- Relocated calls with no source expression rebucketing to
  `relocated-call-not-in-source`.

Add a live smoke check for `fn_8019F9C4`: `call-not-localized` must no longer be
present in the reported function. The expected improvement is that many
placeholder targets resolve to real callees through `R_PPC_REL24`, and generated
helpers without source calls receive `relocated-call-not-in-source`.

## Review Notes

An independent review rejected the initial idea of treating all
`fn+0x...` targets as intra-function branch-links. The accepted refinement is
to parse `R_PPC_REL24` first and classify only unresolved function-local offset
targets as structural branch-link cases.
