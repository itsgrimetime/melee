#!/usr/bin/env python3
"""Ghidra investigation — sanity-check the project import.

Run setup_ghidra.sh first to create the Ghidra project, then this script
verifies imageBase, memory blocks, and a few sample functions are loaded.
Useful when bringing up a new RE environment.
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
            run_queries(program)
    finally:
        proj.close()


def run_queries(program):
    fm = program.getFunctionManager()
    rm = program.getReferenceManager()
    addr_factory = program.getAddressFactory()

    def addr(va):
        return addr_factory.getAddress(f"0x{va:08x}")

    def fn_at(va):
        return fm.getFunctionAt(addr(va))

    def fn_containing(va):
        return fm.getFunctionContaining(addr(va))

    print("=" * 70)
    print("DIAGNOSTIC: program state")
    print("=" * 70)
    print(f"  imageBase: {program.getImageBase()}")
    funcs = list(fm.getFunctions(True))
    print(f"  total functions: {len(funcs)}")
    if funcs:
        print(f"  first fn: {funcs[0].getEntryPoint()} {funcs[0].getName()}")
        print(f"  last fn:  {funcs[-1].getEntryPoint()} {funcs[-1].getName()}")
    print()

    # ─── 1. coalescenodes function ───────────────────────────────────
    print("=" * 70)
    print("FUNCTION: coalescenodes @ 0x530A80")
    print("=" * 70)
    f = fn_at(0x530A80)
    if f:
        print(f"  name: {f.getName()}")
        print(f"  size: 0x{f.getBody().getNumAddresses():x} bytes")
        print(f"  signature: {f.getSignature()}")
        callers = list(f.getCallingFunctions(None))
        callees = list(f.getCalledFunctions(None))
        print(f"  callers ({len(callers)}):")
        for c in callers:
            print(f"    {c.getEntryPoint()} {c.getName()}")
        print(f"  callees ({len(callees)}):")
        for c in callees:
            print(f"    {c.getEntryPoint()} {c.getName()}")
    else:
        print("  NOT FOUND")
    print()

    # ─── 2. Decompile coalescenodes ──────────────────────────────────
    print("=" * 70)
    print("DECOMPILATION: coalescenodes")
    print("=" * 70)
    from ghidra.app.decompiler import DecompInterface
    from ghidra.util.task import ConsoleTaskMonitor
    di = DecompInterface()
    di.openProgram(program)
    if f:
        res = di.decompileFunction(f, 120, ConsoleTaskMonitor())
        if res and res.decompileCompleted():
            print(res.getDecompiledFunction().getC())
        else:
            print(f"  decompile failed: {res.getErrorMessage() if res else 'no result'}")
    print()

    # ─── 3. Xrefs to globals ─────────────────────────────────────────
    for label, va in [
        ("INTERFERENCEGRAPH @ 0x587E3C", 0x587E3C),
        ("0x587E74 (coalesce array)", 0x587E74),
        ("0x587C74 (coalesce header)", 0x587C74),
        ("N_IGNODES @ 0x587190", 0x587190),
    ]:
        print("=" * 70)
        print(f"XREFS: {label}")
        print("=" * 70)
        target = addr(va)
        refs = list(rm.getReferencesTo(target))
        for r in refs:
            from_addr = r.getFromAddress()
            from_va = int(str(from_addr), 16)
            fn = fn_containing(from_va)
            fn_name = fn.getName() if fn else "(no-fn)"
            fn_ep = fn.getEntryPoint() if fn else "?"
            ref_type = r.getReferenceType()
            op_idx = r.getOperandIndex()
            print(f"  {from_addr} {ref_type} op{op_idx} | fn={fn_name} @ {fn_ep}")
        print(f"  TOTAL: {len(refs)} refs")
        print()

    # ─── 4. Caller of coalescenodes — likely buildinterferencegraph ──
    if f:
        callers = list(f.getCallingFunctions(None))
        for caller in callers[:2]:
            print("=" * 70)
            print(f"DECOMPILATION: caller {caller.getName()} @ {caller.getEntryPoint()}")
            print("=" * 70)
            res = di.decompileFunction(caller, 120, ConsoleTaskMonitor())
            if res and res.decompileCompleted():
                # Truncate long output
                code = res.getDecompiledFunction().getC()
                if len(code) > 8000:
                    print(code[:4000])
                    print(f"\n... [truncated; {len(code)-8000} chars omitted] ...\n")
                    print(code[-4000:])
                else:
                    print(code)
            else:
                print(f"  decompile failed: {res.getErrorMessage() if res else 'no result'}")
            print()


if __name__ == "__main__":
    main()
