#!/usr/bin/env bash
# Run a single-TU compile under the patched mwcc_debug DLL and capture pcdump.txt.
#
# Usage:
#   tools/workflow/mwcc-debug-run.sh <path/to/source.c>
#
# Output:
#   build/mwcc_debug/<basename>.txt  (the full IR + codegen dump for the TU)
#
# Implementation notes:
#   * Backs up the stock lmgr326b.dll, swaps in the patched one, restores on exit.
#   * Uses ninja with -j1 to compile just the one TU so pcdump.txt isn't raced.
#   * pcdump.txt is written to the compiler's CWD (= repo root for ninja), so we
#     scoop it from there and move it into build/mwcc_debug/.
#   * Never run a parallel build while this script is active — the DLL swap is
#     repo-wide.

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <path/to/source.c>" >&2
  exit 64
fi

SRC="$1"
if [[ ! -f "${SRC}" ]]; then
  echo "Source file not found: ${SRC}" >&2
  exit 66
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPILER_DIR="${REPO_ROOT}/build/compilers/GC/1.2.5n"
DEBUG_DLL="${REPO_ROOT}/build/tools/mwcc_debug/lmgr326b.dll"
OUT_DIR="${REPO_ROOT}/build/mwcc_debug"
TU_BASE="$(basename "${SRC}" .c)"
OUT_FILE="${OUT_DIR}/${TU_BASE}.txt"
PCDUMP_LIVE="${REPO_ROOT}/pcdump.txt"

if [[ ! -f "${DEBUG_DLL}" ]]; then
  echo "Patched DLL missing — run: make -C tools/mwcc_debug all" >&2
  exit 1
fi

if [[ -f "${COMPILER_DIR}/lmgr326b.dll.stock" ]]; then
  echo "WARNING: stock DLL backup already exists." >&2
  echo "A previous run may have crashed without restoring. Run:" >&2
  echo "  tools/workflow/mwcc-debug-restore.sh" >&2
  echo "before re-running this script." >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
rm -f "${PCDUMP_LIVE}"

cleanup() {
  if [[ -f "${COMPILER_DIR}/lmgr326b.dll.stock" ]]; then
    mv -f "${COMPILER_DIR}/lmgr326b.dll.stock" "${COMPILER_DIR}/lmgr326b.dll"
    echo "Restored stock lmgr326b.dll"
  fi
}
trap cleanup EXIT

# Install patched DLL
cp "${COMPILER_DIR}/lmgr326b.dll" "${COMPILER_DIR}/lmgr326b.dll.stock"
cp "${DEBUG_DLL}" "${COMPILER_DIR}/lmgr326b.dll"
echo "Installed patched DLL"

# Resolve the .o ninja target for this source file
REL_SRC="${SRC#${REPO_ROOT}/}"
OBJ_TARGET="build/GALE01/${REL_SRC%.c}.o"

# Force re-compile by removing the .o first
rm -f "${REPO_ROOT}/${OBJ_TARGET}"

# Build single TU with no parallelism
cd "${REPO_ROOT}"
ninja -j1 "${OBJ_TARGET}"

if [[ ! -s "${PCDUMP_LIVE}" ]]; then
  echo "ERROR: pcdump.txt was not produced or is empty" >&2
  exit 1
fi

mv "${PCDUMP_LIVE}" "${OUT_FILE}"
echo "Dump written to ${OUT_FILE} ($(wc -c < "${OUT_FILE}") bytes)"
