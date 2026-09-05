"""Live P0 substrate + fidelity gates for mwcc-retro (#541).

These exercise the retrowin32 emulator + gdb against the real GC/1.2.5n compiler.
They are gated by RETRO_LIVE=1 (distinct from the repo's LIVE_9ACC_TESTS, because
these need the retrowin32 emulator rather than wibo) and skipped when the built
retrowin32 binary is absent. See tools/mwcc_retro/P0_FINDINGS.md.
"""
import hashlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from tools.mwcc_retro import setup as rs  # noqa: E402

_RETRO_BIN = rs._retrowin32_binary(rs.VENDOR_DIR / "retrowin32")
_EXE_125N = REPO / "build/compilers/GC/1.2.5n/mwcceppc.exe"

pytestmark = pytest.mark.skipif(
    os.environ.get("RETRO_LIVE") != "1" or not _RETRO_BIN.exists(),
    reason="set RETRO_LIVE=1 and run `debug retro setup` (needs built retrowin32)",
)


@pytest.mark.slow
def test_retrowin32_binary_resolves_to_real_target_dir():
    # Regression for the P0 finding: the binary lives under cargo's redirected
    # target-dir (build/cargo), not <repo>/target.
    assert _RETRO_BIN.exists()
    assert _RETRO_BIN.name == "retrowin32"


@pytest.mark.slow
def test_o_byte_parity_with_wibo(tmp_path):
    """The critical fidelity gate: retrowin32-emulated mwcceppc must produce a
    byte-identical .o to the wibo path for a real melee TU."""
    smoke = tmp_path / "smoke.c"
    smoke.write_text("int add(int a, int b) { return a + b; }\n")
    args = ["-O4,p", "-nodefaults", "-c", str(smoke)]
    mwcc = str(_EXE_125N)
    wibo = REPO / "build/tools/wibo"
    if not wibo.exists():
        pytest.skip("wibo not present")
    ref = tmp_path / "ref.o"
    retro = tmp_path / "retro.o"
    subprocess.run([str(wibo), mwcc, *args, "-o", str(ref)],
                   cwd=REPO, check=True, timeout=300)
    subprocess.run([str(_RETRO_BIN), mwcc, *args, "-o", str(retro)],
                   cwd=REPO, check=True, timeout=300)
    assert ref.exists() and retro.exists()
    assert hashlib.md5(ref.read_bytes()).hexdigest() == \
        hashlib.md5(retro.read_bytes()).hexdigest()


@pytest.mark.slow
def test_gdb_read_write_breakpoint(tmp_path):
    """gdb attach + memory read + write + software breakpoint against the stub.

    Confirms the load-bearing primitives for the dump/intervention recipe.
    """
    smoke = tmp_path / "smoke.c"
    smoke.write_text("int add(int a, int b) { return a + b; }\n")
    script = tmp_path / "probe.gdb"
    script.write_text(
        "set pagination off\n"
        "set architecture i386\n"
        "set osabi none\n"
        "target remote localhost:9001\n"
        "x/1xb 0x42C8DB\n"          # read known DEBUGLISTING-patch byte (0xc6)
        "set {unsigned char}0x584226 = 1\n"
        "x/1xb 0x584226\n"          # write+readback DEBUGLISTING flag
        "break *0x42CD86\n"          # IRO Starting-function push
        "continue\n"
        "printf \"HIT %x\\n\", $pc\n"
        "kill\nquit\n"
    )
    emu = subprocess.Popen(
        [str(_RETRO_BIN), "--gdb-stub", str(_EXE_125N),
         "-O4,p", "-nodefaults", "-c", "-o", str(tmp_path / "p.o"), str(smoke)],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import time
        time.sleep(1.5)  # do NOT pre-connect to poll; that steals the accept slot
        out = subprocess.run(["gdb", "-batch", "-nx", "-x", str(script)],
                             capture_output=True, text=True, timeout=120)
    finally:
        if emu.poll() is None:
            emu.terminate()
    combined = out.stdout + out.stderr
    assert "0xc6" in combined           # read worked
    assert "0x584226:\t0x01" in combined  # write+readback worked
    assert "hit 42cd86" in combined.lower()  # breakpoint hit
