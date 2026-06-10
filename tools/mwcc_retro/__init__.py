"""mwcc-retro: retail-binary MWCC introspection via retrowin32 + gdb (issue #541).

See docs/superpowers/specs/2026-06-10-mwcc-retro-debugger-design.md.
"""
from pathlib import Path

RETROWIN32_REPO = "https://github.com/encounter/retrowin32"
RETROWIN32_BRANCH = "gdb-stub"
RETROWIN32_PIN = "11dbea5a68af21121511a6577a2d4a2f917da6dc"
CADMIC_REPO = "https://github.com/cadmic/mwcc-debugger"
CADMIC_PIN = "bad9cea2423bed957188c930086f9dabe669d30c"
GDB_STUB_PORT = 9001

PKG_ROOT = Path(__file__).resolve().parent
VENDOR_DIR = PKG_ROOT / "vendor"
TABLES_DIR = PKG_ROOT / "tables"
