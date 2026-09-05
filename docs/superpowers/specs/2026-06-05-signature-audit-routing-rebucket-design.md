# Signature Audit Routing And Rebucket Design

## Problem

Issues #429 and #430 are the same handoff failure at two points in the
signature-call-type workflow.

The taxonomy queue still routes `signature-call-type` rows to
`debug suggest casts`, even though issue #428 added the more relevant
`debug suggest signatures` command. Matching agents therefore keep reaching for
the older explicit-cast linter when the row is really about call-prep and
prototype shape.

The new signature auditor also emits useful findings, but its campaign output
can end at generic audit-only actions. In a 60-row sample, it produced 1327
findings and no patch candidates: 1132 `call-target-shape-audit` actions and
195 `call-argument-type-audit` actions. That is not enough for queue agents to
decide whether to patch source, rebucket the function, or stop spending time on
signature tooling.

## Goals

- Route taxonomy `signature-call-type` rows to
  `melee-agent debug suggest signatures`.
- Keep the route advisory. Do not register a harvest harness for signature
  audit rows in this slice.
- Extend `debug suggest signatures --json` with an aggregate summary that
  distinguishes patch candidates, validated patch candidates, unvalidated patch
  candidates, rebucketed audit-only actions, and audit-only actions that still
  lack a rebucket reason.
- Add concrete rebucket metadata to every fallback audit-only action produced
  by the signature auditor.
- Make the stop condition explicit:
  - `validated-patch-candidates` when at least one validation result is
    improving or matched.
  - `unvalidated-patch-candidates` when patch descriptors exist but validation
    has not proved improvement.
  - `rebucketed-audit-only` only when there are findings, no patch candidates,
    and `audit_only_unrebucketed == 0`.
  - `source-lever-audit` when audit actions identify a bounded source lever but
    no automatic patch exists.
  - `audit-only-unclassified` when any audit-only action still lacks both a
    rebucket reason and a bounded source lever.
  - `no-findings` when the auditor found no signature differences.

## Non-Goals

- Do not auto-apply signature audit patches.
- Do not add a registered harvest harness for `debug suggest signatures`.
- Do not solve cross-TU prototype rewriting or whole-project type inference.
- Do not remove `debug suggest casts`; it remains useful for explicit cast
  linting outside taxonomy queue handoff.

## Taxonomy Routing

For `signature-call-type`, `describe_actionability()` returns:

```python
{
    "source_actionability": "current-tools-signature-audit",
    "headline_tool": "debug-suggest-signatures",
    "actionability_reason": (
        "call shape or prototype mismatch; run signature audit to inspect "
        "call-prep, prototypes, argument widths, and concrete rebucket reasons"
    ),
}
```

For the same bucket, `next_command()` returns:

```bash
melee-agent debug suggest signatures -f <function> --source-file src/<file_path> --json
```

When the queue row has no source file path, the command omits
`--source-file` rather than emitting `--source-file src/`.
`harvest.select_harness()` must continue returning `None` for these rows
because no source-emitting harness is registered.

## Signature Action Rebucket Shape

`SignatureAction` gains:

```python
rebucket: dict[str, object] | None = None
```

Rebucket dictionaries use stable string keys so they are easy to consume from
CLI JSON:

```python
{
    "reason": "register-source-cascade",
    "work_bucket": "register-allocator",
    "subcategory": "argument-source-register",
    "explanation": "The ABI register is the same, but the source register differs; signature audit has no bounded source patch.",
}
```

Fallback mappings:

| Finding/action source | Reason | Work bucket | Subcategory |
| --- | --- | --- | --- |
| Call target differs by ordinal | `call-offset-shift` | `structural-reconstruction` | `call-target-shape` |
| Call site cannot be localized to source | `call-not-localized` | `structural-reconstruction` | `call-source-localization` |
| Argument bank differs and no cast/prototype lever is found | `prototype-candidate-missing` | `signature-call-type` | `argument-bank` |
| Argument source register differs | `register-source-cascade` | `register-allocator` | `argument-source-register` |
| Argument width differs and no patch/prototype lever is found | `width-prototype-candidate-missing` | `signature-call-type` | `argument-width` |
| Load kind differs and no field/type lever is found | `type-evidence-missing` | `signature-call-type` | `argument-load-kind` |
| Argument register presence differs and no patch/prototype lever is found | `prototype-candidate-missing` | `signature-call-type` | `argument-presence` |

Same-TU static prototype audit actions are not rebucketed. They are counted as
source-lever audit actions because they identify a bounded manual source lever.

## Summary Shape

`SignatureAuditReport` gains:

```python
summary: dict[str, object] | None = None
```

The summary contains:

```python
{
    "finding_count": 3,
    "action_count": 3,
    "patch_candidate_count": 0,
    "validated_patch_candidate_count": 0,
    "unvalidated_patch_candidate_count": 0,
    "rebucketed_audit_only_count": 3,
    "audit_only_unrebucketed": 0,
    "source_lever_action_count": 0,
    "action_kind_counts": {"call-target-shape-audit": 2},
    "rebucket_reason_counts": {"call-offset-shift": 2},
    "stop_condition": {
        "kind": "rebucketed-audit-only",
        "reason": "all audit-only actions have concrete rebucket reasons",
    },
}
```

Validation updates must recompute summary counts so validated candidates are
visible in `--validate --json` output. An unvalidated patch candidate must not
satisfy the stronger #430 stop condition as a validated source candidate.

Stop-condition precedence is:

1. `no-findings` when `finding_count == 0`.
2. `validated-patch-candidates` when any patch candidate validates as matched
   or improves match percentage.
3. `unvalidated-patch-candidates` when patch candidates exist but none has
   validated improvement.
4. `audit-only-unclassified` when any audit-only action has neither a rebucket
   nor a bounded source-lever kind.
5. `source-lever-audit` when one or more source-lever audit actions exist.
6. `rebucketed-audit-only` when all remaining audit-only actions are
   rebucketed.

## Text Output

Text output remains concise but includes:

- The summary stop condition and counts near the top.
- For each rebucketed action, one line naming `reason`,
  `work_bucket/subcategory`, and the explanation.

## Testing

Add regression tests for:

- Taxonomy actionability and next command route `signature-call-type` to
  `debug suggest signatures`.
- Signature audit rows are advisory: `harvest.select_harness()` returns `None`.
- Call-target shape audit actions carry `call-offset-shift` rebucket metadata.
- Argument-source-register fallback actions carry `register-source-cascade`.
- Width/type fallback actions carry concrete signature rebucket reasons.
- Summary reports `rebucketed-audit-only` only when
  `audit_only_unrebucketed == 0`.
- Patch-producing findings report patch candidate counts separately from
  validated patch candidate counts.
- CLI JSON includes summary and rebucket metadata.
- CLI text prints the stop condition and rebucket reason.

## Independent Review Notes

Hooke reviewed the design before implementation. The accepted changes from that
review are:

- Track validated, unvalidated, and audit-only-unrebucketed counts separately.
- Require `audit_only_unrebucketed == 0` before reporting
  `rebucketed-audit-only`.
- Add an explicit test that signature-audit taxonomy rows do not select a
  registered harvest harness.
