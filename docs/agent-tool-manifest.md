# Agent Tool Manifest

> **CLI commands and skills** are inventoried in
> [CAPABILITIES.md](CAPABILITIES.md) (generated; query with
> `melee-agent capabilities search <task>`). This manifest covers standalone
> `tools/*.py` scripts and setup paths the generated index does not.

Canonical commands for this fork. Prefer these names over remembered aliases or
older paths.

## Matching Field Guide

Read [MATCHING_GUIDE.md](MATCHING_GUIDE.md) before a prolonged source sweep.
Sections 1-2 cover measurement and residual classification; sections 9-10 route
to the right tool and explain when a terminal verdict is justified.

## Standalone Matching Tools

`decomp-search` finds matched source donors by whole-function or 32-instruction
window similarity. It also has a separate type-layout index for duplicate,
nearby, union-view, and cast-heavy records:

```bash
cd /Users/mike/code/decomp-search
.venv/bin/python -m dsearch.cli find <function> --min-match 99.5 --exclude-self-unit -k 10
.venv/bin/python -m dsearch.cli --backend hashed findw <function> --min-match 99.5 -k 10
```

Read `/Users/mike/code/decomp-search/.claude/skills/decomp-search/SKILL.md` for
the donor-transplant and type-layout workflows. Use `find` for whole-function
twins, `findw` for a construct buried in a larger function, and `stats` to see
which projects/backends are present in the local index.
If setup or imports fail, check `melee-agent issue list --tool decomp-search`
before debugging locally; known packaging regressions are tracked there.

`decomp-scripts` is the binary-archaeology toolbox for inspecting unknown PE/COFF
artifacts, pinning input hashes, running reproducible headless Ghidra exports,
and capturing/comparing MWCC allocator snapshots. Start at
`/Users/mike/code/decomp-scripts/README.md`; its `mwcc-compiler-notes.md` is the
supporting compiler-analysis reference. This is forensic tooling, not the normal
per-function compile/diff loop.

## Issue #1240 Retail PCode Previews

These `mwcc-retro` commands expose useful partial/candidate evidence:

```bash
melee-agent debug retro probe-backend-map <src.c> -f <function>
melee-agent debug retro probe-backend-ig <src.c> -f <function>
melee-agent debug retro probe-backend-pcode <src.c> -f <function>
melee-agent debug retro backend-candidate <src.c> -f <function> [--one-pass]
```

Treat their v1 outputs as diagnostics. They do not establish the exhaustive
lifetime proof tracked by local issue #1240, and the v2 request must remain
fail-closed until the proof registry is independently promoted. See
[mwcc-retro.md](mwcc-retro.md) for workflow-level guidance and
[`tools/mwcc_retro/README.md`](../tools/mwcc_retro/README.md) for artifact and
trust-boundary details.

## Bootstrap And Health

```bash
python tools/worktree-doctor.py --fix
python tools/worktree-doctor.py
```

The doctor checks fork tooling, `tools/checkdiff.py`, workflow scripts,
`orig/GALE01/sys/main.dol`, stale build state, `melee-agent`, `table-typer`,
`discord-search`, and optional `GHIDRA_INSTALL_DIR`. Use `--fix` for fresh
matching worktrees so safe local repairs happen before choosing targets.

## Repo-Local Skill

Canonical skill path:

```text
.claude/skills/decomp/SKILL.md
```

Codex should see the same skills through:

```text
.codex/skills
```

## Diff And Build

```bash
python tools/checkdiff.py <function>
python configure.py && ninja
```

Use `tools/checkdiff.py` or repo wrappers, not direct `objdiff-cli`, `wine`, or
`wibo` calls.

## Dolphin Runtime Evidence

Use `/melee-debug` for owned emulator sessions, persistent GDB commands, controller
input, and native PNG capture. Select this checkout's implementation explicitly:

```bash
MELEE_AGENT_USE_REPO_LOCAL=1 melee-agent dolphin --help
MELEE_AGENT_USE_REPO_LOCAL=1 melee-agent dolphin launch \
  --session /tmp/melee-doc-example --iso /path/to/GALE01.iso \
  --dolphin /path/to/Dolphin --interpreter
```

Launch stays alive as the owning service. Subsequent commands pass the same
`--session` path; stop through that endpoint. Each session has its own profile,
connection, input pipes, and capture artifacts. Do not use an implicit memory-engine
attachment when multiple emulators may be running. Capture quality checks do not
verify game state. See [dolphin-validation.md](dolphin-validation.md) for tested
contracts, reproduction commands, and limits.

## Source Shape Tools

```bash
tools/symbol-layout-analyzer.py <symbol-or-address>
melee-agent patterns inlines <source-file>
melee-agent patterns wrappers "gobj->user_data"
melee-agent patterns anti-patterns list
```

Singular forms also work: `melee-agent patterns wrapper` and
`melee-agent patterns anti-pattern`.

## Attempt Tracking

```bash
melee-agent attempts record <func> --match <pct> --outcome improved
melee-agent attempts show <func>
melee-agent attempts list
```

Use `--classification register-allocation`, `--blocker`, and `--retained` to
preserve useful state after experiments.

## Tool Issue Reporting

```bash
melee-agent issue report "short summary" --tool mwcc-debug --kind bug --function <func>
melee-agent issue list --status open
melee-agent issue show <id>
melee-agent issue resolve <id> --note "fixed by <summary-or-commit>"
```

Use this for tooling bugs, hangs, feature requests, papercuts, and blockers.
`issue report` auto-records the reporting agent, Codex/Claude session when
available, current worktree, and branch. If a tool hangs, interrupt it and
report the command plus last visible output in `--body`.

## Common Setup Paths

- Base DOL: `orig/GALE01/sys/main.dol`
- Shared base DOL: `~/.config/decomp-me/orig/GALE01/main.dol`
- State DB: `~/.config/decomp-me/agent_state.db`
- Discord archive CLI: `/Users/mike/code/discord-archive-mcp/.venv/bin/discord-search`
- Ghidra: set `GHIDRA_INSTALL_DIR`
- Table typer: `tools/table-typer/table-typer`
