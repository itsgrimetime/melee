#!/usr/bin/env python3
"""Thin entrypoint — delegates to the function_taxonomy_inventory package.

This file exists for backward compatibility with CLI invocations
(python tools/function_taxonomy_inventory.py) and imports
(from tools.function_taxonomy_inventory import ...).
"""

import sys
from pathlib import Path

_sys_path_entry = str(Path(__file__).resolve().parent)
if _sys_path_entry not in sys.path:
    sys.path.insert(0, _sys_path_entry)

from function_taxonomy_inventory import *  # noqa: E402, F403
from function_taxonomy_inventory import main as _main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_main())
