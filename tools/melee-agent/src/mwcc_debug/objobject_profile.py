"""Semantic identities and order distance for mwcc-inspect ObjObjects."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .inspect_parser import parse_inspect_snapshots

_ADDRESS = r"(?:0[xX][0-9A-Fa-f]+|[0-9A-Fa-f]+[hH]|[0-9A-Fa-f]{6,})"
_OBJECT_START_RE = re.compile(rf"^\s*(?:->\s*)?ObjObject(?:\s+@\s*(?P<address>{_ADDRESS}))?", re.IGNORECASE)
_REAL_OBJECT_RE = re.compile(
    rf"^\s*(?:->\s*)?ObjObject\s+@\s*{_ADDRESS}\s*:\s*"
    r"(?P<name>.*?)\s+\(DataType:\s*(?P<kind>[^,]+),\s*Type:\s*(?P<type>.*)\)\s*$",
    re.IGNORECASE,
)
_LABELED_FIELD_RE = re.compile(
    r"^\s*(?P<label>kind|data[_ ]?type|name|source[_ ]?name|type|type[_ ]?name|scope|"
    r"expression|initializer|occurrence|occurrence[_ ]?id|source[_ ]?order|first[_ ]?appearance)\s*[:=]\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
_HEX_ADDRESS_RE = re.compile(rf"(?<![A-Za-z0-9_]){_ADDRESS}(?![A-Za-z0-9_])")
_TEMP_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:@\d+|%?r\d+(?:_\d+)?|(?:temp|tmp|var)_?r?\d+(?:_\d+)?)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")
_STRUCTURAL_SPACE_RE = re.compile(r"\s*([()[\]{},;:])\s*")
_OPERATOR_SPACE_RE = re.compile(r"\s*([+*/%&|^=<>?-]+)\s*")
_TYPE_POINTER_SPACE_RE = re.compile(r"\s*\*")


@dataclass(frozen=True, slots=True)
class ObjObjectIdentity:
    kind: str
    source_name: str
    type_name: str
    scope: str
    expression: str


@dataclass(frozen=True, slots=True)
class ObjObjectProfile:
    identities: tuple[ObjObjectIdentity, ...]
    complete: bool
    blocker: str | None = None
    occurrence_evidence: tuple[str | None, ...] = field(default=(), repr=False)


@dataclass
class _ObjectRecord:
    fields: dict[str, str]
    occurrence: str | None = None


def _normalize(value: str, *, unstable_ids: bool = False, type_syntax: bool = False) -> str:
    if unstable_ids:
        value = _OPERATOR_SPACE_RE.sub(r" \1 ", value)
    value = _HEX_ADDRESS_RE.sub("<addr>", value)
    if unstable_ids:
        value = _TEMP_ID_RE.sub("<temp>", value)
    value = _SPACE_RE.sub(" ", value).strip()
    value = _STRUCTURAL_SPACE_RE.sub(r"\1", value)
    if type_syntax:
        value = _TYPE_POINTER_SPACE_RE.sub("*", value)
    return value


def _canonical_label(label: str) -> str:
    compact = label.lower().replace("_", " ")
    if compact in {"data type", "kind"}:
        return "kind"
    if compact in {"name", "source name"}:
        return "source_name"
    if compact in {"type", "type name"}:
        return "type_name"
    if compact in {"expression", "initializer"}:
        return "expression"
    if compact in {"occurrence", "occurrence id", "source order", "first appearance"}:
        return "occurrence"
    return "scope"


def _parse_inline_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in re.split(r"\s*[;|]\s*", line):
        match = _LABELED_FIELD_RE.match(part)
        if match is not None:
            fields[_canonical_label(match.group("label"))] = match.group("value")
    return fields


def _parse_records(snapshot_text: str, function: str) -> tuple[list[_ObjectRecord], bool]:
    records: list[_ObjectRecord] = []
    current: _ObjectRecord | None = None
    saw_unparsed_content = False

    def flush() -> None:
        nonlocal current
        if current is not None:
            records.append(current)
        current = None

    for line in snapshot_text.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or set(stripped) <= {"-", "="}:
            continue

        real_match = _REAL_OBJECT_RE.match(line)
        if real_match is not None:
            flush()
            records.append(
                _ObjectRecord(
                    fields={
                        "kind": real_match.group("kind"),
                        "source_name": real_match.group("name"),
                        "type_name": real_match.group("type"),
                        "scope": function,
                        "expression": real_match.group("name"),
                    }
                )
            )
            continue

        start_match = _OBJECT_START_RE.match(line)
        if start_match is not None:
            flush()
            current = _ObjectRecord(fields={})
            remainder = line[start_match.end() :].strip().lstrip(":").strip()
            if remainder:
                inline_fields = _parse_inline_fields(remainder)
                current.occurrence = inline_fields.pop("occurrence", None)
                current.fields.update(inline_fields)
            continue

        label_match = _LABELED_FIELD_RE.match(line)
        if current is not None and label_match is not None:
            label = _canonical_label(label_match.group("label"))
            value = label_match.group("value")
            if label == "occurrence":
                current.occurrence = value
            else:
                current.fields[label] = value
            continue

        if current is not None:
            inline_fields = _parse_inline_fields(stripped)
            if inline_fields:
                occurrence = inline_fields.pop("occurrence", None)
                current.fields.update(inline_fields)
                if occurrence is not None:
                    current.occurrence = occurrence
                continue
        saw_unparsed_content = True

    flush()
    return records, saw_unparsed_content


def parse_objobject_profile(inspect_text: str, function: str) -> ObjObjectProfile:
    """Parse the final ObjObject snapshot for exactly ``function``."""

    snapshots = [
        snapshot
        for snapshot in parse_inspect_snapshots(inspect_text, function=function)
        if snapshot.name == "Frontend: OBJOBJECTS"
    ]
    if not snapshots:
        return ObjObjectProfile((), False, "missing-objobject-snapshot")

    records, saw_unparsed_content = _parse_records(snapshots[-1].text, function)
    identities: list[ObjObjectIdentity] = []
    occurrences: list[str | None] = []
    required = {"kind", "source_name", "type_name", "scope", "expression"}
    for record in records:
        if set(record.fields) != required:
            return ObjObjectProfile(tuple(identities), False, "incomplete-objobject-entry")
        identities.append(
            ObjObjectIdentity(
                kind=_normalize(record.fields["kind"]),
                source_name=_normalize(record.fields["source_name"]),
                type_name=_normalize(record.fields["type_name"], type_syntax=True),
                scope=_normalize(record.fields["scope"]),
                expression=_normalize(record.fields["expression"], unstable_ids=True),
            )
        )
        occurrences.append(_normalize(record.occurrence, unstable_ids=True) if record.occurrence is not None else None)

    if saw_unparsed_content or (not records and len(snapshots[-1].text.splitlines()) > 1):
        return ObjObjectProfile(tuple(identities), False, "incomplete-objobject-entry")

    counts = Counter(identities)
    for identity, count in counts.items():
        if count < 2:
            continue
        evidence = [occurrences[idx] for idx, item in enumerate(identities) if item == identity]
        if any(item is None for item in evidence) or len(set(evidence)) != count:
            return ObjObjectProfile(
                tuple(identities),
                False,
                "ambiguous-objobject-identity",
                tuple(occurrences),
            )

    return ObjObjectProfile(tuple(identities), True, occurrence_evidence=tuple(occurrences))


def _multiset_delta(candidate: tuple[ObjObjectIdentity, ...], donor: tuple[ObjObjectIdentity, ...]) -> int:
    candidate_counts = Counter(candidate)
    donor_counts = Counter(donor)
    return sum(
        abs(candidate_counts[item] - donor_counts[item]) for item in candidate_counts.keys() | donor_counts.keys()
    )


def _ordered_common_tokens(
    profile: ObjObjectProfile,
    common_tokens: set[tuple[ObjObjectIdentity, str | None]],
    repeated: set[ObjObjectIdentity],
) -> list[tuple[ObjObjectIdentity, str | None]]:
    evidence = profile.occurrence_evidence or (None,) * len(profile.identities)
    result: list[tuple[ObjObjectIdentity, str | None]] = []
    for identity, occurrence in zip(profile.identities, evidence, strict=True):
        token = (identity, occurrence if identity in repeated else None)
        if token in common_tokens:
            result.append(token)
    return result


def _kendall_inversions(candidate: list[object], donor: list[object]) -> int:
    donor_positions = {token: idx for idx, token in enumerate(donor)}
    positions = [donor_positions[token] for token in candidate]
    return sum(
        positions[left] > positions[right]
        for left in range(len(positions))
        for right in range(left + 1, len(positions))
    )


def objobject_order_distance(candidate: ObjObjectProfile, donor: ObjObjectProfile) -> tuple[int, int]:
    """Return multiset membership delta followed by common-order inversions."""

    if not candidate.complete or not donor.complete:
        raise ValueError("incomplete-objobject-evidence")

    membership = _multiset_delta(candidate.identities, donor.identities)
    combined_counts = Counter(candidate.identities) | Counter(donor.identities)
    repeated = {identity for identity, count in combined_counts.items() if count > 1}

    def tokens(profile: ObjObjectProfile) -> set[tuple[ObjObjectIdentity, str | None]]:
        evidence = profile.occurrence_evidence or (None,) * len(profile.identities)
        return {
            (identity, occurrence if identity in repeated else None)
            for identity, occurrence in zip(profile.identities, evidence, strict=True)
        }

    common_tokens = tokens(candidate) & tokens(donor)
    candidate_order = _ordered_common_tokens(candidate, common_tokens, repeated)
    donor_order = _ordered_common_tokens(donor, common_tokens, repeated)
    return membership, _kendall_inversions(candidate_order, donor_order)
