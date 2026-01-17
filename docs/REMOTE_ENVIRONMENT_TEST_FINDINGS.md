# Remote Environment Testing Findings

**Date:** 2026-01-17
**Environment:** Containerized Linux (no GUI, no wine/wibo, no devkitPPC)
**Tester:** Claude Code (automated agent)

## Summary

This document records findings from testing the remote/containerized environment setup process documented in `REMOTE_ENVIRONMENT.md`. The goal was to identify issues, unclear instructions, and missing steps that would prevent a new user from successfully setting up the environment.

## Test Environment Initial State

- Python 3.11.14 installed
- ninja 1.11.1 installed
- Git available
- No wine/wibo
- No devkitPPC
- Environment variables partially set:
  - `GITHUB_TOKEN`: Set
  - `MELEE_DOL_URL`: Set
  - `PPC_REF_750CL_URL`: Set
  - `DECOMP_API_BASE`: NOT SET (critical for remote)

## Issues Found

### 1. CRITICAL: Missing melee-agent Installation Step

**Severity:** Critical
**Location:** REMOTE_ENVIRONMENT.md - Quick Start section

**Problem:** The documentation assumes `melee-agent` is available, but there are no instructions on how to install it. In a fresh container, running any `melee-agent` command fails because the package isn't installed.

**What happened:**
```bash
$ melee-agent --help
melee-agent: command not found
```

**Solution:** Add installation step:
```bash
cd tools/melee-agent
pip install -e .
```

Or for production:
```bash
pip install -e ./tools/melee-agent
```

---

### 2. MEDIUM: Main README References "Containers: Coming Soon"

**Severity:** Medium
**Location:** `.github/README.md` line 108-109

**Problem:** The main README says "# Containers\nComing soon." but `docs/REMOTE_ENVIRONMENT.md` already exists with container documentation.

**Solution:** Update README to link to the remote environment documentation.

---

### 3. MEDIUM: Undocumented `melee-agent setup` Commands

**Severity:** Medium
**Location:** REMOTE_ENVIRONMENT.md

**Problem:** The CLI has helpful setup commands that aren't documented:

```bash
$ melee-agent setup status
Decomp Setup Status

Base DOL: Not configured
  Run: melee-agent setup dol --auto

Config directory: /root/.config/decomp-me
```

The `melee-agent setup dol --auto` command can auto-discover main.dol from worktrees, which is useful for multi-worktree setups.

**Solution:** Add documentation for the setup subcommands.

---

### 4. LOW: Bootstrap Script Doesn't Handle 503 Errors Gracefully

**Severity:** Low
**Location:** `tools/bootstrap_orig.py`, `tools/bootstrap_ppc_ref.py`

**Problem:** When pre-signed URLs return HTTP 503 (service unavailable), the error message doesn't suggest:
1. The URL may have expired
2. How to obtain a new URL
3. Alternative manual download options

**What happened:**
```
Downloading main.dol...
Downloading to /home/user/melee/orig/GALE01/sys/main.dol...
  (URL not shown for security)

Error: HTTP 503 - Service Unavailable
```

**Solution:** Improve error messages to suggest common causes and next steps.

---

### 5. LOW: extract list Requires Build, Not Clearly Documented

**Severity:** Low
**Location:** REMOTE_ENVIRONMENT.md - Tool Compatibility Matrix

**Problem:** The matrix shows `extract list` as "Full" support, but it requires `build/GALE01/report.json` which only exists after a successful build. Running it before build gives:

```
Warning: report.json not found. Run 'ninja build/GALE01/report.json' to generate it.
```

**Solution:** Add note that build must complete first, or the tool needs report.json.

---

### 6. INFO: Partial Bootstrap Success Still Useful

**Severity:** Informational
**Location:** `tools/bootstrap_ppc_ref.py`

**Positive finding:** The PPC reference bootstrap script handles partial success well, downloading 2/3 PDFs even when one fails:

```
Bootstrap Summary:
  Downloaded: 2
  Skipped (already present): 0
  Failed: 1
  No URL provided: 0

PDFs available: 2/3
```

This is good UX - the tool continues despite partial failures.

---

### 7. INFO: checkdiff.py Auto-Download Works Well

**Severity:** Informational
**Location:** `tools/checkdiff.py`

**Positive finding:** The tool correctly advertises auto-download capability:
```
Remote environment support:
- Auto-downloads dtk (decomp-toolkit) if powerpc-eabi-objdump is not available
- Works in containers without devkitPPC installed
```

---

## Workflow Issues

### Cannot Complete Full Decompilation Workflow Without:

1. **main.dol** - Required for ninja build to succeed
2. **DECOMP_API_BASE** - Required for any scratch operations
3. **wine/wibo** - Required for MWCC compiler to run

### What CAN Be Done Without Full Setup:

- `melee-agent claim list/add/release` - Local SQLite operations work
- `melee-agent state status` - Local state works
- `melee-agent setup status` - Shows current config
- `python configure.py` - Generates build.ninja (but build fails without main.dol)

---

## Recommendations

### Immediate Documentation Updates

1. Add melee-agent installation instructions to Quick Start
2. Document the `melee-agent setup` subcommands
3. Add "Build Prerequisites" section explaining main.dol is required
4. Link REMOTE_ENVIRONMENT.md from main README's Containers section

### Future Improvements

1. Add `melee-agent setup check` command that validates entire environment
2. Consider providing a Docker image with pre-installed dependencies
3. Add retry logic with backoff for bootstrap HTTP errors

---

## Test Commands Run

```bash
# Environment check
echo $DECOMP_API_BASE  # Empty
echo $GITHUB_TOKEN     # Set
echo $MELEE_DOL_URL    # Set

# Installation (missing from docs)
cd tools/melee-agent && pip install -e .

# CLI test
melee-agent --help                 # Works after install
melee-agent setup status           # Works - shows DOL not configured
melee-agent claim list             # Works - local SQLite
melee-agent state status           # Works - no functions

# Build test
python configure.py                # Works
ninja                              # FAILS - main.dol missing

# Bootstrap test
python tools/bootstrap_orig.py     # FAILS - HTTP 503
python tools/bootstrap_ppc_ref.py  # PARTIAL - 2/3 PDFs

# Scratch test (requires server)
melee-agent scratch get test       # FAILS - no DECOMP_API_BASE
```

---

## Conclusion

The remote environment documentation is comprehensive but has a critical missing step (melee-agent installation) that would block any new user. After adding that step, the documentation flow is reasonable, though several medium-priority improvements would enhance the experience.

The biggest blocker for actual decompilation work in a containerized environment is obtaining `main.dol`, which requires either:
1. Pre-signed URL from secure storage (recommended)
2. Manual extraction from game ISO (requires Dolphin/local setup)
