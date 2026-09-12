# Order-distance kill-switch result

**Gating function:** (none)
**Gating fixture (eligibility.json):** None
**Verdict:** FIRED / STOPPED — premise refuted or witness unavailable; STOP. Keep the shipped phys-match objective; route the pool to the permuter arm.

## Assertions
- (a) same anchored target-role set: False
- (b) strict descent win < pre_win: False
- (c) recorded named pair flips in intended direction: False
- (d) negative control does not descend: False

**Failure reason:** HARD STOP: no derivation-eligible witness (eligibility.json gating_fixture is null) — ORCHESTRATOR ACTION REQUIRED: revisit the kill-switch function assignment (§6c contingency exhausted)

## Detail

    {
      "eligibility": {
        "gating_fixture": null,
        "witnesses": {
          "mnDiagram_802427B4": {
            "routing": "not_order_class",
            "class_evidence": "mnDiagram_802427B4: checkdiff primary is 'signature-type-mismatch', not register-only (['backend-ceiling', 'normalized-structural-match', 'operand-register-or-offset']); not in the order-distance pool",
            "base_match_percent": 95.68,
            "negative_control_edit": "swap: '    HSD_Text* text;\\n    HSD_Text* row_text;' -> '    HSD_Text* row_text;\\n    HSD_Text* text;'",
            "negative_control_match_percent": 95.54667,
            "not_eligible_reason": "checkdiff_primary_not_register_only"
          },
          "fn_803ACD58": {
            "routing": "not_order_class",
            "class_evidence": "forced-ORDER build did not byte-eliminate the class residual; order is a symptom of instruction-content/emission divergence upstream of select (e.g. coalescing/VN/liveness/statement-copy skew)",
            "base_match_percent": 98.94068,
            "negative_control_edit": "swap: '    s32 icon_size;\\n    s32 hdr_plus_icon;' -> '    s32 hdr_plus_icon;\\n    s32 icon_size;'",
            "negative_control_match_percent": 98.644066
          }
        },
        "notes": "gating: mnDiagram_802427B4 whenever it derives directed (an empty named_pair then FIRES at T7 \u2014 the win invisible to role-stable order distance is a refutation, never dodged); fn_803ACD58 (pure decl-order chain) is promoted ONLY when the primary base is not derivation-eligible (\u00a76c contingency). null gating_fixture => NO derivation-eligible witness: the kill switch hard-stops and the orchestrator must revisit the kill-switch function assignment."
      }
    }
