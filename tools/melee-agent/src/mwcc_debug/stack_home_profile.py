"""Stable stack-home identities and generalized stack-layout distance."""

from __future__ import annotations

import json
import re
from dataclasses import astuple, dataclass
from typing import Any, Mapping

from .stack_slot_bridge import STACK_ACCESS_OPCODES

_REGISTER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<kind>[fr])(?P<number>\d+)(?!\d)",
    re.IGNORECASE,
)
_ADDRESS_OFFSET_RE = re.compile(
    r"[-+]?(?:0x[0-9a-f]+|\d+)\s*\(\s*r\d+\s*\)",
    re.IGNORECASE,
)
_UNSTABLE_TEMP_RE = re.compile(r"@\d+")
_COMPILER_VIRTUAL_RE = re.compile(r"(?<![A-Za-z0-9_])(?P<kind>IG:|v)\d+(?![A-Za-z0-9_])")
_EVIDENCE_SITE_RE = re.compile(r"\bB(?P<block>\d+):(?P<instr>\d+)\b")
_SPACE_RE = re.compile(r"\s+")
_PUNCTUATION_SPACE_RE = re.compile(r"\s*([,()[\]])\s*")
_FIRST_DEF_OPCODE_RE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9]*|psq_l|psq_lu|psq_st|psq_stu)(?:[.+-])?",
    re.IGNORECASE,
)
_MISSING = object()

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


def _normalize_identity_text(value: object) -> str:
    normalized = _normalize_text(value)
    normalized = _ADDRESS_OFFSET_RE.sub("<offset>", normalized)
    normalized = _UNSTABLE_TEMP_RE.sub("<temp>", normalized)

    def stable_virtual(match: re.Match[str]) -> str:
        return "<ig>" if match.group("kind") == "IG:" else "<virtual>"

    normalized = _COMPILER_VIRTUAL_RE.sub(stable_virtual, normalized)

    def stable_register(match: re.Match[str]) -> str:
        return f"<{match.group('kind').lower()}reg>"

    normalized = _REGISTER_RE.sub(stable_register, normalized)
    normalized = _PUNCTUATION_SPACE_RE.sub(r"\1", normalized)
    return _SPACE_RE.sub(" ", normalized).strip()


def _normalize_access_opcode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.lower()
    return normalized if normalized in STACK_ACCESS_OPCODES else None


def _normalize_first_def_opcode(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or _FIRST_DEF_OPCODE_RE.fullmatch(value) is None
        or _REGISTER_RE.fullmatch(value) is not None
    ):
        return None
    return value.lower()


def _normalize_first_def(opcode: object, operands: object) -> tuple[str, str] | None:
    normalized_opcode = _normalize_first_def_opcode(opcode)
    if normalized_opcode is None or not isinstance(operands, str):
        return None
    normalized_operands = _normalize_identity_text(operands)
    if not normalized_operands:
        return None

    parts = normalized_operands.split(",", maxsplit=1)
    if parts and re.fullmatch(r"<[fr]reg>", parts[0].strip(), re.IGNORECASE):
        parts[0] = "<dst>"
        normalized_operands = ",".join(parts)
    return normalized_opcode, normalized_operands


def _pcode_expression_first_def(expression: object) -> tuple[str, str] | None:
    if not isinstance(expression, str):
        return None
    parts = expression.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    return _normalize_first_def(parts[0], parts[1])


def _first_def_from_candidate(
    candidate: Mapping[str, Any],
    owner: Mapping[str, Any],
) -> tuple[str, str] | None:
    if _normalize_text(owner.get("confidence")).lower() != "pcode-first-def":
        return None
    owner_first_def = _pcode_expression_first_def(owner.get("expression"))
    if owner_first_def is None:
        return None

    for container in (candidate, owner):
        first_def = container.get("first_def", _MISSING)
        if first_def is _MISSING:
            continue
        if not isinstance(first_def, Mapping):
            return None
        explicit_first_def = _normalize_first_def(first_def.get("opcode"), first_def.get("operands"))
        if explicit_first_def != owner_first_def:
            return None
    return owner_first_def


def _source_owner_signature(owner: Mapping[str, Any]) -> dict[str, object] | None:
    confidence = _normalize_text(owner.get("confidence")).lower()
    first_def = _pcode_expression_first_def(owner.get("expression"))
    if confidence != "pcode-first-def" or first_def is None:
        return None
    explicit_first_def = owner.get("first_def", _MISSING)
    if explicit_first_def is not _MISSING:
        if not isinstance(explicit_first_def, Mapping):
            return None
        if (
            _normalize_first_def(
                explicit_first_def.get("opcode"),
                explicit_first_def.get("operands"),
            )
            != first_def
        ):
            return None

    signature: dict[str, object] = {
        "confidence": confidence,
        "expression": f"{first_def[0]} {first_def[1]}",
    }
    source_file = owner.get("source_file")
    if source_file is not None:
        if not isinstance(source_file, str) or not source_file.strip():
            return None
        signature["source_file"] = source_file.strip()
    name = owner.get("name")
    if name is not None:
        if not isinstance(name, str) or not name.strip():
            return None
        normalized_name = _normalize_identity_text(name)
        if not normalized_name:
            return None
        signature["name"] = normalized_name
    for coordinate in ("source_line", "source_col"):
        value = owner.get(coordinate)
        if value is None:
            continue
        if not _is_int(value) or value <= 0:
            return None
        signature[coordinate] = value
    return signature


def _source_owner_key(owner_signature: Mapping[str, object]) -> str:
    return json.dumps(owner_signature, sort_keys=True, separators=(",", ":"))


def _source_owners_compatible(
    authoritative: Mapping[str, Any],
    fallback: Mapping[str, Any],
) -> bool:
    authoritative_signature = _source_owner_signature(authoritative)
    fallback_signature = _source_owner_signature(fallback)
    if authoritative_signature is None or fallback_signature is None:
        return False
    return all(
        authoritative_signature[key] == fallback_signature[key]
        for key in authoritative_signature.keys() & fallback_signature.keys()
    )


def _source_owner_from_candidate(candidate: Mapping[str, Any]) -> Mapping[str, Any] | None:
    source_owner = candidate.get("source_owner", _MISSING)
    nearest = candidate.get("nearest_source_expression", _MISSING)
    if source_owner is not _MISSING:
        if not isinstance(source_owner, Mapping):
            return None
        if nearest is not _MISSING:
            if not isinstance(nearest, Mapping) or not _source_owners_compatible(source_owner, nearest):
                return None
        return source_owner
    if not isinstance(nearest, Mapping):
        return None
    return nearest


def _compiler_identity(
    candidate: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None]:
    opcode = _normalize_access_opcode(candidate.get("opcode"))
    owner = _source_owner_from_candidate(candidate)
    if opcode is None or owner is None:
        return None, None, "unresolved-compiler-temp-home"

    first_def = _first_def_from_candidate(candidate, owner)
    owner_signature = _source_owner_signature(owner)
    if first_def is None or owner_signature is None:
        return None, None, "unresolved-compiler-temp-home"

    first_def_opcode, first_def_operands = first_def
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
        _source_owner_key(owner_signature),
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
) -> tuple[
    list[_PendingHome],
    list[Mapping[str, Any]],
    list[Mapping[str, Any]],
]:
    raw_assignments = current.get("stack_home_assignments")
    status = current.get("stack_home_assignment_status")
    if not isinstance(raw_assignments, list) or not isinstance(status, str):
        blockers.add("incomplete-frame-report")
        return [], [], []
    if status not in {
        "resolved-symbolic-homes",
        "unavailable-no-resolved-symbolic-homes",
    }:
        blockers.add("incomplete-frame-report")
    if bool(raw_assignments) != (status == "resolved-symbolic-homes"):
        blockers.add("incomplete-frame-report")

    homes: list[_PendingHome] = []
    named_assignments: list[Mapping[str, Any]] = []
    anonymous_assignments: list[Mapping[str, Any]] = []
    assignment_orders: list[int] = []
    for raw in raw_assignments:
        if not isinstance(raw, Mapping):
            blockers.add("incomplete-stack-home-assignment")
            continue
        symbol = raw.get("symbol")
        offset = raw.get("offset")
        order = raw.get("assignment_order")
        opcodes = raw.get("opcodes")
        if (
            not isinstance(symbol, str)
            or not symbol
            or not _is_int(offset)
            or not _is_int(order)
            or int(order) < 0
            or not isinstance(opcodes, list)
            or not opcodes
            or not all(isinstance(item, str) and _normalize_text(item) for item in opcodes)
        ):
            blockers.add("incomplete-stack-home-assignment")
            continue
        assignment_orders.append(int(order))
        if symbol.startswith("@"):
            anonymous_assignments.append(raw)
            continue
        named_assignments.append(raw)
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
    return homes, named_assignments, anonymous_assignments


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


def _candidate_matches_assignment(
    candidate: Mapping[str, Any],
    assignment: Mapping[str, Any],
) -> bool:
    opcode = _normalize_text(candidate.get("opcode")).lower()
    return candidate.get("current_offset") == assignment.get("offset") and opcode in {
        _normalize_text(item).lower() for item in assignment.get("opcodes", []) if isinstance(item, str)
    }


def _pending_compiler_home(
    candidate: Mapping[str, Any],
    *,
    sequence_key: tuple[int, ...],
    assignment: Mapping[str, Any] | None = None,
) -> tuple[_PendingHome | None, str | None, str | None]:
    identity, owner_key, blocker = _compiler_identity(candidate)
    if blocker is not None or identity is None or owner_key is None:
        return None, None, blocker or "unresolved-compiler-temp-home"
    mismatch = candidate["mismatch"]
    absolute = (
        (assignment is not None and _is_int(assignment.get("expected_offset")))
        or _is_int(candidate.get("expected_offset"))
        or _is_int(mismatch.get("expected_offset"))
    )
    return (
        _PendingHome(
            identity=identity,
            offset=int(candidate["current_offset"]),
            reference_kind="absolute" if absolute else "proxy",
            sequence_key=sequence_key,
            origin="compiler-temp",
        ),
        owner_key,
        None,
    )


def _compiler_homes(
    report: Mapping[str, Any] | None,
    named_assignments: list[Mapping[str, Any]],
    anonymous_assignments: list[Mapping[str, Any]],
    frame_size: int | None,
    frame_function: str | None,
    blockers: set[str],
) -> list[_PendingHome]:
    if report is None:
        blockers.add("incomplete-stack-slot-evidence")
        return []
    if not isinstance(report, Mapping):
        blockers.add("incomplete-stack-slot-evidence")
        return []
    candidates = report.get("candidates")
    candidate_count = report.get("candidate_count")
    status = report.get("status")
    report_function = report.get("function")
    if (
        not isinstance(candidates, list)
        or not _is_int(candidate_count)
        or int(candidate_count) != len(candidates)
        or status not in {"ok", "no-candidates"}
        or (status == "ok") != bool(candidates)
        or not isinstance(report_function, str)
        or not report_function
        or report_function != frame_function
    ):
        blockers.add("incomplete-stack-slot-evidence")
        return []
    report_frame_size = report.get("frame_size")
    if report_frame_size is not None and report_frame_size != frame_size:
        blockers.add("frame-size-mismatch")

    valid_candidates: list[tuple[int, Mapping[str, Any], tuple[int, ...]]] = []
    for index, raw in enumerate(candidates):
        if not isinstance(raw, Mapping):
            blockers.add("incomplete-stack-slot-evidence")
            continue
        opcode = _normalize_access_opcode(raw.get("opcode"))
        offset = raw.get("current_offset")
        mismatch = raw.get("mismatch")
        sequence_key = _candidate_sequence_key(raw, index)
        if opcode is None or not _is_int(offset) or not isinstance(mismatch, Mapping) or sequence_key is None:
            blockers.add("incomplete-stack-slot-evidence")
            continue
        if mismatch.get("opcode") != raw.get("opcode") or mismatch.get("current_offset") != offset:
            blockers.add("incomplete-stack-slot-evidence")
            continue
        valid_candidates.append((index, raw, sequence_key))

    homes: list[_PendingHome] = []
    owner_keys: set[str] = set()
    consumed: set[int] = set()

    for index, raw, _sequence_key in valid_candidates:
        named_matches = _candidate_matches_named_home(raw, named_assignments)
        if named_matches == 1:
            consumed.add(index)
            continue
        if named_matches > 1:
            blockers.add("ambiguous-compiler-temp-home")
            consumed.add(index)
            continue

    for assignment in anonymous_assignments:
        matches = [item for item in valid_candidates if _candidate_matches_assignment(item[1], assignment)]
        if not matches:
            blockers.add("unresolved-compiler-temp-home")
            continue
        if len(matches) > 1 or matches[0][0] in consumed:
            blockers.add("ambiguous-compiler-temp-home")
            consumed.update(item[0] for item in matches)
            continue
        index, raw, _candidate_key = matches[0]
        consumed.add(index)
        home, owner_key, blocker = _pending_compiler_home(
            raw,
            sequence_key=_assignment_sequence_key(
                assignment,
                int(assignment["assignment_order"]),
            ),
            assignment=assignment,
        )
        if blocker is not None or home is None or owner_key is None:
            blockers.add(blocker or "unresolved-compiler-temp-home")
            continue
        if owner_key in owner_keys:
            blockers.add("ambiguous-compiler-temp-home")
        owner_keys.add(owner_key)
        homes.append(home)

    for index, raw, sequence_key in valid_candidates:
        if index in consumed:
            continue
        home, owner_key, blocker = _pending_compiler_home(
            raw,
            sequence_key=sequence_key,
        )
        if blocker is not None or home is None or owner_key is None:
            blockers.add(blocker or "unresolved-compiler-temp-home")
            continue
        if owner_key in owner_keys:
            blockers.add("ambiguous-compiler-temp-home")
        owner_keys.add(owner_key)
        homes.append(home)
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
    frame_function_value = frame_report.get("function")
    frame_function = frame_function_value if isinstance(frame_function_value, str) and frame_function_value else None
    if frame_function is None:
        blockers.add("incomplete-frame-report")
    frame_size = current.get("frame_size")
    if frame_size is None:
        blockers.add("missing-frame-size")
    elif not _is_int(frame_size) or int(frame_size) < 0:
        blockers.add("incomplete-frame-report")
        frame_size = None
    else:
        frame_size = int(frame_size)

    pending, named_assignments, anonymous_assignments = _named_homes(current, blockers)
    pending.extend(
        _compiler_homes(
            stack_slot_report,
            named_assignments,
            anonymous_assignments,
            frame_size,
            frame_function,
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
