#!/usr/bin/env bash
# Build the patched wibo binary from Luke Champine's melee-harness fork.
#
# The patches (in wibo/macros.S, loader.cpp, main.cpp, modules.h) fix two
# macOS-specific bugs that block mwcc_debug from working under stock wibo:
#   - LJMP64 trampoline SIGBUS on @NNN scratch temps (formatoperands)
#   - Nested-PE relocation crash (sjiswrap.exe → mwcceppc.exe)
#
# Installs into tools/mwcc_debug/bin/wibo. Re-run any time; source is
# cached for incremental rebuilds.

set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR="$ROOT/wibo_source"
BIN_DIR="$ROOT/bin"
HARNESS_REPO="https://github.com/lukechampine/melee-harness"

mkdir -p "$BIN_DIR"

# Pick a non-venv Python >=3.10 for the wibo trampoline generator. It
# self-bootstraps a `clang` venv only when it isn't already running inside
# one, so we must avoid the melee .venv.
pick_python() {
    local brew_py cand p ok
    if command -v brew >/dev/null 2>&1; then
        brew_py="$(brew --prefix 2>/dev/null)/bin/python3"
        [ -x "$brew_py" ] && { echo "$brew_py"; return 0; }
    fi
    for cand in python3.13 python3.12 python3.11 python3.10 python3; do
        p="$(command -v "$cand" 2>/dev/null)" || continue
        case "$p" in *"/.venv/"*|*"/venv/"*) continue ;; esac
        ok="$("$p" -c 'import sys;print(sys.version_info[:2]>=(3,10))' 2>/dev/null)" || continue
        [ "$ok" = "True" ] && { echo "$p"; return 0; }
    done
    return 1
}

if ! py="$(pick_python)"; then
    echo "error: no non-venv Python >=3.10 found for the wibo build" >&2
    exit 1
fi
echo "    using Python: $py"

# Fetch source. We only need the wibo subtree of melee-harness. Sparse
# checkout keeps the local clone small and skips the other vendored
# tools (objdiff, m2c, decomp-permuter) we don't build here.
if [ ! -d "$SOURCE_DIR/.git" ]; then
    echo "==> Cloning patched wibo source from $HARNESS_REPO..."
    rm -rf "$SOURCE_DIR"
    git clone --depth 1 --filter=blob:none --sparse \
        "$HARNESS_REPO" "$SOURCE_DIR"
    git -C "$SOURCE_DIR" sparse-checkout set wibo
else
    echo "==> Updating wibo source..."
    git -C "$SOURCE_DIR" pull --ff-only
fi

# Build.
echo "==> Building patched wibo..."
(
    cd "$SOURCE_DIR/wibo"
    env -u VIRTUAL_ENV -u PYTHONHOME cmake --preset release-macos \
        -DPython3_EXECUTABLE="$py"
    env -u VIRTUAL_ENV -u PYTHONHOME cmake --build --preset release-macos
)

cp "$SOURCE_DIR/wibo/build/release/wibo" "$BIN_DIR/wibo"
echo "==> Installed $BIN_DIR/wibo"
"$BIN_DIR/wibo" --version 2>&1 | head -1 || true
