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
#   * Reconfigures the build to use the patched wibo (build/tools/wibo) instead
#     of whatever wrapper was previously configured (e.g. wine). The original
#     build.ninja is saved and restored on exit. The patched wibo is required
#     because it calls DllMain on the licence DLL, which is what lets the patched
#     pcdump tracing run at all.
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
PATCHED_WIBO="${REPO_ROOT}/build/tools/wibo"
OUT_DIR="${REPO_ROOT}/build/mwcc_debug"
TU_BASE="$(basename "${SRC}" .c)"
OUT_FILE="${OUT_DIR}/${TU_BASE}.txt"
PCDUMP_LIVE="${REPO_ROOT}/pcdump.txt"
BUILD_NINJA="${REPO_ROOT}/build.ninja"
BUILD_NINJA_BACKUP="${REPO_ROOT}/build.ninja.mwcc_debug_backup"

if [[ ! -f "${DEBUG_DLL}" ]]; then
  echo "Patched DLL missing — run: make -C tools/mwcc_debug all" >&2
  exit 1
fi

if [[ ! -x "${PATCHED_WIBO}" ]]; then
  echo "Patched wibo missing at ${PATCHED_WIBO}" >&2
  echo "Build it via the Task 5a patch flow (see tools/mwcc_debug/)." >&2
  exit 1
fi

if [[ -f "${COMPILER_DIR}/lmgr326b.dll.stock" ]]; then
  echo "WARNING: stock DLL backup already exists." >&2
  echo "A previous run may have crashed without restoring. Run:" >&2
  echo "  tools/workflow/mwcc-debug-restore.sh" >&2
  echo "before re-running this script." >&2
  exit 1
fi

if [[ -f "${BUILD_NINJA_BACKUP}" ]]; then
  echo "WARNING: build.ninja backup already exists at ${BUILD_NINJA_BACKUP}" >&2
  echo "A previous run may have crashed without restoring. Inspect and either" >&2
  echo "restore it manually or re-run configure.py before re-running this script." >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
rm -f "${PCDUMP_LIVE}"

cleanup() {
  if [[ -f "${COMPILER_DIR}/lmgr326b.dll.stock" ]]; then
    mv -f "${COMPILER_DIR}/lmgr326b.dll.stock" "${COMPILER_DIR}/lmgr326b.dll"
    echo "Restored stock lmgr326b.dll"
  fi
  if [[ -f "${BUILD_NINJA_BACKUP}" ]]; then
    mv -f "${BUILD_NINJA_BACKUP}" "${BUILD_NINJA}"
    echo "Restored original build.ninja"
  fi
  # Delete the .o we built so the next normal build re-runs it with the stock
  # DLL and configured wrapper. Otherwise ninja would see it as up-to-date and
  # we'd ship a .o built under the patched toolchain.
  if [[ -n "${OBJ_TARGET:-}" ]]; then
    rm -f "${REPO_ROOT}/${OBJ_TARGET}"
  fi
}
trap cleanup EXIT

# Install patched DLL
cp "${COMPILER_DIR}/lmgr326b.dll" "${COMPILER_DIR}/lmgr326b.dll.stock"
cp "${DEBUG_DLL}" "${COMPILER_DIR}/lmgr326b.dll"
echo "Installed patched DLL"

# Reconfigure ninja to use the patched wibo (back up current build.ninja first)
cp "${BUILD_NINJA}" "${BUILD_NINJA_BACKUP}"
cd "${REPO_ROOT}"
python configure.py --wrapper "${PATCHED_WIBO}" >/dev/null
echo "Reconfigured build.ninja to use patched wibo"

# Resolve the .o ninja target for this source file
REL_SRC="${SRC#${REPO_ROOT}/}"
OBJ_TARGET="build/GALE01/${REL_SRC%.c}.o"

# Force re-compile by removing the .o first
rm -f "${REPO_ROOT}/${OBJ_TARGET}"

# Build single TU with no parallelism.
#
# We wrap ninja in a timeout because the patched DLL is currently known to
# cause mwcceppc to hang during codegen on non-trivial inputs (the trivial
# smoke test in tools/mwcc_debug/smoke_test.sh runs cleanly, but real Melee
# TUs hang partway through). pcdump.txt is written line-by-line during the
# hung run, so we can still salvage it after the timeout fires.
NINJA_TIMEOUT_SECS=${MWCC_DEBUG_NINJA_TIMEOUT:-60}
TIMEOUT_BIN=$(command -v gtimeout || command -v timeout || true)
if [[ -z "${TIMEOUT_BIN}" ]]; then
  echo "WARNING: no timeout/gtimeout binary found; running without timeout" >&2
  set +e
  ninja -j1 "${OBJ_TARGET}"
  NINJA_EXIT=$?
  set -e
else
  set +e
  "${TIMEOUT_BIN}" -k 5 "${NINJA_TIMEOUT_SECS}" ninja -j1 "${OBJ_TARGET}"
  NINJA_EXIT=$?
  set -e
fi

# Clean up any wibo processes the hung run leaked. macOS will eventually
# collect them but they linger as zombies until then; this is harmless but
# noisy if you re-run.
pkill -9 -f "${REPO_ROOT}/build/tools/wibo" 2>/dev/null || true

if [[ ! -s "${PCDUMP_LIVE}" ]]; then
  echo "ERROR: pcdump.txt was not produced or is empty (ninja exit ${NINJA_EXIT})" >&2
  exit 1
fi

mv "${PCDUMP_LIVE}" "${OUT_FILE}"
if [[ "${NINJA_EXIT}" -ne 0 ]]; then
  echo "WARNING: ninja failed/timed out (exit ${NINJA_EXIT}); dump may be partial" >&2
fi
echo "Dump written to ${OUT_FILE} ($(wc -c < "${OUT_FILE}") bytes)"
