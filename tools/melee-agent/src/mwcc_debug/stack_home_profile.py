"""Stable stack-home identities and generalized stack-layout distance."""

from __future__ import annotations

import json
import re
from dataclasses import astuple, dataclass
from typing import Any, Mapping

_REGISTER_RE = re.compile(r"\b(?P<kind>[fr])(?P<number>\d+)\b", re.IGNORECASE)
_STACK_OFFSET_RE = re.compile(
    r"(?<![\w@])[-+]?(?:0x[0-9a-f]+|\d+)\s*\(\s*r1\s*\)",
    re.IGNORECASE,
)
_UNSTABLE_TEMP_RE = re.compile(r"(?<!\w)@\d+(?!\w)")
_EVIDENCE_SITE_RE = re.compile(r"\bB(?P<block>\d+):(?P<instr>\d+)\b")
_SPACE_RE = re.compile(r"\s+")
_PUNCTUATION_SPACE_RE = re.compile(r"\s*([,()[\]])\s*")

_BLOCKER_ORDER = {
    "missing-frame-size": 0,
    "frame-size-mismatch": 1,
    "incomplete-frame-report": 2,
    "incomplete-stack-home-assignment": 3,
    "incomplete-stack-slot-evidence": 4,
    "unresolved-compiler-temp-home": 5,
    "ambiguous-compiler-temp-home": 6,
    "duplicate-stack-home-identity": 7,
}


@dataclass(frozen=True, slots=True)
class StackHome:
    identity: str
    offset: int
    order: int
    reference_kind: str


@dataclass(frozen=True, slots=True)
class StackHomeProfile:
    frame_size: int | None
    homes: tuple[StackHome, ...]
    complete: bool
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StackHomeDistance:
    unresolved_or_mismatched_homes: int
    total_absolute_offset_delta: int
    home_order_inversions: int
    absolute_frame_size_delta: int

    def as_tuple(self) -> tuple[int, ...]:
        return astuple(self)


@dataclass(frozen=True, slots=True)
class _PendingHome:
    identity: str
    offset: int
    reference_kind: str
    sequence_key: tuple[int, ...]
    origin: str


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _ordered_blockers(blockers: set[str]) -> tuple[str, ...]:
    return tuple(sorted(blockers, key=lambda item: (_BLOCKER_ORDER.get(item, 99), item)))


def _normalize_text(value: object) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip())


def _normalize_first_def(opcode: object, operands: object) -> tuple[str, str] | None:
    normalized_opcode = _normalize_text(opcode).lower()
    normalized_operands = _normalize_text(operands)
    if not normalized_opcode:
        return None

    normalized_operands = _STACK_OFFSET_RE.sub("<stack>(r1)", normalized_operands)
    normalized_operands = _UNSTABLE_TEMP_RE.sub("<temp>", normalized_operands)
    parts = normalized_operands.split(",", maxsplit=1)
    if parts and re.fullmatch(r"[fr]\d+", parts[0].strip(), re.IGNORECASE):
        parts[0] = "<dst>"
        normalized_operands = ",".join(parts)

    def stable_register(match: re.Match[str]) -> str:
        kind = match.group("kind").lower()
        number = int(match.group("number"))
        if kind == "r" and number == 1:
            return "r1"
        return f"<{kind}reg>"

    normalized_operands = _REGISTER_RE.sub(stable_register, normalized_operands)
    normalized_operands = _PUNCTUATION_SPACE_RE.sub(r"\1", normalized_operands)
    normalized_operands = _SPACE_RE.sub(" ", normalized_operands).strip()
    return normalized_opcode, normalized_operands


def _first_def_from_candidate(
    candidate: Mapping[str, Any],
    owner: Mapping[str, Any],
) -> tuple[str, str] | None:
    first_def = candidate.get("first_def")
    if not isinstance(first_def, Mapping):
        first_def = owner.get("first_def")
    if isinstance(first_def, Mapping):
        return _normalize_first_def(first_def.get("opcode"), first_def.get("operands"))

    if str(owner.get("confidence") or "").lower() != "pcode-first-def":
        return None
    expression = _normalize_text(owner.get("expression"))
    if not expression:
        return None
    opcode, separator, operands = expression.partition(" ")
    if not separator:
        return None
    return _normalize_first_def(opcode, operands)


def _source_owner_signature(owner: Mapping[str, Any]) -> dict[str, object] | None:
    expression = _normalize_text(owner.get("expression"))
    expression = _STACK_OFFSET_RE.sub("<stack>(r1)", expression)
    expression = _UNSTABLE_TEMP_RE.sub("<temp>", expression)
    name = _normalize_text(owner.get("name"))
    if not expression and not name:
        return None

    signature: dict[str, object] = {
        "confidence": _normalize_text(owner.get("confidence")).lower(),
        "expression": expression,
        "name": name,
    }
    for key in ("source_file", "source_line", "source_col"):
        value = owner.get(key)
        if value is not None:
            signature[key] = value
    return signature


def _compiler_identity(
    candidate: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    opcode = _normalize_text(candidate.get("opcode")).lower()
    owner = candidate.get("source_owner")
    if not isinstance(owner, Mapping):
        owner = candidate.get("nearest_source_expression")
    if not opcode or not isinstance(owner, Mapping):
        return None, "unresolved-compiler-temp-home"

    first_def = _first_def_from_candidate(candidate, owner)
    owner_signature = _source_owner_signature(owner)
    if first_def is None or owner_signature is None:
        return None, "unresolved-compiler-temp-home"

    first_def_opcode, first_def_operands = first_def
    if owner_signature.get("confidence") == "pcode-first-def":
        owner_signature["expression"] = f"{first_def_opcode} {first_def_operands}"
    payload = {
        "access_opcode": opcode,
        "first_def": {
            "opcode": first_def_opcode,
            "operands": first_def_operands,
        },
        "source_owner": owner_signature,
    }
    return (
        "compiler-temp:" + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        None,
    )


def _candidate_sequence_key(candidate: Mapping[str, Any], index: int) -> tuple[int, ...] | None:
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) for item in evidence):
        return None
    match = _EVIDENCE_SITE_RE.search(evidence[0])
    if match is None:
        return None
    return (0, int(match.group("block")), int(match.group("instr")), 1, index)


def _assignment_sequence_key(assignment: Mapping[str, Any], order: int) -> tuple[int, ...]:
    first_access = assignment.get("first_access")
    if isinstance(first_access, Mapping):
        block = first_access.get("block_idx")
        instr = first_access.get("instr_idx")
        if _is_int(block) and _is_int(instr):
            return (0, int(block), int(instr), 0, order)
    return (1, order)


def _named_homes(
    current: Mapping[str, Any],
    blockers: set[str],
) -> tuple[list[_PendingHome], list[Mapping[str, Any]]]:
    raw_assignments = current.get("stack_home_assignments")
    status = current.get("stack_home_assignment_status")
    if not isinstance(raw_assignments, list) or not isinstance(status, str):
        blockers.add("incomplete-frame-report")
        return [], []
    if status not in {
        "resolved-symbolic-homes",
        "unavailable-no-resolved-symbolic-homes",
    }:
        blockers.add("incomplete-frame-report")
    if bool(raw_assignments) != (status == "resolved-symbolic-homes"):
        blockers.add("incomplete-frame-report")

    homes: list[_PendingHome] = []
    assignments: list[Mapping[str, Any]] = []
    assignment_orders: list[int] = []
    for raw in raw_assignments:
        if not isinstance(raw, Mapping):
            blockers.add("incomplete-stack-home-assignment")
            continue
        symbol = raw.get("symbol")
        offset = raw.get("offset")
        order = raw.get("assignment_order")
        if not isinstance(symbol, str) or not symbol or not _is_int(offset) or not _is_int(order) or int(order) < 0:
            blockers.add("incomplete-stack-home-assignment")
            continue
        assignments.append(raw)
        assignment_orders.append(int(order))
        homes.append(
            _PendingHome(
                identity=f"symbol:{symbol}",
                offset=int(offset),
                reference_kind="absolute" if _is_int(raw.get("expected_offset")) else "proxy",
                sequence_key=_assignment_sequence_key(raw, int(order)),
                origin="symbol",
            )
        )
    if sorted(assignment_orders) != list(range(len(raw_assignments))):
        blockers.add("incomplete-stack-home-assignment")
    return homes, assignments


def _candidate_matches_named_home(
    candidate: Mapping[str, Any],
    assignments: list[Mapping[str, Any]],
) -> int:
    offset = candidate.get("current_offset")
    opcode = _normalize_text(candidate.get("opcode")).lower()
    return sum(
        raw.get("offset") == offset
        and opcode in {_normalize_text(item).lower() for item in raw.get("opcodes", []) if isinstance(item, str)}
        for raw in assignments
    )


def _compiler_homes(
    report: Mapping[str, Any] | None,
    assignments: list[Mapping[str, Any]],
    frame_size: int | None,
    blockers: set[str],
) -> list[_PendingHome]:
    if report is None:
        return []
    if not isinstance(report, Mapping):
        blockers.add("incomplete-stack-slot-evidence")
        return []
    candidates = report.get("candidates")
    candidate_count = report.get("candidate_count")
    status = report.get("status")
    if (
        not isinstance(candidates, list)
        or not _is_int(candidate_count)
        or int(candidate_count) != len(candidates)
        or status not in {"ok", "no-candidates"}
        or (status == "ok") != bool(candidates)
    ):
        blockers.add("incomplete-stack-slot-evidence")
        return []
    report_frame_size = report.get("frame_size")
    if report_frame_size is not None and report_frame_size != frame_size:
        blockers.add("frame-size-mismatch")

    homes: list[_PendingHome] = []
    for index, raw in enumerate(candidates):
        if not isinstance(raw, Mapping):
            blockers.add("incomplete-stack-slot-evidence")
            continue
        opcode = _normalize_text(raw.get("opcode")).lower()
        offset = raw.get("current_offset")
        mismatch = raw.get("mismatch")
        sequence_key = _candidate_sequence_key(raw, index)
        if not opcode or not _is_int(offset) or not isinstance(mismatch, Mapping) or sequence_key is None:
            blockers.add("incomplete-stack-slot-evidence")
            continue
        if mismatch.get("opcode") != raw.get("opcode") or mismatch.get("current_offset") != offset:
            blockers.add("incomplete-stack-slot-evidence")
            continue

        named_matches = _candidate_matches_named_home(raw, assignments)
        if named_matches == 1:
            continue
        if named_matches > 1:
            blockers.add("ambiguous-compiler-temp-home")
            continue

        identity, blocker = _compiler_identity(raw)
        if blocker is not None or identity is None:
            blockers.add(blocker or "unresolved-compiler-temp-home")
            continue
        homes.append(
            _PendingHome(
                identity=identity,
                offset=int(offset),
                reference_kind=(
                    "absolute"
                    if _is_int(raw.get("expected_offset")) or _is_int(mismatch.get("expected_offset"))
                    else "proxy"
                ),
                sequence_key=sequence_key,
                origin="compiler-temp",
            )
        )
    return homes


def build_stack_home_profile(
    frame_report: Mapping[str, Any],
    stack_slot_report: Mapping[str, Any] | None,
) -> StackHomeProfile:
    """Build an immutable profile from existing frame and stack-slot reports."""

    blockers: set[str] = set()
    if not isinstance(frame_report, Mapping) or not isinstance(frame_report.get("current"), Mapping):
        return StackHomeProfile(None, (), False, ("incomplete-frame-report",))
    current = frame_report["current"]
    frame_size = current.get("frame_size")
    if frame_size is None:
        blockers.add("missing-frame-size")
    elif not _is_int(frame_size) or int(frame_size) < 0:
        blockers.add("incomplete-frame-report")
        frame_size = None
    else:
        frame_size = int(frame_size)

    pending, assignments = _named_homes(current, blockers)
    pending.extend(
        _compiler_homes(
            stack_slot_report,
            assignments,
            frame_size,
            blockers,
        )
    )

    by_identity: dict[str, list[_PendingHome]] = {}
    for home in pending:
        by_identity.setdefault(home.identity, []).append(home)
    for repeated in by_identity.values():
        if len(repeated) < 2:
            continue
        if any(home.origin == "compiler-temp" for home in repeated):
            blockers.add("ambiguous-compiler-temp-home")
        else:
            blockers.add("duplicate-stack-home-identity")

    ordered = sorted(pending, key=lambda home: (home.sequence_key, home.identity))
    homes = tuple(
        StackHome(home.identity, home.offset, order, home.reference_kind) for order, home in enumerate(ordered)
    )
    blocker_tuple = _ordered_blockers(blockers)
    return StackHomeProfile(frame_size, homes, not blocker_tuple, blocker_tuple)


def _validate_profile(profile: StackHomeProfile) -> dict[str, StackHome]:
    if not profile.complete or profile.blockers or not _is_int(profile.frame_size):
        raise ValueError("incomplete-stack-home-evidence")
    by_identity: dict[str, StackHome] = {}
    orders: set[int] = set()
    for home in profile.homes:
        if (
            not home.identity
            or not _is_int(home.offset)
            or not _is_int(home.order)
            or home.order < 0
            or home.reference_kind not in {"absolute", "proxy", "mixed"}
            or home.identity in by_identity
            or home.order in orders
        ):
            raise ValueError("incomplete-stack-home-evidence")
        by_identity[home.identity] = home
        orders.add(home.order)
    if orders != set(range(len(profile.homes))):
        raise ValueError("incomplete-stack-home-evidence")
    return by_identity


def _order_inversions(
    candidate: StackHomeProfile,
    reference: StackHomeProfile,
    common: set[str],
) -> int:
    candidate_order = [
        home.identity for home in sorted(candidate.homes, key=lambda item: item.order) if home.identity in common
    ]
    reference_order = [
        home.identity for home in sorted(reference.homes, key=lambda item: item.order) if home.identity in common
    ]
    reference_positions = {identity: index for index, identity in enumerate(reference_order)}
    positions = [reference_positions[identity] for identity in candidate_order]
    return sum(
        positions[left] > positions[right]
        for left in range(len(positions))
        for right in range(left + 1, len(positions))
    )


def stack_home_distance(
    candidate: StackHomeProfile,
    reference: StackHomeProfile,
) -> StackHomeDistance:
    """Join by stable identity and score membership, movement, order, and frame."""

    candidate_by_identity = _validate_profile(candidate)
    reference_by_identity = _validate_profile(reference)
    candidate_identities = set(candidate_by_identity)
    reference_identities = set(reference_by_identity)
    common = candidate_identities & reference_identities

    moved = sum(candidate_by_identity[identity].offset != reference_by_identity[identity].offset for identity in common)
    membership = len(candidate_identities ^ reference_identities)
    total_delta = sum(
        abs(candidate_by_identity[identity].offset - reference_by_identity[identity].offset) for identity in common
    )
    return StackHomeDistance(
        unresolved_or_mismatched_homes=membership + moved,
        total_absolute_offset_delta=total_delta,
        home_order_inversions=_order_inversions(candidate, reference, common),
        absolute_frame_size_delta=abs(int(candidate.frame_size) - int(reference.frame_size)),
    )
