#!/usr/bin/env bash
# Run mwcc-inspector on a single Melee TU on the remote Windows host.
#
# Usage:
#   tools/workflow/mwcc-inspect.sh <path/to/source.c>
#
# What it does:
#   1. Verifies the local repo is committed/pushed (the remote pulls from origin)
#   2. SSHes to ${MWCC_INSPECT_HOST:-nzxt-local}, git pulls the melee fork
#   3. Extracts the mwcc compile command for the TU from local ninja
#   4. Strips wine/wibo/sjiswrap wrappers (mwcceppc runs natively on Windows)
#   5. Runs mwcc-inspector with those args
#   6. Captures structured IR output to build/mwcc_inspect/<TU>.txt locally
#
# Requirements:
#   * SSH config alias for the Windows host (default: nzxt-local)
#   * On the host: mwcc-inspector built (see docs/mwcc-inspector.md for setup)
#   * On the host: melee fork cloned to %USERPROFILE%\code\melee
#   * Local repo: clean working tree on master (or pass MWCC_INSPECT_REMOTE_REF
#     to override the ref the remote checks out)

set -euo pipefail

if [[ $# -ne 1 ]]; then
  cat >&2 <<EOF
Usage: $0 <path/to/source.c>

Inspects the MWCC compilation of a single Melee TU on the remote Windows host
and captures structured IR output (ENodes, ObjObjects, Statements).

Env vars:
  MWCC_INSPECT_HOST       SSH alias of the Windows host (default: nzxt-local)
  MWCC_INSPECT_REMOTE_REF Git ref for the remote to check out (default: HEAD-on-origin/master)
  MWCC_INSPECT_REMOTE_DIR Remote melee fork path (default: /c/Users/mikes/code/melee)
  MWCC_INSPECT_CLI        Remote inspector CLI exe path (default: GC 1.0 build)
EOF
  exit 64
fi

SRC="$1"
if [[ ! -f "${SRC}" ]]; then
  echo "Source file not found: ${SRC}" >&2
  exit 66
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REL_SRC="${SRC#${REPO_ROOT}/}"
TU_BASE="$(basename "${SRC}" .c)"
OUT_DIR="${REPO_ROOT}/build/mwcc_inspect"
OUT_FILE="${OUT_DIR}/${TU_BASE}.txt"

HOST="${MWCC_INSPECT_HOST:-nzxt-local}"
REMOTE_DIR="${MWCC_INSPECT_REMOTE_DIR:-/c/Users/mikes/code/melee}"
REMOTE_CLI="${MWCC_INSPECT_CLI:-/c/Users/mikes/code/melee-decomp/mwcc-inspector-package/mwcc-inspector/MwccInspectorCLI/bin/GC 1.0 Debug/net8.0/MwccInspectorCLI.exe}"
REMOTE_MWCCEPPC="${REMOTE_DIR}/build/compilers/GC/1.2.5n/mwcceppc.exe"
# The remote's default ssh shell is cmd.exe; we need msys2 bash so /c/ paths work.
REMOTE_BASH="${MWCC_INSPECT_REMOTE_BASH:-C:\\devkitPro\\msys2\\usr\\bin\\bash.exe}"

# 1. Verify we're in a sensible local state (clean tree on master, or matches HEAD)
LOCAL_HEAD=$(git -C "${REPO_ROOT}" rev-parse HEAD)
LOCAL_BRANCH=$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD)
if ! git -C "${REPO_ROOT}" diff --quiet -- "${SRC}"; then
  echo "WARNING: ${SRC} has uncommitted local modifications." >&2
  echo "         The remote will compile the committed version at ${LOCAL_HEAD}." >&2
  echo "         To inspect uncommitted changes, commit + push first." >&2
fi

# 2. Get the compile command for this TU locally
RAW_CMD=$(cd "${REPO_ROOT}" && ninja -t commands "build/GALE01/${REL_SRC%.c}.o" 2>/dev/null | tail -1)
if [[ -z "${RAW_CMD}" ]]; then
  echo "ERROR: could not get compile command for ${REL_SRC%.c}.o" >&2
  echo "  Is the build configured? Try: python configure.py" >&2
  exit 1
fi

# 3. Strip macOS-side wrappers (wine, wibo, sjiswrap) — on Windows mwcceppc runs natively.
#    We need just the mwcceppc args (everything from -nowraplines onward, basically).
#    Approach: split off after "mwcceppc.exe " and prepend the remote inspector + remote mwcceppc.
MWCC_ARGS="${RAW_CMD#*mwcceppc.exe }"
# Strip trailing "&& transform_dep.py..." chain
MWCC_ARGS="${MWCC_ARGS%% && *}"
# Rewrite paths: anything relative to the local build/ dir is already a relative path,
# so it works as-is on the remote (which has the same layout). Output dir gets remapped
# below.

# 4. Remote command: cd to remote melee, fetch+checkout, run inspector
REMOTE_REF="${MWCC_INSPECT_REMOTE_REF:-${LOCAL_HEAD}}"

mkdir -p "${OUT_DIR}"

echo "[mwcc-inspect] Host: ${HOST}"
echo "[mwcc-inspect] Source: ${REL_SRC}"
echo "[mwcc-inspect] Remote ref: ${REMOTE_REF}"
echo "[mwcc-inspect] Running on ${HOST}…"

# The default ssh shell on Windows is cmd.exe; we explicitly invoke msys2 bash
# with `-s` so it reads the script from stdin. The heredoc below substitutes
# our local variables before the script is shipped. SSH delivers the heredoc
# content as bash's stdin — no nested-quoting nightmare.
ssh "${HOST}" "${REMOTE_BASH}" -s > "${OUT_FILE}" <<REMOTE_SCRIPT
set -euo pipefail
cd "${REMOTE_DIR}"
if ! git rev-parse --verify "${REMOTE_REF}" >/dev/null 2>&1; then
  git fetch origin --quiet
fi
git -c advice.detachedHead=false checkout --quiet "${REMOTE_REF}" 2>/dev/null
"${REMOTE_CLI}" "${REMOTE_MWCCEPPC}" ${MWCC_ARGS}
REMOTE_SCRIPT

echo "[mwcc-inspect] Output: ${OUT_FILE} ($(wc -c < "${OUT_FILE}") bytes)"
echo "[mwcc-inspect] Section summary:"
grep -E "^(====|FUNCTION:|LOCAL VARIABLES|STATEMENTS|Compilation finished)" "${OUT_FILE}" | head -20 || true
