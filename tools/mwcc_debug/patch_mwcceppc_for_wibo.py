#!/usr/bin/env python3
"""Patch a local mwcceppc.exe copy so wibo loads the real debug DLL.

wibo provides a built-in shim for LMGR326B.dll and ignores the DLL next to the
compiler. Renaming the import to another same-length DLL name avoids that shim.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


OLD_IMPORT = b"LMGR326B.dll"
NEW_IMPORT = b"MWDBG326.dll"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_exe", type=Path)
    parser.add_argument("output_exe", type=Path)
    parser.add_argument(
        "--dll",
        type=Path,
        default=Path(__file__).resolve().parent / "MWDBG326.dll",
        help="debug DLL to copy next to the patched compiler",
    )
    parser.add_argument(
        "--no-copy-dll",
        action="store_true",
        help="only patch the compiler executable",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.source_exe.resolve() == args.output_exe.resolve():
        raise SystemExit("refusing to patch in place; write a local compiler copy")

    data = args.source_exe.read_bytes()
    count = data.count(OLD_IMPORT)
    if count != 1:
        raise SystemExit(f"expected one {OLD_IMPORT!r} import, found {count}")

    args.output_exe.parent.mkdir(parents=True, exist_ok=True)
    args.output_exe.write_bytes(data.replace(OLD_IMPORT, NEW_IMPORT, 1))

    if not args.no_copy_dll:
        if not args.dll.exists():
            raise SystemExit(f"missing {args.dll}; run ./build_macos.sh first")
        shutil.copy2(args.dll, args.output_exe.parent / NEW_IMPORT.decode("ascii"))

    print(f"wrote {args.output_exe}")
    if not args.no_copy_dll:
        print(f"copied {args.output_exe.parent / NEW_IMPORT.decode('ascii')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
