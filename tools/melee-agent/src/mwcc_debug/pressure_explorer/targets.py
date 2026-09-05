from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Mapping
from typing import Any

from .models import TargetAllocation, TargetSet


_TARGET_TOKEN_RE = re.compile(r"^(?P<prefix>[A-Za-z]*)(?P<ig>\d+)$")


def _class_id_from_prefix(prefix: str, default_class_id: int) -> int:
    normalized = prefix.strip().lower()
    if normalized == "":
        return default_class_id
    if normalized in {"0", "gpr", "r"}:
        return 0
    if normalized in {"1", "fpr", "f"}:
        return 1
    raise ValueError(f"bad register class prefix {prefix!r}")


def _parse_int(value: object, *, entry: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad force-phys entry {entry!r}") from exc


def _target_from_token(
    token: str,
    expected_phys: object,
    *,
    default_class_id: int,
    entry: str,
) -> TargetAllocation:
    match = _TARGET_TOKEN_RE.fullmatch(token.strip())
    if match is None:
        raise ValueError(f"bad force-phys entry {entry!r}")
    class_id = _class_id_from_prefix(match.group("prefix"), default_class_id)
    return TargetAllocation(
        class_id=class_id,
        ig_id=_parse_int(match.group("ig"), entry=entry),
        expected_phys=_parse_int(expected_phys, entry=entry),
    )


def _target_from_mapping_item(
    key: object,
    value: object,
    *,
    default_class_id: int,
) -> TargetAllocation:
    entry = f"{key}:{value}"
    if isinstance(value, Mapping):
        phys = value.get("expected_phys", value.get("phys", value.get("assigned_phys")))
        raw_class_id = value.get("class_id")
        class_id = (
            default_class_id
            if raw_class_id is None
            else _class_id_from_prefix(str(raw_class_id), default_class_id)
        )
        target = _target_from_token(
            str(key),
            phys,
            default_class_id=class_id,
            entry=entry,
        )
        return TargetAllocation(
            class_id=target.class_id,
            ig_id=target.ig_id,
            expected_phys=target.expected_phys,
            source=str(value.get("source", "force-phys")),
        )
    return _target_from_token(
        str(key),
        value,
        default_class_id=default_class_id,
        entry=entry,
    )


def parse_force_phys_spec(raw: str, default_class_id: int = 0) -> TargetSet:
    if raw.strip() == "":
        raise ValueError("empty force-phys spec")

    targets: list[TargetAllocation] = []
    for entry in raw.split(","):
        entry = entry.strip()
        parts = [part.strip() for part in entry.split(":")]
        if len(parts) == 2 and all(parts):
            targets.append(
                _target_from_token(
                    parts[0],
                    parts[1],
                    default_class_id=default_class_id,
                    entry=entry,
                )
            )
            continue
        if len(parts) == 3 and all(parts):
            class_id = _class_id_from_prefix(parts[0], default_class_id)
            targets.append(
                TargetAllocation(
                    class_id=class_id,
                    ig_id=_parse_int(parts[1], entry=entry),
                    expected_phys=_parse_int(parts[2], entry=entry),
                )
            )
            continue
        raise ValueError(f"bad force-phys entry {entry!r}")

    return TargetSet(targets=tuple(targets))


def _load_target_mapping(data: Mapping[str, Any]) -> tuple[TargetAllocation, ...]:
    raw_targets = data.get("force_phys", data.get("virtuals"))
    if not isinstance(raw_targets, Mapping):
        raise ValueError("target file must contain force_phys or virtuals mapping")
    if not raw_targets:
        raise ValueError("empty target mapping")

    default_class_id = int(data.get("class_id", data.get("class", 0)))
    targets = [
        _target_from_mapping_item(
            key,
            value,
            default_class_id=default_class_id,
        )
        for key, value in raw_targets.items()
    ]
    return tuple(sorted(targets, key=lambda target: (target.class_id, target.ig_id)))


def parse_target_file(path: str | pathlib.Path) -> TargetSet:
    target_path = pathlib.Path(path)
    data = json.loads(target_path.read_text())
    if not isinstance(data, Mapping):
        raise ValueError("target file must contain a JSON object")
    return TargetSet(
        function=data.get("function"),
        targets=_load_target_mapping(data),
        provenance=data.get("provenance") or {"path": str(target_path)},
    )


__all__ = [
    "_class_id_from_prefix",
    "parse_force_phys_spec",
    "_load_target_mapping",
    "parse_target_file",
]
