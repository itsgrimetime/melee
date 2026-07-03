"""Backend address discovery helpers for retail MWCC GC/1.2.5n."""
from __future__ import annotations

import struct
from typing import Any


def scan_abs32_operands(
    blob: bytes, *, base_va: int, lo: int, hi: int
) -> list[dict[str, int]]:
    refs: list[dict[str, int]] = []
    for off in range(0, max(len(blob) - 3, 0)):
        val = struct.unpack_from("<I", blob, off)[0]
        if lo <= val < hi:
            refs.append({"site_va": base_va + off, "target_va": val})
    return refs


def unique_operand_target(
    candidates: list[dict[str, Any]], target_va: int
) -> dict[str, Any] | None:
    hits = [c for c in candidates if c.get("target_va") == target_va]
    if len(hits) != 1:
        return None
    return hits[0]


def confidence_entry(
    *, va: int, provenance: str, confidence: str, evidence: dict[str, Any]
) -> dict[str, Any]:
    return {
        "va": va,
        "provenance": provenance,
        "confidence": confidence,
        "evidence": evidence,
    }
