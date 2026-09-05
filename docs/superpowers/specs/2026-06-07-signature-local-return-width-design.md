# Signature Local Return-Width Design

## Problem

`debug suggest signatures` can identify argument-prep mismatches and prototype parameter candidates, but it misses a related return-value pattern: a narrow helper return is masked immediately at the call site even when the target keeps the raw return value live and masks only at later consumers.

For `mnDiagram2_UpdateHeader`, the target code after `mnDiagram_GetNameByIndex` and `mnDiagram_GetFighterByIndex` keeps the helper result with `mr r31,r3`; current code emits `clrlwi r31,r3,24` because the visible helper prototypes return `u8`. Broadly changing the helper return type to `int` improves `mnDiagram2_UpdateHeader` and `mnDiagram2_Create`, but it regresses sibling ranked helper callers. The tool needs bounded, source-emitting variants that explore local return-width shapes without presenting a broad prototype change as a ready fix.

## Goals

- Detect post-call return-width mismatches in `debug suggest signatures`.
- Localize the mismatch to the source helper call that produced the value, not only to the downstream consumer where the masked value is used.
- Emit bounded source variants for call-site-local return-width experiments.
- Validate variants against the requested function and, when configured, sibling functions from the same source file so a local improvement does not hide known regressions.
- Report exhausted local-return-width search distinctly from generic rebucket-only output.

## Non-Goals

- Do not change the real Melee source files as part of this tooling feature.
- Do not automatically recommend broad cross-translation-unit return type changes as source-ready fixes.
- Do not infer arbitrary dataflow across the whole function. The first implementation follows direct call-result shape and direct source-call localization.
- Do not require every generated variant to improve. Failed and non-improving variants are useful evidence when the tool reports them explicitly.

## Detection

The audit will add return-value shape analysis alongside the existing call-prep analysis.

For each expected/current ASM call pair with the same call target and target ordinal, inspect the post-call GPR use chain within a small bounded window. The scan follows `r3` directly and follows one copy from `r3` through `mr dst,r3`. A return-width mismatch is actionable when:

- the call target has a visible narrow integer return type such as `u8`, `s8`, `u16`, or `s16`;
- the source call is localized by target ordinal;
- one side keeps `r3` as a 32-bit value with a move such as `mr dst,r3`;
- the other side narrows `r3` or its one-hop copy with an operation such as `clrlwi dst,r3,24`, `rlwinm dst,src,0,24,31`, `extsb dst,r3`, `extsh dst,r3`, or `clrlwi dst,r3,16`;
- the destination register is later visible in an existing consumer mismatch or in the post-call shape itself.

The report kind will be `helper-return-width-mismatch`. Its action kind will be `call-site-local-return-width`.

The return-shape payload will classify at least these shapes: `plain-move`, `zero-extend-8`, `zero-extend-16`, `sign-extend-8`, `sign-extend-16`, and `unknown`. It will record whether the mask was immediate or through a one-hop copy.

## Source Variants

The action will carry candidate metadata and a source patch plan. Existing single-patch actions remain supported. Return-width actions will use a new `SourceVariant` abstraction with a stable `variant_id`, `label`, ordered patch descriptors, and patch-application diagnostics. Validation will apply ordered patches atomically: if any patch is missing or ambiguous, the variant is skipped and the reason is attached to validation.

The first implementation will generate conservative variants:

- `local-temp-widen-consumer-cast`: widen a simple receiving local from the helper return width to `int` and add explicit narrow casts at direct consumers whose callee prototype already requires a narrow argument.
- `raw-helper-call`: replace an existing widening macro call with the raw helper call, preserving the assignment and all consumers.
- `helper-call-explicit-consumer-cast`: keep the raw helper result in the local variable and add explicit narrow casts at direct consumers that already require narrow values.
- `local-wrapper-shim`: insert a file-local helper shim or macro near existing helper wrappers and replace only the localized call site with that shim.
- `call-local-temporary`: introduce a local temporary around the helper call when the assignment line is simple enough to rewrite safely.

Each variant will include:

- helper name;
- source line;
- original call text;
- replacement call text or patch list;
- confidence;
- decision reason;
- safety status.

Unsafe cases are reported without source patches:

- source localization is overall-ordinal only;
- helper prototype is missing or not a simple narrow integer return;
- the source line has multiple candidate helper calls and cannot be patched unambiguously;
- required insertion anchor is missing;
- source parser cannot identify direct consumers for variants that need consumer casts.
- the receiving lvalue is not a simple local assignment and the variant needs to widen that local type.

## Validation

Validation will compile each generated source variant through the existing temp-object path. The requested function is the primary validation target.

The CLI will also support sibling validation for local return-width variants. The default sibling set is inferred by scanning same-file functions that call the same helper symbols, capped at eight siblings, and by adding the known `mnDiagram2` ranked helper functions when the requested function is in that family. A repeatable `--sibling-function` option will override or extend the inferred list, and the implementation will expose an internal sibling list parameter so tests can provide deterministic sibling functions without depending on repo state.

Sibling validation will compile the candidate source once, install the candidate object under the repo lock once, run `checkdiff --no-build` for the primary function and each sibling, then restore the original object. This avoids recompiling the same candidate per sibling and keeps object restoration scoped to one lock.

Validation status is retained only when:

- the primary target matches or improves versus its baseline score; and
- every sibling target with an available baseline does not regress.

The action validation payload records:

- primary status, baseline score, candidate score, and delta;
- sibling statuses and deltas;
- `retained` boolean;
- `rejection_reason` such as `primary-non-improving`, `sibling-regressed`, `candidate-unscored`, or `compile-failed`.

A variant is retained only when the primary target matches or has a positive score delta and every scored sibling has a delta greater than or equal to zero. Missing sibling baselines are reported but do not count as retained evidence.

## CLI Output

JSON output will include the new finding/action/candidate fields through dataclass serialization.

Text output will print a compact candidate line:

```text
candidate: call-site-local-return-width <helper> (<variant>, <safety-status>)
  validation: primary <status>, siblings <summary>
```

Summary counts will include `local_return_width_candidate_count` and `retained_local_return_width_candidate_count`.

If local return-width candidates are generated but none are retained, the stop condition will be `local-return-width-exhausted`. If candidates exist but validation has not run, the stop condition will be `source-lever-audit`.

## Testing

Regression tests will cover:

- red test showing the current audit reports only rebucketed output for an immediate post-call mask pattern;
- return-width mismatch detection from synthetic ASM where target has `mr dst,r3` and current has `clrlwi dst,r3,24`;
- return-width mismatch detection through one-hop copy/use where the mask is `rlwinm dst,copy,0,24,31`;
- no candidate for overall-ordinal localization;
- no candidate for helper prototypes that are not simple narrow integer returns;
- `SourceVariant` ordered patch application with missing/ambiguous patch diagnostics;
- validation summary where primary improves and a sibling regresses, producing `retained=false`;
- validation compiles a candidate once and scores primary plus siblings from the same temporary object;
- CLI JSON output exposing `call-site-local-return-width`;
- CLI text output printing the candidate and validation summary;
- live smoke on `mnDiagram2_UpdateHeader` showing at least one local-return-width candidate for the helper calls.

## Acceptance Criteria

- `debug suggest signatures -f mnDiagram2_UpdateHeader --source-file src/melee/mn/mndiagram2.c --json` reports `call-site-local-return-width` source candidates for the helper-return mask pattern.
- `debug suggest signatures -f mnDiagram2_Create --source-file src/melee/mn/mndiagram2.c --json` reports local return-width evidence or an explicit local-return-width exhaustion reason instead of only generic rebuckets for the helper-derived value.
- Validation restores build objects after every candidate and records sibling regressions when present.
- Existing signature audit behavior and JSON shape for single-patch prototype/cast candidates remain compatible.
