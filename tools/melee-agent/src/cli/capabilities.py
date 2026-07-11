"""melee-agent capabilities — a discoverable, queryable index of existing CLI
commands and skills, so agents stop rebuilding tools that already exist.

`search` and `show` introspect the LIVE Typer tree (never stale); `generate`
writes the auto-loaded brief and the full inventory doc.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

import typer

from ._common import DEFAULT_MELEE_ROOT


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
    except Exception as exc:
        import sys
        print(f"capabilities: list_commands failed ({exc}); falling back to .commands", file=sys.stderr)
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
        short = click_cmd.get_short_help_str(limit=200)
    except Exception:
        short = ""
    if short:
        return short.strip()
    if click_cmd.help:
        lines = click_cmd.help.strip().splitlines()
        return lines[0].strip() if lines else ""
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
                # keywords = command-path tokens only (search ranks help text separately)
                keywords=full_name.replace("-", " ").split(),
            )
        )
    return caps

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


_SCORE_THRESHOLD = 4  # >=4 requires either one name-token hit (score 5) or two keyword hits (2+2)

# Task-intent -> in-scope capability ids (CLI commands + skills only).
# Standalone tools/*.py targets are intentionally excluded (see manifest cross-link).
# Every target below was verified to resolve to a real CLI leaf or skill name.
TASK_ALIASES: dict[str, list[str]] = {
    "find callers": ["ghidra", "commit check-callers"],
    "cross reference": ["ghidra", "commit check-callers"],
    "debug registers": [
        "debug inspect causal-diff",
        "debug inspect lifetime-pressure",
        "mwcc-debug",
        "mwcc-inspect",
    ],
    "register allocation": [
        "debug inspect causal-diff",
        "debug inspect lifetime-pressure",
        "mwcc-debug",
        "mwcc-inspect",
    ],
    "stack home ownership": ["debug inspect causal-diff", "debug inspect stack-homes"],
    "compiler provenance": ["debug inspect causal-diff", "mwcc-inspect"],
    "score candidate": ["debug target score-source", "debug target score-dump"],
    "scorer": ["debug target score-source", "debug target score-dump"],
    "permuter scorer": ["debug target score-source", "debug permute run"],
    "per-file progress": ["extract files"],
    "per-file stats": ["extract files"],
    "find similar functions": ["opseq", "patterns similar"],
    "transform corpus source-shape probes": [
        "debug search plan-transforms",
        "debug mutate lifetime-layout",
        "debug coalesce-search",
        "debug select-order-search",
        "debug mutate frame-transform-search",
    ],
    "transform corpus pressure coalesce select order": [
        "debug mutate lifetime-layout",
        "debug coalesce-search",
        "debug select-order-search",
    ],
    "transform corpus frame source-shape": [
        "debug mutate frame-transform-search",
        "debug search plan-transforms",
    ],
    "retained case c sensitivity": ["debug search plan-transforms"],
    "retained case-c sensitivity": ["debug search plan-transforms"],
    "retained gpr case c": ["debug search plan-transforms"],
    "retained ig44 window order continuation": ["debug search plan-transforms"],
    "retained ig44 window-order continuation": ["debug search plan-transforms"],
    "select order json retained ig44": ["debug search plan-transforms"],
    "field load source order": [
        "debug select-order-search",
        "debug search plan-transforms",
    ],
    "field-load source-order bridge": [
        "debug select-order-search",
        "debug search plan-transforms",
    ],
    "gobj user_data select order": [
        "debug select-order-search",
        "debug search plan-transforms",
    ],
    "post ceiling retained frontier": ["debug search retained-frontiers"],
    "post source ceiling backend codegen axis": [
        "debug search post-source-ceiling-axis",
    ],
    "post-source-ceiling backend codegen axis": [
        "debug search post-source-ceiling-axis",
    ],
    "post source model ceiling next axis": [
        "debug search post-source-ceiling-axis",
    ],
    "post-source-model-ceiling next-axis": [
        "debug search post-source-ceiling-axis",
    ],
    "sort post source ceiling gpr non source codegen axis": [
        "debug search post-source-ceiling-axis",
    ],
    "draw post source ceiling fpr non source codegen axis": [
        "debug search post-source-ceiling-axis",
    ],
    "retained frontier triage": ["debug search retained-frontiers"],
    "alternate retained frontier ranking": ["debug search retained-frontiers"],
    "mndiagram retained frontier": ["debug search retained-frontiers"],
    "meta ceiling synthesis": [
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
        "debug search source-model-synthesis",
    ],
    "sort source model synthesis": ["debug search source-model-synthesis"],
    "sort post cross tu source hypothesis": ["debug search source-model-synthesis"],
    "sort post-cross-tu source hypothesis": ["debug search source-model-synthesis"],
    "sort post cross tu selection swap source hypothesis": [
        "debug search source-model-synthesis"
    ],
    "sort-post-cross-tu-selection-swap-source-hypothesis": [
        "debug search source-model-synthesis"
    ],
    "sort post cross tu selection swap next dimension": [
        "debug search source-model-synthesis"
    ],
    "sort post cross tu broader natural rewrite": [
        "debug search source-model-synthesis"
    ],
    "sort-post-cross-tu-broader-natural-c-rewrite": [
        "debug search source-model-synthesis"
    ],
    "sort-no-modeled-source-actionable-family-after-post-cross-tu-selection-swap-source-hypothesis": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "sort-no-modeled-source-actionable-family-after-post-cross-tu-broader-natural-c-rewrite": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
    ],
    "sort-post-broader-natural-inline-boundary-source-hypothesis": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
    ],
    "sort-no-modeled-source-actionable-family-after-post-broader-natural-inline-boundary-source-hypothesis": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
    ],
    "sort-no-modeled-source-actionable-family-after-cross-tu-linkage": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw fpr source model synthesis": ["debug search source-model-synthesis"],
    "draw expression source family": ["debug search source-model-synthesis"],
    "fpr expression source family synthesis": ["debug search source-model-synthesis"],
    "post meta ceiling source family": ["debug search source-model-synthesis"],
    "draw-loop-body-callsite-and-object-base-lifetime-source-context": [
        "debug search source-model-synthesis",
    ],
    "draw-no-modeled-source-actionable-family-after-loop-body-callsite-and-object-base-lifetime-source-context": [
        "debug search post-source-context-next-dimension",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw-no-modeled-source-actionable-family-after-post-source-context-whole-function-fpr-source-model": [
        "debug search post-source-context-next-dimension",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw-post-all-known-loop-product-translate-expression-graph": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw-no-modeled-source-actionable-family-after-post-all-known-loop-product-translate-expression-graph": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw loop product translate expression graph": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw-coupled-post-meta-fpr-expression-lifetime": [
        "debug search post-source-context-next-dimension",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw-no-modeled-source-actionable-family-after-post-row-offset-owner-split": [
        "debug search source-model-synthesis",
        "debug search source-family-continuation",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw-post-row-offset-owner-expression-lifetime": [
        "debug search source-model-synthesis",
        "debug search source-family-continuation",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw post row offset owner expression lifetime": [
        "debug search source-model-synthesis",
        "debug search source-family-continuation",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw-no-modeled-source-actionable-family-after-post-row-offset-owner-expression-lifetime": [
        "debug search source-model-synthesis",
        "debug search source-family-continuation",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw loop body callsite object base lifetime source context": [
        "debug search source-model-synthesis",
    ],
    "draw source context generator": ["debug search source-model-synthesis"],
    "post source context next dimension": [
        "debug search post-source-context-next-dimension",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "post-source-context next-dimension discovery": [
        "debug search post-source-context-next-dimension",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw post source context discovery": [
        "debug search post-source-context-next-dimension",
    ],
    "retained frontiers after source context": [
        "debug search post-source-context-next-dimension",
        "debug search retained-frontiers",
    ],
    "source family continuation": ["debug search source-family-continuation"],
    "post meta source family continuation": [
        "debug search source-family-continuation",
        "debug search retained-frontiers",
    ],
    "source model continuation proof": [
        "debug search source-family-continuation",
        "debug search retained-frontiers",
    ],
    "stack clean no anchor continuation": [
        "debug search source-family-continuation",
        "debug inspect stack-homes",
        "debug suggest expression-interferer-repair",
        "debug suggest protected-expression-reconcile",
        "debug suggest inline-boundary-continuation",
    ],
    "stack-clean no-anchor recovery": [
        "debug search source-family-continuation",
        "debug inspect stack-homes",
        "debug suggest expression-interferer-repair",
        "debug suggest protected-expression-reconcile",
        "debug suggest inline-boundary-continuation",
    ],
    "draw-post-product-translate-stack-clean-no-anchor-recovery": [
        "debug search source-family-continuation",
        "debug inspect stack-homes",
        "debug suggest expression-interferer-repair",
        "debug suggest protected-expression-reconcile",
        "debug suggest inline-boundary-continuation",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw-no-modeled-source-actionable-family-after-post-product-translate-stack-clean-no-anchor-recovery": [
        "debug search source-family-continuation",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "post stack clean": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug search post-source-context-next-dimension",
        "debug solve allocator-ceiling",
    ],
    "after stack clean recovery": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug search post-source-context-next-dimension",
        "debug solve allocator-ceiling",
    ],
    "no anchor fpr shape": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug search post-source-context-next-dimension",
        "debug solve allocator-ceiling",
    ],
    "draw-post-stack-clean-no-anchor-fpr-source-shape-hypothesis": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "draw-no-modeled-source-actionable-family-after-post-stack-clean-no-anchor-fpr-source-shape-hypothesis": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "retained source model": [
        "debug search source-model-synthesis",
        "debug search retained-frontiers",
    ],
    "all known frontiers exhausted": [
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
    "retained frontiers terminal proof": [
        "debug search retained-frontiers",
        "debug solve allocator-ceiling",
    ],
}


def all_capabilities(repo_root: Path | None = None) -> list[Capability]:
    repo_root = repo_root or DEFAULT_MELEE_ROOT
    return command_capabilities() + skill_capabilities(repo_root)


def _score(query: str, c: Capability) -> int:
    q_tokens = [t for t in re.split(r"[\s\-_/]+", query.lower()) if t]
    name_tokens = set(re.split(r"[\s\-_/]+", c.name.lower()))
    hay_tokens = set(re.split(r"[^\w]+", f"{c.summary} {' '.join(c.keywords)}".lower()))
    score = 0
    for t in q_tokens:
        if t in name_tokens:
            score += 5
        elif t in hay_tokens:
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
    ranked = boosted + [c for s, c in scored if s >= _SCORE_THRESHOLD]
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


_BRIEF_HEADER = (
    "# melee-agent capabilities (auto-generated — DO NOT EDIT; run "
    "`melee-agent capabilities generate`)\n\n"
    "Before building any tool/script/command, run "
    "`melee-agent capabilities search <task>`.\n"
)

BRIEF_TASK_HINTS = [
    "register allocation",
    "score candidate",
    "find callers",
    "transform corpus pressure coalesce select order",
]


def _repo_root() -> Path:
    return DEFAULT_MELEE_ROOT


def _artifact_paths() -> tuple[Path, Path]:
    root = _repo_root()
    return root / ".claude" / "capabilities-brief.md", root / "docs" / "CAPABILITIES.md"


def render_brief(caps: list[Capability]) -> str:
    cmds = [c for c in caps if c.kind == "command"]
    skills = [c for c in caps if c.kind == "skill"]
    by_name = {c.name: c for c in caps}
    lines = [_BRIEF_HEADER, "## CLI command groups (`melee-agent <group> --help`)"]
    keyfn = lambda c: c.group
    for group, members in itertools.groupby(sorted(cmds, key=keyfn), key=keyfn):
        members = list(members)
        # Immediate second-level token only (e.g. "debug target score-source" -> "target"),
        # deduped — keeps the brief compact instead of dumping every nested leaf path.
        verbs = ", ".join(sorted({m.name.split()[1] for m in members if " " in m.name})) or "(direct)"
        lines.append(f"- {group}: {verbs}")
    lines.append("\n## Common task shortcuts")
    for task in BRIEF_TASK_HINTS:
        targets = [
            by_name[target].invoke
            for target in TASK_ALIASES.get(task, [])
            if target in by_name
        ]
        if targets:
            lines.append(
                f"- {task}: " + ", ".join(f"`{target}`" for target in targets)
            )
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
        aliases = {
            m.group(2): m.group(1)
            for m in re.finditer(
                r"from\s+[\w.]+\s+import\s+(\w+_app)\s+as\s+(\w+_app)",
                text,
            )
        }
        for m in re.finditer(r"^(\w+_app)\s*=\s*typer\.Typer\(", text, re.MULTILINE):
            declared.setdefault(m.group(1), py)
        for name in re.findall(r"add_typer\(\s*(\w+_app)", text):
            registered.add(name)
            registered.add(aliases.get(name, name))
    return [
        f"{var} ({path.relative_to(repo_root)})"
        for var, path in sorted(declared.items())
        if var not in registered
    ]


capabilities_app = typer.Typer(
    help="Discover existing CLI commands and skills before building new ones.",
    no_args_is_help=True,
)


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
