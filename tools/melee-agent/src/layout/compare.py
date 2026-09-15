"""Pure interval comparator for data-layout discrepancies."""
from __future__ import annotations

from dataclasses import dataclass, field

DATA_ELF_SECTIONS = {
    ".data", ".bss", ".sdata", ".sdata2", ".sbss", ".sbss2", ".rodata",
}


@dataclass(frozen=True)
class Interval:
    name: str | None
    offset: int
    size: int
    binding: str | None = None
    anonymous: bool = False

    @property
    def end(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class Finding:
    kind: str
    section: str
    target: tuple[str | None, int, int] | None
    current: list[tuple[str | None, int, int]] = field(default_factory=list)
    message: str = ""
    confidence: str = "high"


def _ov(a: Interval, lo: int, hi: int) -> bool:
    return a.offset < hi and a.end > lo


def _trip(iv: Interval) -> tuple[str | None, int, int]:
    return (iv.name, iv.offset, iv.size)


def compare_section(
    section: str,
    target: list[Interval],
    current: list[Interval],
    *,
    check_binding: bool = False,
) -> list[Finding]:
    real_c = [c for c in current if not c.anonymous and c.name]
    cur_by_name = {c.name: c for c in real_c}
    real_targets = sorted((t for t in target if not t.anonymous and t.name),
                          key=lambda i: i.offset)
    tgt_by_name = {t.name: t for t in real_targets}
    findings: list[Finding] = []
    merged: list[tuple[int, int]] = []

    for idx, t in enumerate(real_targets):
        if any(lo <= t.offset and t.end <= hi for (lo, hi) in merged):
            continue
        lo, hi = t.offset, t.end
        next_off = real_targets[idx + 1].offset if idx + 1 < len(real_targets) else None
        ov_real = [c for c in real_c if _ov(c, lo, hi)]
        ov_all = [c for c in current if _ov(c, lo, hi)]

        span = None
        if next_off is not None:
            span = next((c for c in ov_real if c.offset <= lo and c.end > next_off), None)
        if span is not None:
            merged.append((span.offset, span.end))
            findings.append(Finding("merge", section, _trip(t), [_trip(span)],
                f"current {span.name} (0x{span.size:X}) spans multiple target objects"))
            continue

        inside = [c for c in ov_real if c.offset >= lo and c.end <= hi]
        if len(inside) >= 2:
            findings.append(Finding("split", section, _trip(t), [_trip(c) for c in inside],
                f"{t.name} (0x{t.size:X}) split into {len(inside)} current objects"))
            continue

        same = cur_by_name.get(t.name)
        if same is not None:
            if same.offset != t.offset:
                findings.append(Finding("reorder", section, _trip(t), [_trip(same)],
                    f"{t.name} at offset 0x{same.offset:X} (target 0x{t.offset:X})"))
            elif same.size != t.size:
                findings.append(Finding("size-mismatch", section, _trip(t), [_trip(same)],
                    f"{t.name}: size 0x{same.size:X} vs target 0x{t.size:X}"))
            elif (check_binding and t.binding and same.binding
                    and t.binding != same.binding):
                findings.append(Finding("binding-mismatch", section, _trip(t), [_trip(same)],
                    f"{t.name}: binding {same.binding} vs {t.binding}"))
            continue

        if not ov_all:
            findings.append(Finding("missing", section, _trip(t), [],
                f"{t.name}: target object absent in current object"))
            continue
        if all(c.anonymous for c in ov_all):
            findings.append(Finding("anonymous", section, _trip(t),
                [_trip(c) for c in ov_all], f"{t.name}: covered by anonymous symbol(s)"))
            continue
        foreign = next((c for c in ov_real if c.offset == lo),
                       ov_real[0] if ov_real else None)
        if foreign is not None and foreign.name in tgt_by_name:
            findings.append(Finding("reorder", section, _trip(t), [_trip(foreign)],
                f"{foreign.name} occupies the slot of {t.name}"))
        else:
            findings.append(Finding("anonymous", section, _trip(t),
                [_trip(c) for c in ov_all], f"{t.name}: unexpected current coverage"))
    return findings


def compare_layout(
    target_by_section: dict[str, list[Interval]],
    current_by_section: dict[str, list[Interval]],
    *,
    check_binding: bool = False,
) -> list[Finding]:
    cur_global: dict[str, tuple[str, Interval]] = {}
    for sec, ivs in current_by_section.items():
        for c in ivs:
            if not c.anonymous and c.name:
                cur_global.setdefault(c.name, (sec, c))

    out: list[Finding] = []
    for sec in sorted(set(target_by_section) | set(current_by_section)):
        for f in compare_section(sec, target_by_section.get(sec, []),
                                 current_by_section.get(sec, []),
                                 check_binding=check_binding):
            if f.kind in ("missing", "anonymous") and f.target:
                name = f.target[0]
                if name in cur_global and cur_global[name][0] != sec:
                    osec, oiv = cur_global[name]
                    f = Finding("section-mismatch", sec, f.target, [_trip(oiv)],
                        f"{name}: target section {sec} vs current {osec}")
            out.append(f)
    return out
