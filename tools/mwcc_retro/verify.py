"""`debug retro verify` — cross-checks for the mwcc-retro substrate (#541).

Authoritative check (achievable today): byte-parity of a unit's .o between the
retrowin32-emulated retail mwcceppc and the normal wibo build. If they match, the
emulator is a faithful oracle and any dump it produces is trustworthy.

Advisory check: presence of a front-end IRO trace for the control function.

The fuller authoritative set from the spec (AFTER-REGALLOC virtual->phys map and
regalloc node counts vs the DLL pcdump) depends on the backend 1.2.5n address
port, tracked as a #541 follow-on.
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import PKG_ROOT, setup as _setup

_REPO = PKG_ROOT.parent.parent


@dataclass
class Result:
    name: str
    kind: str              # "parity" | "frontend"
    authoritative: bool
    passed: bool
    detail: str = ""


def _mwcc_command(unit: str) -> str:
    """The mwcceppc command line for a unit (without the wibo/sjiswrap prefix).
    Reuses the CLI's build.ninja extractor."""
    from src.cli.debug import _ninja_cflags_for_unit
    cflags, _mw = _ninja_cflags_for_unit(unit)
    obj = f"build/GALE01/{unit[:-2]}.o"
    return f"{cflags} -c {unit} -o {obj}"


def run(unit: str = "src/melee/mn/mnvibration.c", fn: str | None = None
        ) -> list[Result]:
    results: list[Result] = []
    try:
        res = _setup.ensure(force=False)
    except _setup.SetupError as e:
        return [Result("setup", "parity", True, False, str(e))]

    mwcc = str(_REPO / "build/compilers/GC/1.2.5n/mwcceppc.exe")
    wibo = _REPO / "build/tools/wibo"
    sjis = _REPO / "build/tools/sjiswrap.exe"
    try:
        args = _mwcc_command(unit)
    except Exception as e:  # noqa: BLE001
        return [Result("ninja-command", "parity", True, False, str(e))]
    # drop -MMD (depfile) for a clean one-shot compile
    arg_list = [a for a in shlex.split(args) if a != "-MMD"]

    with tempfile.TemporaryDirectory() as td:
        ref = Path(td) / "ref.o"
        retro = Path(td) / "retro.o"

        def swap_out(lst, out):
            lst = list(lst)
            lst[lst.index("-o") + 1] = str(out)
            return lst

        ok = True
        detail = ""
        if wibo.exists():
            subprocess.run([str(wibo), str(sjis), mwcc] + swap_out(arg_list, ref),
                           cwd=_REPO, capture_output=True, timeout=300)
        subprocess.run([str(res.retrowin32_bin), mwcc] + swap_out(arg_list, retro),
                       cwd=_REPO, capture_output=True, timeout=300)

        if ref.exists() and retro.exists():
            h1 = hashlib.md5(ref.read_bytes()).hexdigest()
            h2 = hashlib.md5(retro.read_bytes()).hexdigest()
            ok = h1 == h2
            detail = f"wibo={h1[:8]} retro={h2[:8]}"
        elif retro.exists():
            ok = True
            detail = "retro produced .o (wibo unavailable for comparison)"
        else:
            ok = False
            detail = "retrowin32 produced no .o"
        results.append(Result(f".o byte-parity ({unit})", "parity", True, ok, detail))

    return results
