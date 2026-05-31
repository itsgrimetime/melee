# run_pcdump.ps1 -- compile a single Melee TU under the patched mwcc_debug DLL
# and emit pcdump.txt to stdout.
#
# Usage (typically via SSH from macOS):
#   powershell -NoProfile -ExecutionPolicy Bypass -File run_pcdump.ps1 <c-path-relative-to-repo>
#
# Environment:
#   MWCC_DEBUG_TIMEOUT_SECS  (default 60)
#   MWCC_DEBUG_REPO          (default C:\Users\mikes\code\melee — the master
#                            checkout, also used as the worktree base)
#   MWCC_DEBUG_BRANCH        (default: master; if set to anything else, the
#                            script uses a worktree at
#                            <MWCC_DEBUG_REPO>-worktrees\<sanitized-branch>
#                            instead of the master checkout. Worktree is
#                            auto-created from origin/<branch> if missing.)
#   MWCC_DEBUG_WORKTREES_DIR (default <MWCC_DEBUG_REPO>-worktrees; the parent
#                            directory under which per-branch worktrees live)
#   MWCC_DEBUG_COMPILER_DIR  (default <repo>\build\compilers\GC\1.2.5n);
#                            falls back to master's compiler then the
#                            inspector-package path if not found
#   MWCC_DEBUG_PATCHED_DLL   (default <script-dir>\lmgr326b.dll)
#   MWCC_DEBUG_NO_PULL       (set to 1 to skip `git pull`/worktree-sync for
#                            testing)
#
# Output contract:
#   stdout = raw pcdump.txt content (binary-safe -- caller redirects to file)
#   stderr = all diagnostics
#   exit code = 0 success, non-zero on any failure (lock held, sync failed,
#               compile failed, no pcdump produced, etc.)

# Stop on any unhandled error
$ErrorActionPreference = "Stop"

# --- Helpers ---
function Write-Err {
    param([string]$Msg)
    [Console]::Error.WriteLine($Msg)
}

function Fail {
    param([string]$Msg, [int]$Code = 1)
    Write-Err "ERROR: $Msg"
    exit $Code
}

# --- Arg parsing ---
if ($args.Count -ne 1) {
    Write-Err "Usage: run_pcdump.ps1 <src-relative-to-repo>"
    exit 64
}
$srcRel = $args[0] -replace '\\', '/'  # normalize to forward slashes

# --- Resolve paths ---
$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$masterRoot  = if ($env:MWCC_DEBUG_REPO) { $env:MWCC_DEBUG_REPO } else { "C:\Users\mikes\code\melee" }
# Trim — cmd.exe's `set NAME=value && ...` chain includes any
# whitespace before `&&` in the value. Defensive trim avoids surprises
# when this script is invoked via SSH + cmd from the local CLI.
$branch      = if ($env:MWCC_DEBUG_BRANCH) { $env:MWCC_DEBUG_BRANCH.Trim() } else { "" }
$worktreesDir = if ($env:MWCC_DEBUG_WORKTREES_DIR) {
    $env:MWCC_DEBUG_WORKTREES_DIR
} else {
    "$masterRoot-worktrees"
}

# Compute the active $repoRoot. If no branch override (or branch is the
# default master/main), use the legacy master checkout. Otherwise the
# script will use (and possibly create) a worktree under $worktreesDir.
$useWorktree = ($branch -ne "" -and $branch -ne "master" -and $branch -ne "main")
if ($useWorktree) {
    # Sanitize branch name for filesystem use: `/` → `-`, drop anything
    # that's not alphanumeric, dash, dot, or underscore.
    $branchSafe = ($branch -replace '/', '-') -replace '[^A-Za-z0-9._\-]', ''
    if (-not $branchSafe) {
        Fail "branch name sanitized to empty string: $branch" 64
    }
    $repoRoot = Join-Path $worktreesDir $branchSafe
} else {
    $repoRoot = $masterRoot
}

$compilerDir = if ($env:MWCC_DEBUG_COMPILER_DIR) {
    $env:MWCC_DEBUG_COMPILER_DIR
} else {
    # Try active repo's compiler first.
    $candidate = Join-Path $repoRoot "build\compilers\GC\1.2.5n"
    if (Test-Path (Join-Path $candidate "mwcceppc.exe")) {
        $candidate
    } else {
        # Fall back to master's compiler (worktrees usually don't have one
        # since `python configure.py` only runs in master).
        $masterCompiler = Join-Path $masterRoot "build\compilers\GC\1.2.5n"
        if (Test-Path (Join-Path $masterCompiler "mwcceppc.exe")) {
            $masterCompiler
        } else {
            # Fall back to inspector-package compiler if neither has it.
            "C:\Users\mikes\code\melee-decomp\mwcc-inspector-package\melee\build\compilers\GC\1.2.5n"
        }
    }
}
$patchedDll = if ($env:MWCC_DEBUG_PATCHED_DLL) { $env:MWCC_DEBUG_PATCHED_DLL } else { Join-Path $scriptDir "lmgr326b.dll" }
$timeoutSecs = if ($env:MWCC_DEBUG_TIMEOUT_SECS) { [int]$env:MWCC_DEBUG_TIMEOUT_SECS } else { 60 }

if ($useWorktree) {
    Write-Err "[mwcc_debug] using worktree for branch '$branch' at $repoRoot"
} else {
    Write-Err "[mwcc_debug] using master checkout at $repoRoot"
}

$stockDll    = Join-Path $compilerDir "lmgr326b.dll"
$stockBackup = Join-Path $compilerDir "lmgr326b.dll.stock"
$mwccExe     = Join-Path $compilerDir "mwcceppc.exe"
$lockFile    = Join-Path $env:TEMP "mwcc_debug.lock"
$workDir     = Join-Path $env:TEMP "mwcc_debug_run"
$pcdumpFile  = Join-Path $workDir "pcdump.txt"

# --- Sanity checks (pre-worktree) ---
if (-not (Test-Path $masterRoot)) { Fail "master repo not found: $masterRoot" }
if (-not (Test-Path $patchedDll)) { Fail "patched DLL not found: $patchedDll" }

# --- Worktree creation (if branch override given) ---
if ($useWorktree) {
    if (-not (Test-Path $worktreesDir)) {
        New-Item -ItemType Directory -Path $worktreesDir -Force | Out-Null
    }
    if (-not (Test-Path $repoRoot)) {
        Write-Err "[mwcc_debug] creating worktree for branch '$branch' at $repoRoot"
        Push-Location $masterRoot
        $savedErrActPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            # Fetch first so origin/$branch is current
            $fetchOut = & git fetch origin $branch 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Pop-Location
                $ErrorActionPreference = $savedErrActPref
                Fail "git fetch origin $branch failed:`n$fetchOut" 70
            }
            # Create the worktree pointing at origin/$branch. Use the
            # branch name (sanitized for filesystem) as the worktree dir.
            # `git worktree add <path> origin/<branch>` will create a
            # detached HEAD, which is fine for our read-only-compile use.
            $addOut = & git worktree add $repoRoot "origin/$branch" 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Pop-Location
                $ErrorActionPreference = $savedErrActPref
                Fail "git worktree add $repoRoot origin/$branch failed:`n$addOut" 70
            }
            Write-Err "[mwcc_debug] worktree created"
        } finally {
            Pop-Location
            $ErrorActionPreference = $savedErrActPref
        }
    }
}

# --- Sanity checks (post-worktree) ---
if (-not (Test-Path $repoRoot))   { Fail "repo not found: $repoRoot" }
if (-not (Test-Path $mwccExe))    { Fail "mwcceppc.exe not found: $mwccExe" }
if (-not (Test-Path $stockDll))   { Fail "stock DLL not found: $stockDll" }

# --- Lock acquisition ---
if (Test-Path $lockFile) {
    $holder = Get-Content $lockFile -Raw
    $age = (Get-Date) - (Get-Item $lockFile).LastWriteTime
    # Try to detect stale lock -- extract PID, see if process still alive
    $holderPid = $null
    if ($holder -match 'pid=(\d+)') { $holderPid = [int]$Matches[1] }
    $stale = $false
    if ($holderPid) {
        $proc = Get-Process -Id $holderPid -ErrorAction SilentlyContinue
        if (-not $proc) { $stale = $true }
    } elseif ($age.TotalMinutes -gt 30) {
        $stale = $true
    }
    if ($stale) {
        Write-Err "WARNING: stale lock from PID=$holderPid (age $($age.TotalMinutes.ToString('F1'))min); breaking"
        Remove-Item -Force $lockFile
    } else {
        Fail "lock held by PID=$holderPid (age $($age.TotalMinutes.ToString('F1'))min); content: $holder" 75
    }
}
"pid=$PID start=$(Get-Date -Format o) src=$srcRel" | Set-Content $lockFile

# --- Stale stock-backup detection ---
if (Test-Path $stockBackup) {
    Write-Err "WARNING: stale stock backup at $stockBackup -- restoring before proceeding"
    Move-Item -Force $stockBackup $stockDll
}

# --- Sync repo (unless suppressed) ---
# PS 5.1 treats native-command stderr (even normal progress output) as an
# error when ErrorActionPreference=Stop. Relax it locally for the git call.
if ($env:MWCC_DEBUG_NO_PULL -ne "1") {
    Push-Location $repoRoot
    $savedErrActPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($useWorktree) {
            # Worktrees are detached HEAD on origin/<branch>. To resync,
            # fetch + reset to origin/<branch>. Forceful: discards any
            # accidental local mods in the worktree (which shouldn't exist
            # since the worktree is auto-managed and read-only-compile).
            $fetchOut = & git fetch origin $branch 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Write-Err "git fetch origin $branch failed:"
                Write-Err $fetchOut
                Remove-Item -Force $lockFile -ErrorAction SilentlyContinue
                Pop-Location
                $ErrorActionPreference = $savedErrActPref
                Fail "could not sync worktree at $repoRoot" 70
            }
            $resetOut = & git reset --hard "origin/$branch" 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Write-Err "git reset --hard origin/$branch failed:"
                Write-Err $resetOut
                Remove-Item -Force $lockFile -ErrorAction SilentlyContinue
                Pop-Location
                $ErrorActionPreference = $savedErrActPref
                Fail "could not reset worktree to origin/$branch" 70
            }
        } else {
            # Master checkout — preserve the original pull-rebase behavior.
            # --autostash to preserve any local mods (the Windows repo
            # shouldn't have them, but be defensive).
            $pullOut = & git pull --rebase --autostash 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Write-Err "git pull failed:"
                Write-Err $pullOut
                Remove-Item -Force $lockFile -ErrorAction SilentlyContinue
                Pop-Location
                $ErrorActionPreference = $savedErrActPref
                Fail "could not sync repo at $repoRoot" 70
            }
        }
    } finally {
        Pop-Location
        $ErrorActionPreference = $savedErrActPref
    }
}

# --- Resolve source path + compile command ---
$srcAbs = Join-Path $repoRoot $srcRel
if (-not (Test-Path $srcAbs)) {
    Remove-Item -Force $lockFile -ErrorAction SilentlyContinue
    Fail "source file not found in repo: $srcAbs" 66
}

# Hardcode the standard Melee compile flags. This avoids depending on
# build.ninja being present/current on the Windows side, which would
# require running `python configure.py` etc.
$mwccArgs = @(
    "-nowraplines",
    "-cwd", "source",
    "-Cpp_exceptions", "off",
    "-proc", "gekko",
    "-fp", "hardware",
    "-align", "powerpc",
    "-nosyspath",
    "-fp_contract", "on",
    "-O4,p",
    "-multibyte",
    "-enum", "int",
    "-nodefaults",
    "-inline", "auto",
    "-pragma", "cats off",
    "-pragma", "warn_notinlined off",
    "-RTTI", "off",
    "-str", "reuse",
    "-DBUILD_VERSION=0",
    "-DVERSION_GALE01",
    "-maxerrors", "1",
    "-msgstyle", "std",
    "-warn", "off",
    "-warn", "iserror",
    "-requireprotos",
    "-i", (Join-Path $repoRoot "src"),
    "-i", (Join-Path $repoRoot "src\MSL"),
    "-i", (Join-Path $repoRoot "src\Runtime"),
    "-i", (Join-Path $repoRoot "extern\dolphin\include"),
    "-i", (Join-Path $repoRoot "src\melee"),
    "-i", (Join-Path $repoRoot "src\melee\ft\chara"),
    "-i", (Join-Path $repoRoot "src\sysdolphin"),
    "-lang=c",
    "-c", $srcAbs,
    "-o", "obj.o"
)

# --- Install DLL + run with cleanup ---
try {
    # Backup + install
    Copy-Item $stockDll $stockBackup
    Copy-Item $patchedDll $stockDll -Force
    Write-Err "[mwcc_debug] installed patched DLL"

    # Prepare workdir
    if (Test-Path $workDir) { Remove-Item -Recurse -Force $workDir }
    New-Item -ItemType Directory -Path $workDir -Force | Out-Null

    # Run with timeout. We use a background job (not Start-Process) because
    # Start-Process -ArgumentList joins args into a single string and Windows
    # re-parses, which destroys arguments containing spaces (e.g. -pragma "cats off").
    # The & call-operator with array splat preserves arg boundaries correctly.
    Push-Location $workDir
    $savedErrActPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $job = Start-Job -ScriptBlock {
            param($exe, $argList, $wd)
            Set-Location $wd
            # Redirect stdout+stderr to files so we can pass-through on errors
            & $exe @argList 2>"$wd\stderr.txt" | Out-File -FilePath "$wd\stdout.txt" -Encoding ASCII
            $LASTEXITCODE
        } -ArgumentList $mwccExe, $mwccArgs, $workDir

        $completed = Wait-Job $job -Timeout $timeoutSecs
        if ($null -eq $completed) {
            Write-Err "[mwcc_debug] compile timed out after ${timeoutSecs}s; killing"
            Stop-Job $job -ErrorAction SilentlyContinue
            $compileExit = 124
        } else {
            $compileExit = Receive-Job $job
            if ($null -eq $compileExit) { $compileExit = 0 }
        }
        Remove-Job $job -Force -ErrorAction SilentlyContinue
        $sw.Stop()
        Write-Err "[mwcc_debug] compile exit=$compileExit elapsed=$($sw.Elapsed.ToString('mm\:ss\.fff'))"

        # Pass through mwcc's stderr/stdout if there were issues
        if ($compileExit -ne 0) {
            $mwccStderr = Get-Content "$workDir\stderr.txt" -Raw -ErrorAction SilentlyContinue
            if ($mwccStderr) {
                Write-Err "[mwcc_debug] mwcceppc stderr:"
                Write-Err $mwccStderr
            }
            $mwccStdout = Get-Content "$workDir\stdout.txt" -Raw -ErrorAction SilentlyContinue
            if ($mwccStdout) {
                Write-Err "[mwcc_debug] mwcceppc stdout:"
                Write-Err $mwccStdout
            }
        }
    } finally {
        Pop-Location
        $ErrorActionPreference = $savedErrActPref
    }

    # --- Emit pcdump.txt to stdout ---
    if (-not (Test-Path $pcdumpFile)) {
        Fail "no pcdump.txt produced (compile exit=$compileExit)" 1
    }
    if ((Get-Item $pcdumpFile).Length -eq 0) {
        Fail "pcdump.txt is empty (compile exit=$compileExit)" 1
    }
    # Write raw bytes to stdout. Avoid Get-Content because it would do encoding
    # conversion. Use .NET to write the raw file content.
    $stdoutStream = [Console]::OpenStandardOutput()
    $bytes = [System.IO.File]::ReadAllBytes($pcdumpFile)
    $stdoutStream.Write($bytes, 0, $bytes.Length)
    $stdoutStream.Flush()
    Write-Err "[mwcc_debug] emitted $($bytes.Length) bytes"

    # Note: still exit non-zero if compile failed, even though we emitted partial output.
    if ($compileExit -ne 0) {
        exit $compileExit
    }
}
finally {
    # Always restore stock DLL
    if (Test-Path $stockBackup) {
        Move-Item -Force $stockBackup $stockDll
        Write-Err "[mwcc_debug] restored stock DLL"
    }
    # Release lock
    Remove-Item -Force $lockFile -ErrorAction SilentlyContinue
}
