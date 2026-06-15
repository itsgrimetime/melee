"""Adapters for using transform-corpus probes in source scoring commands."""

from __future__ import annotations

from collections.abc import Iterable
import re

from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe
from src.search.directed.transform_corpus import (
    DEFAULT_TRANSFORM_FAMILIES,
    TransformProbe,
)


class TransformProbeConfigError(ValueError):
    """Raised when transform-corpus command options are invalid."""


_VALID_FAMILY_IDS = frozenset(family.family_id for family in DEFAULT_TRANSFORM_FAMILIES)
_CLASS_NAMES = {
    "gpr": 0,
    "int": 0,
    "r": 0,
    "class0": 0,
    "fp": 1,
    "fpr": 1,
    "f": 1,
    "class1": 1,
}
_UNSAFE_LABEL_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _probe_ordinal(probe: TransformProbe) -> str:
    if "@" not in probe.probe_id:
        return "0"
    ordinal = probe.probe_id.rsplit("@", 1)[1].strip()
    return ordinal or "0"


def _safe_label_part(value: str) -> str:
    cleaned = _UNSAFE_LABEL_CHARS_RE.sub("-", value.strip())
    return cleaned.strip("-") or "unknown"


def normalize_transform_families(values: Iterable[str] | None) -> tuple[str, ...]:
    families: list[str] = []
    for value in values or ():
        for item in str(value).split(","):
            family = item.strip()
            if not family:
                continue
            if family not in _VALID_FAMILY_IDS:
                known = ", ".join(sorted(_VALID_FAMILY_IDS))
                raise TransformProbeConfigError(
                    f"unknown transform family {family!r}; known families: {known}"
                )
            families.append(family)
    return tuple(dict.fromkeys(families))


def filter_transform_probes(
    probes: Iterable[TransformProbe],
    *,
    families: Iterable[str] | None,
) -> tuple[TransformProbe, ...]:
    requested = frozenset(normalize_transform_families(families))
    if not requested:
        return tuple(probes)
    return tuple(probe for probe in probes if probe.family_id in requested)


def transform_probe_key(probe: TransformProbe) -> str:
    return f"transform-corpus:{probe.family_id}:{_probe_ordinal(probe)}"


def _safe_probe_label(probe: TransformProbe) -> str:
    family = _safe_label_part(probe.family_id)
    ordinal = _safe_label_part(_probe_ordinal(probe))
    return f"transform-corpus-{family}-{ordinal}"


def transform_probe_to_lifetime_probe(probe: TransformProbe) -> LifetimeLayoutProbe:
    provenance = {
        "kind": "transform-corpus",
        "probe_id": probe.probe_id,
        "family_id": probe.family_id,
        "family_label": probe.family_label,
        "mutator_key": probe.mutator_key,
        "semantic_risk": probe.semantic_risk,
        "source_region": probe.source_region,
        "expected_compiler_effect": probe.expected_compiler_effect,
        "generated_probe_form": probe.generated_probe_form,
        "target_assignments": list(probe.target_assignments),
        "span": list(probe.span),
        "payload": dict(probe.payload),
    }
    if "requires_full_unit_source" in probe.payload:
        provenance["requires_full_unit_source"] = bool(
            probe.payload["requires_full_unit_source"]
        )
    if "updated_call_sites" in probe.payload:
        provenance["updated_call_sites"] = probe.payload["updated_call_sites"]
    return LifetimeLayoutProbe(
        label=_safe_probe_label(probe),
        operator=f"transform-corpus:{probe.family_id}",
        description=(
            f"{probe.family_label}: {probe.generated_probe_form}; "
            f"expected effect: {probe.expected_compiler_effect}"
        ),
        source_text=probe.candidate_text,
        provenance=provenance,
    )


def adapted_transform_lifetime_probes(
    probes: Iterable[TransformProbe],
    *,
    families: Iterable[str] | None,
    max_probes: int,
) -> list[LifetimeLayoutProbe]:
    limit = max(0, max_probes)
    if limit == 0:
        return []

    out: list[LifetimeLayoutProbe] = []
    seen_text: set[str] = set()
    for probe in filter_transform_probes(probes, families=families):
        if probe.candidate_text in seen_text:
            continue
        seen_text.add(probe.candidate_text)
        out.append(transform_probe_to_lifetime_probe(probe))
        if len(out) >= limit:
            break
    return out


def parse_transform_force_phys(raw: str | None) -> dict[int, int]:
    """Parse transform-corpus force-phys entries into ig_idx -> phys id."""

    if raw is None or not str(raw).strip():
        return {}

    force_phys: dict[int, int] = {}
    for entry in str(raw).split(","):
        spec = entry.strip()
        if not spec:
            continue
        parts = [part.strip() for part in spec.split(":")]
        try:
            if len(parts) == 3:
                _parse_transform_class(parts[0])
                virtual = _parse_transform_int(parts[1], prefix="ig")
                phys = _parse_transform_phys(parts[2])
            elif len(parts) == 2:
                virtual = _parse_transform_int(parts[0], prefix="ig")
                phys = _parse_transform_phys(parts[1])
            else:
                raise ValueError("expected IG:PHYS or CLASS:IG:PHYS")
        except ValueError as exc:
            raise TransformProbeConfigError(
                f"invalid transform force-phys entry {spec!r}: {exc}; "
                "expected IG:PHYS or CLASS:IG:PHYS"
            ) from exc
        force_phys[virtual] = phys
    return force_phys


def _parse_transform_class(raw: str) -> int:
    value = raw.strip().lower()
    if value in _CLASS_NAMES:
        return _CLASS_NAMES[value]
    if value.startswith("class"):
        value = value[len("class"):]
    return _parse_transform_int(value)


def _parse_transform_phys(raw: str) -> int:
    value = raw.strip().lower()
    if value.startswith("phys="):
        value = value.split("=", 1)[1]
    if value.startswith(("r", "f")):
        value = value[1:]
    return _parse_transform_int(value)


def _parse_transform_int(raw: str, *, prefix: str = "") -> int:
    value = raw.strip().lower()
    if prefix and value.startswith(prefix):
        value = value[len(prefix):]
    if not value:
        raise ValueError(f"missing integer in {raw!r}")
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise ValueError(f"expected decimal integer in {raw!r}") from exc
    if parsed < 0:
        raise ValueError(f"expected non-negative integer in {raw!r}")
    return parsed
