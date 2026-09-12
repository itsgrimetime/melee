# Melee Decompilation Project

This fork supports the reverse engineering, documentation, and maintenance of
Super Smash Bros. Melee (GALE01). The canonical matching campaign is complete:
the current upstream and fork refs mark every configured object as `Matching`.
A stale checkout or generated report may still show historical progress.

Treat the rebuilt DOL as a preservation constraint, not the remaining project
goal. Most new work should improve how accurately and clearly the code explains
the game without changing the binary.

## Current Priorities

Prefer work in roughly this order:

1. Understand and name address-based functions, data, parameters, and locals.
2. Replace unknown fields and raw offsets with evidence-backed structs, enums,
   and types.
3. Document behavior, invariants, ownership, units, state transitions, and
   non-obvious callbacks.
4. Remove stale TODOs, obsolete match-percentage notes, redundant casts, and
   decompiler residue.
5. Simplify awkward matched source when the cleaner form still reproduces the
   original binary.
6. Improve headers, module boundaries, and documentation pages without
   inventing APIs or semantics.

Do not begin a new broad matching campaign merely because old notes, local
state, or a stale build report mention unmatched code. Confirm against the
current branch first. Matching tools remain useful for regressions and for
proving that a cleanup is binary-preserving.

## Evidence Standard

Documentation is reverse-engineering work, not cosmetic annotation.

- Every documentation claim must be validated. Human validation is strongly
  preferred, especially for names and descriptions of game behavior.
- AI-generated confidence is not evidence. Contributors and maintainers are
  right to demand a higher burden of proof from AI-authored documentation.
- Every AI-authored semantic claim must be backed by a reproducible observation
  from the emulated game. Static code analysis may motivate a hypothesis, but
  it does not by itself validate what a field, function, state, or flag means.
- Read the implementation, all callers, important callees, neighboring module
  code, relevant structs, and any debug/assert strings before choosing a name.
- Prefer original names recoverable from strings or symbols. Otherwise use a
  conservative project-style name supported by behavior and call-site context.
- Distinguish known facts, strong inferences, and unresolved questions. Keep an
  address-based or offset-based name when the purpose is still uncertain.
- Never invent a field name. If its meaning cannot be validated, leave the
  offset-based name alone. A concise comment may record a data-backed
  hypothesis only when it is explicitly labeled tentative or unverified and is
  not repeated elsewhere as fact.
- Explain intent and constraints. Avoid comments that merely restate the C.
- Do not assign a semantic field name from one ambiguous access. Check all
  reads/writes and verify the field's offset and type.
- Renames must be complete across definitions, declarations, call sites,
  tables, and `config/GALE01/symbols.txt` where applicable.
- Preserve unusual source constructs when they are required for the match.
  If a construct looks fake or load-bearing, prove the replacement with a
  clean rebuild instead of deleting it on sight.
- Never introduce a new local, cast, or pointer derivation whose only purpose
  is to reproduce codegen. If the plain field or array access does not match,
  keep the previously accepted form and report the asm diff in the PR so the
  maintainers choose; do not replace one fake construct with another
  (see `docs/STYLE_GUIDE.md`, "Don't invent locals").

Useful evidence sources include repository xrefs, assert and report strings,
adjacent state-machine functions, data tables, the `melee-re/` submodule when
present, and cached Ghidra xrefs. Do not copy speculative names from unrelated
reverse-engineering projects.

## Validation Policy

Validation is a release gate for documentation and cleanup, not a follow-up
task. If a claim cannot be tested with existing tooling, first audit the tools
already available and then improve or build the required validation tooling.
Skipping validation because the tooling is missing is not acceptable.

For each semantic change, retain a compact evidence record in the PR
description or durable supporting documentation:

- the exact claim being tested;
- the GALE01 game state, setup, inputs, and relevant preconditions;
- the emulator, instrumentation, watchpoint, trace, or controlled patch used;
- the observed result, including a negative or contrasting case when useful;
- the static evidence that connects the runtime observation to the symbol or
  field being documented;
- who performed or reviewed the validation, with pending human review called
  out explicitly when applicable.

Runtime evidence should test the meaning of the claim, not merely show that the
game still boots. Prefer controlled comparisons: vary one input or value, watch
the relevant state change, and confirm the predicted effect. Record enough
detail for a skeptical maintainer to reproduce the result.

Purely structural statements such as an offset, size, caller relationship, or
binary identity may be validated by the binary, build artifacts, and xrefs.
Once a structural fact is given behavioral meaning, runtime validation in the
emulated game is required.

Human review is the preferred final validation. When a human reviewer is not
immediately available, the work must still include reproducible runtime
evidence and must not imply that human review occurred. Keep the change small
and clearly identify it as awaiting human confirmation.

## Match Preservation Is Absolute

No accepted cleanup or documentation change may reduce match percentage in any
way. Do not trade a regression in one function, object, section, relocation,
code metric, data metric, or linked metric for readability or aggregate gains
elsewhere.

- Establish a current, clean baseline before editing.
- Compare the same scope before and after the change; aggregate progress alone
  can hide a local regression.
- Require the expected GALE01 DOL hash and unchanged 100% object/section results
  for every affected translation unit.
- Treat stale reports, relaxed relocation settings, and successful compilation
  without binary verification as insufficient.
- Temporary local experiments may regress the match, but the regression must
  be fully removed before the change is committed, shared, or marked complete.
- If a desirable cleanup cannot preserve the match, document the constraint
  and leave the matched source unchanged.

## Before Adding Tooling

Before writing a new tool, script, or CLI command, run:

```bash
melee-agent capabilities search <task>
```

The fork already contains a large local toolset. Also check
`docs/agent-tool-manifest.md` when the task may live in the standalone
`decomp-search` or `decomp-scripts` repositories.

## Repository Layout

```text
melee/
├── src/melee/                 # Game source and co-located headers
├── src/sysdolphin/baselib/    # HAL's base library
├── src/dolphin/               # Dolphin SDK source
├── src/MetroTRK/              # Target Resident Kernel
├── src/MSL/ and src/Runtime/  # Runtime libraries
├── config/GALE01/             # Symbols, splits, and build configuration
├── docs/                      # Project and fork documentation
├── .github/CONTRIBUTING.md    # Upstream coding and PR conventions
├── .claude/skills/            # Fork-specific agent workflows
├── tools/                     # Build, analysis, and fork workflow tools
└── build/                     # Generated output; never hand-edit
```

Important files:

| Path | Purpose |
|---|---|
| `.github/CONTRIBUTING.md` | Authoritative upstream coding and PR rules |
| `docs/STYLE_GUIDE.md` | Maintainer-review-derived cleanup guidance |
| `docs/getting_started.md` | Project background and matching overview |
| `config/GALE01/symbols.txt` | Function and data symbol names |
| `config/GALE01/splits.txt` | Translation-unit and section boundaries |
| `config/GALE01/config.yml` | Original DOL hash and extraction settings |
| `docs/MATCHING_GUIDE.md` | Detailed matching/regression reference |
| `docs/agent-tool-manifest.md` | Short guide to local and standalone tools |
| `tools/workflow/README.md` | Fork/upstream branch workflow |

`~/.config/decomp-me/agent_state.db` stores local agent claims and completion
metadata. It is coordination state, not authoritative evidence about the
repository or its current match status.

## Documentation and Cleanup Workflow

1. Start from a current branch and inspect `git status`. Preserve unrelated
   edits and untracked artifacts.
2. Choose a narrow target: one function, struct, file, or coherent subsystem.
3. If parallel work is possible, claim a representative function before
   editing:

   ```bash
   melee-agent claim add <function>
   ```

4. Gather static evidence with fast repository searches first:

   ```bash
   rg -n "<symbol-or-field>" src config/GALE01
   melee-agent extract get <function>
   melee-agent struct show <struct>
   melee-agent struct offset <offset>
   ```

5. Use `/understand <target>` for the full naming and documentation workflow.
   Use `/ghidra` when whole-binary callers, callees, or debug strings are
   needed. For item code, also follow `/item-decomp` conventions.
6. Turn the proposed meaning into a falsifiable runtime test. Validate it in
   the emulated game and record the setup, observation, and static-to-runtime
   connection. Build validation tooling first when the required observation is
   not currently possible.
7. Make the smallest coherent change. Do not mix unrelated modules or mass
   mechanical cleanup into an evidence-heavy rename.
8. Format only changed C/C++ files with the repository's `.clang-format`.
9. Review the diff for unsupported semantic claims, incomplete renames, raw
   offsets that should be typed, and accidental code-generation changes.
10. Configure and build from the active checkout, then compare the affected
    objects and every progress metric with the clean baseline:

   ```bash
   python configure.py
   ninja
   python configure.py progress
   git diff --check
   ```

11. Seek human review of the claim and its evidence. Never state or imply that
    a human validated the work unless they actually did.
12. Only after the runtime evidence, match-preservation checks, and review
    status are recorded should documentation work be marked locally:

   ```bash
   melee-agent complete document <function>
   # Use --status partial when meaningful unknowns remain.
   ```

The build must continue to reproduce the expected GALE01 DOL, with no local or
aggregate match regression. A successful C compile alone is insufficient for a
cleanup that changes matched source.

## Cleanup Guidance

- Prefer proper field access over `M2C_FIELD`; add or refine a struct only when
  layout and cross-file uses support it.
- Prefer project types and enums over raw integers when the value domain is
  established.
- Remove unnecessary casts by fixing the underlying declaration or prototype.
- Put forward declarations in `forward.h` and definitions in `types.h`; avoid
  pulling `types.h` into public headers when a forward declaration suffices.
- Use fully qualified angle-bracket includes in headers. Follow the surrounding
  file and upstream guidance for source-file includes.
- Keep file-local types and data local when they are not a real shared API.
- Use lowercase `bool`, `true`, and `false` for boolean semantics.
- Prefer `int` for ordinary counters and indices unless width or signedness is
  semantically significant or match-sensitive.
- Use `ARRAY_SIZE` instead of duplicating a known array bound.
- Use Doxygen comments where API documentation is useful, but favor precise
  prose over boilerplate `@param` text.
- Do not leave obsolete match percentages or abandoned-investigation prose in
  source comments. Preserve durable compiler findings in `docs/` when they
  remain useful.
- Do not perform repository-wide formatting as part of a targeted cleanup.
- Keep semantic changes small enough that a reviewer can connect each name or
  comment directly to its static and runtime evidence.

The original source remains the conceptual gold standard. Local consistency is
helpful, but recovered original terminology and verified binary behavior take
precedence over generic style rules.

## Build and Worktree Safety

Run build and analysis commands from the current worktree. Never jump to the
shared main checkout from an isolated worktree, because another task may be
using it.

If a worktree lacks the original DOL or generated report, inspect and repair its
local prerequisites with:

```bash
python tools/worktree-doctor.py
python tools/worktree-doctor.py --fix
```

Generated build output, scratch candidates, compiler dumps, and local databases
do not belong in upstream PRs.

## Fork and Upstream Workflow

This fork carries a local tooling/documentation overlay on top of
`upstream/master`. The number of overlay commits is not a fixed invariant; use
the workflow scripts to inspect the current relationship instead of assuming
that `master` is exactly one commit ahead.

```text
upstream/master ── canonical project history
       └── master ── fork tooling/docs overlay and local integration
             ├── wip/* ── isolated longer-running work
             └── pr/*  ── clean branches based on upstream/master
```

Common commands:

```bash
./tools/workflow/status.sh
./tools/workflow/sync-upstream.sh --dry-run
./tools/workflow/sync-upstream.sh
./tools/workflow/create-pr.sh <topic>
./tools/workflow/update-pr.sh pr/<topic> [--amend]
./tools/workflow/pr-worktree.sh create <branch>
```

Read `tools/workflow/README.md` before unusual sync or recovery work. Do not
manually rebase or reset the shared fork merely to make its graph resemble an
old diagram.

Upstream PRs must contain only upstream-relevant source, headers, configuration,
and supporting documentation. Keep fork-only tooling, local state, agent notes,
scratch artifacts, and generated output out of them. PR descriptions should
state reviewable code and behavior changes plus verification, without naming
the private agent workflow used to produce them. Every PR opened against
`doldecomp/melee` with AI assistance must carry the upstream `ai-assisted`
label from the moment it is created (`gh pr create --label ai-assisted ...`);
if a PR was opened without it, add it with `gh pr edit <n> --add-label
ai-assisted` before asking for review.

## Skills and Tools

Primary post-matching skills:

- `/understand <target>` — analyze and document a function, struct, file, or
  module.
- `/ghidra` — query cached whole-binary xrefs and debug strings.
- `/item-decomp` — apply item-specific types and conventions.
- `/decomp-fixup <function>` — repair headers, signatures, and callers when a
  cleanup exposes a type/build issue.
- `/workflow`, `/prepare-pr`, `/sync-upstream` — manage fork and upstream work.

Useful CLI checks:

```bash
melee-agent patterns anti-pattern <code-snippet-or-list>
melee-agent patterns api <api-name>
melee-agent state status --category undocumented
melee-agent complete list
melee-agent issue list --available
```

Check `--help` before relying on an unfamiliar command. Report repeatable fork
tool failures through `melee-agent issue report`, and claim a queued tooling
issue before working on it.

## Matching Regression Fallback

Matching work is no longer the default activity. If a cleanup breaks the match:

1. Reduce the diff to the smallest responsible change.
2. Use `tools/checkdiff.py` or objdiff to identify whether the regression is
   code, data, relocation, or symbol-layout related.
3. Revert speculative cleanup before adding padding, casts, or compiler tricks.
4. Use `/decomp`, `/mismatch-db`, `/opseq`, or `/discord-knowledge` for ordinary
   regressions; escalate to `/mwcc-debug`, `/mwcc-retro`, or `/mwcc-inspect`
   only for demonstrated compiler-shape problems.

For unusual floating-point register allocation or local-frame behavior, see
`docs/ftCo_80095EFC-match-learning.md` and the mismatch pattern
`single-field-aggregate-fpr-allocation`. Historical campaign notes under
`docs/` are references, not statements of current project status.

## Durable Rules

- Use `rg`/`rg --files` for repository search.
- Use project CLI commands rather than raw decomp.me HTTP calls.
- Do not hand-edit generated files under `build/`.
- Do not overwrite, delete, or reformat unrelated work in a dirty tree.
- Keep changes narrow, evidence-backed, and binary-preserving.
- Treat missing runtime evidence as a blocker, not an invitation to infer.
- Never describe an AI-authored claim as human-validated without explicit human
  review.
- When context is compacted, retain the active target, worktree/branch, evidence
  gathered, unresolved uncertainties, files changed, and verification status.
