---
name: understand
description: Investigate and document a Melee function, translation unit, or struct using reproducible runtime evidence and binary-preservation checks. Use for post-matching documentation, conservative naming, and trials of the documentation workflow.
---

# Melee Documentation and Understanding

The matching campaign is complete. The deliverable is a small, accurate explanation
of the game, supported by evidence a maintainer can reproduce. Static analysis
starts the investigation; it does not establish behavioral meaning. A matching
binary establishes preservation, not correctness of a name or explanation.

Read the active checkout's `AGENTS.md` and `.github/CONTRIBUTING.md` before editing.
Use their evidence, naming, documentation-placement, and review requirements.
In particular, documentation lives inline at the declaration, not in `.dox`
files (see "Write the smallest useful documentation"). Existing comments,
field names, and other skills are research leads, not independent validation.

## Choose a testable scope

Accept a function, TU path, or struct. When choosing a TU, prefer a small module
with an observable effect and reachable game state. Select one coherent claim
within it first; a short TU can still have many callers and expensive validation.
Inventory the remaining functions without promising to document them all.

Inspect branch, status, current configuration, and prerequisites. Preserve unrelated
work and run all build/analysis commands from this checkout. Claim a representative
function with `melee-agent claim add <function>` before editing. If claimed by
someone else, select another target. Release your claim when work stops; don't use
completion metadata as a substitute for releasing an unfinished investigation.

Establish a fresh baseline before changing game source, headers, symbols, or
publishable game documentation. If prerequisites are missing, inspect and repair
with `python tools/worktree-doctor.py` and `--fix`. Record exact configure options,
revision, DOL hash, affected TU/section results, and complete progress metrics.
Do not infer baseline success from `Object(Matching, ...)` or a cached report.
If a fresh report disagrees with campaign status, record the discrepancy and
reconcile configuration/current refs before claiming global completion. Do not
turn a documentation trial into a broad matching campaign.

## Build a claim ledger

Keep a compact supporting record outside game source while investigating. For
each proposed name or statement, record:

- Exact claim and intended documentation location.
- Static anchors: symbols, call sites, offsets, types, debug strings, data tables.
- Status: structural fact, unvalidated behavioral hypothesis, or runtime-tested
  claim. Keep human-review status separate from runtime-test status.
- Falsifiable test, expected contrasting result, actual observation, artifact
  location, and remaining uncertainty.

Read the implementation, every caller/reference for the selected claim, important
callees, adjacent module code, and relevant struct definitions. Search identifiers
without requiring `(` so callback tables and pointer references are included:

```bash
rg -n '<symbol-or-field>' src config/GALE01
melee-agent extract get <function>
melee-agent struct show <struct>
```

Use `/ghidra` when repository references are insufficient for whole-binary xrefs
or strings, and `/item-decomp` for item conventions. Verify addresses against the
active configuration and binary; offset comments and cache entries can be stale.
Recover original terminology from debug strings where possible, but don't inflate
a string into proof of a broader game mechanic. Community knowledge and the
`melee-re/` submodule may suggest tests, not replace them.

Do not infer timing units, ownership, persistence, event meaning, or enum domains
from a suggestive name. For example, a field called `saved_language` does not
prove that its setter writes a memory card. Distinguish a function's input, stored
value, return value, and downstream effect when designing its contract.

## Validate meaning in the emulated game

For each semantic claim, specify GALE01 revision, state/setup, inputs,
preconditions, emulator/version, instrumentation, and the observation that would
falsify it. Vary one factor and include a negative or contrasting case where
useful. A boot, memory snapshot, or host-side reimplementation alone does not
validate a behavioral claim. A direct function-invocation experiment can validate
an API contract; it cannot by itself establish its normal game-event association.

Before adding tooling:

```bash
melee-agent capabilities search <task>
```

Also inspect `docs/agent-tool-manifest.md`, relevant command `--help`, and existing
tool implementation. An empty capability search is not proof that no tool exists.
For Dolphin, consult `/melee-debug` and inspect
`tools/melee-agent/src/dolphin_debug/`; verify its prerequisites and commands in
this environment before relying on them. Use an isolated Dolphin user directory
for controlled tests, with explicit game/profile paths. Don't terminate another
session or modify the normal profile as a side effect of a helper's defaults.

Audit the observation path itself: confirm game identity, loaded function bytes,
address/pointer resolution, and whether the instrumentation actually observes the
requested event. Do not describe flaky JIT breakpoints or successful connection
as a trace. If the required observation isn't possible, improve the existing
validation tooling or build the missing capability after the audit. Record the
specific failure and next test; never silently lower the evidence threshold.

Verify the imported tooling path as well as the shell working directory. An
installed `melee-agent` or `src.dolphin_debug` can resolve to a different checkout.
For local Dolphin experiments, use `PYTHONPATH="$PWD/tools/melee-agent"` and
inspect the imported module's `__file__` before testing local changes. For the
installed console entrypoint, `MELEE_AGENT_USE_REPO_LOCAL=1 melee-agent` selects
this checkout; `MELEE_AGENT_PRINT_SRC_CLI=1` prints the chosen CLI path.

Use the owned-session commands in `/melee-debug` for repeated reads, execution,
controller input, and native screenshots. Keep the launch service alive and pass
its explicit `--session` path to each client. A nonblack capture or issued input
is not evidence that the target game state was reached.

For a bounded API contract, consider an isolated interpreter session before
investing in menu navigation. Require an acknowledged stop, verified PC and
function bytes, explicit ABI setup, bounded stepping, return/storage observations,
and restoration checks. Do not generalize this to normal event timing or UI
behavior. The [setter experiment](../../../tools/dolphin-lblanguage-contract.py)
is a narrow reproducible example, not a general-purpose function-call API.
Do not equate a daemon's success flag with a stop: inspect its underlying reply.

Retain reproduction commands or a reusable harness plus actual results, including
controlled patches and their restoration. Identify who performed the test and
whether human confirmation is still pending. Keep ROMs, generated output,
profiles, saves, and local databases out of the patch.

## Write the smallest useful documentation

Promote only validated claims. Leave uncertain address/offset names unchanged.
Keep tentative hypotheses in the evidence record; do not scatter speculative
`@todo` comments through source. Explain intent, constraints, ownership, units,
or non-obvious contracts instead of restating assignments or adding boilerplate
`@param` text. Pure offsets, sizes, caller relationships, and binary identity may
be validated structurally; giving them behavioral meaning requires runtime proof.

Place documentation at the declaration; `.dox` files are retired (#2938,
#3461). Function docs go above the prototype in the header, or above the
`static` forward declaration in the C file for statics. Struct-field docs go on
the field: a trailing `///<` when the whole line fits in 80 columns, otherwise
a `///` or `/** */` block above the field. Every block-documented declaration
or field gets a blank line before the block and after the declaration;
one-line `///<` fields stay packed. `@file` blocks sit above the include guard.
Prose longer than a short paragraph goes in `docs/*.md` (Doxygen renders it as
a page) and is linked with `@ref`; `@dir` blocks may live in a markdown file.
Do not use the removed `@at`/`@sz` aliases; offsets belong in the `/* +NN */`
comments and sizes in `ASSERT_SIZE`. Respect upstream's restrictions on
AI-authored global names and record proposed names for review when applicable. Do not invent a rename merely to make the trial look productive.
For permitted renames, update definitions, declarations, call sites, callback/data
tables, and `config/GALE01/symbols.txt` together. Preserve address comments.

Treat type and source cleanup as separate, justified changes. Positivity alone
is not a reason to replace `int` with `u32`; 0/1 observations do not establish a
boolean domain. Prefer project types and established conventions, preserving
compiler-sensitive constructs until a clean comparison proves a replacement.
When a rename lets you remove an overlay or wrapper, try the plain field or
array access first. If it regresses the match, do not invent a replacement
local or pointer derivation to win the match back; maintainers reject those as
fake (#3451). Keep the previously accepted form and put the asm diff and the
attempted plain form in the PR description so the reviewer picks the shape.
Format only changed C/C++ files.

## Verify and hand off

Configure/build in this worktree, regenerate progress, and run `git diff --check`.
Require the expected GALE01 DOL hash and no regression in any affected object,
section, relocation, code, data, or linked metric relative to the baseline. Use
the same strict relocation settings before/after; do not relax comparison to
obtain a pass. Compilation or aggregate progress alone is insufficient. If a
cleanup regresses, remove the responsible change before sharing it; consult
`/decomp` only for a demonstrated matching regression.

Review each final semantic statement against its evidence record. Deliver a
reviewable diff and compact record of tests, observations, binary checks, unknowns,
and human-review status. Do not claim human validation without explicit review.
Stage only intended files if committing is in scope; never use `git add -A`.

Only use `melee-agent complete document <function>` after evidence and preservation
gates pass and review status is recorded. Use `--status partial` for a validated
subset with known omissions, not for speculative or blocked work. Check command
help for claim release without recording completion.

## When the user is testing this workflow

Retain the chosen TU, attempted claim, what the old workflow would have accepted,
what the trial actually demonstrated, and the resulting skill correction. An
honest blocked claim is useful trial evidence, but it is not finished game
documentation. Separate completed skill improvements from unfinished validation.
See [the lblanguage trial](references/lblanguage-trial.md) for a concrete example
of this distinction and its recorded limitations.
