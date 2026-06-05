"""Audit checkdiff call-prep signature/type mismatches against source calls."""

from __future__ import annotations

import re
from dataclasses import dataclass
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
class SignatureAction:
    kind: str
    confidence: str
    affected_call_sites: list[dict]
    reason: str
    patch: PatchDescriptor | None = None
    validation: dict | None = None
    rebucket: dict[str, object] | None = None


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


@dataclass
class _AsmCall:
    call_target: str
    overall_ordinal: int
    target_ordinal: int
    instruction_index: int
    arg_preps: dict[str, _ArgPrep]


@dataclass(frozen=True)
class _ArgPrepComparison:
    arg_index: int
    expected_register: str | None
    current_register: str | None
    expected: _ArgPrep | None
    current: _ArgPrep | None


@dataclass(frozen=True)
class _PrototypeInfo:
    has_prototype: bool
    is_static: bool
    is_variadic: bool
    param_types: tuple[str, ...]


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
) -> SignatureAuditReport:
    """Run candidate source patches and attach checkdiff validation metadata."""
    for finding in report.findings:
        for action in finding.actions:
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
            candidate_match = _payload_match_percent(payload)
            match = bool(payload.get("match") is True)
            delta = (
                candidate_match - baseline_match_percent
                if candidate_match is not None and baseline_match_percent is not None
                else None
            )
            status = "validated" if match else "scored"
            if delta is not None and delta <= 0 and not match:
                status = "non-improving"
            action.validation = {
                "status": status,
                "match": match,
                "baseline_match_percent": baseline_match_percent,
                "candidate_match_percent": candidate_match,
                "delta_match_percent": delta,
                "classification": _classification_primary(payload),
            }
    report.summary = _summarize_report(report.findings)
    return report


SOURCE_LEVER_ACTION_KINDS = {
    "same-tu-static-prototype-audit",
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

    for finding in findings:
        for action in finding.actions:
            action_count += 1
            action_kind_counts[action.kind] = (
                action_kind_counts.get(action.kind, 0) + 1
            )
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


def _summary_stop_condition(
    *,
    finding_count: int,
    patch_candidate_count: int,
    validated_patch_candidate_count: int,
    audit_only_unrebucketed: int,
    source_lever_action_count: int,
    rebucketed_audit_only_count: int,
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


def _payload_match_percent(payload: dict) -> float | None:
    for key in ("fuzzy_match_percent", "match_percent", "percent"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
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
    for instr_index, instr in enumerate(instrs):
        if instr.opcode != "bl" or not instr.operands:
            continue
        target = _normalize_call_target(instr.operands[0])
        if target is None:
            continue
        target_counts[target] = target_counts.get(target, 0) + 1
        calls.append(
            _AsmCall(
                call_target=target,
                overall_ordinal=len(calls) + 1,
                target_ordinal=target_counts[target],
                instruction_index=instr.index,
                arg_preps=_collect_arg_preps(instrs, instr_index, window),
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
    call_sites: dict[tuple[str, int], dict]
    prototypes: dict[str, _PrototypeInfo]
    local_types: dict[str, str]


def _build_source_context(
    source_text: str,
    function: str,
    source_file: str | None,
) -> _SourceContext:
    span = find_function(source_text, function)
    if span is None:
        return _SourceContext(
            call_sites={},
            prototypes=_parse_visible_prototypes(source_text),
            local_types={},
        )

    full_function = source_text[span.sig_start:span.full_end]
    body_text = source_text[span.body_open:span.full_end]
    body_line_offset = source_text[: span.body_open].count("\n")
    call_sites: dict[tuple[str, int], dict] = {}
    target_counts: dict[str, int] = {}
    overall_ordinal = 0
    for site in find_call_sites(body_text):
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
        call_sites[(site.call_target, target_ordinal)] = {
            "source_file": source_file,
            "line": abs_line,
            "call_target": site.call_target,
            "target_ordinal": target_ordinal,
            "overall_call_ordinal": overall_ordinal,
            "args": args,
        }

    return _SourceContext(
        call_sites=call_sites,
        prototypes=_parse_visible_prototypes(source_text),
        local_types=_extract_local_types(full_function),
    )


def _parse_visible_prototypes(source_text: str) -> dict[str, _PrototypeInfo]:
    prototypes: dict[str, _PrototypeInfo] = {}
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
        open_idx = match.end() - 1
        close_idx = _matching_paren(source_text, open_idx)
        if close_idx is None:
            continue
        suffix = source_text[close_idx + 1 :].lstrip()
        if not suffix or suffix[0] not in ";{":
            continue
        params = source_text[open_idx + 1 : close_idx].strip()
        is_variadic = "..." in params
        param_types = tuple(_extract_param_types(params))
        existing = prototypes.get(name)
        info = _PrototypeInfo(
            has_prototype=True,
            is_static="static" in prefix.split(),
            is_variadic=is_variadic,
            param_types=param_types,
        )
        if existing is None or info.is_static:
            prototypes[name] = info
    return prototypes


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
            r"^(.+?)(?:\s+(?P<stars>\*+)?\s*[A-Za-z_]\w*)$",
            cleaned,
        )
        if match is not None:
            cleaned = match.group(1).strip()
            if match.group("stars"):
                cleaned = f"{cleaned} {match.group('stars')}"
        param_types.append(cleaned)
    return param_types


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
        source_site = _source_site_for_call(
            source_context,
            current_call or expected_call,
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
            rebucket=_call_target_rebucket(source_site),
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
        "call_ordinal": call.overall_ordinal,
        "target_ordinal": call.target_ordinal,
    }


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
    comparisons: list[_ArgPrepComparison] = []
    max_args = max(len(expected_registers), len(current_registers))
    for arg_index in range(max_args):
        expected_register = (
            expected_registers[arg_index]
            if arg_index < len(expected_registers)
            else None
        )
        current_register = (
            current_registers[arg_index]
            if arg_index < len(current_registers)
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
        return site
    if prefer_current:
        return None
    return source_context.call_sites.get((call.call_target, 1))


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
    }


def _actions_for_finding(
    *,
    kind: str,
    expected: _ArgPrep | None,
    current: _ArgPrep | None,
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

    if prototype is not None and prototype.is_static:
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
                rebucket=_argument_rebucket(kind, source_site),
            )
        )

    return actions


def _rebucket(
    reason: str,
    work_bucket: str,
    subcategory: str,
    explanation: str,
) -> dict[str, object]:
    return {
        "reason": reason,
        "work_bucket": work_bucket,
        "subcategory": subcategory,
        "explanation": explanation,
    }


def _call_target_rebucket(source_site: dict | None) -> dict[str, object]:
    if source_site is None:
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


def _argument_rebucket(kind: str, source_site: dict | None) -> dict[str, object]:
    if source_site is None:
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
        return _rebucket(
            "width-prototype-candidate-missing",
            "signature-call-type",
            "argument-width",
            (
                "The argument width shaping differs, but no bounded cast or "
                "prototype source candidate was found."
            ),
        )
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
