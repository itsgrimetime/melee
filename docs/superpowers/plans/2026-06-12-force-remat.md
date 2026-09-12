# Plan: mwcc-debug force-remat diagnostic override

1. Add regression tests first.
   - CLI help exposes `--force-remat` / `--force-remat-fn`.
   - Local dump fake-wibo test proves the actual child env contains
     `MWCC_DEBUG_FORCE_REMAT` and function scope.
   - Remote dump fake-Popen test proves cmd.exe env forwarding.
   - Remote default-output test proves forced runs avoid canonical cache
     contamination.
   - C harness includes `mwcc_debug.c`, parses rules, applies them to a fake IG
     array, and checks bit `0x10` set/clear behavior plus function scoping.

2. Implement DLL support in `tools/mwcc_debug/mwcc_debug.c`.
   - Add `IG_FLAG_REMAT_ALT_OPERAND`.
   - Add parser state and helper for `class:ig=copy|literal`.
   - Add hook/trampoline for `0x4CE1A0`, applying rules before the original
     routine runs.
   - Log skipped/unreachable rules for out-of-range, physical-register, null,
     spilled, slot-mismatch, and no-remat-record cases.
   - Parse env in `DllMain` and install the hook.

3. Implement CLI support in `tools/melee-agent/src/cli/debug/__init__.py`.
   - Add `--force-remat` and `--force-remat-fn` to local and remote dump.
   - Validate unsafe shell characters.
   - Pass env vars to local child and remote command.
   - Include remat options in forced-run cache skip, diagnostic warning, diff
     function priority, and multi-function scoping guard.

4. Verify.
   - Run focused pytest for the new tests.
   - Build the patched DLL.
   - Smoke `melee-agent debug dump local --help`.
   - Run an issue-list smoke, commit to `master`, refresh editable install, and
     resolve #579.
