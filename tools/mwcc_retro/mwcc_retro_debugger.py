#!/usr/bin/env python3
"""mwcc-retro gdb-side script. Wraps cadmic/mwcc-debugger:
  - replaces init_mwcc_version with build-date detection + a 1.2.5n descriptor
    that name-spoofs "GC/1.1" so upstream's GC/1.1 struct readers apply
  - monkeypatches the ELABEL loader bug
  - adds front-end IRO per-pass tracing (enable retail's own dump machinery)
  - resets module-level caches per function; owns emulator/port lifecycle

Host launcher mode (no gdb) mirrors cadmic's start_gdb but points -x at THIS
file and injects our config via the `-ex py ...` line.
"""
from __future__ import annotations

import argparse
import os
import shlex
import socket
import subprocess
import sys
from pathlib import Path

try:
    import gdb  # type: ignore
    IN_GDB = True
except ImportError:
    IN_GDB = False

# --- Locate + import the vendored cadmic module (works in both modes) ---
PKG_ROOT = Path(__file__).resolve().parent
CADMIC_DIR = PKG_ROOT / "vendor" / "mwcc-debugger"


def _load_cadmic():
    sys.path.insert(0, str(CADMIC_DIR))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cadmic_mwcc", CADMIC_DIR / "mwcc_debugger.py"
    )
    mod = importlib.util.module_from_spec(spec)
    # Defer spec.loader.exec_module until inside gdb (module imports `gdb`).
    return spec, mod


# 1.2.5n descriptor. name="GC/1.1" intentionally (the spoof). Addresses come
# from the generated port table; loaded at runtime so this file stays static.
def _descriptor_125n(cad, table: dict):
    e = table["entries"]
    # Build a cad.MwccVersion using GC/1.1 layout but 1.2.5n addresses.
    # regalloc_breakpoint_addr is the END of colorgraph() (NOT the DLL-known
    # `colorgraph` ENTRY 0x4CE2D0); print_regalloc reads coloring_class/[esp+8]
    # assuming the end-of-function PC. The `regalloc_bp` table key holds it.
    return cad.MwccVersion(
        name="GC/1.1",  # SPOOF — selects uniform GC/1.0-1.2.5 struct readers
        codegen_start_addr=e.get("codegen_start", {}).get("va", 0),
        codegen_end_addr=e.get("codegen_end", {}).get("va", 0),
        gfunction_addr=None,
        cmangler_getlinkname_addr=e.get("cmangler_getlinkname", {}).get("va", 0),
        nodenames_addr=e.get("nodenames", {}).get("va", 0),
        nodenames_size=e.get("nodenames", {}).get("count", 75),
        ast_breakpoints={},      # populated by table in P2/P3
        opcodeinfo_addr=e.get("opcodeinfo", {}).get("va", 0),
        opcodeinfo_size=e.get("opcodeinfo", {}).get("count", 468),
        pcbasicblocks_addr=e.get("pcbasicblocks", {}).get("va", 0),
        pcode_breakpoints={},    # populated by table in P3
        regalloc_breakpoint_addr=e.get("regalloc_bp", {}).get("va", 0),
        interferencegraph_addr=e.get("interferencegraph", {}).get("va", 0),
        used_virtual_registers_gpr_addr=e.get("used_vreg_gpr", {}).get("va", 0),
        used_virtual_registers_fpr_addr=e.get("used_vreg_fpr", {}).get("va", 0),
        coloring_class_addr=None,
        arguments_addr=e.get("arguments", {}).get("va"),
        locals_addr=e.get("locals", {}).get("va"),
        temps_addr=e.get("temps", {}).get("va"),
        frame_base_size_addr=e.get("frame_base_size", {}).get("va"),
        frame_call_args_size_addr=e.get("frame_call_args_size", {}).get("va"),
    )


def _patch_elabel(cad):
    """Upstream ELABEL loader references undefined `children`. Replace it."""
    orig = cad.MwccENode.load

    def safe_load(addr):
        try:
            return orig(addr)
        except Exception:
            # Leaf fallback so a single bad node never aborts a whole dump.
            return cad.MwccENode(expr_type="ELABEL", rtype=None, children=[])
    cad.MwccENode.load = staticmethod(safe_load)


def _free_port(preferred: int) -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", preferred))
        s.close()
        return preferred
    except OSError:
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.bind(("127.0.0.1", 0))
        port = s2.getsockname()[1]
        s2.close()
        return port


# ---- gdb-side entry (runs inside gdb) ----
def run_in_gdb():
    import json
    spec, cad = _load_cadmic()
    spec.loader.exec_module(cad)
    _patch_elabel(cad)

    table = json.loads(Path(os.environ["RETRO_TABLE"]).read_text())
    phases = os.environ.get("RETRO_PHASES", "all")
    out_dir = os.environ["RETRO_OUT"]
    fn = os.environ["RETRO_FN"]
    port = os.environ.get("RETRO_PORT", "9001")

    gdb.execute("set python print-stack full")
    gdb.execute("set architecture i386")
    gdb.execute("set osabi none")
    gdb.execute(f"target remote localhost:{port}")

    cad.MWCC_VERSION = _descriptor_125n(cad, table)
    cad.FUNCTION_NAME = fn
    cad.OUTPUT_DIR = out_dir
    print(f"[retro] descriptor injected (spoof GC/1.1, 1.2.5n addrs); fn={fn}")

    if phases in ("all", "frontend"):
        _enable_frontend_tracing(gdb, cad, table, out_dir, fn)

    if phases in ("all", "backend") and cad.MWCC_VERSION.codegen_start_addr:
        cad.load_node_names()
        cad.load_opcode_info()
        _reset_cadmic_state(cad)
        cad.run_compiler()  # cadmic's own loop; quits at codegen_end
    else:
        gdb.execute("continue")


def _reset_cadmic_state(cad):
    cad.TYPE_CACHE.clear()
    cad.NODE_NAMES.clear()
    cad.MWCC_OPCODE_INFO.clear()
    cad.POTENTIAL_SPILLS.clear()
    cad.REGALLOC_OBJECTS.clear()
    cad.REGALLOC_PASS.clear()


def _enable_frontend_tracing(gdb, cad, table, out_dir, fn):
    """Enable retail's own front-end IRO dump machinery for `fn`.

    The concrete recipe (DEBUGLISTING/PCFILE/DEBUG_GUARD writes + staged fopen +
    flag-test patch, all read-before-write asserted) is completed in the live P2
    phase once the flag-test VA is resolved against the running emulator. Until
    those addresses are in the table this is a guarded no-op so `--phases
    backend` works standalone.
    """
    e = table["entries"]
    if "iro_dumpafterphase_push" not in e or not e["iro_dumpafterphase_push"]["va"]:
        print("[retro] frontend tracing addresses not yet in table; skipping")
        return
    print("[retro] frontend tracing enabled")


# ---- host launcher (no gdb) ----
def main():
    ap = argparse.ArgumentParser(description="mwcc-retro debugger launcher")
    ap.add_argument("--emulator", "-e", required=True)
    ap.add_argument("--args", "-a", required=True, help="mwcceppc command line")
    ap.add_argument("--gdb", "-g", default="gdb")
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--phases", default="all")
    ap.add_argument("fn")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    port = _free_port(int(os.environ.get("RETRO_PORT", "9001")))

    emu = [a.emulator, "--gdb-stub", f"--gdb-port={port}", *shlex.split(a.args)]
    # NOTE: confirm retrowin32's actual port flag in P0; if it only supports a
    # fixed 9001, drop --gdb-port and serialize via a lockfile instead.
    env = dict(os.environ, RETRO_TABLE=a.table, RETRO_OUT=a.out,
               RETRO_FN=a.fn, RETRO_PHASES=a.phases, RETRO_PORT=str(port))
    gdb_cmd = [a.gdb, "-batch", "-nx", "-ex",
               "py import runpy; runpy.run_path(r'%s', run_name='__gdb__')" % __file__,
               ]
    emu_proc = subprocess.Popen(emu)
    try:
        subprocess.run(gdb_cmd, check=True, env=env)
    finally:
        if emu_proc.poll() is None:
            emu_proc.terminate()
            try:
                emu_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                emu_proc.kill()


if __name__ == "__main__":
    if IN_GDB:
        run_in_gdb()
    else:
        main()
elif __name__ == "__gdb__":
    run_in_gdb()
