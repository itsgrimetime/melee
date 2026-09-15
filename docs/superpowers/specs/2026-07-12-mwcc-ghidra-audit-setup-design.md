# MWCC Ghidra Audit Setup Design

## Problem

Issue #1239 was produced by invoking a hard-coded Ghidra 10.1.5 installation
directly against `mwcceppc.exe`. On Apple Silicon that release launches the
x86_64 native decompiler under translation. The PE loader completes, but the
Decompiler Switch Analyzer blocks while registering the native decompiler and
never observes Ghidra's per-file analysis timeout. The same compiler binary,
SHA-256
`ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c`,
finishes full analysis with the configured native-arm64 Ghidra 12.0.1 in 82
seconds.

The repository already contains the correct MWCC-specific entry point at
`tools/mwcc_debug/scripts/setup_ghidra.sh`, but it is not discoverable through
`melee-agent`, has no outer wall-clock watchdog, and treats any existing
`.rep` directory as a complete import. An interrupted empty project is
therefore silently accepted on the next run.

## Decision

Harden the existing workflow and expose it as
`melee-agent debug retro ghidra-setup`. Do not add another general-purpose
Ghidra importer and do not extend the canonical Melee-DOL Ghidra cache with PE
semantics.

The Python implementation is the source of truth. The existing shell script
becomes a compatibility launcher for the branch-local CLI so direct users and
agents receive the same detection, timeout, validation, and repair behavior.

## Command contract

```text
melee-agent debug retro ghidra-setup
    [--project-dir PATH]
    [--analysis-timeout SECONDS]
    [--wall-timeout SECONDS]
    [--repair]
    [--json]
```

Defaults:

- project directory:
  `tools/mwcc_debug/ghidra_project`
- project name: `mwcceppc`
- program: `/mwcceppc.exe`
- analysis timeout: 300 seconds
- outer wall timeout: 420 seconds
- compiler: `build/compilers/GC/1.2.5n/mwcceppc.exe`
- compiler identity: the exact SHA-256 above

`--project-dir` supports isolated acceptance and recovery runs without
overwriting the established project. The project name and compiler identity
remain fixed so the command cannot accidentally certify a different PE.

Successful JSON output uses schema `mwcc-ghidra-setup.v1` and records status
(`ready`, `imported`, or `repaired`), detected install/headless/native
decompiler paths, compiler SHA-256, project/program identity, function count,
and elapsed seconds. Text output presents the same facts compactly.

## Detection and native preflight

Reuse `src.cli.ghidra.detect.detect_ghidra_install()` rather than reproducing
Homebrew path discovery. Resolve `support/analyzeHeadless` under the detected
installation and reject a missing or non-executable launcher.

On macOS, require the host-native decompiler executable:

- `arm64`/`aarch64` -> `Ghidra/Features/Decompiler/os/mac_arm_64/decompile`
- `x86_64`/`amd64` -> `Ghidra/Features/Decompiler/os/mac_x86_64/decompile`

This check rejects the exact obsolete x86-only-on-arm64 configuration that
caused #1239. Other platforms require the detected Ghidra installation and
headless launcher but do not invent an unsupported architecture mapping.

## Import, timeout, and validation

All headless processes run through the existing process-group timeout helper,
so a wall timeout kills the Java process and native decompiler children. The
import command retains Ghidra's own `-analysisTimeoutPerFile` bound as a second
line of defense. Timeout, nonzero exit, `Analysis timed out`, cancellation,
or fatal analyzer text is failure even if Ghidra saved a partial project.

A bundled headless post-script, `MwccAuditStatus.java`, validates every reused
or newly imported project. It must emit one parseable status marker containing
the current program's executable SHA-256 and function count. Validation
succeeds only when:

- project and `/mwcceppc.exe` open successfully;
- executable SHA-256 equals the fixed compiler SHA-256;
- function count is greater than zero;
- the subprocess exits zero without timeout/fatal markers.

The `.rep` directory alone is never proof of readiness.

## Recovery and retention

Without `--repair`, an invalid existing project fails closed and prints the
exact retry command. With `--repair`, preserve rather than delete the existing
`.gpr` and `.rep` artifacts by atomically renaming them with a shared
`.invalid-YYYYmmddTHHMMSSZ` suffix. Then import into the canonical project name
and validate the result. If import or validation fails, retain both the
quarantined prior project and the failed new project for diagnosis.

The command creates a missing project directory. It never mutates a valid
project and a valid rerun is idempotent.

## Discoverability and documentation

The new Typer leaf appears automatically in `debug retro --help` and the live
capability inventory. Add task aliases for `MWCC Ghidra compiler audit` and
`stripped compiler callsite audit`, update the `mwcc-retro` skill to route
static compiler audits through this command, and update
`tools/mwcc_debug/scripts/setup_ghidra.sh` to delegate to the branch-local CLI.

## Testing and acceptance

Unit and CLI tests use fake Ghidra installations and a mocked process-group
runner. They prove host-native selection, exact SHA enforcement, wall timeout
classification, fatal/analysis-timeout rejection, status-marker validation,
idempotent reuse, incomplete-project rejection, retained repair, CLI output,
shell delegation, and capability search.

Real acceptance uses the exact compiler PE in an isolated project directory:

1. current detected Ghidra import exits zero within 420 seconds;
2. status validation reports the exact compiler SHA and a nonzero function
   count;
3. a second run returns `ready` without re-analysis;
4. no Java/native-decompiler process remains;
5. the focused tests, shell syntax check, Ruff, and repository build pass.

This resolves #1239's operational failure. It unblocks evidence acquisition
for #1240 but does not claim the function/call/string inventory is the
exhaustive semantic PCode lifetime proof required by that separate issue.
