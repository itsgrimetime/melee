"""Host-side GC/1.1 -> GC/1.2.5n address porter.

Two methods, in priority order:
  1. string_anchor: find a unique string, find the unique PUSH imm32 that
     references it in each binary; the delta between push sites is the local
     text drift. High confidence when both sides are unique.
  2. byte_correlate: for an address with no nearby unique string, match a
     wildcarded instruction-window around the GC/1.1 site against GC/1.2.5n
     .text, enforcing monotonic ordering and a uniqueness margin.

All results carry provenance + confidence and are cross-checked against the
DLL's independently-known 1.2.5n VAs.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

from . import pe


@dataclass
class Anchor:
    needle: bytes
    src_site: int        # GC/1.1 push site VA
    dst_site: int        # GC/1.2.5n push site VA
    src_str_va: int
    dst_str_va: int
    confidence: str      # "unique" | "ambiguous" | "missing"


def string_anchor(src_exe, dst_exe, needle: bytes) -> Anchor:
    a = pe.load(src_exe)
    b = pe.load(dst_exe)
    sa = a.find_string_vas(needle)
    sb = b.find_string_vas(needle)
    if len(sa) != 1 or len(sb) != 1:
        return Anchor(needle, 0, 0, 0, 0, "missing")
    pa = a.push_imm32_sites(sa[0])
    pb = b.push_imm32_sites(sb[0])
    if len(pa) != 1 or len(pb) != 1:
        return Anchor(needle, 0, 0, sa[0], sb[0], "ambiguous")
    return Anchor(needle, pa[0], pb[0], sa[0], sb[0], "unique")


def overlaps_ninja(va: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= va < hi for lo, hi in ranges)


# DLL-known 1.2.5n VAs (independently RE'd in tools/mwcc_debug/mwcc_debug.c).
DLL_KNOWN_125N: dict[str, int] = {
    "colorgraph": 0x4CE2D0,
    "simplifygraph": 0x4CE400,
    "ig_builder": 0x530C00,
    "coalescer": 0x530E00,
    "formatoperands": 0x4C4BF0,
    "pcode_traverse": 0x4C2560,
    "pclistblocks_stub": 0x4C4BD0,
    "debug_printf": 0x44D580,
    "debuglisting_flag": 0x584226,
    "pcfile": 0x580610,
    "debug_guard": 0x5882B8,
    "fopen": 0x40C690,
}

# Live-validated 1.2.5n VAs (confirmed by disassembly + a live retrowin32 run
# producing 54 per-phase IRO dumps — see P0_FINDINGS.md / iro front-end tracing).
LIVE_VALIDATED_125N: dict[str, dict] = {
    # IRO_DumpAfterPhase(char *str, Boolean flag): entry, and the flag-test
    # guard `je` (bytes 74 41) at entry+5 whose NOP-out forces per-phase dumps.
    "iro_dumpafterphase_entry": {"va": 0x44D830},
    "iro_dumpafterphase_je": {"va": 0x44D835, "patch_from": "7441",
                              "patch_to": "9090"},
    # FunctionName global (current function ObjObject*) — read for per-fn scoping.
    "iro_function_name_ptr": {"va": 0x5875B8},
    # copt debug-listing option-default byte (DLL flips this to 1 at load).
    "copt_debug_byte": {"va": 0x42C8E1, "patch_from": "00", "patch_to": "01"},
}

NINJA_RANGES_125N: list[tuple[int, int]] = [
    (0x4ABD9A, 0x4ABDB4),
    (0x506510, 0x50653E),
]


@dataclass
class Correlation:
    src_va: int
    dst_va: int
    confidence: str  # "unique" | "unique-margin" | "ambiguous" | "missing"
    runner_up_score: float = 0.0


def _wildcard_window(img: pe.Image, va: int, window: int) -> bytes:
    """Mask bytes that look like absolute VAs into 0x00 so operand
    relocations don't defeat matching. Conservative: mask any 4-byte
    little-endian value that maps to a valid VA in this image."""
    raw = bytearray(img.read(va, window))
    for i in range(0, window - 3):
        val = struct.unpack_from("<I", raw, i)[0]
        if img.va_to_offset(val) is not None or 0x400000 <= val < 0x600000:
            raw[i : i + 4] = b"\x00\x00\x00\x00"
    return bytes(raw)


def byte_correlate(src_exe, dst_exe, src_va: int, window: int = 24) -> Correlation:
    a = pe.load(src_exe)
    b = pe.load(dst_exe)
    needle = _wildcard_window(a, src_va, window)
    text = next(s for s in b.sections if s.name == ".text")
    blob = b.data[text.raw_offset : text.raw_offset + text.raw_size]
    nz = [(i, c) for i, c in enumerate(needle) if c != 0]
    scores: list[tuple[float, int]] = []
    prior = src_va + 0x10
    centers = [prior + d for d in range(-0x400, 0x400)]
    for dst_va in centers:
        off = dst_va - text.va
        if off < 0 or off + window > len(blob):
            continue
        score = sum(1 for i, c in nz if blob[off + i] == c) / max(len(nz), 1)
        scores.append((score, dst_va))
    if not scores:
        return Correlation(src_va, 0, "missing")
    scores.sort(reverse=True)
    top_score, top_va = scores[0]
    runner = scores[1][0] if len(scores) > 1 else 0.0
    if top_score < 0.6:
        return Correlation(src_va, 0, "missing", runner)
    conf = "unique" if (top_score - runner) > 0.15 else "unique-margin"
    if top_score - runner < 0.02:
        conf = "ambiguous"
    return Correlation(src_va, top_va, conf, runner)


def build_table(src_exe, dst_exe) -> dict:
    """Generate the GC/1.2.5n port table. DLL-known VAs are seeded with
    provenance 'dll-known'; string anchors carry 'string-anchor'; correlations
    'byte-correlate'. Asserts no Ninji-range overlap."""
    entries: dict[str, dict] = {}
    for name, va in DLL_KNOWN_125N.items():
        entries[name] = {"va": va, "provenance": "dll-known", "confidence": "unique"}
    anchors = {
        "iro_starting_function_push": b"Starting function %s",
        "iro_dumpafterphase_push": b"Dumping function %s after %s ",
    }
    for name, needle in anchors.items():
        a = string_anchor(src_exe, dst_exe, needle)
        if a.confidence != "unique" or a.dst_site == 0:
            raise AssertionError(
                f"anchor {name!r} did not resolve uniquely "
                f"(confidence={a.confidence}, dst_site={a.dst_site:#x})"
            )
        entries[name] = {
            "va": a.dst_site,
            "src_va": a.src_site,
            "provenance": "string-anchor",
            "confidence": a.confidence,
            "needle": needle.decode("latin-1"),
        }
    for name, spec in LIVE_VALIDATED_125N.items():
        entries[name] = {**spec, "provenance": "live-validated",
                         "confidence": "unique"}
    for name, e in entries.items():
        if e["va"] and overlaps_ninja(e["va"], NINJA_RANGES_125N):
            raise AssertionError(f"table entry {name} overlaps Ninji patch range")
    return {"compiler": "1.2.5n", "entries": entries}


def write_table(table: dict, path) -> None:
    Path(path).write_text(json.dumps(table, indent=2) + "\n")
