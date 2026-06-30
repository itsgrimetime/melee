# Trace-CSE Design

## Goal

Expose MWCC IRO CommonSubs replacement node IDs in ordinary mwcc-debug dumps so agents can target `--force-no-cse` without first guessing a fake veto rule.

## Context

The existing DLL hook at IRO CommonSubs (`0x44DF00`) can replay the native pass and veto selected replacements when `MWCC_DEBUG_FORCE_NO_CSE` is set. When no veto rules are set, the hook delegates to native MWCC and the local pcdump does not reliably expose the replacement IDs needed by `--force-no-cse`.

## Design

Add `MWCC_DEBUG_TRACE_CSE=1` as a trace-only mode. Trace mode enters the existing replayed CommonSubs path, logs each replacement as `IRO_CommonSub: replaced node <at> with <with>`, preserves the legacy `Replacing common sub at <at> with <with>` line, and never vetoes unless an independently scoped `MWCC_DEBUG_FORCE_NO_CSE` rule matches.

Trace and veto decisions are separate booleans. `allow_veto` is true only when force-no-CSE rules exist and the force-no-CSE function scope matches. `trace_replacements` is true only when trace-CSE is enabled and the trace-CSE function scope matches. This prevents an unscoped trace run from accidentally applying a scoped no-CSE rule to other functions in the same TU.

Expose the mode as `melee-agent debug dump local --trace-cse` and `debug dump remote --trace-cse`. Local dumps use `--function` as the default trace scope when `--trace-cse-fn` is absent. Remote dumps support explicit `--trace-cse-fn`. Trace runs are diagnostic and must skip baseline pcdump cache sync, like other forced/debug override runs.

## Validation

Add Python CLI tests for remote env propagation, local `--function` auto-scope, and doctor feature-manifest coverage. Add source-level DLL assertions for the new hook strings and preserve the existing force-no-CSE parser harness. Build the DLL after implementation and run a local trace-CSE smoke against `mnDiagram_80240D94`.
