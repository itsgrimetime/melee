# Addi Schedule Window Diagnostics

## Goal

Teach `mwcc-debug` scheduler diagnostics to explain non-load `addi`/`addi`
order windows from small-pattern near-matches without changing the existing
load-only force hook.

## Root Cause

`debug inspect explain-schedule` currently only understands same-base load
operand windows. Reports such as `addi:0x204>0x1fc` use final current-asm
function offsets from `tools/checkdiff.py --format json`, so the pcdump-only
load path cannot recognize them. The C hook also cannot force these windows
today because it has no final object offset identity.

## Design

- Preserve existing same-base load behavior and help text.
- Add a bounded checkdiff-asm fallback that runs only when the load explanation
  is missing and `--checkdiff-json` supplied `target_asm` and `current_asm`.
- Interpret non-load rule numbers as current-asm function offsets.
- Map those current instructions into target asm by instruction body and local
  order.
- Classify stack-local address materialization (`addi dst,r1,imm`) versus
  counter increments (`addi rN,rN,1`).
- Report the window as explainable but `not-forceable-by-current-hook`.
- Emit ranked source-shape suggestions for delaying local address
  materialization, anchoring the counter increment, narrowing local vector
  lifetime, and reordering the counter/local block.

## Implementation Tasks

1. Add `mwcc_debug.asm_windows` for checkdiff asm parsing and code-offset window
   detection.
2. Extend `schedule_explain` dataclasses with defaulted diagnostic fields and
   source reshape records.
3. Wire the asm fallback into `explain_schedule` after the existing load-window
   path returns `missing`.
4. Add `debug inspect explain-schedule --checkdiff-json`.
5. Keep `debug dump local --force-schedule` documented as same-base-load-only.

## Verification

- Unit tests for straddled addi code-offset windows and rendering.
- CLI regression test for reading checkdiff JSON.
- Existing same-base load schedule tests.
- Force-schedule help tests preserving the load-hook boundary.
- Manual smoke on `it_802BCB88` with `tools/checkdiff.py --format json
  --no-build` and `debug inspect explain-schedule --checkdiff-json`.
