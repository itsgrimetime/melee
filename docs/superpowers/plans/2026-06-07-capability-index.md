# Capability Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop agents from rebuilding tools that already exist by shipping a generated, tiered-auto-loaded, queryable `melee-agent capabilities` index (CLI commands + skills), a soft build-intent nudge hook, an audit-first rule, and a drift guard.

**Architecture:** A new Typer sub-app (`capabilities`) introspects the LIVE root Typer tree (via `typer.main.get_command` → click walk, so it can never go stale) plus `.claude/skills/*/SKILL.md` metadata. `search`/`show` are live; `generate` writes a compact `.claude/capabilities-brief.md` (auto-loaded by the session hook) and a full `docs/CAPABILITIES.md`. Two non-blocking nudge hooks (`UserPromptSubmit` for build-intent prompts, `PreToolUse` for writing a new tool file under `tools/`) inject "search first" context. A dedicated CI workflow + pre-commit hook fail on artifact drift.

**Tech Stack:** Python 3.11, Typer/Click, pytest + `typer.testing.CliRunner`, PyYAML, bash + python3 hooks, GitHub Actions.

**Source spec:** `docs/superpowers/specs/2026-06-06-capability-index-discoverability-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tools/melee-agent/src/cli/capabilities.py` | The `capabilities` sub-app: introspection, skill parsing, alias map, search/show/generate, audit logging. |
| `tools/melee-agent/src/cli/__init__.py` | Register `capabilities_app` on the root app (modify). |
| `tools/melee-agent/tests/test_capabilities.py` | Unit tests for introspection, skill parsing, search, generate. |
| `tools/melee-agent/tests/test_capabilities_hooks.py` | Tests for the two hook helper scripts. |
| `.claude/capabilities-brief.md` | Generated compact tier (auto-loaded). |
| `docs/CAPABILITIES.md` | Generated full inventory (on-demand). |
| `docs/agent-tool-manifest.md` | Add bidirectional cross-link (modify, do NOT delete). |
| `.claude/hooks/emit-capabilities-context.py` | Builds the SessionStart `additionalContext` JSON (escaped) from the brief. |
| `.claude/hooks/session-startup.sh` | Call the emitter unconditionally (modify). |
| `.claude/hooks/build-intent-nudge.py` | Soft `UserPromptSubmit` nudge on build-intent prompts. |
| `.claude/hooks/build-intent-tooluse-nudge.py` | Soft `PreToolUse` nudge on Write/Edit of a new tool file under `tools/`. |
| `.claude/settings.json` | Register the `UserPromptSubmit` + `PreToolUse` hooks (modify). |
| `CLAUDE.md` | Add the audit-first rule block (modify). |
| `.claude/skills/decomp/SKILL.md`, `.claude/skills/workflow/SKILL.md` | Add an audit-first line (modify). |
| `.github/workflows/capabilities-drift.yml` | CI drift guard. |
| `.pre-commit-config.yaml` | Local drift guard (modify/create). |

**Conventions:** run all `melee-agent`/`pytest` commands from the worktree root `tools/melee-agent` dir unless noted. Tests import `from src.cli...`. Never run `python -m src.cli` from the repo root (imports the main checkout, not the worktree — see spec grounding facts).

---

### Task 1: Scaffold the `capabilities` sub-app and register it

**Files:**
- Create: `tools/melee-agent/src/cli/capabilities.py`
- Modify: `tools/melee-agent/src/cli/__init__.py` (after line 102, the last `add_typer`)
- Test: `tools/melee-agent/tests/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/test_capabilities.py
from typer.testing import CliRunner

from src.cli.capabilities import capabilities_app

runner = CliRunner()


def test_capabilities_help_lists_subcommands():
    res = runner.invoke(capabilities_app, ["--help"])
    assert res.exit_code == 0
    out = res.output.lower()
    assert "search" in out
    assert "show" in out
    assert "generate" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.cli.capabilities'`

- [ ] **Step 3: Write minimal implementation**

```python
# tools/melee-agent/src/cli/capabilities.py
"""melee-agent capabilities — a discoverable, queryable index of existing CLI
commands and skills, so agents stop rebuilding tools that already exist.

`search` and `show` introspect the LIVE Typer tree (never stale); `generate`
writes the auto-loaded brief and the full inventory doc.
"""
from __future__ import annotations

import typer

capabilities_app = typer.Typer(
    help="Discover existing CLI commands and skills before building new ones.",
    no_args_is_help=True,
)


@capabilities_app.command("search")
def search(task: str = typer.Argument(..., help="What you are trying to do.")) -> None:
    """Find existing commands/skills matching a task description."""
    typer.echo(f"(not yet implemented) search: {task}")


@capabilities_app.command("show")
def show(group: str = typer.Argument(None, help="Command group or skill to detail.")) -> None:
    """Show full detail for a group (or everything)."""
    typer.echo("(not yet implemented) show")


@capabilities_app.command("generate")
def generate() -> None:
    """Regenerate the capability brief and full inventory doc."""
    typer.echo("(not yet implemented) generate")
```

- [ ] **Step 4: Register the sub-app on the root app**

In `tools/melee-agent/src/cli/__init__.py`, add the import near the other `.extract`/`.layout` imports (around line 51):

```python
from .capabilities import capabilities_app
```

And add the registration immediately after line 102 (`app.add_typer(layout_app, name="layout")`):

```python
app.add_typer(capabilities_app, name="capabilities")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -v`
Expected: PASS

Run: `cd tools/melee-agent && MELEE_AGENT_PRINT_SRC_CLI=1 melee-agent capabilities --help` then `melee-agent capabilities --help`
Expected: help lists `search`, `show`, `generate`.

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/cli/capabilities.py tools/melee-agent/src/cli/__init__.py tools/melee-agent/tests/test_capabilities.py
git commit -m "feat(capabilities): scaffold capabilities sub-app and register it"
```

---

### Task 2: Live Typer tree introspection (with help fallback)

**Files:**
- Modify: `tools/melee-agent/src/cli/capabilities.py`
- Test: `tools/melee-agent/tests/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tools/melee-agent/tests/test_capabilities.py
from src.cli import capabilities as cap


def test_command_capabilities_include_known_commands():
    caps = cap.command_capabilities()
    names = {c.name for c in caps}
    # Known leaf commands from the real tree (verified against live introspection):
    assert "debug target score-source" in names   # NOTE: there is NO `debug score`
    assert "extract files" in names
    assert "struct verify" in names
    # Every command has a non-empty invoke string and a summary fallback.
    for c in caps:
        assert c.invoke.startswith("melee-agent ")
        assert isinstance(c.summary, str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py::test_command_capabilities_include_known_commands -v`
Expected: FAIL with `AttributeError: module 'src.cli.capabilities' has no attribute 'command_capabilities'`

- [ ] **Step 3: Write minimal implementation**

Add to `tools/melee-agent/src/cli/capabilities.py` (top-level, above the commands):

```python
from dataclasses import dataclass, field


@dataclass
class Capability:
    kind: str                       # "command" | "skill"
    name: str                       # e.g. "debug target score-source" or "ghidra"
    summary: str                    # one-line description
    invoke: str                     # how to run it
    group: str = ""                 # top-level group for commands; "" for skills
    keywords: list[str] = field(default_factory=list)


# CRITICAL (verified): Typer sub-apps are lazily-populated TyperGroups — walking
# `.commands` directly yields only 3 leaves. Use the lazy-safe list_commands(ctx)
# + get_command(ctx, name) API (yields the real 215 leaves) and skip hidden cmds
# (the `issues` alias, `debug inspect ceiling`, etc.).
def _walk_click(cmd, ctx, prefix: str = ""):
    """Yield (full_name, click_command) for every VISIBLE leaf command."""
    import click

    try:
        names = cmd.list_commands(ctx)
    except Exception:
        names = list(getattr(cmd, "commands", {}).keys())
    for name in sorted(names):
        sub = cmd.get_command(ctx, name)
        if sub is None or getattr(sub, "hidden", False):
            continue
        full = f"{prefix}{name}"
        if isinstance(sub, click.Group):
            yield from _walk_click(sub, ctx, prefix=f"{full} ")
        else:
            yield full, sub


def _help_text(click_cmd) -> str:
    """short_help -> first line of help/docstring -> ''. Typer folds the command
    callback docstring into `.help`, so get_short_help_str covers the chain."""
    try:
        short = click_cmd.get_short_help_str(limit=100)
    except Exception:
        short = ""
    if short:
        return short.strip()
    if click_cmd.help:
        return click_cmd.help.strip().splitlines()[0].strip()
    return ""


def command_capabilities(root_app=None) -> list[Capability]:
    """Introspect the LIVE root Typer app into a flat list of command capabilities.
    `root_app` is injectable for tests; defaults to the real CLI app."""
    import typer.main
    import click

    if root_app is None:
        from src.cli import app as root_app  # lazy import avoids circular import

    root = typer.main.get_command(root_app)
    ctx = click.Context(root, info_name="melee-agent")
    caps: list[Capability] = []
    for full_name, cmd in _walk_click(root, ctx):
        group = full_name.split(" ", 1)[0]
        caps.append(
            Capability(
                kind="command",
                name=full_name,
                summary=_help_text(cmd),
                invoke=f"melee-agent {full_name}",
                group=group,
                keywords=full_name.replace("-", " ").split(),
            )
        )
    return caps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/capabilities.py tools/melee-agent/tests/test_capabilities.py
git commit -m "feat(capabilities): introspect live Typer tree into Capability list"
```

---

### Task 3: SKILL.md metadata parsing (frontmatter + H1/prose fallback)

**Files:**
- Modify: `tools/melee-agent/src/cli/capabilities.py`
- Test: `tools/melee-agent/tests/test_capabilities.py`

> Spec grounding: `prepare-pr`, `sync-upstream`, `workflow` SKILL.md have NO YAML frontmatter (start with `# H1`). The parser MUST fall back to H1 title + first prose paragraph so these are not dropped.

- [ ] **Step 1: Write the failing test**

```python
# add to tools/melee-agent/tests/test_capabilities.py
import textwrap


def test_parse_skill_frontmatter(tmp_path):
    d = tmp_path / "decomp"
    d.mkdir()
    (d / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: decomp
        description: Use when matching Melee functions against asm diffs.
        ---

        # Melee Decompilation
        body
    """))
    c = cap.parse_skill(d / "SKILL.md")
    assert c.name == "decomp"
    assert "matching Melee functions" in c.summary


def test_parse_skill_fallback_without_frontmatter(tmp_path):
    d = tmp_path / "workflow"
    d.mkdir()
    (d / "SKILL.md").write_text(textwrap.dedent("""\
        # Workflow Management Skill

        Use this skill to manage git branches and prepare changes for upstream PRs.

        ## When to Use
    """))
    c = cap.parse_skill(d / "SKILL.md")
    assert c.name == "workflow"  # falls back to directory name
    assert "manage git branches" in c.summary


def test_skill_capabilities_does_not_drop_frontmatterless_skills():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    caps = cap.skill_capabilities(repo)
    names = {c.name for c in caps}
    # These three lack frontmatter in the real repo and must still appear:
    assert {"prepare-pr", "sync-upstream", "workflow"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -k skill -v`
Expected: FAIL with `AttributeError: ... has no attribute 'parse_skill'`

- [ ] **Step 3: Write minimal implementation**

Add to `tools/melee-agent/src/cli/capabilities.py`:

```python
import re
from pathlib import Path


def parse_skill(skill_md: Path) -> Capability:
    """Parse a SKILL.md into a Capability. Uses YAML frontmatter when present,
    else falls back to the H1 title and first prose paragraph (3 repo skills
    have no frontmatter)."""
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    dir_name = skill_md.parent.name
    name = dir_name
    desc = ""

    if text.lstrip().startswith("---"):
        body_start = text.find("---") + 3
        end = text.find("\n---", body_start)
        if end != -1:
            import yaml

            try:
                meta = yaml.safe_load(text[body_start:end]) or {}
            except yaml.YAMLError:
                meta = {}
            name = str(meta.get("name") or dir_name).strip() or dir_name
            desc = str(meta.get("description") or "").strip()

    if not desc:
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("---"):
                continue
            desc = s
            break

    return Capability(
        kind="skill",
        name=name,
        summary=desc,
        invoke=f"/{dir_name}",
        keywords=[dir_name] + dir_name.replace("-", " ").split(),
    )


def skill_capabilities(repo_root: Path) -> list[Capability]:
    skills_dir = repo_root / ".claude" / "skills"
    caps: list[Capability] = []
    if not skills_dir.is_dir():
        return caps
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        caps.append(parse_skill(skill_md))
    return caps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -k skill -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/capabilities.py tools/melee-agent/tests/test_capabilities.py
git commit -m "feat(capabilities): parse SKILL.md metadata with H1/prose fallback"
```

---

### Task 4: Task-alias map + search ranking + no-match + audit logging

**Files:**
- Modify: `tools/melee-agent/src/cli/capabilities.py`
- Test: `tools/melee-agent/tests/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tools/melee-agent/tests/test_capabilities.py
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_all_alias_targets_resolve_to_real_capabilities():
    caps = cap.all_capabilities(REPO)
    valid = {c.name for c in caps}
    for key, targets in cap.TASK_ALIASES.items():
        for t in targets:
            assert t in valid, f"alias '{key}' -> unknown target '{t}'"


def test_search_relevance_regression():
    """Each documented near-rebuild query must surface the right tool."""
    assert "debug target score-source" in [c.name for c in cap.run_search("scorer", REPO)]
    assert "extract files" in [c.name for c in cap.run_search("per-file progress", REPO)]
    assert any(c.name in {"ghidra", "commit check-callers"} for c in cap.run_search("find callers", REPO))
    assert any(c.name in {"mwcc-debug", "mwcc-inspect"} for c in cap.run_search("register allocation", REPO))


def test_search_cli_no_match_wording():
    res = runner.invoke(capabilities_app, ["search", "zzz-nonexistent-capability-xyz"])
    assert res.exit_code == 0
    assert "No existing capability found via indexed search" in res.output


def test_search_cli_reports_hits():
    res = runner.invoke(capabilities_app, ["search", "scorer"])
    assert res.exit_code == 0
    assert "debug target score-source" in res.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -k "alias or search" -v`
Expected: FAIL (`TASK_ALIASES`/`all_capabilities`/`run_search` undefined).

- [ ] **Step 3: Write minimal implementation**

Add to `tools/melee-agent/src/cli/capabilities.py`:

```python
from ._common import DEFAULT_MELEE_ROOT

# Task-intent -> in-scope capability ids (CLI commands + skills only).
# Standalone tools/*.py targets are intentionally excluded (see manifest cross-link).
# Every target below was verified to resolve to a real CLI leaf or skill name.
TASK_ALIASES: dict[str, list[str]] = {
    "find callers": ["ghidra", "commit check-callers"],
    "cross reference": ["ghidra", "commit check-callers"],
    "debug registers": ["mwcc-debug", "mwcc-inspect"],
    "register allocation": ["mwcc-debug", "mwcc-inspect"],
    "score candidate": ["debug target score-source", "debug target score-dump"],
    "scorer": ["debug target score-source", "debug target score-dump"],
    "permuter scorer": ["debug target score-source", "debug permute run"],
    "per-file progress": ["extract files"],
    "per-file stats": ["extract files"],
    "find similar functions": ["opseq", "patterns similar"],
}


def all_capabilities(repo_root: Path | None = None) -> list[Capability]:
    repo_root = repo_root or DEFAULT_MELEE_ROOT
    return command_capabilities() + skill_capabilities(repo_root)


def _score(query: str, c: Capability) -> int:
    q_tokens = [t for t in re.split(r"[\s\-_/]+", query.lower()) if t]
    haystack = f"{c.name} {c.summary} {' '.join(c.keywords)}".lower()
    score = 0
    for t in q_tokens:
        if t in c.name.lower():
            score += 5
        elif t in haystack:
            score += 2
    return score


def run_search(query: str, repo_root: Path | None = None, limit: int = 8) -> list[Capability]:
    repo_root = repo_root or DEFAULT_MELEE_ROOT
    caps = all_capabilities(repo_root)
    by_name = {c.name: c for c in caps}

    # Alias boost: if the query contains an alias key, pull its targets to the top.
    boosted: list[Capability] = []
    ql = query.lower()
    for key, targets in TASK_ALIASES.items():
        if key in ql or all(tok in ql for tok in key.split()):
            for t in targets:
                if t in by_name and by_name[t] not in boosted:
                    boosted.append(by_name[t])

    scored = sorted(
        ((_score(query, c), c) for c in caps if c not in boosted),
        key=lambda pair: pair[0],
        reverse=True,
    )
    ranked = boosted + [c for s, c in scored if s > 0]
    return ranked[:limit]


def _log_search(query: str, results: list[Capability]) -> None:
    """Best-effort: record search usage to audit_log for phase-2 measurement."""
    try:
        from src.db import StateDB

        StateDB().log_audit(
            entity_type="capability",
            entity_id=query[:200],
            action="capability_search",
            metadata={"results": [c.name for c in results]},
        )
    except Exception:
        pass  # never let measurement break search
```

Then replace the `search` command body:

```python
@capabilities_app.command("search")
def search(task: str = typer.Argument(..., help="What you are trying to do.")) -> None:
    """Find existing commands/skills matching a task description."""
    results = run_search(task)
    _log_search(task, results)
    if not results:
        typer.echo(
            "No existing capability found via indexed search; check the nearest "
            "`--help` group and relevant docs before building."
        )
        return
    for c in results:
        typer.echo(f"{c.name:30}  {c.summary}\n{'':30}  -> {c.invoke}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -k "alias or search" -v`
Expected: PASS. If `test_all_alias_targets_resolve_to_real_capabilities` fails, a seed alias points at a renamed command — fix the alias to the real name, do not weaken the test.

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/capabilities.py tools/melee-agent/tests/test_capabilities.py
git commit -m "feat(capabilities): task-alias search, no-match guidance, audit logging"
```

---

### Task 5: `capabilities show`

**Files:**
- Modify: `tools/melee-agent/src/cli/capabilities.py`
- Test: `tools/melee-agent/tests/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tools/melee-agent/tests/test_capabilities.py
def test_show_all_lists_groups_and_skills():
    res = runner.invoke(capabilities_app, ["show"])
    assert res.exit_code == 0
    assert "debug" in res.output
    assert "ghidra" in res.output


def test_show_group_filters():
    res = runner.invoke(capabilities_app, ["show", "debug"])
    assert res.exit_code == 0
    assert "debug target score-source" in res.output
    assert "extract files" not in res.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -k show -v`
Expected: FAIL (current stub prints "(not yet implemented) show").

- [ ] **Step 3: Write minimal implementation**

Replace the `show` command body in `capabilities.py`:

```python
@capabilities_app.command("show")
def show(group: str = typer.Argument(None, help="Command group or skill to detail.")) -> None:
    """Show full detail for a group (or everything)."""
    caps = all_capabilities()
    if group:
        caps = [c for c in caps if c.group == group or c.name == group or c.name.startswith(f"{group} ")]
        if not caps:
            typer.echo(f"No commands or skills match '{group}'.")
            raise typer.Exit(1)
    for c in caps:
        tag = "skill" if c.kind == "skill" else "cmd"
        typer.echo(f"[{tag}] {c.name:30}  {c.summary}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -k show -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/melee-agent/src/cli/capabilities.py tools/melee-agent/tests/test_capabilities.py
git commit -m "feat(capabilities): add show command"
```

---

### Task 6: `generate` — brief + full doc + unregistered-app warning + manifest cross-link

**Files:**
- Modify: `tools/melee-agent/src/cli/capabilities.py`
- Modify: `docs/agent-tool-manifest.md`
- Test: `tools/melee-agent/tests/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tools/melee-agent/tests/test_capabilities.py
def test_render_brief_is_compact_and_grouped():
    caps = cap.all_capabilities(REPO)
    brief = cap.render_brief(caps)
    assert brief.startswith("# melee-agent capabilities")
    assert "debug:" in brief                     # grouped by top-level group
    assert "/decomp" in brief or "decomp" in brief
    # Stays small enough to auto-load every session (emitter appends ~700 bytes
    # of nudge/remote text on top of this).
    assert len(brief.encode("utf-8")) < 9_000


def test_find_unregistered_apps_flags_exactly_the_known_three():
    flagged_vars = {f.split(" ", 1)[0] for f in cap.find_unregistered_apps(REPO)}
    # claim_app / complete_app / workflow_app exist under src/cli but are never
    # add_typer'd anywhere — nested debug sub-apps must NOT be false-positived.
    assert flagged_vars == {"claim_app", "complete_app", "workflow_app"}


def test_generate_writes_both_artifacts(tmp_path, monkeypatch):
    # Redirect outputs into a temp repo skeleton.
    (tmp_path / ".claude").mkdir()
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(cap, "_artifact_paths", lambda: (
        tmp_path / ".claude/capabilities-brief.md",
        tmp_path / "docs/CAPABILITIES.md",
    ))
    monkeypatch.setattr(cap, "_repo_root", lambda: REPO)
    res = runner.invoke(capabilities_app, ["generate"])
    assert res.exit_code == 0
    assert (tmp_path / ".claude/capabilities-brief.md").exists()
    assert (tmp_path / "docs/CAPABILITIES.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -k "brief or unregistered or generate" -v`
Expected: FAIL (`render_brief`/`find_unregistered_apps`/`_artifact_paths` undefined).

- [ ] **Step 3: Write minimal implementation**

Add to `tools/melee-agent/src/cli/capabilities.py`:

```python
import itertools

_BRIEF_HEADER = (
    "# melee-agent capabilities (auto-generated — DO NOT EDIT; run "
    "`melee-agent capabilities generate`)\n\n"
    "Before building any tool/script/command, run "
    "`melee-agent capabilities search <task>`.\n"
)


def _repo_root() -> Path:
    return DEFAULT_MELEE_ROOT


def _artifact_paths() -> tuple[Path, Path]:
    root = _repo_root()
    return root / ".claude" / "capabilities-brief.md", root / "docs" / "CAPABILITIES.md"


def render_brief(caps: list[Capability]) -> str:
    cmds = [c for c in caps if c.kind == "command"]
    skills = [c for c in caps if c.kind == "skill"]
    lines = [_BRIEF_HEADER, "## CLI command groups (`melee-agent <group> --help`)"]
    keyfn = lambda c: c.group
    for group, members in itertools.groupby(sorted(cmds, key=keyfn), key=keyfn):
        members = list(members)
        # Immediate second-level token only (e.g. "debug target score-source" -> "target"),
        # deduped — keeps the brief compact instead of dumping every nested leaf path.
        verbs = ", ".join(sorted({m.name.split()[1] for m in members if " " in m.name})) or "(direct)"
        lines.append(f"- {group}: {verbs}")
    lines.append("\n## Skills (invoke `/<name>`)")
    for s in sorted(skills, key=lambda c: c.name):
        lines.append(f"- {s.name} — {s.summary}")
    return "\n".join(lines) + "\n"


def render_full(caps: list[Capability]) -> str:
    lines = [
        "# melee-agent Capabilities (auto-generated — run `melee-agent capabilities generate`)",
        "",
        "> Standalone `tools/*.py` scripts and setup paths are documented in "
        "[agent-tool-manifest.md](agent-tool-manifest.md), not here.",
        "",
        "## CLI commands",
    ]
    for c in sorted([c for c in caps if c.kind == "command"], key=lambda c: c.name):
        lines.append(f"- `{c.invoke}` — {c.summary}")
    lines.append("\n## Skills")
    for c in sorted([c for c in caps if c.kind == "skill"], key=lambda c: c.name):
        lines.append(f"- `/{c.name}` — {c.summary}")
    return "\n".join(lines) + "\n"


def find_unregistered_apps(repo_root: Path) -> list[str]:
    """Static scan: *_app Typer instances declared under src/cli that are never
    add_typer'd ANYWHERE (root OR nested) are invisible to introspection.

    NOTE (verified): scan ALL cli files for add_typer, not just __init__.py —
    debug.py and others register nested sub-apps; scanning only __init__.py
    false-positives those nested apps. This yields exactly claim/complete/workflow.
    """
    cli_dir = repo_root / "tools" / "melee-agent" / "src" / "cli"
    declared: dict[str, Path] = {}
    registered: set[str] = {"capabilities_app"}
    for py in cli_dir.rglob("*.py"):
        text = py.read_text(errors="replace")
        for m in re.finditer(r"^(\w+_app)\s*=\s*typer\.Typer\(", text, re.MULTILINE):
            declared.setdefault(m.group(1), py)
        registered |= set(re.findall(r"add_typer\(\s*(\w+_app)", text))
    return [
        f"{var} ({path.relative_to(repo_root)})"
        for var, path in sorted(declared.items())
        if var not in registered
    ]
```

Replace the `generate` command body:

```python
@capabilities_app.command("generate")
def generate() -> None:
    """Regenerate the capability brief and full inventory doc."""
    caps = all_capabilities(_repo_root())
    brief_path, full_path = _artifact_paths()
    brief_path.write_text(render_brief(caps), encoding="utf-8")
    full_path.write_text(render_full(caps), encoding="utf-8")
    typer.echo(f"Wrote {brief_path} and {full_path}")
    unregistered = find_unregistered_apps(_repo_root())
    if unregistered:
        typer.echo(
            "WARNING: Typer apps declared but NOT registered at root (invisible to "
            "the index): " + ", ".join(unregistered),
            err=True,
        )
```

- [ ] **Step 4: Add the manifest cross-link**

Append to the top of `docs/agent-tool-manifest.md` (after its title line):

```markdown
> **CLI commands and skills** are inventoried in
> [CAPABILITIES.md](CAPABILITIES.md) (generated; query with
> `melee-agent capabilities search <task>`). This manifest covers standalone
> `tools/*.py` scripts and setup paths the generated index does not.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py -v`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add tools/melee-agent/src/cli/capabilities.py tools/melee-agent/tests/test_capabilities.py docs/agent-tool-manifest.md
git commit -m "feat(capabilities): generate brief + full doc; warn unregistered apps; cross-link manifest"
```

---

### Task 7: SessionStart context emitter (JSON-escaped, graceful degrade)

**Files:**
- Create: `.claude/hooks/emit-capabilities-context.py`
- Test: `tools/melee-agent/tests/test_capabilities_hooks.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/melee-agent/tests/test_capabilities_hooks.py
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EMIT = REPO / ".claude/hooks/emit-capabilities-context.py"


def _run(args, briefdir):
    return subprocess.run(
        [sys.executable, str(EMIT), *args],
        capture_output=True, text=True,
        env={"CAPABILITIES_BRIEF_DIR": str(briefdir), "PATH": "/usr/bin:/bin"},
    )


def test_emitter_outputs_valid_json_with_tricky_brief(tmp_path):
    (tmp_path / "capabilities-brief.md").write_text('Has "quotes", `backticks`,\nand newlines.')
    res = _run([], tmp_path)
    assert res.returncode == 0
    obj = json.loads(res.stdout)  # must be valid JSON despite tricky chars
    assert obj["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "backticks" in obj["hookSpecificOutput"]["additionalContext"]


def test_emitter_degrades_when_brief_missing(tmp_path):
    res = _run([], tmp_path)  # no brief file present
    assert res.returncode == 0
    obj = json.loads(res.stdout)
    # Still emits the nudge even without a brief.
    assert "capabilities search" in obj["hookSpecificOutput"]["additionalContext"]


def test_emitter_includes_remote_notice(tmp_path):
    (tmp_path / "capabilities-brief.md").write_text("brief body")
    res = _run(["--remote"], tmp_path)
    obj = json.loads(res.stdout)
    assert "REMOTE ENVIRONMENT" in obj["hookSpecificOutput"]["additionalContext"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities_hooks.py -v`
Expected: FAIL (emitter script does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# .claude/hooks/emit-capabilities-context.py
#!/usr/bin/env python3
"""Print a SessionStart hookSpecificOutput JSON injecting the capabilities brief.

Called by session-startup.sh in ALL environments. json.dumps handles escaping.
Degrades gracefully: still emits the nudge if the brief is missing; the brief
dir can be overridden with CAPABILITIES_BRIEF_DIR (for tests)."""
import json
import os
import sys
from pathlib import Path

NUDGE = (
    "Before building any new tool, script, or CLI command, run "
    "`melee-agent capabilities search <task>` first — this repo has 150+ "
    "subcommands and ~20 skills; your need may already exist."
)

REMOTE_NOTICE = (
    "REMOTE ENVIRONMENT DETECTED\n\n"
    "Compilation is LIMITED (wibo blocked by container security).\n"
    "WORKING: view target asm via dtk; build .ctx files; read/edit src.\n"
    "NOT WORKING: compiling C (mwcc via wibo), checkdiff.py."
)


def _brief_dir() -> Path:
    override = os.environ.get("CAPABILITIES_BRIEF_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / ".claude"


def main() -> int:
    parts = [NUDGE]
    brief = _brief_dir() / "capabilities-brief.md"
    if brief.exists():
        parts.append(brief.read_text(encoding="utf-8", errors="replace").strip())
    if "--remote" in sys.argv:
        parts.append(REMOTE_NOTICE)
    context = "\n\n".join(p for p in parts if p)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Make it executable:

```bash
chmod +x .claude/hooks/emit-capabilities-context.py
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities_hooks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/emit-capabilities-context.py tools/melee-agent/tests/test_capabilities_hooks.py
git commit -m "feat(hooks): SessionStart capabilities context emitter (json-escaped, degrades)"
```

---

### Task 8: Wire `session-startup.sh` to emit the context unconditionally

**Files:**
- Modify: `.claude/hooks/session-startup.sh`
- Test: manual (the script depends on env; covered functionally by Task 7's emitter tests)

> The current hook (`session-startup.sh:50-53`) exits before emitting context in local sessions, and only emits the remote notice in the remote branch (`:101-109`). Replace the trailing remote-only `cat` with a call to the emitter, and call the emitter on the local path too.

- [ ] **Step 1: Replace the local early-exit (lines ~50-53)**

Change:

```bash
# Only continue with remote/container bootstrap in Claude Code remote.
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    exit 0
fi
```

to:

```bash
# Local sessions: emit the capabilities context, then stop (no remote bootstrap).
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/emit-capabilities-context.py" 2>/dev/null || true
    exit 0
fi
```

- [ ] **Step 2: Replace the trailing remote `cat <<'EOF' ... EOF` block (lines ~101-109)** with:

```bash
# Output workflow context for Claude (capabilities brief + remote notice).
python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/emit-capabilities-context.py" --remote 2>/dev/null || true

exit 0
```

- [ ] **Step 3: Verify the script emits valid JSON locally**

Run:
```bash
cd /Users/mike/code/melee/.claude/worktrees/busy-colden-e51dd0
CLAUDE_PROJECT_DIR="$PWD" CLAUDE_CODE_REMOTE=false bash .claude/hooks/session-startup.sh | python3 -m json.tool
```
Expected: valid JSON with `hookSpecificOutput.additionalContext` containing the nudge (and the brief once Task 12 generates it).

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/session-startup.sh
git commit -m "feat(hooks): auto-load capabilities context in all sessions"
```

---

### Task 9: Soft build-intent nudges (UserPromptSubmit + PreToolUse hooks)

**Files:**
- Create: `.claude/hooks/build-intent-nudge.py` (UserPromptSubmit)
- Create: `.claude/hooks/build-intent-tooluse-nudge.py` (PreToolUse)
- Modify: `.claude/settings.json`
- Test: `tools/melee-agent/tests/test_capabilities_hooks.py`

> Phase-1 lever for the dominant behavioral cause. Soft and non-blocking: it only injects `additionalContext`. The hard blocking gate is phase 2 (out of scope).

- [ ] **Step 1: Write the failing test**

```python
# add to tools/melee-agent/tests/test_capabilities_hooks.py
NUDGE_HOOK = REPO / ".claude/hooks/build-intent-nudge.py"


def _run_nudge(prompt):
    return subprocess.run(
        [sys.executable, str(NUDGE_HOOK)],
        input=json.dumps({"prompt": prompt}),
        capture_output=True, text=True,
    )


def test_nudge_fires_on_build_intent():
    res = _run_nudge("Let's build a new tool to score permuter candidates")
    assert res.returncode == 0
    obj = json.loads(res.stdout)
    assert "capabilities search" in obj["hookSpecificOutput"]["additionalContext"]


def test_nudge_silent_on_ordinary_prompt():
    res = _run_nudge("Match function ftCo_8009C744 in ftcollision.c")
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_nudge_tolerates_bad_stdin():
    res = subprocess.run([sys.executable, str(NUDGE_HOOK)], input="not json",
                         capture_output=True, text=True)
    assert res.returncode == 0
    assert res.stdout.strip() == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities_hooks.py -k nudge -v`
Expected: FAIL (hook does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# .claude/hooks/build-intent-nudge.py
#!/usr/bin/env python3
"""UserPromptSubmit hook: when a prompt expresses build-intent, inject a
non-blocking reminder to search existing capabilities first."""
import json
import re
import sys

BUILD_INTENT = re.compile(
    r"\b(build|create|write|implement|add|make|develop)\b.{0,40}?"
    r"\b(tool|script|command|cli|utility|helper|wrapper|sub-?command|integration)\b",
    re.IGNORECASE | re.DOTALL,
)

CONTEXT = (
    "Build-intent detected. Before building, run "
    "`melee-agent capabilities search <task>` — an equivalent CLI command or "
    "skill may already exist (this repo has 150+ subcommands and ~20 skills). "
    "Past sessions wasted hours rebuilding mwcc-inspector and a permuter scorer "
    "(`debug target score-source`) that already existed."
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = str(data.get("prompt", ""))
    if not BUILD_INTENT.search(prompt):
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": CONTEXT,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```bash
chmod +x .claude/hooks/build-intent-nudge.py
```

- [ ] **Step 4: Register the hook in `.claude/settings.json`**

Read `.claude/settings.json` and add a sibling key to the existing `SessionStart` hook (inside the `"hooks"` object if present, else at the same level as `SessionStart`):

```json
"UserPromptSubmit": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "python3 $CLAUDE_PROJECT_DIR/.claude/hooks/build-intent-nudge.py"
      }
    ]
  }
]
```

- [ ] **Step 5: Add the PreToolUse nudge (catches mid-session tool creation)**

> Spec Component 5 / Codex must-fix: the dominant failure is an agent *mid-design*
> writing a new tool file — which a prompt-only hook misses. Add a second
> non-blocking nudge on Write/Edit of a new `.py`/`.sh` file under `tools/`.
> It only injects context (no `permissionDecision`), so it never blocks.

Create `.claude/hooks/build-intent-tooluse-nudge.py`:

```python
# .claude/hooks/build-intent-tooluse-nudge.py
#!/usr/bin/env python3
"""PreToolUse hook: nudge to search capabilities before creating a new tool
file (a .py/.sh under tools/). Non-blocking — emits additionalContext only."""
import json
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") not in ("Write", "Edit"):
        return 0
    path = str((data.get("tool_input") or {}).get("file_path", "")).replace("\\", "/")
    if "tools/" not in path or not path.endswith((".py", ".sh")):
        return 0
    if "/tests/" in path or "capabilities" in path:
        return 0
    ctx = (
        "About to write a file under tools/. Before building new tooling, run "
        "`melee-agent capabilities search <task>` — an equivalent may already "
        "exist (150+ subcommands, ~20 skills)."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": ctx,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```bash
chmod +x .claude/hooks/build-intent-tooluse-nudge.py
```

- [ ] **Step 6: Write the PreToolUse hook test**

```python
# add to tools/melee-agent/tests/test_capabilities_hooks.py
TOOLUSE_HOOK = REPO / ".claude/hooks/build-intent-tooluse-nudge.py"


def _run_tooluse(tool, file_path):
    return subprocess.run(
        [sys.executable, str(TOOLUSE_HOOK)],
        input=json.dumps({"tool_name": tool, "tool_input": {"file_path": file_path}}),
        capture_output=True, text=True,
    )


def test_tooluse_fires_on_new_tool_file():
    res = _run_tooluse("Write", "tools/melee-agent/src/cli/myscorer.py")
    obj = json.loads(res.stdout)
    assert obj["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "capabilities search" in obj["hookSpecificOutput"]["additionalContext"]


def test_tooluse_silent_on_non_tool_paths():
    assert _run_tooluse("Write", "src/melee/mn/mnvibration.c").stdout.strip() == ""
    assert _run_tooluse("Write", "tools/melee-agent/tests/test_x.py").stdout.strip() == ""
    assert _run_tooluse("Read", "tools/melee-agent/src/cli/foo.py").stdout.strip() == ""
```

- [ ] **Step 7: Register both hooks in `.claude/settings.json`**

Read `.claude/settings.json` and add both keys as siblings of `SessionStart` (inside the same `"hooks"` object). Add the `UserPromptSubmit` block from Step 4 AND:

```json
"PreToolUse": [
  {
    "matcher": "Write|Edit",
    "hooks": [
      {
        "type": "command",
        "command": "python3 $CLAUDE_PROJECT_DIR/.claude/hooks/build-intent-tooluse-nudge.py"
      }
    ]
  }
]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities_hooks.py -k "nudge or tooluse" -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add .claude/hooks/build-intent-nudge.py .claude/hooks/build-intent-tooluse-nudge.py .claude/settings.json tools/melee-agent/tests/test_capabilities_hooks.py
git commit -m "feat(hooks): soft build-intent nudges (UserPromptSubmit + PreToolUse) to search capabilities first"
```

---

### Task 10: Audit-first rule in CLAUDE.md + key skills

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/skills/decomp/SKILL.md`, `.claude/skills/workflow/SKILL.md`

- [ ] **Step 1: Add the rule block near the top of `CLAUDE.md`** (immediately after the first heading/intro, before `## Architecture`):

```markdown
## Before You Build Anything

**Audit-first rule:** before writing a new tool, script, or CLI command, run
`melee-agent capabilities search <task>`. This repo has 150+ CLI subcommands and
~20 skills; assume your need may already exist. Past sessions wasted hours
rebuilding `mwcc-inspector` and a permuter scorer (`melee-agent debug target
score-source`) that already existed. The session also auto-loads a capability
brief — skim it.
```

- [ ] **Step 2: Add one line to `.claude/skills/decomp/SKILL.md`** (in its "getting unstuck"/tools area):

```markdown
- **Before building any helper or tool**, run `melee-agent capabilities search <task>` — it probably already exists.
```

- [ ] **Step 3: Add the same line to `.claude/skills/workflow/SKILL.md`** (near its tool references).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md .claude/skills/decomp/SKILL.md .claude/skills/workflow/SKILL.md
git commit -m "docs: add audit-first capabilities rule to CLAUDE.md and skills"
```

---

### Task 11: Drift guard (CI workflow + pre-commit)

**Files:**
- Create: `.github/workflows/capabilities-drift.yml`
- Modify: `.pre-commit-config.yaml` (it ALREADY EXISTS with a `- repo: local` block — MERGE, do not clobber)

- [ ] **Step 1: Create the CI workflow**

```yaml
# .github/workflows/capabilities-drift.yml
name: capabilities-drift
on:
  pull_request:
    paths:
      - '.claude/**'
      - 'docs/CAPABILITIES.md'
      - 'docs/agent-tool-manifest.md'
      - 'tools/melee-agent/**'
      - 'CLAUDE.md'
  push:
    branches: [master]
    paths:
      - '.claude/**'
      - 'docs/CAPABILITIES.md'
      - 'tools/melee-agent/**'
      - 'CLAUDE.md'

jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4   # full checkout: .claude and docs present
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install melee-agent
        run: pip install -e tools/melee-agent
      - name: Regenerate capability artifacts
        run: melee-agent capabilities generate
      - name: Fail on drift
        run: |
          if ! git diff --exit-code -- .claude/capabilities-brief.md docs/CAPABILITIES.md; then
            echo "::error::Capability artifacts are stale. Run 'melee-agent capabilities generate' and commit."
            exit 1
          fi
```

- [ ] **Step 2: Merge a pre-commit hook into the existing `.pre-commit-config.yaml`**

> The file already exists with a `- repo: local` block (containing `melee-style-check`,
> `check-fork-files`). Add the hook below as a new item in that block's `hooks:` list —
> do NOT replace the file. The `files:` regex covers every source that can change the
> generated index: CLI source, skills, hooks, settings, CLAUDE.md, and the manifest.

```yaml
# Append under the EXISTING `- repo: local` block's `hooks:` list:
      - id: capabilities-drift
        name: capabilities index up to date
        entry: bash -c 'melee-agent capabilities generate && git diff --exit-code -- .claude/capabilities-brief.md docs/CAPABILITIES.md'
        language: system
        pass_filenames: false
        files: '^(tools/melee-agent/src/cli/|\.claude/skills/|\.claude/hooks/|\.claude/settings\.json|CLAUDE\.md|docs/agent-tool-manifest\.md)'
```

- [ ] **Step 3: Verify the workflow file is valid YAML**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/capabilities-drift.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Confirm sync-upstream preserves these paths**

Run: `grep -nE "\.claude|docs|tools" tools/workflow/sync-upstream.sh | head`
Expected: `.claude/`, `docs/`, `tools/` are in the preserved overlay (so the artifacts, generator, and hooks survive an upstream sync). If any path is NOT preserved, add it to the overlay list in `sync-upstream.sh` and note it in the commit.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/capabilities-drift.yml .pre-commit-config.yaml
git commit -m "ci: fail on capability-index drift; pre-commit regen guard"
```

---

### Task 12: Generate real artifacts + full verification

**Files:**
- Create (generated): `.claude/capabilities-brief.md`, `docs/CAPABILITIES.md`

- [ ] **Step 1: Generate the artifacts**

Run: `cd /Users/mike/code/melee/.claude/worktrees/busy-colden-e51dd0/tools/melee-agent && melee-agent capabilities generate`
Expected: "Wrote …/.claude/capabilities-brief.md and …/docs/CAPABILITIES.md". Note any "WARNING: Typer apps declared but NOT registered" line — record it (claim/complete/workflow are expected; the warning is informational, not a failure).

- [ ] **Step 2: Sanity-check the brief size and content**

Run: `wc -c .claude/capabilities-brief.md && head -40 .claude/capabilities-brief.md` (from repo root)
Expected: under ~9 KB; groups + skills present; the `debug:` line lists second-level groups like `target, permute, inspect, suggest` (NOT every nested leaf).

- [ ] **Step 3: Run the entire melee-agent test suite**

Run: `cd tools/melee-agent && python -m pytest tests/test_capabilities.py tests/test_capabilities_hooks.py -v`
Expected: all PASS.

Run (regression — make sure nothing else broke from the `__init__.py` edit): `cd tools/melee-agent && python -m pytest tests/test_layout_cli.py tests/test_extract_cli.py -q`
Expected: PASS.

- [ ] **Step 4: End-to-end smoke test**

Run:
```bash
cd /Users/mike/code/melee/.claude/worktrees/busy-colden-e51dd0/tools/melee-agent
melee-agent capabilities search "find callers"
melee-agent capabilities search "scorer"
CLAUDE_PROJECT_DIR="$(git rev-parse --show-toplevel)" CLAUDE_CODE_REMOTE=false bash "$(git rev-parse --show-toplevel)/.claude/hooks/session-startup.sh" | python3 -m json.tool >/dev/null && echo "session hook JSON OK"
```
Expected: search returns the right tools; "session hook JSON OK".

- [ ] **Step 5: Commit the generated artifacts**

```bash
cd "$(git rev-parse --show-toplevel)"
git add .claude/capabilities-brief.md docs/CAPABILITIES.md
git commit -m "feat(capabilities): generate initial brief and full inventory"
```

---

## Self-Review

- **Spec coverage:** Component 1 (search/show/generate) → Tasks 1,2,4,5,6; Component 2 (alias map) → Task 4; Component 3 (artifacts + manifest cross-link) → Task 6,12; Component 4 (session hook auto-load + JSON escaping) → Tasks 7,8; Component 5 (soft nudge — UserPromptSubmit + PreToolUse) → Task 9; Component 6 (audit-first rule) → Task 10; Component 7 (drift guard + sync-upstream) → Task 11; Component 8 (audit_log measurement) → Task 4. Introspection caveats (unregistered apps, help fallback, worktree entrypoint) → Tasks 2,6. Frontmatter fallback → Task 3. All covered.
- **No placeholders:** every code/test step contains complete code and exact commands.
- **Type consistency:** `Capability` dataclass fields (`kind/name/summary/invoke/group/keywords`) are used consistently; helpers `command_capabilities`, `skill_capabilities`, `all_capabilities`, `parse_skill`, `run_search`, `render_brief`, `render_full`, `find_unregistered_apps`, `_artifact_paths`, `_repo_root` are defined before use and referenced by the same names in tests.

## Codex plan-review incorporation (changelog)

Independent Codex review (line-cited; findings verified against the live tree before applying):
- **Introspection (must-fix):** `.commands` walk yielded only 3 leaves → rewrote to lazy-safe `list_commands(ctx)`/`get_command(ctx, name)` (215 leaves) + hidden-command filtering (Task 2). Verified: 215 leaves, `issues`/`debug inspect ceiling` excluded.
- **Stale `debug score` (must-fix):** there is no `debug score`; real scorers are `debug target score-source`/`score-dump`/`score-force-phys`/`score-simplify-order`. Fixed every test/alias/nudge/CLAUDE.md/spec reference. Verified all alias targets resolve.
- **`find_unregistered_apps` (must-fix):** regex scanned only `__init__.py` → false-positived nested debug sub-apps. Rewrote to scan ALL cli files for `add_typer`. Verified: flags exactly `claim_app/complete_app/workflow_app`.
- **PreToolUse coverage gap (must-fix):** added a second non-blocking `PreToolUse` nudge on Write/Edit of a new `tools/` `.py`/`.sh` file (Task 9), since prompt-only missed the mid-design case the spec calls out.
- **Pre-commit clobber (must-fix):** `.pre-commit-config.yaml` already exists → Task 11 now MERGES into its `- repo: local` block and broadens the `files:` trigger.
- **Should-fix:** help fallback documented (`short_help → help/docstring`); brief-size guard tightened to <9 KB; `render_brief` lists second-level tokens only (compact); `command_capabilities(root_app=…)` injectable; exact unregistered-apps assertion added.
- **Verified non-issue:** `DEFAULT_MELEE_ROOT` is detection-based and resolves to the current worktree, so `generate`/`_repo_root()` are worktree-correct.

## Phase 2 (explicitly deferred — do NOT build now)

A hard, **blocking** pre-build gate — a `PreToolUse` hook that returns
`permissionDecision: "ask"`/`"deny"` (distinct from the phase-1 *soft* PreToolUse
nudge, which only injects context) — only if measurement (audit_log
`capability_search` rate vs. near-rebuild incident tally) shows the soft nudges
are insufficient.
