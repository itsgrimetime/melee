"""Canonical display metadata for function taxonomy dashboard artifacts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = 5
FALLBACK_COLOR = "#647076"

BUCKET_ORDER = [
    "signature-call-type",
    "inline-boundary",
    "structural-reconstruction",
    "normalized-structural-near-match",
    "backend-ceiling",
    "data-symbol-relocation",
    "stack-local-layout",
    "indexed-struct-pointer",
    "struct-offset-discrepancy",
    "known-small-pattern-candidate",
    "register-allocator",
]
TIER_ORDER = [">=99%", "97-99%", "95-97%", "90-95%", "<90%"]

PRIMARY_ORDER = [
    "signature-type-mismatch",
    "inline-boundary-toolchain-artifact",
    "control-flow-source-shape",
    "instruction-sequence",
    "data-symbol-or-relocation",
    "bss-anchor-ceiling",
    "indexed-struct-pointer-materialization",
    "stack-slot-layout",
    "stack-layout",
    "register-allocation",
    "operand-register-or-offset",
    "normalized-structural-match",
    "normalized-structural-near-match",
    "backend-ceiling",
]

ACTIONABILITY_ORDER = [
    "current-tools-data-symbol",
    "current-tools-indexed-pointer",
    "current-tools-struct-verify",
    "current-tools",
    "advisory-signature-audit",
    "manual-inline-guidance",
    "manual-small-pattern",
    "structural-rebuild",
    "opcode-reconstruction",
    "pcdump-proof-needed",
    "struct-inference-blocked",
    "generator-gated",
    "normalized-structural-triage",
    "backend-ceiling",
    "ceiling",
    "diagnostic-only",
    "source-probe",
]

FRAME_EVIDENCE_ORDER = [
    "checkdiff-only",
    "pcdump-attributed",
    "tool-evaluated",
    "probe-validated",
]
FRAME_PROBE_STATUS_ORDER = [
    "needs-attribution",
    "materializable",
    "probe-inconclusive",
    "validated-improving",
    "terminal-no-safe-lever",
    "ceiling",
]
FRAME_MATCH_RELEVANCE_ORDER = [
    "match-gating-candidate",
    "match-neutral",
    "unknown",
]

PRIMARY_INTERVENTION_ORDER = [
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
    "register-allocation-proof",
]
SECONDARY_SIGNAL_ORDER = [
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
    "unresolved-struct-field",
]
EVIDENCE_STAGE_ORDER = [
    "heuristic",
    "observed",
    "attributed",
    "materializable",
    "evaluated",
    "validated",
    "blocked",
    "ceiling",
]
BLOCKER_FAMILY_ORDER = [
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
    "source-insensitive-ceiling",
]

SEMANTIC_DELTA_FAMILY_ORDER = [
    "address-constant-materialization",
    "integer-width-bitfield-scale",
    "floating-point-expression-storage",
    "branch-predicate-control",
    "indexed-update-memory",
    "frame-save-window",
    "integer-memory-width-transfer",
    "other-opcode-sequence",
]
OPCODE_EDIT_DIRECTION_ORDER = [
    "current-extra",
    "reference-extra",
    "substitution",
    "mixed",
    "operand-shape-only",
]
NORMALIZED_TRIGGER_SIZE_ORDER = ["one-line", "two-line", "three-line"]
NORMALIZED_TRIGGER_FAMILY_ORDER = [
    f"{size}-{direction}"
    for size in NORMALIZED_TRIGGER_SIZE_ORDER
    for direction in OPCODE_EDIT_DIRECTION_ORDER
]

_CONTROL_FLOW_BLOCKER_FAMILIES = {
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
    "analysis-error": "tooling-failure",
}
_NAME_MAGIC_BLOCKER_FAMILIES = {
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
    "sdata2-pool-order-dependent": "linker-order-dependence",
}

AUXILIARY_QUEUE_ORDER = [
    "checkdiff-errors.tsv",
    "report-only-not-extract-backed.tsv",
    "db-completed-extract-backed-non100.tsv",
]
CONTROL_FLOW_QUEUE_PREFIX = "structural-reconstruction.control-flow-shape"
CONTROL_FLOW_QUEUE_KINDS = (
    "branch-idiom",
    "call-hoist",
    "pointer-walk-indexed-shape",
    "concurrent-buffer-lifetime",
    "loop-peel-unroll",
    "missing-extra-call-layer",
)

BUCKET_INFO = {
    "signature-call-type": {
        "label": "Signature / Call Type",
        "description": "Call setup differs in a way that usually points at prototypes, return types, parameter types, casts, or caller-side signature propagation.",
        "focus": "Audit declarations and call sites first; these are good candidates for batch type and header cleanup.",
        "color": "#c2413a",
    },
    "inline-boundary": {
        "label": "Inline Boundary",
        "description": "The mismatch centers on whether a helper call is emitted, inlined, or shaped as a toolchain inline artifact.",
        "focus": "Compare helper boundaries and inline source shape before tuning local statements.",
        "color": "#b7791f",
    },
    "structural-reconstruction": {
        "label": "Structural Reconstruction",
        "description": "Control flow or opcode sequence differs enough that the source is probably not expressing the original structure yet.",
        "focus": "Use opseq, xrefs, and nearby matched code to rebuild natural source structure.",
        "color": "#5156a6",
    },
    "normalized-structural-near-match": {
        "label": "Normalized Structural Near Match",
        "description": "Only one to three normalized instruction-structure lines remain, so the function is close but not proven allocator-only.",
        "focus": "Inspect the normalized residual and alignment evidence before source reconstruction or register-allocation work.",
        "color": "#6d5bd0",
    },
    "backend-ceiling": {
        "label": "Backend Ceiling",
        "description": "Current evidence attributes the residual to backend code generation or another source-insensitive boundary.",
        "focus": "Review the evidence and bank the row unless a credible source lever appears.",
        "color": "#6b7280",
    },
    "data-symbol-relocation": {
        "label": "Data / Symbol Relocation",
        "description": "Data, string, or relocation references are wrong even when surrounding code is close.",
        "focus": "Model named data, string blobs, and relocation-bearing objects instead of chasing registers.",
        "color": "#0f766e",
    },
    "stack-local-layout": {
        "label": "Stack / Local Layout",
        "description": "The function is close, but stack frame size, slot placement, or local lifetime is still different.",
        "focus": "Try declaration order, local scope/lifetime, and frame-layout diagnostics.",
        "color": "#2f855a",
    },
    "indexed-struct-pointer": {
        "label": "Indexed Struct Pointer",
        "description": "The compiler chose a different source shape for array-indexed struct access versus materialized element pointers.",
        "focus": "Rewrite array/struct access form and pointer temporaries around indexed loads and stores.",
        "color": "#0e7490",
    },
    "struct-offset-discrepancy": {
        "label": "Struct Offset Discrepancy",
        "description": "Base-register field displacements differ in a way that may indicate a struct layout or field-selection mismatch.",
        "focus": "Run struct verify and use verified named-field evidence before treating the residual as allocator noise.",
        "color": "#2563a6",
    },
    "known-small-pattern-candidate": {
        "label": "Known Small Pattern",
        "description": "Only a small opcode, operand, or idiom remains, and it resembles patterns that are often batch-fixable.",
        "focus": "Search mismatch DB/opcode examples and try narrow type, cast, or addressing tweaks.",
        "color": "#805ad5",
    },
    "register-allocator": {
        "label": "Register Allocator",
        "description": "The instruction stream is largely right, but register allocation or scheduling proof is still needed.",
        "focus": "Use pcdump-backed evidence and first-divergence analysis before manual RA tuning.",
        "color": "#b83280",
    },
}

PRIMARY_INFO = {
    "signature-type-mismatch": {
        "label": "Signature Type Mismatch",
        "description": "A call or operand shape suggests the compiler sees different argument, return, pointer, signedness, or cast information.",
        "focus": "Start with headers, prototypes, typedef width, and explicit casts at the relevant call.",
    },
    "inline-boundary-toolchain-artifact": {
        "label": "Inline Boundary Toolchain Artifact",
        "description": "The reference and current code disagree around a helper call versus inlined body, often due to inline annotations or helper source shape.",
        "focus": "Check helper definitions, static inline boundaries, and call-preserving source forms.",
    },
    "control-flow-source-shape": {
        "label": "Control Flow Source Shape",
        "description": "Branching, loop structure, condition ordering, or early-exit shape is not matching the original source structure.",
        "focus": "Reconstruct the high-level control flow before chasing final register differences.",
    },
    "instruction-sequence": {
        "label": "Instruction Sequence",
        "description": "Opcode order or selected instructions differ without a more specific classifier taking ownership.",
        "focus": "Compare similar matched functions and known opcode idioms for source-shape clues.",
    },
    "data-symbol-or-relocation": {
        "label": "Data Symbol Or Relocation",
        "description": "A data reference, string symbol, relocation, or blob offset is mismatched.",
        "focus": "Name the data and model blob layout so the emitted relocation matches.",
    },
    "bss-anchor-ceiling": {
        "label": "BSS Anchor Ceiling",
        "description": "Named BSS versus .bss.0 section-anchor residuals are currently treated as a compiler or linker anchor ceiling.",
        "focus": "Bank the row unless a validated source candidate proves otherwise.",
    },
    "indexed-struct-pointer-materialization": {
        "label": "Indexed Struct Pointer Materialization",
        "description": "One side materializes an element pointer while the other keeps address arithmetic in indexed load/store instructions.",
        "focus": "Adjust temporary pointers, array indexing, and struct member access shape.",
    },
    "stack-slot-layout": {
        "label": "Stack Slot Layout",
        "description": "The frame size is usually close, but local variables or spills occupy different stack slots.",
        "focus": "Try local declaration order, scope narrowing, and lifetime changes.",
    },
    "stack-layout": {
        "label": "Stack Layout",
        "description": "The overall stack frame reservation or local storage shape differs.",
        "focus": "Look for missing locals, widened types, helper calls, or source shapes that create spills.",
    },
    "register-allocation": {
        "label": "Register Allocation",
        "description": "Remaining differences are mainly register choices after the structural instruction stream is close.",
        "focus": "Use pcdump/allocator diagnostics to prove the first allocator divergence.",
    },
    "operand-register-or-offset": {
        "label": "Operand Register Or Offset",
        "description": "A small register operand, immediate, or offset differs while the surrounding opcode pattern is close.",
        "focus": "Check casts, constants, field offsets, address bases, and narrow source-expression tweaks.",
    },
    "normalized-structural-match": {
        "label": "Normalized Structural Match",
        "description": "The normalized instruction structure matches even though raw operands, registers, or labels still differ.",
        "focus": "Inspect operand and allocator evidence rather than rebuilding control flow.",
    },
    "normalized-structural-near-match": {
        "label": "Normalized Structural Near Match",
        "description": "Only a very small normalized structural residual remains.",
        "focus": "Inspect the remaining normalized lines before deciding whether this is allocator-only.",
    },
    "backend-ceiling": {
        "label": "Backend Ceiling",
        "description": "Current evidence attributes the remaining mismatch to backend code generation or another source-insensitive boundary.",
        "focus": "Review backend evidence and bank the row unless a credible source lever appears.",
    },
}

ACTIONABILITY_INFO = {
    "advisory-signature-audit": {
        "label": "Advisory Signature Audit",
        "description": "Prototype, cast, typedef-width, or call-shape work where current tools provide diagnostics but not source-emitting candidates.",
        "focus": "Run debug suggest casts, audit headers, and verify call-site declarations manually.",
    },
    "manual-inline-guidance": {
        "label": "Manual Inline Guidance",
        "description": "Inline or emitted-call boundary work where existing pattern inspection gives context but not bounded source patches.",
        "focus": "Compare helper definitions, static inline annotations, and call-preserving source forms manually.",
    },
    "current-tools-data-symbol": {
        "label": "Data Symbol Tools",
        "description": "Data, string, blob, or relocation rows where naming/modeling data is the primary current-tool path.",
        "focus": "Use checkdiff name-magic evidence and model named data or string blobs.",
    },
    "current-tools-indexed-pointer": {
        "label": "Indexed Pointer Shape",
        "description": "Array-indexed versus materialized element-pointer rows that current source-shape rewrites can test.",
        "focus": "Try pointer temporaries, array indexing, and struct member access variants.",
    },
    "current-tools-struct-verify": {
        "label": "Struct Verify Tools",
        "description": "Offset residuals for which the struct resolver can check base registers and named fields.",
        "focus": "Run the row's struct verify command and prioritize resolver-verified findings.",
    },
    "manual-small-pattern": {
        "label": "Manual Small Pattern",
        "description": "Tiny opcode, operand, or idiom rows that are good mismatch-db/opseq candidates.",
        "focus": "Search known patterns, then try a narrow type, cast, constant, or address-base tweak.",
    },
    "current-tools": {
        "label": "Current Frame Tools",
        "description": "Frame rows with a bounded current-tool probe path.",
        "focus": "Run the row's next command before broader source exploration.",
    },
    "structural-rebuild": {
        "label": "Structural Rebuild",
        "description": "Control-flow/source-shape rows that need natural branch, loop, or early-exit reconstruction.",
        "focus": "Use extract, opseq, xrefs, and nearby matched functions to rebuild high-level structure.",
    },
    "opcode-reconstruction": {
        "label": "Opcode Reconstruction",
        "description": "Generic instruction sequence rows where the next split is opcode-pattern research.",
        "focus": "Search opseq and mismatch-db for similar emitted instruction runs.",
    },
    "pcdump-proof-needed": {
        "label": "Pcdump Proof Needed",
        "description": "Register-allocation rows that need allocator evidence before source edits are credible.",
        "focus": "Collect pcdump-backed first-divergence or force-phys evidence.",
    },
    "struct-inference-blocked": {
        "label": "Struct Inference Blocked",
        "description": (
            "The offset residual is real, but the struct resolver cannot map it "
            "to a named field and data-symbol preflight found no supported pair."
        ),
        "focus": (
            "Improve struct/type evidence or resolver coverage before retrying "
            "source or relocation probes."
        ),
    },
    "generator-gated": {
        "label": "Generator Gated",
        "description": "Likely source-reachable, but blocked on a missing generator or source lever.",
        "focus": "Inspect the row evidence to identify what bounded tooling is still missing.",
    },
    "normalized-structural-triage": {
        "label": "Normalized Structural Triage",
        "description": "A near-zero normalized structural residual needs inspection before it can be assigned to a source or allocator workflow.",
        "focus": "Compare the remaining normalized lines and their alignment context; do not assume it is a terminal backend ceiling.",
    },
    "backend-ceiling": {
        "label": "Backend Ceiling",
        "description": "Rows classified as backend/toolchain ceilings or direct-inspection cases, not current source-probe wins.",
        "focus": "Inspect manually and bank unless new evidence reveals a source lever.",
    },
    "ceiling": {
        "label": "Ceiling",
        "description": "Current evidence marks this as unresolved, compiler-internal, or not worth routing to source probes.",
        "focus": "Bank it or collect better attribution evidence.",
    },
    "diagnostic-only": {
        "label": "Diagnostic Only",
        "description": "Rows where current tools can explain the residual but do not yet offer a bounded source transform.",
        "focus": "Inspect before investing in source experiments.",
    },
    "source-probe": {
        "label": "Generic Source Probe",
        "description": "Fallback actionability for rows that do not yet have a sharper source-action tier.",
        "focus": "Use the bucket and primary classification to choose the first tool.",
    },
}

FRAME_EVIDENCE_INFO = {
    "checkdiff-only": {"label": "Checkdiff Only", "description": "Only assembly-diff classification is available.", "focus": "Materialize pcdump attribution before selecting a source probe."},
    "pcdump-attributed": {"label": "Pcdump Attributed", "description": "A pcdump frame report provides source/object attribution.", "focus": "Use the report's bounded next command."},
    "tool-evaluated": {"label": "Tool Evaluated", "description": "A bounded diagnostic ran without a successful compiled probe.", "focus": "Respect the diagnostic outcome without overstating validation."},
    "probe-validated": {"label": "Probe Validated", "description": "Compiled probe results establish the reported outcome.", "focus": "Use the measured probe result."},
}
FRAME_PROBE_STATUS_INFO = {
    "needs-attribution": {"label": "Needs Attribution", "description": "Source-probe selection awaits pcdump attribution.", "focus": "Dump pcdump and inspect frame reservations."},
    "materializable": {"label": "Materializable", "description": "A bounded source probe can be compiled.", "focus": "Run the materialized command."},
    "probe-inconclusive": {"label": "Probe Inconclusive", "description": "Bounded evaluation did not establish improvement or a ceiling.", "focus": "Review preserved probe diagnostics."},
    "validated-improving": {"label": "Validated Improving", "description": "A compiled source probe improved the frame objective.", "focus": "Continue from the validated source lever."},
    "terminal-no-safe-lever": {"label": "Terminal: No Safe Lever", "description": "Bounded semantic analysis found no safe source lever.", "focus": "Bank unless new evidence changes the source model."},
    "ceiling": {"label": "Measured Ceiling", "description": "Compiled bounded probes left the frame objective unchanged.", "focus": "Bank the measured ceiling."},
}
FRAME_MATCH_RELEVANCE_INFO = {
    "match-gating-candidate": {"label": "Match-Gating Candidate", "description": "Explicit before/after match evidence associates the frame change with match progress.", "focus": "Use the score evidence."},
    "match-neutral": {"label": "Match Neutral", "description": "A same-frame offset-only residual is match-neutral.", "focus": "Do not treat it as a frame-size match gate."},
    "unknown": {"label": "Unknown", "description": "Current evidence does not establish match relevance.", "focus": "Require explicit before/after match-score evidence."},
}


def _facet_info(
    labels: Mapping[str, str], description: str, focus: str
) -> dict[str, dict[str, str]]:
    return {
        value: {
            "label": label,
            "description": description.format(label=label.lower()),
            "focus": focus,
        }
        for value, label in labels.items()
    }


PRIMARY_INTERVENTION_INFO = _facet_info(
    {
        "signature-audit": "Signature Audit",
        "inline-boundary-reconstruction": "Inline Boundary Reconstruction",
        "control-flow-reconstruction": "Control Flow Reconstruction",
        "opcode-sequence-reconstruction": "Opcode Sequence Reconstruction",
        "manual-attribution": "Manual Attribution",
        "normalized-residual-attribution": "Normalized Residual Attribution",
        "backend-ceiling-review": "Backend Ceiling Review",
        "bss-anchor-analysis": "BSS Anchor Analysis",
        "data-symbol-modeling": "Data Symbol Modeling",
        "stack-lifetime-layout": "Stack Lifetime Layout",
        "stack-frame-reconstruction": "Stack Frame Reconstruction",
        "indexed-pointer-rewrite": "Indexed Pointer Rewrite",
        "struct-layout-inference": "Struct Layout Inference",
        "small-pattern-research": "Small Pattern Research",
        "register-allocation-proof": "Register Allocation Proof",
    },
    "The primary intervention is {label}.",
    "Use this route to select the first specialized workflow.",
)
SECONDARY_SIGNAL_INFO = _facet_info(
    {
        "normalized-structural-match": "Normalized Structural Match",
        "near-zero-structural-residual": "Near-Zero Structural Residual",
        "opcode-delta-signature": "Opcode Delta Signature",
        "branch-idiom": "Branch Idiom",
        "call-hoist": "Call Hoist",
        "pointer-walk-indexed-shape": "Pointer Walk / Indexed Shape",
        "concurrent-buffer-lifetime": "Concurrent Buffer Lifetime",
        "loop-peel-unroll": "Loop Peel / Unroll",
        "missing-extra-call-layer": "Missing / Extra Call Layer",
        "indexed-pointer-materialization": "Indexed Pointer Materialization",
        "stack-slot-displacement": "Stack Slot Displacement",
        "equal-size-stack-layout": "Equal-Size Stack Layout",
        "frame-size-delta": "Frame Size Delta",
        "operand-displacement": "Operand Displacement",
        "relocation-only-residual": "Relocation-Only Residual",
        "bss-section-anchor": "BSS Section Anchor",
        "register-only-delta": "Register-Only Delta",
        "callee-save-register-rotation": "Callee-Save Register Rotation",
        "volatile-register-selection": "Volatile Register Selection",
        "backend-register-window-rotation": "Backend Register Window Rotation",
        "inline-boundary-artifact": "Inline Boundary Artifact",
        "struct-field-verified": "Struct Field Verified",
        "unresolved-struct-field": "Unresolved Struct Field",
    },
    "Structured evidence reports {label}.",
    "Use this signal as a cross-bucket tooling filter.",
)
EVIDENCE_STAGE_INFO = {
    "heuristic": {
        "label": "Heuristic",
        "description": "The primary route is inferred without stronger structured evidence.",
        "focus": "Collect route-specific evidence before automating a source change.",
    },
    "observed": {
        "label": "Observed",
        "description": "Structured diff evidence directly supports the primary route.",
        "focus": "Inspect the observed evidence and choose a bounded next step.",
    },
    "attributed": {
        "label": "Attributed",
        "description": "Tool evidence attributes the residual to a source object or field.",
        "focus": "Use the named attribution to target the intervention.",
    },
    "materializable": {
        "label": "Materializable",
        "description": "A bounded source probe can be generated but is not yet validated.",
        "focus": "Compile and score the generated probe.",
    },
    "evaluated": {
        "label": "Evaluated",
        "description": "A bounded diagnostic or probe ran without proving improvement.",
        "focus": "Review the evaluation result before expanding the search.",
    },
    "validated": {
        "label": "Validated",
        "description": "A compiled probe produced measured improvement.",
        "focus": "Continue from the validated source lever.",
    },
    "blocked": {
        "label": "Blocked",
        "description": "Current route-specific evidence prevents a bounded probe.",
        "focus": "Resolve the listed blocker families first.",
    },
    "ceiling": {
        "label": "Ceiling",
        "description": "Current evidence marks the primary route source-insensitive or terminal.",
        "focus": "Bank the row unless new evidence reveals a source lever.",
    },
}
BLOCKER_FAMILY_INFO = _facet_info(
    {
        "source-unavailable": "Source Unavailable",
        "build-artifact-unavailable": "Build Artifact Unavailable",
        "source-attribution": "Source Attribution",
        "source-anchor": "Source Anchor",
        "unsafe-source-transform": "Unsafe Source Transform",
        "no-source-candidate": "No Source Candidate",
        "struct-inference": "Struct Inference",
        "relocation-support": "Relocation Support",
        "relocation-ambiguity": "Relocation Ambiguity",
        "relocation-validation": "Relocation Validation",
        "linker-order-dependence": "Linker Order Dependence",
        "allocator-proof": "Allocator Proof",
        "residual-attribution": "Residual Attribution",
        "tooling-failure": "Tooling Failure",
        "no-safe-source-lever": "No Safe Source Lever",
        "source-insensitive-ceiling": "Source-Insensitive Ceiling",
    },
    "Structured evidence identifies {label} as a blocker family.",
    "Resolve or explicitly accept this blocker before source automation.",
)

SEMANTIC_DELTA_FAMILY_INFO = _facet_info(
    {
        "address-constant-materialization": "Address / Constant Materialization",
        "integer-width-bitfield-scale": "Integer Width / Bitfield / Scale",
        "floating-point-expression-storage": "Floating-Point Expression / Storage",
        "branch-predicate-control": "Branch / Predicate / Control",
        "indexed-update-memory": "Indexed / Update Memory",
        "frame-save-window": "Frame / Save Window",
        "integer-memory-width-transfer": "Integer Memory Width / Transfer",
        "other-opcode-sequence": "Other Opcode Sequence",
    },
    "Structured opcode presence places this residual in the {label} delta family.",
    "Use this as a likely focus for investigation, not as a proven source cause.",
)
OPCODE_EDIT_DIRECTION_INFO = _facet_info(
    {
        "current-extra": "Current Extra",
        "reference-extra": "Reference Extra",
        "substitution": "Substitution",
        "mixed": "Mixed",
        "operand-shape-only": "Operand Shape Only",
    },
    "The aligned opcode delta has {label} edit direction.",
    "Use the direction to narrow the likely focus while preserving the ordered evidence.",
)
NORMALIZED_TRIGGER_FAMILY_INFO = {
    family: {
        "label": family.replace("-", " ").title(),
        "description": (
            "A one-to-three-line normalized residual has this line-count and "
            "opcode edit-direction trigger family."
        ),
        "focus": (
            "Compare rows in this trigger family as a likely focus; inspect the "
            "exact safe signature before choosing a source experiment."
        ),
    }
    for family in NORMALIZED_TRIGGER_FAMILY_ORDER
}

SEMANTIC_DELTA_FIELDS = (
    "semantic_delta_families",
    "opcode_edit_direction",
    "normalized_trigger_signature_status",
    "normalized_trigger_signature",
    "normalized_trigger_family",
    "normalized_trigger_cluster_size",
)
ROOT_CAUSE_FIELDS = ("root_cause_keys", "max_root_cause_impact")

_DEPRECATED_FRAME_KEYS = {"closability_tier", "frame_closability_tier"}


def _sanitize_deprecated_frame_keys(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _sanitize_deprecated_frame_keys(nested)
            for key, nested in value.items()
            if key not in _DEPRECATED_FRAME_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_deprecated_frame_keys(nested) for nested in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_deprecated_frame_keys(nested) for nested in value)
    return value


def _recognized_frame_mutation_command(value: Any) -> bool:
    command = str(value or "")
    return any(
        token in command
        for token in (
            "melee-agent debug mutate frame-transform-search",
            "melee-agent debug mutate lifetime-layout",
        )
    )


def _has_bounded_frame_probe(row: Mapping[str, Any]) -> bool:
    if any(
        _recognized_frame_mutation_command(row.get(key))
        for key in ("next_command", "frame_next_command")
    ):
        return True
    for key in ("frame_probe_plan", "frame_transform_probe_plan", "probe_plan"):
        plan = row.get(key)
        if not isinstance(plan, Mapping) or plan.get("status") != "ready":
            continue
        commands = plan.get("suggested_commands")
        if isinstance(commands, Sequence) and any(
            isinstance(item, Mapping)
            and _recognized_frame_mutation_command(item.get("command"))
            for item in commands
        ):
            return True
    return False


def _legacy_frame_actionability(status: str, cause: str) -> tuple[str, str, str]:
    if status in {"materializable", "validated-improving"}:
        headline = (
            "lifetime-layout"
            if cause == "stack-object-offset-shift"
            else "frame-transform-search"
        )
        reason = (
            "compiled frame probe improved the frame objective"
            if status == "validated-improving"
            else "bounded frame evidence identifies a source probe ready to compile"
        )
        return "current-tools", headline, reason
    if status == "probe-inconclusive":
        return (
            "diagnostic-only",
            "frame-reservations",
            "bounded frame probe evaluation was inconclusive",
        )
    if status in {"terminal-no-safe-lever", "ceiling"}:
        return (
            "ceiling",
            "frame-reservations",
            "bounded frame evidence reached a terminal state",
        )
    return (
        "diagnostic-only",
        "frame-reservations",
        "pcdump attribution must precede source-probe selection",
    )


def normalize_frame_record(row: Mapping[str, Any]) -> dict[str, Any]:
    legacy_alias = bool(row.get("frame_closability_tier"))
    result = _sanitize_deprecated_frame_keys(row)
    frame_keys = (
        "frame_cause", "frame_verdict", "frame_raw_verdict",
        "frame_attribution_status", "frame_evidence", "frame_probe_status",
        "frame_closability_tier",
    )
    if not legacy_alias and not any(result.get(key) for key in frame_keys):
        result.pop("frame_closability_tier", None)
        return result
    legacy = legacy_alias or not all(
        result.get(key)
        for key in (
            "frame_evidence",
            "frame_probe_status",
            "frame_match_relevance",
        )
    )
    cause = str(result.get("frame_cause") or "")
    verdict = str(result.get("frame_raw_verdict") or result.get("frame_verdict") or "")
    attribution = str(result.get("frame_attribution_status") or "")
    evidence = str(result.get("frame_evidence") or "")
    status = str(result.get("frame_probe_status") or "")
    relevance = str(result.get("frame_match_relevance") or "")
    if not evidence:
        if not verdict and not attribution:
            evidence = "checkdiff-only"
        elif "checkdiff-only" in {verdict, attribution}:
            evidence = "checkdiff-only"
        elif verdict in {"source-reachable-validated", "partial-source-reachable-validated", "attributed-frame-unchanged", "internal-tiebreak-ceiling"}:
            evidence = "probe-validated"
        else:
            evidence = "pcdump-attributed"
    if not status:
        if evidence == "checkdiff-only":
            status = "needs-attribution"
        elif verdict in {"source-reachable-validated", "partial-source-reachable-validated"}:
            status = "validated-improving"
        elif verdict in {"attributed-frame-unchanged", "internal-tiebreak-ceiling"}:
            status = "ceiling"
        elif verdict == "source-reachable-candidate" and _has_bounded_frame_probe(result):
            status = "materializable"
        else:
            status = "needs-attribution"
    if not relevance:
        relevance = "match-neutral" if cause == "stack-object-offset-shift" else "unknown"
    result["frame_evidence"] = evidence
    result["frame_probe_status"] = status
    result["frame_match_relevance"] = relevance
    result.pop("frame_closability_tier", None)
    if legacy:
        actionability, headline, reason = _legacy_frame_actionability(status, cause)
        result["source_actionability"] = actionability
        result["headline_tool"] = headline
        result["actionability_reason"] = reason
    return result


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _ordered_string_list(
    values: Any, preferred: Sequence[str]
) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    cleaned = {
        value.strip()
        for value in values
        if isinstance(value, str) and value.strip()
    }
    return [value for value in preferred if value in cleaned] + sorted(
        cleaned.difference(preferred)
    )


def _derive_primary_intervention(row: Mapping[str, Any]) -> str:
    bucket = row.get("work_bucket")
    subcategory = row.get("subcategory")
    if bucket == "signature-call-type":
        return "signature-audit"
    if bucket == "inline-boundary":
        return "inline-boundary-reconstruction"
    if bucket == "structural-reconstruction":
        if subcategory == "branch-or-control-flow-shape":
            return "control-flow-reconstruction"
        if subcategory == "opcode-sequence-diff":
            return "opcode-sequence-reconstruction"
        return "manual-attribution"
    if bucket == "normalized-structural-near-match":
        return "normalized-residual-attribution"
    if bucket == "backend-ceiling":
        return "backend-ceiling-review"
    if bucket == "data-symbol-relocation":
        if subcategory == "bss-section-anchor-ceiling":
            return "bss-anchor-analysis"
        return "data-symbol-modeling"
    if bucket == "stack-local-layout":
        if subcategory in {
            "same-frame-stack-slot-placement",
            "unattributed-lifetime-or-ordering-shift",
        }:
            return "stack-lifetime-layout"
        return "stack-frame-reconstruction"
    if bucket == "indexed-struct-pointer":
        return "indexed-pointer-rewrite"
    if bucket == "struct-offset-discrepancy":
        return "struct-layout-inference"
    if bucket == "known-small-pattern-candidate":
        return "small-pattern-research"
    if bucket == "register-allocator":
        return "register-allocation-proof"
    return "manual-attribution"


def _stack_sizes(row: Mapping[str, Any]) -> tuple[Any, Any]:
    expected = row.get("expected_frame_size")
    current = row.get("current_frame_size")
    if expected is not None or current is not None:
        return expected, current
    classification = _mapping(row.get("classification"))
    for key in ("stack_frame_delta", "stack_frame_sizes"):
        sizes = _mapping(classification.get(key))
        if sizes:
            return sizes.get("expected_frame_size"), sizes.get("current_frame_size")
    return None, None


def _derive_secondary_signals(row: Mapping[str, Any]) -> list[str]:
    classification = _mapping(row.get("classification"))
    signals: list[str] = []
    gate_status = _mapping(classification.get("structural_truth_gate")).get("status")
    if gate_status == "structural-match":
        signals.append("normalized-structural-match")
    elif gate_status == "near-zero-structural-diff":
        signals.append("near-zero-structural-residual")
    if (
        row.get("opcode_delta_signature_status") == "available"
        and isinstance(row.get("opcode_delta_signature"), str)
        and row.get("opcode_delta_signature", "").strip()
    ):
        signals.append("opcode-delta-signature")
    hint_kinds = row.get("control_flow_shape_hint_kinds")
    if isinstance(hint_kinds, list):
        signals.extend(
            value
            for value in hint_kinds
            if isinstance(value, str) and value in SECONDARY_SIGNAL_ORDER
        )
    if classification.get("indexed_struct_pointer_materialization"):
        signals.append("indexed-pointer-materialization")
    if classification.get("stack_slot_localizer"):
        signals.append("stack-slot-displacement")
    if row.get("work_bucket") == "stack-local-layout":
        expected, current = _stack_sizes(row)
        if (
            isinstance(expected, int)
            and not isinstance(expected, bool)
            and isinstance(current, int)
            and not isinstance(current, bool)
        ):
            signals.append(
                "equal-size-stack-layout"
                if expected == current
                else "frame-size-delta"
            )
    if classification.get("offset_discrepancies"):
        signals.append("operand-displacement")
    if row.get("subcategory") == "normalized-structural-relocation-only":
        signals.append("relocation-only-residual")
    if _mapping(classification.get("bss_anchor_relocations")).get("pairs"):
        signals.append("bss-section-anchor")
    guidance = _mapping(classification.get("register_allocation_guidance"))
    if _positive_int(guidance.get("register_only_count")):
        signals.append("register-only-delta")
    if guidance.get("callee_swap_pairs"):
        signals.append("callee-save-register-rotation")
    if guidance.get("volatile_target_registers") or guidance.get(
        "volatile_current_registers"
    ):
        signals.append("volatile-register-selection")
    backend = _mapping(classification.get("backend_ceiling"))
    if (
        backend.get("subclass") == "register-window-rotation"
        or classification.get("register_window_rotation")
    ):
        signals.append("backend-register-window-rotation")
    if classification.get("inline_boundary_artifact"):
        signals.append("inline-boundary-artifact")
    if row.get("struct_verify_status") == "verified":
        signals.append("struct-field-verified")
    elif row.get("struct_verify_status") == "unverified":
        signals.append("unresolved-struct-field")
    return signals


def _derive_evidence_stage(
    row: Mapping[str, Any], intervention: str
) -> str:
    if intervention in {"stack-lifetime-layout", "stack-frame-reconstruction"}:
        status = row.get("frame_probe_status")
        evidence = row.get("frame_evidence")
        if status == "validated-improving":
            return "validated"
        if status == "materializable":
            return "materializable"
        if status == "probe-inconclusive":
            return "evaluated"
        if status in {"terminal-no-safe-lever", "ceiling"}:
            return "ceiling"
        if evidence == "tool-evaluated":
            return "evaluated"
        if evidence == "pcdump-attributed":
            return "attributed"
        if evidence == "checkdiff-only":
            return "observed"
        return "heuristic"
    if intervention == "control-flow-reconstruction":
        validation = row.get("control_flow_shape_validation_status")
        if (
            validation in {"validated", "validated-improving"}
            and _positive_int(row.get("control_flow_shape_validated_probe_count"))
        ):
            return "validated"
        preflight = row.get("control_flow_shape_source_preflight_status")
        if preflight == "materializable" and _positive_int(
            row.get("control_flow_shape_generated_probe_count")
        ):
            return "materializable"
        if preflight in {"terminal", "source-unavailable", "preflight-error"}:
            return "blocked"
        if row.get("control_flow_shape_analysis_status") == "heuristic-hints":
            return "heuristic"
        return "heuristic"
    if intervention in {"data-symbol-modeling", "bss-anchor-analysis"}:
        probe_count = row.get("name_magic_probe_count")
        stop_kind = row.get("name_magic_stop_kind")
        if _positive_int(probe_count) and stop_kind in {
            "validated",
            "validated-improving",
            "source-reachable-validated",
            "partial-source-reachable-validated",
        }:
            return "validated"
        if _positive_int(probe_count):
            return "materializable"
        if row.get("name_magic_blocker"):
            return "blocked"
        if intervention == "bss-anchor-analysis":
            return "ceiling"
        return "observed"
    if intervention == "struct-layout-inference":
        status = row.get("struct_verify_status")
        if status == "verified":
            return "attributed"
        if status in {"unverified", "unavailable"}:
            return "blocked"
        return "observed"
    if intervention == "backend-ceiling-review":
        return "ceiling"
    if intervention in {
        "register-allocation-proof",
        "normalized-residual-attribution",
        "indexed-pointer-rewrite",
        "signature-audit",
        "inline-boundary-reconstruction",
        "opcode-sequence-reconstruction",
        "small-pattern-research",
    }:
        return "observed"
    return "heuristic"


def _derive_blocker_families(
    row: Mapping[str, Any], intervention: str, stage: str
) -> list[str]:
    blockers: list[str] = []
    raw_control_blockers = row.get("control_flow_shape_blockers")
    if isinstance(raw_control_blockers, list):
        blockers.extend(
            _CONTROL_FLOW_BLOCKER_FAMILIES[value]
            for value in raw_control_blockers
            if isinstance(value, str) and value in _CONTROL_FLOW_BLOCKER_FAMILIES
        )
    preflight = row.get("control_flow_shape_source_preflight_status")
    if preflight == "source-unavailable":
        blockers.append("source-unavailable")
    elif preflight == "preflight-error":
        blockers.append("tooling-failure")

    name_magic_blocker = row.get("name_magic_blocker")
    if isinstance(name_magic_blocker, str):
        if (
            intervention == "struct-layout-inference"
            and name_magic_blocker == "raw-diff-no-supported-data-symbol-pair"
        ):
            blockers.append("struct-inference")
        elif (
            intervention in {"data-symbol-modeling", "bss-anchor-analysis"}
            and name_magic_blocker == "raw-diff-no-supported-data-symbol-pair"
        ):
            blockers.append("relocation-support")
        elif name_magic_blocker in _NAME_MAGIC_BLOCKER_FAMILIES:
            blockers.append(_NAME_MAGIC_BLOCKER_FAMILIES[name_magic_blocker])
        elif name_magic_blocker == "bss-anchor-ceiling" and stage == "ceiling":
            blockers.append("source-insensitive-ceiling")

    if intervention == "struct-layout-inference" and row.get(
        "struct_verify_status"
    ) in {"unverified", "unavailable"}:
        blockers.append("struct-inference")
    if intervention in {"stack-lifetime-layout", "stack-frame-reconstruction"}:
        status = row.get("frame_probe_status")
        if status == "needs-attribution":
            blockers.append("source-attribution")
        elif status == "terminal-no-safe-lever":
            blockers.append("no-safe-source-lever")
        elif status == "ceiling":
            blockers.append("source-insensitive-ceiling")
    if intervention == "register-allocation-proof" and stage != "validated":
        blockers.append("allocator-proof")
    if intervention == "normalized-residual-attribution":
        blockers.append("residual-attribution")
    if intervention == "backend-ceiling-review":
        blockers.append("source-insensitive-ceiling")
    if intervention == "bss-anchor-analysis" and stage == "ceiling":
        blockers.append("source-insensitive-ceiling")
    return blockers


def normalize_routing_record(
    row: Mapping[str, Any], *, preserve_existing: bool = True
) -> dict[str, Any]:
    result = dict(row)
    intervention = result.get("primary_intervention") if preserve_existing else None
    if not isinstance(intervention, str) or not intervention.strip():
        intervention = _derive_primary_intervention(result)
    else:
        intervention = intervention.strip()
    result["primary_intervention"] = intervention

    supplied_signals = result.get("secondary_signals") if preserve_existing else None
    signals = (
        supplied_signals
        if isinstance(supplied_signals, list)
        else _derive_secondary_signals(result)
    )
    result["secondary_signals"] = _ordered_string_list(
        signals, SECONDARY_SIGNAL_ORDER
    )

    stage = result.get("evidence_stage") if preserve_existing else None
    if not isinstance(stage, str) or not stage.strip():
        stage = _derive_evidence_stage(result, intervention)
    else:
        stage = stage.strip()
    result["evidence_stage"] = stage

    supplied_blockers = result.get("blocker_families") if preserve_existing else None
    blockers = (
        supplied_blockers
        if isinstance(supplied_blockers, list)
        else _derive_blocker_families(result, intervention, stage)
    )
    result["blocker_families"] = _ordered_string_list(
        blockers, BLOCKER_FAMILY_ORDER
    )
    return result


def normalize_semantic_delta_record(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if not any(key in result for key in SEMANTIC_DELTA_FIELDS):
        return result

    if "semantic_delta_families" in result:
        result["semantic_delta_families"] = _ordered_string_list(
            result.get("semantic_delta_families"), SEMANTIC_DELTA_FAMILY_ORDER
        )
    for key in (
        "opcode_edit_direction",
        "normalized_trigger_signature_status",
        "normalized_trigger_signature",
        "normalized_trigger_family",
    ):
        if key in result:
            value = result.get(key)
            result[key] = value.strip() if isinstance(value, str) else ""
    if "normalized_trigger_cluster_size" in result:
        value = result.get("normalized_trigger_cluster_size")
        result["normalized_trigger_cluster_size"] = (
            value if _positive_int(value) else 0
        )
    return result


def normalize_root_cause_record(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if not any(key in result for key in ROOT_CAUSE_FIELDS):
        return result

    if "root_cause_keys" in result:
        values = result.get("root_cause_keys")
        normalized: list[str] = []
        seen: set[str] = set()
        if isinstance(values, (list, tuple)):
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    continue
                cleaned = value.strip()
                if cleaned not in seen:
                    seen.add(cleaned)
                    normalized.append(cleaned)
        result["root_cause_keys"] = normalized
    if "max_root_cause_impact" in result:
        value = result.get("max_root_cause_impact")
        result["max_root_cause_impact"] = value if _positive_int(value) else 0
    return result


def _observed(records: Sequence[Mapping[str, Any]], key: str) -> list[str]:
    return sorted({str(row[key]) for row in records if row.get(key)})


def _observed_many(records: Sequence[Mapping[str, Any]], key: str) -> list[str]:
    return sorted(
        {
            value.strip()
            for row in records
            for value in (
                row.get(key) if isinstance(row.get(key), (list, tuple)) else []
            )
            if isinstance(value, str) and value.strip()
        }
    )


def _ordered(
    preferred: Sequence[str], observed: Sequence[str], *, keep_all_preferred: bool
) -> list[str]:
    observed_set = set(observed)
    known = list(preferred) if keep_all_preferred else [
        value for value in preferred if value in observed_set
    ]
    return known + sorted(observed_set.difference(preferred))


def _fallback_info(kind: str, value: str, *, color: bool = False) -> dict[str, str]:
    info = {
        "label": value.replace("-", " ").title(),
        "description": f"No curated {kind} description is available for this observed value.",
        "focus": (
            "Use the row evidence and next command; add curated metadata if this "
            "value becomes stable."
        ),
    }
    if color:
        info["color"] = FALLBACK_COLOR
    return info


def _info_for(
    curated: Mapping[str, Mapping[str, str]],
    values: Sequence[str],
    kind: str,
    *,
    color: bool = False,
) -> dict[str, dict[str, str]]:
    result = {key: dict(value) for key, value in curated.items()}
    for value in values:
        result.setdefault(value, _fallback_info(kind, value, color=color))
    return result


def _queue_sort_key(filename: str) -> tuple[int, int, str]:
    for index, bucket in enumerate(BUCKET_ORDER):
        if filename == f"{bucket}.tsv":
            return index, 0, filename
        if bucket == "structural-reconstruction":
            for control_index, kind in enumerate(CONTROL_FLOW_QUEUE_KINDS):
                if filename == f"{CONTROL_FLOW_QUEUE_PREFIX}.{kind}.tsv":
                    return index, 1, f"{control_index:02d}"
            if filename == f"{CONTROL_FLOW_QUEUE_PREFIX}.materializable.tsv":
                return index, 1, "06"
            if filename == f"{CONTROL_FLOW_QUEUE_PREFIX}.terminal.tsv":
                return index, 1, "07"
            if filename == "structural-reconstruction.opcode-sequence-diff.tsv":
                return index, 1, "08"
            for family_index, family in enumerate(SEMANTIC_DELTA_FAMILY_ORDER):
                if filename == (
                    "structural-reconstruction.opcode-family."
                    f"{family}.tsv"
                ):
                    return index, 1, f"{family_index + 9:02d}"
        if filename.startswith(f"{bucket}.") and filename.endswith(".tsv"):
            return index, 2, filename
    if filename == "root-cause.bss-symbol.repeated.tsv":
        return BUCKET_ORDER.index("data-symbol-relocation"), 3, filename
    routing_stage_files = [
        "routing.materializable.tsv",
        "routing.validated.tsv",
        "routing.blocked.tsv",
    ]
    if filename in routing_stage_files:
        return len(BUCKET_ORDER), routing_stage_files.index(filename), filename
    if filename in AUXILIARY_QUEUE_ORDER:
        return (
            len(BUCKET_ORDER) + 1,
            AUXILIARY_QUEUE_ORDER.index(filename),
            filename,
        )
    return len(BUCKET_ORDER) + 1, 0, filename


def build_dashboard_manifest(
    records: list[dict[str, Any]], queue_counts: dict[str, int]
) -> dict[str, Any]:
    bucket_order = _ordered(
        BUCKET_ORDER, _observed(records, "work_bucket"), keep_all_preferred=True
    )
    tier_order = _ordered(
        TIER_ORDER, _observed(records, "match_tier"), keep_all_preferred=True
    )
    primary_order = _ordered(
        PRIMARY_ORDER, _observed(records, "primary"), keep_all_preferred=False
    )
    actionability_order = _ordered(
        ACTIONABILITY_ORDER,
        _observed(records, "source_actionability"),
        keep_all_preferred=False,
    )
    frame_evidence_order = _ordered(
        FRAME_EVIDENCE_ORDER, _observed(records, "frame_evidence"),
        keep_all_preferred=False,
    )
    frame_probe_status_order = _ordered(
        FRAME_PROBE_STATUS_ORDER, _observed(records, "frame_probe_status"),
        keep_all_preferred=False,
    )
    frame_match_relevance_order = _ordered(
        FRAME_MATCH_RELEVANCE_ORDER, _observed(records, "frame_match_relevance"),
        keep_all_preferred=False,
    )
    intervention_order = _ordered(
        PRIMARY_INTERVENTION_ORDER,
        _observed(records, "primary_intervention"),
        keep_all_preferred=False,
    )
    evidence_stage_order = _ordered(
        EVIDENCE_STAGE_ORDER,
        _observed(records, "evidence_stage"),
        keep_all_preferred=False,
    )
    secondary_signal_order = _ordered(
        SECONDARY_SIGNAL_ORDER,
        _observed_many(records, "secondary_signals"),
        keep_all_preferred=False,
    )
    blocker_family_order = _ordered(
        BLOCKER_FAMILY_ORDER,
        _observed_many(records, "blocker_families"),
        keep_all_preferred=False,
    )
    semantic_delta_family_order = _ordered(
        SEMANTIC_DELTA_FAMILY_ORDER,
        _observed_many(records, "semantic_delta_families"),
        keep_all_preferred=False,
    )
    opcode_edit_direction_order = _ordered(
        OPCODE_EDIT_DIRECTION_ORDER,
        _observed(records, "opcode_edit_direction"),
        keep_all_preferred=False,
    )
    normalized_trigger_family_order = _ordered(
        NORMALIZED_TRIGGER_FAMILY_ORDER,
        _observed(records, "normalized_trigger_family"),
        keep_all_preferred=False,
    )
    root_cause_counts: Counter[str] = Counter()
    for row in records:
        values = row.get("root_cause_keys")
        if not isinstance(values, (list, tuple)):
            continue
        root_cause_counts.update(
            {
                value.strip()
                for value in values
                if isinstance(value, str) and value.strip()
            }
        )
    root_cause_key_order = sorted(
        root_cause_counts,
        key=lambda value: (-root_cause_counts[value], value),
    )
    root_cause_key_info = {}
    for value in root_cause_key_order:
        if value.startswith("bss-symbol:") and value.removeprefix("bss-symbol:"):
            root_cause_key_info[value] = {
                "label": value.removeprefix("bss-symbol:"),
                "description": (
                    "Named BSS symbol shared by a relocation-residual cohort."
                ),
                "focus": (
                    "Inspect all affected rows before building or applying a "
                    "symbol-level fix."
                ),
            }
        else:
            info = _fallback_info("root cause key", value)
            info["label"] = value.replace("-", " ").replace(":", " ").title()
            root_cause_key_info[value] = info
    return {
        "schemaVersion": SCHEMA_VERSION,
        "bucketOrder": bucket_order,
        "tierOrder": tier_order,
        "primaryOrder": primary_order,
        "actionabilityOrder": actionability_order,
        "frameEvidenceOrder": frame_evidence_order,
        "frameProbeStatusOrder": frame_probe_status_order,
        "frameMatchRelevanceOrder": frame_match_relevance_order,
        "interventionOrder": intervention_order,
        "evidenceStageOrder": evidence_stage_order,
        "secondarySignalOrder": secondary_signal_order,
        "blockerFamilyOrder": blocker_family_order,
        "semanticDeltaFamilyOrder": semantic_delta_family_order,
        "opcodeEditDirectionOrder": opcode_edit_direction_order,
        "normalizedTriggerFamilyOrder": normalized_trigger_family_order,
        "rootCauseKeyOrder": root_cause_key_order,
        "queueFiles": sorted(queue_counts, key=_queue_sort_key),
        "bucketInfo": _info_for(BUCKET_INFO, bucket_order, "bucket", color=True),
        "primaryInfo": _info_for(PRIMARY_INFO, primary_order, "primary"),
        "actionabilityInfo": _info_for(
            ACTIONABILITY_INFO, actionability_order, "actionability"
        ),
        "frameEvidenceInfo": _info_for(FRAME_EVIDENCE_INFO, frame_evidence_order, "frame evidence"),
        "frameProbeStatusInfo": _info_for(FRAME_PROBE_STATUS_INFO, frame_probe_status_order, "frame probe status"),
        "frameMatchRelevanceInfo": _info_for(FRAME_MATCH_RELEVANCE_INFO, frame_match_relevance_order, "frame match relevance"),
        "interventionInfo": _info_for(
            PRIMARY_INTERVENTION_INFO, intervention_order, "intervention"
        ),
        "evidenceStageInfo": _info_for(
            EVIDENCE_STAGE_INFO, evidence_stage_order, "evidence stage"
        ),
        "secondarySignalInfo": _info_for(
            SECONDARY_SIGNAL_INFO, secondary_signal_order, "secondary signal"
        ),
        "blockerFamilyInfo": _info_for(
            BLOCKER_FAMILY_INFO, blocker_family_order, "blocker family"
        ),
        "semanticDeltaFamilyInfo": _info_for(
            SEMANTIC_DELTA_FAMILY_INFO,
            semantic_delta_family_order,
            "semantic delta family",
        ),
        "opcodeEditDirectionInfo": _info_for(
            OPCODE_EDIT_DIRECTION_INFO,
            opcode_edit_direction_order,
            "opcode edit direction",
        ),
        "normalizedTriggerFamilyInfo": _info_for(
            NORMALIZED_TRIGGER_FAMILY_INFO,
            normalized_trigger_family_order,
            "normalized trigger family",
        ),
        "rootCauseKeyInfo": root_cause_key_info,
    }
