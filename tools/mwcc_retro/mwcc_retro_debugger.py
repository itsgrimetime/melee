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
import contextlib
import os
import shlex
import subprocess
import sys
import time
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
    # Register in sys.modules BEFORE exec_module: Python 3.14's @dataclass looks
    # up sys.modules[cls.__module__].__dict__ during class creation, so an
    # unregistered module makes cadmic's dataclasses raise AttributeError.
    sys.modules["cadmic_mwcc"] = mod
    # exec_module is deferred to the caller (inside gdb; the module imports gdb).
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


# retrowin32's gdb-stub port is hardcoded to 9001 (cli/src/debugger.rs:881);
# there is no --gdb-port flag. Serialize concurrent sessions on a lockfile so
# parallel agents don't collide on the single port.
GDB_PORT = 9001


@contextlib.contextmanager
def _port_lock():
    import fcntl
    lock_path = Path(os.environ.get("TMPDIR", "/tmp")) / "mwcc_retro_9001.lock"
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


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
    compiler = os.environ.get("RETRO_COMPILER", "1.2.5n")

    gdb.execute("set python print-stack full")
    cad.FUNCTION_NAME = fn
    cad.OUTPUT_DIR = out_dir

    # GC/1.1 backend uses cadmic's native run_compiler, which does its OWN
    # `target remote` + init + find + dump + quit. We must NOT pre-connect here
    # (a second `target remote` makes the stub drop the first connection); hand
    # the whole session to cadmic.
    # NOTE: robust cadmic-loop integration + the 1.2.5n backend address-table
    # port + the full verify harness are #541 follow-ons; backend is
    # EXPERIMENTAL and the DLL pcdump path remains the backend reference on
    # 1.2.5n.
    if phases == "backend" and compiler == "1.1":
        try:
            cad.run_compiler()  # self-connects; quits at codegen_end
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            if "Remote connection closed" not in str(exc) and \
               "not being run" not in str(exc):
                print(f"[retro] backend run note: {exc}")
        return

    # Frontend (and 1.2.5n) path: we own the connection and version descriptor.
    gdb.execute("set architecture i386")
    gdb.execute("set osabi none")
    gdb.execute(f"target remote localhost:{port}")
    if compiler == "1.1":
        cad.init_mwcc_version()
        print(f"[retro] cadmic GC/1.1 native; fn={fn}")
    else:
        cad.MWCC_VERSION = _descriptor_125n(cad, table)
        print(f"[retro] descriptor injected (spoof GC/1.1, 1.2.5n addrs); fn={fn}")

    if phases == "backend":  # 1.2.5n backend — needs the P3 address-table port
        print("[retro] 1.2.5n backend address table not populated (P3 "
              "follow-on); use the DLL pcdump path for backend on 1.2.5n.")
        _continue_to_exit(gdb)
    else:  # "frontend" or "all"
        _enable_frontend_tracing(gdb, cad, table, out_dir, fn)


def _continue_to_exit(gdb):
    """Continue until the inferior exits. When the emulated compiler finishes,
    retrowin32 closes the gdb-stub socket; gdb raises "Remote connection closed".
    That is the normal end-of-run signal, not an error — swallow it."""
    try:
        gdb.execute("continue")
    except gdb.error as e:
        if "Remote connection closed" not in str(e) and \
           "not being run" not in str(e):
            raise


def _reset_cadmic_state(cad):
    cad.TYPE_CACHE.clear()
    cad.NODE_NAMES.clear()
    cad.MWCC_OPCODE_INFO.clear()
    cad.POTENTIAL_SPILLS.clear()
    cad.REGALLOC_OBJECTS.clear()
    cad.REGALLOC_PASS.clear()


# Scratch .data VAs for staging the fopen path/mode strings (unused tail of
# .data past the DEBUGLISTING/PCFILE globals; fopen copies the bytes immediately
# so transient reuse is safe). Confirmed writable in the live P0 probe.
_SCRATCH_PATH = 0x584400
_SCRATCH_MODE = 0x584460
# The gdb side opens a SHORT temp path (must fit the scratch gap above and not
# collide with the mode string); the host launcher copies it to out_dir.
_TRACE_TMP = "/tmp/mwcc_retro_iro.txt"


def _enable_frontend_tracing(gdb, cad, table, out_dir, fn):
    """Enable retail's own front-end IRO per-phase dump machinery, scoped to `fn`.

    Live-validated recipe (see P0_FINDINGS.md): at the first IRO "Starting
    function" push (CRT initialised, deep in compilation) — stage a filename and
    call the compiler's fopen with pre-staged pointers (gdb cannot marshal string
    literals into a no-symbol inferior), store the FILE* into PCFILE, set
    DEBUGLISTING/DEBUG_GUARD/copt-debug, and NOP the IRO_DumpAfterPhase flag-test
    `je` so every phase dumps its flowgraph. Per-function scoping: a breakpoint
    handler at the same push toggles PCFILE on only while the target function
    compiles, so non-target functions emit nothing.
    """
    import struct as _struct

    e = table["entries"]
    req = ["iro_dumpafterphase_je", "debuglisting_flag", "debug_guard",
           "pcfile", "fopen", "copt_debug_byte", "iro_starting_function_push",
           "iro_function_name_ptr"]
    missing = [k for k in req if k not in e or not e[k].get("va")]
    if missing:
        print(f"[retro] frontend tracing addresses missing {missing}; skipping")
        gdb.execute("continue")
        return

    je = e["iro_dumpafterphase_je"]
    je_va = je["va"]
    je_from = bytes.fromhex(je["patch_from"])
    je_to = bytes.fromhex(je["patch_to"])
    dbg_flag = e["debuglisting_flag"]["va"]
    dbg_guard = e["debug_guard"]["va"]
    pcfile = e["pcfile"]["va"]
    fopen_va = e["fopen"]["va"]
    copt = e["copt_debug_byte"]
    sf_push = e["iro_starting_function_push"]["va"]
    fname_ptr = e["iro_function_name_ptr"]["va"]

    inf = gdb.selected_inferior()
    rd = lambda a, n: bytes(inf.read_memory(a, n))
    wr = lambda a, b: inf.write_memory(a, b)
    # Open a SHORT temp path inside the inferior (long out_dir paths overflow the
    # scratch gap and collide with the staged mode string); host copies it out.
    out_path = _TRACE_TMP

    def current_fn_name():
        fnobj = _struct.unpack("<I", rd(fname_ptr, 4))[0]
        if not fnobj:
            return None
        namep = _struct.unpack("<I", rd(fnobj + 0xA, 4))[0]  # ObjObject->name
        if not namep:
            return None
        out = bytearray()
        a = namep + 0xA  # HashNameNode->name string
        for _ in range(256):
            c = rd(a, 1)
            if c == b"\x00":
                break
            out += c
            a += 1
        return out.decode("latin-1")

    state = {"filep": 0, "ready": False, "aborted": False}

    def set_pcfile(on):
        wr(pcfile, _struct.pack("<I", state["filep"] if on else 0))

    def one_time_setup():
        cur = rd(je_va, len(je_from))
        if cur != je_from:
            print(f"[retro] ABORT: je guard {je_va:#x}={cur.hex()} != "
                  f"{je_from.hex()}; not patching")
            state["aborted"] = True
            return
        wr(_SCRATCH_PATH, out_path.encode("latin-1") + b"\x00")
        wr(_SCRATCH_MODE, b"w\x00")
        filep = int(gdb.parse_and_eval(
            f"((int(*)(int,int)){fopen_va:#x})({_SCRATCH_PATH:#x},"
            f"{_SCRATCH_MODE:#x})"))
        if not filep:
            print("[retro] ABORT: fopen returned NULL")
            state["aborted"] = True
            return
        state["filep"] = filep
        wr(dbg_flag, b"\x01")
        wr(dbg_guard, b"\x01\x00\x00\x00")
        wr(copt["va"], bytes.fromhex(copt["patch_to"]))
        wr(je_va, je_to)
        state["ready"] = True
        print(f"[retro] frontend tracing enabled; trace -> {out_path}")

    class _Scope(gdb.Breakpoint):
        def stop(self):
            if not state["ready"] and not state["aborted"]:
                one_time_setup()
            if state["ready"]:
                set_pcfile(current_fn_name() == fn)
            return False  # never halt; just toggle scoping

    _Scope(f"*{sf_push:#x}")
    _continue_to_exit(gdb)


# ---- host launcher (no gdb) ----
def main():
    ap = argparse.ArgumentParser(description="mwcc-retro debugger launcher")
    ap.add_argument("--emulator", "-e", required=True)
    ap.add_argument("--args", "-a", required=True, help="mwcceppc command line")
    ap.add_argument("--gdb", "-g", default="gdb")
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--phases", default="all")
    ap.add_argument("--compiler", default="1.2.5n")
    ap.add_argument("fn")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    if os.path.exists(_TRACE_TMP):
        os.remove(_TRACE_TMP)  # stale from a prior run

    # retrowin32 takes the mwcc command as a positional greedy cmdline after
    # --gdb-stub; the gdb port is hardcoded to 9001 (no --gdb-port flag).
    emu = [a.emulator, "--gdb-stub", *shlex.split(a.args)]
    env = dict(os.environ, RETRO_TABLE=a.table, RETRO_OUT=a.out,
               RETRO_FN=a.fn, RETRO_PHASES=a.phases, RETRO_PORT=str(GDB_PORT),
               RETRO_COMPILER=a.compiler)
    # gdb runs a .py passed to -x as embedded Python with __name__ == "__main__"
    # (and the `gdb` module importable), so the __main__/IN_GDB branch below
    # fires run_in_gdb(). This is cadmic's mechanism; runpy.run_path misbehaves
    # inside gdb's interpreter.
    gdb_cmd = [a.gdb, "-batch", "-nx", "-x", __file__]
    # Hold the lock across the whole emu+gdb session: the fixed port 9001 means
    # only one retro session can run at a time.
    with _port_lock():
        emu_proc = subprocess.Popen(emu)
        try:
            # Give retrowin32 a beat to start listening. Do NOT pre-connect to
            # poll readiness: wait_for_gdb_connection accepts exactly one socket,
            # so a probe connection steals gdb's slot. A short sleep is enough;
            # gdb is the only connector.
            time.sleep(1.5)
            subprocess.run(gdb_cmd, check=True, env=env)
        finally:
            if emu_proc.poll() is None:
                emu_proc.terminate()
                try:
                    emu_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    emu_proc.kill()
    # Copy the short-path trace the gdb side wrote into the requested out_dir.
    if os.path.exists(_TRACE_TMP):
        import shutil
        shutil.copy(_TRACE_TMP, os.path.join(a.out, "iro-trace.txt"))


if __name__ == "__main__":
    # Inside gdb (`-x this.py`): the gdb module is importable -> run the dumper.
    # As a plain CLI: drive the emulator + gdb.
    if IN_GDB:
        run_in_gdb()
    else:
        main()
