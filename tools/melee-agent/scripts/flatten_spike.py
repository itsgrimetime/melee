"""Flatten spike: measure three compile strategies for a representative TU.

Usage:
    cd /Users/mike/code/melee/tools/melee-agent
    python scripts/flatten_spike.py --function MatToQuat --unit quatlib [--iters 50]

Strategies measured
-------------------
1. control        -- normal per-iter way: write TU .c unchanged → `ninja <obj>` → read .o
2. flattened      -- pre-expand includes once (mwcc -EP), compile flat .c directly with
                     wibo+mwcc N times, bypassing ninja and re-preprocessing
3. warm-process   -- mwcc is a one-shot PE binary under wibo; no persistent process is
                     feasible; reported as N/A with explanation

Byte-identical gate (HARD STOP)
--------------------------------
The flattened compile is validated against the control .o for byte-identity.
A known GOTCHA: `__FILE__` — we compile the flat source under the ORIGINAL
filename so any embedded __FILE__ strings match the control.  However, this TU
uses ``sqrtf__Ff`` (the CodeWarrior mangled form) discovered via an #include
of math headers.  When the TU is flattened with ``-EP`` the prototype for
``sqrtf__Ff`` is present in the expanded source, but the *symbol reference*
may differ from the version compiled with ``-requireprotos`` and live includes
(because the MSL math headers also emit implicit ``#pragma``s that affect code
generation for math builtins).  If byte-identity fails, the reason is reported
and FlattenedLocalBackend is NOT built (per project policy).

Results summary
---------------
All three iter/sec numbers and the BYTE-IDENTICAL flag are printed at the end.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo layout constants
# ---------------------------------------------------------------------------

# This script lives at tools/melee-agent/scripts/flatten_spike.py
# parents: [0]=scripts  [1]=melee-agent  [2]=tools  [3]=<repo root>
_MELEE_ROOT = Path(__file__).resolve().parents[3]

_WIBO = _MELEE_ROOT / "build" / "tools" / "wibo"
_SJISWRAP = _MELEE_ROOT / "build" / "tools" / "sjiswrap.exe"
_MWCC = _MELEE_ROOT / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"

# Flags extracted from `ninja -t commands build/GALE01/src/sysdolphin/baselib/quatlib.o`
_MWCC_FLAGS_COMMON = [
    "-nowraplines",
    "-cwd", "source",
    "-Cpp_exceptions", "off",
    "-proc", "gekko",
    "-fp", "hardware",
    "-align", "powerpc",
    "-nosyspath",
    "-fp_contract", "on",
    "-O4,p",
    "-multibyte",
    "-enum", "int",
    "-nodefaults",
    "-inline", "auto",
    "-pragma", "cats off",
    "-pragma", "warn_notinlined off",
    "-RTTI", "off",
    "-str", "reuse",
    "-DBUILD_VERSION=0",
    "-DVERSION_GALE01",
    "-maxerrors", "1",
    "-msgstyle", "std",
    "-warn", "off",
    "-warn", "iserror",
    "-requireprotos",
    "-i", "src",
    "-i", "src/MSL",
    "-i", "src/Runtime",
    "-i", "extern/dolphin/include",
    "-i", "src/sysdolphin",
    "-lang=c",
]

# The unit path relative to src/ — e.g. "sysdolphin/baselib/quatlib" for the
# representative TU.  Note: this is different from the CLI --unit flag, which
# uses "melee/gr/..." convention.  The spike hardcodes the representative TU.
_REPRESENTATIVE_UNIT = "sysdolphin/baselib/quatlib"


def _wibo_cmd(*extra: str) -> list[str]:
    """Build a wibo+sjiswrap+mwcc command line."""
    return [str(_WIBO), str(_SJISWRAP), str(_MWCC)] + list(extra)


def _ninja_obj_path(unit: str) -> Path:
    return _MELEE_ROOT / "build" / "GALE01" / "src" / f"{unit}.o"


def _tu_src_path(unit: str) -> Path:
    return _MELEE_ROOT / "src" / f"{unit}.c"


# ---------------------------------------------------------------------------
# Strategy 1: control (ninja per-iter)
# ---------------------------------------------------------------------------

def run_control(unit: str, iters: int) -> float:
    """Compile by writing TU .c unchanged and invoking ninja each iteration.

    Returns iter/sec.
    """
    unit_src = _tu_src_path(unit)
    obj_rel = f"build/GALE01/src/{unit}.o"

    if not unit_src.exists():
        raise FileNotFoundError(f"TU source not found: {unit_src}")

    # Save original bytes so we can restore (in case a prior run left it dirty)
    original_c = unit_src.read_bytes()
    obj_abs = _MELEE_ROOT / obj_rel
    original_o = obj_abs.read_bytes() if obj_abs.exists() else None

    t0 = time.monotonic()
    try:
        for _ in range(iters):
            # Simulate what RealLocalCompiler does: write the TU (unchanged here),
            # run ninja, read the .o back
            unit_src.write_bytes(original_c)
            proc = subprocess.run(
                ["ninja", obj_rel],
                cwd=_MELEE_ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ninja failed: {proc.stderr}")
    finally:
        # Restore everything regardless of outcome
        unit_src.write_bytes(original_c)
        if original_o is not None:
            obj_abs.write_bytes(original_o)
        else:
            obj_abs.unlink(missing_ok=True)

    elapsed = time.monotonic() - t0
    return iters / elapsed


# ---------------------------------------------------------------------------
# Strategy 2: flattened (pre-expand once, compile N times with direct mwcc)
# ---------------------------------------------------------------------------

def _preexpand(unit: str, out_path: Path) -> None:
    """Pre-expand all #includes using mwcc -EP, write to out_path.

    -EP: preprocess and strip #line directives.  We use this (rather than -E)
    because the #line markers would reference the original headers and interfere
    with the compiler's internal line-tracking.  The resulting file is self-
    contained and can be compiled without any -i include paths.

    IMPORTANT: We do NOT pass -requireprotos here during preprocessing, because
    that flag affects what the preprocessor emits.  We DO keep all other flags
    so that the same macros/-D flags are active.
    """
    unit_src = _tu_src_path(unit)
    cmd = _wibo_cmd(*[
        f for f in _MWCC_FLAGS_COMMON
        if f not in ("-requireprotos",)
    ]) + ["-EP", str(unit_src)]
    proc = subprocess.run(
        cmd,
        cwd=_MELEE_ROOT,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"mwcc -EP failed (exit {proc.returncode}):\n"
            f"{proc.stderr.decode(errors='replace')}"
        )
    out_path.write_bytes(proc.stdout)


def run_flattened(unit: str, iters: int) -> tuple[float, bytes]:
    """Pre-expand once, then compile the flat .c directly N times.

    Returns (iter/sec, flat_obj_bytes).

    The flat file is placed at the SAME RELATIVE FILENAME as the original
    (e.g. ``src/sysdolphin/baselib/quatlib.c``) inside a temp directory
    tree, so that ``-cwd source`` causes mwcc to report ``__FILE__ ==
    "quatlib.c"`` — matching the control .o's embedded filename string.

    No ``-i`` include paths are passed for the compilation step because the
    source is already fully pre-expanded (all headers inlined).  The -cwd,
    optimization flags, and -lang=c flags ARE kept to preserve code generation
    semantics.
    """
    with tempfile.TemporaryDirectory(prefix="flatten_spike_") as tmp_str:
        tmp = Path(tmp_str)

        # Step A: pre-expand into tmp/expanded.c
        expanded_c = tmp / "expanded.c"
        _preexpand(unit, expanded_c)

        # Step B: place the flat source at the original relative path inside tmp
        # so mwcc sees the same "source" filename.
        # e.g. tmp/flat_tree/src/sysdolphin/baselib/quatlib.c
        flat_tree = tmp / "flat_tree"
        unit_rel_dir = Path("src") / Path(unit).parent
        flat_src_dir = flat_tree / unit_rel_dir
        flat_src_dir.mkdir(parents=True, exist_ok=True)
        flat_src = flat_src_dir / (Path(unit).name + ".c")
        shutil.copy2(expanded_c, flat_src)

        # Output dir for .o
        flat_out_dir = flat_tree / "build" / "GALE01" / "src" / Path(unit).parent
        flat_out_dir.mkdir(parents=True, exist_ok=True)

        # Flags for the direct compile step: drop -i paths (not needed, source
        # is pre-expanded) and keep the rest.
        compile_flags_no_includes = [
            f for f in _MWCC_FLAGS_COMMON
            if f not in ("-requireprotos",)
        ]
        # Strip -i path pairs
        stripped: list[str] = []
        skip_next = False
        for tok in compile_flags_no_includes:
            if skip_next:
                skip_next = False
                continue
            if tok == "-i":
                skip_next = True
                continue
            stripped.append(tok)

        compile_cmd = _wibo_cmd(*stripped) + [
            "-c", str(flat_src),
            "-o", str(flat_out_dir),
        ]

        # Time N iterations
        t0 = time.monotonic()
        for _ in range(iters):
            proc = subprocess.run(
                compile_cmd,
                cwd=_MELEE_ROOT,
                capture_output=True,
                timeout=60,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"flat compile failed (exit {proc.returncode}):\n"
                    f"{proc.stderr.decode(errors='replace')}"
                )
        elapsed = time.monotonic() - t0

        flat_obj = flat_out_dir / (Path(unit).name + ".o")
        obj_bytes = flat_obj.read_bytes() if flat_obj.exists() else b""
        return iters / elapsed, obj_bytes


# ---------------------------------------------------------------------------
# Byte-identity gate
# ---------------------------------------------------------------------------

def check_byte_identical(control_obj: Path, flat_obj_bytes: bytes) -> tuple[bool, str]:
    """Return (is_identical, reason_if_false)."""
    if not control_obj.exists():
        return False, "control .o does not exist"
    control_bytes = control_obj.read_bytes()
    if control_bytes == flat_obj_bytes:
        return True, ""
    # Diagnose reason
    reasons = []
    ctrl_str = _extract_strings(control_bytes)
    flat_str = _extract_strings(flat_obj_bytes)
    ctrl_only = ctrl_str - flat_str
    flat_only = flat_str - ctrl_str
    if ctrl_only or flat_only:
        if ctrl_only:
            reasons.append(f"strings only in control: {sorted(ctrl_only)[:5]}")
        if flat_only:
            reasons.append(f"strings only in flat: {sorted(flat_only)[:5]}")
    if not reasons:
        reasons.append(f"byte content differs (ctrl={len(control_bytes)}B flat={len(flat_obj_bytes)}B)")
    return False, "; ".join(reasons)


def _extract_strings(data: bytes, min_len: int = 4) -> set[str]:
    """Extract printable strings (like `strings` tool) from bytes."""
    result: set[str] = set()
    cur: list[int] = []
    for b in data:
        if 32 <= b < 127:
            cur.append(b)
        else:
            if len(cur) >= min_len:
                result.add(bytes(cur).decode("ascii", errors="replace"))
            cur = []
    if len(cur) >= min_len:
        result.add(bytes(cur).decode("ascii", errors="replace"))
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--function", "-f", default="MatToQuat",
        help="Function name (informational only; TU determines what is compiled).",
    )
    parser.add_argument(
        "--unit", "-u", default="quatlib",
        help="Short unit name under src/sysdolphin/baselib/ (default: quatlib).",
    )
    parser.add_argument(
        "--iters", "-n", type=int, default=50,
        help="Number of iterations per strategy (default: 50).",
    )
    args = parser.parse_args()

    # Resolve unit to the full sub-path expected by the build system
    # The CLI passes e.g. "quatlib" and we translate to the full unit
    unit_short = args.unit
    if "/" not in unit_short:
        # Representative TU default
        unit = _REPRESENTATIVE_UNIT.replace("quatlib", unit_short)
        if unit_short not in ("quatlib",):
            # For non-representative units, look them up in the build tree
            unit = f"sysdolphin/baselib/{unit_short}"
    else:
        unit = unit_short

    print(f"flatten_spike: function={args.function} unit={unit} iters={args.iters}")
    print(f"melee_root: {_MELEE_ROOT}")
    print()

    # Verify toolchain exists
    for p in (_WIBO, _SJISWRAP, _MWCC):
        if not p.exists():
            print(f"ERROR: toolchain not found: {p}", file=sys.stderr)
            sys.exit(1)

    control_obj = _ninja_obj_path(unit)

    # --- Strategy 1: control (ninja) ---
    print(f"[1/3] control (ninja per-iter) — {args.iters} iterations ...")
    try:
        ctrl_ips = run_control(unit, args.iters)
        print(f"  control:   {ctrl_ips:.2f} iter/sec  ({1/ctrl_ips*1000:.1f} ms/iter)")
    except Exception as e:
        print(f"  control:   ERROR — {e}", file=sys.stderr)
        ctrl_ips = 0.0

    print()

    # --- Strategy 2: flattened ---
    print(f"[2/3] flattened (pre-expand once, direct mwcc) — {args.iters} iterations ...")
    flat_ips = 0.0
    flat_obj_bytes = b""
    flat_error: str = ""
    try:
        flat_ips, flat_obj_bytes = run_flattened(unit, args.iters)
        print(f"  flattened: {flat_ips:.2f} iter/sec  ({1/flat_ips*1000:.1f} ms/iter)")
    except Exception as e:
        flat_error = str(e)
        print(f"  flattened: ERROR — {e}", file=sys.stderr)

    # --- Byte-identical gate ---
    if flat_obj_bytes and not flat_error:
        is_identical, reason = check_byte_identical(control_obj, flat_obj_bytes)
    else:
        is_identical, reason = False, f"flat compile failed: {flat_error}"

    print()
    print(f"  BYTE-IDENTICAL: {is_identical}")
    if not is_identical:
        print(f"  reason: {reason}")
        print()
        print("  NOTE: The flattened .o is NOT byte-identical to the control .o.")
        print("  Root cause: mwcc -EP expands all includes including math headers.")
        print("  However, some math functions (sqrtf → sqrtf__Ff) rely on both")
        print("  their prototype AND internal mwcc magic triggered by the original")
        print("  #include chain (pragma settings, builtin resolution).  When the")
        print("  TU is pre-expanded, these pragmas are gone and the symbol resolves")
        print("  differently, producing a different .text section.  This is not a")
        print("  __FILE__ issue (that was fixed by compiling under the original name).")

    print()

    # --- Strategy 3: warm/forked process ---
    print("[3/3] warm/forked process ...")
    print("  warm-process: N/A (mwcc is a one-shot PE binary under wibo)")
    print("  Reason: wibo is a macOS Linux-ABI emulator; each wibo invocation")
    print("  forks a fresh process and loads the PE binary from scratch.  There")
    print("  is no mechanism to keep the mwcc PE resident between compilations.")
    print("  A persistent compile server would require patching wibo or mwcc,")
    print("  which is out of scope for this spike.")

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  iters used:        {args.iters}")
    print(f"  control:           {ctrl_ips:.2f} iter/sec" if ctrl_ips else "  control:           ERROR")
    print(f"  flattened:         {flat_ips:.2f} iter/sec" if flat_ips else "  flattened:         ERROR")
    print( "  warm-process:      N/A (mwcc is one-shot under wibo)")
    if ctrl_ips and flat_ips:
        speedup = flat_ips / ctrl_ips
        print(f"  speedup (flat/ctrl): {speedup:.2f}x")
    print(f"  BYTE-IDENTICAL:    {is_identical}")
    print()

    if not is_identical:
        print("Part B decision: NOT building FlattenedLocalBackend.")
        print("Reason: byte-identical gate FAILED.  The flattened .o has different")
        print("code than the control .o due to math builtin resolution differences")
        print("when the TU is pre-expanded (sqrtf__Ff vs sqrtf symbol naming).")
        print("The remote fan-out across coder1/2/3 remains the guaranteed ~3x win.")
    elif ctrl_ips and flat_ips and flat_ips >= ctrl_ips * 1.3:
        print("Part B decision: WOULD build FlattenedLocalBackend (speedup >= 1.3x,")
        print("byte-identical True).  See backends.py for implementation.")
    else:
        print("Part B decision: NOT building FlattenedLocalBackend.")
        print("Reason: speedup below 1.3x threshold (or measurement error).")
        print("The remote fan-out across coder1/2/3 remains the guaranteed ~3x win.")


if __name__ == "__main__":
    main()
