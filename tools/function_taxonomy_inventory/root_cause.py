"""Stable shared root-cause keys derived from structured taxonomy evidence."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any


def derive_root_cause_keys(classification: object) -> list[str]:
    """Return case-preserving named-BSS keys without consulting record prose."""
    if not isinstance(classification, Mapping):
        return []
    relocations = classification.get("bss_anchor_relocations")
    if not isinstance(relocations, Mapping):
        return []
    pairs = relocations.get("pairs")
    if not isinstance(pairs, list):
        return []

    keys: list[str] = []
    seen: set[str] = set()
    for pair in pairs:
        if not isinstance(pair, Mapping):
            continue
        symbol = pair.get("named_symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        key = f"bss-symbol:{symbol.strip()}"
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def attach_root_cause_impacts(records: list[dict[str, Any]]) -> None:
    """Attach the maximum unique-row membership count for each keyed row."""
    memberships: Counter[str] = Counter()
    for row in records:
        keys = row.get("root_cause_keys")
        if not isinstance(keys, list):
            continue
        memberships.update(
            {
                key
                for key in keys
                if isinstance(key, str) and key.strip()
            }
        )

    for row in records:
        keys = row.get("root_cause_keys")
        if not isinstance(keys, list):
            continue
        row["max_root_cause_impact"] = max(
            (
                memberships[key]
                for key in dict.fromkeys(keys)
                if isinstance(key, str) and key.strip()
            ),
            default=0,
        )
