import shutil
import subprocess
import pytest
from pathlib import Path
from src.common.elf_symbols import ObjSymbol, read_object_symbols

# Repo root relative to this file: tests/ -> tools/melee-agent/ -> tools/ -> repo root
_REPO = Path(__file__).parent.parent.parent.parent
_WIBO = _REPO / "build/tools/wibo"
_MWCC = _REPO / "build/compilers/GC/1.2.5/mwcceppc.exe"


def _compile_fixture(tmp_path: Path) -> Path:
    """Compile a small C file to a relocatable ELF .o.

    Prefers MWCC/wibo (always produces ELF on all host platforms) over the
    host cc/gcc which may produce Mach-O on macOS.
    """
    src = tmp_path / "fix.c"
    src.write_text("int g_global = 7;\nstatic int g_local = 3;\nchar g_buf[10];\n")
    obj = tmp_path / "fix.o"

    # Prefer MWCC + wibo: always emits ELF regardless of host platform.
    if _WIBO.exists() and _MWCC.exists():
        rc = subprocess.run(
            [str(_WIBO), str(_MWCC), "-c", str(src), "-o", str(obj),
             "-nodefaults", "-proc", "gekko", "-fp", "hardware",
             "-Cpp_exceptions", "off", "-enum", "int"],
            capture_output=True,
        )
        if rc.returncode == 0 and obj.exists():
            return obj

    # Fallback: host cc/gcc (may produce Mach-O on macOS — skip if so).
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no host C compiler available and MWCC/wibo not found")
    rc = subprocess.run([cc, "-c", str(src), "-o", str(obj)], capture_output=True)
    if rc.returncode != 0:
        pytest.skip("host cc could not produce an object")
    # Verify it's actually an ELF file (macOS cc produces Mach-O).
    with obj.open("rb") as f:
        magic = f.read(4)
    if magic != b"\x7fELF":
        pytest.skip("host cc produced a non-ELF object (e.g. Mach-O); need an ELF compiler")
    return obj


def test_reads_named_object_symbols_with_sizes(tmp_path):
    syms = {s.name: s for s in read_object_symbols(_compile_fixture(tmp_path))}
    assert syms["g_global"].size == 4
    assert syms["g_global"].type == "STT_OBJECT"
    assert syms["g_global"].bind == "STB_GLOBAL"
    assert syms["g_buf"].size == 10


def test_missing_file_returns_empty(tmp_path):
    assert read_object_symbols(tmp_path / "nope.o") == []
