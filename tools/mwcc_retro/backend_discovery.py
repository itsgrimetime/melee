"""Backend address discovery helpers for retail MWCC GC/1.2.5n."""
from __future__ import annotations

import struct
from typing import Any

from . import pe, port_table, struct_map


_GC125N_REQUIRED_CANDIDATES: dict[str, dict[str, Any]] = {
    "codegen_start": {
        **port_table.BACKEND_PARTIAL_125N["codegen_start"],
        "provenance": "tools/mwcc_retro/port_table.py:BACKEND_PARTIAL_125N",
    },
    "codegen_end": {
        **port_table.BACKEND_PARTIAL_125N["codegen_end"],
        "provenance": "tools/mwcc_retro/port_table.py:BACKEND_PARTIAL_125N",
    },
    "pcode_pass_boundary": {
        "va": port_table.DLL_KNOWN_125N["pcode_traverse"],
        "provenance": "tools/mwcc_debug/mwcc_debug.c:pcode_traverse hook",
    },
    "backend_block_list": {
        "provenance": "pending retail backend global identification",
    },
    "pcbasicblocks": {
        "va": 0x587C74,
        "provenance": "tools/mwcc_debug/mwcc_debug.c:PCBASICBLOCKS",
    },
    "interference_matrix": {
        "va": 0x583088,
        "provenance": "tools/mwcc_debug/mwcc_debug.c:INTERFERENCE_MATRIX",
    },
    "coalesce_alias": {
        "va": 0x58308C,
        "provenance": "tools/mwcc_debug/mwcc_debug.c:COALESCE_ALIAS",
    },
    "interferencegraph": {
        "va": 0x587E3C,
        "provenance": "tools/mwcc_debug/mwcc_debug.c:INTERFERENCEGRAPH",
    },
    "n_ignodes": {
        "va": 0x587190,
        "provenance": "tools/mwcc_debug/mwcc_debug.c:N_IGNODES",
    },
    "used_vreg_gpr": {
        "va": 0x58846E,
        "provenance": "live probe candidate: rclass 0 n_virtuals counter",
    },
    "used_vreg_fpr": {
        "va": 0x58846C,
        "provenance": "live probe candidate: rclass 1 n_virtuals counter",
    },
    "build_interference_matrix": {
        "va": 0x531290,
        "provenance": "tools/mwcc_debug/mwcc_debug.c:FUN_00531290 comment",
    },
    "real_coalesce": {
        "va": 0x530E00,
        "provenance": "tools/mwcc_debug/mwcc_debug.c:real_coalesce hook",
    },
    "build_adjacency_vectors": {
        "va": 0x530C00,
        "provenance": "tools/mwcc_debug/mwcc_debug.c:buildadjacencyvectors comment",
    },
    "simplifygraph": {
        "va": port_table.DLL_KNOWN_125N["simplifygraph"],
        "provenance": "tools/mwcc_retro/port_table.py:DLL_KNOWN_125N",
    },
    "colorgraph": {
        "va": port_table.DLL_KNOWN_125N["colorgraph"],
        "provenance": "tools/mwcc_retro/port_table.py:DLL_KNOWN_125N",
    },
    "frame_locals": {
        "va": 0x587FB8,
        "provenance": "cadmic GC/1.1 locals list port candidate; live frame sample required",
    },
    "final_scheduler": {
        "va": 0x435D75,
        "provenance": "live probe candidate: after final scheduler call in CodeGen_Generator",
    },
}


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


def _static_candidate_entry(img: pe.Image, spec: dict[str, Any]) -> dict[str, Any]:
    va = spec.get("va")
    provenance = spec["provenance"]
    if not isinstance(va, int):
        return {
            "provenance": provenance,
            "confidence": "unknown",
            "needs_live_invariant": True,
        }

    section = img.section_of_va(va)
    if section == ".text" and img.va_to_offset(va) is not None:
        return {
            "va": va,
            "section": section,
            "first_bytes_hex": img.read(va, 8).hex(),
            "provenance": provenance,
            "confidence": "static-pe-present",
            "needs_live_invariant": True,
        }
    if section is not None:
        return {
            "va": va,
            "section": section,
            "provenance": provenance,
            "confidence": "static-section-present",
            "needs_live_invariant": True,
        }
    return {
        "va": va,
        "section": None,
        "provenance": provenance,
        "confidence": "unknown",
        "needs_live_invariant": True,
    }


def build_gc125n_backend_candidate_report(exe_path) -> dict[str, Any]:
    """Build a static PE-presence report for required GC/1.2.5n backend keys.

    This report is intentionally audit-only: every entry still requires a live
    invariant, and its confidence values are below struct_map's required gate.
    """
    img = pe.load(exe_path)
    entries = {
        key: _static_candidate_entry(img, _GC125N_REQUIRED_CANDIDATES[key])
        for key in struct_map.REQUIRED_GC125N_BACKEND_KEYS
    }
    structs = {
        name: {
            "fields": dict(fields),
            "provenance": "mwcc-debug-docs",
            "confidence": "docs-only",
            "needs_live_invariant": True,
        }
        for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items()
    }
    summary = {
        "present_text": sum(1 for entry in entries.values() if entry.get("section") == ".text"),
        "present_bss": sum(1 for entry in entries.values() if entry.get("section") == ".bss"),
        "missing": sum(1 for entry in entries.values() if entry.get("confidence") == "unknown"),
        "needs_live_invariant": sum(
            1 for entry in entries.values() if entry.get("needs_live_invariant") is True
        ),
    }
    return {
        "compiler": "1.2.5n",
        "entries": entries,
        "structs": structs,
        "summary": summary,
    }
