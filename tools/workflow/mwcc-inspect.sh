#!/usr/bin/env bash
# Run mwcc-inspector on a single Melee TU on the remote Windows host.
#
# Usage:
#   tools/workflow/mwcc-inspect.sh [options] <path/to/source.c>
#   tools/workflow/mwcc-inspect.sh --cancel INVOCATION_ID
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
[[ -f "${SRC}" ]] || { echo "Source file not found: ${SRC}" >&2; exit 66; }

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

mkdir -p "$(dirname "${OUT_FILE}")"

echo "[mwcc-inspect] Host: ${HOST}"
echo "[mwcc-inspect] Source: ${REL_SRC}"
if [[ "${UPLOAD_SOURCE}" == "1" ]]; then
  echo "[mwcc-inspect] Candidate: ${SRC_ABS}"
fi
echo "[mwcc-inspect] Remote ref: ${REMOTE_REF}"

REMOTE_JOB_DIR="${REMOTE_JOB_ROOT}/${INVOCATION_ID}"
JOB_TOKEN="$(openssl rand -hex 32)"
REMOTE_TMP=""
REMOTE_SOURCE="${REL_SRC}"
if [[ "${UPLOAD_SOURCE}" == "1" ]]; then
  REMOTE_TMP="${REMOTE_JOB_DIR}/candidate"
  REMOTE_SOURCE="${REMOTE_TMP}/${REL_SRC}"
fi

LOCAL_STAGE="${OUT_FILE}.stage.${INVOCATION_ID}"
LOCAL_ERR="${OUT_FILE}.stderr.${INVOCATION_ID}"
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

set +e
{
  printf 'set -euo pipefail\n'
  printf 'JOB_ID=%s\n' "$(shell_quote "${INVOCATION_ID}")"
  printf 'JOB_ROOT=%s\n' "$(shell_quote "${REMOTE_JOB_ROOT}")"
  printf 'JOB_DIR=%s\n' "$(shell_quote "${REMOTE_JOB_DIR}")"
  printf 'REMOTE_TMP=%s\n' "$(shell_quote "${REMOTE_TMP}")"
  printf 'TOKEN=%s\n' "$(shell_quote "${JOB_TOKEN}")"
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
if [[ -n "${REMOTE_TMP}" ]]; then
  mkdir -p "${REMOTE_TMP}"
fi
exit 0
REMOTE_INIT
} | remote_bash
REMOTE_INIT_EXIT=$?
set -e
if [[ "${REMOTE_INIT_EXIT}" -ne 0 ]]; then
  if [[ "${REMOTE_INIT_EXIT}" -ne 73 ]]; then
    cancel_remote_job "${INVOCATION_ID}" "${CLEANUP_TIMEOUT}" >/dev/null 2>&1 || true
  fi
  exit "${REMOTE_INIT_EXIT}"
fi
REMOTE_JOB_ACTIVE=1

if [[ "${UPLOAD_SOURCE}" == "1" ]]; then
  echo "[mwcc-inspect] Preparing remote candidate source..."
  remote_bash <<REMOTE_MKDIR
set -euo pipefail
mkdir -p $(shell_quote "${REMOTE_TMP}/$(dirname "${REL_SRC}")")
exit
REMOTE_MKDIR
  REMOTE_SOURCE_DIR="${REMOTE_DIR}/$(dirname "${REL_SRC}")"
  REMOTE_CANDIDATE_DIR="${REMOTE_TMP}/$(dirname "${REL_SRC}")"
  remote_bash <<REMOTE_HEADERS
set -euo pipefail
if [[ -d $(shell_quote "${REMOTE_SOURCE_DIR}") ]]; then
  find $(shell_quote "${REMOTE_SOURCE_DIR}") -maxdepth 1 -type f \\( -name '*.h' -o -name '*.inc' \\) -exec cp -p '{}' $(shell_quote "${REMOTE_CANDIDATE_DIR}/") \\;
fi
exit
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
    printf 'exit\n'
  } | remote_bash
fi

echo "[mwcc-inspect] Running on ${HOST}…"

REMAINING_SECONDS="$(remaining_budget "${DEADLINE_SECONDS}" "${STARTED_AT}")"
if ! valid_positive_seconds "${REMAINING_SECONDS}"; then
  echo "[mwcc-inspect] invocation ${INVOCATION_ID} timed out before remote launch" >&2
  cancel_remote_job "${INVOCATION_ID}" "${CLEANUP_TIMEOUT}" || true
  REMOTE_JOB_ACTIVE=0
  exit 124
fi

set +e
{
  printf 'set -euo pipefail\n'
  printf 'JOB_ID=%s\n' "$(shell_quote "${INVOCATION_ID}")"
  printf 'JOB_DIR=%s\n' "$(shell_quote "${REMOTE_JOB_DIR}")"
  printf 'TOKEN=%s\n' "$(shell_quote "${JOB_TOKEN}")"
  printf 'DEADLINE_SECONDS=%s\n' "$(shell_quote "${REMAINING_SECONDS}")"
  cat <<'REMOTE_MONOTONIC'
remote_monotonic_now() {
  if [[ -n "${MWCC_INSPECT_MONOTONIC_CMD:-}" ]]; then
    "${MWCC_INSPECT_MONOTONIC_CMD}"
  elif [[ -r /proc/uptime ]]; then
    local uptime ignored
    read -r uptime ignored < /proc/uptime
    printf '%s\n' "${uptime}"
  elif command -v perl >/dev/null 2>&1; then
    perl -MTime::HiRes=clock_gettime,CLOCK_MONOTONIC \
      -e 'printf "%.9f\n", clock_gettime(CLOCK_MONOTONIC)'
  else
    echo "remote monotonic clock unavailable" >&2
    return 125
  fi
}
REMOTE_PHASE_STARTED="$(remote_monotonic_now)" || exit 125
REMOTE_MONOTONIC
  printf 'cd %s\n' "$(shell_quote "${REMOTE_DIR}")"
  printf 'echo "[mwcc-inspect:remote] stage=checkout ref=%s" >&2\n' "$(shell_quote "${REMOTE_REF}")"
  printf 'echo "[mwcc-inspect:remote] stage=fetch ref=%s" >&2\n' "$(shell_quote "${REMOTE_REF}")"
  printf "git fetch origin --prune '+refs/heads/*:refs/remotes/origin/*'\n"
  printf 'if ! git cat-file -e %s 2>/dev/null; then\n' "$(shell_quote "${REMOTE_REF}^{commit}")"
  printf '  echo "[mwcc-inspect:remote] remote is missing ref %s after fetch; push it to origin or set MWCC_INSPECT_REMOTE_REF" >&2\n' "$(shell_quote "${REMOTE_REF}")"
  printf '  exit 128\n'
  printf 'fi\n'
  printf 'git -c advice.detachedHead=false checkout --quiet %s\n' "$(shell_quote "${REMOTE_REF}")"
  printf 'REMOTE_SOURCE=%s\n' "$(shell_quote "${REMOTE_SOURCE}")"
  printf 'REMOTE_TMP=%s\n' "$(shell_quote "${REMOTE_TMP}")"
  printf 'REMOTE_DIR=%s\n' "$(shell_quote "${REMOTE_DIR}")"
  printf 'REL_SRC_LOCAL=%s\n' "$(shell_quote "${REL_SRC}")"
  printf 'MWCC_ARGS_REMOTE=%s\n' "$(shell_quote "${MWCC_ARGS}")"
  printf 'if [[ -n "${REMOTE_TMP}" ]]; then\n'
  printf '  MWCC_ARGS_REMOTE="${MWCC_ARGS_REMOTE/$REL_SRC_LOCAL/$REMOTE_SOURCE}"\n'
  printf '  MWCC_ARGS_REMOTE="$(sed -E "s@(^|[[:space:]])-i[[:space:]]+([^/[:space:]][^[:space:]]*)@\\1-i ${REMOTE_DIR}/\\2@g" <<< "${MWCC_ARGS_REMOTE}")"\n'
  printf '  MWCC_ARGS_REMOTE="-i ${REMOTE_TMP}/src -i ${REMOTE_TMP}/src/melee ${MWCC_ARGS_REMOTE}"\n'
  printf 'fi\n'
  printf 'REMOTE_NOW="$(remote_monotonic_now)" || exit 125\n'
  printf 'DEADLINE_SECONDS="$(awk -v budget="${DEADLINE_SECONDS}" -v started="${REMOTE_PHASE_STARTED}" -v now="${REMOTE_NOW}" '\''BEGIN { remaining = budget - (now - started); if (remaining < 0) remaining = 0; printf "%%.6f", remaining }'\'')"\n'
  printf 'awk -v value="${DEADLINE_SECONDS}" '\''BEGIN { exit !(value > 0) }'\'' || exit 124\n'
  printf 'export MWCC_ARGS_REMOTE\n'
  printf 'COMMAND="${JOB_DIR}/inspector-command"\n'
  printf 'cat > "${COMMAND}" <<'"'"'MWCC_INSPECT_COMMAND_EOF'"'"'\n'
  printf '#!/usr/bin/env bash\nset -euo pipefail\n'
  printf 'cd %s\n' "$(shell_quote "${REMOTE_DIR}")"
  printf 'export MWCC_INSPECT_INVOCATION_ID=%s\n' "$(shell_quote "${INVOCATION_ID}")"
  printf 'exec %s %s ${MWCC_ARGS_REMOTE}\n' \
    "$(shell_quote "${REMOTE_CLI}")" \
    "$(shell_quote "${REMOTE_MWCCEPPC}")"
  printf 'MWCC_INSPECT_COMMAND_EOF\n'
  printf 'chmod 700 "${COMMAND}"\n'
  printf 'echo "[mwcc-inspect:remote] stage=supervisor-launch job=${JOB_ID}" >&2\n'
  printf 'exec "${JOB_DIR}/supervisor" launch --job-dir "${JOB_DIR}" --job-id "${JOB_ID}" --token "${TOKEN}" --deadline-seconds "${DEADLINE_SECONDS}" -- "${COMMAND}"\n'
} | remote_bash 2> "${LOCAL_ERR}"
LAUNCH_EXIT=$?
set -e

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
  if ! cancel_remote_job "${INVOCATION_ID}" "${CLEANUP_TIMEOUT}"; then
    echo "[mwcc-inspect] timeout cleanup failed for ${INVOCATION_ID}" >&2
  fi
  REMOTE_JOB_ACTIVE=0
  rm -f "${LOCAL_STAGE}" "${LOCAL_ERR}"
  exit "${LAUNCH_EXIT}"
fi

REMAINING_SECONDS="$(remaining_budget "${DEADLINE_SECONDS}" "${STARTED_AT}")"
if ! valid_positive_seconds "${REMAINING_SECONDS}"; then
  cancel_remote_job "${INVOCATION_ID}" "${CLEANUP_TIMEOUT}" || true
  REMOTE_JOB_ACTIVE=0
  exit 124
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
  exit "${AWAIT_EXIT}"
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
