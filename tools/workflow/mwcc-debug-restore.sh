#!/usr/bin/env bash
# Recover from a crashed mwcc-debug-run.sh that left the patched DLL installed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPILER_DIR="${REPO_ROOT}/build/compilers/GC/1.2.5n"
STOCK="${COMPILER_DIR}/lmgr326b.dll.stock"
LIVE="${COMPILER_DIR}/lmgr326b.dll"

if [[ ! -f "${STOCK}" ]]; then
  echo "No backup at ${STOCK} — nothing to restore." >&2
  echo "If you suspect the patched DLL is active, redownload the stock DLL" >&2
  echo "by removing the 1.2.5n compiler directory and re-running configure.py." >&2
  exit 0
fi

mv -f "${STOCK}" "${LIVE}"
echo "Restored stock lmgr326b.dll from ${STOCK}"
