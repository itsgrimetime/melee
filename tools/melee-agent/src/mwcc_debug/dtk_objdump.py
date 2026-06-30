"""GNU objdump-compatible text from project dtk disassembly."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class DtkObjdumpError(RuntimeError):
    """Raised when the dtk-backed objdump wrapper cannot run."""


_DTK_INSTRUCTION_RE = re.compile(
    r"^/\*\s*(?P<offset>[0-9A-Fa-f]{8})\s+"
    r"[0-9A-Fa-f]{8}\s+"
    r"(?P<bytes>(?:[0-9A-Fa-f]{2}\s+){3}[0-9A-Fa-f]{2})\s*\*/\s*"
    r"\t(?P<asm>.+?)\s*$"
)


def convert_dtk_disasm_to_objdump(text: str) -> str:
    """Convert `dtk elf disasm` instruction rows to objdump-like rows.

    decomp-permuter's PPC scorer expects the three-column shape emitted by GNU
    objdump: address, raw bytes, instruction. dtk has the same information in
    comment-prefixed assembly rows, so this adapter keeps scoring independent of
    a system `powerpc-eabi-objdump` install.
    """
    rows: list[str] = []
    for line in text.splitlines():
        match = _DTK_INSTRUCTION_RE.match(line)
        if match is None:
            continue
        offset = int(match.group("offset"), 16)
        byte_text = match.group("bytes").lower()
        asm_text = match.group("asm").strip()
        rows.append(f"{offset:x}:\t{byte_text}\t{asm_text}")
    return "\n".join(rows) + ("\n" if rows else "")


def candidate_melee_roots(start: Path | None = None) -> list[Path]:
    """Return likely melee repo roots for local and remote permuter cwd layouts."""
    cwd = (start or Path.cwd()).resolve()
    candidates: list[Path] = []
    if env_root := os.environ.get("MELEE_ROOT"):
        candidates.append(Path(env_root).expanduser())
    candidates.extend([cwd, *cwd.parents])
    for parent in [cwd, *cwd.parents]:
        candidates.append(parent / "melee")
    candidates.extend([
        Path("~/code/melee").expanduser(),
        Path("/Users/mike/code/melee"),
        Path("/home/coder/melee"),
    ])
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def find_melee_root(explicit: Path | None = None) -> Path:
    candidates = [explicit.resolve()] if explicit is not None else candidate_melee_roots()
    for candidate in candidates:
        if (candidate / "build" / "tools" / "dtk").exists():
            return candidate
    formatted = ", ".join(str(path) for path in candidates[:8])
    raise DtkObjdumpError(
        "could not find a melee root with build/tools/dtk; "
        f"checked: {formatted}"
    )


def resolve_object_file(o_file: Path, *, object_root: Path | None = None) -> Path:
    """Resolve object paths appended by decomp-permuter scorer commands."""
    expanded = o_file.expanduser()
    if expanded.is_absolute():
        return expanded

    candidates: list[Path] = []
    if object_root is not None:
        candidates.append(object_root.expanduser() / expanded)
    if caller_cwd := os.environ.get("MELEE_AGENT_CALLER_CWD"):
        candidates.append(Path(caller_cwd).expanduser() / expanded)
    candidates.append(Path.cwd() / expanded)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else expanded


def resolve_name_magic_target(obj_path: Path, melee_root: Path) -> Path | None:
    """Find the production object used to resolve anonymous @N relocs."""
    obj_path = obj_path.resolve()
    sibling_target = obj_path.with_name("target.o")
    if obj_path.name != "target.o" and sibling_target.exists():
        return sibling_target

    build_obj_root = (melee_root / "build" / "GALE01" / "obj").resolve()
    try:
        obj_path.relative_to(build_obj_root)
        return None
    except ValueError:
        pass

    build_src_root = (melee_root / "build" / "GALE01" / "src").resolve()
    try:
        rel = obj_path.relative_to(build_src_root)
    except ValueError:
        return None
    target = build_obj_root / rel
    return target if target.exists() else None


def disassemble_object(
    o_file: Path,
    *,
    melee_root: Path | None = None,
    object_root: Path | None = None,
    name_magic: bool = True,
) -> str:
    root = find_melee_root(melee_root)
    dtk = root / "build" / "tools" / "dtk"
    obj_path = resolve_object_file(o_file, object_root=object_root)
    if not dtk.exists():
        raise DtkObjdumpError(f"dtk not found: {dtk}")
    if not obj_path.exists():
        raise DtkObjdumpError(f"object file not found: {obj_path}")

    with tempfile.TemporaryDirectory(prefix="melee-dtk-objdump-") as td:
        objdump_input = obj_path
        if name_magic:
            target_o = resolve_name_magic_target(obj_path, root)
            if target_o is not None:
                from .o_rewriter import apply_name_magic_auto

                objdump_input = Path(td) / obj_path.name
                shutil.copy2(obj_path, objdump_input)
                apply_name_magic_auto(objdump_input, target_o)

        out_path = Path(td) / "out.s"
        proc = subprocess.run(
            [str(dtk), "elf", "disasm", str(objdump_input), str(out_path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise DtkObjdumpError(f"dtk elf disasm failed: {detail}")
        return convert_dtk_disasm_to_objdump(out_path.read_text())
