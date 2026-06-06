# src/common/struct_layout.py
"""Reusable MWCC offsetof-probe layout resolver.

Resolves struct field offsets by compiling a probe TU with the same
MWCC flags as the real build, then reading the .data symbol back from the
ELF object file.
"""
from __future__ import annotations

import re
import shlex
import struct
import subprocess
import tempfile
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


_HEADER_DIRS = [
    "include",
    "src",
    "extern/dolphin/include",
    "extern/dolphin/src",
]


def _find_struct_body(repo: Path, name: str) -> str | None:
    """Find the body of a C struct (or typedef struct) by name.

    Handles both:
      struct Name { ... }
      typedef struct _Name { ... } Name;
    Returns the raw content between the outermost braces, or None.
    """
    pats = [
        re.compile(rf"struct\s+_?{re.escape(name)}\s*\{{(.*?)\}}", re.S),
        re.compile(rf"struct\s*\{{(.*?)\}}\s*{re.escape(name)}\s*;", re.S),
    ]
    for d in _HEADER_DIRS:
        root = repo / d
        if not root.exists():
            continue
        for hp in root.rglob("*.h"):
            try:
                txt = hp.read_text(errors="ignore")
            except OSError:
                continue
            if name not in txt:
                continue
            for pat in pats:
                m = pat.search(txt)
                if m:
                    return m.group(1)
    return None


def _parse_c_fields(body: str) -> list[dict]:
    """Parse C struct fields from raw body text (no offset-comment required).

    Returns a list of dicts with keys: name, type, is_array, array_size.
    Skips fields whose names start with 'pad' or 'unk' (padding/unknown).
    Handles simple declarations, array declarations, and pointer types.
    """
    fields = []
    # Strip C comments
    cleaned = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    cleaned = re.sub(r"//[^\n]*", "", cleaned)

    # Split into statements by semicolons; handle nested braces (anonymous structs etc)
    # We parse line-by-line within a flat struct body
    for line in cleaned.split(";"):
        line = line.strip()
        if not line:
            continue

        # Match: optional leading pointer stars, optional const, type, optional stars/const, name, optional [N]
        # Pattern: type_tokens... name [array_size]?
        # Example lines:
        #   u8 RST
        #   u8* dLC[3]
        #   THPComponent components[3]
        #   u32 pad2[9]
        #   u8 validHuffmanTabs

        # Simplify: find the last token as the name (with optional array suffix)
        # Split by whitespace, last token = name (possibly name[N])
        tokens = line.split()
        if len(tokens) < 2:
            continue

        # Last token is name possibly with array suffix
        raw_name = tokens[-1]
        arr_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)(?:\[(\d+)\])?$", raw_name)
        if not arr_match:
            continue

        field_name = arr_match.group(1)
        array_size = int(arr_match.group(2)) if arr_match.group(2) else None

        # Type is everything except the last token, stripped of pointer stars from the end
        type_str = " ".join(tokens[:-1]).rstrip("*").strip()
        # Also strip pointer from name-start (e.g. "u8*" split oddly)
        type_str = re.sub(r"\*+$", "", type_str).strip()

        fields.append({
            "name": field_name,
            "type": type_str,
            "is_array": array_size is not None,
            "array_size": array_size,
        })

    return fields


def enumerate_field_paths(repo: Path, struct_name: str, _depth: int = 0) -> list[str]:
    """Enumerate offsetof-able field paths for a struct.

    Returns strings like "RST", "components[0].predDC", etc.
    Recurses one level into struct-typed fields.
    Skips fields whose names start with 'pad' or 'unk'.
    """
    body = _find_struct_body(repo, struct_name)
    if body is None:
        raise ValueError(f"struct {struct_name!r} not found in header dirs")

    fields = _parse_c_fields(body)
    out: list[str] = []

    for f in fields:
        nm = f["name"]
        if not nm or nm.startswith("pad") or nm.startswith("unk"):
            continue

        arr = f["array_size"]
        elem_type = f["type"]

        # Recurse into nested struct types (one level only)
        nested: list[str] = []
        if _depth < 1 and _find_struct_body(repo, elem_type) is not None:
            try:
                nested = enumerate_field_paths(repo, elem_type, _depth + 1)
            except ValueError:
                nested = []

        # Determine indices to emit
        if arr is not None:
            indices: list[int | None] = list(range(min(arr, 2)))  # 0 and 1 (or just 0 for size-1)
        else:
            indices = [None]

        for idx in indices:
            base = nm if idx is None else f"{nm}[{idx}]"
            if nested:
                out.extend(f"{base}.{sub}" for sub in nested)
            else:
                out.append(base)

    return out


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
            # Use shlex.split to properly handle quoted pragma values like
            # -pragma "cats off" (split() would break the quoted string)
            raw = cf.group(1).strip()
            try:
                tokens = shlex.split(raw)
            except ValueError:
                tokens = raw.split()
            return CflagsSpec(mw.group(1).strip(), tokens)
    raise ValueError(f"no build edge found for {tu_src}")


# Flags to drop when building a standalone probe (build-system or path-dependent flags).
# -cwd <dir> sets MWCC's "current working directory" for source-relative includes;
# the probe doesn't need it and the 'source' dir doesn't exist in the worktree.
# -warn iserror would turn probe warnings into errors unnecessarily.
_DROP_FLAGS: set[str] = {"-MMD", "-warn"}
# Flags that take a following argument to also drop
_DROP_FLAGS_WITH_ARG: set[str] = {"-cwd"}


def _probe_cflags(spec: CflagsSpec) -> list[str]:
    """Filter spec.cflags to only the flags relevant for layout probing."""
    out: list[str] = []
    skip_next = False
    i = 0
    toks = spec.cflags
    while i < len(toks):
        tok = toks[i]
        if skip_next:
            skip_next = False
            i += 1
            continue
        if tok in _DROP_FLAGS:
            # drop this flag; if it has a following non-flag token, drop that too
            # (e.g. -warn iserror: next token is "iserror", not a flag)
            if i + 1 < len(toks) and not toks[i + 1].startswith("-"):
                skip_next = True
            i += 1
            continue
        if tok in _DROP_FLAGS_WITH_ARG:
            # drop this flag AND its next argument unconditionally
            skip_next = True
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


def _compile_probe(repo: Path, spec: CflagsSpec, src: str) -> bytes:
    """Compile a C source string with the given cflags via MWCC/wibo.

    Returns the raw bytes of the resulting .o file.
    Raises RuntimeError if compilation fails.
    """
    with tempfile.TemporaryDirectory() as td:
        cpath = Path(td) / "probe.c"
        opath = Path(td) / "probe.o"
        cpath.write_text(src)
        cc = repo / "build/compilers" / spec.mw_version / "mwcceppc.exe"
        wibo = repo / "build/tools/wibo"
        cmd = [str(wibo), str(cc), *_probe_cflags(spec), "-c", str(cpath), "-o", str(opath)]
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        if not opath.exists():
            raise RuntimeError(
                f"probe compile failed:\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
            )
        return opath.read_bytes()


def _read_symbol_u32s(obj: bytes, symbol: str) -> list[int]:
    """Read an array of u32 values from a named symbol in an ELF32 object file."""
    assert obj[:4] == b"\x7fELF", "not an ELF file"
    end = ">" if obj[5] == 2 else "<"  # ELFDATA2MSB = 2 → big-endian
    (e_shoff,) = struct.unpack(end + "I", obj[0x20:0x24])
    (e_shentsize,) = struct.unpack(end + "H", obj[0x2E:0x30])
    (e_shnum,) = struct.unpack(end + "H", obj[0x30:0x32])
    (e_shstrndx,) = struct.unpack(end + "H", obj[0x32:0x34])
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        nm, typ, fl, ad, off, sz, lk, inf, al, es = struct.unpack(end + "10I", obj[o : o + 40])
        secs.append(dict(name=nm, offset=off, size=sz, link=lk, entsize=es))
    sh = secs[e_shstrndx]
    shstr = obj[sh["offset"] : sh["offset"] + sh["size"]]
    for s in secs:
        s["sn"] = shstr[s["name"] : shstr.index(b"\0", s["name"])].decode()
    sym = next(s for s in secs if s["sn"] == ".symtab")
    st = secs[sym["link"]]
    strd = obj[st["offset"] : st["offset"] + st["size"]]
    for i in range(sym["size"] // sym["entsize"]):
        o = sym["offset"] + i * sym["entsize"]
        n, val, sz, info, other, shndx = struct.unpack(end + "IIIBBH", obj[o : o + 16])
        name = strd[n : strd.index(b"\0", n)].decode()
        if name == symbol or name == "_" + symbol:
            sec = secs[shndx]
            raw = obj[sec["offset"] + val : sec["offset"] + val + sz]
            return [struct.unpack(end + "I", raw[j : j + 4])[0] for j in range(0, len(raw), 4)]
    raise KeyError(f"symbol {symbol!r} not found in .symtab")


def _tu_include_of(repo: Path, struct_name: str) -> str:
    """Find the angle-bracket include path for the header that defines `struct_name`.

    Returns e.g. '<dolphin/thp/thp.h>' (relative to one of the -i include dirs).
    """
    pats = [
        re.compile(rf"struct\s+_?{re.escape(struct_name)}\s*\{{"),
        re.compile(rf"\}}\s*{re.escape(struct_name)}\s*;"),
    ]
    for d in _HEADER_DIRS:
        root = repo / d
        if not root.exists():
            continue
        for hp in root.rglob("*.h"):
            try:
                txt = hp.read_text(errors="ignore")
            except OSError:
                continue
            if any(p.search(txt) for p in pats):
                rel = hp.relative_to(root)
                return f"<{rel.as_posix()}>"
    raise ValueError(f"no header found for struct {struct_name!r}")


def resolve_layout(repo: Path, struct_name: str, tu_src: str) -> dict[str, int]:
    """Compile an offsetof-probe and return a mapping of field-path → byte offset.

    Uses the same MWCC cflags as the real build edge for `tu_src`.
    """
    spec = parse_tu_cflags(repo, tu_src)
    paths = enumerate_field_paths(repo, struct_name)
    incl = _tu_include_of(repo, struct_name)

    # Build the probe source: an array of offsets, one per field path.
    # Use the address-of trick instead of offsetof() to avoid needing stddef.h.
    body = f"#include {incl}\n"
    body += f"#define OFF(f) ((unsigned long)&((({struct_name}*)0)->f))\n"
    body += "unsigned long __off[] = {\n"
    body += ",\n".join(f"  OFF({p})" for p in paths)
    body += "\n};\n"

    obj = _compile_probe(repo, spec, body)
    offs = _read_symbol_u32s(obj, "__off")
    return {p: o for p, o in zip(paths, offs)}


def offset_to_field(layout: dict[str, int], offset: int) -> str | None:
    """Return the field path for a given offset, or None if not found."""
    for p, o in layout.items():
        if o == offset:
            return p
    return None


def verify_offsets(
    repo: Path,
    struct_name: str,
    tu_src: str,
    expect: dict[str, int],
) -> bool:
    """Compile a static-assertion probe to verify expected field offsets.

    Returns True if all expected offsets match, False if any do not.
    This is cheaper than resolve_layout() when you only need a pass/fail check
    on a known set of offsets.
    """
    spec = parse_tu_cflags(repo, tu_src)
    incl = _tu_include_of(repo, struct_name)

    # Use typedef char[1] (ok) / typedef char[-1] (compiler error) trick.
    body = f"#include {incl}\n"
    body += f"#define OFF(f) ((unsigned long)&((({struct_name}*)0)->f))\n"
    for i, (path, off) in enumerate(expect.items()):
        body += f"typedef char _chk{i}[OFF({path}) == {off} ? 1 : -1];\n"

    try:
        _compile_probe(repo, spec, body)
        return True
    except RuntimeError:
        return False
