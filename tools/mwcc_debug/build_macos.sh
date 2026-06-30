#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ZIG_VERSION=0.16.0
INDEX_URL=https://ziglang.org/download/index.json

case "$(uname -m)" in
    arm64)
        ZIG_PLATFORM=aarch64-macos
        ;;
    x86_64)
        ZIG_PLATFORM=x86_64-macos
        ;;
    *)
        echo "error: unsupported macOS architecture: $(uname -m)" >&2
        exit 1
        ;;
esac

TOOLS_DIR="$ROOT/tools"
INDEX_JSON="$TOOLS_DIR/zig-index.json"
ZIG_DIR="$TOOLS_DIR/zig-$ZIG_PLATFORM-$ZIG_VERSION"
ZIG="$ZIG_DIR/zig"

mkdir -p "$TOOLS_DIR"

if [ ! -x "$ZIG" ]; then
    echo "fetching Zig $ZIG_VERSION for $ZIG_PLATFORM"
    curl -L "$INDEX_URL" -o "$INDEX_JSON"

    ZIG_META=$(python3 - "$INDEX_JSON" "$ZIG_VERSION" "$ZIG_PLATFORM" <<'PY'
import json
import sys

index_path, version, platform = sys.argv[1:]
with open(index_path, "r", encoding="utf-8") as f:
    entry = json.load(f)[version][platform]
print(entry["tarball"])
print(entry["shasum"])
PY
)
    ZIG_TARBALL=$(printf '%s\n' "$ZIG_META" | sed -n '1p')
    ZIG_SHASUM=$(printf '%s\n' "$ZIG_META" | sed -n '2p')
    ZIG_ARCHIVE="$TOOLS_DIR/$(basename "$ZIG_TARBALL")"

    curl -L "$ZIG_TARBALL" -o "$ZIG_ARCHIVE"
    printf '%s  %s\n' "$ZIG_SHASUM" "$ZIG_ARCHIVE" | shasum -a 256 -c -
    tar -xf "$ZIG_ARCHIVE" -C "$TOOLS_DIR"
fi

"$ZIG" build-lib \
    -target x86-windows-gnu \
    -dynamic \
    -O ReleaseFast \
    -fstrip \
    -fno-compiler-rt \
    -fno-emit-implib \
    --subsystem console \
    --name lmgr326b \
    -fentry=DllMain@12 \
    -femit-bin="$ROOT/lmgr326b.dll" \
    "$ROOT/mwcc_debug.c" \
    "$ROOT/mwcc_debug.def" \
    -lkernel32

cp "$ROOT/lmgr326b.dll" "$ROOT/MWDBG326.dll"
echo "built $ROOT/lmgr326b.dll"
echo "built $ROOT/MWDBG326.dll"
