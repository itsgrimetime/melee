# Signature Prototype Source-Lever Ranking Design

## Context

Issue #435 reports that `melee-agent debug suggest signatures` can produce
`source-lever-audit` stop conditions for localized signature mismatches without
giving agents an executable next step. Representative cases include:

- `pl_80038144`: `same-tu-static-prototype-audit` actions on
  `fn_80037F00` for argument source-register cascades. Manual prototype and
  call-site experiments did not improve the caller.
- `it_802A7384`: clean `global-prototype-candidate` actions for
  `it_802A6F80`, but `proposed_type` is `null` because the mismatch only has
  register-presence evidence.
- `grAnime_801C7228`, `grStadium_801D4548`, and `fn_80315C44`: repeated
  visible prototype candidates where the current prototype already has a
  register-bank-compatible type, but the report still stops as if source
  prototype work is pending.

The recurring failure is that diagnostic prototype context is counted as a
source lever even when there is no proposed type change, no safe patch, and no
ranked call-site transform to validate.

## Goals

- Preserve useful prototype candidates when there is a concrete source edit:
  generated same-TU static patches, cross-TU type proposals, and validated cast
  removal patches must keep their current behavior.
- Add enough metadata for register-presence prototype candidates to explain the
  type decision: expected ABI bank, current prototype bank, candidate source,
  and why no type edit is proposed.
- Stop reporting source-lever actions when the prototype already matches the
  expected ABI bank or when the mismatch is actually a register/source cascade.
- Rebucket non-actionable prototype context with concrete reasons so harvest
  campaigns can move to the right work bucket instead of looping on signature
  prototype campaigns.
- Keep the change bounded to `debug suggest signatures`; do not edit Melee C
  source or change `checkdiff.py` scoring semantics.

## Non-Goals

- Do not build a general source-expression rewriter for argument reorder,
  temporary extraction, or pointer/address rewrites.
- Do not apply cross-translation-unit prototype patches automatically.
- Do not infer pointer target types from register presence alone. A GPR register
  can carry pointers and integers, so register presence is only ABI-bank
  evidence unless there is stronger prep/load evidence.

## Approaches Considered

1. **Generate speculative call-site rewrites.** This would try swapping,
   inserting, or casting call arguments when prototype candidates are weak.
   It is powerful, but unsafe without expression-to-register provenance. The
   pl_80038144 examples show that naive rewrites can worsen the caller.

2. **Treat every visible prototype as source-actionable.** This preserves the
   current source-lever stop condition and adds explanatory text. It does not
   unblock harvest agents because the queue still points at prototype work with
   no candidate to execute.

3. **Separate executable candidates from diagnostic prototype context.**
   Candidate actions are emitted only when there is a proposed type change or
   patch. Otherwise the audit attaches prototype context to a concrete rebucket
   such as `prototype-already-matches-abi-bank`,
   `prototype-candidate-unsupported`, or `register-source-cascade`.

The chosen approach is option 3. It matches the issue's stop condition: either
emit an executable candidate, or rebucket with a concrete reason.

## Design

### Candidate Type Decision

Prototype candidate construction will compute a small decision object:

- `current_type`: visible prototype parameter type, if present.
- `current_bank`: ABI bank implied by `current_type`.
- `expected_register` and `current_register`: the register slots carried from
  `_ArgPrepComparison`, even when no `_ArgPrep` exists.
- `expected_bank`: ABI bank implied by the expected prep, or by
  `expected_register` when the prep is absent.
- `proposed_type`: a concrete type only when the evidence supports a meaningful
  type edit.
- `patch_status`: `generated`, `cross-translation-unit`,
  `already-matches-abi-bank`, `unsupported-type-shape`,
  `unsupported-parameter-shape`, or existing statuses such as
  `duplicate-visible-declarations`.
- `decision_reason`: concise explanation of why the candidate is executable or
  why it is diagnostic only.

For width mismatches, existing prep-based inference remains authoritative.
For presence mismatches, register bank evidence is used only to detect whether
the visible prototype is compatible. It is not enough evidence to infer a
specific scalar or pointer type. If the prototype bank already matches the
expected register bank, the audit must not emit a source-lever candidate. If the
prototype bank differs, rebucket the finding as unsupported prototype evidence
unless another source of evidence, such as a real prep-width mismatch, produces
a concrete `proposed_type`. Same-TU static patches must not be generated from
register-presence bank evidence alone.

### Rebucket Rules

When prototype context is not executable:

- `argument-source-register-mismatch` remains
  `register-source-cascade`; same-TU static prototypes must not override this
  with `same-tu-static-prototype-audit`.
- Register-presence candidates whose visible prototype already matches the
  expected ABI bank rebucket to `prototype-already-matches-abi-bank` under
  `signature-call-type/argument-presence`.
- Prototype candidates without enough type evidence, including bank-only
  register-presence mismatches where the visible prototype bank differs from
  the expected register bank, rebucket to
  `prototype-candidate-unsupported` under the same signature bucket.
- Existing no-prototype, variadic-tail, source-arity, relocated-call, and
  intra-function branch-link rebuckets keep their current behavior.

### Output Shape

Executable prototype candidates keep the existing `candidate` object and add:

- `expected_bank`
- `current_bank`
- `candidate_source`: one of `prep-width`, `register-presence-bank`, or
  `source-prototype`
- `decision_reason`

Diagnostic rebucket actions include `prototype_context` nested under
`action.rebucket` with the same fields when available. This gives agents the
useful facts without counting the action as a source lever. The schema is:

- `call_target`
- `arg_index`
- `current_type`
- `proposed_type`
- `current_bank`
- `expected_bank`
- `expected_register`
- `current_register`
- `prototype_scope`
- `candidate_source`
- `decision_reason`

### Validation

Existing `--validate` behavior applies only to patch-bearing actions. Diagnostic
rebuckets are intentionally not validated because they have no source patch.
Same-TU static prototype patches and cast-removal patches keep the existing
temp-object validation path.

### Testing

Add focused regressions for:

- Same-TU static argument-source-register mismatch rebuckets to
  `register-source-cascade` instead of `same-tu-static-prototype-audit`.
- Global register-presence mismatch with a bank-compatible pointer prototype
  rebuckets to `prototype-already-matches-abi-bank` and includes prototype
  context.
- Global register-presence mismatch with a mismatched prototype bank rebuckets
  to `prototype-candidate-unsupported` with prototype context, because bank-only
  evidence is not a safe type proposal.
- Same-TU static register-presence mismatch with a mismatched prototype bank
  also rebuckets to `prototype-candidate-unsupported`; no patch is generated
  without stronger type evidence.
- Existing regressions that currently accept `proposed_type=None` candidates,
  such as unsupported `clrlwi` width evidence, should move to concrete rebucket
  expectations unless the action has a patch or a meaningful proposed type.
- CLI JSON/text output includes the new metadata for candidates and rebuckets.

Live smoke checks should cover at least `it_802A7384` and `pl_80038144` to
confirm the previous `source-lever-audit` outputs now either rebucket or produce
concrete candidate metadata.
