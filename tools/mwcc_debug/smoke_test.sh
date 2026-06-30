#!/usr/bin/env bash
# Smoke test: verify the patched DLL produces a non-empty pcdump.txt.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPILER_DIR="${REPO_ROOT}/build/compilers/GC/1.2.5n"
DEBUG_DLL="${REPO_ROOT}/build/tools/mwcc_debug/lmgr326b.dll"
SMOKE_DIR="$(mktemp -d)"
PCDUMP="${SMOKE_DIR}/pcdump.txt"

cleanup() {
  if [[ -f "${COMPILER_DIR}/lmgr326b.dll.stock" ]]; then
    mv -f "${COMPILER_DIR}/lmgr326b.dll.stock" "${COMPILER_DIR}/lmgr326b.dll"
    echo "Restored stock lmgr326b.dll"
  fi
  rm -rf "${SMOKE_DIR}"
}
trap cleanup EXIT

cp "${COMPILER_DIR}/lmgr326b.dll" "${COMPILER_DIR}/lmgr326b.dll.stock"
cp "${DEBUG_DLL}" "${COMPILER_DIR}/lmgr326b.dll"
echo "Installed patched DLL"

cp "${REPO_ROOT}/tools/mwcc_debug/smoke_test.c" "${SMOKE_DIR}/"
cd "${SMOKE_DIR}"

"${REPO_ROOT}/build/tools/wibo" \
  "${COMPILER_DIR}/mwcceppc.exe" \
  -c -O4,p -proc gekko -enum int -fp hardware \
  -o smoke_test.o smoke_test.c

if [[ ! -s "${PCDUMP}" ]]; then
  echo "FAIL: pcdump.txt missing or empty in ${SMOKE_DIR}"
  ls -la "${SMOKE_DIR}"
  exit 1
fi

echo "PASS: pcdump.txt is $(wc -c < "${PCDUMP}") bytes"
echo "First 20 lines:"
head -20 "${PCDUMP}"
