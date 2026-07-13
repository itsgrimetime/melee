#!/usr/bin/env bash
# Invocation-scoped remote ownership for mwcc-inspector.
#
# The detached supervisor is the only process allowed to terminate the inspector
# tree.  Other clients communicate exclusively through authenticated files in a
# mode-0700 job directory and wait for an atomic terminal record.

set -euo pipefail

die() {
  echo "mwcc-inspect-supervisor: $*" >&2
  exit 64
}

valid_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]
}

valid_token() {
  [[ "$1" =~ ^[A-Fa-f0-9]{64}$ ]]
}

valid_seconds() {
  [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]] &&
    awk -v value="$1" 'BEGIN { exit !(value > 0) }'
}

monotonic_now() {
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
    echo "mwcc-inspect-supervisor: no monotonic clock source" >&2
    return 125
  fi
}

float_add() {
  awk -v left="$1" -v right="$2" 'BEGIN { printf "%.9f\n", left + right }'
}

float_ge() {
  awk -v left="$1" -v right="$2" 'BEGIN { exit !(left >= right) }'
}

job_mode() {
  local mode
  mode="$(stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null)" || return 1
  printf '%s\n' "$mode"
}

validate_windows_job_security() {
  local security_output
  if [[ -n "${MWCC_INSPECT_WINDOWS_SECURITY_CMD:-}" ]]; then
    security_output="$("${MWCC_INSPECT_WINDOWS_SECURITY_CMD}" "${JOB_DIR}")" || return 1
    security_output="${security_output//$'\r'/}"
    [[ "${security_output}" =~ ^MWCC_INSPECT_WINDOWS_SECURITY_OK:S-1-[0-9-]+$ ]]
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
  $item = Get-Item -LiteralPath $path -Force
  if (-not $item.PSIsContainer) { throw 'job path is not a directory' }
  if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'job path is a reparse point'
  }

  $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
  $acl = $item.GetAccessControl()
  if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $currentSid.Value) {
    throw 'job owner is not the current Windows SID'
  }
  if (-not $acl.AreAccessRulesProtected) { throw 'job ACL inheritance is enabled' }

  $rules = @($acl.GetAccessRules(
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
  foreach ($name in @(
    'token',
    'supervisor',
    'terminal',
    'artifact.partial',
    'artifact.success',
    'cancel.request',
    'inspector-command'
  )) {
    $childPath = Join-Path $path $name
    if (-not [System.IO.File]::Exists($childPath)) { continue }
    $child = Get-Item -LiteralPath $childPath -Force
    if ($child.PSIsContainer) { throw "job file is a directory: $name" }
    if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "job file is a reparse point: $name"
    }
  }
  Write-Output ('MWCC_INSPECT_WINDOWS_SECURITY_OK:' + $currentSid.Value)
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
  [[ "${security_output}" =~ ^MWCC_INSPECT_WINDOWS_SECURITY_OK:S-1-[0-9-]+$ ]]
}

validate_job_boundary() {
  [[ -d "${JOB_DIR}" && ! -L "${JOB_DIR}" ]] || {
    echo "mwcc-inspect-supervisor: missing safe job directory: ${JOB_DIR}" >&2
    return 1
  }
  local parent_dir canonical_parent canonical_job platform
  parent_dir="$(dirname "${JOB_DIR}")"
  canonical_parent="$(cd "${parent_dir}" && pwd -P)" || return 1
  canonical_job="$(cd "${JOB_DIR}" && pwd -P)" || return 1
  [[ "$(basename "${JOB_DIR}")" == "${JOB_ID}" ]] || return 1
  [[ "${canonical_job}" == "${canonical_parent}/${JOB_ID}" ]] || {
    echo "mwcc-inspect-supervisor: job path escaped its exact parent: ${JOB_DIR}" >&2
    return 1
  }
  [[ "${JOB_DIR}" == "${canonical_job}" ]] || {
    echo "mwcc-inspect-supervisor: non-canonical job path rejected: ${JOB_DIR}" >&2
    return 1
  }
  platform="${MWCC_INSPECT_PLATFORM:-$(uname -s)}"
  case "${platform}" in
    MSYS*|MINGW*|CYGWIN*)
      validate_windows_job_security || {
        echo "mwcc-inspect-supervisor: native Windows security validation failed: ${JOB_DIR}" >&2
        return 1
      }
      ;;
    *)
      [[ "$(job_mode "${JOB_DIR}")" == "700" ]] || {
        echo "mwcc-inspect-supervisor: job directory is not mode 0700: ${JOB_DIR}" >&2
        return 1
      }
      ;;
  esac
  [[ -f "${JOB_DIR}/token" && ! -L "${JOB_DIR}/token" ]] || {
    echo "mwcc-inspect-supervisor: missing job token" >&2
    return 1
  }
}

validate_job() {
  validate_job_boundary || return 1
  local stored_token
  IFS= read -r stored_token < "${JOB_DIR}/token" || true
  valid_token "${stored_token}" || return 1
  [[ "${stored_token}" == "${TOKEN}" ]] || {
    echo "mwcc-inspect-supervisor: token mismatch for ${JOB_ID}" >&2
    return 1
  }
}

run_read_token() {
  JOB_DIR="" JOB_ID=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --job-dir) [[ $# -ge 2 ]] || die "$1 requires a path"; JOB_DIR="$2"; shift 2 ;;
      --job-id) [[ $# -ge 2 ]] || die "$1 requires an ID"; JOB_ID="$2"; shift 2 ;;
      *) die "unknown read-token option: $1" ;;
    esac
  done
  [[ -n "${JOB_DIR}" && -n "${JOB_ID}" ]] || die "job-dir and job-id are required"
  valid_id "${JOB_ID}" || die "invalid job ID"
  validate_job_boundary || exit 125
  local stored_token
  IFS= read -r stored_token < "${JOB_DIR}/token" || true
  valid_token "${stored_token}" || exit 125
  printf '%s\n' "${stored_token}"
}

terminal_field() {
  local key="$1"
  sed -n "s/^${key}=//p" "${JOB_DIR}/terminal" | head -n 1
}

validate_terminal() {
  [[ -f "${JOB_DIR}/terminal" && ! -L "${JOB_DIR}/terminal" ]] || return 1
  [[ "$(terminal_field version)" == "1" ]] || return 1
  [[ "$(terminal_field id)" == "${JOB_ID}" ]] || return 1
  [[ "$(terminal_field token)" == "${TOKEN}" ]] || return 1
  local status
  status="$(terminal_field status)"
  [[ "${status}" =~ ^(success|failed|cancelled|timeout|cleanup-failed)$ ]] || return 1
}

write_terminal() {
  local status="$1"
  local reason="$2"
  local reaped="$3"
  local artifact_sha="${4:-}"
  local tmp="${JOB_DIR}/terminal.tmp.$$"
  if [[ -e "${JOB_DIR}/terminal" ]]; then
    return 0
  fi
  umask 077
  {
    printf 'version=1\n'
    printf 'id=%s\n' "${JOB_ID}"
    printf 'token=%s\n' "${TOKEN}"
    printf 'status=%s\n' "${status}"
    printf 'reason=%s\n' "${reason}"
    printf 'child_reaped=%s\n' "${reaped}"
    printf 'artifact_sha256=%s\n' "${artifact_sha}"
  } > "${tmp}"
  chmod 600 "${tmp}"
  mv "${tmp}" "${JOB_DIR}/terminal"
}

await_terminal() {
  local wait_seconds="$1"
  local deadline
  deadline="$(float_add "$(monotonic_now)" "${wait_seconds}")"
  while true; do
    if [[ -e "${JOB_DIR}/terminal" ]]; then
      validate_terminal || {
        echo "mwcc-inspect-supervisor: invalid terminal record for ${JOB_ID}" >&2
        return 125
      }
      return 0
    fi
    if float_ge "$(monotonic_now)" "${deadline}"; then
      return 124
    fi
    sleep "${MWCC_INSPECT_POLL_SECONDS:-0.02}"
  done
}

parse_common() {
  JOB_DIR=""
  JOB_ID=""
  TOKEN=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --job-dir) [[ $# -ge 2 ]] || die "$1 requires a path"; JOB_DIR="$2"; shift 2 ;;
      --job-id) [[ $# -ge 2 ]] || die "$1 requires an ID"; JOB_ID="$2"; shift 2 ;;
      --token) [[ $# -ge 2 ]] || die "$1 requires a token"; TOKEN="$2"; shift 2 ;;
      --) shift; REMAINING=("$@"); break ;;
      *) REMAINING=("$@"); break ;;
    esac
  done
  [[ -n "${JOB_DIR}" && -n "${JOB_ID}" && -n "${TOKEN}" ]] || die "job-dir, job-id, and token are required"
  valid_id "${JOB_ID}" || die "invalid job ID"
  valid_token "${TOKEN}" || die "invalid token"
  validate_job || exit 125
}

resolve_native_pid() {
  local child_pid="$1"
  if [[ -n "${MWCC_INSPECT_NATIVE_PID_CMD:-}" ]]; then
    "${MWCC_INSPECT_NATIVE_PID_CMD}" "${child_pid}"
  else
    ps -W 2>/dev/null | awk -v child_pid="${child_pid}" \
      '$1 == child_pid { print $4; exit }'
  fi
}

resolve_owned_native_pid() {
  local resolve_deadline
  resolve_deadline="$(float_add "$(monotonic_now)" "${MWCC_INSPECT_NATIVE_PID_SECONDS:-2}")"
  while true; do
    NATIVE_PID="$(resolve_native_pid "${CHILD_PID}" || true)"
    if [[ "${NATIVE_PID}" =~ ^[0-9]+$ ]]; then
      return 0
    fi
    if ! kill -0 "${CHILD_PID}" 2>/dev/null; then
      NATIVE_PID=""
      return 0
    fi
    if float_ge "$(monotonic_now)" "${resolve_deadline}"; then
      return 1
    fi
    sleep "${MWCC_INSPECT_POLL_SECONDS:-0.02}"
  done
}

wait_after_cleanup_failure() {
  # Retain ownership after publishing failure.  Never abandon a live child.
  while kill -0 "${CHILD_PID}" 2>/dev/null; do
    sleep "${MWCC_INSPECT_POLL_SECONDS:-0.02}"
  done
  set +e
  wait "${CHILD_PID}" 2>/dev/null
  set -e
  umask 077
  printf 'child_reaped=true\n' > "${JOB_DIR}/cleanup-eventually-reaped.tmp.$$"
  mv "${JOB_DIR}/cleanup-eventually-reaped.tmp.$$" "${JOB_DIR}/cleanup-eventually-reaped"
}

terminate_owned_child() {
  local terminal_status="$1"
  local reason="$2"
  if ! kill -0 "${CHILD_PID}" 2>/dev/null; then
    set +e
    wait "${CHILD_PID}" 2>/dev/null
    set -e
    write_terminal "${terminal_status}" "${reason}" true
    return 0
  fi

  local taskkill="${MWCC_INSPECT_TASKKILL:-taskkill.exe}"
  set +e
  "${taskkill}" //PID "${NATIVE_PID}" //T //F >"${JOB_DIR}/taskkill.stdout" 2>"${JOB_DIR}/taskkill.stderr"
  local kill_rc=$?
  set -e
  if (( kill_rc != 0 )); then
    write_terminal cleanup-failed "${terminal_status}-${reason}-taskkill-exit-${kill_rc}" false
    wait_after_cleanup_failure
    return 125
  fi

  local kill_deadline
  kill_deadline="$(float_add "$(monotonic_now)" "${MWCC_INSPECT_KILL_AWAIT_SECONDS:-5}")"
  while kill -0 "${CHILD_PID}" 2>/dev/null; do
    if float_ge "$(monotonic_now)" "${kill_deadline}"; then
      write_terminal cleanup-failed "${terminal_status}-${reason}-child-survived-taskkill" false
      wait_after_cleanup_failure
      return 125
    fi
    sleep "${MWCC_INSPECT_POLL_SECONDS:-0.02}"
  done
  set +e
  wait "${CHILD_PID}" 2>/dev/null
  set -e
  write_terminal "${terminal_status}" "${reason}" true
}

run_supervisor() {
  local deadline_seconds=""
  JOB_DIR="" JOB_ID="" TOKEN=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --job-dir) JOB_DIR="$2"; shift 2 ;;
      --job-id) JOB_ID="$2"; shift 2 ;;
      --token) TOKEN="$2"; shift 2 ;;
      --deadline-seconds) deadline_seconds="$2"; shift 2 ;;
      --) shift; COMMAND=("$@"); break ;;
      *) die "unknown supervise option: $1" ;;
    esac
  done
  valid_id "${JOB_ID:-}" || die "invalid job ID"
  valid_token "${TOKEN:-}" || die "invalid token"
  valid_seconds "${deadline_seconds}" || die "invalid deadline"
  [[ ${#COMMAND[@]} -gt 0 ]] || die "missing inspector command"
  validate_job || exit 125
  [[ ! -e "${JOB_DIR}/terminal" ]] || die "job is already terminal"

  local deadline_at
  deadline_at="$(float_add "$(monotonic_now)" "${deadline_seconds}")"
  umask 077
  "${COMMAND[@]}" >"${JOB_DIR}/artifact.partial" 2>"${JOB_DIR}/inspector.stderr" &
  CHILD_PID=$!
  if ! resolve_owned_native_pid; then
    write_terminal cleanup-failed native-pid-unavailable false
    wait_after_cleanup_failure
    exit 125
  fi

  {
    printf 'version=1\n'
    printf 'id=%s\n' "${JOB_ID}"
    printf 'token=%s\n' "${TOKEN}"
  } > "${JOB_DIR}/ready.tmp.$$"
  chmod 600 "${JOB_DIR}/ready.tmp.$$"
  mv "${JOB_DIR}/ready.tmp.$$" "${JOB_DIR}/ready"

  trap 'terminate_owned_child cancelled supervisor-signal || true; exit 125' HUP INT TERM
  while true; do
    if [[ -e "${JOB_DIR}/cancel.request" ]]; then
      local request_token=""
      IFS= read -r request_token < "${JOB_DIR}/cancel.request" || true
      if [[ "${request_token}" != "${TOKEN}" ]]; then
        terminate_owned_child cleanup-failed invalid-cancel-token || true
        exit 125
      fi
      set +e
      terminate_owned_child cancelled requested
      local cleanup_rc=$?
      set -e
      (( cleanup_rc == 0 )) || exit "${cleanup_rc}"
      exit 124
    fi
    if float_ge "$(monotonic_now)" "${deadline_at}"; then
      set +e
      terminate_owned_child timeout deadline
      local cleanup_rc=$?
      set -e
      (( cleanup_rc == 0 )) || exit "${cleanup_rc}"
      exit 124
    fi
    if ! kill -0 "${CHILD_PID}" 2>/dev/null; then
      set +e
      wait "${CHILD_PID}"
      local child_rc=$?
      set -e
      if (( child_rc != 0 )); then
        write_terminal failed "inspector-exit-${child_rc}" true
        exit "${child_rc}"
      fi
      if grep -Eq '^[[:space:]]*#[[:space:]]*Error:|(^|[^[:alnum:]_])([A-Za-z]:[/\\]|/[^[:space:]]+)[^[:space:]]*\([0-9]+\):[[:space:]]+(error|fatal error):' "${JOB_DIR}/artifact.partial"; then
        write_terminal failed compiler-diagnostics true
        exit 65
      fi
      if ! grep -q '^FUNCTION:' "${JOB_DIR}/artifact.partial"; then
        write_terminal failed no-function-section true
        exit 65
      fi
      if ! grep -Eq '^Compilation finished\.?[[:space:]]*$' "${JOB_DIR}/artifact.partial"; then
        write_terminal failed no-completion-marker true
        exit 65
      fi
      mv "${JOB_DIR}/artifact.partial" "${JOB_DIR}/artifact.success"
      local artifact_sha
      artifact_sha="$(sha256sum "${JOB_DIR}/artifact.success" | awk '{print $1}')"
      write_terminal success completed true "${artifact_sha}"
      exit 0
    fi
    sleep "${MWCC_INSPECT_POLL_SECONDS:-0.02}"
  done
}

run_launch() {
  local deadline_seconds=""
  local startup_seconds="${MWCC_INSPECT_STARTUP_SECONDS:-10}"
  JOB_DIR="" JOB_ID="" TOKEN=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --job-dir) JOB_DIR="$2"; shift 2 ;;
      --job-id) JOB_ID="$2"; shift 2 ;;
      --token) TOKEN="$2"; shift 2 ;;
      --deadline-seconds) deadline_seconds="$2"; shift 2 ;;
      --) shift; COMMAND=("$@"); break ;;
      *) die "unknown launch option: $1" ;;
    esac
  done
  valid_id "${JOB_ID:-}" || die "invalid job ID"
  valid_token "${TOKEN:-}" || die "invalid token"
  valid_seconds "${deadline_seconds}" || die "invalid deadline"
  [[ ${#COMMAND[@]} -gt 0 ]] || die "missing inspector command"
  validate_job || exit 125
  local setsid_cmd="${MWCC_INSPECT_SETSID:-setsid}"
  command -v "${setsid_cmd}" >/dev/null 2>&1 || {
    write_terminal cleanup-failed detach-command-unavailable false
    exit 125
  }
  nohup "${setsid_cmd}" "$0" supervise \
    --job-dir "${JOB_DIR}" --job-id "${JOB_ID}" --token "${TOKEN}" \
    --deadline-seconds "${deadline_seconds}" -- "${COMMAND[@]}" \
    </dev/null >"${JOB_DIR}/supervisor.log" 2>&1 &

  local startup_deadline
  startup_deadline="$(float_add "$(monotonic_now)" "${startup_seconds}")"
  while true; do
    if [[ -e "${JOB_DIR}/ready" ]]; then
      grep -Fxq "id=${JOB_ID}" "${JOB_DIR}/ready" &&
        grep -Fxq "token=${TOKEN}" "${JOB_DIR}/ready" && return 0
      echo "mwcc-inspect-supervisor: invalid ready record" >&2
      return 125
    fi
    if [[ -e "${JOB_DIR}/terminal" ]]; then
      validate_terminal || return 125
      [[ "$(terminal_field status)" == success ]]
      return $?
    fi
    if float_ge "$(monotonic_now)" "${startup_deadline}"; then
      echo "mwcc-inspect-supervisor: detached supervisor did not become ready" >&2
      return 124
    fi
    sleep "${MWCC_INSPECT_POLL_SECONDS:-0.02}"
  done
}

cancel_validated_job() {
  local wait_seconds="$1"
  if [[ ! -e "${JOB_DIR}/terminal" ]]; then
    local request_tmp="${JOB_DIR}/cancel.request.tmp.$$"
    umask 077
    printf '%s\n' "${TOKEN}" > "${request_tmp}"
    chmod 600 "${request_tmp}"
    mv "${request_tmp}" "${JOB_DIR}/cancel.request"
  fi
  set +e
  await_terminal "${wait_seconds}"
  local await_rc=$?
  set -e
  if (( await_rc != 0 )); then
    echo "mwcc-inspect-supervisor: cancellation lacks terminal cleanup proof for ${JOB_ID}" >&2
    return "${await_rc}"
  fi
  if [[ "$(terminal_field status)" == cleanup-failed ]]; then
    echo "mwcc-inspect-supervisor: cleanup failed for ${JOB_ID}: $(terminal_field reason)" >&2
    return 125
  fi
  [[ "$(terminal_field child_reaped)" == true ]] || {
    echo "mwcc-inspect-supervisor: terminal state does not prove child reap" >&2
    return 125
  }
}

run_cancel() {
  local wait_seconds=""
  JOB_DIR="" JOB_ID="" TOKEN=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --job-dir) JOB_DIR="$2"; shift 2 ;;
      --job-id) JOB_ID="$2"; shift 2 ;;
      --token) TOKEN="$2"; shift 2 ;;
      --wait-seconds) wait_seconds="$2"; shift 2 ;;
      *) die "unknown cancel option: $1" ;;
    esac
  done
  valid_id "${JOB_ID:-}" || die "invalid job ID"
  valid_token "${TOKEN:-}" || die "invalid token"
  valid_seconds "${wait_seconds}" || die "invalid wait"
  validate_job || exit 125
  cancel_validated_job "${wait_seconds}"
}

run_cancel_stored_token() {
  local wait_seconds=""
  JOB_DIR="" JOB_ID="" TOKEN=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --job-dir) JOB_DIR="$2"; shift 2 ;;
      --job-id) JOB_ID="$2"; shift 2 ;;
      --wait-seconds) wait_seconds="$2"; shift 2 ;;
      *) die "unknown cancel-stored-token option: $1" ;;
    esac
  done
  valid_id "${JOB_ID:-}" || die "invalid job ID"
  valid_seconds "${wait_seconds}" || die "invalid wait"
  validate_job_boundary || exit 125
  IFS= read -r TOKEN < "${JOB_DIR}/token" || true
  valid_token "${TOKEN}" || exit 125
  cancel_validated_job "${wait_seconds}"
}

run_await() {
  local wait_seconds=""
  JOB_DIR="" JOB_ID="" TOKEN=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --job-dir) JOB_DIR="$2"; shift 2 ;;
      --job-id) JOB_ID="$2"; shift 2 ;;
      --token) TOKEN="$2"; shift 2 ;;
      --wait-seconds) wait_seconds="$2"; shift 2 ;;
      *) die "unknown await option: $1" ;;
    esac
  done
  valid_id "${JOB_ID:-}" || die "invalid job ID"
  valid_token "${TOKEN:-}" || die "invalid token"
  valid_seconds "${wait_seconds}" || die "invalid wait"
  validate_job || exit 125
  await_terminal "${wait_seconds}" || exit $?
  case "$(terminal_field status)" in
    success) exit 0 ;;
    failed) exit 1 ;;
    cancelled|timeout) exit 124 ;;
    cleanup-failed)
      if [[ "$(terminal_field reason)" == timeout-* ]]; then exit 126; fi
      exit 125
      ;;
  esac
}

run_emit_success() {
  JOB_DIR="" JOB_ID="" TOKEN=""
  parse_common "$@"
  validate_terminal || {
    echo "mwcc-inspect-supervisor: missing valid terminal proof" >&2
    exit 125
  }
  [[ "$(terminal_field status)" == success && "$(terminal_field child_reaped)" == true ]] || {
    echo "mwcc-inspect-supervisor: job is not a reaped success" >&2
    exit 125
  }
  [[ -f "${JOB_DIR}/artifact.success" && ! -L "${JOB_DIR}/artifact.success" ]] || exit 125
  local local_sha
  local_sha="$(sha256sum "${JOB_DIR}/artifact.success" | awk '{print $1}')"
  [[ "${local_sha}" == "$(terminal_field artifact_sha256)" ]] || {
    echo "mwcc-inspect-supervisor: success artifact hash mismatch" >&2
    exit 125
  }
  cat "${JOB_DIR}/artifact.success"
}

run_diagnostics() {
  JOB_DIR="" JOB_ID="" TOKEN=""
  parse_common "$@"
  if [[ -f "${JOB_DIR}/terminal" ]]; then
    echo "[mwcc-inspect:remote] terminal:" >&2
    sed -n '1,40p' "${JOB_DIR}/terminal" >&2
  fi
  if [[ -s "${JOB_DIR}/inspector.stderr" ]]; then
    echo "[mwcc-inspect:remote] inspector stderr:" >&2
    sed -n '1,160p' "${JOB_DIR}/inspector.stderr" >&2
  fi
}

finalize_validated_success() {
  validate_terminal || {
    echo "mwcc-inspect-supervisor: missing valid terminal proof" >&2
    exit 125
  }
  [[ "$(terminal_field status)" == success && "$(terminal_field child_reaped)" == true ]] || {
    echo "mwcc-inspect-supervisor: refusing to remove non-success diagnostic state" >&2
    exit 125
  }
  [[ -f "${JOB_DIR}/artifact.success" && ! -L "${JOB_DIR}/artifact.success" ]] || exit 125
  local artifact_sha
  artifact_sha="$(sha256sum "${JOB_DIR}/artifact.success" | awk '{print $1}')"
  [[ "${artifact_sha}" == "$(terminal_field artifact_sha256)" ]] || exit 125
  local parent_dir
  parent_dir="$(cd "${JOB_DIR}/.." && pwd -P)"
  [[ "${JOB_DIR}" == "${parent_dir}/${JOB_ID}" ]] || {
    echo "mwcc-inspect-supervisor: refusing unsafe finalization path" >&2
    exit 125
  }
  cd "${parent_dir}"
  rm -rf -- "${JOB_DIR}"
  [[ ! -e "${JOB_DIR}" ]] || exit 125
}

run_finalize_success() {
  JOB_DIR="" JOB_ID="" TOKEN=""
  parse_common "$@"
  finalize_validated_success
}

run_finalize_stored_token() {
  JOB_DIR="" JOB_ID="" TOKEN=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --job-dir) JOB_DIR="$2"; shift 2 ;;
      --job-id) JOB_ID="$2"; shift 2 ;;
      *) die "unknown finalize-stored-token option: $1" ;;
    esac
  done
  valid_id "${JOB_ID:-}" || die "invalid job ID"
  validate_job_boundary || exit 125
  IFS= read -r TOKEN < "${JOB_DIR}/token" || true
  valid_token "${TOKEN}" || exit 125
  finalize_validated_success
}

[[ $# -ge 1 ]] || die "mode required"
MODE="$1"
shift
case "${MODE}" in
  read-token) run_read_token "$@" ;;
  supervise) run_supervisor "$@" ;;
  launch) run_launch "$@" ;;
  cancel) run_cancel "$@" ;;
  cancel-stored-token) run_cancel_stored_token "$@" ;;
  await) run_await "$@" ;;
  diagnostics) run_diagnostics "$@" ;;
  emit-success) run_emit_success "$@" ;;
  finalize-success) run_finalize_success "$@" ;;
  finalize-stored-token) run_finalize_stored_token "$@" ;;
  *) die "unknown mode: ${MODE}" ;;
esac
