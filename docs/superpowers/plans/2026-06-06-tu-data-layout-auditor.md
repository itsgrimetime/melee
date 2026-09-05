# TU Data-Layout Auditor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only `melee-agent layout audit <file.c>` command that compares a TU's reference object (`build/GALE01/obj/<unit>.o`) against its current object (`build/GALE01/src/<unit>.o`) and reports data-layout discrepancies (split / merge / size-mismatch / reorder / section-mismatch / missing / anonymous, plus opt-in binding) with concrete source suggestions.

**Architecture:** A pure interval comparator at the core (no I/O, exhaustively unit-tested) fed by an ELF data-symbol reader (pyelftools) and a source declaration mapper. An orchestrator wires them and a reporter renders text/JSON; a thin Typer CLI exposes it. Spec: `docs/superpowers/specs/2026-06-06-tu-data-layout-auditor-design.md`.

**Tech Stack:** Python 3, pyelftools (existing checkdiff dep), Typer (existing melee-agent CLI), pytest (existing `tools/melee-agent/tests/`).

**Reviewed:** Codex design (2 rounds) + plan (1 round, no-go → this revision applies all 7 findings). Notable decisions from review: comparator precedence is merge→split→same-name→reorder; cross-section moves are `section-mismatch`; `gap_*` ref symbols are filtered as padding; binding checks are opt-in; symbols.txt parsing is OUT of v1 (the ref object's address-encoded names are authoritative — symbols.txt absolute-anchoring/cross-check is a documented phase-2); `gap-change` is deferred to phase-2 (subsumed by size-mismatch in practice).

**Conventions:**
- Paths below are relative to repo root unless absolute. Package root: `tools/melee-agent/`.
- Run tests from `tools/melee-agent/`: `python -m pytest tests/<file>::<test> -v`.
- Package imports: `from ..common.x import y` / `from .x import y`; tests use `from src.x import y`.
- The runnable CLI module is `python -m src.cli` (NOT `src.launcher`, which has no `__main__` guard). The installed entry point is `melee-agent`.
- Commit after each task on the current worktree branch.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/common/elf_symbols.py` (NEW) | `ObjSymbol` + `read_object_symbols(path)` — read a `.o`'s symbol table via pyelftools. |
| `src/layout/__init__.py` (NEW) | Package marker. |
| `src/layout/compare.py` (NEW) | `Interval`, `Finding`, `compare_section(...)`, `compare_layout(...)` — pure comparator core. |
| `src/layout/objects.py` (NEW) | `unit_paths(...)` path resolution + `section_intervals(...)` object→intervals (filters `gap_*`/anonymous). |
| `src/layout/source_map.py` (NEW) | `map_decls(c_path)` — symbol name → declaration line. |
| `src/layout/audit.py` (NEW) | `audit_tu(...)` orchestrator + `suggest(...)`. |
| `src/layout/report.py` (NEW) | `render_text(...)` / `render_json(...)`. |
| `src/cli/layout.py` (NEW) | `layout_app` Typer group with the `audit` command. |
| `src/cli/__init__.py` (MODIFY ~line 35 import + ~line 88 add_typer) | Register `layout_app`. |
| `tests/test_elf_symbols.py` (NEW) | Reader unit tests (host-compiled fixture `.o`). |
| `tests/test_layout_compare.py` (NEW) | Comparator tests — one per discrepancy class + cross-section. |
| `tests/test_layout_objects.py` (NEW) | Path resolution + `gap_*`/anonymous filtering. |
| `tests/test_layout_source_map.py` (NEW) | Source decl mapper. |
| `tests/test_layout_audit.py` (NEW) | Orchestrator (synthetic) + mnevent acceptance (skip-if-absent). |
| `tests/test_layout_report.py` (NEW) | Golden text/JSON output. |
| `tests/test_layout_cli.py` (NEW) | Typer CliRunner smoke test. |

---

## Task 1: ELF symbol reader (`common/elf_symbols.py`)

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
    syms = {s.name: s for s in read_object_symbols(_compile_fixture(tmp_path))}
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

Clean typed wrapper. (tools/checkdiff.py has a private equivalent,
_read_object_symbol_records; dedup is a possible later follow-up — kept off
that critical tool here to bound blast radius.)
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
Expected: PASS (or skip if no host cc).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/common/elf_symbols.py tools/melee-agent/tests/test_elf_symbols.py
git commit -m "feat(layout): typed ELF symbol reader (common/elf_symbols)"
```

---

## Task 2: Pure interval comparator (`layout/compare.py`) — CORE

The heart of the tool; pure (no I/O). `compare_section` classifies ONE section; `compare_layout` runs all sections and reclassifies cross-section moves.

**Per-target precedence (each real target gets ONE finding):**
1. Skip a target already covered by a reported **merge** range.
2. **merge** — a real current symbol spans this target into the next real target.
3. **split** — ≥2 real current symbols lie inside this target.
4. same-name current in this section:
   - different offset → **reorder**; else different size → **size-mismatch**;
     else (opt-in) different binding → **binding-mismatch**; else ok.
5. name absent here: no overlap → **missing**; all-anonymous overlap → **anonymous**;
   a foreign target-known name at this slot → **reorder**; else → **anonymous**.

`compare_layout` then upgrades a **missing** whose name appears in another current section to **section-mismatch** (handles `.bss`↔`.sbss`, etc.).

**Files:**
- Create: `tools/melee-agent/src/layout/__init__.py` (empty)
- Create: `tools/melee-agent/src/layout/compare.py`
- Test: `tools/melee-agent/tests/test_layout_compare.py`

- [ ] **Step 1: Write the failing tests (one per class + cross-section)**

```python
# tests/test_layout_compare.py
from src.layout.compare import Interval, compare_section, compare_layout


def I(name, off, size, binding="STB_GLOBAL", anonymous=False):
    return Interval(name=name, offset=off, size=size, binding=binding, anonymous=anonymous)


def kinds(fs):
    return {f.kind for f in fs}


def test_ok_identical_layout_no_findings():
    t = [I("a", 0, 0xC), I("b", 0xC, 0xC)]
    assert compare_section(".data", t, list(t)) == []


def test_split_one_target_many_current():
    t = [I("blob", 0, 0x30)]
    c = [I("blob", 0, 0xC), I("p1", 0xC, 0xC), I("p2", 0x18, 0xC), I("p3", 0x24, 0xC)]
    assert "split" in kinds(compare_section(".data", t, c))


def test_size_mismatch_same_name_same_offset():
    f = compare_section(".data", [I("s", 0, 0xA)], [I("s", 0, 0xC)])
    assert any(x.kind == "size-mismatch" and x.target[0] == "s" for x in f)


def test_merge_one_current_spans_two_targets():
    t = [I("a", 0, 0xC), I("b", 0xC, 0xC)]
    f = compare_section(".data", t, [I("a", 0, 0x18)])
    assert kinds(f) == {"merge"}  # b is skipped as covered, no extra noise


def test_reorder_name_at_wrong_offset():
    t = [I("a", 0, 0x8), I("b", 0x8, 0x8)]
    c = [I("b", 0, 0x8), I("a", 0x8, 0x8)]
    assert "reorder" in kinds(compare_section(".sdata", t, c))


def test_binding_mismatch_is_opt_in():
    t = [I("a", 0, 0x8, binding="STB_GLOBAL")]
    c = [I("a", 0, 0x8, binding="STB_LOCAL")]
    assert compare_section(".data", t, c) == []  # default: off
    assert "binding-mismatch" in kinds(compare_section(".data", t, c, check_binding=True))


def test_missing_target_uncovered():
    t = [I("a", 0, 0x8), I("gen", 0x8, 0x8)]
    assert "missing" in kinds(compare_section(".sdata2", t, [I("a", 0, 0x8)]))


def test_anonymous_current_covers_target():
    c = [I("@123", 0, 0x4, anonymous=True)]
    assert "anonymous" in kinds(compare_section(".sdata2", [I("lit", 0, 0x4)], c))


def test_section_mismatch_name_in_other_section():
    t = {".bss": [I("g", 0x10, 0x10)]}
    c = {".sbss": [I("g", 0, 0x4)]}
    assert any(x.kind == "section-mismatch" for x in compare_layout(t, c))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_compare.py -v`
Expected: FAIL — `ModuleNotFoundError: src.layout.compare`.

- [ ] **Step 3: Write the implementation**

```python
# src/layout/__init__.py  (create empty)
```

```python
# src/layout/compare.py
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
            if f.kind == "missing" and f.target:
                name = f.target[0]
                if name in cur_global and cur_global[name][0] != sec:
                    osec, oiv = cur_global[name]
                    f = Finding("section-mismatch", sec, f.target, [_trip(oiv)],
                        f"{name}: target section {sec} vs current {osec}")
            out.append(f)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_compare.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/layout/__init__.py tools/melee-agent/src/layout/compare.py tools/melee-agent/tests/test_layout_compare.py
git commit -m "feat(layout): pure interval comparator (merge/split/size/reorder/section/missing/anon)"
```

---

## Task 3: Object paths + intervals (`layout/objects.py`)

**Files:**
- Create: `tools/melee-agent/src/layout/objects.py`
- Test: `tools/melee-agent/tests/test_layout_objects.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layout_objects.py
from pathlib import Path
from src.layout.objects import unit_paths, UnitPaths, _is_anonymous, _is_gap


def test_unit_paths_from_relative_c_file():
    up = unit_paths(Path("/repo"), Path("/repo/src/melee/mn/mnevent.c"))
    assert isinstance(up, UnitPaths)
    assert up.obj_path == "melee/mn/mnevent"
    assert up.ref_obj == Path("/repo/build/GALE01/obj/melee/mn/mnevent.o")
    assert up.our_obj == Path("/repo/build/GALE01/src/melee/mn/mnevent.o")


def test_anonymous_and_gap_detection():
    assert _is_gap("gap_07_803EF792_data")
    assert _is_anonymous("@123")
    assert _is_anonymous("...data.0")
    assert not _is_anonymous("mnEvent_803EF758")
    assert not _is_gap("mnEvent_803EF758")
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

from ..common.elf_symbols import read_object_symbols
from .compare import DATA_ELF_SECTIONS, Interval

_ANON_PREFIXES = ("@", "...", "lbl_", "$")


@dataclass(frozen=True)
class UnitPaths:
    obj_path: str
    ref_obj: Path
    our_obj: Path


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


def _is_gap(name: str) -> bool:
    return bool(name) and name.startswith("gap_")


def _is_anonymous(name: str) -> bool:
    return (not name) or name.startswith(_ANON_PREFIXES) or ".data." in name


def section_intervals(obj: Path) -> dict[str, list[Interval]]:
    """Group a .o's data-section object symbols into Intervals by ELF section.

    Skips `gap_*` padding markers; marks @N/...data./lbl_/$ as anonymous.
    """
    out: dict[str, list[Interval]] = {}
    for s in read_object_symbols(obj):
        if s.section not in DATA_ELF_SECTIONS:
            continue
        if s.type not in ("STT_OBJECT", "STT_NOTYPE"):
            continue
        if _is_gap(s.name):
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
git commit -m "feat(layout): object path resolution + section intervals (gap_/anon filtering)"
```

---

## Task 4: Source declaration mapper (`layout/source_map.py`)

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
    assert "fn_8024D15C" not in decls  # used, not file-scope declared
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_source_map.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/layout/source_map.py
"""Best-effort map from data-symbol name -> file-scope declaration line."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/layout/source_map.py tools/melee-agent/tests/test_layout_source_map.py
git commit -m "feat(layout): best-effort source declaration mapper"
```

---

## Task 5: Orchestrator + suggester (`layout/audit.py`)

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

REPO = Path(__file__).resolve().parents[3]  # tools/melee-agent/tests -> repo root


def test_suggest_covers_every_kind():
    for kind in ["split", "merge", "size-mismatch", "reorder",
                 "section-mismatch", "binding-mismatch", "missing", "anonymous"]:
        assert suggest(Finding(kind, ".data", ("s", 0, 8), [("s", 0, 8)], "m"))


@pytest.mark.skipif(
    not (REPO / "build/GALE01/obj/melee/mn/mnevent.o").exists()
    or not (REPO / "build/GALE01/src/melee/mn/mnevent.o").exists(),
    reason="mnevent objects not built",
)
def test_mnevent_acceptance_flags_known_issues():
    res = audit_tu(REPO, REPO / "src/melee/mn/mnevent.c")
    assert isinstance(res, AuditResult)
    by_name = {(f.target[0] if f.target else None): f.kind for f in res.findings}
    assert by_name.get("mnEvent_803EF758") == "split"
    assert by_name.get("mnEvent_803EF788") == "size-mismatch"
    assert by_name.get("mnEvent_804A0908") == "section-mismatch"
    # binding noise must NOT appear by default
    assert all(f.kind != "binding-mismatch" for f in res.findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_audit.py -v`
Expected: FAIL — `ModuleNotFoundError` (acceptance may skip).

- [ ] **Step 3: Write minimal implementation**

```python
# src/layout/audit.py
"""Orchestrate a TU data-layout audit and attach suggestions/locations."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .compare import Finding, compare_layout
from .objects import section_intervals, unit_paths
from .source_map import map_decls

_SUGGEST = {
    "split": "Model one object of the target size; reference sub-fields by offset.",
    "merge": "Split the source blob into the target's distinct objects.",
    "size-mismatch": "Resize the array/type to the target size.",
    "reorder": "Reorder the declarations to match target address order.",
    "section-mismatch": "Move the object to the target section (regular vs small-data: adjust type/const/size).",
    "binding-mismatch": "Fix static/global to match the target binding.",
    "missing": "Model this generated/literal object (unmodeled in source).",
    "anonymous": "Give this data a named declaration matching the production symbol.",
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


def audit_tu(repo: Path, c_file: Path, *, check_binding: bool = False) -> AuditResult:
    repo = Path(repo)
    up = unit_paths(repo, c_file)

    if not up.ref_obj.exists():
        return AuditResult(up.obj_path, degraded=True,
            warnings=[f"reference object missing: {up.ref_obj} (degraded mode not in v1)"])
    if not up.our_obj.exists():
        return AuditResult(up.obj_path, degraded=True,
            warnings=[f"current object missing: {up.our_obj}; build it first"])

    warnings: list[str] = []
    try:
        if up.our_obj.stat().st_mtime < Path(c_file).stat().st_mtime:
            warnings.append("current object older than source; rebuild for accuracy")
    except OSError:
        warnings.append("freshness unknown")

    target = section_intervals(up.ref_obj)
    current = section_intervals(up.our_obj)
    decls = map_decls(c_file)
    findings = compare_layout(target, current, check_binding=check_binding)

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
Expected: PASS (acceptance passes if mnevent objects exist; else skips). If the acceptance test FAILS (not skips), dump `nm -S` on both objects and reconcile the comparator/interval logic before continuing — do NOT weaken the assertions to pass.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/layout/audit.py tools/melee-agent/tests/test_layout_audit.py
git commit -m "feat(layout): audit orchestrator + suggestions + mnevent acceptance"
```

---

## Task 6: Reporter (`layout/report.py`)

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
    assert ":89" in out


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

## Task 7: CLI wiring (`cli/layout.py` + register)

**Files:**
- Create: `tools/melee-agent/src/cli/layout.py`
- Modify: `tools/melee-agent/src/cli/__init__.py` (import near line 35; `add_typer` near line 88)
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
    assert "not found" in res.output.lower()
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

from ..mwcc_debug.dtk_objdump import find_melee_root  # dtk_objdump.py:69
from ..layout.audit import audit_tu
from ..layout.report import render_json, render_text

layout_app = typer.Typer(help="Audit TU data layout (sections/symbols) vs target")


@layout_app.command("audit")
def audit_cmd(
    file: Path = typer.Argument(..., help="Path to the TU .c file (relative to CWD)"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    root: Path = typer.Option(None, "--root", help="Repo root (default: auto-detect)"),
    check_binding: bool = typer.Option(False, "--check-binding",
                                       help="Also report STB binding mismatches"),
) -> None:
    """Report data-layout discrepancies for a TU's .c file."""
    c = Path(file)
    if not c.is_absolute():
        c = (Path.cwd() / c).resolve()  # relative paths are CWD-relative
    if not c.exists():
        typer.echo(f"error: file not found: {c}", err=True)
        raise typer.Exit(2)
    repo = Path(root).resolve() if root else find_melee_root()
    res = audit_tu(repo, c, check_binding=check_binding)
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

- [ ] **Step 4: Run tests + smoke-test registration**

Run: `cd tools/melee-agent && python -m pytest tests/test_layout_cli.py -v`
Run: `cd tools/melee-agent && python -m src.cli layout audit --help`
Expected: tests PASS; help shows the `audit` command; registered under `melee-agent layout`.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/layout.py tools/melee-agent/src/cli/__init__.py tools/melee-agent/tests/test_layout_cli.py
git commit -m "feat(layout): melee-agent layout audit CLI command"
```

---

## Task 8: End-to-end acceptance + generalization validation

**Files:** none new. Uses real build objects.

- [ ] **Step 1: Ensure mnevent objects exist, run full suite**

Run: `cd /Users/mike/code/melee/.claude/worktrees/goofy-burnell-a2a060 && ninja build/GALE01/src/melee/mn/mnevent.o build/GALE01/obj/melee/mn/mnevent.o` (build if missing; ignore if already built).
Run: `cd tools/melee-agent && python -m pytest tests/test_elf_symbols.py tests/test_layout_compare.py tests/test_layout_objects.py tests/test_layout_source_map.py tests/test_layout_audit.py tests/test_layout_report.py tests/test_layout_cli.py -v`
Expected: all PASS — including `test_mnevent_acceptance_flags_known_issues` (not skipped).

- [ ] **Step 2: Run the auditor on mnevent and eyeball output**

Run: `cd tools/melee-agent && python -m src.cli layout audit ../../src/melee/mn/mnevent.c`
Expected: reports `[split] mnEvent_803EF758`, `[size-mismatch] mnEvent_803EF788`, `[section-mismatch] mnEvent_804A0908`, plus `.sdata` discrepancies (reorder, and a merge around `mnEvent_804D5040`); each with a suggestion; no `gap_*` noise; no binding noise.

- [ ] **Step 3: Generalization — run on a second TU**

Run: `cd tools/melee-agent && python -m src.cli layout audit ../../src/melee/ft/chara/ftCommon/ftCo_<ThrownKirby unit>.c` (resolve the real filename) and a `groldyoshi` TU.
Expected: surfaces `.sdata2` float-pool discrepancies (anonymous/missing/reorder); no crashes; findings plausible. Record output for the PR.

- [ ] **Step 4: Hand-validate ONE suggestion via checkdiff**

Apply the lowest-risk mnevent suggestion (resize `mnEvent_803EF788` to `[0xA]`) to `src/melee/mn/mnevent.c`, rebuild, and confirm the object now matches the target size:
Run: `cd /Users/mike/code/melee/.claude/worktrees/goofy-burnell-a2a060 && python tools/checkdiff.py <a function referencing _788> --no-tty`
Expected: that object's data-symbol size is now correct (audit no longer reports `size-mismatch` for `_788`). Revert the edit afterward (the auditor is read-only). Document before/after for the PR.

- [ ] **Step 5: Commit any test refinements**

```bash
git add -A tools/melee-agent/tests/
git commit -m "test(layout): end-to-end acceptance + generalization coverage"
```

---

## Self-Review notes (against the spec)

- **Spec coverage:** object-vs-object via pyelftools (Tasks 1/3/5), no dtk/nm (Task 1), target = ref object incl. its symbols (Task 3), interval comparison (Task 2), missing≠anonymous + split/merge/reorder + section-mismatch (Task 2), binding opt-in (Task 2/5/7), staleness (Task 5), shared reader in `common/` not touching checkdiff (Task 1), new module + CLI (Task 7), acceptance + generalization + hand-validation (Task 8).
- **Deferred to phase-2 (documented, not gaps):** (1) symbols.txt absolute-address anchoring + size cross-check — unnecessary for v1 because ref-object names encode addresses; (2) `gap-change` findings — in practice subsumed by `size-mismatch` on the preceding object, and `gap_*` markers are filtered so they cause no noise; (3) degraded (no-object) mode — v1 reports a clear warning and exits without findings rather than guessing from declarations.
- **Type consistency:** `Interval(name,offset,size,binding,anonymous)`, `Finding(kind,section,target,current,message,confidence)`, `AuditResult(obj_path,degraded,warnings,findings,enriched)`, `EnrichedFinding(finding,source_line,suggestion)`, `UnitPaths(obj_path,ref_obj,our_obj)`, `Decl(name,line,is_static)`, `ObjSymbol(name,section,shndx,value,size,bind,type)` — used consistently across tasks/tests.
- **Acceptance assertions verified against real `nm -S`** (per Codex plan review): `_758`→split, `_788`→size-mismatch, `_804A0908`→section-mismatch (`.bss` target vs `.sbss` current).
