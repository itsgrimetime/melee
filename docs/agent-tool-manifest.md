# Agent Tool Manifest

Canonical commands for this fork. Prefer these names over remembered aliases or
older paths.

## Bootstrap And Health

```bash
python tools/worktree-doctor.py
python tools/worktree-doctor.py --fix
```

The doctor checks fork tooling, `tools/checkdiff.py`, workflow scripts,
`orig/GALE01/sys/main.dol`, stale build state, `melee-agent`, `table-typer`,
`discord-search`, and optional `GHIDRA_INSTALL_DIR`.

## Repo-Local Skill

Canonical skill path:

```text
.agents/skills/decomp/SKILL.md
```

Agent-specific compatibility paths should point at the canonical skill:

```text
.claude/skills/decomp/SKILL.md
.codex/skills
```

## Diff And Build

```bash
python tools/checkdiff.py <function>
python configure.py && ninja
```

Use `tools/checkdiff.py` or repo wrappers, not direct `objdiff-cli`, `wine`, or
`wibo` calls.

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

## Common Setup Paths

- Base DOL: `orig/GALE01/sys/main.dol`
- Shared base DOL: `~/.config/decomp-me/orig/GALE01/main.dol`
- State DB: `~/.config/decomp-me/agent_state.db`
- Discord archive CLI: `/Users/mike/code/discord-archive-mcp/.venv/bin/discord-search`
- Ghidra: set `GHIDRA_INSTALL_DIR`
- Table typer: `tools/table-typer/table-typer`
