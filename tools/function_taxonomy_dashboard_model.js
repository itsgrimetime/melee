"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.FunctionTaxonomyDashboardModel = api;
})(typeof globalThis === "undefined" ? this : globalThis, function () {
  const fallbackColor = "#647076";
  const primaryInterventionOrder = [
    "signature-audit",
    "inline-boundary-reconstruction",
    "control-flow-reconstruction",
    "opcode-sequence-reconstruction",
    "manual-attribution",
    "normalized-residual-attribution",
    "backend-ceiling-review",
    "bss-anchor-analysis",
    "data-symbol-modeling",
    "stack-lifetime-layout",
    "stack-frame-reconstruction",
    "indexed-pointer-rewrite",
    "struct-layout-inference",
    "small-pattern-research",
    "register-allocation-proof"
  ];
  const secondarySignalOrder = [
    "normalized-structural-match",
    "near-zero-structural-residual",
    "opcode-delta-signature",
    "branch-idiom",
    "call-hoist",
    "pointer-walk-indexed-shape",
    "concurrent-buffer-lifetime",
    "loop-peel-unroll",
    "missing-extra-call-layer",
    "indexed-pointer-materialization",
    "stack-slot-displacement",
    "equal-size-stack-layout",
    "frame-size-delta",
    "operand-displacement",
    "relocation-only-residual",
    "bss-section-anchor",
    "register-only-delta",
    "callee-save-register-rotation",
    "volatile-register-selection",
    "backend-register-window-rotation",
    "inline-boundary-artifact",
    "struct-field-verified",
    "unresolved-struct-field"
  ];
  const evidenceStageOrder = [
    "heuristic", "observed", "attributed", "materializable",
    "evaluated", "validated", "blocked", "ceiling"
  ];
  const blockerFamilyOrder = [
    "source-unavailable",
    "build-artifact-unavailable",
    "source-attribution",
    "source-anchor",
    "unsafe-source-transform",
    "no-source-candidate",
    "struct-inference",
    "relocation-support",
    "relocation-ambiguity",
    "relocation-validation",
    "linker-order-dependence",
    "allocator-proof",
    "residual-attribution",
    "tooling-failure",
    "no-safe-source-lever",
    "source-insensitive-ceiling"
  ];
  const semanticDeltaFamilyOrder = [
    "address-constant-materialization",
    "integer-width-bitfield-scale",
    "floating-point-expression-storage",
    "branch-predicate-control",
    "indexed-update-memory",
    "frame-save-window",
    "integer-memory-width-transfer",
    "other-opcode-sequence"
  ];
  const opcodeEditDirectionOrder = [
    "current-extra", "reference-extra", "substitution", "mixed",
    "operand-shape-only"
  ];
  const normalizedTriggerSizeOrder = ["one-line", "two-line", "three-line"];
  const normalizedTriggerFamilyOrder = normalizedTriggerSizeOrder.flatMap(
    (size) => opcodeEditDirectionOrder.map((direction) => `${size}-${direction}`)
  );
  const semanticDeltaFields = [
    "semantic_delta_families",
    "opcode_edit_direction",
    "normalized_trigger_signature_status",
    "normalized_trigger_signature",
    "normalized_trigger_family",
    "normalized_trigger_cluster_size"
  ];
  const rootCauseFields = ["root_cause_keys", "max_root_cause_impact"];
  const semanticDeltaFamilyLabels = {
    "address-constant-materialization": "Address / Constant Materialization",
    "integer-width-bitfield-scale": "Integer Width / Bitfield / Scale",
    "floating-point-expression-storage": "Floating-Point Expression / Storage",
    "branch-predicate-control": "Branch / Predicate / Control",
    "indexed-update-memory": "Indexed / Update Memory",
    "frame-save-window": "Frame / Save Window",
    "integer-memory-width-transfer": "Integer Memory Width / Transfer",
    "other-opcode-sequence": "Other Opcode Sequence"
  };
  const opcodeEditDirectionLabels = {
    "current-extra": "Current Extra",
    "reference-extra": "Reference Extra",
    substitution: "Substitution",
    mixed: "Mixed",
    "operand-shape-only": "Operand Shape Only"
  };

  function facetInfo(labels, description, focus) {
    return Object.fromEntries(Object.entries(labels).map(([value, label]) => [
      value, {label, description: description.replace("{label}", label.toLowerCase()), focus}
    ]));
  }

  const semanticDeltaFamilyInfo = facetInfo(
    semanticDeltaFamilyLabels,
    "Structured opcode presence places this residual in the {label} delta family.",
    "Use this as a likely focus for investigation, not as a proven source cause."
  );
  const opcodeEditDirectionInfo = facetInfo(
    opcodeEditDirectionLabels,
    "The aligned opcode delta has {label} edit direction.",
    "Use the direction to narrow the likely focus while preserving the ordered evidence."
  );
  const normalizedTriggerFamilyInfo = Object.fromEntries(
    normalizedTriggerFamilyOrder.map((family) => [family, {
      label: family.split("-").filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" "),
      description: "A one-to-three-line normalized residual has this line-count and opcode edit-direction trigger family.",
      focus: "Compare rows in this trigger family as a likely focus; inspect the exact safe signature before choosing a source experiment."
    }])
  );
  const controlFlowBlockerFamilies = {
    "source-unavailable": "source-unavailable",
    "call-anchor-not-found": "source-anchor",
    "u8-index-table-anchor-not-found": "source-anchor",
    "simple-counted-loop-not-found": "source-anchor",
    "source-owner-region-not-found": "source-anchor",
    "unsafe-index-expression": "unsafe-source-transform",
    "unsafe-non-u8-base": "unsafe-source-transform",
    "write-target": "unsafe-source-transform",
    "inline-control-flow-statement": "unsafe-source-transform",
    "loop-body-control-flow": "unsafe-source-transform",
    "true-hoist-not-source-preserving": "unsafe-source-transform",
    "nonconstant-byte-offset": "unsafe-source-transform",
    "no-control-flow-shape-probes": "no-source-candidate",
    "source-preflight-error": "tooling-failure",
    "analysis-error": "tooling-failure"
  };
  const nameMagicBlockerFamilies = {
    "no-name-magic-candidate": "no-source-candidate",
    "target-object-missing": "build-artifact-unavailable",
    "current-object-missing": "build-artifact-unavailable",
    "unsupported-source-site": "relocation-support",
    "unsupported-reloc-kind": "relocation-support",
    "unsupported-section-anchor-offset": "relocation-support",
    "declaration-apply-unsupported": "relocation-support",
    "ambiguous-relocation-pair": "relocation-ambiguity",
    "ambiguous-sdata2-value": "relocation-ambiguity",
    "no-name-magic-validation-failed": "relocation-validation",
    "section-anchor-source-fixable-residual": "relocation-validation",
    "sdata2-pool-order-dependent": "linker-order-dependence"
  };

  function strings(values) {
    return Array.from(new Set((values || []).filter(Boolean).map(String)));
  }

  function ordered(preferred, observed) {
    const known = strings(preferred);
    const knownSet = new Set(known);
    const extras = strings(observed)
      .filter((value) => !knownSet.has(value))
      .sort((a, b) => a.localeCompare(b));
    return known.concat(extras);
  }

  function fallbackInfo(kind, value, includeColor) {
    const info = {
      label: value.split("-").filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" "),
      description: `No curated ${kind} description is available for this observed value.`,
      focus: "Use the row evidence and next command; add curated metadata if this value becomes stable."
    };
    if (includeColor) info.color = fallbackColor;
    return info;
  }

  function withFallbacks(info, values, kind, includeColor) {
    const result = Object.create(null);
    for (const [key, value] of Object.entries(info || {})) {
      result[key] = value;
    }
    for (const value of values) {
      if (!Object.prototype.hasOwnProperty.call(result, value)) {
        result[value] = fallbackInfo(kind, value, includeColor);
      }
    }
    return result;
  }

  function observed(records, key) {
    return (records || []).map((row) => row && row[key]).filter(Boolean);
  }

  function observedMany(records, key) {
    return (records || []).flatMap((row) => (
      row && Array.isArray(row[key]) ? row[key] : []
    )).filter((value) => typeof value === "string" && value.trim())
      .map((value) => value.trim());
  }

  function mapping(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function nonEmpty(value) {
    if (Array.isArray(value)) return value.length > 0;
    if (value && typeof value === "object") return Object.keys(value).length > 0;
    if (typeof value === "string") return Boolean(value.trim());
    return Boolean(value);
  }

  function positiveInteger(value) {
    return Number.isInteger(value) && value > 0;
  }

  function orderedStringList(values, preferred) {
    if (!Array.isArray(values)) return [];
    const cleaned = Array.from(new Set(values
      .filter((value) => typeof value === "string" && value.trim())
      .map((value) => value.trim())));
    const cleanedSet = new Set(cleaned);
    return preferred.filter((value) => cleanedSet.has(value)).concat(
      cleaned.filter((value) => !preferred.includes(value))
        .sort((a, b) => a.localeCompare(b))
    );
  }

  function derivePrimaryIntervention(row) {
    const bucket = row.work_bucket;
    const subcategory = row.subcategory;
    if (bucket === "signature-call-type") return "signature-audit";
    if (bucket === "inline-boundary") return "inline-boundary-reconstruction";
    if (bucket === "structural-reconstruction") {
      if (subcategory === "branch-or-control-flow-shape") {
        return "control-flow-reconstruction";
      }
      if (subcategory === "opcode-sequence-diff") {
        return "opcode-sequence-reconstruction";
      }
      return "manual-attribution";
    }
    if (bucket === "normalized-structural-near-match") {
      return "normalized-residual-attribution";
    }
    if (bucket === "backend-ceiling") return "backend-ceiling-review";
    if (bucket === "data-symbol-relocation") {
      return subcategory === "bss-section-anchor-ceiling"
        ? "bss-anchor-analysis" : "data-symbol-modeling";
    }
    if (bucket === "stack-local-layout") {
      return [
        "same-frame-stack-slot-placement",
        "unattributed-lifetime-or-ordering-shift"
      ].includes(subcategory) ? "stack-lifetime-layout" : "stack-frame-reconstruction";
    }
    if (bucket === "indexed-struct-pointer") return "indexed-pointer-rewrite";
    if (bucket === "struct-offset-discrepancy") return "struct-layout-inference";
    if (bucket === "known-small-pattern-candidate") return "small-pattern-research";
    if (bucket === "register-allocator") return "register-allocation-proof";
    return "manual-attribution";
  }

  function stackSizes(row) {
    if (row.expected_frame_size !== undefined || row.current_frame_size !== undefined) {
      return [row.expected_frame_size, row.current_frame_size];
    }
    const classification = mapping(row.classification);
    for (const key of ["stack_frame_delta", "stack_frame_sizes"]) {
      const sizes = mapping(classification[key]);
      if (Object.keys(sizes).length) {
        return [sizes.expected_frame_size, sizes.current_frame_size];
      }
    }
    return [null, null];
  }

  function deriveSecondarySignals(row) {
    const classification = mapping(row.classification);
    const signals = [];
    const gateStatus = mapping(classification.structural_truth_gate).status;
    if (gateStatus === "structural-match") signals.push("normalized-structural-match");
    else if (gateStatus === "near-zero-structural-diff") {
      signals.push("near-zero-structural-residual");
    }
    if (row.opcode_delta_signature_status === "available"
        && typeof row.opcode_delta_signature === "string"
        && row.opcode_delta_signature.trim()) {
      signals.push("opcode-delta-signature");
    }
    if (Array.isArray(row.control_flow_shape_hint_kinds)) {
      signals.push(...row.control_flow_shape_hint_kinds.filter(
        (value) => typeof value === "string" && secondarySignalOrder.includes(value)
      ));
    }
    if (nonEmpty(classification.indexed_struct_pointer_materialization)) {
      signals.push("indexed-pointer-materialization");
    }
    if (nonEmpty(classification.stack_slot_localizer)) signals.push("stack-slot-displacement");
    if (row.work_bucket === "stack-local-layout") {
      const [expected, current] = stackSizes(row);
      if (Number.isInteger(expected) && Number.isInteger(current)) {
        signals.push(expected === current ? "equal-size-stack-layout" : "frame-size-delta");
      }
    }
    if (nonEmpty(classification.offset_discrepancies)) signals.push("operand-displacement");
    if (row.subcategory === "normalized-structural-relocation-only") {
      signals.push("relocation-only-residual");
    }
    if (nonEmpty(mapping(classification.bss_anchor_relocations).pairs)) {
      signals.push("bss-section-anchor");
    }
    const guidance = mapping(classification.register_allocation_guidance);
    if (positiveInteger(guidance.register_only_count)) signals.push("register-only-delta");
    if (nonEmpty(guidance.callee_swap_pairs)) signals.push("callee-save-register-rotation");
    if (nonEmpty(guidance.volatile_target_registers)
        || nonEmpty(guidance.volatile_current_registers)) {
      signals.push("volatile-register-selection");
    }
    const backend = mapping(classification.backend_ceiling);
    if (backend.subclass === "register-window-rotation"
        || nonEmpty(classification.register_window_rotation)) {
      signals.push("backend-register-window-rotation");
    }
    if (nonEmpty(classification.inline_boundary_artifact)) {
      signals.push("inline-boundary-artifact");
    }
    if (row.struct_verify_status === "verified") signals.push("struct-field-verified");
    else if (row.struct_verify_status === "unverified") signals.push("unresolved-struct-field");
    return signals;
  }

  function deriveEvidenceStage(row, intervention) {
    if (["stack-lifetime-layout", "stack-frame-reconstruction"].includes(intervention)) {
      if (row.frame_probe_status === "validated-improving") return "validated";
      if (row.frame_probe_status === "materializable") return "materializable";
      if (row.frame_probe_status === "probe-inconclusive") return "evaluated";
      if (["terminal-no-safe-lever", "ceiling"].includes(row.frame_probe_status)) {
        return "ceiling";
      }
      if (row.frame_evidence === "tool-evaluated") return "evaluated";
      if (row.frame_evidence === "pcdump-attributed") return "attributed";
      if (row.frame_evidence === "checkdiff-only") return "observed";
      return "heuristic";
    }
    if (intervention === "control-flow-reconstruction") {
      if (["validated", "validated-improving"].includes(
        row.control_flow_shape_validation_status
      ) && positiveInteger(row.control_flow_shape_validated_probe_count)) {
        return "validated";
      }
      if (row.control_flow_shape_source_preflight_status === "materializable"
          && positiveInteger(row.control_flow_shape_generated_probe_count)) {
        return "materializable";
      }
      if (["terminal", "source-unavailable", "preflight-error"].includes(
        row.control_flow_shape_source_preflight_status
      )) return "blocked";
      return "heuristic";
    }
    if (["data-symbol-modeling", "bss-anchor-analysis"].includes(intervention)) {
      if (positiveInteger(row.name_magic_probe_count) && [
        "validated", "validated-improving", "source-reachable-validated",
        "partial-source-reachable-validated"
      ].includes(row.name_magic_stop_kind)) return "validated";
      if (positiveInteger(row.name_magic_probe_count)) return "materializable";
      if (nonEmpty(row.name_magic_blocker)) return "blocked";
      return intervention === "bss-anchor-analysis" ? "ceiling" : "observed";
    }
    if (intervention === "struct-layout-inference") {
      if (row.struct_verify_status === "verified") return "attributed";
      if (["unverified", "unavailable"].includes(row.struct_verify_status)) return "blocked";
      return "observed";
    }
    if (intervention === "backend-ceiling-review") return "ceiling";
    if ([
      "register-allocation-proof", "normalized-residual-attribution",
      "indexed-pointer-rewrite", "signature-audit", "inline-boundary-reconstruction",
      "opcode-sequence-reconstruction", "small-pattern-research"
    ].includes(intervention)) return "observed";
    return "heuristic";
  }

  function deriveBlockerFamilies(row, intervention, stage) {
    const blockers = [];
    if (Array.isArray(row.control_flow_shape_blockers)) {
      blockers.push(...row.control_flow_shape_blockers
        .filter((value) => typeof value === "string"
          && Object.prototype.hasOwnProperty.call(controlFlowBlockerFamilies, value))
        .map((value) => controlFlowBlockerFamilies[value]));
    }
    if (row.control_flow_shape_source_preflight_status === "source-unavailable") {
      blockers.push("source-unavailable");
    } else if (row.control_flow_shape_source_preflight_status === "preflight-error") {
      blockers.push("tooling-failure");
    }
    const raw = row.name_magic_blocker;
    if (typeof raw === "string") {
      if (intervention === "struct-layout-inference"
          && raw === "raw-diff-no-supported-data-symbol-pair") {
        blockers.push("struct-inference");
      } else if (["data-symbol-modeling", "bss-anchor-analysis"].includes(intervention)
          && raw === "raw-diff-no-supported-data-symbol-pair") {
        blockers.push("relocation-support");
      } else if (Object.prototype.hasOwnProperty.call(nameMagicBlockerFamilies, raw)) {
        blockers.push(nameMagicBlockerFamilies[raw]);
      } else if (raw === "bss-anchor-ceiling" && stage === "ceiling") {
        blockers.push("source-insensitive-ceiling");
      }
    }
    if (intervention === "struct-layout-inference"
        && ["unverified", "unavailable"].includes(row.struct_verify_status)) {
      blockers.push("struct-inference");
    }
    if (["stack-lifetime-layout", "stack-frame-reconstruction"].includes(intervention)) {
      if (row.frame_probe_status === "needs-attribution") blockers.push("source-attribution");
      else if (row.frame_probe_status === "terminal-no-safe-lever") {
        blockers.push("no-safe-source-lever");
      } else if (row.frame_probe_status === "ceiling") {
        blockers.push("source-insensitive-ceiling");
      }
    }
    if (intervention === "register-allocation-proof" && stage !== "validated") {
      blockers.push("allocator-proof");
    }
    if (intervention === "normalized-residual-attribution") {
      blockers.push("residual-attribution");
    }
    if (intervention === "backend-ceiling-review") {
      blockers.push("source-insensitive-ceiling");
    }
    if (intervention === "bss-anchor-analysis" && stage === "ceiling") {
      blockers.push("source-insensitive-ceiling");
    }
    return blockers;
  }

  function normalizeRoutingRecord(input, { preserveExisting = true } = {}) {
    const row = Object.assign({}, input || {});
    let intervention = preserveExisting ? row.primary_intervention : null;
    if (typeof intervention !== "string" || !intervention.trim()) {
      intervention = derivePrimaryIntervention(row);
    } else intervention = intervention.trim();
    row.primary_intervention = intervention;

    const suppliedSignals = preserveExisting ? row.secondary_signals : null;
    row.secondary_signals = orderedStringList(
      Array.isArray(suppliedSignals) ? suppliedSignals : deriveSecondarySignals(row),
      secondarySignalOrder
    );

    let stage = preserveExisting ? row.evidence_stage : null;
    if (typeof stage !== "string" || !stage.trim()) {
      stage = deriveEvidenceStage(row, intervention);
    } else stage = stage.trim();
    row.evidence_stage = stage;

    const suppliedBlockers = preserveExisting ? row.blocker_families : null;
    row.blocker_families = orderedStringList(
      Array.isArray(suppliedBlockers)
        ? suppliedBlockers : deriveBlockerFamilies(row, intervention, stage),
      blockerFamilyOrder
    );
    return row;
  }

  function normalizeSemanticDeltaRecord(input) {
    const row = Object.assign({}, input || {});
    if (!semanticDeltaFields.some((key) => Object.hasOwn(row, key))) return row;
    if (Object.hasOwn(row, "semantic_delta_families")) {
      row.semantic_delta_families = orderedStringList(
        row.semantic_delta_families,
        semanticDeltaFamilyOrder
      );
    }
    [
      "opcode_edit_direction",
      "normalized_trigger_signature_status",
      "normalized_trigger_signature",
      "normalized_trigger_family"
    ].forEach((key) => {
      if (Object.hasOwn(row, key)) {
        row[key] = typeof row[key] === "string" ? row[key].trim() : "";
      }
    });
    if (Object.hasOwn(row, "normalized_trigger_cluster_size")) {
      row.normalized_trigger_cluster_size = positiveInteger(
        row.normalized_trigger_cluster_size
      ) ? row.normalized_trigger_cluster_size : 0;
    }
    return row;
  }

  function normalizeRootCauseRecord(input) {
    const row = Object.assign({}, input || {});
    if (!rootCauseFields.some((key) => Object.hasOwn(row, key))) return row;
    if (Object.hasOwn(row, "root_cause_keys")) {
      const values = Array.isArray(row.root_cause_keys) ? row.root_cause_keys : [];
      const seen = new Set();
      row.root_cause_keys = [];
      values.forEach((value) => {
        if (typeof value !== "string" || !value.trim()) return;
        const cleaned = value.trim();
        if (!seen.has(cleaned)) {
          seen.add(cleaned);
          row.root_cause_keys.push(cleaned);
        }
      });
    }
    if (Object.hasOwn(row, "max_root_cause_impact")) {
      row.max_root_cause_impact = positiveInteger(row.max_root_cause_impact)
        ? row.max_root_cause_impact : 0;
    }
    return row;
  }

  function sanitizeDeprecatedFrameKeys(value) {
    if (Array.isArray(value)) return value.map(sanitizeDeprecatedFrameKeys);
    if (!value || typeof value !== "object") return value;
    const sanitized = {};
    for (const [key, nested] of Object.entries(value)) {
      if (["closability_tier", "frame_closability_tier"].includes(key)) continue;
      sanitized[key] = sanitizeDeprecatedFrameKeys(nested);
    }
    return sanitized;
  }

  function recognizedFrameMutationCommand(value) {
    const command = String(value || "");
    return [
      "melee-agent debug mutate frame-transform-search",
      "melee-agent debug mutate lifetime-layout"
    ].some((token) => command.includes(token));
  }

  function hasBoundedFrameProbe(row) {
    if ([row.next_command, row.frame_next_command].some(recognizedFrameMutationCommand)) {
      return true;
    }
    return [row.frame_probe_plan, row.frame_transform_probe_plan, row.probe_plan]
      .some((plan) => plan && typeof plan === "object" && plan.status === "ready"
        && Array.isArray(plan.suggested_commands)
        && plan.suggested_commands.some((item) => item && typeof item === "object"
          && recognizedFrameMutationCommand(item.command)));
  }

  function legacyFrameActionability(status, cause) {
    if (["materializable", "validated-improving"].includes(status)) {
      return {
        source_actionability: "current-tools",
        headline_tool: cause === "stack-object-offset-shift"
          ? "lifetime-layout" : "frame-transform-search",
        actionability_reason: status === "validated-improving"
          ? "compiled frame probe improved the frame objective"
          : "bounded frame evidence identifies a source probe ready to compile"
      };
    }
    if (status === "probe-inconclusive") {
      return {
        source_actionability: "diagnostic-only",
        headline_tool: "frame-reservations",
        actionability_reason: "bounded frame probe evaluation was inconclusive"
      };
    }
    if (["terminal-no-safe-lever", "ceiling"].includes(status)) {
      return {
        source_actionability: "ceiling",
        headline_tool: "frame-reservations",
        actionability_reason: "bounded frame evidence reached a terminal state"
      };
    }
    return {
      source_actionability: "diagnostic-only",
      headline_tool: "frame-reservations",
      actionability_reason: "pcdump attribution must precede source-probe selection"
    };
  }

  function normalizeFrameRecord(input) {
    const legacyAlias = Boolean(input && input.frame_closability_tier);
    const row = sanitizeDeprecatedFrameKeys(input || {});
    const frameKeys = [
      "frame_cause", "frame_verdict", "frame_raw_verdict",
      "frame_attribution_status", "frame_evidence", "frame_probe_status",
      "frame_closability_tier"
    ];
    if (!legacyAlias && !frameKeys.some((key) => row[key])) {
      delete row.frame_closability_tier;
      return row;
    }
    const legacy = legacyAlias
      || !["frame_evidence", "frame_probe_status", "frame_match_relevance"]
        .every((key) => row[key]);
    const cause = String(row.frame_cause || "");
    const verdict = String(row.frame_raw_verdict || row.frame_verdict || "");
    const attribution = String(row.frame_attribution_status || "");
    let evidence = String(row.frame_evidence || "");
    let status = String(row.frame_probe_status || "");
    let relevance = String(row.frame_match_relevance || "");
    if (!evidence) {
      if (!verdict && !attribution) {
        evidence = "checkdiff-only";
      } else if (verdict === "checkdiff-only" || attribution === "checkdiff-only") {
        evidence = "checkdiff-only";
      } else if ([
        "source-reachable-validated", "partial-source-reachable-validated",
        "attributed-frame-unchanged", "internal-tiebreak-ceiling"
      ].includes(verdict)) {
        evidence = "probe-validated";
      } else {
        evidence = "pcdump-attributed";
      }
    }
    if (!status) {
      if (evidence === "checkdiff-only") status = "needs-attribution";
      else if (["source-reachable-validated", "partial-source-reachable-validated"].includes(verdict)) {
        status = "validated-improving";
      } else if (["attributed-frame-unchanged", "internal-tiebreak-ceiling"].includes(verdict)) {
        status = "ceiling";
      } else if (verdict === "source-reachable-candidate"
        && hasBoundedFrameProbe(row)) {
        status = "materializable";
      } else status = "needs-attribution";
    }
    if (!relevance) {
      relevance = cause === "stack-object-offset-shift" ? "match-neutral" : "unknown";
    }
    row.frame_evidence = evidence;
    row.frame_probe_status = status;
    row.frame_match_relevance = relevance;
    delete row.frame_closability_tier;
    if (legacy) {
      Object.assign(row, legacyFrameActionability(status, cause));
    }
    return row;
  }

  function normalizeRecords(records) {
    return (records || []).map((row) => normalizeRootCauseRecord(
      normalizeSemanticDeltaRecord(normalizeRoutingRecord(normalizeFrameRecord(row)))
    ));
  }

  function routingSearchText(row) {
    if (!row || typeof row !== "object") return "";
    return [row.primary_intervention, row.evidence_stage,
      ...diagnosticStrings(row.secondary_signals),
      ...diagnosticStrings(row.blocker_families)]
      .filter((value) => typeof value === "string" && value).join(" ");
  }

  function matchesRoutingFilters(row, filters) {
    const selected = filters || {};
    return (!selected.intervention || row.primary_intervention === selected.intervention)
      && (!selected.evidenceStage || row.evidence_stage === selected.evidenceStage)
      && (!selected.secondarySignal
        || diagnosticStrings(row.secondary_signals).includes(selected.secondarySignal))
      && (!selected.blockerFamily
        || diagnosticStrings(row.blocker_families).includes(selected.blockerFamily));
  }

  function routingDetail(row) {
    if (!row || typeof row !== "object") return null;
    return {
      primaryIntervention: typeof row.primary_intervention === "string"
        ? row.primary_intervention : "",
      evidenceStage: typeof row.evidence_stage === "string" ? row.evidence_stage : "",
      secondarySignals: diagnosticStrings(row.secondary_signals).slice(),
      blockerFamilies: diagnosticStrings(row.blocker_families).slice(),
      rawActionability: typeof row.source_actionability === "string"
        ? row.source_actionability : ""
    };
  }

  function semanticDeltaSearchText(row) {
    if (!row || typeof row !== "object") return "";
    return [
      ...diagnosticStrings(row.semantic_delta_families),
      row.opcode_edit_direction,
      row.normalized_trigger_signature_status,
      row.normalized_trigger_signature,
      row.normalized_trigger_family,
      Number.isInteger(row.normalized_trigger_cluster_size)
        ? String(row.normalized_trigger_cluster_size) : ""
    ].filter((value) => typeof value === "string" && value).join(" ");
  }

  function matchesSemanticDeltaFilters(row, filters) {
    const selected = filters || {};
    return (!selected.family
        || diagnosticStrings(row.semantic_delta_families).includes(selected.family))
      && (!selected.direction || row.opcode_edit_direction === selected.direction)
      && (!selected.triggerFamily
        || row.normalized_trigger_family === selected.triggerFamily);
  }

  function normalizedTriggerSignatureDetail(row) {
    if (!row || typeof row !== "object"
        || row.normalized_trigger_signature_status !== "available"
        || typeof row.normalized_trigger_signature !== "string"
        || !row.normalized_trigger_signature) return null;
    let parsed;
    try {
      parsed = JSON.parse(row.normalized_trigger_signature);
    } catch {
      return null;
    }
    const validOpcode = (value) => value === null
      || (typeof value === "string" && Boolean(value));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)
        || parsed.version !== 1
        || !Number.isInteger(parsed.normalized_diff_lines)
        || ![1, 2, 3].includes(parsed.normalized_diff_lines)
        || typeof parsed.edit_direction !== "string"
        || !parsed.edit_direction
        || parsed.edit_direction !== row.opcode_edit_direction
        || !Array.isArray(parsed.pairs)
        || !parsed.pairs.every((pair) => Array.isArray(pair) && pair.length === 2
          && pair.every(validOpcode))) return null;
    if ((parsed.edit_direction === "operand-shape-only" && parsed.pairs.length !== 0)
        || (parsed.edit_direction !== "operand-shape-only" && parsed.pairs.length === 0)) {
      return null;
    }
    return {
      version: 1,
      normalizedDiffLines: parsed.normalized_diff_lines,
      editDirection: parsed.edit_direction,
      pairs: parsed.pairs.map((pair) => pair.slice())
    };
  }

  function semanticDeltaDetail(row) {
    if (!row || typeof row !== "object"
        || !semanticDeltaFields.some((key) => Object.hasOwn(row, key))) return null;
    return {
      families: diagnosticStrings(row.semantic_delta_families).slice(),
      editDirection: typeof row.opcode_edit_direction === "string"
        ? row.opcode_edit_direction : "",
      triggerFamily: typeof row.normalized_trigger_family === "string"
        ? row.normalized_trigger_family : "",
      triggerClusterSize: positiveInteger(row.normalized_trigger_cluster_size)
        ? row.normalized_trigger_cluster_size : 0,
      triggerSignature: normalizedTriggerSignatureDetail(row)
    };
  }

  function rootCauseSearchText(row) {
    if (!row || typeof row !== "object") return "";
    return [
      ...diagnosticStrings(row.root_cause_keys),
      Number.isInteger(row.max_root_cause_impact)
        ? String(row.max_root_cause_impact) : ""
    ].filter(Boolean).join(" ");
  }

  function matchesRootCauseFilters(row, filters) {
    const selected = filters || {};
    return !selected.key
      || diagnosticStrings(row.root_cause_keys).includes(selected.key);
  }

  function rootCauseDetail(row) {
    if (!row || typeof row !== "object"
        || !rootCauseFields.some((key) => Object.hasOwn(row, key))) return null;
    return {
      keys: diagnosticStrings(row.root_cause_keys).slice(),
      maxImpact: positiveInteger(row.max_root_cause_impact)
        ? row.max_root_cause_impact : 0
    };
  }

  function rootCauseMembershipDetail(row, visibleRecords, allRecords) {
    const detail = rootCauseDetail(row);
    if (!detail) return [];
    const membershipCount = (records, key) => (records || []).filter((record) => (
      new Set(diagnosticStrings(record && record.root_cause_keys)).has(key)
    )).length;
    return detail.keys.map((key) => ({
      key,
      visible: membershipCount(visibleRecords, key),
      total: membershipCount(allRecords, key)
    }));
  }

  function frameSearchText(row) {
    if (!row || typeof row !== "object") return "";
    return [row.frame_cause, row.frame_evidence, row.frame_probe_status,
      row.frame_match_relevance, row.frame_attribution_status,
      row.frame_source_object_symbol, row.frame_raw_verdict, row.frame_reason]
      .filter((value) => typeof value === "string" && value).join(" ");
  }

  function matchesFrameFilters(row, filters) {
    const selected = filters || {};
    return (!selected.evidence || row.frame_evidence === selected.evidence)
      && (!selected.probeStatus || row.frame_probe_status === selected.probeStatus)
      && (!selected.matchRelevance || row.frame_match_relevance === selected.matchRelevance);
  }

  function frameMetricCounts(rows) {
    const counts = { needsAttribution: 0, materializable: 0, validatedImproving: 0 };
    for (const row of rows || []) {
      if (row.frame_probe_status === "needs-attribution") counts.needsAttribution += 1;
      if (row.frame_probe_status === "materializable") counts.materializable += 1;
      if (row.frame_probe_status === "validated-improving") counts.validatedImproving += 1;
    }
    return counts;
  }

  function frameDetail(row) {
    if (!row || typeof row !== "object") return null;
    if (!["frame_cause", "frame_evidence", "frame_probe_status"].some(
      (key) => Object.prototype.hasOwnProperty.call(row, key)
    )) return null;
    return {
      cause: row.frame_cause || "",
      evidence: row.frame_evidence || "",
      probeStatus: row.frame_probe_status || "",
      matchRelevance: row.frame_match_relevance || "",
      attributionStatus: row.frame_attribution_status || "",
      sourceObject: row.frame_source_object_symbol || row.frame_source_object || null,
      rawVerdict: row.frame_raw_verdict || row.frame_verdict || "",
      reason: row.frame_reason || row.actionability_reason || ""
    };
  }

  function diagnosticStrings(values) {
    return Array.isArray(values) ? values.filter((value) => typeof value === "string") : [];
  }

  function controlFlowShapeSearchText(row) {
    if (!row || typeof row !== "object") return "";
    return [
      ...diagnosticStrings(row.control_flow_shape_hint_kinds),
      row.control_flow_shape_source_preflight_status,
      row.control_flow_shape_source_preflight_reason,
      ...diagnosticStrings(row.control_flow_shape_blockers)
    ].filter((value) => typeof value === "string" && value).join(" ");
  }

  function controlFlowShapeDetail(row) {
    if (!row || typeof row !== "object") return null;
    const hasDiagnostic = [
      "control_flow_shape_analysis_status",
      "control_flow_shape_hint_kinds",
      "control_flow_shape_hints",
      "control_flow_shape_source_preflight_status",
      "control_flow_shape_source_preflight_reason",
      "control_flow_shape_generated_probe_count",
      "control_flow_shape_blockers",
      "control_flow_shape_validation_status",
      "control_flow_shape_validated_probe_count"
    ].some((key) => Object.prototype.hasOwnProperty.call(row, key));
    if (!hasDiagnostic) return null;
    return {
      analysisStatus: typeof row.control_flow_shape_analysis_status === "string"
        ? row.control_flow_shape_analysis_status : "",
      hintKinds: diagnosticStrings(row.control_flow_shape_hint_kinds),
      hints: Array.isArray(row.control_flow_shape_hints)
        ? row.control_flow_shape_hints.filter((hint) => hint && typeof hint === "object") : [],
      sourcePreflightStatus: typeof row.control_flow_shape_source_preflight_status === "string"
        ? row.control_flow_shape_source_preflight_status : "",
      sourcePreflightReason: typeof row.control_flow_shape_source_preflight_reason === "string"
        ? row.control_flow_shape_source_preflight_reason : "",
      generatedProbeCount: Number.isFinite(row.control_flow_shape_generated_probe_count)
        ? row.control_flow_shape_generated_probe_count : 0,
      blockers: diagnosticStrings(row.control_flow_shape_blockers),
      validationStatus: typeof row.control_flow_shape_validation_status === "string"
        ? row.control_flow_shape_validation_status : "",
      validatedProbeCount: Number.isFinite(row.control_flow_shape_validated_probe_count)
        ? row.control_flow_shape_validated_probe_count : 0
    };
  }

  function opcodeDeltaSignatureSearchText(row) {
    return row && typeof row === "object" && typeof row.opcode_delta_signature === "string"
      ? row.opcode_delta_signature : "";
  }

  function isOpcodeValue(value) {
    return value === null || typeof value === "string";
  }

  function opcodeDeltaSignatureDetail(row) {
    if (!row || typeof row !== "object") return null;
    const hasStatus = Object.prototype.hasOwnProperty.call(
      row, "opcode_delta_signature_status"
    );
    const status = typeof row.opcode_delta_signature_status === "string"
      ? row.opcode_delta_signature_status : "";
    if (hasStatus && status && status !== "available"
      && row.opcode_delta_signature === "") {
      return { status, signature: "", first: [], dominant: [] };
    }
    if (typeof row.opcode_delta_signature !== "string" || !row.opcode_delta_signature) {
      return null;
    }
    let parsed;
    try {
      parsed = JSON.parse(row.opcode_delta_signature);
    } catch {
      return null;
    }
    if (!parsed || typeof parsed !== "object" || parsed.version !== 1) return null;
    if (!Array.isArray(parsed.first) || parsed.first.length !== 2
      || !parsed.first.every(isOpcodeValue)) return null;
    if (!Array.isArray(parsed.dominant) || !parsed.dominant.every((pair) => (
      Array.isArray(pair) && pair.length === 3
      && isOpcodeValue(pair[0]) && isOpcodeValue(pair[1])
      && Number.isInteger(pair[2]) && pair[2] > 0
    ))) return null;
    return {
      status,
      signature: row.opcode_delta_signature,
      first: parsed.first.slice(),
      dominant: parsed.dominant.map((pair) => pair.slice())
    };
  }

  function resolveManifest(manifest, records, queueCounts) {
    const source = manifest || {};
    records = normalizeRecords(records);
    const bucketOrder = ordered(source.bucketOrder, observed(records, "work_bucket"));
    const tierOrder = ordered(source.tierOrder, observed(records, "match_tier"));
    const primaryOrder = ordered(source.primaryOrder, observed(records, "primary"));
    const actionabilityOrder = ordered(
      source.actionabilityOrder,
      observed(records, "source_actionability")
    );
    const frameEvidenceOrder = ordered(source.frameEvidenceOrder, observed(records, "frame_evidence"));
    const frameProbeStatusOrder = ordered(source.frameProbeStatusOrder, observed(records, "frame_probe_status"));
    const frameMatchRelevanceOrder = ordered(source.frameMatchRelevanceOrder, observed(records, "frame_match_relevance"));
    const interventionObserved = observed(records, "primary_intervention");
    const evidenceStageObserved = observed(records, "evidence_stage");
    const secondarySignalObserved = observedMany(records, "secondary_signals");
    const blockerFamilyObserved = observedMany(records, "blocker_families");
    const semanticDeltaFamilyObserved = observedMany(records, "semantic_delta_families");
    const opcodeEditDirectionObserved = observed(records, "opcode_edit_direction");
    const normalizedTriggerFamilyObserved = observed(records, "normalized_trigger_family");
    const rootCauseCounts = new Map();
    records.forEach((row) => {
      new Set(diagnosticStrings(row.root_cause_keys)).forEach((value) => {
        rootCauseCounts.set(value, (rootCauseCounts.get(value) || 0) + 1);
      });
    });
    const rootCauseKeyObserved = Array.from(rootCauseCounts).sort((a, b) => (
      (b[1] - a[1]) || a[0].localeCompare(b[0])
    )).map(([value]) => value);
    const interventionOrder = ordered(
      source.interventionOrder || primaryInterventionOrder.filter(
        (value) => interventionObserved.includes(value)
      ),
      interventionObserved
    );
    const resolvedEvidenceStageOrder = ordered(
      source.evidenceStageOrder || evidenceStageOrder.filter(
        (value) => evidenceStageObserved.includes(value)
      ),
      evidenceStageObserved
    );
    const resolvedSecondarySignalOrder = ordered(
      source.secondarySignalOrder || secondarySignalOrder.filter(
        (value) => secondarySignalObserved.includes(value)
      ),
      secondarySignalObserved
    );
    const resolvedBlockerFamilyOrder = ordered(
      source.blockerFamilyOrder || blockerFamilyOrder.filter(
        (value) => blockerFamilyObserved.includes(value)
      ),
      blockerFamilyObserved
    );
    const resolvedSemanticDeltaFamilyOrder = ordered(
      source.semanticDeltaFamilyOrder || semanticDeltaFamilyOrder.filter(
        (value) => semanticDeltaFamilyObserved.includes(value)
      ),
      semanticDeltaFamilyObserved
    );
    const resolvedOpcodeEditDirectionOrder = ordered(
      source.opcodeEditDirectionOrder || opcodeEditDirectionOrder.filter(
        (value) => opcodeEditDirectionObserved.includes(value)
      ),
      opcodeEditDirectionObserved
    );
    const resolvedNormalizedTriggerFamilyOrder = ordered(
      source.normalizedTriggerFamilyOrder || normalizedTriggerFamilyOrder.filter(
        (value) => normalizedTriggerFamilyObserved.includes(value)
      ),
      normalizedTriggerFamilyObserved
    );
    const resolvedRootCauseKeyOrder = ordered(
      source.rootCauseKeyOrder || rootCauseKeyObserved,
      rootCauseKeyObserved
    );
    const rootCauseKeyInfo = Object.assign(
      Object.create(null), source.rootCauseKeyInfo || {}
    );
    resolvedRootCauseKeyOrder.forEach((value) => {
      if (Object.hasOwn(rootCauseKeyInfo, value)) return;
      if (value.startsWith("bss-symbol:") && value.slice("bss-symbol:".length)) {
        rootCauseKeyInfo[value] = {
          label: value.slice("bss-symbol:".length),
          description: "Named BSS symbol shared by a relocation-residual cohort.",
          focus: "Inspect all affected rows before building or applying a symbol-level fix."
        };
      } else {
        rootCauseKeyInfo[value] = fallbackInfo("root cause key", value, false);
        rootCauseKeyInfo[value].label = value.replaceAll("-", " ").replaceAll(":", " ")
          .split(" ").filter(Boolean)
          .map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
      }
    });
    const queueFiles = ordered(source.queueFiles, Object.keys(queueCounts || {}));
    return {
      schemaVersion: 5,
      bucketOrder,
      tierOrder,
      primaryOrder,
      actionabilityOrder,
      frameEvidenceOrder,
      frameProbeStatusOrder,
      frameMatchRelevanceOrder,
      interventionOrder,
      evidenceStageOrder: resolvedEvidenceStageOrder,
      secondarySignalOrder: resolvedSecondarySignalOrder,
      blockerFamilyOrder: resolvedBlockerFamilyOrder,
      semanticDeltaFamilyOrder: resolvedSemanticDeltaFamilyOrder,
      opcodeEditDirectionOrder: resolvedOpcodeEditDirectionOrder,
      normalizedTriggerFamilyOrder: resolvedNormalizedTriggerFamilyOrder,
      rootCauseKeyOrder: resolvedRootCauseKeyOrder,
      queueFiles,
      bucketInfo: withFallbacks(source.bucketInfo, bucketOrder, "bucket", true),
      primaryInfo: withFallbacks(source.primaryInfo, primaryOrder, "primary", false),
      actionabilityInfo: withFallbacks(
        source.actionabilityInfo, actionabilityOrder, "actionability", false
      ),
      frameEvidenceInfo: withFallbacks(source.frameEvidenceInfo, frameEvidenceOrder, "frame evidence", false),
      frameProbeStatusInfo: withFallbacks(source.frameProbeStatusInfo, frameProbeStatusOrder, "frame probe status", false),
      frameMatchRelevanceInfo: withFallbacks(source.frameMatchRelevanceInfo, frameMatchRelevanceOrder, "frame match relevance", false),
      interventionInfo: withFallbacks(
        source.interventionInfo, interventionOrder, "intervention", false
      ),
      evidenceStageInfo: withFallbacks(
        source.evidenceStageInfo, resolvedEvidenceStageOrder, "evidence stage", false
      ),
      secondarySignalInfo: withFallbacks(
        source.secondarySignalInfo, resolvedSecondarySignalOrder, "secondary signal", false
      ),
      blockerFamilyInfo: withFallbacks(
        source.blockerFamilyInfo, resolvedBlockerFamilyOrder, "blocker family", false
      ),
      semanticDeltaFamilyInfo: withFallbacks(
        source.semanticDeltaFamilyInfo || semanticDeltaFamilyInfo,
        resolvedSemanticDeltaFamilyOrder,
        "semantic delta family",
        false
      ),
      opcodeEditDirectionInfo: withFallbacks(
        source.opcodeEditDirectionInfo || opcodeEditDirectionInfo,
        resolvedOpcodeEditDirectionOrder,
        "opcode edit direction",
        false
      ),
      normalizedTriggerFamilyInfo: withFallbacks(
        source.normalizedTriggerFamilyInfo || normalizedTriggerFamilyInfo,
        resolvedNormalizedTriggerFamilyOrder,
        "normalized trigger family",
        false
      ),
      rootCauseKeyInfo
    };
  }

  return {
    resolveManifest,
    normalizeFrameRecord,
    normalizeRoutingRecord,
    normalizeSemanticDeltaRecord,
    normalizeRootCauseRecord,
    normalizeRecords,
    routingSearchText,
    matchesRoutingFilters,
    routingDetail,
    semanticDeltaSearchText,
    matchesSemanticDeltaFilters,
    semanticDeltaDetail,
    normalizedTriggerSignatureDetail,
    rootCauseSearchText,
    matchesRootCauseFilters,
    rootCauseDetail,
    rootCauseMembershipDetail,
    frameSearchText,
    matchesFrameFilters,
    frameMetricCounts,
    frameDetail,
    controlFlowShapeSearchText,
    controlFlowShapeDetail,
    opcodeDeltaSignatureSearchText,
    opcodeDeltaSignatureDetail
  };
});
