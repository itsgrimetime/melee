# Force-No-CSE IRO Veto Design

## Problem

Issue #602 needs a diagnostic hook for cases where MWCC's IRO common-subexpression/value-numbering pass collapses two source expressions into one cached value before backend register allocation. Existing `force-*` hooks operate at PCode, interference, coalescing, simplification, coloring, rematerialization, or scheduling time. Those hooks cannot recreate an IRO expression that has already been removed by CSE.

The concrete report is `mnDiagram_80240D94`: two textually identical `GetNameText((u8) arg2)` expressions are value-numbered into one cached value, but the target recomputes at each use. The tool needs to answer whether vetoing one CSE replacement reaches the desired backend shape.

## Constraints

- The hook must affect the actual CSE replacement, not only suppress logging.
- The hook must be opt-in and diagnostic-only.
- IRO node numbers are per function/pass and collision-prone, so CLI entry points should support function scoping and should refuse unscoped multi-function local runs by default.
- The default compiler path must delegate to the original MWCC function when no force-no-CSE rule is active.
- The hook should be selected by the reported `Replacing common sub at X with Y` node IDs.

## Design

Add a front-end IRO hook around the CommonSubs pass at `0x44DF00`, the function containing the only reference to `Replacing common sub at %d with %d` at `0x44E0B2`.

When `MWCC_DEBUG_FORCE_NO_CSE` is absent, the hook calls the original trampoline. When present, the hook runs a faithful C reimplementation of the native CommonSubs function, with a single additional decision point before the native replacement block:

```text
if current replacement is selected by MWCC_DEBUG_FORCE_NO_CSE:
    log [FORCE_NO_CSE] skip...
    continue without replacing/removing the redundant IRO node
else:
    perform the same native replacement/removal sequence
```

The env grammar is normalized by the CLI:

- `439=431` skips replacement of node `439` only when it would be replaced with `431`.
- `439` skips any replacement whose destination node is `439`.
- `iro:` may prefix either form for readability, for example `iro:439=431`.
- Decimal and `0x` hex are accepted by the CLI and normalized to decimal for the DLL.

Function scoping uses `MWCC_DEBUG_FORCE_NO_CSE_FUNCTION` and MWCC's front-end function context at `0x5875B8`; the emitted function name is `(*(ctx + 0xA) + 0xA)`, matching the native `Starting function %s` diagnostic.

## Validation

- Python CLI tests cover local/remote help, env propagation, normalization, malformed input rejection, diagnostic cache skipping, and multi-function scoping refusal.
- A C harness includes `mwcc_debug.c` under `MWCC_DEBUG_TEST` to exercise the parser and selected-rule matching directly.
- DLL setup/doctor smoke checks verify the rebuilt DLL advertises the new feature manifest and still loads under local wibo.
- A targeted local pcdump smoke verifies `--force-no-cse` produces a diagnostic-only dump without crashing.
