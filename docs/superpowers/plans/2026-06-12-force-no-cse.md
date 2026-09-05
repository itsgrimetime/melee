# Force-No-CSE IRO Veto Implementation Plan

> **For agentic workers:** Use subagent-driven development or independent review for the implementation. This plan intentionally avoids backend register-force approximations.

**Goal:** Resolve issue #602 by adding a robust, function-scoped `--force-no-cse` diagnostic hook that can veto selected IRO CommonSubs replacements by the node IDs printed in `Replacing common sub at X with Y`.

**Design:** `docs/superpowers/specs/2026-06-12-force-no-cse-design.md`

## Tasks

- [x] Add regression tests for `debug dump local/remote --force-no-cse`, CLI normalization/rejection, multi-function local scope refusal, diagnostic cache skipping, and DLL parser/matcher behavior.
- [x] Add CLI options and validation:
  - `--force-no-cse`
  - `--force-no-cse-fn`
  - `MWCC_DEBUG_FORCE_NO_CSE`
  - `MWCC_DEBUG_FORCE_NO_CSE_FUNCTION`
- [x] Update local/remote forced-run handling so force-no-CSE skips cache sync and is treated as diagnostic-only.
- [x] Add the DLL parser, function scope check, and CommonSubs hook at `0x44DF00`, delegating to the native trampoline when inactive.
- [x] Rebuild/deploy the DLL through `melee-agent debug dump setup --rebuild-dll`.
- [x] Run targeted pytest, compile checks, `debug dump doctor`, and command-level local smokes.
- [x] Use an independent subagent/code-review pass before resolving #602.

## Verdicts

- `mnDiagram_80240D94`: all 11 CommonSubs replacements reported by the baseline pcdump were vetoed one at a time with `--force-no-cse <at=with> --force-no-cse-fn mnDiagram_80240D94 --diff`; every run logged `[FORCE_NO_CSE] skip replacement ...` and every forced object still mismatched target bytes. Verdict: single-site clean CSE kill is not sufficient; this site is deeper than the VN kill primitive alone.
- `mnDiagram_InputProc`: all 48 CommonSubs replacements reported by the baseline pcdump were vetoed one at a time with `--force-no-cse <at=with> --force-no-cse-fn mnDiagram_InputProc --diff`; every run logged a skip and every forced object still mismatched target bytes. Verdict: the sampled Door-A-family site is also deeper than a single-site clean CSE kill.

## Review Follow-up

Independent review found one non-blocking scope edge case: an overlong `--force-no-cse-fn` could be accepted by the CLI and then ignored by the DLL's fixed 256-byte function-name buffer. The final implementation rejects overlong scopes in the CLI and fails closed in the DLL if direct env input truncates the scope.
