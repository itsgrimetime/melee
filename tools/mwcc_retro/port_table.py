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
