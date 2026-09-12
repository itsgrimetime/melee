# Signature Prototype Candidate Inference Design

## Problem

Issue #433 reports that, after call-site localization, the signature audit still
terminates many localized argument findings with broad fallback reasons:

- `prototype-candidate-missing` for localized argument-presence mismatches.
- `width-prototype-candidate-missing` for localized argument-width mismatches.

The audit already knows the source line, call target, source argument text,
visible prototype metadata, expected/current ABI registers, and expected/current
prep opcodes. The missing layer is a conservative source-candidate model that
turns that localized evidence into bounded prototype/callsite guidance or a
narrower non-actionable reason.

## Goals

- For localized `argument-width-mismatch` findings, infer the expected ABI type
  family from the expected prep opcode/width and compare it to the visible
  callee parameter type and source argument type.
- For localized `argument-register-presence-mismatch` findings, infer whether
  the mismatch is a likely prototype arity/type issue, variadic tail case,
  macro/generated call, or external prototype gap.
- Emit structured candidate metadata on actions so JSON consumers can see:
  candidate kind, proposed type, current type, prototype scope, blast radius,
  validation status, and why a patch is or is not generated.
- Generate automatic patch candidates only for same-translation-unit static
  prototype or definition parameter type changes that are one-line, exact-text
  replacements.
- Reuse existing signature validation for generated patch descriptors. A
  prototype patch is validated the same way as a removable call-argument cast:
  temporary source, temporary object, checkdiff score, real source restored.
- Replace broad fallback rebuckets with narrower terminal reasons when no safe
  source candidate is available.

## Non-Goals

- Do not rewrite public headers or cross-translation-unit declarations.
- Do not add or remove function parameters automatically.
- Do not infer whole-project type ownership.
- Do not infer prototypes for unresolved function-local branch-link or
  relocated helper calls; #431 already rebuckets those structurally.
- Do not auto-apply patches.

## Design

`SignatureAction` gains an optional `candidate` dictionary. It is included in
`dataclasses.asdict()` output, so the existing JSON command surface carries it
without custom serialization. Text output prints a short candidate line when
present.

`_PrototypeInfo` is extended with enough source location data for bounded
patches:

- `is_definition`
- `line`
- `param_texts`
- `param_names`
- `declaration_count`
- `source_scope`, one of `same-tu-static`, `visible-nonstatic`, or `unknown`

The existing visible prototype parser already finds prototypes and same-TU
definitions. It will keep the same matching boundaries, but will preserve each
parameter's raw one-line text and normalized type/name split. If the parameter
list spans multiple lines, a parameter cannot be split safely, the parameter is
a function pointer or array declarator, or the callee has both a forward
prototype and a later definition, no patch is generated; the action still
reports a candidate with `patch_status` such as
`unsupported-parameter-shape` or `duplicate-visible-declarations`.

The candidate inference runs inside `_actions_for_finding()` after the existing
remove-call-arg-cast path and before the generic fallback rebucket.

Prototype patches require trusted localization. A patch may be generated only
when `localization_kind == "target-ordinal"` and the localized source call
target exactly matches the resolved ASM call target. Overall-ordinal
localization may still emit diagnostic candidate metadata, but never a patch.

### Width Candidates

For `argument-width-mismatch`, infer an expected type from the expected prep:

| Expected prep | Candidate type |
| --- | --- |
| `extsb` or 8-bit signed evidence | `s8` |
| `lbz` or 8-bit zero-extension evidence | `u8` |
| `extsh`/`lha` or 16-bit signed evidence | `s16` |
| `lhz` or 16-bit zero-extension evidence | `u16` |
| simple 32-bit GPR evidence | `s32` |

`clrlwi`, `rlwinm`, `bool`, enum-like names, pointers, arrays, function
pointers, and unknown typedefs are evidence-only unless the existing parameter
is already a simple scalar integer type that can be rewritten safely. Unsupported
cases report candidate metadata with `patch_status="unsupported-type-shape"`.

If the localized call target has a visible same-TU static prototype or
definition and the parameter at `arg_index` is safely patchable, emit:

```python
SignatureAction(
    kind="same-tu-static-prototype-candidate",
    confidence="medium",
    candidate={
        "kind": "prototype-parameter-type",
        "call_target": "...",
        "arg_index": 0,
        "current_type": "int",
        "proposed_type": "s8",
        "prototype_scope": "same-tu-static",
        "blast_radius": "same-translation-unit",
        "patch_status": "generated",
        "reason": "...",
    },
    patch=PatchDescriptor(...),
)
```

If the prototype is visible but non-static, emit
`global-prototype-candidate` without a patch and with
`blast_radius="cross-translation-unit"`. If no prototype is visible, rebucket to
`external-prototype-unavailable` instead of
`width-prototype-candidate-missing`.

### Presence Candidates

For `argument-register-presence-mismatch`, candidate generation is deliberately
more conservative because presence mismatches often indicate arity, macro, or
structural call-shape issues.

If the localized source call has a source argument at `arg_index`, infer the
argument's candidate ABI type from local type evidence, literals, casts, and
prep bank/width. Then:

- Variadic tail argument (`prototype.is_variadic` and
  `arg_index >= len(param_types)`): rebucket to `variadic-prototype-tail`
  before any same-TU or global prototype candidate generation.
- Same-TU static prototype with a parameter at `arg_index`: emit
  `same-tu-static-prototype-candidate` without an automatic patch unless the
  mismatch is reducible to a parameter type change and the parameter text is
  safely patchable.
- Visible non-static prototype: emit `global-prototype-candidate` without a
  patch.
- No visible prototype: rebucket to `external-prototype-unavailable`.

If the localized source call has no source argument at `arg_index`, rebucket to
`source-call-arity-mismatch`; this is a call-shape or macro/source-expression
problem rather than a bounded prototype type edit.

To make that arity case observable, localized argument comparison must include
surplus expected/current argument preps after the parsed source-argument count.
Those surplus comparisons produce `argument-register-presence-mismatch`
findings with `source_arg=None` and the `source-call-arity-mismatch` rebucket.

### Summary Behavior

Patch-bearing prototype candidates count as patch candidates and are validated
by the existing `validate_signature_patches()` path. Non-patch prototype
candidates count as source-lever actions, alongside the existing
`same-tu-static-prototype-audit` action class. The new non-patch candidate kinds
must be added to `SOURCE_LEVER_ACTION_KINDS` so summary output reports
`source_lever_action_count`, keeps `audit_only_unrebucketed == 0`, and reaches
the `source-lever-audit` stop condition. Broad
`prototype-candidate-missing` and `width-prototype-candidate-missing` remain
only as last-resort fallbacks for unexpected states.

## Testing

Add unit tests in `tools/melee-agent/tests/test_mwcc_debug_signature_audit.py`
for:

- Width mismatch on a same-TU static helper produces a
  `same-tu-static-prototype-candidate` with a patch changing the parameter type,
  and validation attaches a score to that patch.
- Width mismatch on a visible non-static prototype produces a
  `global-prototype-candidate` without a patch and reports cross-TU blast
  radius. Assert `source_lever_action_count == 1`,
  `audit_only_unrebucketed == 0`, and stop condition
  `source-lever-audit`.
- Width mismatch with no visible prototype rebuckets to
  `external-prototype-unavailable`, not
  `width-prototype-candidate-missing`.
- Presence mismatch on a variadic tail argument rebuckets to
  `variadic-prototype-tail`.
- Presence mismatch with no source argument rebuckets to
  `source-call-arity-mismatch`.
- Same-TU static helper with both a forward prototype and a definition emits
  `same-tu-static-prototype-candidate` metadata but no patch, with
  `patch_status="duplicate-visible-declarations"`.
- Overall-ordinal localization can emit diagnostic candidate metadata but no
  patch.
- Unsupported parameter shapes, including multi-line params, function-pointer
  params, and array params, do not generate patches and report an explicit
  `patch_status`.

Add one CLI JSON regression in `tools/melee-agent/tests/test_debug_cli_reorg.py`
to prove candidate metadata appears in `debug suggest signatures --json`.
Add one text CLI regression proving the concise candidate line is printed.

Run a live top-sample smoke after implementation:

```bash
melee-agent debug suggest signatures -f fn_8019F9C4 --json
```

Expected sample-level success is not that every localized finding gets a patch.
It is that localized argument-presence/width findings produce either candidate
actions or narrower terminal reasons, reducing generic
`prototype-candidate-missing` and `width-prototype-candidate-missing` counts.

## Review Notes

The design intentionally avoids automatic global prototype edits. The first
patchable surface is same-TU static helpers because the validation harness can
score the exact source change while keeping real source and build objects
unchanged.
