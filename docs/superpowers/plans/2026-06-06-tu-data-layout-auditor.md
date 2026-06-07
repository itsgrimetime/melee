# TU Data-Layout Auditor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only `melee-agent layout audit <file.c>` command that compares a TU's reference object (`build/GALE01/obj/<unit>.o`) against its current object (`build/GALE01/src/<unit>.o`) and reports data-layout discrepancies (split / merge / size-mismatch / reorder / binding / missing / anonymous / gap-change) with concrete source suggestions.

**Architecture:** A pure interval comparator at the core (no I/O, exhaustively unit-tested) fed by three I/O readers — an ELF data-symbol reader (pyelftools), a symbols.txt data-symbol parser, and a source declaration mapper. An orchestrator wires them and enriches findings with absolute addresses + source lines; a reporter renders text/JSON; a thin Typer CLI exposes it. Spec: `docs/superpowers/specs/2026-06-06-tu-data-layout-auditor-design.md`.

**Tech Stack:** Python 3, pyelftools (existing checkdiff dep), Typer (existing melee-agent CLI), pytest (existing `tools/melee-agent/tests/`).

**Conventions:**
- All paths below are relative to the repo root `tools/melee-agent/` unless absolute.
- Run tests from `tools/melee-agent/`: `python -m pytest tests/<file>::<test> -v`.
- Module imports inside the package use `from ..common.x import y` / `from .x import y`.
- Commit after each task. Branch: work on the current worktree's branch.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/common/elf_symbols.py` (NEW) | `ObjSymbol` dataclass + `read_object_symbols(path)` — read a `.o`'s symbol table via pyelftools. |
| `src/layout/__init__.py` (NEW) | Package marker. |
| `src/layout/symbols_data.py` (NEW) | `DataSymbol` + `load_data_symbols(melee_root)` — parse `type:object` rows from symbols.txt. |
| `src/layout/compare.py` (NEW) | `Interval`, `Finding`, `compare_section(...)` — the pure comparator core. |
| `src/layout/objects.py` (NEW) | Path resolution (`unit_paths`), object→intervals (`section_intervals`), absolute-address anchoring. |
| `src/layout/source_map.py` (NEW) | `map_decls(c_path)` — symbol name → declaration line(s). |
| `src/layout/audit.py` (NEW) | `audit_tu(...)` orchestrator + per-finding `suggest(...)`. |
| `src/layout/report.py` (NEW) | `render_text(...)` / `render_json(...)`. |
| `src/cli/layout.py` (NEW) | `layout_app` Typer group with the `audit` command. |
| `src/cli/__init__.py` (MODIFY ~line 35 + ~line 88) | Register `layout_app`. |
| `tests/test_elf_symbols.py` (NEW) | Reader unit tests (host-compiled fixture `.o`). |
| `tests/test_layout_symbols_data.py` (NEW) | symbols.txt data parser tests. |
| `tests/test_layout_compare.py` (NEW) | Comparator tests — one per discrepancy class. |
| `tests/test_layout_objects.py` (NEW) | Path resolution + anchoring tests. |
| `tests/test_layout_source_map.py` (NEW) | Source decl mapper tests. |
| `tests/test_layout_audit.py` (NEW) | Orchestrator (synthetic) + mnevent acceptance (skip-if-absent). |
| `tests/test_layout_report.py` (NEW) | Golden text/JSON output. |
| `tests/test_layout_cli.py` (NEW) | Typer CliRunner smoke test. |

---

## Task 1: ELF data-symbol reader (`common/elf_symbols.py`)

**Files:**
- Create: `tools/melee-agent/src/common/elf_symbols.py`
- Test: `tools/melee-agent/tests/test_elf_symbols.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_elf_symbols.py
import shutil
import subprocess
import pytest
from pathlib import Path
from src.common.elf_symbols import ObjSymbol, read_object_symbols


def _compile_fixture(tmp_path: Path) -> Path:
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no host C compiler available")
    src = tmp_path / "fix.c"
    src.write_text("int g_global = 7;\nstatic int g_local = 3;\nchar g_buf[10];\n")
    obj = tmp_path / "fix.o"
    rc = subprocess.run([cc, "-c", str(src), "-o", str(obj)], capture_output=True)
    if rc.returncode != 0:
        pytest.skip("host cc could not produce an object")
    return obj


def test_reads_named_object_symbols_with_sizes(tmp_path):
    obj = _compile_fixture(tmp_path)
    syms = {s.name: s for s in read_object_symbols(obj)}
    assert "g_global" in syms
    assert syms["g_global"].size == 4
    assert syms["g_global"].type == "STT_OBJECT"
    assert syms["g_global"].bind == "STB_GLOBAL"
    assert syms["g_buf"].size == 10


def test_missing_file_returns_empty(tmp_path):
    assert read_object_symbols(tmp_path / "nope.o") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_elf_symbols.py -v`
Expected: FAIL — `ModuleNotFoundError: src.common.elf_symbols`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/common/elf_symbols.py
"""Read a relocatable object's symbol table via pyelftools.

A clean, typed wrapper. (tools/checkdiff.py has a private equivalent,
_read_object_symbol_records; dedup is a possible later follow-up — out of
scope here to keep changes off that critical tool.)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ObjSymbol:
    name: str
    section: str | None  # e.g. ".data", ".bss", ".sdata2"; None if no section
    shndx: int
    value: int           # st_value — section-relative offset in a relocatable .o
    size: int            # st_size
    bind: str            # "STB_GLOBAL" | "STB_LOCAL" | "STB_WEAK"
    type: str            # "STT_OBJECT" | "STT_FUNC" | "STT_NOTYPE" | ...


def read_object_symbols(path: Path) -> list[ObjSymbol]:
    """Return all named symbols in ``path``'s .symtab. [] on any error."""
    try:
        from elftools.common.exceptions import ELFError
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return []

    try:
        with Path(path).open("rb") as f:
            elf = ELFFile(f)
            symtab = elf.get_section_by_name(".symtab")
            if symtab is None:
                return []
            out: list[ObjSymbol] = []
            for sym in symtab.iter_symbols():
                name = sym.name
                shndx = sym["st_shndx"]
                if not name or not isinstance(shndx, int):
                    continue
                info = sym["st_info"]
                section = elf.get_section(shndx)
                out.append(ObjSymbol(
                    name=name,
                    section=section.name if section is not None else None,
                    shndx=shndx,
                    value=int(sym["st_value"]),
                    size=int(sym["st_size"]),
                    bind=info["bind"],
                    type=info["type"],
                ))
            return out
    except (OSError, KeyError, TypeError, ValueError, ELFError):
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_elf_symbols.py -v`
Expected: PASS (2 passed, or skips if no host cc).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/common/elf_symbols.py tools/melee-agent/tests/test_elf_symbols.py
git commit -m "feat(layout): typed ELF symbol reader (common/elf_symbols)"
```

---

## Task 2: symbols.txt data-symbol parser (`layout/symbols_data.py`)

**Why a new parser:** `src/extractor/symbols.py` hard-codes `type:function` and its `FunctionSymbol` has no size/data fields for objects. We need `type:object` rows.

**Files:**
- Create: `tools/melee-agent/src/layout/__init__.py` (empty)
- Create: `tools/melee-agent/src/layout/symbols_data.py`
- Test: `tools/melee-agent/tests/test_layout_symbols_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layout_symbols_data.py
from src.layout.symbols_data import DataSymbol, parse_data_symbols

SAMPLE = """\
fn_8024D15C = .text:0x8024D15C; // type:function size:0x40 scope:global
mnEvent_803EF758 = .data:0x803EF758; // type:object size:0x30 scope:global
mnEvent_803EF788 = .data:0x803EF788; // type:object size:0xA scope:global data:string
mnEvent_804A0908 = .bss:0x804A0908; // type:object size:0x10 scope:global data:4byte
mnEvent_804DC150 = .sdata2:0x804DC150; // type:object size:0x4 scope:global align:4 data:float
"""


def test_parses_only_object_symbols():
    syms = parse_data_symbols(SAMPLE.splitlines())
    assert "fn_8024D15C" not in syms  # functions excluded
    assert syms["mnEvent_803EF758"] == DataSymbol(
        name="mnEvent_803EF758", section="data", address=0x803EF758,
        size=0x30, scope="global", data_kind=None)
    assert syms["mnEvent_803EF788"].data_kind == "string"
    assert syms["mnEvent_804DC150"].section == "sdata2"
    assert syms["mnEvent_804A0908"].size == 0x10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_symbols_data.py -v`
Expected: FAIL — `ModuleNotFoundError: src.layout.symbols_data`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/layout/__init__.py  (create empty)
```

```python
# src/layout/symbols_data.py
"""Parse data (type:object) symbols from config/GALE01/symbols.txt."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DATA_SECTIONS = {"data", "bss", "sdata", "sdata2", "sbss", "sbss2", "rodata"}

# name = section:0xADDR; // type:object size:0xN scope:... [align:N] [data:kind]
_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z_]\w*)\s*=\s*"
    r"(?P<section>[\w.]+):0x(?P<addr>[0-9A-Fa-f]+)\s*;"
    r"(?:\s*//\s*(?P<meta>.*))?$"
)
_ATTR = re.compile(r"(\w+):(\S+)")


@dataclass(frozen=True)
class DataSymbol:
    name: str
    section: str       # symbols.txt section without leading dot, e.g. "data"
    address: int       # absolute linked address
    size: int
    scope: str | None
    data_kind: str | None  # "string" | "float" | "double" | "4byte" | ...


def parse_data_symbols(lines: Iterable[str]) -> dict[str, DataSymbol]:
    out: dict[str, DataSymbol] = {}
    for line in lines:
        m = _LINE.match(line)
        if not m:
            continue
        section = m.group("section").lstrip(".")
        if section not in DATA_SECTIONS:
            continue
        attrs = dict(_ATTR.findall(m.group("meta") or ""))
        if attrs.get("type") != "object":
            continue
        try:
            size = int(attrs.get("size", "0"), 0)
        except ValueError:
            size = 0
        out[m.group("name")] = DataSymbol(
            name=m.group("name"),
            section=section,
            address=int(m.group("addr"), 16),
            size=size,
            scope=attrs.get("scope"),
            data_kind=attrs.get("data"),
        )
    return out


def load_data_symbols(melee_root: Path) -> dict[str, DataSymbol]:
    path = Path(melee_root) / "config" / "GALE01" / "symbols.txt"
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return parse_data_symbols(f)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_symbols_data.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/layout/__init__.py tools/melee-agent/src/layout/symbols_data.py tools/melee-agent/tests/test_layout_symbols_data.py
git commit -m "feat(layout): symbols.txt data-symbol parser"
```

---

## Task 3: Pure interval comparator (`layout/compare.py`) — CORE

This is the heart of the tool and must be exhaustively tested. It is pure (no I/O): it takes target and current intervals for ONE section and returns findings.

**Algorithm (per section), in precedence order so each target interval gets ONE primary finding:**
1. Build `name → Interval` for non-anonymous target and current.
2. For each TARGET interval `t` (sorted by offset):
   - Collect current intervals overlapping `[t.offset, t.offset+t.size)`.
   - If none → **missing**.
   - Else if all overlapping current are anonymous → **anonymous**.
   - Else if a single current `c` starts at `t.offset` and `c.size == t.size` and `c.name == t.name`:
     - if `c.binding != t.binding` → **binding-mismatch**, else **ok** (no finding).
   - Else if a single current `c` starts at `t.offset`, `c.name == t.name`, `c.size != t.size` → **size-mismatch**.
   - Else if ≥2 non-anonymous current intervals lie within `t` → **split**.
   - Else if a single current `c` overlaps `t` AND also overlaps the next target (i.e. `c` spans ≥2 targets) → **merge** (reported once on the first covered target).
   - Else if the current interval at `t.offset` has a different name that exists elsewhere in the target set → **reorder**.
   - Else → **anonymous** (fallback: covered by an unexpected/foreign symbol).
3. Gaps: compute inter-interval gaps for target and current; only emit **gap-change** when a target gap's size differs from the aligned current gap, or a real (non-anonymous) current object overlaps a target gap.

**Files:**
- Create: `tools/melee-agent/src/layout/compare.py`
- Test: `tools/melee-agent/tests/test_layout_compare.py`

- [ ] **Step 1: Write the failing tests (one per class)**

```python
# tests/test_layout_compare.py
from src.layout.compare import Interval, compare_section


def I(name, off, size, binding="STB_GLOBAL", anonymous=False):
    return Interval(name=name, offset=off, size=size, binding=binding, anonymous=anonymous)


def kinds(findings):
    return {f.kind for f in findings}


def test_ok_identical_layout_no_findings():
    t = [I("a", 0, 0xC), I("b", 0xC, 0xC)]
    c = [I("a", 0, 0xC), I("b", 0xC, 0xC)]
    assert compare_section(".data", t, c) == []


def test_split_one_target_many_current():
    t = [I("blob", 0, 0x30)]
    c = [I("blob", 0, 0xC), I("p1", 0xC, 0xC), I("p2", 0x18, 0xC), I("p3", 0x24, 0xC)]
    f = compare_section(".data", t, c)
    assert "split" in kinds(f)


def test_size_mismatch_same_name_same_offset():
    t = [I("s", 0, 0xA)]
    c = [I("s", 0, 0xC)]
    f = compare_section(".data", t, c)
    assert any(x.kind == "size-mismatch" and x.target[0] == "s" for x in f)


def test_merge_one_current_spans_two_targets():
    t = [I("a", 0, 0xC), I("b", 0xC, 0xC)]
    c = [I("a", 0, 0x18)]
    assert "merge" in kinds(compare_section(".data", t, c))


def test_reorder_name_at_wrong_offset():
    t = [I("a", 0, 0x8), I("b", 0x8, 0x8)]
    c = [I("b", 0, 0x8), I("a", 0x8, 0x8)]
    assert "reorder" in kinds(compare_section(".sdata", t, c))


def test_binding_mismatch():
    t = [I("a", 0, 0x8, binding="STB_GLOBAL")]
    c = [I("a", 0, 0x8, binding="STB_LOCAL")]
    assert "binding-mismatch" in kinds(compare_section(".data", t, c))


def test_missing_target_uncovered():
    t = [I("a", 0, 0x8), I("gen", 0x8, 0x8)]
    c = [I("a", 0, 0x8)]
    assert "missing" in kinds(compare_section(".sdata2", t, c))


def test_anonymous_current_covers_target():
    t = [I("lit", 0, 0x4)]
    c = [I("@123", 0, 0x4, anonymous=True)]
    assert "anonymous" in kinds(compare_section(".sdata2", t, c))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_compare.py -v`
Expected: FAIL — `ModuleNotFoundError: src.layout.compare`.

- [ ] **Step 3: Write the implementation**

```python
# src/layout/compare.py
"""Pure interval comparator: classify data-layout discrepancies for one section."""
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
    kind: str          # split|merge|size-mismatch|reorder|binding-mismatch|missing|anonymous|gap-change
    section: str
    target: tuple[str | None, int, int] | None  # (name, offset, size)
    current: list[tuple[str | None, int, int]] = field(default_factory=list)
    message: str = ""
    confidence: str = "high"


def _overlaps(a: Interval, lo: int, hi: int) -> bool:
    return a.offset < hi and a.end > lo


def _trip(iv: Interval) -> tuple[str | None, int, int]:
    return (iv.name, iv.offset, iv.size)


def compare_section(
    section: str,
    target: list[Interval],
    current: list[Interval],
) -> list[Finding]:
    target = sorted(target, key=lambda i: i.offset)
    current = sorted(current, key=lambda i: i.offset)
    cur_by_name = {c.name: c for c in current if not c.anonymous and c.name}
    tgt_by_name = {t.name: t for t in target if not t.anonymous and t.name}
    findings: list[Finding] = []
    merged_reported: set[int] = set()

    for idx, t in enumerate(target):
        lo, hi = t.offset, t.end
        ov = [c for c in current if _overlaps(c, lo, hi)]
        if not ov:
            findings.append(Finding("missing", section, _trip(t),
                                    [], f"{t.name}: target object absent in current object"))
            continue
        if all(c.anonymous for c in ov):
            findings.append(Finding("anonymous", section, _trip(t),
                                    [_trip(c) for c in ov],
                                    f"{t.name}: covered by anonymous symbol(s)"))
            continue
        named_inside = [c for c in ov if not c.anonymous
                        and c.offset >= lo and c.end <= hi]
        # single same-offset same-name current
        same = next((c for c in ov if not c.anonymous and c.offset == t.offset
                     and c.name == t.name), None)
        if same is not None and same.size == t.size:
            if (t.binding is not None and same.binding is not None
                    and same.binding != t.binding):
                findings.append(Finding("binding-mismatch", section, _trip(t),
                                        [_trip(same)],
                                        f"{t.name}: binding {same.binding} vs {t.binding}"))
            continue
        if same is not None and same.size != t.size:
            findings.append(Finding("size-mismatch", section, _trip(t),
                                    [_trip(same)],
                                    f"{t.name}: size 0x{same.size:X} vs target 0x{t.size:X}"))
            continue
        # one current spanning >=2 targets -> merge
        span = next((c for c in ov if not c.anonymous and c.offset <= t.offset
                     and c.end > (target[idx + 1].offset if idx + 1 < len(target) else hi)
                     and idx + 1 < len(target)), None)
        if span is not None and span.offset not in merged_reported:
            merged_reported.add(span.offset)
            findings.append(Finding("merge", section, _trip(t), [_trip(span)],
                                    f"current {span.name} spans multiple target objects"))
            continue
        # >=2 named current inside target -> split
        if len(named_inside) >= 2:
            findings.append(Finding("split", section, _trip(t),
                                    [_trip(c) for c in named_inside],
                                    f"{t.name} (0x{t.size:X}) split into "
                                    f"{len(named_inside)} current objects"))
            continue
        # foreign name at this offset that belongs elsewhere -> reorder
        at = next((c for c in ov if not c.anonymous and c.offset == t.offset), None)
        if at is not None and at.name in tgt_by_name and tgt_by_name[at.name].offset != at.offset:
            findings.append(Finding("reorder", section, _trip(t), [_trip(at)],
                                    f"{at.name} at offset 0x{at.offset:X} "
                                    f"(target slot of {t.name})"))
            continue
        findings.append(Finding("anonymous", section, _trip(t),
                                [_trip(c) for c in ov],
                                f"{t.name}: unexpected current coverage"))

    findings.extend(_gap_findings(section, target, current))
    return findings


def _gaps(ivs: list[Interval]) -> list[tuple[int, int]]:
    out = []
    for a, b in zip(ivs, ivs[1:]):
        if b.offset > a.end:
            out.append((a.end, b.offset - a.end))
    return out


def _gap_findings(section, target, current) -> list[Finding]:
    tgaps = dict(_gaps(target))
    cgaps = dict(_gaps(current))
    out = []
    for off, size in tgaps.items():
        if off in cgaps and cgaps[off] != size:
            out.append(Finding("gap-change", section, None, [],
                               f"padding at 0x{off:X}: 0x{cgaps[off]:X} vs target 0x{size:X}"))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_compare.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/layout/compare.py tools/melee-agent/tests/test_layout_compare.py
git commit -m "feat(layout): pure interval comparator with per-class classification"
```

---

## Task 4: Object paths + intervals + anchoring (`layout/objects.py`)

**Files:**
- Create: `tools/melee-agent/src/layout/objects.py`
- Test: `tools/melee-agent/tests/test_layout_objects.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layout_objects.py
from pathlib import Path
from src.layout.objects import unit_paths, UnitPaths


def test_unit_paths_from_c_file():
    up = unit_paths(Path("/repo"), Path("src/melee/mn/mnevent.c"))
    assert isinstance(up, UnitPaths)
    assert up.obj_path == "melee/mn/mnevent"
    assert up.ref_obj == Path("/repo/build/GALE01/obj/melee/mn/mnevent.o")
    assert up.our_obj == Path("/repo/build/GALE01/src/melee/mn/mnevent.o")


def test_unit_paths_accepts_absolute_under_src(tmp_path):
    c = tmp_path / "src" / "melee" / "it" / "item.c"
    up = unit_paths(tmp_path, c)
    assert up.obj_path == "melee/it/item"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_objects.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/layout/objects.py
"""Resolve a TU's ref/our object paths and read their data-section intervals."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..common.elf_symbols import ObjSymbol, read_object_symbols
from .compare import DATA_ELF_SECTIONS, Interval

_ANON = ("@", "...", "lbl_", "$")  # heuristic anonymous markers


@dataclass(frozen=True)
class UnitPaths:
    obj_path: str       # e.g. "melee/mn/mnevent"
    ref_obj: Path       # build/GALE01/obj/<obj_path>.o
    our_obj: Path       # build/GALE01/src/<obj_path>.o


def unit_paths(repo: Path, c_file: Path) -> UnitPaths:
    repo = Path(repo)
    c = Path(c_file)
    if c.is_absolute():
        c = c.relative_to(repo)
    parts = c.with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    obj_path = "/".join(parts)
    return UnitPaths(
        obj_path=obj_path,
        ref_obj=repo / "build" / "GALE01" / "obj" / f"{obj_path}.o",
        our_obj=repo / "build" / "GALE01" / "src" / f"{obj_path}.o",
    )


def _is_anonymous(name: str) -> bool:
    return (not name) or name.startswith(_ANON) or ".data." in name


def section_intervals(obj: Path) -> dict[str, list[Interval]]:
    """Group a .o's data-section object symbols into Intervals by ELF section."""
    out: dict[str, list[Interval]] = {}
    for s in read_object_symbols(obj):
        if s.section not in DATA_ELF_SECTIONS:
            continue
        if s.type not in ("STT_OBJECT", "STT_NOTYPE"):
            continue
        out.setdefault(s.section, []).append(Interval(
            name=s.name, offset=s.value, size=s.size,
            binding=s.bind, anonymous=_is_anonymous(s.name),
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_objects.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/layout/objects.py tools/melee-agent/tests/test_layout_objects.py
git commit -m "feat(layout): object path resolution + section intervals"
```

---

## Task 5: Source declaration mapper (`layout/source_map.py`)

**Files:**
- Create: `tools/melee-agent/src/layout/source_map.py`
- Test: `tools/melee-agent/tests/test_layout_source_map.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layout_source_map.py
from src.layout.source_map import map_decls

SRC = '''\
#include "x.h"
static AnimLoopSettings mnEvent_803EF758 = { 0, 199.0f, 0 };
static Vec3 mnEvent_803EF764 = { -3.8f, -0.6f, 0 };
static char mnEvent_803EF788[0xC] = "translate";
void fn_8024D15C(void) { mnEvent_803EF764.x = 1.0f; }
'''


def test_maps_symbol_names_to_decl_lines(tmp_path):
    p = tmp_path / "mnevent.c"
    p.write_text(SRC)
    decls = map_decls(p)
    assert decls["mnEvent_803EF758"].line == 2
    assert decls["mnEvent_803EF788"].line == 4
    assert decls["mnEvent_803EF788"].is_static is True
    # a name only *used* (not declared at file scope) is not a decl
    assert "fn_8024D15C" not in decls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_source_map.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/layout/source_map.py
"""Best-effort map from data-symbol name -> its file-scope declaration line."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# file-scope decl: optional storage/qualifiers, a type, the NAME, optional [..], then = or ;
_DECL = re.compile(
    r"^\s*(?P<static>static\s+)?(?:const\s+)?(?:volatile\s+)?"
    r"[A-Za-z_]\w*[\w\s\*]*?\b(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])*\s*(?:=|;)"
)


@dataclass(frozen=True)
class Decl:
    name: str
    line: int
    is_static: bool


def map_decls(c_file: Path) -> dict[str, Decl]:
    out: dict[str, Decl] = {}
    depth = 0
    for n, raw in enumerate(Path(c_file).read_text(errors="replace").splitlines(), 1):
        # crude file-scope tracking: skip lines inside braces (function bodies)
        if depth == 0:
            m = _DECL.match(raw)
            if m and "(" not in raw.split(m.group("name"))[0]:
                out.setdefault(m.group("name"),
                               Decl(m.group("name"), n, bool(m.group("static"))))
        depth += raw.count("{") - raw.count("}")
        if depth < 0:
            depth = 0
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_source_map.py -v`
Expected: PASS.

Note: `map_decls` is best-effort for suggestions only; a miss yields a finding without a line number, never a crash (spec error-handling).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/layout/source_map.py tools/melee-agent/tests/test_layout_source_map.py
git commit -m "feat(layout): best-effort source declaration mapper"
```

---

## Task 6: Orchestrator + suggester (`layout/audit.py`)

**Files:**
- Create: `tools/melee-agent/src/layout/audit.py`
- Test: `tools/melee-agent/tests/test_layout_audit.py`

- [ ] **Step 1: Write the failing test (synthetic + mnevent acceptance)**

```python
# tests/test_layout_audit.py
from pathlib import Path
import pytest
from src.layout.audit import audit_tu, AuditResult, suggest
from src.layout.compare import Finding

REPO = Path(__file__).resolve().parents[3]  # repo root from tools/melee-agent/tests/


def test_suggest_covers_every_kind():
    for kind in ["split", "merge", "size-mismatch", "reorder",
                 "binding-mismatch", "missing", "anonymous", "gap-change"]:
        f = Finding(kind, ".data", ("s", 0, 8), [("s", 0, 8)], "msg")
        assert suggest(f)  # non-empty suggestion string


@pytest.mark.skipif(
    not (REPO / "build/GALE01/obj/melee/mn/mnevent.o").exists()
    or not (REPO / "build/GALE01/src/melee/mn/mnevent.o").exists(),
    reason="mnevent objects not built",
)
def test_mnevent_acceptance_flags_known_issues():
    res = audit_tu(REPO, REPO / "src/melee/mn/mnevent.c")
    assert isinstance(res, AuditResult)
    kinds_by_name = {(f.target[0] if f.target else None): f.kind
                     for f in res.findings}
    # _758 split, _788 size, _804A0908 bss size
    assert kinds_by_name.get("mnEvent_803EF758") == "split"
    assert kinds_by_name.get("mnEvent_803EF788") == "size-mismatch"
    assert kinds_by_name.get("mnEvent_804A0908") == "size-mismatch"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_audit.py -v`
Expected: FAIL — `ModuleNotFoundError` (acceptance test may skip).

- [ ] **Step 3: Write minimal implementation**

```python
# src/layout/audit.py
"""Orchestrate a TU data-layout audit and attach suggestions/locations."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .compare import Finding, compare_section
from .objects import section_intervals, unit_paths
from .source_map import map_decls
from .symbols_data import load_data_symbols

_SUGGEST = {
    "split": "Model one object of the target size; reference sub-fields by offset.",
    "merge": "Split the source blob into the target's distinct objects.",
    "size-mismatch": "Resize the array/type to the target size.",
    "reorder": "Reorder the declarations to match target address order.",
    "binding-mismatch": "Fix static/global to match the target binding.",
    "missing": "Model this generated/literal object (it is unmodeled in source).",
    "anonymous": "Give this data a named declaration matching the production symbol.",
    "gap-change": "Adjust preceding object size/alignment so padding matches.",
}


def suggest(f: Finding) -> str:
    return _SUGGEST.get(f.kind, "Investigate this data-layout discrepancy.")


@dataclass(frozen=True)
class EnrichedFinding:
    finding: Finding
    source_line: int | None
    suggestion: str


@dataclass(frozen=True)
class AuditResult:
    obj_path: str
    degraded: bool
    warnings: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    enriched: list[EnrichedFinding] = field(default_factory=list)


def audit_tu(repo: Path, c_file: Path) -> AuditResult:
    repo = Path(repo)
    up = unit_paths(repo, c_file)
    warnings: list[str] = []

    if not up.ref_obj.exists():
        return AuditResult(up.obj_path, degraded=True,
                           warnings=[f"reference object missing: {up.ref_obj} "
                                     "(degraded mode not implemented in v1)"])
    if not up.our_obj.exists():
        return AuditResult(up.obj_path, degraded=True,
                           warnings=[f"current object missing: {up.our_obj}; "
                                     "build it for high-confidence audit"])

    # staleness: our .o older than the source
    try:
        if up.our_obj.stat().st_mtime < Path(c_file).stat().st_mtime:
            warnings.append("current object is older than source; rebuild for accuracy")
    except OSError:
        warnings.append("freshness unknown")

    target = section_intervals(up.ref_obj)
    current = section_intervals(up.our_obj)
    decls = map_decls(c_file)

    findings: list[Finding] = []
    for section in sorted(set(target) | set(current)):
        findings.extend(compare_section(section,
                                        target.get(section, []),
                                        current.get(section, [])))

    enriched = []
    for f in findings:
        name = f.target[0] if f.target else None
        line = decls[name].line if name in decls else None
        enriched.append(EnrichedFinding(f, line, suggest(f)))

    return AuditResult(up.obj_path, degraded=False, warnings=warnings,
                       findings=findings, enriched=enriched)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_audit.py -v`
Expected: PASS (acceptance test passes if mnevent objects exist; else skips). If the acceptance test FAILS (not skips), the comparator or interval mapping needs fixing — debug against real `nm -S` output before proceeding.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/layout/audit.py tools/melee-agent/tests/test_layout_audit.py
git commit -m "feat(layout): audit orchestrator + suggestions + acceptance test"
```

---

## Task 7: Reporter (`layout/report.py`)

**Files:**
- Create: `tools/melee-agent/src/layout/report.py`
- Test: `tools/melee-agent/tests/test_layout_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layout_report.py
import json
from src.layout.compare import Finding
from src.layout.audit import AuditResult, EnrichedFinding
from src.layout.report import render_text, render_json


def _result():
    f = Finding("size-mismatch", ".data", ("mnEvent_803EF788", 0x48, 0xA),
                [("mnEvent_803EF788", 0x48, 0xC)], "size 0xC vs target 0xA")
    ef = EnrichedFinding(f, source_line=89, suggestion="Resize the array/type.")
    return AuditResult("melee/mn/mnevent", degraded=False, warnings=["w1"],
                       findings=[f], enriched=[ef])


def test_render_text_groups_and_shows_suggestion():
    out = render_text(_result())
    assert "melee/mn/mnevent" in out
    assert "size-mismatch" in out
    assert "mnEvent_803EF788" in out
    assert "Resize the array/type." in out
    assert ":89" in out  # source line


def test_render_json_roundtrips():
    out = json.loads(render_json(_result()))
    assert out["obj_path"] == "melee/mn/mnevent"
    assert out["findings"][0]["kind"] == "size-mismatch"
    assert out["findings"][0]["source_line"] == 89
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_report.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/layout/report.py
"""Render an AuditResult as text or JSON."""
from __future__ import annotations

import json

from .audit import AuditResult


def render_text(res: AuditResult) -> str:
    lines = [f"data-layout audit: {res.obj_path}"
             + ("  [DEGRADED]" if res.degraded else "")]
    for w in res.warnings:
        lines.append(f"  ! {w}")
    by_section: dict[str, list] = {}
    for ef in res.enriched:
        by_section.setdefault(ef.finding.section, []).append(ef)
    if not res.enriched:
        lines.append("  no data-layout discrepancies found")
    for section in sorted(by_section):
        lines.append(f"\n{section}")
        for ef in by_section[section]:
            f = ef.finding
            name = f.target[0] if f.target else "(gap)"
            loc = f" ({res.obj_path}.c:{ef.source_line})" if ef.source_line else ""
            lines.append(f"  [{f.kind}] {name}{loc}: {f.message}")
            lines.append(f"      -> {ef.suggestion}")
    return "\n".join(lines)


def render_json(res: AuditResult) -> str:
    return json.dumps({
        "obj_path": res.obj_path,
        "degraded": res.degraded,
        "warnings": res.warnings,
        "findings": [{
            "kind": ef.finding.kind,
            "section": ef.finding.section,
            "target": ef.finding.target,
            "current": ef.finding.current,
            "message": ef.finding.message,
            "confidence": ef.finding.confidence,
            "source_line": ef.source_line,
            "suggestion": ef.suggestion,
        } for ef in res.enriched],
    }, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/layout/report.py tools/melee-agent/tests/test_layout_report.py
git commit -m "feat(layout): text + JSON reporter"
```

---

## Task 8: CLI wiring (`cli/layout.py` + register)

**Files:**
- Create: `tools/melee-agent/src/cli/layout.py`
- Modify: `tools/melee-agent/src/cli/__init__.py` (add import near line 35; `add_typer` near line 88)
- Test: `tools/melee-agent/tests/test_layout_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layout_cli.py
from typer.testing import CliRunner
from src.cli.layout import layout_app

runner = CliRunner()


def test_audit_help_lists_command():
    res = runner.invoke(layout_app, ["audit", "--help"])
    assert res.exit_code == 0
    assert "file" in res.output.lower()


def test_audit_missing_file_errors_cleanly(tmp_path):
    res = runner.invoke(layout_app, ["audit", str(tmp_path / "nope.c")])
    assert res.exit_code != 0
    assert "not found" in res.output.lower() or "no such" in res.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: src.cli.layout`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/cli/layout.py
"""`melee-agent layout` — TU data-layout auditing."""
from __future__ import annotations

from pathlib import Path

import typer

from ..mwcc_debug.dtk_objdump import find_melee_root  # confirmed: dtk_objdump.py:69
from ..layout.audit import audit_tu
from ..layout.report import render_json, render_text

layout_app = typer.Typer(help="Audit TU data layout (sections/symbols) vs target")


@layout_app.command("audit")
def audit_cmd(
    file: Path = typer.Argument(..., help="Path to the TU .c file"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    root: Path = typer.Option(None, "--root", help="Repo root (default: auto)"),
) -> None:
    """Report data-layout discrepancies for a TU's .c file."""
    repo = Path(root) if root else find_melee_root()
    c = Path(file)
    if not c.is_absolute():
        c = repo / c
    if not c.exists():
        typer.echo(f"error: file not found: {c}", err=True)
        raise typer.Exit(2)
    res = audit_tu(repo, c)
    typer.echo(render_json(res) if json_out else render_text(res))
    raise typer.Exit(1 if res.enriched else 0)
```

Then modify `src/cli/__init__.py`:

```python
# near line 35 (with the other `from .X import X_app` lines)
from .layout import layout_app
# near line 88 (with the other app.add_typer(...) lines)
app.add_typer(layout_app, name="layout")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_cli.py -v`
Then smoke-test registration:
Run: `cd tools/melee-agent && python -m src.launcher layout audit --help`
Expected: PASS; help text shown; command registered under `melee-agent layout`.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/layout.py tools/melee-agent/src/cli/__init__.py tools/melee-agent/tests/test_layout_cli.py
git commit -m "feat(layout): melee-agent layout audit CLI command"
```

---

## Task 9: End-to-end acceptance + generalization validation

**Files:** none new (validation task). Uses the real build objects.

- [ ] **Step 1: Run the full layout test suite**

Run: `cd tools/melee-agent && python -m pytest tests/test_elf_symbols.py tests/test_layout_symbols_data.py tests/test_layout_compare.py tests/test_layout_objects.py tests/test_layout_source_map.py tests/test_layout_audit.py tests/test_layout_report.py tests/test_layout_cli.py -v`
Expected: all PASS (acceptance test passes, not skips, if `build/GALE01/{obj,src}/melee/mn/mnevent.o` exist — build them first with `ninja build/GALE01/src/melee/mn/mnevent.o` if needed).

- [ ] **Step 2: Run the auditor on mnevent and eyeball output**

Run: `cd tools/melee-agent && python -m src.launcher layout audit ../../src/melee/mn/mnevent.c`
(The `--root` defaults to auto-detected repo root; pass `--root <repo>` if needed.)
Expected: reports `[split] mnEvent_803EF758`, `[size-mismatch] mnEvent_803EF788`, `[size-mismatch] mnEvent_804A0908`, and `.sdata` reorder/missing, each with a suggestion.

- [ ] **Step 3: Generalization — run on a second TU**

Run: `cd tools/melee-agent && python -m src.launcher layout audit src/melee/ft/chara/ftCommon/ftCo_*.c` (pick the ftCo_ThrownKirby TU file) and a `groldyoshi` file.
Expected: surfaces `.sdata2` float-pool discrepancies (anonymous/missing/reorder). Capture output; confirm no crashes and findings are plausible.

- [ ] **Step 4: Hand-validate ONE suggestion via checkdiff**

Pick the lowest-risk mnevent suggestion (e.g. resize `mnEvent_803EF788` to `[0xA]`), apply it to `src/melee/mn/mnevent.c`, rebuild, and confirm the data symbol now matches:
Run: `cd /Users/mike/code/melee/.claude/worktrees/goofy-burnell-a2a060 && python tools/checkdiff.py <a function in mnevent that references _788> --no-tty`
Expected: the data-symbol mismatch for that object is resolved (or the function's data reloc now targets the named symbol). Revert the edit afterward (the auditor is read-only; this is a one-off validation). Document the before/after in the PR description.

- [ ] **Step 5: Commit any test refinements**

```bash
git add -A tools/melee-agent/tests/
git commit -m "test(layout): end-to-end acceptance + generalization coverage"
```

---

## Self-Review notes (filled during writing-plans self-review)

- **Spec coverage:** object-vs-object (Task 4/6), pyelftools no dtk/nm (Task 1), target=all symbols in ref obj (Task 4 reads ref obj; symbols.txt parser Task 2 supplies names/addrs/size cross-check — see follow-up below), interval+gap model (Task 3), missing≠anonymous (Task 3), binding (Task 3), degraded/staleness (Task 6), `layout_common`-style shared reader (Task 1 in `common/`), new module + CLI (Task 8), acceptance+generalization+hand-validation (Task 9).
- **Scope decision — symbols.txt role (raise in Codex plan review):** v1 uses the ref object (`build/GALE01/obj`) as the authoritative target — its data symbols are named per the address convention (`mnEvent_803EF758` encodes addr `0x803EF758`), so names already convey addresses and the comparison is fully self-contained (Tasks 1/3/4/6). Task 2 (symbols.txt data parser) is therefore NOT on the v1 critical path; it is built+tested for two concrete uses: (a) naming/absolute-address display for the rare *semantically*-named data symbol whose ELF name does not encode its address, and (b) a future `--cross-check` flagging ref-object-size vs symbols.txt-size disagreement. If the Codex review judges (a)/(b) not worth v1 cost, DROP Task 2 and its test (pure YAGNI) and the rest of the plan is unaffected. The orchestrator (Task 6) wires symbols.txt only if Task 2 is kept; otherwise `audit_tu` ignores it. This is a bounded keep-or-drop toggle, not an unfinished requirement.
- **Anonymous detection** (`_is_anonymous`, Task 4) is heuristic (`@`, `...`, `.data.`, `lbl_`, `$`). Validate against real mnevent objects in Task 9 and tighten if it mis-flags.
- **Reorder vs merge precedence:** comparator handles merge before split before reorder; covered by Task 3 tests. If Task 9 shows a real case mis-classified, add a regression test to `test_layout_compare.py` first, then fix.
