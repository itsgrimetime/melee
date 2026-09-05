# Issue 1256: function-sliced DTK objdump

## Problem

Full-TU permuter objects contain the requested function plus neighboring
functions. The stock decomp-permuter scorer compares every instruction emitted
by `objdump_command`, so unchanged target bytes can receive a nonzero score and
unrelated suffix functions can distort candidate ranking.

## Implementation

1. Add an optional target-function selector to the DTK objdump adapter and
   `debug target dtk-objdump`. Select one exact `.fn NAME`/`.endfn NAME` block
   before converting instruction rows. Keep the unfiltered path unchanged.
2. Fail closed when the requested function is missing, appears more than once,
   has a mismatched or missing terminator, or contains no instruction rows.
3. Generate and repair permuter `objdump_command` values with the known
   `--function NAME`. Preserve that selector when adding remote melee/object
   roots and when probing the command in remote doctor.
4. Do not change decomp-permuter: its existing `shlex.split(command)` plus
   appended object path already supports wrapper arguments.

## Acceptance

- Unfiltered DTK conversion retains its current GNU objdump-shaped output.
- A multi-function disassembly emits only the requested function, retaining its
  original addresses, instruction bytes, assembly, and relocation operands.
- Two full-TU objects with identical target functions but different suffix
  functions produce identical filtered scorer input; the stock scorer gives an
  exact target a zero score.
- Missing, duplicate, unterminated/mismatched, and empty requested functions
  exit nonzero with actionable errors.
- Bootstrap, scorer setup, config generation/repair, remote settings rewriting,
  and remote doctor retain a function-bound objdump command.
- Focused tests, relevant config/remote/help tests, Ruff, compileall, and a final
  diff review pass.
