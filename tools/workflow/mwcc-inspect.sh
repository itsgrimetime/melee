#!/usr/bin/env bash
# Run mwcc-inspector on a single Melee TU on the remote Windows host.
#
# Usage:
#   tools/workflow/mwcc-inspect.sh [--function fn_name] [--output out.txt] <path/to/source.c>
#
# What it does:
#   1. Chooses a remote base ref for the TU
#   2. SSHes to ${MWCC_INSPECT_HOST:-nzxt-local}, git pulls the melee fork
#   3. Extracts the mwcc compile command for the TU from local ninja
#   4. Strips wine/wibo/sjiswrap wrappers (mwcceppc runs natively on Windows)
#   5. Uploads uncommitted/candidate source to a unique remote temp file when needed
#   6. Runs mwcc-inspector with those args
#   7. Captures structured IR output to build/mwcc_inspect/<TU>.txt locally
#
# Requirements:
#   * SSH config alias for the Windows host (default: nzxt-local)
#   * On the host: mwcc-inspector built (see docs/mwcc-inspector.md for setup)
#   * On the host: melee fork cloned to %USERPROFILE%\code\melee
#   * Local repo: configured build/report.json so the TU compile command exists
#   * Pass MWCC_INSPECT_REMOTE_REF to override the remote base checkout

set -euo pipefail

usage() {
  printf '%s\n' \
    "Usage: $0 [--function fn_name] [--output out.txt] <path/to/source.c>" \
    "" \
    "Inspects the MWCC compilation of a single Melee TU on the remote Windows host" \
    "and captures structured IR output (ENodes, ObjObjects, Statements)." \
    "" \
    "Options:" \
    "  -f, --function FN        Function used to resolve the TU for candidate sources" \
    "  -o, --output PATH        Local output path (default: build/mwcc_inspect/<TU>.txt)" \
    "  -h, --help               Show this help" \
    "" \
    "Env vars:" \
    "  MWCC_INSPECT_HOST       SSH alias of the Windows host (default: nzxt-local)" \
    "  MWCC_INSPECT_REMOTE_REF Git ref for the remote to check out (default: local HEAD" \
    "                          for committed repo source; upstream or master for" \
    "                          uploaded candidate source)" \
    "  MWCC_INSPECT_REMOTE_DIR Remote melee fork path (default: /c/Users/mikes/code/melee)" \
    "  MWCC_INSPECT_CLI        Remote inspector CLI exe path (default: GC 1.0 build)" \
    "  MWCC_INSPECT_CONNECT_TIMEOUT SSH connect timeout in seconds (default: 10)" \
    >&2
}

FUNCTION=""
OUT_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--function)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a function name" >&2
        usage
        exit 64
      fi
      FUNCTION="$2"
      shift 2
      ;;
    -o|--output)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires an output path" >&2
        usage
        exit 64
      fi
      OUT_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "ERROR: unknown option: $1" >&2
      usage
      exit 64
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -ne 1 ]]; then
  usage
  exit 64
fi

SRC="$1"
if [[ ! -f "${SRC}" ]]; then
  echo "Source file not found: ${SRC}" >&2
  exit 66
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC_ABS="$(cd "$(dirname "${SRC}")" && pwd)/$(basename "${SRC}")"
if [[ "${SRC_ABS}" == "${REPO_ROOT}/"* ]]; then
  INPUT_REL_SRC="${SRC_ABS#${REPO_ROOT}/}"
else
  INPUT_REL_SRC=""
fi
if [[ "${INPUT_REL_SRC}" == src/*.c ]]; then
  REL_SRC="${INPUT_REL_SRC}"
else
  if [[ -z "${FUNCTION}" ]]; then
    echo "ERROR: --function is required when inspecting candidate source outside src/" >&2
    exit 64
  fi
  REL_SRC=$(python3 -c '
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1])
function = sys.argv[2]
report = repo / "build" / "GALE01" / "report.json"
if not report.exists():
    raise SystemExit(
        f"cannot resolve base TU for {function}: {report} is missing; "
        "run `python configure.py && ninja build/GALE01/report.json`"
    )
data = json.loads(report.read_text())
for unit in data.get("units", []):
    for fn in unit.get("functions", []):
        if fn.get("name") == function:
            name = str(unit.get("name", "")).removeprefix("main/")
            print(f"src/{name}.c")
            raise SystemExit(0)
raise SystemExit(f"cannot resolve base TU for {function}: function not in report.json")
' "${REPO_ROOT}" "${FUNCTION}")
fi
TU_BASE="$(basename "${REL_SRC}" .c)"
OUT_DIR="${REPO_ROOT}/build/mwcc_inspect"
if [[ -z "${OUT_FILE}" ]]; then
  if [[ "${INPUT_REL_SRC}" == "${REL_SRC}" ]]; then
    OUT_FILE="${OUT_DIR}/${TU_BASE}.txt"
  else
    CANDIDATE_STEM="$(basename "${SRC_ABS}" .c | tr -c 'A-Za-z0-9_.-' '-')"
    CANDIDATE_HASH="$(printf '%s\0%s' "${FUNCTION}" "${SRC_ABS}" | shasum -a 256 | awk '{print substr($1,1,12)}')"
    OUT_FILE="${OUT_DIR}/candidates/${CANDIDATE_STEM}-${CANDIDATE_HASH}.txt"
  fi
fi

HOST="${MWCC_INSPECT_HOST:-nzxt-local}"
SSH_CONNECT_TIMEOUT="${MWCC_INSPECT_CONNECT_TIMEOUT:-10}"
REMOTE_DIR="${MWCC_INSPECT_REMOTE_DIR:-/c/Users/mikes/code/melee}"
REMOTE_CLI="${MWCC_INSPECT_CLI:-/c/Users/mikes/code/melee-decomp/mwcc-inspector-package/mwcc-inspector/MwccInspectorCLI/bin/GC 1.0 Debug/net8.0/MwccInspectorCLI.exe}"
REMOTE_MWCCEPPC="${REMOTE_DIR}/build/compilers/GC/1.2.5n/mwcceppc.exe"
# The remote's default ssh shell is cmd.exe; we need msys2 bash so /c/ paths work.
REMOTE_BASH="${MWCC_INSPECT_REMOTE_BASH:-C:\\devkitPro\\msys2\\usr\\bin\\bash.exe}"

shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

remote_bash() {
  ssh -o "ConnectTimeout=${SSH_CONNECT_TIMEOUT}" "${HOST}" "${REMOTE_BASH}" -s
}

# 1. Verify whether the remote can use the checked-out source, or needs upload.
LOCAL_HEAD=$(git -C "${REPO_ROOT}" rev-parse HEAD)
LOCAL_UPSTREAM=$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
UPLOAD_SOURCE=0
if [[ "${INPUT_REL_SRC}" != "${REL_SRC}" ]]; then
  UPLOAD_SOURCE=1
elif [[ -n "$(git -C "${REPO_ROOT}" status --porcelain -- "${REL_SRC}")" ]]; then
  UPLOAD_SOURCE=1
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
if [[ -n "${MWCC_INSPECT_REMOTE_REF:-}" ]]; then
  REMOTE_REF="${MWCC_INSPECT_REMOTE_REF}"
elif [[ "${UPLOAD_SOURCE}" == "1" ]]; then
  if [[ -n "${LOCAL_UPSTREAM}" ]]; then
    REMOTE_REF="${LOCAL_UPSTREAM}"
  else
    REMOTE_REF="${MWCC_INSPECT_DEFAULT_REMOTE_REF:-master}"
  fi
else
  REMOTE_REF="${LOCAL_HEAD}"
fi

mkdir -p "$(dirname "${OUT_FILE}")"

echo "[mwcc-inspect] Host: ${HOST}"
echo "[mwcc-inspect] Source: ${REL_SRC}"
if [[ "${UPLOAD_SOURCE}" == "1" ]]; then
  echo "[mwcc-inspect] Candidate: ${SRC_ABS}"
fi
echo "[mwcc-inspect] Remote ref: ${REMOTE_REF}"

REMOTE_TMP=""
REMOTE_SOURCE="${REL_SRC}"
if [[ "${UPLOAD_SOURCE}" == "1" ]]; then
  echo "[mwcc-inspect] Preparing remote candidate source..."
  REMOTE_TMP=$(remote_bash <<REMOTE_PREP | tr -d '\r'
set -euo pipefail
mkdir -p $(shell_quote "${REMOTE_DIR}/build")
mktemp -d $(shell_quote "${REMOTE_DIR}/build/mwcc-inspect-${TU_BASE}.XXXXXX")
REMOTE_PREP
)
  REMOTE_SOURCE="${REMOTE_TMP}/${REL_SRC}"
  remote_bash <<REMOTE_MKDIR
set -euo pipefail
mkdir -p $(shell_quote "${REMOTE_TMP}/$(dirname "${REL_SRC}")")
REMOTE_MKDIR
  REMOTE_SOURCE_DIR="${REMOTE_DIR}/$(dirname "${REL_SRC}")"
  REMOTE_CANDIDATE_DIR="${REMOTE_TMP}/$(dirname "${REL_SRC}")"
  remote_bash <<REMOTE_HEADERS
set -euo pipefail
if [[ -d $(shell_quote "${REMOTE_SOURCE_DIR}") ]]; then
  find $(shell_quote "${REMOTE_SOURCE_DIR}") -maxdepth 1 -type f \\( -name '*.h' -o -name '*.inc' \\) -exec cp -p '{}' $(shell_quote "${REMOTE_CANDIDATE_DIR}/") \\;
fi
REMOTE_HEADERS
  UPLOAD_DELIM="MWCC_INSPECT_UPLOAD_$$_$(date +%s)"
  {
    printf 'set -euo pipefail\n'
    while IFS= read -r LOCAL_HEADER; do
      HEADER_NAME="$(basename "${LOCAL_HEADER}")"
      REPO_HEADER="${REPO_ROOT}/$(dirname "${REL_SRC}")/${HEADER_NAME}"
      if [[ -f "${REPO_HEADER}" ]] && cmp -s "${LOCAL_HEADER}" "${REPO_HEADER}"; then
        continue
      fi
      REMOTE_HEADER="${REMOTE_CANDIDATE_DIR}/${HEADER_NAME}"
      HEADER_DELIM="MWCC_INSPECT_HEADER_$$_$(printf '%s' "${HEADER_NAME}" | tr -c 'A-Za-z0-9_' '_')"
      printf 'cat > %s <<'"'"'%s'"'"'\n' "$(shell_quote "${REMOTE_HEADER}")" "${HEADER_DELIM}"
      cat "${LOCAL_HEADER}"
      printf '\n%s\n' "${HEADER_DELIM}"
    done < <(
      find "$(dirname "${SRC_ABS}")" -maxdepth 1 -type f \
        \( -name '*.h' -o -name '*.inc' \) | sort
    )
    printf 'cat > %s <<'"'"'%s'"'"'\n' "$(shell_quote "${REMOTE_SOURCE}")" "${UPLOAD_DELIM}"
    cat "${SRC_ABS}"
    printf '\n%s\n' "${UPLOAD_DELIM}"
  } | remote_bash
fi

echo "[mwcc-inspect] Running on ${HOST}…"

# The default ssh shell on Windows is cmd.exe; we explicitly invoke msys2 bash
# with `-s` so it reads the script from stdin. Build the script with printf so
# POSIX/coder login shells never get a chance to reinterpret bash's `-lc`
# argument or heredoc quoting.
TMP_OUT="$(mktemp "${OUT_FILE}.tmp.XXXXXX")"
TMP_ERR="$(mktemp "${OUT_FILE}.stderr.XXXXXX")"
set +e
{
  printf 'set -euo pipefail\n'
  printf 'cd %s\n' "$(shell_quote "${REMOTE_DIR}")"
  printf 'echo "[mwcc-inspect:remote] stage=checkout ref=%s" >&2\n' "$(shell_quote "${REMOTE_REF}")"
  printf 'if ! git rev-parse --verify %s >/dev/null 2>&1; then\n' "$(shell_quote "${REMOTE_REF}")"
  printf '  git fetch origin --quiet\n'
  printf 'fi\n'
  printf 'git -c advice.detachedHead=false checkout --quiet %s 2>/dev/null\n' "$(shell_quote "${REMOTE_REF}")"
  printf 'REMOTE_SOURCE=%s\n' "$(shell_quote "${REMOTE_SOURCE}")"
  printf 'REMOTE_TMP=%s\n' "$(shell_quote "${REMOTE_TMP}")"
  printf 'REMOTE_DIR=%s\n' "$(shell_quote "${REMOTE_DIR}")"
  printf 'if [[ -n "${REMOTE_TMP}" ]]; then\n'
  printf '  cleanup() { rm -rf "${REMOTE_TMP}"; }\n'
  printf '  trap cleanup EXIT\n'
  printf 'fi\n'
  printf 'REL_SRC_LOCAL=%s\n' "$(shell_quote "${REL_SRC}")"
  printf 'MWCC_ARGS_REMOTE=%s\n' "$(shell_quote "${MWCC_ARGS}")"
  printf 'if [[ -n "${REMOTE_TMP}" ]]; then\n'
  printf '  REMOTE_TMP_REL="${REMOTE_TMP#${REMOTE_DIR}/}"\n'
  printf '  MWCC_ARGS_REMOTE="${MWCC_ARGS_REMOTE/$REL_SRC_LOCAL/$REMOTE_SOURCE}"\n'
  printf '  MWCC_ARGS_REMOTE="-i ${REMOTE_TMP_REL}/src -i ${REMOTE_TMP}/src -i ${REMOTE_TMP_REL}/src/melee -i ${REMOTE_TMP}/src/melee ${MWCC_ARGS_REMOTE}"\n'
  printf '  MWCC_ARGS_REMOTE="${MWCC_ARGS_REMOTE/ -i src / -i src -i ${REMOTE_TMP_REL}/src -i ${REMOTE_TMP}/src }"\n'
  printf '  MWCC_ARGS_REMOTE="${MWCC_ARGS_REMOTE/ -i src\\/melee / -i src\\/melee -i ${REMOTE_TMP_REL}\\/src\\/melee -i ${REMOTE_TMP}\\/src\\/melee }"\n'
  printf 'fi\n'
  printf 'echo "[mwcc-inspect:remote] stage=inspector source=${REMOTE_SOURCE}" >&2\n'
  printf '%s %s ${MWCC_ARGS_REMOTE}\n' \
    "$(shell_quote "${REMOTE_CLI}")" \
    "$(shell_quote "${REMOTE_MWCCEPPC}")"
} | ssh -o "ConnectTimeout=${SSH_CONNECT_TIMEOUT}" "${HOST}" "${REMOTE_BASH}" -s > "${TMP_OUT}" 2> "${TMP_ERR}"
REMOTE_EXIT=$?
set -e

if [[ "${REMOTE_EXIT}" -ne 0 ]]; then
  echo "[mwcc-inspect] remote command failed (exit ${REMOTE_EXIT}) on ${HOST}" >&2
  echo "[mwcc-inspect] command: ssh -o ConnectTimeout=${SSH_CONNECT_TIMEOUT} ${HOST} ${REMOTE_BASH} -s" >&2
  echo "[mwcc-inspect] stage: remote checkout/compiler/inspector" >&2
  if [[ -s "${TMP_ERR}" ]]; then
    echo "[mwcc-inspect] remote stderr:" >&2
    sed -n '1,160p' "${TMP_ERR}" >&2
  else
    echo "[mwcc-inspect] remote stderr: <empty>" >&2
  fi
  if [[ -s "${TMP_OUT}" ]]; then
    mv "${TMP_OUT}" "${OUT_FILE}"
    echo "[mwcc-inspect] partial output preserved: ${OUT_FILE} ($(wc -c < "${OUT_FILE}") bytes)" >&2
  else
    rm -f "${OUT_FILE}" "${TMP_OUT}"
    echo "[mwcc-inspect] no structured output was produced; ${OUT_FILE} was not written" >&2
  fi
  rm -f "${TMP_ERR}"
  exit "${REMOTE_EXIT}"
fi

mv "${TMP_OUT}" "${OUT_FILE}"
rm -f "${TMP_ERR}"

echo "[mwcc-inspect] Output: ${OUT_FILE} ($(wc -c < "${OUT_FILE}") bytes)"
echo "[mwcc-inspect] Section summary:"
grep -E "^(====|FUNCTION:|LOCAL VARIABLES|STATEMENTS|Compilation finished)" "${OUT_FILE}" | head -20 || true
