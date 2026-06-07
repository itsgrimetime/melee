# PAD_STACK Natural-Source Attribution Design

## Problem

Issue #484 reports that frame attribution can validate a diagnostic
`PAD_STACK(N)` reservation while leaving agents with no PR-ready source lever.
The current `frame-transform-search` payload ranks the PAD_STACK candidate, but
does not state whether the result represents a natural C source transform, a
partial natural-source lead, or a diagnostic-only/no-source-lever outcome.

This ambiguity causes matching agents to treat a diagnostic frame reservation as
though it might still be a source replacement, even when the bounded source
operators have already produced no natural source candidate.

## Chosen Approach

Extend `evaluate_frame_transform_probe_results()` with a
`natural_source_attribution` object. This keeps the feature inside the existing
frame-transform evaluation path, so all callers that already consume
`frame_transform_probe_evaluation` get the new verdict without running another
search.

The attribution classifies the measured probe set into one of these statuses:

- `validated-natural-source`: a non-PAD_STACK frame-transform operator reaches
  the target frame size.
- `partial-natural-source`: a non-PAD_STACK operator reduces the frame delta but
  does not fully fix it.
- `diagnostic-pad-stack-only`: the best measured improvement comes only from
  `frame-reservation-pad-stack`.
- `no-source-lever`: no measured natural-source operator improves the frame, or
  no safe semantic lever can be generated.
- `inconclusive`: probe evidence is missing, failed, or not frame-size-capable.

The object names the best diagnostic candidate, best natural candidate when one
exists, measured operator counts, and an explicit `missing_reason`. The missing
reason is stable enough for harvest/rebucket logic and human agents to quote.
When the only frame improvement is `frame-reservation-pad-stack`, the top-level
evaluation verdict becomes `diagnostic-pad-stack-frame-transform` instead of
`source-reachable-frame-transform`; existing callers can no longer mistake a
diagnostic reservation for a validated natural source replacement.

Natural-source operators are allowlisted to existing frame-size source levers:
`frame-local-dematerialize`, `frame-direct-literal-at-final-fp-call`,
`frame-split-fp-const-lifetime`, and `frame-magic-scratch-relocation`.
`frame-reservation-pad-stack` is always diagnostic. Operators outside the
frame-size allowlist do not count as natural-source origins.

## Alternatives Considered

1. Add a new PAD_STACK origin search command.

   This would duplicate the existing frame-transform scorer and require agents
   to run a second command after every PAD_STACK hit. It is too much machinery
   for the immediate issue.

2. Fold the verdict into the existing stop condition only.

   Stop conditions already describe frame-size success or bounded ceiling
   candidates, but they do not preserve enough structured detail to distinguish
   a diagnostic-only PAD_STACK from a natural source lever.

3. Add structured natural-source attribution to the existing evaluation.

   This is the selected approach. It is small, backward-compatible, and gives
   both CLI users and harvest rows the missing source-actionable verdict.

## Payload Shape

`frame_transform_probe_evaluation` gains:

```json
{
  "natural_source_attribution": {
    "status": "diagnostic-pad-stack-only",
    "verdict": "diagnostic-only",
    "missing_reason": "best frame improvement is PAD_STACK diagnostic; no validated non-PAD_STACK source transform improved the frame; unresolved source attribution: No resolved symbolic stack homes were available",
    "best_diagnostic_variant": {"label": "frame-reservation-pad-stack-16", "operator": "frame-reservation-pad-stack"},
    "best_natural_variant": null,
    "measured_natural_operator_count": 2,
    "measured_diagnostic_operator_count": 1
  }
}
```

The top-level `stop_condition` remains compatible for validated natural-source
results. Diagnostic PAD_STACK-only wins use `kind:
diagnostic-pad-stack-only`, and no-safe-semantic-lever results include a
`natural_source_attribution` copy so CLI users do not have to inspect another
branch of the payload.

## Tests

Focused tests cover:

- A non-PAD_STACK source transform that fixes the frame reports
  `validated-natural-source`.
- A non-PAD_STACK source transform that partially improves the frame reports
  `partial-natural-source`.
- A PAD_STACK-only improvement reports `diagnostic-pad-stack-only` with a
  concrete missing reason copied from frame divergence/source attribution when
  that context is available.
- A no-safe-semantic-lever result reports `no-source-lever`.
- Existing frame-transform ceiling and source-reachable tests continue to pass.

## Out Of Scope

This design does not invent a new natural C construct for each PAD_STACK target.
It makes the bounded-search result explicit: validated natural-source lever,
partial natural-source lead, diagnostic-only PAD_STACK, or no-source-lever with
a reason.
