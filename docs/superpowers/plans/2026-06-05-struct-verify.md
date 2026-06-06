# struct verify — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect wrong struct-field offsets that cause decomp mismatches — report `field: current→expected` across a TU — so a struct fix can cascade to many functions.

**Architecture:** Three units. (1) A reusable MWCC `offsetof`-probe **layout resolver** (compile a probe TU, read offsets back by parsing the `.o`'s `.data` — proven). (2) A **checkdiff extension** that emits `offset_discrepancies` from its aligned diff. (3) A `struct verify` **command** that maps current displacements to fields via the resolver and aggregates across a TU.

**Tech Stack:** Python 3.11+, typer, pytest; MWCC (`mwcceppc.exe` via `build/tools/wibo`); `tools/checkdiff.py` (dtk-based diff).

**Spec:** `docs/superpowers/specs/2026-06-05-struct-verify-design.md` (Codex-reviewed ×2, prototype-validated; +2 THP matches committed at `bb81aecd2`).

**Test command (all tasks):** `cd tools/melee-agent && python -m pytest tests/<file> -v`

---

## File Structure

- Create `tools/melee-agent/src/common/struct_layout.py` — resolver (cflags parse, field-path enumeration, probe compile, ELF read, verify form). One responsibility: struct layout from the compiler.
- Create `tools/melee-agent/src/common/struct_verify.py` — aggregation/confidence logic (pure, no I/O).
- Modify `tools/checkdiff.py` — add `_paired_struct_offset_delta` + `offset_discrepancies` in `classify_asm_diff`.
- Modify `tools/melee-agent/src/extractor/report.py` — add `functions_for_unit()`.
- Modify `tools/melee-agent/src/cli/struct.py` — add `verify` command.
- Tests: `tests/test_struct_layout.py`, `tests/test_checkdiff_offset_discrepancies.py`, `tests/test_struct_verify.py`.

---

## Phase 1 — Layout resolver (`struct_layout.py`)

### Task 1.1: Parse a TU's MWCC cflags from build.ninja

**Files:**
- Create: `tools/melee-agent/src/common/struct_layout.py`
- Test: `tools/melee-agent/tests/test_struct_layout.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_struct_layout.py
from pathlib import Path
from src.common import struct_layout

REPO = Path(__file__).resolve().parents[3]

def test_parse_tu_cflags_thpdec():
    spec = struct_layout.parse_tu_cflags(REPO, "extern/dolphin/src/dolphin/thp/THPDec.c")
    assert spec.mw_version == "GC/1.2.5"
    # layout-determining flags must be present
    assert "-align" in spec.cflags and "powerpc" in spec.cflags
    assert "-enum" in spec.cflags and "int" in spec.cflags
    assert "-proc" in spec.cflags and "gekko" in spec.cflags
    assert "-i" in spec.cflags  # include paths preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_struct_layout.py::test_parse_tu_cflags_thpdec -v`
Expected: FAIL (ModuleNotFoundError / AttributeError).

- [ ] **Step 3: Write minimal implementation**

```python
# src/common/struct_layout.py
from __future__ import annotations
import re, struct, subprocess, tempfile
from dataclasses import dataclass
from pathlib import Path

@dataclass
class CflagsSpec:
    mw_version: str
    cflags: list[str]

def _read_ninja(repo: Path) -> str:
    return (repo / "build.ninja").read_text()

def _join_continuations(block: str) -> str:
    # ninja line continuation is "$\n" + leading whitespace
    return re.sub(r"\$\n\s*", " ", block)

def parse_tu_cflags(repo: Path, tu_src: str) -> CflagsSpec:
    """Extract mw_version + cflags for the build edge that compiles `tu_src`."""
    text = _read_ninja(repo)
    # find the build edge whose inputs include tu_src
    # edges look like: "build <out>: mwcc_sjis $\n    <src> ...\n  mw_version = ...\n  cflags = ... $\n      ...\n  basedir = ..."
    edges = re.split(r"\nbuild ", text)
    for edge in edges:
        if tu_src not in edge:
            continue
        joined = _join_continuations(edge)
        mw = re.search(r"mw_version = (\S+)", joined)
        cf = re.search(r"cflags = (.*?)(?:\n  \w+ =|\Z)", joined, re.S)
        if mw and cf:
            return CflagsSpec(mw.group(1).strip(), cf.group(1).split())
    raise ValueError(f"no build edge found for {tu_src}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_struct_layout.py::test_parse_tu_cflags_thpdec -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/common/struct_layout.py tools/melee-agent/tests/test_struct_layout.py
git commit -m "feat(struct-layout): parse per-TU MWCC cflags from build.ninja"
```

### Task 1.2: Enumerate field paths (names + nested struct/array)

**Files:**
- Modify: `tools/melee-agent/src/common/struct_layout.py`
- Test: `tools/melee-agent/tests/test_struct_layout.py`

Reuse the existing field-name parser in `tools/melee-agent/src/cli/struct.py` (`_parse_struct_fields(content, struct_name)` at `:35`, `_find_struct_in_files(melee_root, struct_name)` at `:95`). NOTE: `_find_struct_in_files` does NOT search `extern/dolphin/include` and matches `struct {name} {` not typedef tags — for v1 the resolver does not need name-resolution to compute offsets (the compiler does), it only needs the **top-level field name list** to build `offsetof(T, field)` probes, and for nested structs the **path** `field` / `field[i].sub`. We enumerate one level of array elements (index 0 and 1) for array fields and recurse one level into struct-typed fields whose type is also defined locally.

- [ ] **Step 1: Write the failing test**

```python
def test_enumerate_field_paths_thpfileinfo():
    paths = struct_layout.enumerate_field_paths(REPO, "THPFileInfo")
    # top-level scalar/pointer/array fields present as offsetof-able paths
    assert "RST" in paths
    assert "nMCU" in paths
    assert "validHuffmanTabs" in paths
    # nested struct array element + sub-field
    assert "components[0].predDC" in paths
    assert "components[1].predDC" in paths
    assert "components[0].DCTableSelector" in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_struct_layout.py::test_enumerate_field_paths_thpfileinfo -v`
Expected: FAIL (AttributeError: enumerate_field_paths).

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/common/struct_layout.py
import sys
_CLI = Path(__file__).resolve().parents[1] / "cli"
if str(_CLI.parent) not in sys.path:
    sys.path.insert(0, str(_CLI.parent))
from cli.struct import _parse_struct_fields  # field-name parser (name,type,is_array,array_size)

_HEADER_DIRS = [
    "include", "src", "extern/dolphin/include", "extern/dolphin/src",
]

def _find_struct_body(repo: Path, name: str) -> str | None:
    # typedef-tag aware: matches `struct _Name {` ... `} Name;` and `struct Name {`
    pats = [re.compile(rf"struct\s+_?{re.escape(name)}\s*\{{(.*?)\}}", re.S),
            re.compile(rf"struct\s*\{{(.*?)\}}\s*{re.escape(name)}\s*;", re.S)]
    for d in _HEADER_DIRS:
        for hp in (repo / d).rglob("*.h"):
            txt = hp.read_text(errors="ignore")
            if name not in txt:
                continue
            for pat in pats:
                m = pat.search(txt)
                if m:
                    return m.group(1)
    return None

def enumerate_field_paths(repo: Path, struct_name: str, _depth: int = 0) -> list[str]:
    body = _find_struct_body(repo, struct_name)
    if body is None:
        raise ValueError(f"struct {struct_name} not found")
    fields = _parse_struct_fields(body, struct_name)  # returns dicts with name,type,array info
    out: list[str] = []
    for f in fields:
        nm = f["name"]
        if not nm or nm.startswith("pad") or nm.startswith("unk"):
            continue
        elem_type = f.get("type", "")
        arr = f.get("array_size")
        nested = enumerate_field_paths(repo, elem_type, _depth + 1) if (_depth < 1 and _find_struct_body(repo, elem_type)) else []
        indices = [0, 1] if arr and int(arr) > 1 else ([0] if arr else [None])
        for idx in indices:
            base = nm if idx is None else f"{nm}[{idx}]"
            if nested:
                out.extend(f"{base}.{sub}" for sub in nested)
            else:
                out.append(base)
    return out
```

NOTE: if `_parse_struct_fields` does not return `type`/`array_size` keys, extend it (in `cli/struct.py`) to do so and add a unit test there; keep its existing return shape backward-compatible by adding keys, not renaming.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_struct_layout.py::test_enumerate_field_paths_thpfileinfo -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(struct-layout): enumerate nested/array field paths"
```

### Task 1.3: Resolve layout via offsetof-probe (discovery form)

**Files:**
- Modify: `tools/melee-agent/src/common/struct_layout.py`
- Test: `tools/melee-agent/tests/test_struct_layout.py`

PROVEN read-out: compile `unsigned long __off[] = { offsetof(T,p0), ... };` and read the `.data` symbol bytes as big-endian u32. ELF parse is verbatim from the validated spike.

- [ ] **Step 1: Write the failing test**

```python
import pytest

@pytest.mark.slow
def test_resolve_layout_thpfileinfo():
    layout = struct_layout.resolve_layout(REPO, "THPFileInfo",
                                          "extern/dolphin/src/dolphin/thp/THPDec.c")
    # field-path -> offset
    assert layout["RST"] == 0x900
    assert layout["nMCU"] == 0x8fc
    assert layout["components[1].predDC"] == 0x86a
    assert layout["components[0].DCTableSelector"] == 0x83c
    # reverse map available
    assert struct_layout.offset_to_field(layout, 0x900) == "RST"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_struct_layout.py::test_resolve_layout_thpfileinfo -v`
Expected: FAIL (AttributeError: resolve_layout).

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/common/struct_layout.py
_DROP_FLAGS = {"-MMD"}  # remove build-only flags; keep layout flags

def _probe_cflags(spec: CflagsSpec) -> list[str]:
    out, skip = [], False
    for tok in spec.cflags:
        if skip:  # value of a dropped flag
            skip = False; continue
        if tok in _DROP_FLAGS:
            continue
        out.append(tok)
    return out

def _compile_probe(repo: Path, spec: CflagsSpec, src: str) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "probe.c"
        opath = Path(td) / "probe.o"
        cpath.write_text(src)
        cc = repo / "build/compilers" / spec.mw_version / "mwcceppc.exe"
        wibo = repo / "build/tools/wibo"
        cmd = [str(wibo), str(cc), *_probe_cflags(spec), "-c", str(cpath), "-o", str(opath)]
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        if not opath.exists():
            raise RuntimeError(f"probe compile failed:\n{r.stdout}\n{r.stderr}")
        return opath.read_bytes()

def _read_symbol_u32s(obj: bytes, symbol: str) -> list[int]:
    assert obj[:4] == b"\x7fELF"
    end = ">" if obj[5] == 2 else "<"
    e_shoff, = struct.unpack(end + "I", obj[0x20:0x24])
    e_shentsize, = struct.unpack(end + "H", obj[0x2e:0x30])
    e_shnum, = struct.unpack(end + "H", obj[0x30:0x32])
    e_shstrndx, = struct.unpack(end + "H", obj[0x32:0x34])
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        nm, typ, fl, ad, off, sz, lk, inf, al, es = struct.unpack(end + "10I", obj[o:o + 40])
        secs.append(dict(name=nm, offset=off, size=sz, link=lk, entsize=es))
    sh = secs[e_shstrndx]; shstr = obj[sh["offset"]:sh["offset"] + sh["size"]]
    for s in secs:
        s["sn"] = shstr[s["name"]:shstr.index(b"\0", s["name"])].decode()
    sym = next(s for s in secs if s["sn"] == ".symtab")
    st = secs[sym["link"]]; strd = obj[st["offset"]:st["offset"] + st["size"]]
    for i in range(sym["size"] // sym["entsize"]):
        o = sym["offset"] + i * sym["entsize"]
        n, val, sz, info, other, shndx = struct.unpack(end + "IIIBBH", obj[o:o + 16])
        name = strd[n:strd.index(b"\0", n)].decode()
        if name == symbol or name == "_" + symbol:
            sec = secs[shndx]; raw = obj[sec["offset"] + val:sec["offset"] + val + sz]
            return [struct.unpack(end + "I", raw[j:j + 4])[0] for j in range(0, len(raw), 4)]
    raise KeyError(symbol)

def resolve_layout(repo: Path, struct_name: str, tu_src: str) -> dict[str, int]:
    spec = parse_tu_cflags(repo, tu_src)
    paths = enumerate_field_paths(repo, struct_name)
    incl = _tu_include_of(repo, struct_name)  # header that declares the struct, e.g. <dolphin/thp/thp.h>
    body = "#include " + incl + "\n"
    body += "#define OFF(f) ((unsigned long)&(((" + struct_name + "*)0)->f))\n"
    body += "unsigned long __off[] = {\n" + ",\n".join(f"  OFF({p})" for p in paths) + "\n};\n"
    obj = _compile_probe(repo, spec, body)
    offs = _read_symbol_u32s(obj, "__off")
    return {p: o for p, o in zip(paths, offs)}

def offset_to_field(layout: dict[str, int], offset: int) -> str | None:
    for p, o in layout.items():
        if o == offset:
            return p
    return None

def _tu_include_of(repo: Path, struct_name: str) -> str:
    # crude: find the header path under _HEADER_DIRS whose struct body exists, return <angle> form
    pats = [re.compile(rf"struct\s+_?{re.escape(struct_name)}\s*\{{"),
            re.compile(rf"\}}\s*{re.escape(struct_name)}\s*;")]
    for d in _HEADER_DIRS:
        root = repo / d
        for hp in root.rglob("*.h"):
            txt = hp.read_text(errors="ignore")
            if any(p.search(txt) for p in pats):
                rel = hp.relative_to(root)
                return f"<{rel.as_posix()}>"
    raise ValueError(f"no header for {struct_name}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_struct_layout.py::test_resolve_layout_thpfileinfo -v`
Expected: PASS (requires `build/tools/wibo` + compilers present; mark `@pytest.mark.slow`).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(struct-layout): offsetof-probe resolver (discovery read-out)"
```

### Task 1.4: Verify form (cheap pre-rebuild check)

**Files:**
- Modify: `tools/melee-agent/src/common/struct_layout.py`
- Test: `tools/melee-agent/tests/test_struct_layout.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.slow
def test_verify_offsets():
    ok = struct_layout.verify_offsets(REPO, "THPFileInfo",
        "extern/dolphin/src/dolphin/thp/THPDec.c",
        {"RST": 0x900, "components[0].predDC": 0x83e})
    assert ok is True
    bad = struct_layout.verify_offsets(REPO, "THPFileInfo",
        "extern/dolphin/src/dolphin/thp/THPDec.c", {"RST": 0x999})
    assert bad is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_struct_layout.py::test_verify_offsets -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
def verify_offsets(repo: Path, struct_name: str, tu_src: str, expect: dict[str, int]) -> bool:
    spec = parse_tu_cflags(repo, tu_src)
    incl = _tu_include_of(repo, struct_name)
    body = "#include " + incl + "\n"
    body += "#define OFF(f) ((unsigned long)&(((" + struct_name + "*)0)->f))\n"
    for i, (p, off) in enumerate(expect.items()):
        body += f"typedef char _chk{i}[OFF({p}) == {off} ? 1 : -1];\n"
    try:
        _compile_probe(repo, spec, body)
        return True
    except RuntimeError:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_struct_layout.py::test_verify_offsets -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(struct-layout): offsetof verify form"
```

---

## Phase 2 — checkdiff `offset_discrepancies` (`tools/checkdiff.py`)

### Task 2.1: `_paired_struct_offset_delta` helper

**Files:**
- Modify: `tools/checkdiff.py` (near `_paired_stack_delta`, `:1439`)
- Test: `tools/melee-agent/tests/test_checkdiff_offset_discrepancies.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_checkdiff_offset_discrepancies.py
import importlib.util
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("checkdiff", REPO / "tools/checkdiff.py")
checkdiff = importlib.util.module_from_spec(spec); spec.loader.exec_module(checkdiff)

def test_paired_struct_offset_delta_basic():
    # same mnemonic, same base, different displacement -> discrepancy
    d = checkdiff._paired_struct_offset_delta("stb     r0,2304(r3)", "stb     r0,1856(r3)")
    assert d == {"base_reg": "r3", "mnemonic": "stb", "ref_disp": 2304, "cur_disp": 1856}

def test_paired_struct_offset_delta_excludes_stack_and_sda():
    assert checkdiff._paired_struct_offset_delta("stw r0,8(r1)", "stw r0,16(r1)") is None
    assert checkdiff._paired_struct_offset_delta("lwz r3,0(r2)", "lwz r3,8(r2)") is None

def test_paired_struct_offset_delta_same_disp_none():
    assert checkdiff._paired_struct_offset_delta("stb r0,8(r3)", "stb r0,8(r3)") is None

def test_paired_struct_offset_delta_diff_mnemonic_none():
    assert checkdiff._paired_struct_offset_delta("stb r0,8(r3)", "sth r0,16(r3)") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_checkdiff_offset_discrepancies.py -v`
Expected: FAIL (AttributeError).

- [ ] **Step 3: Write minimal implementation**

```python
# tools/checkdiff.py — add near _paired_stack_delta
_MEMOP_RE = re.compile(r"^([a-z][a-z0-9.]*)\s+.*?(-?(?:0x[0-9a-fA-F]+|\d+))\((r\d+)\)")

def _paired_struct_offset_delta(ref_body: str, our_body: str):
    """Return a struct-offset discrepancy dict, or None.
    Same mnemonic + same base register (not r1/r2/r13) + differing displacement."""
    rm = _MEMOP_RE.match(ref_body.strip())
    cm = _MEMOP_RE.match(our_body.strip())
    if not rm or not cm:
        return None
    if rm.group(1) != cm.group(1):       # mnemonic
        return None
    if rm.group(3) != cm.group(3):       # base reg
        return None
    base = rm.group(3)
    if base in ("r1", "r2", "r13"):      # stack / sda / sda2
        return None
    def _d(s): return int(s, 16) if s.lower().startswith(("0x", "-0x")) else int(s)
    rd, cd = _d(rm.group(2)), _d(cm.group(2))
    if rd == cd:
        return None
    return {"base_reg": base, "mnemonic": rm.group(1), "ref_disp": rd, "cur_disp": cd}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_checkdiff_offset_discrepancies.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/checkdiff.py tools/melee-agent/tests/test_checkdiff_offset_discrepancies.py
git commit -m "feat(checkdiff): _paired_struct_offset_delta helper"
```

### Task 2.2: Emit `offset_discrepancies` from `classify_asm_diff` (body-aligned, dup-body guard)

**Files:**
- Modify: `tools/checkdiff.py` (`classify_asm_diff`, `:1981`; uses `_asm_body` `:407`, `_is_relocation_line` `:418`)
- Test: `tools/melee-agent/tests/test_checkdiff_offset_discrepancies.py`

- [ ] **Step 1: Write the failing test**

```python
def _lines(seq):  # build normalized "+NNN: bytes \tasm" lines
    return [f"+{i*4:03x}: 00 00 00 00 \t{a}" for i, a in enumerate(seq)]

def test_offset_discrepancies_clean():
    ref = _lines(["li r0,1", "stb r0,2304(r3)", "blr"])
    cur = _lines(["li r0,1", "stb r0,1856(r3)", "blr"])
    c = checkdiff.classify_asm_diff(ref, cur)
    od = c.get("offset_discrepancies", [])
    assert any(d["ref_disp"] == 2304 and d["cur_disp"] == 1856 and d["base_reg"] == "r3" for d in od)

def test_offset_discrepancies_dupbody_guard():
    # identical repeated bodies with ambiguous displacements -> suppressed
    ref = _lines(["stw r0,0(r28)", "stw r0,4(r28)", "stw r0,0(r28)"])
    cur = _lines(["stw r0,0(r28)", "stw r0,8(r28)", "stw r0,0(r28)"])
    c = checkdiff.classify_asm_diff(ref, cur)
    # the middle differing store is bracketed by identical bodies on both sides;
    # require unambiguous context -> here context matches, so it MAY emit; the
    # guard suppresses only when the SAME body repeats with differing disp in one block.
    od = c.get("offset_discrepancies", [])
    assert all(d["base_reg"] != "r28" or (d["ref_disp"], d["cur_disp"]) == (4, 8) for d in od)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_checkdiff_offset_discrepancies.py -k offset_discrepancies -v`
Expected: FAIL (KeyError/empty).

- [ ] **Step 3: Write minimal implementation**

```python
# tools/checkdiff.py — inside classify_asm_diff, after the existing paired classification,
# before the final `return {...}`. Build aligned pairs via SequenceMatcher on BODIES.
    import difflib as _dl
    ref_bodies = [_asm_body(l) for l in ref_lines if not _is_relocation_line(l)]
    our_bodies = [_asm_body(l) for l in our_lines if not _is_relocation_line(l)]
    _sm = _dl.SequenceMatcher(None, [_struct_key(b) for b in ref_bodies],
                                    [_struct_key(b) for b in our_bodies], autojunk=False)
    offset_discrepancies = []
    for tag, i1, i2, j1, j2 in _sm.get_opcodes():
        if tag not in ("equal", "replace"):
            continue
        if (i2 - i1) != (j2 - j1):
            continue  # unequal replace block: can't pair positionally
        # dup-body guard: if a key repeats within this block, skip the block
        block_keys = [_struct_key(ref_bodies[i1 + k]) for k in range(i2 - i1)]
        if len(set(block_keys)) != len(block_keys):
            continue
        for k in range(i2 - i1):
            d = _paired_struct_offset_delta(ref_bodies[i1 + k], our_bodies[j1 + k])
            if d:
                offset_discrepancies.append(d)
    # ... in the returned dict add: "offset_discrepancies": offset_discrepancies
```

Add the key to EVERY dict returned by the non-identical path (or merge once before the final return). Add the `_struct_key` helper (mask displacement + branch targets so equal-shape instructions align):

```python
def _struct_key(body: str) -> str:
    k = re.sub(r"-?(?:0x[0-9a-fA-F]+|\d+)\((r\d+)\)", r"DISP(\1)", body)
    k = re.sub(r"<[^>]*>", "TGT", k)
    return re.sub(r"\s+", " ", k).strip()
```

Do NOT modify `primary` or any existing key.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_checkdiff_offset_discrepancies.py -v`
Expected: PASS. Then regression-check existing classification tests:
Run: `cd tools/melee-agent && python -m pytest tests/test_checkdiff_stack_diagnostics.py -v`
Expected: PASS (unchanged).

- [ ] **Step 5: Commit**

```bash
git add tools/checkdiff.py tools/melee-agent/tests/test_checkdiff_offset_discrepancies.py
git commit -m "feat(checkdiff): emit offset_discrepancies (body-aligned, dup-body guard)"
```

### Task 2.3: Surface in JSON + live-function golden

**Files:**
- Test: `tools/melee-agent/tests/test_checkdiff_offset_discrepancies.py`

- [ ] **Step 1: Write the failing test (live, slow)**

```python
import json, subprocess, pytest
@pytest.mark.slow
def test_thprestart_offset_discrepancies_live():
    # Requires the PRE-fix struct (or a checkout where __THPRestartDefinition mismatches).
    # Run against current build; if RST already matched (post bb81aecd2), assert empty.
    out = subprocess.run(["python", "tools/checkdiff.py", "__THPRestartDefinition",
                          "--no-tty", "--format", "json", "--no-build"],
                         cwd=REPO, capture_output=True, text=True).stdout
    od = json.loads(out)["classification"].get("offset_discrepancies", [])
    # post-fix: matched -> no discrepancies; this asserts the key EXISTS and is a list
    assert isinstance(od, list)
```

- [ ] **Step 2-4:** Run; expected PASS (key present). (The discriminating golden is exercised in Phase 4 against the pre-fix layout.)

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "test(checkdiff): offset_discrepancies present in JSON"
```

---

## Phase 3 — `struct verify` command

### Task 3.1: `functions_for_unit()` helper

**Files:**
- Modify: `tools/melee-agent/src/extractor/report.py` (near `ReportParser`, `:14`)
- Test: `tools/melee-agent/tests/test_struct_verify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_struct_verify.py
from pathlib import Path
from src.extractor import report as report_mod
REPO = Path(__file__).resolve().parents[3]

def test_functions_for_unit_thpdec():
    fns = report_mod.functions_for_unit(REPO / "build/GALE01/report.json", "thp/THPDec")
    assert "__THPRestartDefinition" in fns
    assert "THPVideoDecode" in fns
    assert all(isinstance(f, str) for f in fns)
```

- [ ] **Step 2: Run/fail.** `cd tools/melee-agent && python -m pytest tests/test_struct_verify.py::test_functions_for_unit_thpdec -v` → FAIL.

- [ ] **Step 3: Implement**

```python
# src/extractor/report.py
import json
def functions_for_unit(report_path, unit_substr: str) -> list[str]:
    """Function names belonging to the unit whose name ends with unit_substr."""
    data = json.loads(Path(report_path).read_text())
    for unit in data.get("units", []):
        if unit.get("name", "").endswith(unit_substr):
            return [f["name"] for f in unit.get("functions", [])]
    raise ValueError(f"unit {unit_substr} not found")
```

- [ ] **Step 4: Run/pass.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(report): functions_for_unit helper"`

### Task 3.2: Aggregation + confidence (`struct_verify.py`, pure)

**Files:**
- Create: `tools/melee-agent/src/common/struct_verify.py`
- Test: `tools/melee-agent/tests/test_struct_verify.py`

- [ ] **Step 1: Write the failing test**

```python
from src.common import struct_verify as sv

def test_aggregate_keeps_singletons_and_flags_ambiguous():
    # per-function discrepancies already mapped to fields
    findings = [
        {"function": "f1", "field": "RST", "current": 0x740, "expected": 0x900},
        {"function": "f2", "field": "nMCU", "current": 0x742, "expected": 0x8fc},
        {"function": "f3", "field": "nMCU", "current": 0x742, "expected": 0x8fc},
        # ambiguous: same field, conflicting expected
        {"function": "f4", "field": "RST", "current": 0x740, "expected": 0x123},
    ]
    agg = sv.aggregate(findings)
    rst = next(a for a in agg if a["field"] == "RST")
    nmcu = next(a for a in agg if a["field"] == "nMCU")
    assert rst["conflict"] is True              # RST has two expecteds
    assert nmcu["n_functions"] == 2 and nmcu["conflict"] is False
    assert nmcu["confidence"] == "high"         # >=2 agreeing
    # singleton kept at lower confidence
    single = [a for a in agg if a["field"] == "nMCU"][0]
    assert single["expected"] == 0x8fc
```

- [ ] **Step 2: Run/fail.**

- [ ] **Step 3: Implement**

```python
# src/common/struct_verify.py
from __future__ import annotations
from collections import defaultdict

def aggregate(findings: list[dict]) -> list[dict]:
    by_field: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_field[f["field"]].append(f)
    out = []
    for field, items in by_field.items():
        expecteds = {it["expected"] for it in items}
        current = items[0]["current"]
        conflict = len(expecteds) > 1
        n = len({it["function"] for it in items})
        confidence = "high" if (n >= 2 and not conflict) else "low"
        out.append({
            "field": field,
            "current": current,
            "expected": sorted(expecteds)[0] if not conflict else None,
            "expecteds": sorted(expecteds),
            "n_functions": n,
            "functions": sorted({it["function"] for it in items}),
            "conflict": conflict,
            "confidence": confidence,
        })
    return sorted(out, key=lambda a: a["current"])
```

- [ ] **Step 4: Run/pass.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(struct-verify): aggregation + confidence (keeps singletons, flags conflicts)"`

### Task 3.3: `struct verify` command (per-function base, warn-skip, map via resolver)

**Files:**
- Modify: `tools/melee-agent/src/cli/struct.py` (add `@struct_app.command("verify")`)
- Test: `tools/melee-agent/tests/test_struct_verify.py`

- [ ] **Step 1: Write the failing test (CLI smoke via typer CliRunner)**

```python
from typer.testing import CliRunner
from src.cli.struct import struct_app

def test_struct_verify_help():
    r = CliRunner().invoke(struct_app, ["verify", "--help"])
    assert r.exit_code == 0
    assert "--struct" in r.output and "--base" in r.output
```

- [ ] **Step 2: Run/fail.**

- [ ] **Step 3: Implement** (wires checkdiff JSON → map cur_disp via resolver → aggregate; per-function `--base`, `--base-map` JSON file `{fn: reg}`; warn-skip functions with no base or interior base):

```python
# src/cli/struct.py
import json as _json
from typing import Optional
from ..common import struct_layout, struct_verify
from ..extractor.report import functions_for_unit

@struct_app.command("verify")
def struct_verify_cmd(
    target: str = typer.Argument(..., help="function name or TU substring (e.g. thp/THPDec)"),
    struct: str = typer.Option(..., "--struct", help="struct type name"),
    base: Optional[str] = typer.Option(None, "--base", help="base register, e.g. r3 (single fn)"),
    base_map: Optional[str] = typer.Option(None, "--base-map", help="JSON {function: reg}"),
    tu_src: str = typer.Option(..., "--tu-src", help="path to the TU .c for cflags"),
    as_json: bool = typer.Option(False, "--json"),
):
    repo = get_agent_melee_root()
    layout = struct_layout.resolve_layout(repo, struct, tu_src)
    bmap = _json.loads(Path(base_map).read_text()) if base_map else {}
    # resolve function list
    if "/" in target:
        fns = functions_for_unit(repo / "build/GALE01/report.json", target)
    else:
        fns = [target]
    findings, skipped = [], []
    for fn in fns:
        reg = bmap.get(fn, base)
        if reg is None:
            skipped.append((fn, "no base")); continue
        out = subprocess.run(["python", "tools/checkdiff.py", fn, "--no-tty",
                              "--format", "json", "--no-build"], cwd=repo,
                             capture_output=True, text=True).stdout
        try:
            cls = _json.loads(out)["classification"]
        except Exception:
            skipped.append((fn, "checkdiff failed")); continue
        for d in cls.get("offset_discrepancies", []):
            if d["base_reg"] != reg:
                continue
            field = struct_layout.offset_to_field(layout, d["cur_disp"])
            if field is None:
                skipped.append((fn, f"unmapped cur 0x{d['cur_disp']:x}")); continue
            findings.append({"function": fn, "field": field,
                             "current": d["cur_disp"], "expected": d["ref_disp"]})
    agg = struct_verify.aggregate(findings)
    if as_json:
        console.print_json(data={"findings": agg, "skipped": skipped})
        return
    _render_verify_table(agg, skipped)  # Task 3.4
```

- [ ] **Step 4: Run/pass** the help test.

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(struct): verify command (per-function base, resolver mapping)"`

### Task 3.4: Human table renderer

**Files:**
- Modify: `tools/melee-agent/src/cli/struct.py`
- Test: `tools/melee-agent/tests/test_struct_verify.py`

- [ ] **Step 1: Write the failing test**

```python
def test_render_verify_table_smoke(capsys):
    from src.cli.struct import _render_verify_table
    _render_verify_table([{"field":"RST","current":0x740,"expected":0x900,
        "expecteds":[0x900],"n_functions":1,"functions":["f"],"conflict":False,"confidence":"low"}], [])
    out = capsys.readouterr().out
    assert "RST" in out and "0x900" in out
```

- [ ] **Step 2: Run/fail.**

- [ ] **Step 3: Implement**

```python
def _render_verify_table(agg, skipped):
    t = Table(title="struct offset discrepancies")
    for c in ("field", "current", "expected", "Δ", "n", "confidence"):
        t.add_column(c)
    for a in agg:
        exp = "CONFLICT " + ",".join(hex(e) for e in a["expecteds"]) if a["conflict"] else hex(a["expected"])
        delta = "" if a["conflict"] else f"{a['expected'] - a['current']:+d}"
        t.add_row(a["field"], hex(a["current"]), exp, delta, str(a["n_functions"]), a["confidence"])
    console.print(t)
    if skipped:
        console.print(f"[yellow]skipped {len(skipped)}:[/] " + ", ".join(f"{f}({why})" for f, why in skipped[:20]))
```

- [ ] **Step 4: Run/pass.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(struct): verify human table renderer"`

---

## Phase 4 — Dogfood on THPDec

### Task 4.1: End-to-end golden against the pre-fix layout

**Files:**
- Test: `tools/melee-agent/tests/test_struct_verify.py`

The +2 THP matches are committed (`bb81aecd2`), so the *current* tree no longer
mismatches. To exercise discovery end-to-end, run against the pre-fix struct via
a temporary revert in a throwaway check (the test stashes thp.h, reverts the two
struct edits, rebuilds THPDec.o, runs `struct verify`, asserts the known
findings, then restores). Keep this test `@pytest.mark.slow` and guarded.

- [ ] **Step 1: Write the test**

```python
@pytest.mark.slow
def test_struct_verify_thpdec_reports_known_discrepancies(tmp_path):
    import shutil, subprocess
    hdr = REPO / "extern/dolphin/include/dolphin/thp/thp.h"
    backup = tmp_path / "thp.h.bak"; shutil.copy(hdr, backup)
    try:
        txt = hdr.read_text()
        # revert tail to pre-fix (predDC@+0, tail before components)
        txt = txt.replace("u8 unk0[2];\n    u8 pad;", "THPCoeff predDC;\n    u8 pad;")  # predDC back to +0 (approx)
        hdr.write_text(txt)
        subprocess.run(["touch", "extern/dolphin/src/dolphin/thp/THPDec.c"], cwd=REPO)
        subprocess.run(["ninja", "build/GALE01/src/dolphin/thp/THPDec.o"], cwd=REPO, check=True)
        from typer.testing import CliRunner
        from src.cli.struct import struct_app
        r = CliRunner().invoke(struct_app, ["verify", "thp/THPDec", "--struct", "THPFileInfo",
            "--base", "r3", "--tu-src", "extern/dolphin/src/dolphin/thp/THPDec.c", "--json"])
        assert r.exit_code == 0
        data = __import__("json").loads(r.output)
        fields = {f["field"]: f for f in data["findings"]}
        assert "components[0].predDC" in fields  # +0 -> +6 detected
    finally:
        shutil.copy(backup, hdr)
        subprocess.run(["touch", "extern/dolphin/src/dolphin/thp/THPDec.c"], cwd=REPO)
        subprocess.run(["ninja", "build/GALE01/src/dolphin/thp/THPDec.o"], cwd=REPO, check=True)
```

- [ ] **Step 2: Run** `cd tools/melee-agent && python -m pytest tests/test_struct_verify.py::test_struct_verify_thpdec_reports_known_discrepancies -v` → PASS.

- [ ] **Step 3: Manual dogfood + record** (not a test): on a pre-fix tree, run
`melee-agent struct verify thp/THPDec --struct THPFileInfo --base r3 --tu-src extern/dolphin/src/dolphin/thp/THPDec.c`
and confirm the table lists `RST 0x740→0x900`, `nMCU`, `currMCU`, `components[*].predDC +0→+6`. Note the low-offset false positives should be ABSENT (dropped by unmapped-cur / dup-body guard) — this is the acceptance criterion that the guards work.

- [ ] **Step 4: Commit** `git add -A && git commit -m "test(struct-verify): THPDec dogfood golden"`

---

## Self-Review notes

- Spec coverage: resolver (offsetof, both forms) = Tasks 1.1-1.4; checkdiff extension (body-align, dup-body guard, JSON, don't-touch-primary) = 2.1-2.3; command (functions_for_unit, per-function base/base-map, warn-skip, aggregation, confidence/ambiguous, table+json) = 3.1-3.4; dogfood = 4.1. ✓
- The dup-body guard test (2.2) encodes the prototype's observed failure mode.
- `--tu-src` is required (resolver needs the TU's cflags); for TU targets it's the unit's .c.
- Risk: `_parse_struct_fields` may need `type`/`array_size` keys (Task 1.2 note) — verify first; extend additively if missing.
