#!/usr/bin/env python3
"""Slice one function's section out of a whole-TU mwcc_debug pcdump.

A `debug dump local` dump contains every function in the TU, each section
introduced by a line `Starting function <name>` and running until the next
such line. The Gate-1 corpus stores single-function dumps (LF line endings),
so this slices the requested function and normalizes CRLF->LF.

Match is by substring so an address ("80247510") finds the function whatever
its current source name (fn_80247510 / mnVibration_... ). Refuses ambiguous
or absent matches rather than guessing.

Usage:
    slice_pcdump_function.py <whole_dump.txt> <name-or-address> <out.txt>
"""
import sys


def slice_function(whole_text: str, key: str) -> str:
    lines = whole_text.splitlines()  # drops \r\n / \n -> bare lines
    # Prefer an exact "Starting function <key>" (handles a name that is a
    # substring of another, e.g. Create vs CreateStatRow); fall back to a
    # substring match so an address key still finds a renamed function.
    starts = [i for i, ln in enumerate(lines) if ln == f"Starting function {key}"]
    if not starts:
        starts = [
            i for i, ln in enumerate(lines)
            if ln.startswith("Starting function ") and key in ln
        ]
    if len(starts) != 1:
        matched = [lines[i] for i in starts]
        raise SystemExit(
            f"slice: {key!r} matched {len(starts)} functions (need exactly 1): "
            f"{matched}"
        )
    s = starts[0]
    e = len(lines)
    for j in range(s + 1, len(lines)):
        if lines[j].startswith("Starting function "):
            e = j
            break
    return "\n".join(lines[s:e]) + "\n"


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    whole_path, key, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(whole_path, "r") as f:
        whole = f.read()
    sliced = slice_function(whole, key)
    with open(out_path, "w") as f:
        f.write(sliced)
    header = sliced.split("\n", 1)[0]
    print(f"sliced {header!r} -> {out_path} ({sliced.count(chr(10))} lines)")


if __name__ == "__main__":
    main()
