"""Audit checkdiff call-prep signature/type mismatches against source calls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .cast_audit import (
    _extract_local_types,
    _is_float_type,
    _is_integer_type,
    _looks_integer,
    _split_args,
    find_call_sites,
)
from .source_patch import find_function


@dataclass(frozen=True)
class PatchDescriptor:
    source_file: str | None
    line: int
    old: str
    new: str


@dataclass
class SourceVariant:
    variant_id: str
    label: str
    patches: list[PatchDescriptor]
    candidate: dict[str, object]


@dataclass
class SignatureAction:
    kind: str
    confidence: str
    affected_call_sites: list[dict]
    reason: str
    patch: PatchDescriptor | None = None
    validation: dict | None = None
    rebucket: dict[str, object] | None = None
    candidate: dict[str, object] | None = None
    source_variant: SourceVariant | None = None


@dataclass
class SignatureFinding:
    kind: str
    confidence: str
    call_target: str | None
    call_ordinal: int
    arg_register: str | None
    expected: dict
    current: dict
    source_line: int | None
    arg_index: int | None
    affected_call_sites: list[dict]
    actions: list[SignatureAction]


@dataclass
class SignatureAuditReport:
    function: str
    classification: str | None
    findings: list[SignatureFinding]
    summary: dict[str, object] | None = None


@dataclass(frozen=True)
class _AsmInstr:
    opcode: str
    operands: tuple[str, ...]
    text: str
    index: int


@dataclass(frozen=True)
class _ArgPrep:
    register: str
    bank: str
    width: int | None
    load_kind: str
    source_register: str | None
    opcode: str
    text: str


@dataclass(frozen=True)
class _ReturnUse:
    register: str
    source_register: str
    shape: str
    width: int | None
    opcode: str
    text: str
    through_copy: bool


@dataclass
class _AsmCall:
    call_target: str
    display_target: str
    relocation_target: str | None
    overall_ordinal: int
    target_ordinal: int
    instruction_index: int
    arg_preps: dict[str, _ArgPrep]
    return_use: _ReturnUse | None = None


@dataclass(frozen=True)
class _ArgPrepComparison:
    arg_index: int
    expected_register: str | None
    current_register: str | None
    expected: _ArgPrep | None
    current: _ArgPrep | None


@dataclass
class _PrototypeInfo:
    has_prototype: bool
    is_static: bool
    is_variadic: bool
    param_types: tuple[str, ...]
    return_type: str | None = None
    is_definition: bool = False
    line: int | None = None
    param_texts: tuple[str, ...] = ()
    param_names: tuple[str | None, ...] = ()
    declaration_count: int = 1
    source_scope: str = "unknown"


@dataclass(frozen=True)
class _CallAlias:
    alias: str
    target: str


GPR_ARG_ORDER = tuple(f"r{i}" for i in range(3, 11))
FPR_ARG_ORDER = tuple(f"f{i}" for i in range(1, 14))
ARG_REGISTER_ORDER = {reg: i for i, reg in enumerate(GPR_ARG_ORDER + FPR_ARG_ORDER)}

GPR_PREP_OPS = {
    "mr",
    "li",
    "addi",
    "lwz",
    "lbz",
    "lhz",
    "lha",
    "extsb",
    "extsh",
    "clrlwi",
    "rlwinm",
}
FPR_PREP_OPS = {"fmr", "lfs", "lfd"}
INTEGER_CAST_TYPES = {
    "char",
    "short",
    "int",
    "long",
    "long long",
    "s8",
    "u8",
    "s16",
    "u16",
    "s32",
    "u32",
    "s64",
    "u64",
    "unsigned char",
    "unsigned short",
    "unsigned int",
    "unsigned long",
    "signed char",
    "signed short",
    "signed int",
    "signed long",
}
FLOAT_CAST_TYPES = {"f32", "f64", "float", "double"}
# Bare C type keywords that can appear as the trailing word of a multi-word
# UNNAMED type (e.g. ``unsigned char``, ``long long``). When the trailing word
# of a parameter token is one of these and there are no pointer stars, the
# token has no parameter name and the whole token is the type.
TYPE_KEYWORD_WORDS = {
    "unsigned",
    "signed",
    "int",
    "char",
    "short",
    "long",
    "void",
    "float",
    "double",
}


def audit_signature_call_type(
    checkdiff_payload: dict,
    source_text: str,
    function: str,
    source_file: str | None = None,
    window: int = 10,
) -> SignatureAuditReport:
    """Rank source-level actions for checkdiff call-prep type mismatches."""
    target_calls = _parse_asm_calls(checkdiff_payload.get("target_asm", []), window)
    current_calls = _parse_asm_calls(checkdiff_payload.get("current_asm", []), window)
    source_context = _build_source_context(source_text, function, source_file)
    findings: list[SignatureFinding] = []

    findings.extend(
        _call_target_shape_findings(target_calls, current_calls, source_context)
    )
    findings.extend(
        _return_width_findings(target_calls, current_calls, source_context)
    )
    findings.extend(
        _call_prep_findings(target_calls, current_calls, source_context)
    )

    merged = _merge_findings(findings)
    return SignatureAuditReport(
        function=function,
        classification=_classification_primary(checkdiff_payload),
        findings=merged,
        summary=_summarize_report(merged),
    )


def validate_signature_patches(
    report: SignatureAuditReport,
    source_text: str,
    run_candidate: Callable[[str], dict],
    *,
    baseline_match_percent: float | None = None,
    primary_function: str | None = None,
    sibling_functions: list[str] | None = None,
    sibling_baseline_match_percent: dict[str, float | None] | None = None,
    run_candidate_multi: Callable[[str, list[str]], dict[str, dict]] | None = None,
) -> SignatureAuditReport:
    """Run candidate source patches and attach checkdiff validation metadata."""
    for finding in report.findings:
        for action in finding.actions:
            if action.source_variant is not None:
                patched_source, patch_error = _apply_source_variant(
                    source_text,
                    action.source_variant,
                )
                if patch_error is not None:
                    action.validation = {
                        "status": "skipped",
                        "retained": False,
                        "rejection_reason": "patch-application-failed",
                        "error": patch_error,
                    }
                    continue
                functions = _validation_function_list(
                    primary_function or report.function,
                    sibling_functions or [],
                )
                try:
                    if run_candidate_multi is not None:
                        payloads = run_candidate_multi(patched_source, functions)
                    else:
                        payloads = {
                            functions[0]: run_candidate(patched_source),
                        }
                except Exception as exc:  # pragma: no cover - subprocess errors vary
                    action.validation = {
                        "status": "failed",
                        "retained": False,
                        "rejection_reason": "compile-failed",
                        "error": str(exc),
                    }
                    continue
                action.validation = _source_variant_validation(
                    primary_function=functions[0],
                    sibling_functions=functions[1:],
                    payloads=payloads,
                    baseline_match_percent=baseline_match_percent,
                    sibling_baseline_match_percent=(
                        sibling_baseline_match_percent or {}
                    ),
                )
                continue
            if action.patch is None:
                continue
            patched_source, patch_error = _apply_patch_descriptor(
                source_text,
                action.patch,
            )
            if patch_error is not None:
                action.validation = {
                    "status": "skipped",
                    "error": patch_error,
                }
                continue
            try:
                payload = run_candidate(patched_source)
            except Exception as exc:  # pragma: no cover - exact subprocess errors vary
                action.validation = {
                    "status": "failed",
                    "error": str(exc),
                }
                continue
            action.validation = _single_candidate_validation(
                payload,
                baseline_match_percent=baseline_match_percent,
            )
    report.summary = _summarize_report(report.findings)
    return report


def _validation_function_list(primary: str, siblings: list[str]) -> list[str]:
    functions = [primary]
    seen = {primary}
    for sibling in siblings:
        if sibling in seen:
            continue
        functions.append(sibling)
        seen.add(sibling)
    return functions


def _single_candidate_validation(
    payload: dict,
    *,
    baseline_match_percent: float | None,
) -> dict:
    candidate_match = _payload_match_percent(payload)
    match = bool(payload.get("match") is True)
    delta = (
        candidate_match - baseline_match_percent
        if candidate_match is not None and baseline_match_percent is not None
        else None
    )
    if match:
        status = "validated"
    elif candidate_match is None:
        status = "unscored"
    else:
        status = "scored"
    if delta is not None and delta <= 0 and not match:
        status = "non-improving"
    validation = {
        "status": status,
        "match": match,
        "baseline_match_percent": baseline_match_percent,
        "candidate_match_percent": candidate_match,
        "delta_match_percent": delta,
        "classification": _classification_primary(payload),
    }
    candidate_match_source = _payload_match_percent_source(payload)
    if candidate_match_source is not None:
        validation["candidate_match_percent_source"] = candidate_match_source
    if candidate_match is None and not match:
        validation["score_reason"] = (
            "candidate checkdiff did not return a match percent"
        )
    return validation


def _source_variant_validation(
    *,
    primary_function: str,
    sibling_functions: list[str],
    payloads: dict[str, dict],
    baseline_match_percent: float | None,
    sibling_baseline_match_percent: dict[str, float | None],
) -> dict:
    primary_payload = payloads.get(primary_function, {})
    primary = _single_candidate_validation(
        primary_payload,
        baseline_match_percent=baseline_match_percent,
    )
    primary["function"] = primary_function
    siblings = []
    for sibling in sibling_functions:
        sibling_validation = _single_candidate_validation(
            payloads.get(sibling, {}),
            baseline_match_percent=sibling_baseline_match_percent.get(sibling),
        )
        sibling_validation["function"] = sibling
        siblings.append(sibling_validation)

    rejection_reason = _source_variant_rejection_reason(primary, siblings)
    retained = rejection_reason is None
    return {
        "status": "retained" if retained else "rejected",
        "retained": retained,
        "rejection_reason": rejection_reason,
        "primary": primary,
        "siblings": siblings,
    }


def _source_variant_rejection_reason(
    primary: dict,
    siblings: list[dict],
) -> str | None:
    if primary.get("match") is not True:
        primary_delta = primary.get("delta_match_percent")
        if not isinstance(primary_delta, (int, float)) or primary_delta <= 0:
            if primary.get("candidate_match_percent") is None:
                return "candidate-unscored"
            return "primary-non-improving"
    for sibling in siblings:
        delta = sibling.get("delta_match_percent")
        if delta is None:
            continue
        if isinstance(delta, (int, float)) and delta < 0:
            return "sibling-regressed"
    return None


SOURCE_LEVER_ACTION_KINDS = {
    "same-tu-static-prototype-audit",
    "same-tu-static-prototype-candidate",
    "global-prototype-candidate",
    "field-type-audit",
    "local-temp-shape-audit",
}


def _summarize_report(findings: list[SignatureFinding]) -> dict[str, object]:
    action_kind_counts: dict[str, int] = {}
    rebucket_reason_counts: dict[str, int] = {}
    action_count = 0
    patch_candidate_count = 0
    validated_patch_candidate_count = 0
    unvalidated_patch_candidate_count = 0
    rebucketed_audit_only_count = 0
    audit_only_unrebucketed = 0
    source_lever_action_count = 0
    source_variant_candidate_count = 0
    local_return_width_candidate_count = 0
    validated_local_return_width_candidate_count = 0
    retained_local_return_width_candidate_count = 0

    for finding in findings:
        for action in finding.actions:
            action_count += 1
            action_kind_counts[action.kind] = (
                action_kind_counts.get(action.kind, 0) + 1
            )
            if action.source_variant is not None:
                source_variant_candidate_count += 1
                if action.kind == "call-site-local-return-width":
                    local_return_width_candidate_count += 1
                    if _source_variant_validation_completed(action.validation):
                        validated_local_return_width_candidate_count += 1
                    if _validation_retained(action.validation):
                        retained_local_return_width_candidate_count += 1
                source_lever_action_count += 1
                continue
            if action.patch is not None:
                patch_candidate_count += 1
                if _validation_improves(action.validation):
                    validated_patch_candidate_count += 1
                else:
                    unvalidated_patch_candidate_count += 1
                continue
            if action.rebucket:
                rebucketed_audit_only_count += 1
                reason = str(action.rebucket.get("reason") or "unknown")
                rebucket_reason_counts[reason] = (
                    rebucket_reason_counts.get(reason, 0) + 1
                )
                continue
            if action.kind in SOURCE_LEVER_ACTION_KINDS:
                source_lever_action_count += 1
                continue
            audit_only_unrebucketed += 1

    stop_condition = _summary_stop_condition(
        finding_count=len(findings),
        patch_candidate_count=patch_candidate_count,
        validated_patch_candidate_count=validated_patch_candidate_count,
        audit_only_unrebucketed=audit_only_unrebucketed,
        source_lever_action_count=source_lever_action_count,
        rebucketed_audit_only_count=rebucketed_audit_only_count,
        local_return_width_candidate_count=local_return_width_candidate_count,
        validated_local_return_width_candidate_count=(
            validated_local_return_width_candidate_count
        ),
        retained_local_return_width_candidate_count=(
            retained_local_return_width_candidate_count
        ),
    )

    return {
        "finding_count": len(findings),
        "action_count": action_count,
        "patch_candidate_count": patch_candidate_count,
        "validated_patch_candidate_count": validated_patch_candidate_count,
        "unvalidated_patch_candidate_count": unvalidated_patch_candidate_count,
        "rebucketed_audit_only_count": rebucketed_audit_only_count,
        "audit_only_unrebucketed": audit_only_unrebucketed,
        "source_lever_action_count": source_lever_action_count,
        "source_variant_candidate_count": source_variant_candidate_count,
        "local_return_width_candidate_count": local_return_width_candidate_count,
        "validated_local_return_width_candidate_count": (
            validated_local_return_width_candidate_count
        ),
        "retained_local_return_width_candidate_count": (
            retained_local_return_width_candidate_count
        ),
        "action_kind_counts": action_kind_counts,
        "rebucket_reason_counts": rebucket_reason_counts,
        "stop_condition": stop_condition,
    }


def _validation_improves(validation: dict | None) -> bool:
    if not validation:
        return False
    if validation.get("match") is True:
        return True
    delta = validation.get("delta_match_percent")
    return isinstance(delta, (int, float)) and delta > 0


def _validation_retained(validation: dict | None) -> bool:
    if not validation:
        return False
    return validation.get("retained") is True or _validation_improves(validation)


def _source_variant_validation_completed(validation: dict | None) -> bool:
    if not validation:
        return False
    return validation.get("status") in {"retained", "rejected"}


def _summary_stop_condition(
    *,
    finding_count: int,
    patch_candidate_count: int,
    validated_patch_candidate_count: int,
    audit_only_unrebucketed: int,
    source_lever_action_count: int,
    rebucketed_audit_only_count: int,
    local_return_width_candidate_count: int,
    validated_local_return_width_candidate_count: int,
    retained_local_return_width_candidate_count: int,
) -> dict[str, str]:
    if finding_count == 0:
        return {
            "kind": "no-findings",
            "reason": "signature audit found no call-prep differences",
        }
    if validated_patch_candidate_count > 0:
        return {
            "kind": "validated-patch-candidates",
            "reason": "at least one patch candidate validated as matched or improving",
        }
    if patch_candidate_count > 0:
        return {
            "kind": "unvalidated-patch-candidates",
            "reason": "patch candidates exist but validation has not proved improvement",
        }
    if audit_only_unrebucketed > 0:
        return {
            "kind": "audit-only-unclassified",
            "reason": "some audit-only actions lack a rebucket or source-lever reason",
        }
    if (
        local_return_width_candidate_count > 0
        and retained_local_return_width_candidate_count > 0
    ):
        return {
            "kind": "retained-local-return-width-candidates",
            "reason": "at least one local return-width candidate was retained",
        }
    if (
        local_return_width_candidate_count > 0
        and validated_local_return_width_candidate_count > 0
    ):
        return {
            "kind": "local-return-width-exhausted",
            "reason": "local return-width candidates were validated but none were retained",
        }
    if source_lever_action_count > 0:
        return {
            "kind": "source-lever-audit",
            "reason": "audit actions identify bounded source levers without automatic patches",
        }
    if rebucketed_audit_only_count > 0:
        return {
            "kind": "rebucketed-audit-only",
            "reason": "all audit-only actions have concrete rebucket reasons",
        }
    return {
        "kind": "audit-only-unclassified",
        "reason": "signature audit produced findings without classifiable actions",
    }


def _apply_patch_descriptor(
    source_text: str,
    patch: PatchDescriptor,
) -> tuple[str | None, str | None]:
    if not patch.old:
        return None, "patch old text was empty"
    lines = source_text.splitlines(keepends=True)
    line_index = patch.line - 1
    if 0 <= line_index < len(lines) and patch.old in lines[line_index]:
        lines[line_index] = lines[line_index].replace(patch.old, patch.new, 1)
        return "".join(lines), None
    count = source_text.count(patch.old)
    if count == 1:
        return source_text.replace(patch.old, patch.new, 1), None
    if count == 0:
        return None, f"patch text not found: {patch.old!r}"
    return None, f"patch text was ambiguous ({count} occurrences): {patch.old!r}"


def _apply_source_variant(
    source_text: str,
    variant: SourceVariant,
) -> tuple[str | None, str | None]:
    patched = source_text
    for idx, patch in enumerate(variant.patches, start=1):
        next_source, error = _apply_patch_descriptor(patched, patch)
        if error is not None:
            return None, f"patch {idx} failed: {error}"
        if next_source is None:
            return None, f"patch {idx} failed: patch produced no source"
        patched = next_source
    return patched, None


def _payload_match_percent(payload: dict) -> float | None:
    for key in ("fuzzy_match_percent", "match_percent", "percent"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _payload_match_percent_source(payload: dict) -> str | None:
    for key in (
        "fuzzy_match_percent_source",
        "match_percent_source",
        "percent_source",
    ):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _classification_primary(checkdiff_payload: dict) -> str | None:
    classification = checkdiff_payload.get("classification")
    if isinstance(classification, dict):
        primary = classification.get("primary")
        return str(primary) if primary is not None else None
    if classification is None:
        return None
    return str(classification)


def _strip_asm_line(line: str) -> str:
    stripped = re.sub(r"^\s*/\*.*?\*/\s*", "", line).strip()
    stripped = stripped.split("#", 1)[0].strip()
    offset_match = re.match(
        r"^[+-]?(?:0x)?[0-9A-Fa-f]+:\s*(?P<body>.+)$",
        stripped,
    )
    if offset_match is not None:
        stripped = offset_match.group("body").strip()
        bytes_match = re.match(
            r"^(?:(?:[0-9A-Fa-f]{2}|[0-9A-Fa-f]{8})\s+)+"
            r"(?P<asm>[A-Za-z_.][\w.]*\b.*)$",
            stripped,
        )
        if bytes_match is not None:
            stripped = bytes_match.group("asm").strip()
    return stripped


def _parse_asm_instr(line: str, index: int) -> _AsmInstr | None:
    stripped = _strip_asm_line(line)
    if not stripped:
        return None
    parts = stripped.split(None, 1)
    opcode = parts[0].lower()
    operands: tuple[str, ...] = ()
    if len(parts) == 2:
        operands = tuple(p.strip() for p in parts[1].split(",") if p.strip())
    return _AsmInstr(opcode=opcode, operands=operands, text=stripped, index=index)


def _parse_asm_calls(lines: list[str], window: int) -> list[_AsmCall]:
    instrs = [
        instr
        for idx, line in enumerate(lines)
        if (instr := _parse_asm_instr(line, idx)) is not None
    ]
    calls: list[_AsmCall] = []
    target_counts: dict[str, int] = {}
    rel24_targets = _rel24_targets_by_offset(lines)
    for instr_index, instr in enumerate(instrs):
        if instr.opcode != "bl" or not instr.operands:
            continue
        display_target = _normalize_call_target(instr.operands[0])
        if display_target is None:
            continue
        offset = _asm_line_offset(lines[instr.index])
        relocation_target = rel24_targets.get(offset) if offset is not None else None
        target = relocation_target or display_target
        target_counts[target] = target_counts.get(target, 0) + 1
        calls.append(
            _AsmCall(
                call_target=target,
                display_target=display_target,
                relocation_target=relocation_target,
                overall_ordinal=len(calls) + 1,
                target_ordinal=target_counts[target],
                instruction_index=instr.index,
                arg_preps=_collect_arg_preps(instrs, instr_index, window),
                return_use=_collect_return_use(instrs, instr_index, window),
            )
        )
    return calls


def _normalize_call_target(raw: str) -> str | None:
    target = raw.strip().rstrip(",")
    target = target.split(None, 1)[0]
    target = target.strip("<>")
    if not target or target.startswith("0x"):
        return None
    return target


def _rel24_targets_by_offset(lines: list[str]) -> dict[int, str]:
    targets: dict[int, str] = {}
    for line in lines:
        if "R_PPC_REL24" not in line:
            continue
        offset = _asm_line_offset(line)
        target = _rel24_target(line)
        if offset is None or target is None:
            continue
        targets[offset] = target
    return targets


def _rel24_target(line: str) -> str | None:
    match = re.search(r"\bR_PPC_REL24\b\s+(?P<target>\S+)", line)
    if match is None:
        return None
    return _normalize_call_target(match.group("target"))


def _asm_line_offset(line: str) -> int | None:
    stripped = line.strip()
    colon_match = re.match(
        r"^(?P<sign>[+-]?)(?:0x)?(?P<offset>[0-9A-Fa-f]+):",
        stripped,
    )
    if colon_match is not None:
        value = int(colon_match.group("offset"), 16)
        return -value if colon_match.group("sign") == "-" else value
    comment_match = re.match(
        r"^/\*\s*(?P<offset>[0-9A-Fa-f]+)\s*\*/",
        stripped,
    )
    if comment_match is not None:
        return int(comment_match.group("offset"), 16)
    return None


def _collect_arg_preps(
    instrs: list[_AsmInstr],
    call_instr_pos: int,
    window: int,
) -> dict[str, _ArgPrep]:
    start = max(0, call_instr_pos - window)
    preps: dict[str, _ArgPrep] = {}
    for instr in reversed(instrs[start:call_instr_pos]):
        if _is_arg_prep_boundary(instr):
            break
        prep = _prep_from_instr(instr)
        if prep is not None and prep.register not in preps:
            preps[prep.register] = prep
    return preps


def _collect_return_use(
    instrs: list[_AsmInstr],
    call_instr_pos: int,
    window: int,
) -> _ReturnUse | None:
    first_plain: _ReturnUse | None = None
    copied_register: str | None = None
    end = min(len(instrs), call_instr_pos + window + 1)
    for instr in instrs[call_instr_pos + 1 : end]:
        if _is_arg_prep_boundary(instr):
            break
        return_use = _return_use_from_instr(instr, copied_register)
        if return_use is None:
            continue
        if return_use.shape != "plain-move":
            return return_use
        if first_plain is None:
            first_plain = return_use
        if return_use.source_register == "r3" and copied_register is None:
            copied_register = return_use.register
    return first_plain


def _return_use_from_instr(
    instr: _AsmInstr,
    copied_register: str | None,
) -> _ReturnUse | None:
    if len(instr.operands) < 2:
        return None
    dest = _normalize_register(instr.operands[0])
    src = _normalize_register(instr.operands[1])
    through_copy = copied_register is not None and src == copied_register
    if src != "r3" and not through_copy:
        return None
    if instr.opcode == "mr":
        return _ReturnUse(
            register=dest,
            source_register=src,
            shape="plain-move",
            width=32,
            opcode=instr.opcode,
            text=instr.text,
            through_copy=through_copy,
        )
    shape_width = _return_shape_width(instr)
    if shape_width is None:
        return None
    shape, width = shape_width
    return _ReturnUse(
        register=dest,
        source_register=src,
        shape=shape,
        width=width,
        opcode=instr.opcode,
        text=instr.text,
        through_copy=through_copy,
    )


def _return_shape_width(instr: _AsmInstr) -> tuple[str, int] | None:
    if instr.opcode == "clrlwi" and len(instr.operands) >= 3:
        shift = _parse_int(instr.operands[2])
        if shift == 24:
            return "zero-extend-8", 8
        if shift == 16:
            return "zero-extend-16", 16
    if instr.opcode == "rlwinm" and len(instr.operands) >= 5:
        shift = _parse_int(instr.operands[2])
        mask_begin = _parse_int(instr.operands[3])
        mask_end = _parse_int(instr.operands[4])
        if shift == 0 and mask_begin == 24 and mask_end == 31:
            return "zero-extend-8", 8
        if shift == 0 and mask_begin == 16 and mask_end == 31:
            return "zero-extend-16", 16
    if instr.opcode == "extsb":
        return "sign-extend-8", 8
    if instr.opcode == "extsh":
        return "sign-extend-16", 16
    return None


def _is_arg_prep_boundary(instr: _AsmInstr) -> bool:
    if instr.opcode == "bl" or instr.opcode.startswith("b"):
        return True
    return instr.opcode.endswith(":") or instr.text.endswith(":")


def _prep_from_instr(instr: _AsmInstr) -> _ArgPrep | None:
    if instr.opcode in GPR_PREP_OPS:
        return _gpr_prep_from_instr(instr)
    if instr.opcode in FPR_PREP_OPS or _looks_fp_arithmetic(instr):
        return _fpr_prep_from_instr(instr)
    return None


def _gpr_prep_from_instr(instr: _AsmInstr) -> _ArgPrep | None:
    if not instr.operands:
        return None
    dest = _normalize_register(instr.operands[0])
    if dest not in GPR_ARG_ORDER:
        return None
    width = _gpr_width(instr)
    return _ArgPrep(
        register=dest,
        bank="GPR",
        width=width,
        load_kind=_gpr_load_kind(instr.opcode),
        source_register=_first_source_register(instr.operands[1:], "r"),
        opcode=instr.opcode,
        text=instr.text,
    )


def _fpr_prep_from_instr(instr: _AsmInstr) -> _ArgPrep | None:
    if not instr.operands:
        return None
    dest = _normalize_register(instr.operands[0])
    if dest not in FPR_ARG_ORDER:
        return None
    return _ArgPrep(
        register=dest,
        bank="FPR",
        width=_fpr_width(instr.opcode),
        load_kind=_fpr_load_kind(instr.opcode),
        source_register=_first_source_register(instr.operands[1:], "f"),
        opcode=instr.opcode,
        text=instr.text,
    )


def _looks_fp_arithmetic(instr: _AsmInstr) -> bool:
    return (
        instr.opcode.startswith("f")
        and len(instr.operands) >= 2
        and _normalize_register(instr.operands[0]) in FPR_ARG_ORDER
    )


def _normalize_register(operand: str) -> str:
    return operand.strip().lower().rstrip(",")


def _first_source_register(operands: tuple[str, ...], prefix: str) -> str | None:
    pattern = re.compile(rf"\b{prefix}(?:\d+)\b", re.IGNORECASE)
    for operand in operands:
        match = pattern.search(operand)
        if match is not None:
            return match.group(0).lower()
    return None


def _gpr_width(instr: _AsmInstr) -> int | None:
    opcode = instr.opcode
    if opcode in {"lbz", "extsb"}:
        return 8
    if opcode in {"lhz", "lha", "extsh"}:
        return 16
    if opcode == "clrlwi" and len(instr.operands) >= 3:
        imm = _parse_int(instr.operands[2])
        if imm is not None and 0 <= imm <= 31:
            return 32 - imm
    return 32


def _gpr_load_kind(opcode: str) -> str:
    if opcode in {"lwz", "lbz", "lhz", "lha"}:
        return "integer-load"
    if opcode in {"extsb", "extsh", "clrlwi", "rlwinm"}:
        return "integer-shape"
    if opcode in {"li", "addi"}:
        return "integer-immediate"
    return "move"


def _fpr_width(opcode: str) -> int | None:
    if opcode == "lfs":
        return 32
    if opcode == "lfd":
        return 64
    return None


def _fpr_load_kind(opcode: str) -> str:
    if opcode in {"lfs", "lfd"}:
        return "float-load"
    if opcode == "fmr":
        return "move"
    return "float-arithmetic"


def _parse_int(text: str) -> int | None:
    try:
        return int(text, 0)
    except ValueError:
        return None


@dataclass
class _SourceContext:
    function: str
    source_text: str
    call_sites: dict[tuple[str, int], dict]
    call_sites_by_overall: dict[int, dict]
    prototypes: dict[str, _PrototypeInfo]
    local_types: dict[str, str]
    call_aliases: dict[str, _CallAlias]


def _build_source_context(
    source_text: str,
    function: str,
    source_file: str | None,
) -> _SourceContext:
    combined_source = _source_with_direct_includes(source_text, source_file)
    call_aliases = _parse_call_aliases(combined_source)
    span = find_function(source_text, function)
    if span is None:
        return _SourceContext(
            function=function,
            source_text=source_text,
            call_sites={},
            call_sites_by_overall={},
            prototypes=_parse_visible_prototypes(combined_source),
            local_types={},
            call_aliases=call_aliases,
        )

    full_function = source_text[span.sig_start:span.full_end]
    body_text = source_text[span.body_open:span.full_end]
    body_line_offset = source_text[: span.body_open].count("\n")
    call_sites: dict[tuple[str, int], dict] = {}
    call_sites_by_overall: dict[int, dict] = {}
    target_counts: dict[str, int] = {}
    overall_ordinal = 0
    for site in find_call_sites(body_text):
        if _is_source_parser_artifact(site.call_target):
            continue
        overall_ordinal += 1
        target_counts[site.call_target] = target_counts.get(site.call_target, 0) + 1
        target_ordinal = target_counts[site.call_target]
        abs_line = body_line_offset + site.line
        args = [
            {
                "arg_index": arg.arg_index,
                "text": arg.text.strip(),
                "cast_type": arg.cast_type,
                "inner_expr": arg.inner_expr.strip(),
            }
            for arg in site.args
        ]
        call_site = {
            "source_file": source_file,
            "line": abs_line,
            "call_target": site.call_target,
            "source_call_target": site.call_target,
            "underlying_call_target": site.call_target,
            "target_ordinal": target_ordinal,
            "overall_call_ordinal": overall_ordinal,
            "args": args,
        }
        call_sites[(site.call_target, target_ordinal)] = call_site
        alias = call_aliases.get(site.call_target)
        if alias is not None:
            aliased_site = dict(call_site)
            aliased_site["call_target"] = alias.target
            aliased_site["source_call_target"] = site.call_target
            aliased_site["underlying_call_target"] = alias.target
            call_sites[(alias.target, target_ordinal)] = aliased_site
        call_sites_by_overall[overall_ordinal] = call_site

    return _SourceContext(
        function=function,
        source_text=source_text,
        call_sites=call_sites,
        call_sites_by_overall=call_sites_by_overall,
        prototypes=_parse_visible_prototypes(combined_source),
        local_types=_extract_local_types(full_function),
        call_aliases=call_aliases,
    )


def _is_source_parser_artifact(call_target: str) -> bool:
    return call_target in {"PAD_STACK", "void"}


def _source_with_direct_includes(
    source_text: str,
    source_file: str | None,
) -> str:
    include_texts = _direct_include_texts(source_text, source_file)
    if not include_texts:
        return source_text
    return source_text + "\n" + "\n".join(include_texts)


def _direct_include_texts(source_text: str, source_file: str | None) -> list[str]:
    source_path = Path(source_file).expanduser() if source_file else None
    if source_path is not None and not source_path.is_absolute():
        source_path = Path.cwd() / source_path
    repo_root = _repo_root_for_source(source_path)
    include_dir = source_path.parent if source_path is not None else repo_root
    texts: list[str] = []
    for match in re.finditer(r'^\s*#\s*include\s+([<"])([^>"]+)[>"]', source_text, re.MULTILINE):
        delimiter, include_name = match.groups()
        include_path: Path | None = None
        if delimiter == '"':
            include_path = include_dir / include_name
        elif include_name.startswith("melee/"):
            include_path = repo_root / "src" / include_name
        elif include_name.startswith("baselib/"):
            include_path = repo_root / "src" / "sysdolphin" / include_name
        if include_path is None:
            continue
        try:
            texts.append(include_path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return texts


def _repo_root_for_source(source_path: Path | None) -> Path:
    candidates = []
    if source_path is not None:
        candidates.extend([source_path.parent, *source_path.parents])
    candidates.extend([Path.cwd(), *Path.cwd().parents])
    for candidate in candidates:
        if (candidate / "configure.py").exists() and (candidate / "src").exists():
            return candidate
    return Path.cwd()


def _parse_call_aliases(source_text: str) -> dict[str, _CallAlias]:
    aliases: dict[str, _CallAlias] = {}
    pattern = re.compile(
        r"^\s*#\s*define\s+"
        r"(?P<alias>[A-Za-z_]\w*)\s*\([^)]*\)\s+"
        r"(?P<body>.+)$",
        re.MULTILINE,
    )
    for match in pattern.finditer(source_text):
        alias = match.group("alias")
        body = match.group("body")
        targets = [
            target
            for target in re.findall(r"\b([A-Za-z_]\w*)\s*\(", body)
            if target not in {alias, "int", "u8", "s8", "u16", "s16"}
        ]
        if not targets:
            continue
        aliases[alias] = _CallAlias(alias=alias, target=targets[-1])
    return aliases


def _parse_visible_prototypes(source_text: str) -> dict[str, _PrototypeInfo]:
    prototypes: dict[str, _PrototypeInfo] = {}
    source_text = _strip_block_comments_preserve_lines(source_text)
    pattern = re.compile(
        r"(?P<prefix>(?:^|[;\n}])\s*(?:static\s+)?[A-Za-z_][\w\s\*]*?)"
        r"\b(?P<name>[A-Za-z_]\w*)\s*\(",
        re.MULTILINE,
    )
    for match in pattern.finditer(source_text):
        name = match.group("name")
        prefix = " ".join(match.group("prefix").split())
        if name in {
            "if",
            "for",
            "while",
            "switch",
            "return",
            "sizeof",
        }:
            continue
        cleaned_prefix = re.sub(r"^[;\n}\s]+", "", prefix)
        prefix_first_word = (
            cleaned_prefix.split()[0] if cleaned_prefix.split() else ""
        )
        if prefix_first_word in {
            "case",
            "return",
            "if",
            "for",
            "while",
            "switch",
        }:
            continue
        open_idx = match.end() - 1
        close_idx = _matching_paren(source_text, open_idx)
        if close_idx is None:
            continue
        suffix = source_text[close_idx + 1 :].lstrip()
        if not suffix or suffix[0] not in ";{":
            continue
        params = source_text[open_idx + 1 : close_idx].strip()
        param_texts = tuple(
            param.strip()
            for param in _split_args(params)
            if param.strip() and param.strip() not in {"void", "..."}
        )
        if param_texts and param_texts[-1].endswith("..."):
            param_texts = tuple(param_texts[:-1])
        is_variadic = "..." in params
        param_types = tuple(_extract_param_types(params))
        existing = prototypes.get(name)
        is_static = "static" in prefix.split()
        declaration_count = (
            existing.declaration_count + 1 if existing is not None else 1
        )
        info = _PrototypeInfo(
            has_prototype=True,
            is_static=is_static,
            is_variadic=is_variadic,
            param_types=param_types,
            return_type=_extract_return_type(prefix),
            is_definition=suffix[0] == "{",
            line=source_text[: match.start("name")].count("\n") + 1,
            param_texts=param_texts,
            param_names=tuple(_extract_param_name(param) for param in param_texts),
            declaration_count=declaration_count,
            source_scope="same-tu-static" if is_static else "visible-nonstatic",
        )
        if existing is None:
            prototypes[name] = info
            continue
        existing.declaration_count = declaration_count
        if info.is_static and not existing.is_static:
            prototypes[name] = info
    return prototypes


def _strip_block_comments_preserve_lines(source_text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        text = match.group(0)
        return "\n" * text.count("\n") + " "

    return re.sub(r"/\*.*?\*/", replace, source_text, flags=re.DOTALL)


def _extract_return_type(prefix: str) -> str | None:
    cleaned = prefix.strip()
    cleaned = re.sub(r"^[;\n}\s]+", "", cleaned)
    words = [
        word
        for word in cleaned.split()
        if word not in {"static", "extern", "inline"}
    ]
    if not words:
        return None
    return " ".join(words)


def _matching_paren(text: str, open_idx: int) -> int | None:
    depth = 0
    quote: str | None = None
    i = open_idx
    while i < len(text):
        char = text[i]
        if quote is not None:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
            i += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _extract_param_types(params: str) -> list[str]:
    param_types: list[str] = []
    for param in _split_args(params):
        cleaned = " ".join(param.strip().split())
        if not cleaned or cleaned == "void" or cleaned == "...":
            continue
        if cleaned.endswith("..."):
            cleaned = cleaned[:-3].strip().rstrip(",").strip()
        cleaned = re.sub(r"\[[^\]]*\]\s*$", "", cleaned).strip()
        match = re.match(
            r"^(.+?)(?:\s+(?P<stars>\*+)?\s*(?P<name>[A-Za-z_]\w*))$",
            cleaned,
        )
        if match is not None and (
            match.group("stars")
            or match.group("name") not in TYPE_KEYWORD_WORDS
        ):
            cleaned = match.group(1).strip()
            if match.group("stars"):
                cleaned = f"{cleaned} {match.group('stars')}"
        param_types.append(cleaned)
    return param_types


def _extract_param_name(param_text: str) -> str | None:
    split = _split_param_type_name(param_text)
    if split is None:
        return None
    return split[1]


def _split_param_type_name(param_text: str) -> tuple[str, str] | None:
    if "\n" in param_text or "\r" in param_text:
        return None
    cleaned = " ".join(param_text.strip().split())
    if not cleaned or cleaned in {"void", "..."}:
        return None
    if "[" in cleaned or "]" in cleaned or "(*" in cleaned:
        return None
    match = re.match(r"^(?P<type>.+?)\s+(?P<name>[A-Za-z_]\w*)$", cleaned)
    if match is None:
        return None
    type_text = match.group("type").strip()
    name = match.group("name").strip()
    if not type_text or not name:
        return None
    # An unnamed multi-word type (e.g. ``long long``, ``unsigned char``) has no
    # parameter name; do not split the trailing type keyword off as a name.
    if "*" not in cleaned and name in TYPE_KEYWORD_WORDS:
        return None
    return type_text, name


def _is_simple_scalar_integer_type(type_text: str) -> bool:
    normalized = " ".join(type_text.replace("volatile", "").split())
    if "*" in normalized or "[" in normalized or "]" in normalized or "(*" in normalized:
        return False
    return normalized in INTEGER_CAST_TYPES


def _prototype_patch_status(
    prototype: _PrototypeInfo,
    arg_index: int,
    source_site: dict | None,
    call: _AsmCall,
) -> str:
    if prototype.declaration_count != 1:
        return "duplicate-visible-declarations"
    if not _trusted_patch_localization(source_site, call):
        return "untrusted-localization"
    if arg_index >= len(prototype.param_texts):
        return "parameter-unavailable"
    param_text = prototype.param_texts[arg_index]
    if (
        "\n" in param_text
        or "\r" in param_text
        or "[" in param_text
        or "]" in param_text
        or "(*" in param_text
    ):
        return "unsupported-parameter-shape"
    split = _split_param_type_name(param_text)
    if split is None:
        # Unnamed parameter: the whole token is the type. Still patchable when
        # it is a simple scalar integer type (the bare proposed type replaces
        # the token); otherwise unsupported.
        whole_type = " ".join(param_text.split())
        if _is_simple_scalar_integer_type(whole_type):
            return "generated"
        return "unsupported-parameter-shape"
    current_type, _ = split
    if not _is_simple_scalar_integer_type(current_type):
        return "unsupported-type-shape"
    return "generated"


def _trusted_patch_localization(
    source_site: dict | None,
    call: _AsmCall,
) -> bool:
    if source_site is None:
        return False
    return (
        source_site.get("localization_kind") == "target-ordinal"
        and source_site.get("call_target") == call.call_target
    )


def _call_target_shape_findings(
    target_calls: list[_AsmCall],
    current_calls: list[_AsmCall],
    source_context: _SourceContext,
) -> list[SignatureFinding]:
    findings: list[SignatureFinding] = []
    max_calls = max(len(target_calls), len(current_calls))
    for idx in range(max_calls):
        expected_call = target_calls[idx] if idx < len(target_calls) else None
        current_call = current_calls[idx] if idx < len(current_calls) else None
        if (
            expected_call is not None
            and current_call is not None
            and expected_call.call_target == current_call.call_target
        ):
            continue
        call_target = current_call.call_target if current_call else None
        if call_target is None and expected_call is not None:
            call_target = expected_call.call_target
        call_for_source = current_call or expected_call
        source_site = None
        if not _any_unresolved_function_offset_call(
            (expected_call, current_call),
            source_context,
        ):
            source_site = _source_site_for_call(
                source_context,
                call_for_source,
                prefer_current=True,
            )
        affected = [_call_site_without_args(source_site)] if source_site else []
        expected = _call_shape_dict(expected_call)
        current = _call_shape_dict(current_call)
        action = SignatureAction(
            kind="call-target-shape-audit",
            confidence="high",
            affected_call_sites=affected,
            reason="Expected and current ASM call targets differ by call ordinal.",
            rebucket=_call_target_rebucket(
                source_site,
                (expected_call, current_call),
                source_context,
            ),
        )
        findings.append(
            SignatureFinding(
                kind="call-target-shape-mismatch",
                confidence="high",
                call_target=call_target,
                call_ordinal=idx + 1,
                arg_register=None,
                expected=expected,
                current=current,
                source_line=source_site.get("line") if source_site else None,
                arg_index=None,
                affected_call_sites=affected,
                actions=[action],
            )
        )
    return findings


def _call_shape_dict(call: _AsmCall | None) -> dict:
    if call is None:
        return {"call_target": None}
    return {
        "call_target": call.call_target,
        "display_target": call.display_target,
        "relocation_target": call.relocation_target,
        "call_ordinal": call.overall_ordinal,
        "target_ordinal": call.target_ordinal,
    }


def _return_width_findings(
    target_calls: list[_AsmCall],
    current_calls: list[_AsmCall],
    source_context: _SourceContext,
) -> list[SignatureFinding]:
    findings: list[SignatureFinding] = []
    current_by_target_ordinal = {
        (call.call_target, call.target_ordinal): call for call in current_calls
    }
    for expected_call in target_calls:
        current_call = current_by_target_ordinal.get(
            (expected_call.call_target, expected_call.target_ordinal)
        )
        if current_call is None:
            continue
        if expected_call.return_use is None or current_call.return_use is None:
            continue
        if not _return_uses_differ(expected_call.return_use, current_call.return_use):
            continue
        source_site = _source_site_for_call(source_context, current_call)
        helper_target = _underlying_call_target(source_site, current_call.call_target)
        prototype = source_context.prototypes.get(helper_target)
        if not _is_narrow_integer_return(prototype):
            continue
        affected = [_call_site_without_args(source_site)] if source_site else []
        action = _return_width_action(
            expected_call=expected_call,
            current_call=current_call,
            source_context=source_context,
            source_site=source_site,
            prototype=prototype,
            affected=affected,
        )
        findings.append(
            SignatureFinding(
                kind="helper-return-width-mismatch",
                confidence="medium",
                call_target=current_call.call_target,
                call_ordinal=current_call.overall_ordinal,
                arg_register=None,
                expected=_return_call_dict(expected_call),
                current=_return_call_dict(current_call),
                source_line=source_site.get("line") if source_site else None,
                arg_index=None,
                affected_call_sites=affected,
                actions=[action],
            )
        )
    return findings


def _return_uses_differ(expected: _ReturnUse, current: _ReturnUse) -> bool:
    if expected.shape != current.shape:
        return True
    return expected.width != current.width


def _return_call_dict(call: _AsmCall) -> dict:
    payload = _call_shape_dict(call)
    payload["return_use"] = _return_use_dict(call.return_use)
    return payload


def _return_use_dict(return_use: _ReturnUse | None) -> dict | None:
    if return_use is None:
        return None
    return {
        "register": return_use.register,
        "source_register": return_use.source_register,
        "shape": return_use.shape,
        "width": return_use.width,
        "opcode": return_use.opcode,
        "text": return_use.text,
        "through_copy": return_use.through_copy,
    }


def _underlying_call_target(source_site: dict | None, call_target: str) -> str:
    if source_site is None:
        return call_target
    target = source_site.get("underlying_call_target") or source_site.get("call_target")
    return str(target) if target is not None else call_target


def _return_width_action(
    *,
    expected_call: _AsmCall,
    current_call: _AsmCall,
    source_context: _SourceContext,
    source_site: dict | None,
    prototype: _PrototypeInfo | None,
    affected: list[dict],
) -> SignatureAction:
    helper = _underlying_call_target(source_site, current_call.call_target)
    candidate = {
        "kind": "call-site-local-return-width",
        "helper": helper,
        "call_target": current_call.call_target,
        "source_line": source_site.get("line") if source_site else None,
        "localization_kind": (
            source_site.get("localization_kind") if source_site else None
        ),
        "expected_return_use": _return_use_dict(expected_call.return_use),
        "current_return_use": _return_use_dict(current_call.return_use),
        "helper_return_type": prototype.return_type if prototype else None,
    }
    if not _trusted_return_width_localization(source_site, current_call):
        return SignatureAction(
            kind="call-site-local-return-width",
            confidence="low",
            affected_call_sites=affected,
            reason=(
                "The helper return-width mismatch was found, but the source call "
                "was not localized by helper target ordinal."
            ),
            rebucket=_return_width_rebucket(
                "return-width-source-localization-unsafe",
                "source localization is not trusted for a local return-width edit",
                candidate,
            ),
            candidate=candidate,
        )

    variant = _source_variant_for_return_width(
        source_context=source_context,
        source_site=source_site,
        helper=helper,
        prototype=prototype,
        candidate=candidate,
    )
    if variant is None:
        return SignatureAction(
            kind="call-site-local-return-width",
            confidence="low",
            affected_call_sites=affected,
            reason=(
                "The helper return-width mismatch was localized, but the source "
                "shape is not one of the conservative local rewrite forms."
            ),
            rebucket=_return_width_rebucket(
                "return-width-source-shape-unsupported",
                "source assignment or consumer shape is unsupported",
                candidate,
            ),
            candidate=candidate,
        )
    return SignatureAction(
        kind="call-site-local-return-width",
        confidence="medium",
        affected_call_sites=affected,
        reason="Localized helper return-width mismatch has a bounded source variant.",
        candidate=variant.candidate,
        source_variant=variant,
    )


def _trusted_return_width_localization(
    source_site: dict | None,
    call: _AsmCall,
) -> bool:
    if source_site is None:
        return False
    return (
        source_site.get("localization_kind") == "target-ordinal"
        and source_site.get("call_target") == call.call_target
    )


def _return_width_rebucket(
    reason: str,
    explanation: str,
    candidate: dict[str, object],
) -> dict[str, object]:
    return _rebucket(
        reason,
        "signature-call-type",
        "helper-return-width",
        explanation,
        candidate=candidate,
    )


def _is_narrow_integer_return(prototype: _PrototypeInfo | None) -> bool:
    if prototype is None or prototype.return_type is None:
        return False
    return _integer_abi_width(prototype.return_type) in {8, 16}


def _is_narrow_integer_local(type_text: str | None) -> bool:
    if type_text is None:
        return False
    return _integer_abi_width(type_text) in {8, 16}


def _source_variant_for_return_width(
    *,
    source_context: _SourceContext,
    source_site: dict,
    helper: str,
    prototype: _PrototypeInfo | None,
    candidate: dict[str, object],
) -> SourceVariant | None:
    assignment = _simple_call_assignment(
        source_context.source_text,
        int(source_site.get("line") or 0),
        str(source_site.get("source_call_target") or helper),
    )
    if assignment is None:
        return None

    receiver, call_text = assignment
    receiver_type = source_context.local_types.get(receiver)
    if _is_narrow_integer_local(receiver_type):
        patches = _local_temp_widen_patches(
            source_context=source_context,
            receiver=receiver,
            receiver_type=str(receiver_type),
            assignment_line=int(source_site.get("line") or 0),
        )
        if patches:
            return _return_width_source_variant(
                label="local-temp-widen-consumer-cast",
                helper=helper,
                source_line=int(source_site.get("line") or 0),
                patches=patches,
                candidate=candidate,
            )

    source_call_target = str(source_site.get("source_call_target") or "")
    if receiver_type == "int" and source_call_target and source_call_target != helper:
        raw_call = re.sub(
            rf"\b{re.escape(source_call_target)}\s*\(",
            f"{helper}(",
            call_text,
            count=1,
        )
        if raw_call != call_text:
            return _return_width_source_variant(
                label="raw-helper-call",
                helper=helper,
                source_line=int(source_site.get("line") or 0),
                patches=[
                    PatchDescriptor(
                        source_file=source_site.get("source_file"),
                        line=int(source_site.get("line") or 0),
                        old=call_text,
                        new=raw_call,
                    )
                ],
                candidate=candidate,
            )
    return None


def _return_width_source_variant(
    *,
    label: str,
    helper: str,
    source_line: int,
    patches: list[PatchDescriptor],
    candidate: dict[str, object],
) -> SourceVariant:
    variant_candidate = dict(candidate)
    variant_candidate.update({
        "variant_label": label,
        "patch_status": "generated",
        "decision_reason": "bounded local helper return-width source variant",
    })
    return SourceVariant(
        variant_id=f"local-return-width:{helper}:{source_line}:{label}",
        label=label,
        patches=patches,
        candidate=variant_candidate,
    )


def _simple_call_assignment(
    source_text: str,
    line_no: int,
    call_target: str,
) -> tuple[str, str] | None:
    if line_no <= 0:
        return None
    lines = source_text.splitlines()
    if line_no > len(lines):
        return None
    line = lines[line_no - 1]
    prefix = re.compile(
        rf"^\s*(?P<receiver>[A-Za-z_]\w*)\s*=\s*"
        rf"(?P<call_open>{re.escape(call_target)}\s*\()"
    )
    match = prefix.match(line)
    if match is None:
        return None
    open_idx = match.end("call_open") - 1
    close_idx = _matching_paren(line, open_idx)
    if close_idx is None:
        return None
    # Accept only when the call is the COMPLETE right-hand side, i.e. nothing
    # but the statement terminator follows the matching close paren.
    if line[close_idx + 1 :].strip() != ";":
        return None
    return (
        match.group("receiver"),
        line[match.start("call_open") : close_idx + 1].strip(),
    )


def _local_temp_widen_patches(
    *,
    source_context: _SourceContext,
    receiver: str,
    receiver_type: str,
    assignment_line: int,
) -> list[PatchDescriptor]:
    decl_patch = _local_declaration_patch(
        source_context=source_context,
        receiver=receiver,
        current_type=receiver_type,
        assignment_line=assignment_line,
    )
    if decl_patch is None:
        return []
    consumer_patches = _direct_narrow_consumer_patches(
        source_context=source_context,
        receiver=receiver,
        assignment_line=assignment_line,
    )
    if not consumer_patches:
        return []
    return [decl_patch, *consumer_patches]


def _local_declaration_patch(
    *,
    source_context: _SourceContext,
    assignment_line: int,
    receiver: str,
    current_type: str,
) -> PatchDescriptor | None:
    bounds = _function_line_bounds(source_context.source_text, source_context.function)
    if bounds is None:
        return None
    start_line, end_line = bounds
    pattern = re.compile(
        rf"^\s*{re.escape(current_type)}\s+{re.escape(receiver)}\s*;\s*$"
    )
    for line_no, line in enumerate(source_context.source_text.splitlines(), start=1):
        if line_no < start_line or line_no > end_line or line_no >= assignment_line:
            continue
        if pattern.match(line):
            return PatchDescriptor(
                source_file=None,
                line=line_no,
                old=f"{current_type} {receiver};",
                new=f"int {receiver};",
            )
    return None


def _direct_narrow_consumer_patches(
    *,
    source_context: _SourceContext,
    receiver: str,
    assignment_line: int,
) -> list[PatchDescriptor]:
    patches: list[PatchDescriptor] = []
    seen_lines: set[int] = set()
    for site in source_context.call_sites_by_overall.values():
        line_no = int(site.get("line") or 0)
        if line_no <= assignment_line or line_no in seen_lines:
            continue
        prototype = source_context.prototypes.get(str(site.get("call_target") or ""))
        if prototype is None:
            continue
        for arg in site.get("args", []):
            if str(arg.get("text") or "").strip() != receiver:
                continue
            arg_index = int(arg.get("arg_index") or 0)
            if arg_index >= len(prototype.param_types):
                continue
            param_type = prototype.param_types[arg_index]
            if not _is_narrow_integer_local(param_type):
                continue
            patch = _consumer_argument_cast_patch(
                source_context.source_text,
                line_no=line_no,
                call_target=str(site.get("source_call_target") or site.get("call_target")),
                receiver=receiver,
                param_type=param_type,
                arg_index=arg_index,
            )
            if patch is None:
                continue
            patches.append(patch)
            seen_lines.add(line_no)
            break
    return patches


def _function_line_bounds(
    source_text: str,
    function: str,
) -> tuple[int, int] | None:
    span = find_function(source_text, function)
    if span is None:
        return None
    start_line = source_text[: span.sig_start].count("\n") + 1
    end_line = source_text[: span.body_close].count("\n") + 1
    return start_line, end_line


def _consumer_argument_cast_patch(
    source_text: str,
    *,
    line_no: int,
    call_target: str,
    receiver: str,
    param_type: str,
    arg_index: int,
) -> PatchDescriptor | None:
    lines = source_text.splitlines()
    if line_no <= 0 or line_no > len(lines):
        return None
    line = lines[line_no - 1]
    for _, open_index, close_index in _call_spans_in_line(line, call_target):
        arg_spans = _top_level_argument_spans(line, open_index + 1, close_index)
        if arg_index >= len(arg_spans):
            continue
        arg_start, arg_end = arg_spans[arg_index]
        value_start, value_end = _trim_span(line, arg_start, arg_end)
        if line[value_start:value_end] != receiver:
            continue
        new_line = (
            line[:value_start]
            + f"({param_type}) {receiver}"
            + line[value_end:]
        )
        if new_line == line:
            return None
        return PatchDescriptor(
            source_file=None,
            line=line_no,
            old=line,
            new=new_line,
        )
    return None


def _call_spans_in_line(
    line: str,
    call_target: str,
) -> list[tuple[int, int, int]]:
    spans: list[tuple[int, int, int]] = []
    pattern = re.compile(rf"\b{re.escape(call_target)}\s*\(")
    for match in pattern.finditer(line):
        open_index = line.find("(", match.start(), match.end())
        if open_index < 0:
            continue
        close_index = _matching_paren_index(line, open_index)
        if close_index is None:
            continue
        spans.append((match.start(), open_index, close_index))
    return spans


def _matching_paren_index(line: str, open_index: int) -> int | None:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(open_index, len(line)):
        ch = line[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _top_level_argument_spans(
    line: str,
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    depth = 0
    quote: str | None = None
    escaped = False
    arg_start = start
    for index in range(start, end):
        ch = line[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch in "([{":
            depth += 1
            continue
        if ch in ")]}":
            depth = max(depth - 1, 0)
            continue
        if ch == "," and depth == 0:
            spans.append((arg_start, index))
            arg_start = index + 1
    if arg_start < end:
        spans.append((arg_start, end))
    return spans


def _trim_span(line: str, start: int, end: int) -> tuple[int, int]:
    while start < end and line[start].isspace():
        start += 1
    while end > start and line[end - 1].isspace():
        end -= 1
    return start, end


def _call_prep_findings(
    target_calls: list[_AsmCall],
    current_calls: list[_AsmCall],
    source_context: _SourceContext,
) -> list[SignatureFinding]:
    findings: list[SignatureFinding] = []
    current_by_target_ordinal = {
        (call.call_target, call.target_ordinal): call for call in current_calls
    }
    for expected_call in target_calls:
        current_call = current_by_target_ordinal.get(
            (expected_call.call_target, expected_call.target_ordinal)
        )
        if current_call is None:
            continue
        source_site = _source_site_for_call(source_context, current_call)
        for comparison in _arg_prep_comparisons(
            expected_call=expected_call,
            current_call=current_call,
            source_context=source_context,
            source_site=source_site,
        ):
            arg_index = comparison.arg_index
            expected = comparison.expected
            current = comparison.current
            kind = _classify_prep_mismatch(expected, current)
            if kind is None:
                continue
            affected = _affected_call_sites(source_site, arg_index)
            expected_dict = _prep_dict(expected_call, expected, arg_index)
            if expected is None and comparison.expected_register is not None:
                expected_dict["register"] = comparison.expected_register
            current_dict = _prep_dict(current_call, current, arg_index)
            if current is None and comparison.current_register is not None:
                current_dict["register"] = comparison.current_register
            actions = _actions_for_finding(
                kind=kind,
                expected=expected,
                current=current,
                expected_register=comparison.expected_register,
                current_register=comparison.current_register,
                call=current_call,
                source_context=source_context,
                source_site=source_site,
                arg_index=arg_index,
            )
            findings.append(
                SignatureFinding(
                    kind=kind,
                    confidence=_finding_confidence(kind),
                    call_target=current_call.call_target,
                    call_ordinal=current_call.overall_ordinal,
                    arg_register=(
                        current.register if current is not None else
                        expected.register if expected is not None else
                        comparison.current_register or comparison.expected_register
                    ),
                    expected=expected_dict,
                    current=current_dict,
                    source_line=source_site.get("line") if source_site else None,
                    arg_index=arg_index,
                    affected_call_sites=affected,
                    actions=actions,
                )
            )
    return findings


def _arg_prep_comparisons(
    *,
    expected_call: _AsmCall,
    current_call: _AsmCall,
    source_context: _SourceContext,
    source_site: dict | None,
) -> list[_ArgPrepComparison]:
    if source_site is None or not source_site.get("args"):
        expected_args = _ordered_arg_preps(expected_call)
        current_args = _ordered_arg_preps(current_call)
        max_args = max(len(expected_args), len(current_args))
        return [
            _ArgPrepComparison(
                arg_index=arg_index,
                expected_register=(
                    expected_args[arg_index].register
                    if arg_index < len(expected_args)
                    else None
                ),
                current_register=(
                    current_args[arg_index].register
                    if arg_index < len(current_args)
                    else None
                ),
                expected=(
                    expected_args[arg_index]
                    if arg_index < len(expected_args)
                    else None
                ),
                current=(
                    current_args[arg_index]
                    if arg_index < len(current_args)
                    else None
                ),
            )
            for arg_index in range(max_args)
        ]

    call_target = source_site.get("call_target")
    prototype = (
        source_context.prototypes.get(call_target)
        if isinstance(call_target, str)
        else None
    )
    expected_registers = _registers_for_source_args(
        source_site=source_site,
        source_context=source_context,
        prototype=prototype,
        call=expected_call,
        expected=True,
    )
    current_registers = _registers_for_source_args(
        source_site=source_site,
        source_context=source_context,
        prototype=prototype,
        call=current_call,
        expected=False,
    )
    expected_args = _ordered_arg_preps(expected_call)
    current_args = _ordered_arg_preps(current_call)
    comparisons: list[_ArgPrepComparison] = []
    max_args = max(
        len(expected_registers),
        len(current_registers),
        len(expected_args),
        len(current_args),
    )
    for arg_index in range(max_args):
        expected_register = (
            expected_registers[arg_index]
            if arg_index < len(expected_registers)
            else expected_args[arg_index].register
            if arg_index < len(expected_args)
            else None
        )
        current_register = (
            current_registers[arg_index]
            if arg_index < len(current_registers)
            else current_args[arg_index].register
            if arg_index < len(current_args)
            else None
        )
        comparisons.append(
            _ArgPrepComparison(
                arg_index=arg_index,
                expected_register=expected_register,
                current_register=current_register,
                expected=(
                    expected_call.arg_preps.get(expected_register)
                    if expected_register is not None
                    else None
                ),
                current=(
                    current_call.arg_preps.get(current_register)
                    if current_register is not None
                    else None
                ),
            )
        )
    return comparisons


def _registers_for_source_args(
    *,
    source_site: dict,
    source_context: _SourceContext,
    prototype: _PrototypeInfo | None,
    call: _AsmCall,
    expected: bool,
) -> list[str | None]:
    registers: list[str | None] = []
    gpr_index = 0
    fpr_index = 0
    for arg in source_site.get("args", []):
        arg_index = int(arg.get("arg_index", len(registers)))
        bank = (
            _expected_bank_for_source_arg(arg, source_context, prototype, arg_index)
            if expected
            else _current_bank_for_source_arg(arg, source_context, prototype, arg_index)
        )
        if bank is None:
            bank = _next_actual_bank(call, gpr_index, fpr_index)
        if bank == "FPR":
            register = FPR_ARG_ORDER[fpr_index] if fpr_index < len(FPR_ARG_ORDER) else None
            fpr_index += 1
        else:
            register = GPR_ARG_ORDER[gpr_index] if gpr_index < len(GPR_ARG_ORDER) else None
            gpr_index += 1
        registers.append(register)
    return registers


def _expected_bank_for_source_arg(
    source_arg: dict,
    source_context: _SourceContext,
    prototype: _PrototypeInfo | None,
    arg_index: int,
) -> str | None:
    inner_expr = str(source_arg.get("inner_expr") or "").strip()
    expr_bank = _expr_abi_bank(inner_expr, source_context.local_types)
    if expr_bank is not None:
        return expr_bank
    prototype_bank = _prototype_param_bank(prototype, arg_index)
    if prototype_bank is not None:
        return prototype_bank
    return None


def _current_bank_for_source_arg(
    source_arg: dict,
    source_context: _SourceContext,
    prototype: _PrototypeInfo | None,
    arg_index: int,
) -> str | None:
    cast_type = source_arg.get("cast_type")
    if isinstance(cast_type, str):
        cast_bank = _cast_abi_bank(cast_type)
        if cast_bank is not None:
            return cast_bank
    prototype_bank = _prototype_param_bank(prototype, arg_index)
    if prototype_bank is not None and not _is_default_promotion_sensitive(
        prototype,
        arg_index,
    ):
        return prototype_bank
    inner_expr = str(source_arg.get("inner_expr") or "").strip()
    return _expr_abi_bank(inner_expr, source_context.local_types)


def _expr_abi_bank(expr: str, local_types: dict[str, str]) -> str | None:
    if expr in local_types:
        return _type_abi_bank(local_types[expr])
    if _looks_integer(expr):
        return "GPR"
    if _looks_float_literal(expr):
        return "FPR"
    return None


def _prototype_param_bank(
    prototype: _PrototypeInfo | None,
    arg_index: int,
) -> str | None:
    if prototype is None or arg_index >= len(prototype.param_types):
        return None
    return _type_abi_bank(prototype.param_types[arg_index])


def _type_abi_bank(type_text: str) -> str | None:
    normalized = " ".join(type_text.split())
    if "*" in normalized or "(*" in normalized:
        return "GPR"
    if _is_integer_type(normalized):
        return "GPR"
    if _is_float_type(normalized):
        return "FPR"
    return None


def _next_actual_bank(
    call: _AsmCall,
    gpr_index: int,
    fpr_index: int,
) -> str:
    if (
        gpr_index < len(GPR_ARG_ORDER)
        and GPR_ARG_ORDER[gpr_index] in call.arg_preps
    ):
        return "GPR"
    if (
        fpr_index < len(FPR_ARG_ORDER)
        and FPR_ARG_ORDER[fpr_index] in call.arg_preps
    ):
        return "FPR"
    return "GPR"


def _ordered_arg_preps(call: _AsmCall) -> list[_ArgPrep]:
    return sorted(
        call.arg_preps.values(),
        key=lambda prep: ARG_REGISTER_ORDER.get(prep.register, 999),
    )


def _classify_prep_mismatch(
    expected: _ArgPrep | None,
    current: _ArgPrep | None,
) -> str | None:
    if expected is None or current is None:
        return "argument-register-presence-mismatch"
    if expected.bank != current.bank:
        return "argument-bank-mismatch"
    if expected.width != current.width:
        return "argument-width-mismatch"
    if _load_kind_family(expected.load_kind) != _load_kind_family(current.load_kind):
        return "argument-load-kind-mismatch"
    if expected.source_register != current.source_register:
        return "argument-source-register-mismatch"
    return None


def _load_kind_family(load_kind: str) -> str:
    if load_kind.endswith("-load"):
        return load_kind
    if load_kind.startswith("integer"):
        return "integer"
    if load_kind.startswith("float"):
        return "float"
    return load_kind


def _finding_confidence(kind: str) -> str:
    if kind in {"argument-bank-mismatch", "call-target-shape-mismatch"}:
        return "high"
    if kind == "argument-width-mismatch":
        return "medium"
    return "low"


def _prep_dict(call: _AsmCall, prep: _ArgPrep | None, arg_index: int) -> dict:
    base = {
        "call_target": call.call_target,
        "display_target": call.display_target,
        "relocation_target": call.relocation_target,
        "call_ordinal": call.overall_ordinal,
        "target_ordinal": call.target_ordinal,
        "arg_index": arg_index,
    }
    if prep is None:
        base["register"] = None
        return base
    base.update(
        {
            "register": prep.register,
            "bank": prep.bank,
            "width": prep.width,
            "load_kind": prep.load_kind,
            "source_register": prep.source_register,
            "opcode": prep.opcode,
            "text": prep.text,
        }
    )
    return base


def _source_site_for_call(
    source_context: _SourceContext,
    call: _AsmCall | None,
    prefer_current: bool = False,
) -> dict | None:
    if call is None:
        return None
    site = source_context.call_sites.get((call.call_target, call.target_ordinal))
    if site is not None:
        return _localized_source_site(site, "target-ordinal")
    if _is_unresolved_function_offset_call(call, source_context):
        return None
    if call.relocation_target is not None:
        return None
    site = source_context.call_sites_by_overall.get(call.overall_ordinal)
    if site is not None:
        return _localized_source_site(site, "overall-ordinal")
    if prefer_current:
        return None
    site = source_context.call_sites.get((call.call_target, 1))
    if site is not None:
        return _localized_source_site(site, "target-ordinal")
    return None


def _localized_source_site(source_site: dict, localization_kind: str) -> dict:
    localized = dict(source_site)
    localized["localization_kind"] = localization_kind
    return localized


def _affected_call_sites(source_site: dict | None, arg_index: int) -> list[dict]:
    if source_site is None:
        return []
    site = _call_site_without_args(source_site)
    site["arg_index"] = arg_index
    args = source_site.get("args", [])
    if arg_index < len(args):
        site["arg_text"] = args[arg_index]["text"]
    return [site]


def _call_site_without_args(source_site: dict) -> dict:
    return {
        "source_file": source_site.get("source_file"),
        "line": source_site.get("line"),
        "call_target": source_site.get("call_target"),
        "target_ordinal": source_site.get("target_ordinal"),
        "overall_call_ordinal": source_site.get("overall_call_ordinal"),
        "localization_kind": source_site.get("localization_kind"),
    }


def _actions_for_finding(
    *,
    kind: str,
    expected: _ArgPrep | None,
    current: _ArgPrep | None,
    expected_register: str | None,
    current_register: str | None,
    call: _AsmCall,
    source_context: _SourceContext,
    source_site: dict | None,
    arg_index: int,
) -> list[SignatureAction]:
    actions: list[SignatureAction] = []
    affected = _affected_call_sites(source_site, arg_index)
    call_target = source_site.get("call_target") if source_site else None
    prototype = (
        source_context.prototypes.get(call_target)
        if isinstance(call_target, str)
        else None
    )
    source_arg = _source_arg(source_site, arg_index)

    patch_action = _remove_cast_action(
        expected=expected,
        source_context=source_context,
        source_site=source_site,
        source_arg=source_arg,
        prototype=prototype,
        affected=affected,
        arg_index=arg_index,
    )
    if patch_action is not None:
        actions.append(patch_action)

    candidate_action = _prototype_candidate_action(
        kind=kind,
        expected=expected,
        current=current,
        expected_register=expected_register,
        current_register=current_register,
        call=call,
        source_context=source_context,
        source_site=source_site,
        source_arg=source_arg,
        prototype=prototype,
        affected=affected,
        arg_index=arg_index,
    )
    if candidate_action is not None:
        actions.append(candidate_action)

    if (
        candidate_action is None
        and prototype is not None
        and prototype.is_static
        and kind != "argument-source-register-mismatch"
    ):
        actions.append(
            SignatureAction(
                kind="same-tu-static-prototype-audit",
                confidence="medium",
                affected_call_sites=affected,
                reason=(
                    "Call target has a same-translation-unit static "
                    "prototype/definition; audit its parameter type against "
                    "the expected ABI prep."
                ),
            )
        )

    if not actions:
        actions.append(
            SignatureAction(
                kind="call-argument-type-audit",
                confidence="medium" if kind == "argument-width-mismatch" else "low",
                affected_call_sites=affected,
                reason=(
                    "No safe source patch was identified; audit the source "
                    "argument type, visible prototype, and ABI argument prep."
                ),
                rebucket=_argument_rebucket(
                    kind,
                    source_site,
                    call,
                    source_context,
                ),
            )
        )

    return actions


def _prototype_candidate_action(
    *,
    kind: str,
    expected: _ArgPrep | None,
    current: _ArgPrep | None,
    expected_register: str | None,
    current_register: str | None,
    call: _AsmCall,
    source_context: _SourceContext,
    source_site: dict | None,
    source_arg: dict | None,
    prototype: _PrototypeInfo | None,
    affected: list[dict],
    arg_index: int,
) -> SignatureAction | None:
    if kind not in {
        "argument-width-mismatch",
        "argument-register-presence-mismatch",
    }:
        return None
    if source_site is None:
        return None
    if kind == "argument-register-presence-mismatch" and source_arg is None:
        return SignatureAction(
            kind="call-argument-type-audit",
            confidence="low",
            affected_call_sites=affected,
            reason=(
                "The ABI prep has an argument beyond the parsed source call "
                "arguments; treat this as a call arity or macro/source shape "
                "mismatch rather than a prototype type edit."
            ),
            rebucket=_source_call_arity_rebucket(),
        )
    if (
        kind == "argument-register-presence-mismatch"
        and prototype is not None
        and prototype.is_variadic
        and arg_index >= len(prototype.param_types)
    ):
        return SignatureAction(
            kind="call-argument-type-audit",
            confidence="low",
            affected_call_sites=affected,
            reason=(
                "The mismatched ABI prep is in a variadic argument tail, where "
                "default promotions and call shape are not bounded prototype "
                "type edits."
            ),
            rebucket=_variadic_tail_rebucket(),
        )
    if prototype is None:
        return SignatureAction(
            kind="call-argument-type-audit",
            confidence="medium" if kind == "argument-width-mismatch" else "low",
            affected_call_sites=affected,
            reason=(
                "The localized source call has no visible callee prototype, so "
                "the audit cannot produce a bounded prototype candidate."
            ),
            rebucket=_external_prototype_unavailable_rebucket(kind),
        )

    current_type = (
        prototype.param_types[arg_index]
        if arg_index < len(prototype.param_types)
        else None
    )
    current_bank = _type_abi_bank(current_type) if current_type is not None else None
    if kind == "argument-register-presence-mismatch":
        context_expected_register = (
            expected_register if expected is not None or current is None else None
        )
        context_current_register = (
            current_register if current is not None or expected is None else None
        )
        expected_bank = _register_abi_bank(context_expected_register)
        context = _prototype_context(
            call_target=call.call_target,
            arg_index=arg_index,
            current_type=current_type,
            proposed_type=None,
            current_bank=current_bank,
            expected_bank=expected_bank,
            expected_register=context_expected_register,
            current_register=context_current_register,
            prototype_scope=prototype.source_scope,
            candidate_source="register-presence-bank",
            decision_reason=(
                "visible prototype already matches expected ABI bank"
                if current_bank == expected_bank
                else "register-presence evidence is insufficient for a safe type edit"
            ),
        )
        if current_bank == expected_bank:
            return SignatureAction(
                kind="call-argument-type-audit",
                confidence="low",
                affected_call_sites=affected,
                reason="Visible prototype already matches the expected ABI bank.",
                rebucket=_prototype_already_matches_rebucket(context),
            )
        return SignatureAction(
            kind="call-argument-type-audit",
            confidence="low",
            affected_call_sites=affected,
            reason=(
                "Visible prototype bank differs from the expected register bank, "
                "but register-presence evidence alone is not a safe type proposal."
            ),
            rebucket=_prototype_candidate_unsupported_rebucket(context),
        )

    candidate_source = "prep-width"
    proposed_type = _candidate_type_for_prep(expected)
    expected_bank = expected.bank if expected is not None else None
    if proposed_type is None:
        context = _prototype_context(
            call_target=call.call_target,
            arg_index=arg_index,
            current_type=current_type,
            proposed_type=None,
            current_bank=current_bank,
            expected_bank=expected_bank,
            expected_register=expected_register,
            current_register=current_register,
            prototype_scope=prototype.source_scope,
            candidate_source=candidate_source,
            decision_reason="prep evidence is insufficient for a safe type edit",
        )
        return SignatureAction(
            kind="call-argument-type-audit",
            confidence="low",
            affected_call_sites=affected,
            reason=(
                "The expected argument prep does not map to a safe concrete "
                "prototype type."
            ),
            rebucket=_prototype_candidate_unsupported_rebucket(context),
        )

    blast_radius = (
        "same-translation-unit"
        if prototype.source_scope == "same-tu-static"
        else "cross-translation-unit"
    )
    patch_status = "diagnostic"
    patch: PatchDescriptor | None = None
    if prototype.source_scope == "same-tu-static":
        patch_status = _prototype_patch_status(
            prototype,
            arg_index,
            source_site,
            call,
        )
        if proposed_type is None:
            patch_status = "unsupported-type-shape"
        elif current_type is None or not _is_simple_scalar_integer_type(current_type):
            patch_status = "unsupported-type-shape"
        elif _types_are_abi_equivalent(current_type, proposed_type):
            patch_status = "already-matches"
        elif patch_status == "generated":
            split = _split_param_type_name(prototype.param_texts[arg_index])
            if split is None:
                # Unnamed simple scalar parameter (e.g. ``long long``): emit the
                # bare proposed type, never a corrupt ``<type> <typeword>`` form.
                new_param = proposed_type
            else:
                _, param_name = split
                new_param = f"{proposed_type} {param_name}"
            patch = PatchDescriptor(
                source_file=source_site.get("source_file"),
                line=int(prototype.line or source_site.get("line") or 0),
                old=prototype.param_texts[arg_index],
                new=new_param,
            )
    else:
        patch_status = "cross-translation-unit"

    action_kind = (
        "same-tu-static-prototype-candidate"
        if prototype.source_scope == "same-tu-static"
        else "global-prototype-candidate"
    )
    candidate = {
        "kind": "prototype-parameter-type",
        "call_target": call.call_target,
        "arg_index": arg_index,
        "current_type": current_type,
        "proposed_type": proposed_type,
        "current_bank": current_bank,
        "expected_bank": expected_bank,
        "current_register": current_register,
        "expected_register": expected_register,
        "prototype_scope": prototype.source_scope,
        "candidate_source": candidate_source,
        "blast_radius": blast_radius,
        "patch_status": patch_status,
        "localization_kind": source_site.get("localization_kind"),
        "decision_reason": "prep evidence maps to a concrete prototype type",
        "reason": _prototype_candidate_reason(kind, patch_status),
    }
    return SignatureAction(
        kind=action_kind,
        confidence="medium" if action_kind.startswith("same-tu-static") else "low",
        affected_call_sites=affected,
        reason=(
            "Localized argument prep evidence points at the visible callee "
            "prototype as the bounded source lever."
        ),
        patch=patch,
        candidate=candidate,
    )


def _candidate_type_for_prep(prep: _ArgPrep | None) -> str | None:
    if prep is None or prep.bank != "GPR":
        return None
    if prep.opcode == "extsb":
        return "s8"
    if prep.opcode == "lbz":
        return "u8"
    if prep.opcode in {"extsh", "lha"}:
        return "s16"
    if prep.opcode == "lhz":
        return "u16"
    if prep.width == 32 and prep.opcode in {"mr", "lwz", "li", "addi"}:
        return "s32"
    return None


def _normalize_type_text(type_text: str) -> str:
    return " ".join(type_text.split())


def _integer_abi_width(type_text: str) -> int | None:
    normalized = _normalize_type_text(type_text)
    if normalized in {"s8", "u8", "char", "signed char", "unsigned char"}:
        return 8
    if normalized in {"s16", "u16", "short", "signed short", "unsigned short"}:
        return 16
    if normalized in {
        "s32",
        "u32",
        "int",
        "signed int",
        "unsigned int",
        "long",
        "signed long",
        "unsigned long",
    }:
        return 32
    if normalized in {"s64", "u64", "long long"}:
        return 64
    return None


def _types_are_abi_equivalent(current_type: str, proposed_type: str) -> bool:
    if _normalize_type_text(current_type) == _normalize_type_text(proposed_type):
        return True
    current_width = _integer_abi_width(current_type)
    proposed_width = _integer_abi_width(proposed_type)
    return current_width is not None and current_width == proposed_width


def _register_abi_bank(register: str | None) -> str | None:
    if register is None:
        return None
    if register.startswith("f"):
        return "FPR"
    if register.startswith("r"):
        return "GPR"
    return None


def _prototype_context(
    *,
    call_target: str,
    arg_index: int,
    current_type: str | None,
    proposed_type: str | None,
    current_bank: str | None,
    expected_bank: str | None,
    expected_register: str | None,
    current_register: str | None,
    prototype_scope: str,
    candidate_source: str,
    decision_reason: str,
) -> dict[str, object]:
    return {
        "call_target": call_target,
        "arg_index": arg_index,
        "current_type": current_type,
        "proposed_type": proposed_type,
        "current_bank": current_bank,
        "expected_bank": expected_bank,
        "expected_register": expected_register,
        "current_register": current_register,
        "prototype_scope": prototype_scope,
        "candidate_source": candidate_source,
        "decision_reason": decision_reason,
    }


def _prototype_candidate_reason(kind: str, patch_status: str) -> str:
    if patch_status == "generated":
        return "safe same-translation-unit static parameter type patch"
    if patch_status == "cross-translation-unit":
        return "visible non-static prototype requires cross-translation-unit review"
    if kind == "argument-register-presence-mismatch":
        return "argument presence mismatch localized to visible prototype"
    return "argument width mismatch localized to visible prototype"


def _rebucket(
    reason: str,
    work_bucket: str,
    subcategory: str,
    explanation: str,
    **extra: object,
) -> dict[str, object]:
    payload = {
        "reason": reason,
        "work_bucket": work_bucket,
        "subcategory": subcategory,
        "explanation": explanation,
    }
    payload.update(extra)
    return payload


def _prototype_already_matches_rebucket(context: dict[str, object]) -> dict[str, object]:
    return _rebucket(
        "prototype-already-matches-abi-bank",
        "signature-call-type",
        "argument-presence",
        (
            "The localized visible prototype already uses the ABI bank implied "
            "by the expected register, so there is no bounded prototype type edit."
        ),
        prototype_context=context,
    )


def _prototype_candidate_unsupported_rebucket(
    context: dict[str, object],
) -> dict[str, object]:
    return _rebucket(
        "prototype-candidate-unsupported",
        "signature-call-type",
        "argument-presence",
        (
            "The localized visible prototype cannot be turned into a safe "
            "concrete parameter type edit with the available argument-prep "
            "evidence."
        ),
        prototype_context=context,
    )


def _call_target_rebucket(
    source_site: dict | None,
    calls: tuple[_AsmCall | None, ...],
    source_context: _SourceContext,
) -> dict[str, object]:
    if _any_unresolved_function_offset_call(calls, source_context):
        return _intra_function_branch_link_rebucket()
    if source_site is None:
        call = next((candidate for candidate in calls if candidate is not None), None)
        if call is not None and call.relocation_target is not None:
            return _relocated_call_without_source_rebucket()
        return _rebucket(
            "call-not-localized",
            "structural-reconstruction",
            "call-source-localization",
            (
                "The call shape differs, but signature audit could not map the "
                "ASM call ordinal back to a source call site."
            ),
        )
    return _rebucket(
        "call-offset-shift",
        "structural-reconstruction",
        "call-target-shape",
        (
            "The call target or ordinal differs; signature audit cannot "
            "produce a bounded type/prototype patch for this call shape."
        ),
    )


def _argument_rebucket(
    kind: str,
    source_site: dict | None,
    call: _AsmCall | None,
    source_context: _SourceContext,
) -> dict[str, object]:
    if source_site is None:
        if _is_unresolved_function_offset_call(call, source_context):
            return _intra_function_branch_link_rebucket()
        if call is not None and call.relocation_target is not None:
            return _relocated_call_without_source_rebucket()
        return _rebucket(
            "call-not-localized",
            "structural-reconstruction",
            "call-source-localization",
            (
                "The argument prep differs, but signature audit could not map "
                "the ASM call ordinal back to a source call site."
            ),
        )
    if kind == "argument-source-register-mismatch":
        return _rebucket(
            "register-source-cascade",
            "register-allocator",
            "argument-source-register",
            (
                "The ABI register is the same, but the source register differs; "
                "signature audit has no bounded source patch."
            ),
        )
    if kind == "argument-width-mismatch":
        return _external_prototype_unavailable_rebucket(kind)
    if kind == "argument-load-kind-mismatch":
        return _rebucket(
            "type-evidence-missing",
            "signature-call-type",
            "argument-load-kind",
            (
                "The load kind differs, but source type evidence is too weak "
                "for a bounded field or prototype patch."
            ),
        )
    if kind == "argument-bank-mismatch":
        return _rebucket(
            "prototype-candidate-missing",
            "signature-call-type",
            "argument-bank",
            (
                "The ABI argument bank differs, but no safe cast removal or "
                "prototype source candidate was found."
            ),
        )
    return _rebucket(
        "prototype-candidate-missing",
        "signature-call-type",
        "argument-presence",
        (
            "The argument register presence differs, but no bounded prototype "
            "or argument source candidate was found."
        ),
    )


def _external_prototype_unavailable_rebucket(kind: str) -> dict[str, object]:
    subcategory = (
        "argument-width"
        if kind == "argument-width-mismatch"
        else "argument-presence"
    )
    return _rebucket(
        "external-prototype-unavailable",
        "signature-call-type",
        subcategory,
        (
            "The localized call target has no visible prototype or same-TU "
            "definition, so a bounded prototype candidate cannot be produced."
        ),
    )


def _variadic_tail_rebucket() -> dict[str, object]:
    return _rebucket(
        "variadic-prototype-tail",
        "signature-call-type",
        "argument-presence",
        (
            "The argument presence mismatch is in a variadic tail where "
            "default promotions and callsite shape must be audited manually."
        ),
    )


def _source_call_arity_rebucket() -> dict[str, object]:
    return _rebucket(
        "source-call-arity-mismatch",
        "signature-call-type",
        "argument-presence",
        (
            "The ABI prep contains an argument position that is not present in "
            "the parsed source call expression."
        ),
    )


def _relocated_call_without_source_rebucket() -> dict[str, object]:
    return _rebucket(
        "relocated-call-not-in-source",
        "structural-reconstruction",
        "relocated-helper-no-source-call",
        (
            "The ASM call resolves through R_PPC_REL24, but no matching source "
            "call expression was found; treat it as generated helper or "
            "structural call-shape work before auditing argument types."
        ),
    )


def _intra_function_branch_link_rebucket() -> dict[str, object]:
    return _rebucket(
        "intra-function-branch-link",
        "structural-reconstruction",
        "branch-link-control-flow",
        (
            "The branch-link target is an unresolved function-local offset; "
            "treat this as control-flow or structural reconstruction before "
            "auditing call argument types."
        ),
    )


def _is_unresolved_function_offset_call(
    call: _AsmCall | None,
    source_context: _SourceContext,
) -> bool:
    if call is None or call.relocation_target is not None:
        return False
    target = call.display_target or call.call_target
    return _is_function_offset_target(target, source_context.function)


def _any_unresolved_function_offset_call(
    calls: tuple[_AsmCall | None, ...],
    source_context: _SourceContext,
) -> bool:
    return any(
        _is_unresolved_function_offset_call(call, source_context)
        for call in calls
    )


def _is_function_offset_target(target: str, function: str) -> bool:
    return bool(
        re.fullmatch(
            rf"{re.escape(function)}\+0x[0-9A-Fa-f]+",
            target,
        )
    )


def _source_arg(source_site: dict | None, arg_index: int) -> dict | None:
    if source_site is None:
        return None
    args = source_site.get("args", [])
    if arg_index >= len(args):
        return None
    return args[arg_index]


def _remove_cast_action(
    *,
    expected: _ArgPrep | None,
    source_context: _SourceContext,
    source_site: dict | None,
    source_arg: dict | None,
    prototype: _PrototypeInfo | None,
    affected: list[dict],
    arg_index: int,
) -> SignatureAction | None:
    if expected is None or source_site is None or source_arg is None:
        return None
    if source_site.get("localization_kind") == "overall-ordinal":
        return None
    cast_type = source_arg.get("cast_type")
    inner_expr = source_arg.get("inner_expr")
    if not isinstance(cast_type, str) or not isinstance(inner_expr, str):
        return None
    expected_bank = expected.bank
    cast_bank = _cast_abi_bank(cast_type)
    if cast_bank is None or cast_bank == expected_bank:
        return None
    if not _is_default_promotion_sensitive(prototype, arg_index):
        return None
    if not _inner_expr_matches_bank(inner_expr, expected_bank, source_context.local_types):
        return None

    old = str(source_arg["text"]).strip()
    new = inner_expr.strip()
    return SignatureAction(
        kind="remove-call-arg-cast",
        confidence="high",
        affected_call_sites=affected,
        reason=(
            f"Expected ABI prep uses {expected_bank}, but the source argument "
            f"starts with a {cast_bank} cast on an expression with matching "
            "inner type evidence. With no fixed prototype controlling this "
            "argument, removing the cast is a safe candidate."
        ),
        patch=PatchDescriptor(
            source_file=source_site.get("source_file"),
            line=int(source_site.get("line") or 0),
            old=old,
            new=new,
        ),
    )


def _cast_abi_bank(cast_type: str) -> str | None:
    if "*" in cast_type:
        return "GPR"
    normalized = " ".join(cast_type.split())
    if normalized in FLOAT_CAST_TYPES:
        return "FPR"
    if normalized in INTEGER_CAST_TYPES:
        return "GPR"
    return None


def _is_default_promotion_sensitive(
    prototype: _PrototypeInfo | None,
    arg_index: int,
) -> bool:
    if prototype is None or not prototype.has_prototype:
        return True
    return prototype.is_variadic and arg_index >= len(prototype.param_types)


def _inner_expr_matches_bank(
    inner_expr: str,
    expected_bank: str,
    local_types: dict[str, str],
) -> bool:
    expr = inner_expr.strip()
    if expr in local_types:
        if expected_bank == "GPR":
            return _is_integer_type(local_types[expr])
        if expected_bank == "FPR":
            return _is_float_type(local_types[expr])
    if expected_bank == "GPR":
        return _looks_integer(expr)
    if expected_bank == "FPR":
        return _looks_float_literal(expr)
    return False


def _looks_float_literal(expr: str) -> bool:
    return bool(re.match(r"^-?(?:\d+\.\d*|\.\d+)(?:[fFlL])?$", expr.strip()))


def _merge_findings(findings: list[SignatureFinding]) -> list[SignatureFinding]:
    merged: list[SignatureFinding] = []
    by_key: dict[tuple, SignatureFinding] = {}
    for finding in findings:
        key = (
            finding.kind,
            finding.call_target,
            finding.arg_index,
            _finding_patch_key(finding),
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = finding
            merged.append(finding)
            continue
        existing.affected_call_sites = _merge_call_site_lists(
            existing.affected_call_sites,
            finding.affected_call_sites,
        )
        existing.actions = _merge_actions(existing.actions, finding.actions)
    return merged


def _finding_patch_key(finding: SignatureFinding) -> tuple:
    patch_parts = []
    for action in finding.actions:
        if action.source_variant is not None:
            patch_parts.append(
                (
                    action.kind,
                    action.source_variant.variant_id,
                    action.source_variant.label,
                )
            )
            continue
        if action.patch is None:
            continue
        patch_parts.append(
            (
                action.kind,
                action.patch.source_file,
                action.patch.line,
                action.patch.old,
                action.patch.new,
            )
        )
    if patch_parts:
        return tuple(patch_parts)
    return (finding.call_ordinal, finding.arg_register, finding.source_line)


def _merge_actions(
    existing: list[SignatureAction],
    incoming: list[SignatureAction],
) -> list[SignatureAction]:
    by_key = {_action_merge_key(action): action for action in existing}
    for action in incoming:
        key = _action_merge_key(action)
        current = by_key.get(key)
        if current is None:
            existing.append(action)
            by_key[key] = action
            continue
        current.affected_call_sites = _merge_call_site_lists(
            current.affected_call_sites,
            action.affected_call_sites,
        )
    return existing


def _action_merge_key(action: SignatureAction) -> tuple:
    if action.source_variant is not None:
        return (
            action.kind,
            action.source_variant.variant_id,
            action.source_variant.label,
        )
    if action.patch is not None:
        return (
            action.kind,
            action.patch.source_file,
            action.patch.line,
            action.patch.old,
            action.patch.new,
        )
    if action.rebucket:
        return (
            action.kind,
            action.rebucket.get("reason"),
            action.rebucket.get("work_bucket"),
            action.rebucket.get("subcategory"),
        )
    return (action.kind,)


def _merge_call_site_lists(first: list[dict], second: list[dict]) -> list[dict]:
    merged = list(first)
    seen = {_call_site_key(site) for site in merged}
    for site in second:
        key = _call_site_key(site)
        if key in seen:
            continue
        merged.append(site)
        seen.add(key)
    return merged


def _call_site_key(site: dict) -> tuple:
    return (
        site.get("source_file"),
        site.get("line"),
        site.get("call_target"),
        site.get("target_ordinal"),
        site.get("arg_index"),
    )
