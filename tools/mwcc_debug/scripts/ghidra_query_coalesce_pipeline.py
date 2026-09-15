#!/usr/bin/env python3
"""Decompile the buildinterferencegraph pipeline.

Used during P2b RE (2026-05-19) to identify which function in the pipeline
is the real conservative coalescer. Result: it's FUN_00530E00, operating on
a union-find array at DAT_0058308C (now exposed as COALESCE_ALIAS in
mwcc_debug.c). Keep this script around for future RE work — the same
pattern (decompile + xrefs) generalizes to any MWCC pass we want to hook.
"""
from pathlib import Path
import pyghidra
pyghidra.start()

# Project lives at tools/mwcc_debug/ghidra_project/ (sibling of this script's parent).
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent / "ghidra_project"
PROJECT_NAME = "mwcceppc"


def main():
    proj = pyghidra.open_project(str(PROJECT_DIR), PROJECT_NAME, create=False)
    try:
        with pyghidra.program_context(proj, "/mwcceppc.exe") as program:
            run(program)
    finally:
        proj.close()


def run(program):
    from ghidra.app.decompiler import DecompInterface
    from ghidra.util.task import ConsoleTaskMonitor

    fm = program.getFunctionManager()
    rm = program.getReferenceManager()
    af = program.getAddressFactory()
    di = DecompInterface()
    di.openProgram(program)

    def fn(va):
        return fm.getFunctionAt(af.getAddress(f"0x{va:08x}"))

    def fn_containing(va):
        return fm.getFunctionContaining(af.getAddress(f"0x{va:08x}"))

    def decompile(f, label):
        print("=" * 70)
        print(f"DECOMPILE: {label} {f.getName()} @ {f.getEntryPoint()}")
        print(f"  size: 0x{f.getBody().getNumAddresses():x} bytes")
        callers = list(f.getCallingFunctions(None))
        callees = list(f.getCalledFunctions(None))
        print(f"  callers ({len(callers)}): {', '.join(c.getName() for c in callers)}")
        print(f"  callees ({len(callees)}): {', '.join(c.getName() for c in callees)}")
        print("=" * 70)
        res = di.decompileFunction(f, 120, ConsoleTaskMonitor())
        if res and res.decompileCompleted():
            code = res.getDecompiledFunction().getC()
            if len(code) > 12000:
                print(code[:6000])
                print(f"\n... [TRUNCATED — {len(code)-12000} chars omitted] ...\n")
                print(code[-6000:])
            else:
                print(code)
        else:
            print("  decompile failed")
        print()

    # Pipeline parent (called by who?)
    parent = fn(0x530A00)
    if parent:
        decompile(parent, "PIPELINE PARENT (calls all 5 phases)")

    # The 5 phases
    for va, label in [
        (0x5301B0, "PHASE 1: pre-pass"),
        (0x530A80, "PHASE 2: flag-candidates (current P2 hook)"),
        (0x531290, "PHASE 3: probable MERGE / coalesce-apply"),
        (0x530E00, "PHASE 4: ?"),
        (0x530C00, "PHASE 5: builds INTERFERENCEGRAPH"),
    ]:
        f = fn(va)
        if f:
            decompile(f, label)
        else:
            print(f"### {label} @ 0x{va:08x} NOT FOUND ###\n")

    # What calls FUN_00530a00 (the pipeline)? probably buildinterferencegraph
    if parent:
        callers = list(parent.getCallingFunctions(None))
        print("=" * 70)
        print(f"GRANDPARENT(s) of pipeline parent:")
        print("=" * 70)
        for c in callers:
            print(f"  {c.getEntryPoint()} {c.getName()}, size=0x{c.getBody().getNumAddresses():x}")
        print()


if __name__ == "__main__":
    main()
