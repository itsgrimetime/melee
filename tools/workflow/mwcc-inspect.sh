#!/usr/bin/env bash
# Run mwcc-inspector on a single Melee TU on the remote Windows host.
#
# Usage:
#   tools/workflow/mwcc-inspect.sh [options] <path/to/source.c>
#   tools/workflow/mwcc-inspect.sh --cancel INVOCATION_ID
#
# What it does:
#   1. Resolves an exact remote base commit for the TU
#   2. Extracts and validates the MWCC argv from local ninja
#   3. Snapshots uncommitted/candidate source and TU-local headers when needed
#   4. Launches one authenticated supervisor-owned remote command
#   5. Clones the exact commit into the invocation-private job directory
#   6. Applies hash-verified overlays and runs mwcc-inspector there
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
    "Usage: $0 [options] <path/to/source.c>" \
    "       $0 --cancel INVOCATION_ID [--cleanup-timeout SECONDS]" \
    "" \
    "Inspects the MWCC compilation of a single Melee TU on the remote Windows host" \
    "and captures structured IR output (ENodes, ObjObjects, Statements)." \
    "" \
    "Options:" \
    "  -f, --function FN        Function used to resolve the TU for candidate sources" \
    "  -o, --output PATH        Local output path (default: build/mwcc_inspect/<TU>.txt)" \
    "      --invocation-id ID   Unique safe token owning this inspector invocation" \
    "      --deadline-seconds N Remaining monotonic budget for this invocation" \
    "      --cancel ID          Cancel and await exactly this remote invocation" \
    "      --cleanup-timeout N  Bounded cancellation wait (default: 5 seconds)" \
    "  -h, --help               Show this help" \
    "" \
    "Env vars:" \
    "  MWCC_INSPECT_HOST       SSH alias of the Windows host (default: nzxt-local)" \
    "  MWCC_INSPECT_REMOTE_REF Git ref for the remote to check out (default: local HEAD" \
    "                          for committed repo source; upstream or master for" \
    "                          uploaded candidate source)" \
    "  MWCC_INSPECT_REMOTE_DIR Remote melee fork path (default: /c/Users/mikes/code/melee)" \
    "  MWCC_INSPECT_CLI        Remote inspector CLI exe path (default: GC 1.0 build)" \
    "  MWCC_INSPECT_FRESH_BASH Absolute remote Bash for final child handoff" \
    "  MWCC_INSPECT_CONNECT_TIMEOUT SSH connect timeout in seconds (default: 10)" \
    >&2
}

FUNCTION=""
OUT_FILE=""
INVOCATION_ID=""
DEADLINE_SECONDS=""
CANCEL_ID=""
CLEANUP_TIMEOUT="5"
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
    --invocation-id)
      [[ $# -ge 2 ]] || { echo "ERROR: $1 requires an ID" >&2; exit 64; }
      INVOCATION_ID="$2"
      shift 2
      ;;
    --deadline-seconds)
      [[ $# -ge 2 ]] || { echo "ERROR: $1 requires seconds" >&2; exit 64; }
      DEADLINE_SECONDS="$2"
      shift 2
      ;;
    --cancel)
      [[ $# -ge 2 ]] || { echo "ERROR: $1 requires an ID" >&2; exit 64; }
      CANCEL_ID="$2"
      shift 2
      ;;
    --cleanup-timeout)
      [[ $# -ge 2 ]] || { echo "ERROR: $1 requires seconds" >&2; exit 64; }
      CLEANUP_TIMEOUT="$2"
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

valid_invocation_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]
}

valid_positive_seconds() {
  [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]] && awk -v value="$1" 'BEGIN { exit !(value > 0) }'
}

monotonic_now() {
  perl -MTime::HiRes=clock_gettime,CLOCK_MONOTONIC \
    -e 'printf "%.9f\n", clock_gettime(CLOCK_MONOTONIC)'
}

remaining_budget() {
  awk -v budget="$1" -v started="$2" -v now="$(monotonic_now)" \
    'BEGIN { remaining = budget - (now - started); if (remaining < 0) remaining = 0; printf "%.6f\n", remaining }'
}

HOST="${MWCC_INSPECT_HOST:-nzxt-local}"
SSH_CONNECT_TIMEOUT="${MWCC_INSPECT_CONNECT_TIMEOUT:-10}"
REMOTE_DIR="${MWCC_INSPECT_REMOTE_DIR:-/c/Users/mikes/code/melee}"
REMOTE_CLI="${MWCC_INSPECT_CLI:-/c/Users/mikes/code/melee-decomp/mwcc-inspector-package/mwcc-inspector/MwccInspectorCLI/bin/GC 1.0 Debug/net8.0/MwccInspectorCLI.exe}"
REMOTE_MWCCEPPC="${REMOTE_DIR}/build/compilers/GC/1.2.5n/mwcceppc.exe"
REMOTE_BASH="${MWCC_INSPECT_REMOTE_BASH:-C:\\devkitPro\\msys2\\usr\\bin\\bash.exe}"
REMOTE_FRESH_BASH="${MWCC_INSPECT_FRESH_BASH:-/usr/bin/bash}"
if [[ "${REMOTE_FRESH_BASH}" != /* || "${REMOTE_FRESH_BASH}" == *$'\n'* || \
      "${REMOTE_FRESH_BASH}" == *$'\r'* || \
      ! "${REMOTE_FRESH_BASH}" =~ ^/[A-Za-z0-9._/+-]+$ ]]; then
  echo "ERROR: MWCC_INSPECT_FRESH_BASH must be a safe absolute path" >&2
  exit 64
fi
REMOTE_JOB_ROOT="${REMOTE_DIR}/build/mwcc-inspect-jobs"
LOCAL_SUPERVISOR="$(cd "$(dirname "$0")" && pwd)/mwcc-inspect-supervisor.sh"

shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

remote_bash() {
  ssh -o "AddressFamily=${MWCC_INSPECT_ADDRESS_FAMILY:-inet}" \
    -o "ConnectTimeout=${SSH_CONNECT_TIMEOUT}" "${HOST}" "${REMOTE_BASH}" -s
}

trusted_remote_supervisor() {
  local supervisor_b64 supervisor_sha
  supervisor_b64="$(base64 < "${LOCAL_SUPERVISOR}" | tr -d '\r\n')"
  supervisor_sha="$(shasum -a 256 "${LOCAL_SUPERVISOR}" | awk '{print $1}')"
  {
    printf 'set -euo pipefail\n'
    printf 'TRUSTED_SUPERVISOR_B64=%s\n' "$(shell_quote "${supervisor_b64}")"
    printf 'TRUSTED_SUPERVISOR_SHA256=%s\n' "$(shell_quote "${supervisor_sha}")"
    printf 'set --'
    local arg
    for arg in "$@"; do
      printf ' %s' "$(shell_quote "${arg}")"
    done
    printf '\n'
    cat <<'REMOTE_TRUSTED_SUPERVISOR'
trusted_supervisor="$(mktemp "${TMPDIR:-/tmp}/mwcc-inspect-supervisor.XXXXXX")"
cleanup_trusted_supervisor() { rm -f "${trusted_supervisor}"; }
trap cleanup_trusted_supervisor EXIT HUP INT TERM
if ! printf '%s' "${TRUSTED_SUPERVISOR_B64}" | base64 -d > "${trusted_supervisor}" 2>/dev/null; then
  printf '%s' "${TRUSTED_SUPERVISOR_B64}" | base64 -D > "${trusted_supervisor}"
fi
trusted_sha="$(sha256sum "${trusted_supervisor}" | awk '{print $1}')"
[[ "${trusted_sha}" == "${TRUSTED_SUPERVISOR_SHA256}" ]] || {
  echo "[mwcc-inspect:remote] trusted supervisor transport hash mismatch" >&2
  exit 125
}
chmod 700 "${trusted_supervisor}"
set +e
"${trusted_supervisor}" "$@" </dev/null
trusted_rc=$?
set -e
rm -f "${trusted_supervisor}"
trap - EXIT HUP INT TERM
exit "${trusted_rc}"
REMOTE_TRUSTED_SUPERVISOR
  } | remote_bash
}

cancel_remote_job() {
  local job_id="$1"
  local cleanup_timeout="$2"
  echo "[mwcc-inspect:remote] stage=cancel job=${job_id}" >&2
  trusted_remote_supervisor cancel-stored-token \
    --job-dir "${REMOTE_JOB_ROOT}/${job_id}" --job-id "${job_id}" \
    --wait-seconds "${cleanup_timeout}"
}

finalize_remote_success() {
  local job_id="$1"
  trusted_remote_supervisor finalize-stored-token \
    --job-dir "${REMOTE_JOB_ROOT}/${job_id}" --job-id "${job_id}"
}

if [[ -n "${CANCEL_ID}" ]]; then
  if [[ $# -ne 0 || -n "${INVOCATION_ID}" || -n "${DEADLINE_SECONDS}" ]]; then
    echo "ERROR: --cancel cannot be combined with a source invocation" >&2
    exit 64
  fi
  if ! valid_invocation_id "${CANCEL_ID}"; then
    echo "ERROR: invalid invocation ID: ${CANCEL_ID}" >&2
    exit 64
  fi
  if ! [[ "${CLEANUP_TIMEOUT}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: --cleanup-timeout must be a positive integer" >&2
    exit 64
  fi
  cancel_remote_job "${CANCEL_ID}" "${CLEANUP_TIMEOUT}"
  exit $?
fi

if [[ $# -ne 1 ]]; then usage; exit 64; fi
if [[ -z "${INVOCATION_ID}" ]]; then
  INVOCATION_ID="inspect-$(openssl rand -hex 12)"
fi
if ! valid_invocation_id "${INVOCATION_ID}"; then
  echo "ERROR: invalid invocation ID: ${INVOCATION_ID}" >&2
  exit 64
fi
DEADLINE_SECONDS="${DEADLINE_SECONDS:-${MWCC_INSPECT_TIMEOUT:-300}}"
if ! valid_positive_seconds "${DEADLINE_SECONDS}"; then
  echo "ERROR: --deadline-seconds must be positive" >&2
  exit 64
fi
STARTED_AT="$(monotonic_now)"

SRC="$1"
[[ -f "${SRC}" && ! -L "${SRC}" ]] || {
  echo "ERROR: source must be a regular non-symlink file: ${SRC}" >&2
  exit 66
}

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

# 1. Verify whether the remote can use the checked-out source, or needs upload.
LOCAL_HEAD=$(git -C "${REPO_ROOT}" rev-parse HEAD)
LOCAL_UPSTREAM=$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
UPLOAD_SOURCE=0
if [[ "${INPUT_REL_SRC}" != "${REL_SRC}" ]]; then
  UPLOAD_SOURCE=1
elif [[ -n "$(git -C "${REPO_ROOT}" status --porcelain -- "$(dirname "${REL_SRC}")")" ]]; then
  UPLOAD_SOURCE=1
fi

# 2. Get the compile command for this TU locally
RAW_CMD=$(cd "${REPO_ROOT}" && ninja -t commands "build/GALE01/${REL_SRC%.c}.o" 2>/dev/null | tail -1)
if [[ -z "${RAW_CMD}" ]]; then
  echo "ERROR: could not get compile command for ${REL_SRC%.c}.o" >&2
  echo "  Is the build configured? Try: python configure.py" >&2
  exit 1
fi

# 3. Resolve the exact remote commit before any SSH or input transport.
if [[ -n "${MWCC_INSPECT_REMOTE_REF:-}" ]]; then
  REMOTE_REF_INPUT="${MWCC_INSPECT_REMOTE_REF}"
elif [[ "${UPLOAD_SOURCE}" == "1" ]]; then
  if [[ -n "${LOCAL_UPSTREAM}" ]]; then
    REMOTE_REF_INPUT="${LOCAL_UPSTREAM}"
  else
    REMOTE_REF_INPUT="${MWCC_INSPECT_DEFAULT_REMOTE_REF:-master}"
  fi
else
  REMOTE_REF_INPUT="${LOCAL_HEAD}"
fi
if ! REMOTE_REF=$(git -C "${REPO_ROOT}" rev-parse --verify "${REMOTE_REF_INPUT}^{commit}" 2>/dev/null); then
  echo "ERROR: cannot resolve remote inspector ref locally: ${REMOTE_REF_INPUT}" >&2
  echo "  Fetch the ref locally or pass MWCC_INSPECT_REMOTE_REF as an exact available commit." >&2
  exit 1
fi
if [[ ! "${REMOTE_REF}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR: resolved remote inspector ref is not an exact lowercase commit: ${REMOTE_REF}" >&2
  exit 64
fi

valid_repo_relative_path() {
  local value="$1"
  [[ -n "${value}" && "${value}" != /* && "${value}" != *'\'* ]] || return 1
  [[ "${value}" != *$'\n'* && "${value}" != *$'\r'* ]] || return 1
  case "/${value}/" in *'/../'*|*'/./'*|*'//'*) return 1 ;; esac
  [[ "${value}" =~ ^[A-Za-z0-9][A-Za-z0-9._/+-]*$ ]]
}

valid_header_basename() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.+-]*\.([hH]|[iI][nN][cC])$ ]]
}

valid_repo_relative_path "${REL_SRC}" || {
  echo "ERROR: unsafe repository-relative source path: ${REL_SRC}" >&2
  exit 64
}
[[ "${REL_SRC}" == src/*.c ]] || {
  echo "ERROR: resolved source must be under src/ and end in .c: ${REL_SRC}" >&2
  exit 64
}

# 4. Parse the compile command into an argv vector and bind every mutable path
#    to the invocation-private checkout.
MWCC_ARGV=()
while IFS= read -r -d '' MWCC_ARG; do
  MWCC_ARGV+=("${MWCC_ARG}")
done < <(python3 - "${RAW_CMD}" <<'PY'
import shlex
import sys

tokens = shlex.split(sys.argv[1])
try:
    compiler = next(i for i, token in enumerate(tokens) if token.lower().endswith("mwcceppc.exe"))
except StopIteration:
    raise SystemExit("compile command does not contain mwcceppc.exe")
args = tokens[compiler + 1 :]
if "&&" in args:
    args = args[: args.index("&&")]
for arg in args:
    sys.stdout.buffer.write(arg.encode() + b"\0")
PY
)
[[ "${#MWCC_ARGV[@]}" -gt 0 ]] || {
  echo "ERROR: invalid empty mwcceppc argv" >&2
  exit 64
}
SOURCE_FLAGS=0
SOURCE_OPERANDS=0
OUTPUT_PAIRS=0
OUTPUT_REL=""
PRIVATE_INCLUDE_RELS=()
for ((ARG_INDEX = 0; ARG_INDEX < ${#MWCC_ARGV[@]}; ARG_INDEX++)); do
  case "${MWCC_ARGV[ARG_INDEX]}" in
    -c)
      SOURCE_FLAGS=$((SOURCE_FLAGS + 1))
      ((ARG_INDEX + 1 < ${#MWCC_ARGV[@]})) || {
        echo "ERROR: -c must be immediately followed by ${REL_SRC}" >&2
        exit 64
      }
      ARG_VALUE="${MWCC_ARGV[ARG_INDEX + 1]}"
      [[ "${ARG_VALUE}" == "${REL_SRC}" ]] || {
        echo "ERROR: -c must be immediately followed by ${REL_SRC}; got ${ARG_VALUE}" >&2
        exit 64
      }
      MWCC_ARGV[ARG_INDEX + 1]="__PRIVATE_SOURCE__"
      SOURCE_OPERANDS=$((SOURCE_OPERANDS + 1))
      ARG_INDEX=$((ARG_INDEX + 1))
      ;;
    -i)
      ((ARG_INDEX + 1 < ${#MWCC_ARGV[@]})) || { echo "ERROR: -i missing operand" >&2; exit 64; }
      ARG_VALUE="${MWCC_ARGV[ARG_INDEX + 1]}"
      if [[ "${ARG_VALUE}" != /* ]]; then
        valid_repo_relative_path "${ARG_VALUE}" || {
          echo "ERROR: unsafe relative compiler include: ${ARG_VALUE}" >&2
          exit 64
        }
        PRIVATE_INCLUDE_RELS+=("${ARG_VALUE}")
        MWCC_ARGV[ARG_INDEX + 1]="__PRIVATE_REPO__/${ARG_VALUE}"
      fi
      ARG_INDEX=$((ARG_INDEX + 1))
      ;;
    -o)
      ((ARG_INDEX + 1 < ${#MWCC_ARGV[@]})) || { echo "ERROR: -o missing operand" >&2; exit 64; }
      ARG_VALUE="${MWCC_ARGV[ARG_INDEX + 1]}"
      valid_repo_relative_path "${ARG_VALUE}" || {
        echo "ERROR: unsafe relative compiler output: ${ARG_VALUE}" >&2
        exit 64
      }
      MWCC_ARGV[ARG_INDEX + 1]="__PRIVATE_REPO__/${ARG_VALUE}"
      OUTPUT_REL="${ARG_VALUE}"
      OUTPUT_PAIRS=$((OUTPUT_PAIRS + 1))
      ARG_INDEX=$((ARG_INDEX + 1))
      ;;
    *)
      ARG_VALUE="${MWCC_ARGV[ARG_INDEX]}"
      if [[ "${ARG_VALUE}" != -* && ( "${ARG_VALUE}" == *.c || "${ARG_VALUE}" == *.C ) ]]; then
        echo "ERROR: unexpected additional source operand: ${ARG_VALUE}" >&2
        exit 64
      fi
      ;;
  esac
done
[[ "${SOURCE_FLAGS}" -eq 1 && "${SOURCE_OPERANDS}" -eq 1 && "${OUTPUT_PAIRS}" -eq 1 ]] || {
  echo "ERROR: compiler argv must contain exactly one -c flag, source, and -o operand" >&2
  exit 64
}

# 5. Snapshot uncommitted source/header inputs before SSH. Active TU headers
#    are the first overlay layer; explicit candidate-bundle headers win.
LOCAL_SNAPSHOT=""
LOCAL_OVERLAY_ARCHIVE=""
OVERLAY_SOURCES=()
OVERLAY_DESTS=()
OVERLAY_SHAS=()
OVERLAY_ARCHIVE_SHA=""
HEADER_NAMES=()
BASE_HEADER_NAMES=()
cleanup_local_snapshot() {
  [[ -z "${LOCAL_SNAPSHOT}" ]] || rm -rf "${LOCAL_SNAPSHOT}"
}
trap cleanup_local_snapshot EXIT HUP INT TERM

snapshot_regular_file() {
  local source="$1" destination="$2"
  [[ -f "${source}" && ! -L "${source}" ]] || {
    echo "ERROR: source must be a regular non-symlink file: ${source}" >&2
    return 66
  }
  mkdir -p "$(dirname "${destination}")"
  cp -p -- "${source}" "${destination}"
  [[ -f "${destination}" && ! -L "${destination}" ]]
}

record_header_overlay() {
  local source="$1" name lower existing index destination
  name="$(basename "${source}")"
  valid_header_basename "${name}" || {
    echo "ERROR: unsafe header basename: ${name}" >&2
    return 66
  }
  lower="$(printf '%s' "${name}" | tr '[:upper:]' '[:lower:]')"
  for existing in "${BASE_HEADER_NAMES[@]}"; do
    if [[ "$(printf '%s' "${existing}" | tr '[:upper:]' '[:lower:]')" == "${lower}" && "${existing}" != "${name}" ]]; then
      echo "ERROR: case-colliding header basename: ${existing} vs ${name}" >&2
      return 66
    fi
  done
  for ((index = 0; index < ${#HEADER_NAMES[@]}; index++)); do
    existing="${HEADER_NAMES[index]}"
    if [[ "$(printf '%s' "${existing}" | tr '[:upper:]' '[:lower:]')" == "${lower}" ]]; then
      [[ "${existing}" == "${name}" ]] || {
        echo "ERROR: case-colliding header basename: ${existing} vs ${name}" >&2
        return 66
      }
      destination="${LOCAL_SNAPSHOT}/$(dirname "${REL_SRC}")/${name}"
      snapshot_regular_file "${source}" "${destination}" || return $?
      OVERLAY_SOURCES[index]="${destination}"
      return 0
    fi
  done
  HEADER_NAMES+=("${name}")
  destination="${LOCAL_SNAPSHOT}/$(dirname "${REL_SRC}")/${name}"
  snapshot_regular_file "${source}" "${destination}" || return $?
  OVERLAY_SOURCES+=("${destination}")
  OVERLAY_DESTS+=("$(dirname "${REL_SRC}")/${name}")
}

scan_header_directory() {
  local directory="$1" label="$2" entry
  [[ -d "${directory}" ]] || return 0
  while IFS= read -r -d '' entry; do
    echo "ERROR: unsafe ${label} header: ${entry}" >&2
    return 66
  done < <(find -P "${directory}" -maxdepth 1 -type l \( -iname '*.h' -o -iname '*.inc' \) -print0)
  while IFS= read -r -d '' entry; do
    record_header_overlay "${entry}" || return $?
  done < <(find -P "${directory}" -maxdepth 1 -type f \( -iname '*.h' -o -iname '*.inc' \) -print0)
}

if [[ "${UPLOAD_SOURCE}" == "1" ]]; then
  LOCAL_SNAPSHOT="$(mktemp -d "${TMPDIR:-/tmp}/mwcc-inspect-input.XXXXXX")"
  chmod 700 "${LOCAL_SNAPSHOT}"
  while IFS= read -r BASE_HEADER; do
    [[ -z "${BASE_HEADER}" ]] || BASE_HEADER_NAMES+=("$(basename "${BASE_HEADER}")")
  done < <(
    git -C "${REPO_ROOT}" ls-tree --name-only \
      "${REMOTE_REF}:$(dirname "${REL_SRC}")" 2>/dev/null |
      grep -Ei '^[^/]+\.(h|inc)$' || true
  )
  scan_header_directory "${REPO_ROOT}/$(dirname "${REL_SRC}")" "TU" || exit $?
  scan_header_directory "$(dirname "${SRC_ABS}")" "candidate" || exit $?
  SNAPSHOT_SOURCE="${LOCAL_SNAPSHOT}/${REL_SRC}"
  snapshot_regular_file "${SRC_ABS}" "${SNAPSHOT_SOURCE}" || exit $?
  OVERLAY_SOURCES+=("${SNAPSHOT_SOURCE}")
  OVERLAY_DESTS+=("${REL_SRC}")
fi

if (( ${#OVERLAY_SOURCES[@]} > 0 )); then
  chmod 600 "${OVERLAY_SOURCES[@]}"
  OVERLAY_HASH_OUTPUT="$(shasum -a 256 "${OVERLAY_SOURCES[@]}")" || {
    echo "ERROR: could not hash overlay snapshot" >&2
    exit 66
  }
  while IFS= read -r OVERLAY_HASH_LINE; do
    OVERLAY_SHA="${OVERLAY_HASH_LINE%% *}"
    [[ "${OVERLAY_SHA}" =~ ^[0-9a-f]{64}$ ]] || {
      echo "ERROR: invalid overlay snapshot SHA-256" >&2
      exit 66
    }
    OVERLAY_SHAS+=("${OVERLAY_SHA}")
  done <<< "${OVERLAY_HASH_OUTPUT}"
  [[ "${#OVERLAY_SHAS[@]}" -eq "${#OVERLAY_SOURCES[@]}" ]] || {
    echo "ERROR: incomplete overlay snapshot hashes" >&2
    exit 66
  }
  LOCAL_OVERLAY_ARCHIVE="${LOCAL_SNAPSHOT}/.mwcc-inspect-overlays.tar"
  [[ ! -e "${LOCAL_OVERLAY_ARCHIVE}" && ! -L "${LOCAL_OVERLAY_ARCHIVE}" ]] || exit 66
  COPYFILE_DISABLE=1 tar --format=ustar -cf "${LOCAL_OVERLAY_ARCHIVE}" \
    -C "${LOCAL_SNAPSHOT}" "${OVERLAY_DESTS[@]}" || {
    echo "ERROR: could not archive overlay snapshot" >&2
    exit 66
  }
  chmod 600 "${LOCAL_OVERLAY_ARCHIVE}"
  [[ -f "${LOCAL_OVERLAY_ARCHIVE}" && ! -L "${LOCAL_OVERLAY_ARCHIVE}" ]] || exit 66
  OVERLAY_ARCHIVE_HASH_OUTPUT="$(shasum -a 256 "${LOCAL_OVERLAY_ARCHIVE}")" || exit 66
  OVERLAY_ARCHIVE_SHA="${OVERLAY_ARCHIVE_HASH_OUTPUT%% *}"
  [[ "${OVERLAY_ARCHIVE_SHA}" =~ ^[0-9a-f]{64}$ ]] || {
    echo "ERROR: invalid overlay archive SHA-256" >&2
    exit 66
  }
fi

mkdir -p "$(dirname "${OUT_FILE}")"

echo "[mwcc-inspect] Host: ${HOST}"
echo "[mwcc-inspect] Source: ${REL_SRC}"
if [[ "${UPLOAD_SOURCE}" == "1" ]]; then
  echo "[mwcc-inspect] Candidate: ${SRC_ABS}"
fi
echo "[mwcc-inspect] Remote ref: ${REMOTE_REF}"

REMOTE_JOB_DIR="${REMOTE_JOB_ROOT}/${INVOCATION_ID}"
REMOTE_REPO="${REMOTE_JOB_DIR}/repo"
JOB_TOKEN="$(openssl rand -hex 32)"
REMOTE_SOURCE="${REMOTE_REPO}/${REL_SRC}"
echo "[mwcc-inspect] Invocation: ${INVOCATION_ID}"
echo "[mwcc-inspect] Private repo: ${REMOTE_REPO}"

LOCAL_STAGE="${OUT_FILE}.stage.${INVOCATION_ID}"
LOCAL_ERR="${OUT_FILE}.stderr.${INVOCATION_ID}"
LOCAL_PAYLOAD=""
if ! (set -o noclobber; : > "${LOCAL_STAGE}") 2>/dev/null; then
  echo "ERROR: invocation staging path already exists for ${INVOCATION_ID}" >&2
  exit 73
fi
if ! (set -o noclobber; : > "${LOCAL_ERR}") 2>/dev/null; then
  rm -f "${LOCAL_STAGE}"
  echo "ERROR: invocation stderr path already exists for ${INVOCATION_ID}" >&2
  exit 73
fi
REMOTE_JOB_ACTIVE=0
REMOTE_JOB_TERMINAL_SUCCESS=0
local_cleanup() {
  local status=$?
  rm -f "${LOCAL_STAGE}" "${LOCAL_ERR}"
  [[ -z "${LOCAL_PAYLOAD}" ]] || rm -f -- "${LOCAL_PAYLOAD}"
  cleanup_local_snapshot
  if [[ "${REMOTE_JOB_TERMINAL_SUCCESS}" == "1" ]]; then
    set +e
    finalize_remote_success "${INVOCATION_ID}" >/dev/null 2>&1
    set -e
  elif [[ "${REMOTE_JOB_ACTIVE}" == "1" ]]; then
    set +e
    cancel_remote_job "${INVOCATION_ID}" "${CLEANUP_TIMEOUT}" >/dev/null 2>&1
    set -e
  fi
  return "${status}"
}
trap local_cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

REMAINING_SECONDS="$(remaining_budget "${DEADLINE_SECONDS}" "${STARTED_AT}")"
if ! valid_positive_seconds "${REMAINING_SECONDS}"; then
  echo "[mwcc-inspect] invocation ${INVOCATION_ID} timed out before remote launch" >&2
  exit 124
fi

echo "[mwcc-inspect] Running on ${HOST}…"

LOCAL_PAYLOAD="$(mktemp "${TMPDIR:-/tmp}/mwcc-inspect-payload.${INVOCATION_ID}.XXXXXX")"
chmod 600 "${LOCAL_PAYLOAD}"
[[ -f "${LOCAL_PAYLOAD}" && ! -L "${LOCAL_PAYLOAD}" ]] || {
  echo "ERROR: could not establish secure local launch payload" >&2
  exit 73
}
{
  printf 'set -euo pipefail\n'
  printf 'JOB_ID=%s\n' "$(shell_quote "${INVOCATION_ID}")"
  printf 'JOB_ROOT=%s\n' "$(shell_quote "${REMOTE_JOB_ROOT}")"
  printf 'JOB_DIR=%s\n' "$(shell_quote "${REMOTE_JOB_DIR}")"
  printf 'TOKEN=%s\n' "$(shell_quote "${JOB_TOKEN}")"
  printf 'DEADLINE_SECONDS=%s\n' "$(shell_quote "${REMAINING_SECONDS}")"
  printf 'remote_job_main() {\n'
  cat <<'REMOTE_INIT'
echo "[mwcc-inspect:remote] stage=job-init job=${JOB_ID}" >&2
umask 077
mkdir -p "${JOB_ROOT}"
if [[ -e "${JOB_DIR}" || -L "${JOB_DIR}" ]]; then
  echo "[mwcc-inspect:remote] invocation already exists: ${JOB_ID}" >&2
  exit 73
fi
create_private_job_directory() {
  local platform="${MWCC_INSPECT_PLATFORM:-$(uname -s)}"
  case "${platform}" in
    MSYS*|MINGW*|CYGWIN*)
      ;;
    *)
      mkdir -m 700 "${JOB_DIR}"
      return $?
      ;;
  esac

  local security_output
  if [[ -n "${MWCC_INSPECT_WINDOWS_ACL_INIT_CMD:-}" ]]; then
    security_output="$("${MWCC_INSPECT_WINDOWS_ACL_INIT_CMD}" "${JOB_DIR}")" || return 1
    security_output="${security_output//$'\r'/}"
    [[ "${security_output}" =~ ^MWCC_INSPECT_WINDOWS_ACL_READY:S-1-[0-9-]+$ ]]
    return $?
  fi

  local cygpath_cmd="${MWCC_INSPECT_CYGPATH:-cygpath}"
  local powershell_cmd="${MWCC_INSPECT_POWERSHELL:-powershell.exe}"
  local iconv_cmd="${MWCC_INSPECT_ICONV:-iconv}"
  local base64_cmd="${MWCC_INSPECT_BASE64:-base64}"
  command -v "${cygpath_cmd}" >/dev/null 2>&1 || return 1
  command -v "${powershell_cmd}" >/dev/null 2>&1 || return 1
  command -v "${iconv_cmd}" >/dev/null 2>&1 || return 1
  command -v "${base64_cmd}" >/dev/null 2>&1 || return 1

  local native_job_dir powershell_source encoded
  native_job_dir="$("${cygpath_cmd}" -w "${JOB_DIR}")" || return 1
  powershell_source="$(cat <<'POWERSHELL'
try {
  $ErrorActionPreference = 'Stop'
  $ProgressPreference = 'SilentlyContinue'
  $path = $env:MWCC_INSPECT_SECURITY_PATH
  if ([System.IO.Directory]::Exists($path) -or [System.IO.File]::Exists($path)) {
    throw 'job path already exists'
  }

  $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
  $acl = New-Object System.Security.AccessControl.DirectorySecurity
  $acl.SetOwner($currentSid)
  $acl.SetAccessRuleProtection($true, $false)
  $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $currentSid,
    [System.Security.AccessControl.FileSystemRights]::FullControl,
    ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
      [System.Security.AccessControl.InheritanceFlags]::ObjectInherit),
    [System.Security.AccessControl.PropagationFlags]::None,
    [System.Security.AccessControl.AccessControlType]::Allow
  )
  [void]$acl.AddAccessRule($rule)
  $item = [System.IO.Directory]::CreateDirectory($path, $acl)

  if (-not $item.Exists) { throw 'job path is not a directory' }
  if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'job path is a reparse point'
  }
  $createdAcl = $item.GetAccessControl()
  if ($createdAcl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $currentSid.Value) {
    throw 'job owner is not the current Windows SID'
  }
  if (-not $createdAcl.AreAccessRulesProtected) { throw 'job ACL inheritance is enabled' }
  $rules = @($createdAcl.GetAccessRules(
    $true,
    $true,
    [System.Security.Principal.SecurityIdentifier]
  ))
  if ($rules.Count -lt 1) { throw 'job ACL has no access rules' }
  $full = [System.Security.AccessControl.FileSystemRights]::FullControl
  $container = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit
  $object = [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
  foreach ($entry in $rules) {
    if ($entry.IsInherited) { throw 'job ACL contains an inherited rule' }
    if ($entry.IdentityReference.Value -ne $currentSid.Value) {
      throw "job ACL contains a foreign SID: $($entry.IdentityReference.Value)"
    }
    if ($entry.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) {
      throw 'job ACL contains a non-Allow rule'
    }
    if (($entry.FileSystemRights -band $full) -ne $full) {
      throw 'current Windows SID lacks FullControl'
    }
    if (
      ($entry.InheritanceFlags -band $container) -ne $container -or
      ($entry.InheritanceFlags -band $object) -ne $object
    ) {
      throw 'current Windows SID rule is not inheritable'
    }
  }
  Write-Output ('MWCC_INSPECT_WINDOWS_ACL_READY:' + $currentSid.Value)
  exit 0
} catch {
  [Console]::Error.WriteLine($_.Exception.ToString())
  exit 1
}
POWERSHELL
)"
  encoded="$(printf '%s' "${powershell_source}" | \
    "${iconv_cmd}" -f UTF-8 -t UTF-16LE | "${base64_cmd}" | tr -d '\r\n')" || return 1
  [[ -n "${encoded}" ]] || return 1
  local MWCC_INSPECT_SECURITY_PATH="${native_job_dir}"
  export MWCC_INSPECT_SECURITY_PATH
  security_output="$(MSYS2_ARG_CONV_EXCL='*' \
    "${powershell_cmd}" -NoProfile -NonInteractive \
      -EncodedCommand "${encoded}" </dev/null)" || return 1
  security_output="${security_output//$'\r'/}"
  [[ "${security_output}" =~ ^MWCC_INSPECT_WINDOWS_ACL_READY:S-1-[0-9-]+$ ]]
}
if ! create_private_job_directory; then
  echo "[mwcc-inspect:remote] failed to establish private Windows job ACL: ${JOB_ID}" >&2
  rmdir "${JOB_DIR}" 2>/dev/null || true
  exit 125
fi
[[ -d "${JOB_DIR}" && ! -L "${JOB_DIR}" ]] || exit 125
printf '%s\n' "${TOKEN}" > "${JOB_DIR}/token"
chmod 600 "${JOB_DIR}/token"
cat > "${JOB_DIR}/supervisor" <<'MWCC_INSPECT_SUPERVISOR_EOF'
REMOTE_INIT
  cat "${LOCAL_SUPERVISOR}"
  cat <<'REMOTE_INIT'
MWCC_INSPECT_SUPERVISOR_EOF
chmod 700 "${JOB_DIR}/supervisor"
REMOTE_INIT
  printf 'COMMAND="${JOB_DIR}/inspector-command"\n'
  printf 'cat > "${COMMAND}" <<'"'"'MWCC_INSPECT_COMMAND_EOF'"'"'\n'
  printf '#!/usr/bin/env bash\nset -euo pipefail\n'
  printf 'JOB_DIR=%s\n' "$(shell_quote "${REMOTE_JOB_DIR}")"
  printf 'REMOTE_DIR=%s\n' "$(shell_quote "${REMOTE_DIR}")"
  printf 'REMOTE_REPO=%s\n' "$(shell_quote "${REMOTE_REPO}")"
  printf 'REMOTE_REF=%s\n' "$(shell_quote "${REMOTE_REF}")"
  printf 'REL_SRC=%s\n' "$(shell_quote "${REL_SRC}")"
  printf 'OUTPUT_REL=%s\n' "$(shell_quote "${OUTPUT_REL}")"
  printf 'INVOCATION_ID=%s\n' "$(shell_quote "${INVOCATION_ID}")"
  cat <<'REMOTE_PRIVATE_COMMAND'
unsafe_private_path() {
  echo "[mwcc-inspect:remote] unsafe private repository path: $1" >&2
  exit 125
}

assert_not_reparse() {
  local path="$1" rc
  [[ -n "${MWCC_INSPECT_REPARSE_CHECK_CMD:-}" ]] || return 0
  if "${MWCC_INSPECT_REPARSE_CHECK_CMD}" "${path}"; then
    rc=0
  else
    rc=$?
  fi
  case "${rc}" in
    1) return 0 ;;
    0) unsafe_private_path "${path}" ;;
    *) unsafe_private_path "reparse check failed for ${path}" ;;
  esac
}

windows_reparse_batch_enabled() {
  local platform
  [[ -z "${MWCC_INSPECT_REPARSE_CHECK_CMD:-}" ]] || return 1
  platform="${MWCC_INSPECT_PLATFORM:-$(uname -s)}"
  case "${platform}" in
    MSYS*|MINGW*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

valid_batch_relative_path() {
  local relative="$1"
  [[ "${relative}" == "." ]] && return 0
  [[ -n "${relative}" && "${relative}" != /* && "${relative}" != *'\'* ]] || return 1
  [[ "${relative}" != *$'\n'* && "${relative}" != *$'\r'* && "${relative}" != *$'\t'* ]] || return 1
  case "/${relative}/" in *'/../'*|*'/./'*|*'//'*) return 1 ;; esac
  [[ "${relative}" =~ ^[A-Za-z0-9][A-Za-z0-9._/+-]*$ ]]
}

REPARSE_BATCH_PHASE=""
REPARSE_BATCH_ENTRIES=()

begin_reparse_batch() {
  REPARSE_BATCH_PHASE="$1"
  [[ "${REPARSE_BATCH_PHASE}" == "PRE" || "${REPARSE_BATCH_PHASE}" == "POST" ]] || \
    unsafe_private_path "invalid reparse batch phase"
  REPARSE_BATCH_ENTRIES=()
}

add_reparse_batch_entry() {
  local policy="$1" relative="$2" index entry existing_policy existing_relative merged
  case "${policy}" in
    required-dir|required-file|absent-or-file|absent-or-dir|must-absent) ;;
    *) unsafe_private_path "invalid reparse policy: ${policy}" ;;
  esac
  valid_batch_relative_path "${relative}" || unsafe_private_path "invalid reparse path: ${relative}"
  for ((index = 0; index < ${#REPARSE_BATCH_ENTRIES[@]}; index++)); do
    entry="${REPARSE_BATCH_ENTRIES[index]}"
    existing_policy="${entry%%$'\t'*}"
    existing_relative="${entry#*$'\t'}"
    [[ "${existing_relative}" == "${relative}" ]] || continue
    [[ "${existing_policy}" == "${policy}" ]] && return 0
    merged=""
    case "${existing_policy}:${policy}" in
      required-dir:absent-or-dir|absent-or-dir:required-dir) merged="required-dir" ;;
      required-file:absent-or-file|absent-or-file:required-file) merged="required-file" ;;
    esac
    [[ -n "${merged}" ]] || unsafe_private_path \
      "conflicting reparse policies for ${relative}: ${existing_policy}, ${policy}"
    REPARSE_BATCH_ENTRIES[index]="${merged}"$'\t'"${relative}"
    return 0
  done
  REPARSE_BATCH_ENTRIES+=("${policy}"$'\t'"${relative}")
}

add_reparse_path_with_ancestors() {
  local policy="$1" relative="$2" ancestor_policy="$3"
  local current="" component index
  local -a components
  add_reparse_batch_entry required-dir "."
  IFS='/' read -r -a components <<< "${relative}"
  for ((index = 0; index < ${#components[@]}; index++)); do
    component="${components[index]}"
    [[ "${component}" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ && \
       "${component}" != "." && "${component}" != ".." ]] || \
      unsafe_private_path "${relative}"
    [[ -z "${current}" ]] && current="${component}" || current="${current}/${component}"
    if (( index + 1 == ${#components[@]} )); then
      add_reparse_batch_entry "${policy}" "${current}"
    else
      add_reparse_batch_entry "${ancestor_policy}" "${current}"
    fi
  done
}

flush_reparse_batch() {
  local phase="$1" manifest manifest_sha expected receipt
  local native_repo native_manifest powershell_source encoded
  [[ "${phase}" == "${REPARSE_BATCH_PHASE}" ]] || unsafe_private_path "reparse phase mismatch"
  if ! windows_reparse_batch_enabled; then
    REPARSE_BATCH_ENTRIES=()
    REPARSE_BATCH_PHASE=""
    return 0
  fi
  expected="${#REPARSE_BATCH_ENTRIES[@]}"
  (( expected > 0 )) || unsafe_private_path "empty reparse batch: ${phase}"
  manifest="${JOB_DIR}/reparse-${phase}.manifest"
  [[ -d "${JOB_DIR}" && ! -L "${JOB_DIR}" && ! -e "${manifest}" && ! -L "${manifest}" ]] || \
    unsafe_private_path "unsafe reparse manifest: ${manifest}"
  (umask 077; : > "${manifest}")
  chmod 600 "${manifest}"
  [[ -f "${manifest}" && ! -L "${manifest}" ]] || unsafe_private_path "unsafe reparse manifest: ${manifest}"
  printf '%s\n' "${REPARSE_BATCH_ENTRIES[@]}" > "${manifest}"
  manifest_sha="$(sha256sum "${manifest}" | awk '{print $1}')" || \
    unsafe_private_path "cannot hash reparse manifest: ${phase}"
  [[ "${manifest_sha}" =~ ^[0-9a-f]{64}$ ]] || unsafe_private_path "invalid reparse manifest hash: ${phase}"
  native_repo="$("${MWCC_INSPECT_CYGPATH:-cygpath}" -w "${REMOTE_REPO}")" || \
    unsafe_private_path "cannot convert private repository path"
  native_manifest="$("${MWCC_INSPECT_CYGPATH:-cygpath}" -w "${manifest}")" || \
    unsafe_private_path "cannot convert reparse manifest path"
  powershell_source="$(cat <<'POWERSHELL'
try {
  $ErrorActionPreference = 'Stop'
  $ProgressPreference = 'SilentlyContinue'
  $manifestPath = $env:MWCC_INSPECT_REPARSE_MANIFEST
  $repoPath = $env:MWCC_INSPECT_REPARSE_REPO
  $phase = $env:MWCC_INSPECT_REPARSE_PHASE
  $expectedCount = [int]$env:MWCC_INSPECT_REPARSE_EXPECTED_COUNT
  if ($phase -ne 'PRE' -and $phase -ne 'POST') { throw 'invalid phase' }

  $manifestItem = Get-Item -LiteralPath $manifestPath -Force -ErrorAction Stop
  if (($manifestItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'manifest is a reparse point'
  }
  $manifestBytes = [System.IO.File]::ReadAllBytes($manifestItem.FullName)
  if ($manifestBytes.Count -eq 0 -or $manifestBytes[$manifestBytes.Count - 1] -ne 10) {
    throw 'manifest is empty or unterminated'
  }
  if (@($manifestBytes | Where-Object { $_ -gt 127 }).Count -ne 0) {
    throw 'manifest is not ASCII'
  }
  $sha256 = [System.Security.Cryptography.SHA256]::Create()
  try {
    $computedSha = ([System.BitConverter]::ToString($sha256.ComputeHash($manifestBytes))).Replace('-', '').ToLowerInvariant()
  } finally {
    $sha256.Dispose()
  }
  $text = [System.Text.Encoding]::ASCII.GetString($manifestBytes)
  $lines = @($text.Substring(0, $text.Length - 1).Split("`n"))
  if ($lines.Count -ne $expectedCount) { throw 'manifest row count mismatch' }

  $repoItem = Get-Item -LiteralPath $repoPath -Force -ErrorAction Stop
  if (-not $repoItem.PSIsContainer) { throw 'repository root is not a directory' }
  if (($repoItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'repository root is a reparse point'
  }
  $repoFull = [System.IO.Path]::GetFullPath($repoItem.FullName).TrimEnd('\', '/')
  $repoPrefix = $repoFull + [System.IO.Path]::DirectorySeparatorChar
  $seenRelative = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

  foreach ($line in $lines) {
    if ($line.Contains("`r") -or $line.IndexOf("`t") -le 0 -or
        $line.IndexOf("`t") -ne $line.LastIndexOf("`t")) {
      throw 'invalid manifest row'
    }
    $tab = $line.IndexOf("`t")
    $policy = $line.Substring(0, $tab)
    $relative = $line.Substring($tab + 1)
    if (-not $seenRelative.Add($relative)) { throw 'case-insensitive duplicate manifest path' }
    if ($policy -notin @('required-dir', 'required-file', 'absent-or-file', 'absent-or-dir', 'must-absent')) {
      throw 'invalid manifest policy'
    }
    if ($relative -ne '.') {
      if ($relative -notmatch '^[A-Za-z0-9][A-Za-z0-9._/+\-]*$' -or
          $relative.Contains('\') -or [System.IO.Path]::IsPathRooted($relative)) {
        throw 'invalid repository-relative path'
      }
      foreach ($component in $relative.Split('/')) {
        if ($component -eq '' -or $component -eq '.' -or $component -eq '..' -or
            $component -notmatch '^[A-Za-z0-9][A-Za-z0-9._+\-]*$') {
          throw 'invalid repository-relative component'
        }
      }
      $candidate = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::Combine($repoFull, $relative.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
      )
    } else {
      $candidate = $repoFull
    }
    if (-not $candidate.Equals($repoFull, [System.StringComparison]::OrdinalIgnoreCase) -and
        -not $candidate.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw 'path escaped repository root'
    }

    $missing = $false
    try {
      $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
    } catch {
      if ($_.Exception -is [System.Management.Automation.ItemNotFoundException]) {
        $missing = $true
      } else {
        throw
      }
    }
    if ($missing) {
      if ($policy -notin @('absent-or-file', 'absent-or-dir', 'must-absent')) {
        throw 'required path is absent'
      }
      continue
    }
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw 'path is a reparse point'
    }
    switch ($policy) {
      'required-dir' { if (-not $item.PSIsContainer) { throw 'path is not a directory' } }
      'absent-or-dir' { if (-not $item.PSIsContainer) { throw 'path is not a directory' } }
      'required-file' { if ($item.PSIsContainer) { throw 'path is not a regular file' } }
      'absent-or-file' { if ($item.PSIsContainer) { throw 'path is not a regular file' } }
      'must-absent' { throw 'temporary path is present' }
    }
  }
  Write-Output ("MWCC_INSPECT_REPARSE_BATCH_OK:{0}:{1}:{2}" -f $phase, $lines.Count, $computedSha)
  exit 0
} catch {
  Write-Error $_
  exit 125
}
POWERSHELL
)" || unsafe_private_path "cannot build reparse batch probe"
  encoded="$(printf '%s' "${powershell_source}" | "${MWCC_INSPECT_ICONV:-iconv}" -f UTF-8 -t UTF-16LE | "${MWCC_INSPECT_BASE64:-base64}" | tr -d '\r\n')" || \
    unsafe_private_path "cannot encode reparse batch probe"
  [[ -n "${encoded}" ]] || unsafe_private_path "cannot encode reparse batch probe"
  if receipt="$(MWCC_INSPECT_REPARSE_MANIFEST="${native_manifest}" \
      MWCC_INSPECT_REPARSE_REPO="${native_repo}" \
      MWCC_INSPECT_REPARSE_PHASE="${phase}" \
      MWCC_INSPECT_REPARSE_EXPECTED_COUNT="${expected}" \
      MWCC_INSPECT_REPARSE_MANIFEST_SHA="${manifest_sha}" \
      MSYS2_ARG_CONV_EXCL='*' \
      "${MWCC_INSPECT_POWERSHELL:-powershell.exe}" -NoProfile -NonInteractive \
        -EncodedCommand "${encoded}" </dev/null)"; then
    receipt="${receipt//$'\r'/}"
  else
    unsafe_private_path "reparse batch failed: ${phase}"
  fi
  [[ "${receipt}" == "MWCC_INSPECT_REPARSE_BATCH_OK:${phase}:${expected}:${manifest_sha}" ]] || \
    unsafe_private_path "reparse batch failed: ${phase} receipt"
  rm -f -- "${manifest}"
  REPARSE_BATCH_ENTRIES=()
  REPARSE_BATCH_PHASE=""
}

assert_safe_directory() {
  local path="$1"
  [[ -d "${path}" && ! -L "${path}" ]] || unsafe_private_path "${path}"
  assert_not_reparse "${path}"
}

safe_mkdir_parents() {
  local root="$1" relative="$2" current component
  local -a components
  assert_safe_directory "${root}"
  [[ "${relative}" == "." || -z "${relative}" ]] && return 0
  IFS='/' read -r -a components <<< "${relative}"
  current="${root}"
  for component in "${components[@]}"; do
    [[ "${component}" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ && "${component}" != "." && "${component}" != ".." ]] || \
      unsafe_private_path "${relative}"
    current="${current}/${component}"
    if [[ -e "${current}" || -L "${current}" ]]; then
      assert_safe_directory "${current}"
    else
      mkdir -- "${current}"
      assert_safe_directory "${current}"
    fi
  done
}

assert_safe_file() {
  local root="$1" relative="$2" path
  safe_mkdir_parents "${root}" "$(dirname "${relative}")"
  path="${root}/${relative}"
  [[ -f "${path}" && ! -L "${path}" ]] || unsafe_private_path "${path}"
  assert_not_reparse "${path}"
}

assert_safe_existing_directory_path() {
  local root="$1" relative="$2" current component
  local -a components
  assert_safe_directory "${root}"
  IFS='/' read -r -a components <<< "${relative}"
  current="${root}"
  for component in "${components[@]}"; do
    [[ "${component}" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ && "${component}" != "." && "${component}" != ".." ]] || \
      unsafe_private_path "${relative}"
    current="${current}/${component}"
    assert_safe_directory "${current}"
  done
}

assert_safe_output_directory_path() {
  local root="$1" relative="$2"
  safe_mkdir_parents "${root}" "${relative}"
  assert_safe_directory "${root}/${relative}"
}

preflight_overlay_destination() {
  local relative="$1" current="${REMOTE_REPO}" component index
  local -a components
  assert_safe_directory "${REMOTE_REPO}"
  IFS='/' read -r -a components <<< "${relative}"
  for ((index = 0; index < ${#components[@]}; index++)); do
    component="${components[index]}"
    [[ "${component}" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ && \
       "${component}" != "." && "${component}" != ".." ]] || \
      unsafe_private_path "${relative}"
    current="${current}/${component}"
    if (( index + 1 == ${#components[@]} )); then
      if [[ -e "${current}" || -L "${current}" ]]; then
        [[ -f "${current}" && ! -L "${current}" ]] || unsafe_private_path "${current}"
        assert_not_reparse "${current}"
      fi
    else
      assert_safe_directory "${current}"
    fi
  done
}

assert_safe_overlay_file() {
  local relative="$1" path="${REMOTE_REPO}/$1"
  [[ -f "${path}" && ! -L "${path}" ]] || unsafe_private_path "${path}"
  assert_not_reparse "${path}"
}

prepare_overlay_checksum_manifest() {
  local expected_count="$1" line count=0 relative
  OVERLAY_CHECKSUM_MANIFEST="${JOB_DIR}/overlay-sha256.manifest"
  [[ ! -e "${OVERLAY_CHECKSUM_MANIFEST}" && ! -L "${OVERLAY_CHECKSUM_MANIFEST}" ]] || \
    unsafe_private_path "${OVERLAY_CHECKSUM_MANIFEST}"
  (umask 077; : > "${OVERLAY_CHECKSUM_MANIFEST}")
  while IFS= read -r line; do
    [[ "${line}" =~ ^[0-9a-f]{64}[[:space:]][[:space:]][A-Za-z0-9][A-Za-z0-9._/+-]*$ ]] || \
      unsafe_private_path "invalid overlay checksum manifest"
    relative="${line#*  }"
    valid_batch_relative_path "${relative}" || unsafe_private_path "invalid overlay checksum path"
    printf '%s\n' "${line}" >> "${OVERLAY_CHECKSUM_MANIFEST}"
    count=$((count + 1))
  done
  [[ "${count}" -eq "${expected_count}" ]] || unsafe_private_path "overlay checksum count mismatch"
  chmod 600 "${OVERLAY_CHECKSUM_MANIFEST}"
  [[ -f "${OVERLAY_CHECKSUM_MANIFEST}" && ! -L "${OVERLAY_CHECKSUM_MANIFEST}" ]] || \
    unsafe_private_path "${OVERLAY_CHECKSUM_MANIFEST}"
}

apply_overlay_archive() {
  local expected_archive_sha="$1" expected_count="$2"
  local archive="${JOB_DIR}/overlays.${INVOCATION_ID}.tar"
  local encoded="${JOB_DIR}/overlays.${INVOCATION_ID}.tar.base64"
  local line archive_hash_output actual_archive_sha members verbose member_count=0
  local expected_members="" relative
  [[ "${expected_archive_sha}" =~ ^[0-9a-f]{64}$ && "${expected_count}" -gt 0 ]] || \
    unsafe_private_path "invalid overlay archive metadata"
  [[ -f "${OVERLAY_CHECKSUM_MANIFEST}" && ! -L "${OVERLAY_CHECKSUM_MANIFEST}" ]] || \
    unsafe_private_path "${OVERLAY_CHECKSUM_MANIFEST}"
  [[ ! -e "${archive}" && ! -L "${archive}" && ! -e "${encoded}" && ! -L "${encoded}" ]] || \
    unsafe_private_path "overlay archive staging exists"
  (umask 077; : > "${encoded}")
  while IFS= read -r line; do
    [[ "${line}" =~ ^[A-Za-z0-9+/=]+$ ]] || unsafe_private_path "invalid overlay archive encoding"
    printf '%s' "${line}" >> "${encoded}"
  done
  chmod 600 "${encoded}"
  [[ -f "${encoded}" && ! -L "${encoded}" ]] || unsafe_private_path "${encoded}"
  if ! MWCC_INSPECT_OVERLAY_DECODE=1 "${MWCC_INSPECT_BASE64:-base64}" -d < "${encoded}" > "${archive}" 2>/dev/null; then
    rm -f -- "${archive}"
    MWCC_INSPECT_OVERLAY_DECODE=1 "${MWCC_INSPECT_BASE64:-base64}" -D < "${encoded}" > "${archive}" 2>/dev/null || {
      rm -f -- "${archive}" "${encoded}"
      echo "[mwcc-inspect:remote] overlay archive decode failed" >&2
      exit 125
    }
  fi
  rm -f -- "${encoded}"
  chmod 600 "${archive}"
  [[ -f "${archive}" && ! -L "${archive}" ]] || unsafe_private_path "${archive}"
  archive_hash_output="$(sha256sum "${archive}")" || unsafe_private_path "cannot hash overlay archive"
  actual_archive_sha="${archive_hash_output%% *}"
  if [[ "${actual_archive_sha}" != "${expected_archive_sha}" ]]; then
    echo "[mwcc-inspect:remote] overlay archive SHA-256 mismatch" >&2
    exit 125
  fi
  while IFS= read -r line; do
    relative="${line#*  }"
    [[ -z "${expected_members}" ]] && expected_members="${relative}" || \
      expected_members="${expected_members}"$'\n'"${relative}"
  done < "${OVERLAY_CHECKSUM_MANIFEST}"
  members="$(tar -tf "${archive}")" || unsafe_private_path "cannot list overlay archive"
  members="${members//$'\r'/}"
  [[ "${members}" == "${expected_members}" ]] || unsafe_private_path "overlay archive member mismatch"
  verbose="$(tar -tvf "${archive}")" || unsafe_private_path "cannot inspect overlay archive"
  while IFS= read -r line; do
    [[ "${line:0:1}" == "-" ]] || unsafe_private_path "overlay archive contains non-regular member"
    member_count=$((member_count + 1))
  done <<< "${verbose}"
  [[ "${member_count}" -eq "${expected_count}" ]] || unsafe_private_path "overlay archive member count mismatch"
  tar -xf "${archive}" -C "${REMOTE_REPO}" --no-same-owner || {
    echo "[mwcc-inspect:remote] overlay archive extraction failed" >&2
    exit 125
  }
  if ! sha256sum -c "${OVERLAY_CHECKSUM_MANIFEST}" </dev/null >/dev/null; then
    echo "[mwcc-inspect:remote] overlay file SHA-256 mismatch" >&2
    exit 125
  fi
  rm -f -- "${archive}" "${OVERLAY_CHECKSUM_MANIFEST}"
  OVERLAY_CHECKSUM_MANIFEST=""
}

cd "${REMOTE_DIR}"
if ! git cat-file -e "${REMOTE_REF}^{commit}" 2>/dev/null; then
  echo "[mwcc-inspect:remote] stage=fetch ref=${REMOTE_REF}" >&2
  git fetch origin --prune '+refs/heads/*:refs/remotes/origin/*' || true
fi
git cat-file -e "${REMOTE_REF}^{commit}" 2>/dev/null || {
  echo "[mwcc-inspect:remote] remote is missing exact commit ${REMOTE_REF}" >&2
  exit 128
}
[[ ! -e "${REMOTE_REPO}" && ! -L "${REMOTE_REPO}" ]] || unsafe_private_path "${REMOTE_REPO}"
echo "[mwcc-inspect:remote] stage=private-clone ref=${REMOTE_REF} repo=${REMOTE_REPO}" >&2
git clone --quiet --shared --no-checkout "${REMOTE_DIR}" "${REMOTE_REPO}"
assert_safe_directory "${REMOTE_REPO}"
git -C "${REMOTE_REPO}" -c advice.detachedHead=false checkout --quiet --detach "${REMOTE_REF}"
[[ "$(git -C "${REMOTE_REPO}" rev-parse HEAD)" == "${REMOTE_REF}" ]] || exit 125
[[ -z "$(git -C "${REMOTE_REPO}" status --porcelain=v1)" ]] || exit 125
cd "${REMOTE_REPO}"
REMOTE_PRIVATE_COMMAND
  for OVERLAY_DEST in "${OVERLAY_DESTS[@]}"; do
    printf 'preflight_overlay_destination %s\n' "$(shell_quote "${OVERLAY_DEST}")"
  done
  printf 'begin_reparse_batch PRE\n'
  for ((OVERLAY_INDEX = 0; OVERLAY_INDEX < ${#OVERLAY_DESTS[@]}; OVERLAY_INDEX++)); do
    OVERLAY_DEST="${OVERLAY_DESTS[OVERLAY_INDEX]}"
    REMOTE_STAGE_REL="${OVERLAY_DEST}.upload.${INVOCATION_ID}"
    printf 'add_reparse_path_with_ancestors absent-or-file %s required-dir\n' \
      "$(shell_quote "${OVERLAY_DEST}")"
    printf 'add_reparse_path_with_ancestors must-absent %s required-dir\n' \
      "$(shell_quote "${REMOTE_STAGE_REL}")"
    printf 'add_reparse_path_with_ancestors must-absent %s required-dir\n' \
      "$(shell_quote "${REMOTE_STAGE_REL}.base64")"
  done
  if [[ "${UPLOAD_SOURCE}" != "1" ]]; then
    printf 'add_reparse_path_with_ancestors required-file "${REL_SRC}" required-dir\n'
  fi
  for PRIVATE_INCLUDE_REL in "${PRIVATE_INCLUDE_RELS[@]}"; do
    printf 'add_reparse_path_with_ancestors required-dir %s required-dir\n' \
      "$(shell_quote "${PRIVATE_INCLUDE_REL}")"
  done
  printf 'add_reparse_path_with_ancestors absent-or-dir %s absent-or-dir\n' \
    "$(shell_quote "${OUTPUT_REL}")"
  printf 'flush_reparse_batch PRE\n'
  if (( ${#OVERLAY_SOURCES[@]} > 0 )); then
    printf 'prepare_overlay_checksum_manifest %s <<'"'"'MWCC_INSPECT_OVERLAY_CHECKSUMS_EOF'"'"'\n' \
      "${#OVERLAY_SOURCES[@]}"
    for ((OVERLAY_INDEX = 0; OVERLAY_INDEX < ${#OVERLAY_SOURCES[@]}; OVERLAY_INDEX++)); do
      printf '%s  %s\n' "${OVERLAY_SHAS[OVERLAY_INDEX]}" "${OVERLAY_DESTS[OVERLAY_INDEX]}"
    done
    printf 'MWCC_INSPECT_OVERLAY_CHECKSUMS_EOF\n'
    printf 'apply_overlay_archive %s %s <<'"'"'MWCC_INSPECT_OVERLAY_ARCHIVE_EOF'"'"'\n' \
      "$(shell_quote "${OVERLAY_ARCHIVE_SHA}")" \
      "${#OVERLAY_SOURCES[@]}"
    base64 < "${LOCAL_OVERLAY_ARCHIVE}" | tr -d '\r\n' | fold -w 76
    printf '\nMWCC_INSPECT_OVERLAY_ARCHIVE_EOF\n'
    for OVERLAY_DEST in "${OVERLAY_DESTS[@]}"; do
      printf 'assert_safe_overlay_file %s\n' "$(shell_quote "${OVERLAY_DEST}")"
    done
  fi
  printf 'assert_safe_file "${REMOTE_REPO}" "${REL_SRC}"\n'
  for PRIVATE_INCLUDE_REL in "${PRIVATE_INCLUDE_RELS[@]}"; do
    printf 'assert_safe_existing_directory_path "${REMOTE_REPO}" %s\n' \
      "$(shell_quote "${PRIVATE_INCLUDE_REL}")"
  done
  printf 'assert_safe_output_directory_path "${REMOTE_REPO}" %s\n' \
    "$(shell_quote "${OUTPUT_REL}")"
  printf 'begin_reparse_batch POST\n'
  for ((OVERLAY_INDEX = 0; OVERLAY_INDEX < ${#OVERLAY_DESTS[@]}; OVERLAY_INDEX++)); do
    OVERLAY_DEST="${OVERLAY_DESTS[OVERLAY_INDEX]}"
    REMOTE_STAGE_REL="${OVERLAY_DEST}.upload.${INVOCATION_ID}"
    printf 'add_reparse_path_with_ancestors required-file %s required-dir\n' \
      "$(shell_quote "${OVERLAY_DEST}")"
    printf 'add_reparse_path_with_ancestors must-absent %s required-dir\n' \
      "$(shell_quote "${REMOTE_STAGE_REL}")"
    printf 'add_reparse_path_with_ancestors must-absent %s required-dir\n' \
      "$(shell_quote "${REMOTE_STAGE_REL}.base64")"
  done
  printf 'add_reparse_path_with_ancestors required-file "${REL_SRC}" required-dir\n'
  for PRIVATE_INCLUDE_REL in "${PRIVATE_INCLUDE_RELS[@]}"; do
    printf 'add_reparse_path_with_ancestors required-dir %s required-dir\n' \
      "$(shell_quote "${PRIVATE_INCLUDE_REL}")"
  done
  printf 'add_reparse_path_with_ancestors required-dir %s required-dir\n' \
    "$(shell_quote "${OUTPUT_REL}")"
  printf 'flush_reparse_batch POST\n'
  printf 'cd "${REMOTE_REPO}"\n'
  printf 'export MWCC_INSPECT_INVOCATION_ID=%s\n' "$(shell_quote "${INVOCATION_ID}")"
  printf 'unset BASH_ENV ENV\n'
  printf 'set +e\n'
  printf '%s %s %s %s %s %s %s' \
    "$(shell_quote "${REMOTE_FRESH_BASH}")" \
    "$(shell_quote "--noprofile")" \
    "$(shell_quote "--norc")" \
    "$(shell_quote "-c")" \
    "$(shell_quote 'exec "$@"')" \
    "$(shell_quote "mwcc-inspect-fresh")" \
    "$(shell_quote "${REMOTE_CLI}")"
  printf ' %s' "$(shell_quote "${REMOTE_MWCCEPPC}")"
  for MWCC_ARG in "${MWCC_ARGV[@]}"; do
    case "${MWCC_ARG}" in
      __PRIVATE_SOURCE__) REMOTE_ARG="${REMOTE_SOURCE}" ;;
      __PRIVATE_REPO__/*) REMOTE_ARG="${REMOTE_REPO}/${MWCC_ARG#__PRIVATE_REPO__/}" ;;
      *) REMOTE_ARG="${MWCC_ARG}" ;;
    esac
    printf ' %s' "$(shell_quote "${REMOTE_ARG}")"
  done
  printf '\n'
  printf 'INSPECT_RC=$?\n'
  printf 'set -e\n'
  printf 'exit "${INSPECT_RC}"\n'
  printf 'MWCC_INSPECT_COMMAND_EOF\n'
  printf 'chmod 700 "${COMMAND}"\n'
  printf 'echo "[mwcc-inspect:remote] stage=supervisor-launch job=${JOB_ID}" >&2\n'
  printf 'exec "${JOB_DIR}/supervisor" launch --job-dir "${JOB_DIR}" --job-id "${JOB_ID}" --token "${TOKEN}" --deadline-seconds "${DEADLINE_SECONDS}" -- "${COMMAND}"\n'
  printf '}\n'
  printf 'remote_job_main\n'
} > "${LOCAL_PAYLOAD}"

set +e
remote_bash < "${LOCAL_PAYLOAD}" 2> "${LOCAL_ERR}"
LAUNCH_EXIT=$?
set -e
rm -f -- "${LOCAL_PAYLOAD}"
LOCAL_PAYLOAD=""

if [[ "${LAUNCH_EXIT}" -ne 0 ]]; then
  echo "[mwcc-inspect] detached supervisor launch failed (exit ${LAUNCH_EXIT}) on ${HOST}" >&2
  echo "[mwcc-inspect] command: ssh -o ConnectTimeout=${SSH_CONNECT_TIMEOUT} ${HOST} ${REMOTE_BASH} -s" >&2
  echo "[mwcc-inspect] stage: remote checkout/supervisor-launch" >&2
  if [[ -s "${LOCAL_ERR}" ]]; then
    echo "[mwcc-inspect] remote stderr:" >&2
    sed -n '1,160p' "${LOCAL_ERR}" >&2
  else
    echo "[mwcc-inspect] remote stderr: <empty>" >&2
  fi
  if [[ "${LAUNCH_EXIT}" -ne 73 ]] && ! cancel_remote_job "${INVOCATION_ID}" "${CLEANUP_TIMEOUT}"; then
    echo "[mwcc-inspect] launch cleanup failed for ${INVOCATION_ID}" >&2
  fi
  REMOTE_JOB_ACTIVE=0
  rm -f "${LOCAL_STAGE}" "${LOCAL_ERR}"
  exit "${LAUNCH_EXIT}"
fi
REMOTE_JOB_ACTIVE=1

REMAINING_SECONDS="$(remaining_budget "${DEADLINE_SECONDS}" "${STARTED_AT}")"
if ! valid_positive_seconds "${REMAINING_SECONDS}"; then
  # The supervisor already owns clone/checkout/compile and its original
  # deadline. Give it a bounded window to publish that authoritative timeout
  # record instead of racing it with a wrapper-authored cancellation request.
  REMAINING_SECONDS="${CLEANUP_TIMEOUT}"
fi

set +e
trusted_remote_supervisor await \
  --job-dir "${REMOTE_JOB_DIR}" --job-id "${INVOCATION_ID}" \
  --token "${JOB_TOKEN}" --wait-seconds "${REMAINING_SECONDS}" \
  2>> "${LOCAL_ERR}"
AWAIT_EXIT=$?
set -e

if [[ "${AWAIT_EXIT}" -ne 0 ]]; then
  TIMEOUT_CLASS=0
  TIMEOUT_CLEANUP_FAILED=0
  FAILURE_EXIT="${AWAIT_EXIT}"
  if [[ "${AWAIT_EXIT}" -eq 124 || "${AWAIT_EXIT}" -eq 126 ]]; then
    TIMEOUT_CLASS=1
    echo "[mwcc-inspect] invocation ${INVOCATION_ID} timed out" >&2
    if [[ "${AWAIT_EXIT}" -eq 126 ]]; then TIMEOUT_CLEANUP_FAILED=1; fi
  else
    echo "[mwcc-inspect] invocation ${INVOCATION_ID} failed (exit ${AWAIT_EXIT})" >&2
  fi
  trusted_remote_supervisor diagnostics \
    --job-dir "${REMOTE_JOB_DIR}" --job-id "${INVOCATION_ID}" \
    --token "${JOB_TOKEN}" 2>> "${LOCAL_ERR}" || true
  if [[ "${AWAIT_EXIT}" -eq 1 ]] && \
      grep -Eq 'reason=inspector-exit-125|unsafe private repository path|upload SHA-256 mismatch|overlay decode failed' "${LOCAL_ERR}"; then
    FAILURE_EXIT=125
  fi
  if [[ -s "${LOCAL_ERR}" ]]; then
    sed -n '1,240p' "${LOCAL_ERR}" >&2
  fi
  if [[ "${AWAIT_EXIT}" -ne 126 ]] && ! cancel_remote_job "${INVOCATION_ID}" "${CLEANUP_TIMEOUT}"; then
    TIMEOUT_CLEANUP_FAILED=1
  fi
  REMOTE_JOB_ACTIVE=0
  rm -f "${LOCAL_STAGE}" "${LOCAL_ERR}"
  if [[ "${TIMEOUT_CLASS}" == "1" ]]; then
    if [[ "${TIMEOUT_CLEANUP_FAILED}" == "1" ]]; then
      echo "[mwcc-inspect] timeout-status=cleanup-failed invocation=${INVOCATION_ID}" >&2
      exit 125
    fi
    echo "[mwcc-inspect] timeout-status=deadline invocation=${INVOCATION_ID}" >&2
    exit 124
  fi
  exit "${FAILURE_EXIT}"
fi
REMOTE_JOB_ACTIVE=0
REMOTE_JOB_TERMINAL_SUCCESS=1

set +e
trusted_remote_supervisor emit-success \
  --job-dir "${REMOTE_JOB_DIR}" --job-id "${INVOCATION_ID}" \
  --token "${JOB_TOKEN}" > "${LOCAL_STAGE}" 2>> "${LOCAL_ERR}"
EMIT_EXIT=$?
set -e
if [[ "${EMIT_EXIT}" -ne 0 ]]; then
  echo "[mwcc-inspect] exact success artifact validation failed for ${INVOCATION_ID}" >&2
  exit 125
fi

mv -f "${LOCAL_STAGE}" "${OUT_FILE}"
set +e
finalize_remote_success "${INVOCATION_ID}" 2>> "${LOCAL_ERR}"
FINALIZE_EXIT=$?
set -e
REMOTE_JOB_TERMINAL_SUCCESS=0
if [[ "${FINALIZE_EXIT}" -ne 0 ]]; then
  echo "[mwcc-inspect] output proven and published, but retained success cleanup failed for ${INVOCATION_ID}" >&2
  sed -n '1,240p' "${LOCAL_ERR}" >&2
  exit 125
fi
rm -f "${LOCAL_ERR}"
trap - EXIT HUP INT TERM

echo "[mwcc-inspect] Output: ${OUT_FILE} ($(wc -c < "${OUT_FILE}") bytes)"
echo "[mwcc-inspect] Section summary:"
grep -E "^(====|FUNCTION:|LOCAL VARIABLES|STATEMENTS|Compilation finished)" "${OUT_FILE}" | head -20 || true
