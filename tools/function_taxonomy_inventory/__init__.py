# Classification, output writing, and main entrypoint.
# Shared utilities and dataclasses live in _common.py.

from __future__ import annotations

from collections import Counter

from ._common import *  # noqa: F403 — re-export everything from _common
from ._common import (  # noqa: F401 — explicit imports below
    # _-prefixed names not exported by import *
    _DECL_ORDER_EVAL_LOCK,
    _tail_text,
    _format_timeout,
    _snapshot_candidate_source,
    _restore_candidate_source,
    _signature_residual_bucket,
    _stack_frame_missing_bytes,
    # Public names (redundant with import * but clarifies dependencies)

    DEFAULT_CHECKDIFF_TIMEOUT,
    DEFAULT_DECL_ORDER_TIMEOUT,
    DEFAULT_NAME_MAGIC_PREFLIGHT_TIMEOUT,
    DEFAULT_STRUCT_VERIFY_TIMEOUT,
    DEFAULT_PROGRESS_INTERVAL,
    FunctionCandidate,
    InventoryResult,
    CheckdiffRunner,
    DeclOrderEvaluator,
    FrameReportRunner,
    CastAuditRunner,
    NameMagicPreflightRunner,
    StructVerifyRunner,
    format_address,
    match_tier,
    load_report_candidates,
    default_checkdiff_runner,
    parse_checkdiff_stdout,
    parse_json_object,
    is_known_small_candidate,
    struct_offset_discrepancies,
    offset_discrepancy_summary,
)
from .opcode_delta import derive_opcode_delta_evidence
from .root_cause import attach_root_cause_impacts, derive_root_cause_keys
from tools.function_taxonomy_schema import (
    EVIDENCE_STAGE_ORDER,
    PRIMARY_INTERVENTION_ORDER,
    SEMANTIC_DELTA_FAMILY_ORDER,
    normalize_root_cause_record,
    normalize_routing_record,
    normalize_semantic_delta_record,
)

CONTROL_FLOW_SHAPE_HINT_KINDS = (
    "branch-idiom",
    "call-hoist",
    "pointer-walk-indexed-shape",
    "concurrent-buffer-lifetime",
    "loop-peel-unroll",
    "missing-extra-call-layer",
)
CONTROL_FLOW_SHAPE_SUMMARY_FIELDS = (
    "control_flow_shape_analysis_status",
    "control_flow_shape_hint_kinds",
    "control_flow_shape_source_preflight_status",
    "control_flow_shape_source_preflight_reason",
    "control_flow_shape_generated_probe_count",
    "control_flow_shape_blockers",
    "control_flow_shape_validation_status",
    "control_flow_shape_validated_probe_count",
)
ROUTING_STAGE_QUEUE_VALUES = ("materializable", "validated", "blocked")


def _normalized_register_subcategory(
    classification: dict[str, Any],
) -> str | None:
    guidance = classification.get("register_allocation_guidance")
    if not isinstance(guidance, dict):
        return None
    if parse_int(guidance.get("register_only_count")) <= 0:
        return None
    has_callee_save = bool(guidance.get("callee_swap_pairs"))
    has_volatile = bool(
        guidance.get("volatile_target_registers")
        or guidance.get("volatile_current_registers")
    )
    if has_callee_save and has_volatile:
        return "callee-save-and-volatile-register-selection"
    if has_callee_save:
        return "callee-save-lifetime-ordering"
    if has_volatile:
        return "volatile-register-selection"
    return "normalized-register-selection"


def _has_data_symbol_relocation_reason(
    classification: dict[str, Any],
) -> bool:
    return any(
        "differing paired lines reference data/symbol relocations"
        in str(reason).lower()
        for reason in classification.get("reasons") or []
    )


def _has_equal_stack_frame_summary(classification: dict[str, Any]) -> bool:
    sizes = classification.get("stack_frame_sizes")
    if not isinstance(sizes, dict):
        return False
    expected = sizes.get("expected_frame_size")
    current = sizes.get("current_frame_size")
    growth = sizes.get("frame_growth")
    return (
        isinstance(expected, int)
        and not isinstance(expected, bool)
        and isinstance(current, int)
        and not isinstance(current, bool)
        and expected == current
        and (growth is None or growth == 0)
    )


def classify_bucket(
    candidate: FunctionCandidate,
    payload: dict[str, Any],
    *,
    cast_audit: dict[str, Any] | None = None,
) -> tuple[str, str, bool]:
    classification = payload.get("classification") or {}
    primary = classification.get("primary") or "unknown"
    reasons = classification.get("reasons") or []
    reason_text = "\n".join(str(reason).lower() for reason in reasons)

    if primary == "bss-anchor-ceiling" or classification.get(
        "bss_anchor_relocations"
    ):
        return "data-symbol-relocation", "bss-section-anchor-ceiling", False
    if primary == "signature-type-mismatch":
        if parse_int((cast_audit or {}).get("medium_plus_count")) <= 0:
            return _signature_residual_bucket(candidate, payload)
        return "signature-call-type", "call-shape-or-prototype", False
    if primary == "inline-boundary-toolchain-artifact":
        return "inline-boundary", "missing-reference-call-current-inlined", False
    if primary == "data-symbol-or-relocation":
        return "data-symbol-relocation", "persistent-data-symbol-or-relocation", False
    if primary == "indexed-struct-pointer-materialization":
        return "indexed-struct-pointer", "array-indexed-vs-element-pointer", False
    if primary == "stack-slot-layout":
        return "stack-local-layout", "same-frame-stack-slot-placement", False
    if primary == "stack-layout":
        missing = _stack_frame_missing_bytes(classification)
        if missing == 0:
            return "stack-local-layout", "same-frame-stack-slot-placement", False
        if _has_equal_stack_frame_summary(classification):
            return (
                "stack-local-layout",
                "unattributed-lifetime-or-ordering-shift",
                False,
            )
        if "frame reservation gap" in reason_text or "pad_stack" in reason_text:
            if missing is not None and missing > 0:
                return "stack-local-layout", "frame-too-small", False
            if missing is not None and missing < 0:
                return "stack-local-layout", "frame-too-large", False
            if "too small" in reason_text:
                return "stack-local-layout", "frame-too-small", False
            if "too large" in reason_text:
                return "stack-local-layout", "frame-too-large", False
            return "stack-local-layout", "frame-size-delta", False
        return "stack-local-layout", "frame-size-delta", False
    if primary == "register-allocation":
        if "hsd_assert" in reason_text or "assert" in reason_text:
            return "register-allocator", "register-plus-hsd-assert-data", False
        return "register-allocator", "register-only-needs-pcdump-proof", False
    if primary == "control-flow-source-shape":
        return "structural-reconstruction", "branch-or-control-flow-shape", False
    if primary == "instruction-sequence":
        return "structural-reconstruction", "opcode-sequence-diff", False
    if primary == "backend-ceiling":
        return "backend-ceiling", "source-insensitive-backend-ceiling", False
    if primary == "normalized-structural-near-match":
        return (
            "normalized-structural-near-match",
            "near-zero-normalized-structural-residual",
            False,
        )
    if struct_offset_discrepancies(classification):
        return "struct-offset-discrepancy", "struct-field-offset-displacement", False
    if primary == "normalized-structural-match":
        register_subcategory = _normalized_register_subcategory(classification)
        if register_subcategory is not None:
            return "register-allocator", register_subcategory, False
        if _has_data_symbol_relocation_reason(classification):
            return (
                "data-symbol-relocation",
                "normalized-structural-relocation-only",
                False,
            )
        return (
            "normalized-structural-near-match",
            "unattributed-zero-normalized-structural-residual",
            False,
        )
    if is_known_small_candidate(candidate, payload):
        return "known-small-pattern-candidate", "small-opcode-or-operand-pattern", True
    if primary == "operand-register-or-offset":
        return "known-small-pattern-candidate", "operand-register-offset-small", True
    return "structural-reconstruction", "direct-inspection-needed", False


def describe_actionability(
    bucket: str,
    subcategory: str,
    *,
    frame_taxonomy: dict[str, Any] | None = None,
) -> dict[str, str]:
    if bucket == "stack-local-layout" and frame_taxonomy is not None:
        probe_status = str(frame_taxonomy.get("probe_status") or "")
        cause = str(frame_taxonomy.get("cause") or "stack-frame-divergence")
        if probe_status in {"materializable", "validated-improving"}:
            headline = (
                "lifetime-layout"
                if cause == "stack-object-offset-shift"
                else "frame-transform-search"
            )
            return {
                "source_actionability": "current-tools",
                "headline_tool": headline,
                "actionability_reason": (
                    f"{cause}; report evidence identifies a bounded source probe"
                ),
            }
        if probe_status == "needs-attribution":
            return {
                "source_actionability": "diagnostic-only",
                "headline_tool": "frame-reservations",
                "actionability_reason": (
                    f"{cause}; pcdump attribution must precede source-probe selection"
                ),
            }
        if probe_status == "probe-inconclusive":
            return {
                "source_actionability": "diagnostic-only",
                "headline_tool": "frame-reservations",
                "actionability_reason": (
                    f"{cause}; bounded probe evidence was inconclusive"
                ),
            }
        if probe_status in {"terminal-no-safe-lever", "ceiling"}:
            return {
                "source_actionability": "ceiling",
                "headline_tool": "frame-reservations",
                "actionability_reason": (
                    f"{cause}; current evidence marks this as a ceiling or "
                    "unresolved compiler-layout boundary"
                ),
            }
    if bucket == "stack-local-layout":
        if subcategory == "same-frame-stack-slot-placement":
            return {
                "source_actionability": "source-probe",
                "headline_tool": "lifetime-layout",
                "actionability_reason": (
                    "same-frame stack-slot placement can be tested with "
                    "lifetime-layout and decl-order probes"
                ),
            }
        if subcategory == "unattributed-lifetime-or-ordering-shift":
            return {
                "source_actionability": "diagnostic-only",
                "headline_tool": "frame-reservations",
                "actionability_reason": (
                    "equal-size stack-layout residual without source-object "
                    "attribution; collect pcdump lifetime/order evidence"
                ),
            }
        if subcategory in {"frame-too-small", "frame-too-large", "frame-size-delta"}:
            return {
                "source_actionability": "diagnostic-only",
                "headline_tool": "frame-reservations",
                "actionability_reason": (
                    "frame-size residual; inspect the frame model, but no bounded "
                    "source transform is available yet"
                ),
            }
    if bucket == "known-small-pattern-candidate":
        return {
            "source_actionability": "manual-small-pattern",
            "headline_tool": "mismatch-db",
            "actionability_reason": (
                "small operand/opcode pattern likely has a targeted source "
                "edit, but no source-emitting harvest harness is registered "
                "yet; use mismatch-db as an advisory manual workflow"
            ),
        }
    if bucket == "signature-call-type":
        return {
            "source_actionability": "advisory-signature-audit",
            "headline_tool": "debug-suggest-signatures",
            "actionability_reason": (
                "call shape or prototype mismatch; run signature audit to inspect "
                "call-prep, prototypes, argument widths, and concrete rebucket reasons"
            ),
        }
    if bucket == "inline-boundary":
        return {
            "source_actionability": "manual-inline-guidance",
            "headline_tool": "patterns-inlines",
            "actionability_reason": (
                "inline/call boundary mismatch; compare helper definitions and "
                "call-preserving source forms manually because patterns-inlines "
                "does not emit bounded source candidates"
            ),
        }
    if bucket == "data-symbol-relocation":
        if subcategory == "bss-section-anchor-ceiling":
            return {
                "source_actionability": "ceiling",
                "headline_tool": "checkdiff-name-magic",
                "actionability_reason": (
                    "named BSS versus .bss.0 section-anchor residual; current "
                    "tooling labels this as a compiler or linker anchor ceiling "
                    "unless a validated source candidate proves otherwise"
                ),
            }
        return {
            "source_actionability": "current-tools-data-symbol",
            "headline_tool": "checkdiff-name-magic",
            "actionability_reason": (
                "data, string, or relocation mismatch; model named data and "
                "rerun checkdiff with relocation/name-magic evidence"
            ),
        }
    if bucket == "indexed-struct-pointer":
        return {
            "source_actionability": "current-tools-indexed-pointer",
            "headline_tool": "source-shape",
            "actionability_reason": (
                "array-indexed versus element-pointer source shape mismatch; "
                "try pointer temporary and indexed-access rewrites"
            ),
        }
    if (
        bucket == "struct-offset-discrepancy"
        and subcategory == "unresolved-operand-displacement"
    ):
        return {
            "source_actionability": "struct-inference-blocked",
            "headline_tool": "struct-verify",
            "actionability_reason": (
                "the operand displacement is real, but current struct/type "
                "inference cannot resolve it"
            ),
        }
    if bucket == "struct-offset-discrepancy":
        return {
            "source_actionability": "current-tools-struct-verify",
            "headline_tool": "struct-verify",
            "actionability_reason": (
                "base-register field displacement mismatch; run struct verify "
                "with the reported base register and offsets before treating "
                "this as allocator noise"
            ),
        }
    if bucket == "register-allocator":
        return {
            "source_actionability": "pcdump-proof-needed",
            "headline_tool": "mwcc-debug",
            "actionability_reason": (
                "instruction stream is close; collect pcdump-backed allocator "
                "evidence before source edits"
            ),
        }
    if bucket == "backend-ceiling":
        return {
            "source_actionability": "backend-ceiling",
            "headline_tool": "manual-inspection",
            "actionability_reason": (
                "backend-ceiling classification; review backend evidence and bank "
                "the row unless a credible source lever appears"
            ),
        }
    if bucket == "normalized-structural-near-match":
        return {
            "source_actionability": "normalized-structural-triage",
            "headline_tool": "manual-inspection",
            "actionability_reason": (
                "one to three normalized structural lines remain; inspect the "
                "residual before treating it as allocator-only or rebuilding source shape"
            ),
        }
    if bucket == "structural-reconstruction":
        if subcategory == "branch-or-control-flow-shape":
            return {
                "source_actionability": "structural-rebuild",
                "headline_tool": "control-flow-shape-search",
                "actionability_reason": (
                    "control-flow/source-shape mismatch; rebuild natural branch "
                    "or loop structure before local tuning"
                ),
            }
        if subcategory == "opcode-sequence-diff":
            return {
                "source_actionability": "opcode-reconstruction",
                "headline_tool": "opseq-mismatch-db",
                "actionability_reason": (
                    "generic opcode sequence mismatch; search similar opcode "
                    "patterns and matched functions for source shape"
                ),
            }
        if subcategory == "direct-inspection-needed":
            return {
                "source_actionability": "backend-ceiling",
                "headline_tool": "manual-inspection",
                "actionability_reason": (
                    "backend-ceiling classification; inspect manually and bank "
                    "when no current source lever is credible"
                ),
            }
    return {
        "source_actionability": "source-probe",
        "headline_tool": bucket,
        "actionability_reason": "heuristic taxonomy bucket has source-inspection next steps",
    }


def next_command(
    bucket: str,
    subcategory: str,
    candidate: FunctionCandidate,
    classification: dict[str, Any] | None = None,
) -> str:
    function = candidate.function
    source_path = f"src/{candidate.file_path}"
    if bucket == "signature-call-type":
        if candidate.file_path:
            return (
                f"melee-agent debug suggest signatures -f {function} "
                f"--source-file {source_path} --json"
            )
        return f"melee-agent debug suggest signatures -f {function} --json"
    if bucket == "inline-boundary":
        return (
            f"python tools/checkdiff.py {function} --compact && "
            f"melee-agent patterns inlines {source_path}"
        )
    if bucket in {"backend-ceiling", "normalized-structural-near-match"}:
        return f"python tools/checkdiff.py {function} --compact"
    if bucket == "structural-reconstruction":
        if subcategory == "branch-or-control-flow-shape":
            return (
                f"melee-agent debug mutate control-flow-shape-search -f {function} "
                f"--source-file {source_path} --compile-probes --json"
            )
        return (
            f"melee-agent extract get {function} && "
            f"python tools/checkdiff.py {function} --compact"
        )
    if bucket == "data-symbol-relocation":
        return f"python tools/checkdiff.py {function} --compact --no-name-magic"
    if bucket == "stack-local-layout":
        if subcategory == "same-frame-stack-slot-placement":
            return (
                f"python tools/checkdiff.py {function} --compact --pcdump <pcdump-if-available> && "
                f"melee-agent debug mutate lifetime-layout -f {function} --compile-probes"
            )
        return (
            f"melee-agent debug inspect frame-reservations -f {function} && "
            f"melee-agent debug suggest frame -f {function}"
        )
    if bucket == "known-small-pattern-candidate":
        return (
            f"python tools/checkdiff.py {function} --compact && "
            "melee-agent mismatch search '<opcode/type clue>'"
        )
    if bucket == "struct-offset-discrepancy":
        summary = offset_discrepancy_summary(classification or {})
        bases = [
            base
            for base in str(summary.get("offset_discrepancy_bases") or "").split(",")
            if base
        ]
        base_arg = f" --base {bases[0]}" if len(bases) == 1 else " --base <base-reg>"
        return (
            f"melee-agent struct verify {function}{base_arg} "
            f"--tu-src {source_path} --json"
        )
    if bucket == "register-allocator":
        return (
            "melee-agent debug dump setup && "
            f"melee-agent debug dump local {source_path} --function {function}"
        )
    return f"python tools/checkdiff.py {function} --compact"


def _name_magic_preflight_command(candidate: FunctionCandidate) -> list[str]:
    return [
        "melee-agent",
        "debug",
        "mutate",
        "name-magic-source-declarations",
        "-f",
        candidate.function,
        "--source-file",
        f"src/{candidate.file_path}",
        "--no-compile-probes",
        "--no-score-match-percent",
        "--json",
    ]


def default_name_magic_preflight_runner(
    candidate: FunctionCandidate,
    *,
    timeout: float | None = DEFAULT_NAME_MAGIC_PREFLIGHT_TIMEOUT,
) -> dict[str, Any] | None:
    source_path = REPO_ROOT / "src" / candidate.file_path
    if not source_path.exists():
        return None
    try:
        proc = subprocess.run(
            _name_magic_preflight_command(candidate),
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return parse_json_object(proc.stdout)
    except Exception:
        return None


def _struct_verify_command(
    candidate: FunctionCandidate,
    classification: dict[str, Any],
) -> list[str]:
    cmd = [
        "melee-agent",
        "struct",
        "verify",
        candidate.function,
    ]
    summary = offset_discrepancy_summary(classification)
    bases = [
        base
        for base in str(summary.get("offset_discrepancy_bases") or "").split(",")
        if base
    ]
    if len(bases) == 1:
        cmd.extend(["--base", bases[0]])
    cmd.extend(["--tu-src", f"src/{candidate.file_path}", "--json"])
    return cmd


def default_struct_verify_runner(
    candidate: FunctionCandidate,
    classification: dict[str, Any],
    *,
    timeout: float | None = DEFAULT_STRUCT_VERIFY_TIMEOUT,
) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            _struct_verify_command(candidate, classification),
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return parse_json_object(proc.stdout)
    except Exception:
        return None


def _string_join_unique(values: list[str]) -> str:
    return ",".join(dict.fromkeys(value for value in values if value))


def _struct_verify_skipped_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    raw_skipped = payload.get("skipped") or []
    if isinstance(raw_skipped, list):
        for item in raw_skipped:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                parts.append(f"{item[0]}: {item[1]}")
            elif item:
                parts.append(str(item))
    return "; ".join(parts)


def _verified_struct_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_findings = payload.get("findings") or []
    if not isinstance(raw_findings, list):
        return []
    verified = []
    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        if not finding.get("struct") or not finding.get("field"):
            continue
        if finding.get("conflict") or finding.get("ambiguous"):
            continue
        verified.append(finding)
    return verified


def _struct_verify_skip_unavailable(reason: str) -> bool:
    lowered = reason.lower()
    return (
        "checkdiff failed" in lowered
        or "source read failed" in lowered
        or "source unavailable" in lowered
    )


def summarize_struct_verify_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "struct_verify_status": "unavailable",
            "struct_verify_finding_count": 0,
            "struct_verify_verified_count": 0,
            "struct_verify_structs": "",
            "struct_verify_fields": "",
            "struct_verify_skipped": "",
            "struct_verify_reason": "struct verify unavailable",
        }

    raw_findings = payload.get("findings") or []
    findings = raw_findings if isinstance(raw_findings, list) else []
    verified = _verified_struct_findings(payload)
    skipped = _struct_verify_skipped_text(payload)
    if verified:
        status = "verified"
        reason = f"{len(verified)} verified named field finding(s)"
    elif skipped and _struct_verify_skip_unavailable(skipped):
        status = "unavailable"
        reason = skipped
    else:
        status = "unverified"
        reason = skipped or "no verified named field findings"

    return {
        "struct_verify_status": status,
        "struct_verify_finding_count": len(findings),
        "struct_verify_verified_count": len(verified),
        "struct_verify_structs": _string_join_unique(
            [str(finding.get("struct") or "") for finding in verified]
        ),
        "struct_verify_fields": _string_join_unique(
            [str(finding.get("field") or "") for finding in verified]
        ),
        "struct_verify_skipped": skipped,
        "struct_verify_reason": reason,
    }


def _payload_probe_count(payload: dict[str, Any]) -> int:
    raw_count = payload.get("probe_count")
    if raw_count is not None:
        return parse_int(raw_count)
    probes = payload.get("probes")
    if isinstance(probes, list):
        return len(probes)
    variants = payload.get("variants")
    if isinstance(variants, list):
        return len(variants)
    return 0


def _rehome_unverified_struct_without_data_pair(
    record: dict[str, Any],
    candidate: FunctionCandidate,
) -> bool:
    if (
        record.get("subcategory") != "unverified-struct-offset-displacement"
        or record.get("struct_verify_status") != "unverified"
        or record.get("name_magic_blocker")
        != "raw-diff-no-supported-data-symbol-pair"
        or parse_int(record.get("name_magic_probe_count")) != 0
    ):
        return False
    record["work_bucket"] = "struct-offset-discrepancy"
    record["subcategory"] = "unresolved-operand-displacement"
    record["confidence"] = "resolver-unverified"
    record.update(
        describe_actionability(
            record["work_bucket"],
            record["subcategory"],
        )
    )
    record["actionability_reason"] = (
        "struct verify did not resolve the displacement to a named field, "
        "and name-magic found no supported data-symbol pair; better struct/type "
        "inference is required"
    )
    record["next_command"] = next_command(
        record["work_bucket"],
        record["subcategory"],
        candidate,
        record.get("classification") or {},
    )
    return True


def attach_name_magic_preflight(
    record: dict[str, Any],
    candidate: FunctionCandidate,
    payload: dict[str, Any] | None,
) -> None:
    if payload is None:
        return
    stop_condition = payload.get("stop_condition")
    if not isinstance(stop_condition, dict):
        stop_condition = {}
    blocker = str(
        payload.get("blocker") or stop_condition.get("blocker") or ""
    ).strip()
    stop_kind = str(stop_condition.get("kind") or "").strip()
    reason = str(
        stop_condition.get("reason") or payload.get("reason") or blocker
    ).strip()
    probe_count = _payload_probe_count(payload)

    record["name_magic_blocker"] = blocker
    record["name_magic_stop_kind"] = stop_kind
    record["name_magic_probe_count"] = probe_count
    record["name_magic_reason"] = reason

    if _rehome_unverified_struct_without_data_pair(record, candidate):
        return
    if not blocker or probe_count > 0:
        return
    source_actionability = DATA_SYMBOL_NAME_MAGIC_REBUCKET_BLOCKERS.get(blocker)
    if source_actionability is None:
        return

    detail = reason or blocker
    record["source_actionability"] = source_actionability
    record["headline_tool"] = "checkdiff-name-magic"
    record["actionability_reason"] = (
        f"{blocker}; {detail}; no source-emitting name-magic candidate was "
        "produced by current tooling"
    )
    record["next_command"] = " ".join(_name_magic_preflight_command(candidate))


def attach_struct_verify_gate(
    record: dict[str, Any],
    candidate: FunctionCandidate,
    classification: dict[str, Any],
    payload: dict[str, Any] | None,
) -> None:
    summary = summarize_struct_verify_payload(payload)
    record.update(summary)
    status = summary["struct_verify_status"]
    if status == "verified":
        record["confidence"] = "resolver-verified"
        return
    if status == "unavailable":
        return

    record["work_bucket"] = "data-symbol-relocation"
    record["subcategory"] = "unverified-struct-offset-displacement"
    record["confidence"] = "resolver-rebucketed"
    actionability = describe_actionability(
        record["work_bucket"],
        record["subcategory"],
    )
    record.update(actionability)
    record["actionability_reason"] = (
        "raw struct offset discrepancy did not resolve to a non-ambiguous "
        f"named struct field; {summary['struct_verify_reason']}"
    )
    record["next_command"] = next_command(
        record["work_bucket"],
        record["subcategory"],
        candidate,
        classification,
    )


def _read_candidate_source(candidate: FunctionCandidate) -> str | None:
    try:
        return (REPO_ROOT / "src" / candidate.file_path).read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None


def _control_flow_asm_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(line) for line in value]


def _control_flow_unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _control_flow_materialization_summary(
    hints: list[dict[str, Any]],
) -> tuple[str, int, str, list[str]]:
    materializations = [
        hint.get("source_materialization")
        for hint in hints
        if isinstance(hint.get("source_materialization"), dict)
    ]
    if not materializations:
        return "no-materialization", 0, "", []
    probe_count = sum(
        parse_int(materialization.get("probe_count"))
        for materialization in materializations
    )
    blockers = _control_flow_unique_strings(
        [str(materialization.get("blocker") or "") for materialization in materializations]
    )
    reasons = _string_join_unique(
        [str(materialization.get("reason") or "") for materialization in materializations]
    )
    if any(materialization.get("status") == "materializable" for materialization in materializations):
        return "materializable", probe_count, reasons, blockers
    if any(materialization.get("status") == "terminal" for materialization in materializations):
        return "terminal", probe_count, reasons, blockers
    return "no-materialization", probe_count, reasons, blockers


def attach_control_flow_shape_enrichment(
    record: dict[str, Any],
    candidate: FunctionCandidate,
    payload: dict[str, Any],
) -> None:
    if (
        record.get("work_bucket") != "structural-reconstruction"
        or record.get("subcategory") != "branch-or-control-flow-shape"
    ):
        return

    record["control_flow_shape_validation_status"] = "not-run"
    record["control_flow_shape_validated_probe_count"] = 0
    try:
        from src.mwcc_debug.suggest_control_flow_shape import (
            analyze_control_flow_shape,
            annotate_source_materialization,
        )

        analysis = analyze_control_flow_shape(
            function=candidate.function,
            target_asm=_control_flow_asm_lines(payload.get("target_asm")),
            current_asm=_control_flow_asm_lines(payload.get("current_asm")),
            classification=payload.get("classification"),
            top=None,
        )
    except Exception as exc:
        record.update(
            {
                "control_flow_shape_analysis_status": "analysis-error",
                "control_flow_shape_hints": [],
                "control_flow_shape_hint_kinds": [],
                "control_flow_shape_source_preflight_status": "no-hints",
                "control_flow_shape_generated_probe_count": 0,
                "control_flow_shape_source_preflight_reason": str(exc),
                "control_flow_shape_blockers": [],
            }
        )
        return

    suggestions = analysis.get("suggestions")
    hints = [item for item in suggestions if isinstance(item, dict)] if isinstance(suggestions, list) else []
    record["control_flow_shape_hints"] = hints
    record["control_flow_shape_hint_kinds"] = _control_flow_unique_strings(
        [str(item.get("kind") or "") for item in hints]
    )
    record["control_flow_shape_analysis_status"] = (
        "heuristic-hints" if hints else "no-hints"
    )

    if not hints:
        record.update(
            {
                "control_flow_shape_source_preflight_status": "no-hints",
                "control_flow_shape_generated_probe_count": 0,
                "control_flow_shape_source_preflight_reason": "",
                "control_flow_shape_blockers": [],
            }
        )
        return

    source_text = _read_candidate_source(candidate)
    if source_text is None:
        record.update(
            {
                "control_flow_shape_source_preflight_status": "source-unavailable",
                "control_flow_shape_generated_probe_count": 0,
                "control_flow_shape_source_preflight_reason": "candidate source unavailable",
                "control_flow_shape_blockers": ["source-unavailable"],
            }
        )
        return

    try:
        annotate_source_materialization(
            analysis,
            function=candidate.function,
            source_text=source_text,
            max_probes_per_operator=1,
        )
    except Exception as exc:
        record.update(
            {
                "control_flow_shape_source_preflight_status": "preflight-error",
                "control_flow_shape_generated_probe_count": 0,
                "control_flow_shape_source_preflight_reason": str(exc),
                "control_flow_shape_blockers": ["source-preflight-error"],
            }
        )
        return

    status, probe_count, reason, blockers = _control_flow_materialization_summary(hints)
    record.update(
        {
            "control_flow_shape_source_preflight_status": status,
            "control_flow_shape_generated_probe_count": probe_count,
            "control_flow_shape_source_preflight_reason": reason,
            "control_flow_shape_blockers": blockers,
        }
    )


def default_frame_report_runner(
    candidate: FunctionCandidate,
) -> dict[str, Any] | None:
    cmd = [
        "melee-agent",
        "debug",
        "inspect",
        "frame-reservations",
        "-f",
        candidate.function,
        "--json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return parse_json_object(proc.stdout)
    except Exception:
        return None


def default_cast_audit_runner(candidate: FunctionCandidate) -> dict[str, Any]:
    source_path = REPO_ROOT / "src" / candidate.file_path
    if not source_path.exists():
        return {
            "status": "source-missing",
            "medium_plus_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
        }
    try:
        from src.mwcc_debug.cast_audit import audit_function_casts

        warnings = audit_function_casts(
            source_path.read_text(encoding="utf-8"),
            candidate.function,
        )
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "medium_plus_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
        }
    high_count = sum(1 for warning in warnings if warning.severity == "high")
    medium_count = sum(1 for warning in warnings if warning.severity == "medium")
    low_count = sum(1 for warning in warnings if warning.severity == "low")
    return {
        "status": "ok",
        "medium_plus_count": high_count + medium_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
    }


def frame_taxonomy_for_candidate(
    candidate: FunctionCandidate,
    classification: dict[str, Any],
    bucket: str,
    frame_report_runner: FrameReportRunner | None,
) -> dict[str, Any] | None:
    if bucket != "stack-local-layout":
        return None
    frame_report = None
    if frame_report_runner is not None:
        try:
            frame_report = frame_report_runner(candidate)
        except Exception:
            frame_report = None
    return classify_frame_taxonomy(
        candidate.function,
        classification=classification,
        source_path=f"src/{candidate.file_path}",
        frame_report=frame_report,
    )


def attach_frame_taxonomy(
    record: dict[str, Any],
    frame_taxonomy: dict[str, Any],
) -> None:
    record["frame_taxonomy"] = frame_taxonomy
    record["frame_cause"] = frame_taxonomy.get("cause")
    record["frame_raw_cause"] = frame_taxonomy.get("raw_cause")
    record["frame_verdict"] = frame_taxonomy.get("verdict")
    record["frame_raw_verdict"] = frame_taxonomy.get("raw_verdict")
    record["frame_evidence"] = frame_taxonomy.get("evidence")
    record["frame_probe_status"] = frame_taxonomy.get("probe_status")
    record["frame_attribution_status"] = frame_taxonomy.get("attribution_status")
    record["frame_source_object"] = frame_taxonomy.get("source_object")
    record["frame_source_object_symbol"] = frame_taxonomy.get("source_object_symbol")
    record["frame_next_command"] = frame_taxonomy.get("next_command")
    record["frame_reason"] = frame_taxonomy.get("reason")
    record["frame_match_relevance"] = frame_taxonomy.get("match_relevance")
    record["frame_match_relevance_reason"] = frame_taxonomy.get(
        "match_relevance_reason"
    )
    if frame_taxonomy.get("next_command"):
        record["next_command"] = frame_taxonomy["next_command"]


def default_decl_order_evaluator(
    candidate: FunctionCandidate,
    _record: dict[str, Any],
    *,
    timeout: float | None = DEFAULT_DECL_ORDER_TIMEOUT,
) -> dict[str, Any]:
    cmd = [
        "melee-agent",
        "debug",
        "mutate",
        "decl-orders",
        candidate.function,
        "--strategy",
        "all",
        "--json",
    ]
    try:
        with _DECL_ORDER_EVAL_LOCK:
            proc = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired as exc:
        return {
            "evaluated_status": "unevaluated: decl-orders timed out",
            "candidate_count": 0,
            "best_decl_delta": None,
            "best_ordering": "",
            "stdout_tail": _tail_text(exc.output),
            "stderr_tail": _tail_text(exc.stderr)
            or f"decl-orders timed out after {_format_timeout(exc.timeout)}",
        }
    if proc.returncode != 0:
        return {
            "evaluated_status": "unevaluated: decl-orders command failed",
            "candidate_count": 0,
            "best_decl_delta": None,
            "best_ordering": "",
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:],
        }
    try:
        payload = parse_json_object(proc.stdout)
    except Exception as exc:
        status = "unevaluated: decl-orders emitted no JSON"
        if "no candidate orderings" in proc.stdout.lower():
            status = "no-candidates"
        return {
            "evaluated_status": status,
            "candidate_count": 0,
            "best_decl_delta": None,
            "best_ordering": "",
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:] or str(exc),
        }
    return summarize_decl_order_payload(payload)


def summarize_decl_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rounds = payload.get("rounds") or []
    results: list[dict[str, Any]] = []
    for round_payload in rounds:
        for result in round_payload.get("results") or []:
            if isinstance(result, dict):
                results.append(result)
    candidate_count = len(results)
    skipped = [result for result in results if result.get("skipped")]
    scored = [
        result for result in results
        if result.get("match_pct") is not None and result.get("delta") is not None
    ]
    best_result = max(
        scored,
        key=lambda row: parse_float(row.get("delta")),
        default=None,
    )
    best_delta = (
        parse_float(best_result.get("delta"))
        if best_result is not None
        else None
    )
    best_ordering = str(best_result.get("label") or "") if best_result else ""
    if candidate_count == 0:
        status = "no-candidates"
    elif scored:
        status = "evaluated"
    elif skipped and len(skipped) == candidate_count:
        reasons = " ".join(str(item.get("skip_reason") or "") for item in skipped)
        status = (
            "no-freedom-init-dependency"
            if "depends on" in reasons
            else "unevaluated: all candidates skipped"
        )
    else:
        status = "unevaluated: no scored candidates"
    return {
        "evaluated_status": status,
        "candidate_count": candidate_count,
        "evaluated_candidate_count": len(scored),
        "skipped_count": len(skipped),
        "best_decl_delta": best_delta,
        "best_ordering": best_ordering,
        "baseline_pct": payload.get("baseline_pct"),
        "best_pct": payload.get("best_pct"),
        "scope": payload.get("scope", ""),
        "selected_scope_reason": payload.get("selected_scope_reason", ""),
    }


def should_evaluate_decl_orders(
    candidate: FunctionCandidate,
    bucket: str,
    subcategory: str,
) -> bool:
    return (
        bucket == "stack-local-layout"
        and subcategory == "same-frame-stack-slot-placement"
        and candidate.match_percent >= 99.0
    )


def attach_decl_order_summary(
    record: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    record["decl_order_summary"] = summary
    record["decl_order_evaluated_status"] = summary.get("evaluated_status", "")
    record["decl_order_candidate_count"] = summary.get("candidate_count", 0)
    record["decl_order_best_delta"] = summary.get("best_decl_delta")
    record["decl_order_best_ordering"] = summary.get("best_ordering", "")


def classify_candidate(
    candidate: FunctionCandidate,
    runner: CheckdiffRunner,
    decl_order_evaluator: DeclOrderEvaluator | None = default_decl_order_evaluator,
    frame_report_runner: FrameReportRunner | None = default_frame_report_runner,
    cast_audit_runner: CastAuditRunner | None = default_cast_audit_runner,
    name_magic_preflight_runner: NameMagicPreflightRunner | None = (
        default_name_magic_preflight_runner
    ),
    struct_verify_runner: StructVerifyRunner | None = default_struct_verify_runner,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    started = time.perf_counter()
    try:
        returncode, stdout, stderr = runner(candidate.function)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - started
        stdout_tail = _tail_text(exc.output)
        stderr_tail = _tail_text(exc.stderr)
        return None, {
            "function": candidate.function,
            "error": "checkdiff_timeout",
            "file_path": candidate.file_path,
            "message": f"checkdiff timed out after {_format_timeout(exc.timeout)}",
            "returncode": 124,
            "elapsed_sec": round(elapsed, 3),
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }
    elapsed = time.perf_counter() - started
    try:
        payload = parse_checkdiff_stdout(stdout)
    except Exception as exc:
        return None, {
            "function": candidate.function,
            "error": "json_decode",
            "file_path": candidate.file_path,
            "message": stderr.strip() or str(exc),
            "returncode": returncode,
            "stdout_tail": stdout[-1000:],
            "stderr_tail": stderr[-1000:],
        }

    classification = payload.get("classification") or {}
    primary = classification.get("primary") or "unknown"
    matched = payload.get("match") is True or primary == "instruction-identical"
    expected_returncode = 0 if matched else 1
    has_traceback = "Traceback (most recent call last):" in stderr
    if returncode != expected_returncode or has_traceback:
        if has_traceback:
            message = stderr.strip() or "checkdiff emitted an unhandled traceback"
        else:
            message = (
                f"checkdiff exited {returncode}; expected exit "
                f"{expected_returncode} for the emitted JSON verdict"
            )
        return None, {
            "function": candidate.function,
            "error": "checkdiff_crash",
            "file_path": candidate.file_path,
            "message": message,
            "returncode": returncode,
            "elapsed_sec": round(elapsed, 3),
            "stdout_tail": stdout[-1000:],
            "stderr_tail": stderr[-1000:],
        }
    if matched:
        return None, None
    cast_audit = None
    if primary == "signature-type-mismatch" and cast_audit_runner is not None:
        try:
            cast_audit = cast_audit_runner(candidate)
        except Exception as exc:
            cast_audit = {
                "status": "error",
                "message": str(exc),
                "medium_plus_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            }
    bucket, subcategory, known_small = classify_bucket(
        candidate,
        payload,
        cast_audit=cast_audit,
    )
    semantic_route = bucket == "normalized-structural-near-match" or (
        bucket == "structural-reconstruction"
        and subcategory == "opcode-sequence-diff"
    )
    truth_gate = classification.get("structural_truth_gate") or {}
    opcode_delta_evidence = (
        derive_opcode_delta_evidence(
            payload.get("target_asm"),
            payload.get("current_asm"),
            normalized_diff_lines=(
                truth_gate.get("normalized_diff_lines")
                if bucket == "normalized-structural-near-match"
                else None
            ),
        )
        if semantic_route
        else {}
    )
    root_cause_keys = derive_root_cause_keys(classification)
    bss_root_cause = classification.get("bss_anchor_relocations")
    has_structured_root_cause_pairs = (
        isinstance(bss_root_cause, dict)
        and isinstance(bss_root_cause.get("pairs"), list)
    )
    frame_taxonomy = frame_taxonomy_for_candidate(
        candidate,
        classification,
        bucket,
        frame_report_runner,
    )
    actionability = describe_actionability(
        bucket,
        subcategory,
        frame_taxonomy=frame_taxonomy,
    )
    record = {
        "ok": True,
        "function": candidate.function,
        "address": candidate.address,
        "file_path": candidate.file_path,
        "object_status": candidate.object_status,
        "size_bytes": candidate.size_bytes,
        "match": candidate.match_percent / 100.0,
        "match_percent": candidate.match_percent,
        "match_tier": match_tier(candidate.match_percent),
        "effective_match": False,
        "classification": classification,
        "primary": primary,
        "reasons": classification.get("reasons") or [],
        "structural": payload.get("structural") or {},
        "reference_lines": payload.get("reference_lines"),
        "current_lines": payload.get("current_lines"),
        "work_bucket": bucket,
        "subcategory": subcategory,
        **opcode_delta_evidence,
        **(
            {"root_cause_keys": root_cause_keys}
            if has_structured_root_cause_pairs
            else {}
        ),
        "known_small_pattern_candidate": known_small,
        "cast_audit": cast_audit,
        "cast_audit_status": (cast_audit or {}).get("status"),
        "cast_medium_plus_count": parse_int((cast_audit or {}).get("medium_plus_count")),
        **actionability,
        "confidence": "heuristic",
        "elapsed_sec": round(elapsed, 3),
        "stderr_tail": stderr[-1000:],
        "next_command": next_command(bucket, subcategory, candidate),
    }
    offset_summary = offset_discrepancy_summary(classification)
    if offset_summary["offset_discrepancy_count"]:
        record.update(offset_summary)
        record["next_command"] = next_command(
            bucket,
            subcategory,
            candidate,
            classification,
        )
    if frame_taxonomy is not None:
        attach_frame_taxonomy(record, frame_taxonomy)
    if (
        record["work_bucket"] == "struct-offset-discrepancy"
        and struct_verify_runner is not None
    ):
        try:
            struct_verify_payload = struct_verify_runner(candidate, classification)
        except Exception:
            struct_verify_payload = None
        attach_struct_verify_gate(record, candidate, classification, struct_verify_payload)
    if (
        record["work_bucket"] == "data-symbol-relocation"
        and name_magic_preflight_runner is not None
    ):
        try:
            name_magic_payload = name_magic_preflight_runner(candidate)
        except Exception:
            name_magic_payload = None
        attach_name_magic_preflight(record, candidate, name_magic_payload)
    attach_control_flow_shape_enrichment(record, candidate, payload)
    if (
        decl_order_evaluator is not None
        and should_evaluate_decl_orders(candidate, bucket, subcategory)
    ):
        with _DECL_ORDER_EVAL_LOCK:
            source_snapshot = _snapshot_candidate_source(candidate)
            try:
                decl_order_summary = decl_order_evaluator(candidate, record)
            finally:
                _restore_candidate_source(source_snapshot)
        attach_decl_order_summary(record, decl_order_summary)
    return normalize_root_cause_record(
        normalize_semantic_delta_record(
            normalize_routing_record(record, preserve_existing=False)
        )
    ), None


_DEPRECATED_FRAME_KEYS = {"closability_tier", "frame_closability_tier"}


def _sanitize_deprecated_frame_keys(value: Any) -> Any:
    if isinstance(value, dict):
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(_sanitize_deprecated_frame_keys(row), separators=(",", ":"))
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _taxonomy_tool_sha256() -> str:
    digest = hashlib.sha256()
    for path in [Path(__file__), Path(attempt_evidence.__file__)]:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def apply_terminal_attempt_evidence(
    records: list[dict[str, Any]],
    *,
    attempt_ledger_path: Path | None,
) -> list[dict[str, Any]]:
    evidence = load_terminal_attempt_evidence(attempt_ledger_path)
    if not evidence:
        return records
    current_tool_fingerprints = {"taxonomy_tool_sha256": _taxonomy_tool_sha256()}
    overlaid: list[dict[str, Any]] = []
    for record in records:
        updated = apply_terminal_attempt_overlay(
            record,
            evidence,
            current_tool_fingerprints=current_tool_fingerprints,
        )
        if record.get("function") not in evidence:
            overlaid.append(record)
            continue
        merged = dict(record)
        for field in (
            "source_actionability",
            "headline_tool",
            "actionability_reason",
            "next_command",
            *TERMINAL_ATTEMPT_FIELDS,
        ):
            if field in updated:
                merged[field] = updated[field]
        overlaid.append(merged)
    return overlaid


def attach_normalized_trigger_cluster_sizes(records: list[dict[str, Any]]) -> None:
    eligible = [
        row
        for row in records
        if row.get("work_bucket") == "normalized-structural-near-match"
        and row.get("normalized_trigger_signature_status") == "available"
        and isinstance(row.get("normalized_trigger_signature"), str)
        and row["normalized_trigger_signature"]
    ]
    counts = Counter(row["normalized_trigger_signature"] for row in eligible)
    for row in eligible:
        row["normalized_trigger_cluster_size"] = counts[
            row["normalized_trigger_signature"]
        ]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "match_percent",
        "function",
        "work_bucket",
        "primary",
        "subcategory",
        "primary_intervention",
        "secondary_signals",
        "evidence_stage",
        "blocker_families",
        "opcode_delta_signature_status",
        "opcode_delta_signature",
        "semantic_delta_families",
        "opcode_edit_direction",
        "normalized_trigger_signature_status",
        "normalized_trigger_signature",
        "normalized_trigger_family",
        "normalized_trigger_cluster_size",
        "root_cause_keys",
        "max_root_cause_impact",
        "offset_discrepancy_count",
        "offset_discrepancy_bases",
        "offset_discrepancy_disps",
        "offset_discrepancy_opcodes",
        "struct_verify_status",
        "struct_verify_finding_count",
        "struct_verify_verified_count",
        "struct_verify_structs",
        "struct_verify_fields",
        "struct_verify_skipped",
        "struct_verify_reason",
        "frame_cause",
        "frame_verdict",
        "frame_evidence",
        "frame_probe_status",
        "frame_match_relevance",
        "frame_match_relevance_reason",
        "frame_attribution_status",
        "frame_source_object_symbol",
        "cast_audit_status",
        "cast_medium_plus_count",
        "source_actionability",
        "headline_tool",
        "actionability_reason",
        *CONTROL_FLOW_SHAPE_SUMMARY_FIELDS,
        *TERMINAL_ATTEMPT_FIELDS,
        "name_magic_blocker",
        "name_magic_stop_kind",
        "name_magic_probe_count",
        "name_magic_reason",
        "file_path",
        "size_bytes",
        "next_command",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(_compact_list_fields(row))


def write_queue(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "function",
        "work_bucket",
        "match_percent",
        "primary",
        "subcategory",
        "primary_intervention",
        "secondary_signals",
        "evidence_stage",
        "blocker_families",
        "opcode_delta_signature_status",
        "opcode_delta_signature",
        "semantic_delta_families",
        "opcode_edit_direction",
        "normalized_trigger_signature_status",
        "normalized_trigger_signature",
        "normalized_trigger_family",
        "normalized_trigger_cluster_size",
        "root_cause_keys",
        "max_root_cause_impact",
        "offset_discrepancy_count",
        "offset_discrepancy_bases",
        "offset_discrepancy_disps",
        "offset_discrepancy_opcodes",
        "struct_verify_status",
        "struct_verify_finding_count",
        "struct_verify_verified_count",
        "struct_verify_structs",
        "struct_verify_fields",
        "struct_verify_skipped",
        "struct_verify_reason",
        "frame_cause",
        "frame_verdict",
        "frame_evidence",
        "frame_probe_status",
        "frame_match_relevance",
        "frame_match_relevance_reason",
        "frame_attribution_status",
        "frame_source_object_symbol",
        "cast_audit_status",
        "cast_medium_plus_count",
        "source_actionability",
        "headline_tool",
        "actionability_reason",
        *CONTROL_FLOW_SHAPE_SUMMARY_FIELDS,
        *TERMINAL_ATTEMPT_FIELDS,
        "decl_order_best_delta",
        "decl_order_best_ordering",
        "decl_order_evaluated_status",
        "decl_order_candidate_count",
        "name_magic_blocker",
        "name_magic_stop_kind",
        "name_magic_probe_count",
        "name_magic_reason",
        "file_path",
        "frame_next_command",
        "next_command",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore",
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            out = _compact_list_fields(row)
            out["match_percent"] = f"{parse_float(row.get('match_percent')):.5f}"
            if row.get("decl_order_best_delta") is not None:
                out["decl_order_best_delta"] = (
                    f"{parse_float(row.get('decl_order_best_delta')):.5f}"
                )
            writer.writerow(out)


def _compact_list_fields(row: dict[str, Any]) -> dict[str, Any]:
    out = _sanitize_deprecated_frame_keys(row)
    for field in (
        "secondary_signals",
        "blocker_families",
        "semantic_delta_families",
        "root_cause_keys",
        "control_flow_shape_hint_kinds",
        "control_flow_shape_blockers",
    ):
        if isinstance(out.get(field), list):
            out[field] = json.dumps(out[field], separators=(",", ":"))
    return out


def write_control_flow_shape_queues(
    queues: Path,
    records: list[dict[str, Any]],
) -> None:
    eligible = [
        row
        for row in records
        if row.get("work_bucket") == "structural-reconstruction"
        and row.get("subcategory") == "branch-or-control-flow-shape"
    ]
    prefix = "structural-reconstruction.control-flow-shape"
    for kind in CONTROL_FLOW_SHAPE_HINT_KINDS:
        rows = [
            row
            for row in eligible
            if isinstance(row.get("control_flow_shape_hint_kinds"), list)
            and kind in row["control_flow_shape_hint_kinds"]
        ]
        write_queue(queues / f"{prefix}.{kind}.tsv", rows)
    for status in ("materializable", "terminal"):
        rows = [
            row
            for row in eligible
            if row.get("control_flow_shape_source_preflight_status") == status
        ]
        write_queue(queues / f"{prefix}.{status}.tsv", rows)


def write_opcode_sequence_queue(queues: Path, records: list[dict[str, Any]]) -> None:
    rows = [
        row
        for row in records
        if row.get("work_bucket") == "structural-reconstruction"
        and row.get("subcategory") == "opcode-sequence-diff"
    ]
    write_queue(queues / "structural-reconstruction.opcode-sequence-diff.tsv", rows)


def write_semantic_opcode_family_queues(
    queues: Path, records: list[dict[str, Any]]
) -> None:
    eligible = [
        row
        for row in records
        if row.get("work_bucket") == "structural-reconstruction"
        and row.get("subcategory") == "opcode-sequence-diff"
    ]
    for family in SEMANTIC_DELTA_FAMILY_ORDER:
        write_queue(
            queues / f"structural-reconstruction.opcode-family.{family}.tsv",
            [
                row
                for row in eligible
                if isinstance(row.get("semantic_delta_families"), list)
                and family in row["semantic_delta_families"]
            ],
        )


def normalized_trigger_cluster_sort_key(
    row: dict[str, Any],
) -> tuple[int, str, float, str]:
    return (
        -parse_int(row.get("normalized_trigger_cluster_size")),
        str(row.get("normalized_trigger_signature") or ""),
        -parse_float(row.get("match_percent")),
        str(row.get("function") or ""),
    )


def write_normalized_trigger_cluster_queue(
    queues: Path, records: list[dict[str, Any]]
) -> None:
    rows = [
        row
        for row in records
        if row.get("work_bucket") == "normalized-structural-near-match"
        and parse_int(row.get("normalized_trigger_cluster_size")) >= 2
    ]
    rows.sort(key=normalized_trigger_cluster_sort_key)
    write_queue(queues / "normalized-structural-near-match.trigger-clusters.tsv", rows)


def write_routing_stage_queues(
    queues: Path, records: list[dict[str, Any]]
) -> None:
    for stage in ROUTING_STAGE_QUEUE_VALUES:
        write_queue(
            queues / f"routing.{stage}.tsv",
            [row for row in records if row.get("evidence_stage") == stage],
        )


def write_data_symbol_blocker_subqueues(
    queues: Path,
    records: list[dict[str, Any]],
) -> None:
    for blocker, source_actionability in DATA_SYMBOL_NAME_MAGIC_REBUCKET_BLOCKERS.items():
        rows = [
            row
            for row in records
            if row.get("work_bucket") == "data-symbol-relocation"
            and row.get("source_actionability") == source_actionability
            and row.get("name_magic_blocker") == blocker
        ]
        write_queue(queues / f"data-symbol-relocation.{blocker}.tsv", rows)


def write_repeated_bss_root_cause_queue(
    queues: Path, records: list[dict[str, Any]]
) -> None:
    rows = [
        row
        for row in records
        if row.get("work_bucket") == "data-symbol-relocation"
        and row.get("subcategory") == "bss-section-anchor-ceiling"
        and parse_int(row.get("max_root_cause_impact")) >= 2
    ]
    rows.sort(
        key=lambda row: (
            -parse_int(row.get("max_root_cause_impact")),
            str((row.get("root_cause_keys") or [""])[0]),
            -parse_float(row.get("match_percent")),
            str(row.get("function") or ""),
        )
    )
    write_queue(queues / "root-cause.bss-symbol.repeated.tsv", rows)


def write_error_queue(path: Path, errors: list[dict[str, Any]]) -> None:
    fields = ["function", "error", "file_path", "message"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore",
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(errors)


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def write_summary(
    path: Path,
    *,
    report_non100_count: int,
    records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    bucket_counts = count_by(records, "work_bucket")
    primary_counts = count_by(records, "primary")
    tier_counts = count_by(records, "match_tier")
    frame_probe_status_counts = count_by(
        [row for row in records if row.get("frame_probe_status")],
        "frame_probe_status",
    )
    intervention_counts = count_by(records, "primary_intervention")
    evidence_stage_counts = count_by(records, "evidence_stage")
    root_cause_counts: Counter[str] = Counter()
    for row in records:
        if (
            row.get("work_bucket") != "data-symbol-relocation"
            or row.get("subcategory") != "bss-section-anchor-ceiling"
        ):
            continue
        keys = row.get("root_cause_keys")
        if isinstance(keys, list):
            root_cause_counts.update(
                {
                    key
                    for key in keys
                    if isinstance(key, str) and key.strip()
                }
            )

    lines = [
        "# Function Mismatch Taxonomy Inventory",
        "",
        "Generated from `build/GALE01/report.json` and a read-only `checkdiff --no-build --no-name-magic` pass.",
        "",
        "## Population",
        "| Population | Count |",
        "| --- | --- |",
        f"| Report unmatched functions | {report_non100_count} |",
        f"| Successfully classified by checkdiff | {len(records)} |",
        f"| Checkdiff extraction errors | {len(errors)} |",
        "| Report-only not extract-backed | 0 |",
        "| DB-completed/excluded extract-backed non-100% | 0 |",
        "",
        "## Work Buckets",
        "| Bucket | Count |",
        "| --- | --- |",
    ]
    for bucket in BUCKET_ORDER:
        lines.append(f"| {bucket} | {bucket_counts.get(bucket, 0)} |")
    lines.extend(
        [
            "",
            "## Primary Interventions",
            "| Primary intervention | Count |",
            "| --- | --- |",
        ]
    )
    for intervention in PRIMARY_INTERVENTION_ORDER:
        lines.append(
            f"| {intervention} | {intervention_counts.get(intervention, 0)} |"
        )
    lines.extend(
        [
            "",
            "## Evidence Stages",
            "| Evidence stage | Count |",
            "| --- | --- |",
        ]
    )
    for stage in EVIDENCE_STAGE_ORDER:
        lines.append(f"| {stage} | {evidence_stage_counts.get(stage, 0)} |")
    repeated_root_causes = [
        (key, count)
        for key, count in sorted(
            root_cause_counts.items(), key=lambda item: (-item[1], item[0])
        )
        if count >= 2
    ]
    if repeated_root_causes:
        lines.extend(
            [
                "",
                "## Repeated BSS Root-Cause Keys",
                "| Shared root-cause key | Affected rows |",
                "| --- | --- |",
            ]
        )
        for key, count in repeated_root_causes:
            lines.append(f"| {key} | {count} |")
    lines.extend(["", "## Primary Checkdiff Classifications", "| Primary | Count |", "| --- | --- |"])
    for primary, count in sorted(primary_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {primary} | {count} |")
    lines.extend(["", "## Match Tiers", "| Tier | Classified |", "| --- | --- |"])
    for tier in TIER_ORDER:
        lines.append(f"| {tier} | {tier_counts.get(tier, 0)} |")
    if frame_probe_status_counts:
        lines.extend(
            [
                "",
                "## Stack Frame Probe Status",
                "| Probe status | Classified |",
                "| --- | --- |",
            ]
        )
        for status, count in sorted(frame_probe_status_counts.items()):
            lines.append(f"| {status} | {count} |")
    lines.extend(["", "## High-ROI Queues"])
    for bucket in BUCKET_ORDER:
        lines.append(f"- `build/function-taxonomy/queues/{bucket}.tsv`")
    for blocker in DATA_SYMBOL_NAME_MAGIC_REBUCKET_BLOCKERS:
        lines.append(
            "- "
            f"`build/function-taxonomy/queues/data-symbol-relocation.{blocker}.tsv`"
        )
    for kind in CONTROL_FLOW_SHAPE_HINT_KINDS:
        lines.append(
            "- `build/function-taxonomy/queues/"
            f"structural-reconstruction.control-flow-shape.{kind}.tsv`"
        )
    for family in SEMANTIC_DELTA_FAMILY_ORDER:
        lines.append(
            "- `build/function-taxonomy/queues/"
            f"structural-reconstruction.opcode-family.{family}.tsv`"
        )
    lines.extend(
        [
            "- `build/function-taxonomy/queues/routing.materializable.tsv`",
            "- `build/function-taxonomy/queues/routing.validated.tsv`",
            "- `build/function-taxonomy/queues/routing.blocked.tsv`",
            "- `build/function-taxonomy/queues/"
            "structural-reconstruction.opcode-sequence-diff.tsv`",
            "- `build/function-taxonomy/queues/"
            "normalized-structural-near-match.trigger-clusters.tsv`",
            "- `build/function-taxonomy/queues/"
            "root-cause.bss-symbol.repeated.tsv`",
            "- `build/function-taxonomy/queues/"
            "structural-reconstruction.control-flow-shape.materializable.tsv`",
            "- `build/function-taxonomy/queues/"
            "structural-reconstruction.control-flow-shape.terminal.tsv`",
            "- `build/function-taxonomy/queues/checkdiff-errors.tsv`",
            "- `build/function-taxonomy/queues/report-only-not-extract-backed.tsv`",
            "- `build/function-taxonomy/queues/db-completed-extract-backed-non100.tsv`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_placeholder_auxiliary_files(output_dir: Path) -> None:
    write_jsonl(output_dir / "report-only-nonextract-backed.jsonl", [])
    write_jsonl(output_dir / "db-completed-extract-backed-non100.jsonl", [])
    queues = output_dir / "queues"
    for name in [
        "report-only-not-extract-backed.tsv",
        "db-completed-extract-backed-non100.tsv",
    ]:
        (queues / name).write_text("match_percent\tfunction\tfile_path\tobject_status\n", encoding="utf-8")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _base_run_status(
    *,
    report_path: Path,
    output_dir: Path,
    candidates: list[FunctionCandidate],
    attempted: list[FunctionCandidate],
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": RUN_STATUS_SCHEMA_VERSION,
        "status": "running",
        "started_at": started_at,
        "report_path": str(report_path),
        "output_dir": str(output_dir),
        "report_non100_count": len(candidates),
        "attempted_count": len(attempted),
    }


def _initial_run_status(
    *,
    report_path: Path,
    output_dir: Path,
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": RUN_STATUS_SCHEMA_VERSION,
        "status": "running",
        "started_at": started_at,
        "report_path": str(report_path),
        "output_dir": str(output_dir),
        "report_non100_count": 0,
        "attempted_count": 0,
    }


def write_run_status(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(output_dir / RUN_STATUS_FILENAME, payload)


def _mark_run_failed(
    output_dir: Path,
    run_status: dict[str, Any],
    exc: BaseException,
    *,
    records: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> None:
    failed_status = dict(run_status)
    failed_status.update(
        {
            "status": "failed",
            "failed_at": _utc_now_iso(),
            "error": str(exc) or exc.__class__.__name__,
            "error_type": exc.__class__.__name__,
            "classified_count": len(records or []),
            "error_count": len(errors or []),
        }
    )
    write_run_status(output_dir, failed_status)


def generate_inventory(
    report_path: Path | str = DEFAULT_REPORT,
    output_dir: Path | str = DEFAULT_OUTPUT,
    *,
    checkdiff_runner: CheckdiffRunner = default_checkdiff_runner,
    decl_order_evaluator: DeclOrderEvaluator | None = default_decl_order_evaluator,
    frame_report_runner: FrameReportRunner | None = default_frame_report_runner,
    cast_audit_runner: CastAuditRunner | None = default_cast_audit_runner,
    name_magic_preflight_runner: NameMagicPreflightRunner | None = (
        default_name_magic_preflight_runner
    ),
    struct_verify_runner: StructVerifyRunner | None = default_struct_verify_runner,
    workers: int = 4,
    limit: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_interval: float | None = DEFAULT_PROGRESS_INTERVAL,
    attempt_ledger_path: Path | str | None = None,
    include_terminal_attempts: bool = True,
) -> InventoryResult:
    report_path = Path(report_path).resolve()
    output_dir = Path(output_dir).resolve()
    resolved_attempt_ledger_path = (
        Path(attempt_ledger_path).resolve() if attempt_ledger_path is not None else None
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "queues").mkdir(exist_ok=True)
    started_at = _utc_now_iso()
    run_status = _initial_run_status(
        report_path=report_path,
        output_dir=output_dir,
        started_at=started_at,
    )
    write_run_status(output_dir, run_status)
    try:
        candidates = load_report_candidates(report_path)
    except BaseException as exc:
        _mark_run_failed(output_dir, run_status, exc)
        raise
    attempted = candidates[:limit] if limit is not None else candidates

    run_status = _base_run_status(
        report_path=report_path,
        output_dir=output_dir,
        candidates=candidates,
        attempted=attempted,
        started_at=started_at,
    )
    write_run_status(output_dir, run_status)

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        max_workers = max(1, workers)
        pending: dict[
            Future[tuple[dict[str, Any] | None, dict[str, Any] | None]],
            FunctionCandidate,
        ] = {}
        candidate_iter = iter(attempted)
        last_progress_at = 0.0

        def emit_progress(event: dict[str, Any]) -> None:
            if progress_callback is not None:
                progress_callback(event)

        def emit_periodic_progress() -> None:
            completed_count = len(records) + len(errors)
            active_functions = [candidate.function for candidate in pending.values()]
            event = {
                "event": "inventory_progress",
                "attempted_count": len(attempted),
                "submitted_count": completed_count + len(pending),
                "completed_count": completed_count,
                "classified_count": len(records),
                "error_count": len(errors),
                "pending_count": len(pending),
                "remaining_count": max(
                    0,
                    len(attempted) - completed_count - len(pending),
                ),
                "active_functions": active_functions,
            }
            progress_status = dict(run_status)
            progress_status.update(
                {
                    "status": "running",
                    "updated_at": _utc_now_iso(),
                    "submitted_count": event["submitted_count"],
                    "completed_count": completed_count,
                    "classified_count": len(records),
                    "error_count": len(errors),
                    "pending_count": len(pending),
                    "active_functions": active_functions,
                }
            )
            write_run_status(output_dir, progress_status)
            emit_progress(event)

        def emit_progress_if_due() -> None:
            nonlocal last_progress_at
            if progress_interval is None or progress_interval <= 0:
                return
            now = time.monotonic()
            if now - last_progress_at < progress_interval:
                return
            emit_periodic_progress()
            last_progress_at = now

        def submit_next(executor: ThreadPoolExecutor) -> None:
            try:
                candidate = next(candidate_iter)
            except StopIteration:
                return
            future = executor.submit(
                classify_candidate,
                candidate,
                checkdiff_runner,
                decl_order_evaluator,
                frame_report_runner,
                cast_audit_runner,
                name_magic_preflight_runner,
                struct_verify_runner,
            )
            pending[future] = candidate
            emit_progress({"event": "candidate_submitted", "function": candidate.function})

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for _ in range(min(max_workers, len(attempted))):
                submit_next(executor)
            while pending:
                wait_timeout = (
                    None
                    if progress_interval is None or progress_interval <= 0
                    else progress_interval
                )
                done, _not_done = wait(
                    pending,
                    timeout=wait_timeout,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    emit_periodic_progress()
                    last_progress_at = time.monotonic()
                    continue
                for future in done:
                    candidate = pending.pop(future)
                    try:
                        record, error = future.result()
                    except BaseException as exc:
                        _mark_run_failed(
                            output_dir,
                            run_status,
                            exc,
                            records=records,
                            errors=errors,
                        )
                        for remaining in pending:
                            remaining.cancel()
                        raise
                    if record is not None:
                        records.append(record)
                    if error is not None:
                        errors.append(error)
                    emit_progress(
                        {
                            "event": "candidate_done",
                            "function": candidate.function,
                            "classified_count": len(records),
                            "error_count": len(errors),
                        }
                    )
                    submit_next(executor)
                emit_progress_if_due()

        if include_terminal_attempts:
            records = apply_terminal_attempt_evidence(
                records,
                attempt_ledger_path=resolved_attempt_ledger_path,
            )

        attach_normalized_trigger_cluster_sizes(records)
        attach_root_cause_impacts(records)
        records = [
            normalize_root_cause_record(
                normalize_semantic_delta_record(
                    normalize_routing_record(record, preserve_existing=False)
                )
            )
            for record in records
        ]

        records.sort(key=lambda row: (-parse_float(row.get("match_percent")), row.get("function", "")))
        errors.sort(key=lambda row: row.get("function", ""))

        queues = output_dir / "queues"

        write_jsonl(output_dir / "taxonomy.records.jsonl", records)
        write_csv(output_dir / "taxonomy.records.csv", records)
        write_jsonl(output_dir / "checkdiff-errors.jsonl", errors)
        write_placeholder_auxiliary_files(output_dir)

        for bucket in BUCKET_ORDER:
            bucket_rows = [row for row in records if row.get("work_bucket") == bucket]
            write_queue(queues / f"{bucket}.tsv", bucket_rows)
        write_data_symbol_blocker_subqueues(queues, records)
        write_repeated_bss_root_cause_queue(queues, records)
        write_control_flow_shape_queues(queues, records)
        write_opcode_sequence_queue(queues, records)
        write_semantic_opcode_family_queues(queues, records)
        write_normalized_trigger_cluster_queue(queues, records)
        write_routing_stage_queues(queues, records)
        write_error_queue(queues / "checkdiff-errors.tsv", errors)
        write_summary(
            output_dir / "summary.md",
            report_non100_count=len(candidates),
            records=records,
            errors=errors,
        )
        completed_status = dict(run_status)
        completed_status.update(
            {
                "status": "completed",
                "completed_at": _utc_now_iso(),
                "classified_count": len(records),
                "error_count": len(errors),
            }
        )
        write_run_status(output_dir, completed_status)
    except BaseException as exc:
        current_status = {}
        status_path = output_dir / RUN_STATUS_FILENAME
        try:
            current_status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        if current_status.get("status") != "failed":
            _mark_run_failed(
                output_dir,
                run_status,
                exc,
                records=records,
                errors=errors,
            )
        raise

    return InventoryResult(
        report_non100_count=len(candidates),
        attempted_count=len(attempted),
        classified_count=len(records),
        error_count=len(errors),
        output_dir=output_dir,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate function taxonomy JSONL/TSV artifacts from report.json."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="Path to build/GALE01/report.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output directory for function-taxonomy artifacts.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent checkdiff subprocesses.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N report mismatch/audit candidate functions.",
    )
    parser.add_argument(
        "--skip-decl-order-eval",
        action="store_true",
        help="Skip bounded decl-orders evaluation for >=99%% stack-local-layout rows.",
    )
    parser.add_argument(
        "--skip-frame-report-attribution",
        action="store_true",
        help=(
            "Skip best-effort pcdump-backed frame-reservation attribution for "
            "stack-local-layout rows."
        ),
    )
    parser.add_argument(
        "--skip-name-magic-preflight",
        action="store_true",
        help=(
            "Skip no-compile name-magic preflight for data-symbol rows. "
            "This is faster, but leaves stable non-candidate blockers in the "
            "current-tools-data-symbol queue."
        ),
    )
    parser.add_argument(
        "--skip-struct-verify-gate",
        action="store_true",
        help=(
            "Skip resolver gating for struct-offset-discrepancy rows. This "
            "preserves the legacy raw offset bucket and is faster but noisier."
        ),
    )
    parser.add_argument(
        "--checkdiff-timeout",
        type=float,
        default=DEFAULT_CHECKDIFF_TIMEOUT,
        help=(
            "Per-function checkdiff timeout in seconds "
            f"(default: {DEFAULT_CHECKDIFF_TIMEOUT:g}; 0 disables)."
        ),
    )
    parser.add_argument(
        "--decl-order-timeout",
        type=float,
        default=DEFAULT_DECL_ORDER_TIMEOUT,
        help=(
            "Per-function decl-orders evaluation timeout in seconds "
            f"(default: {DEFAULT_DECL_ORDER_TIMEOUT:g}; 0 disables)."
        ),
    )
    parser.add_argument(
        "--name-magic-preflight-timeout",
        type=float,
        default=DEFAULT_NAME_MAGIC_PREFLIGHT_TIMEOUT,
        help=(
            "Per-function name-magic preflight timeout in seconds "
            f"(default: {DEFAULT_NAME_MAGIC_PREFLIGHT_TIMEOUT:g}; 0 disables)."
        ),
    )
    parser.add_argument(
        "--struct-verify-timeout",
        type=float,
        default=DEFAULT_STRUCT_VERIFY_TIMEOUT,
        help=(
            "Per-function struct verify gate timeout in seconds "
            f"(default: {DEFAULT_STRUCT_VERIFY_TIMEOUT:g}; 0 disables)."
        ),
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=DEFAULT_PROGRESS_INTERVAL,
        help=(
            "Print and persist running progress every N seconds while all "
            f"workers are busy (default: {DEFAULT_PROGRESS_INTERVAL:g}; "
            "0 disables periodic progress)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    checkdiff_timeout = None if args.checkdiff_timeout <= 0 else args.checkdiff_timeout
    decl_order_timeout = None if args.decl_order_timeout <= 0 else args.decl_order_timeout
    name_magic_preflight_timeout = (
        None
        if args.name_magic_preflight_timeout <= 0
        else args.name_magic_preflight_timeout
    )
    struct_verify_timeout = (
        None
        if args.struct_verify_timeout <= 0
        else args.struct_verify_timeout
    )
    progress_interval = None if args.progress_interval <= 0 else args.progress_interval
    output_dir = Path(args.output).resolve()

    def mark_interrupted(signum: int, _frame: Any) -> None:
        status_path = output_dir / RUN_STATUS_FILENAME
        current_status: dict[str, Any] = {}
        try:
            current_status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        interrupted_status = dict(current_status)
        interrupted_status.update(
            {
                "schema_version": RUN_STATUS_SCHEMA_VERSION,
                "status": "failed",
                "failed_at": _utc_now_iso(),
                "error": f"interrupted by signal {signum}",
                "error_type": "SignalInterrupt",
            }
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        write_run_status(output_dir, interrupted_status)
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    previous_handlers: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, mark_interrupted)

    def progress(event: dict[str, Any]) -> None:
        if event.get("event") != "inventory_progress":
            return
        active = ", ".join(str(fn) for fn in event.get("active_functions") or [])
        active_suffix = f"; active: {active}" if active else ""
        print(
            "[taxonomy] "
            f"{event.get('completed_count', 0)}/{event.get('attempted_count', 0)} "
            f"done, {event.get('pending_count', 0)} running, "
            f"{event.get('classified_count', 0)} classified, "
            f"{event.get('error_count', 0)} errors"
            f"{active_suffix}",
            file=sys.stderr,
            flush=True,
        )

    try:
        result = generate_inventory(
            args.report,
            args.output,
            checkdiff_runner=lambda function: default_checkdiff_runner(
                function,
                timeout=checkdiff_timeout,
            ),
            workers=args.workers,
            limit=args.limit,
            decl_order_evaluator=(
                None
                if args.skip_decl_order_eval
                else lambda candidate, record: default_decl_order_evaluator(
                    candidate,
                    record,
                    timeout=decl_order_timeout,
                )
            ),
            frame_report_runner=(
                None
                if args.skip_frame_report_attribution
                else default_frame_report_runner
            ),
            name_magic_preflight_runner=(
                None
                if args.skip_name_magic_preflight
                else lambda candidate: default_name_magic_preflight_runner(
                    candidate,
                    timeout=name_magic_preflight_timeout,
                )
            ),
            struct_verify_runner=(
                None
                if args.skip_struct_verify_gate
                else lambda candidate, classification: default_struct_verify_runner(
                    candidate,
                    classification,
                    timeout=struct_verify_timeout,
                )
            ),
            progress_callback=progress,
            progress_interval=progress_interval,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)

    print(f"Generated taxonomy artifacts in {result.output_dir}")
    print(
        "Rows: "
        f"{result.report_non100_count} report unmatched functions, "
        f"{result.attempted_count} attempted, "
        f"{result.classified_count} classified, "
        f"{result.error_count} errors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
