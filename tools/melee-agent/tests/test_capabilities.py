import textwrap

from pathlib import Path
from typer.testing import CliRunner

from src.cli import capabilities as cap
from src.cli.capabilities import capabilities_app

runner = CliRunner()

REPO = Path(__file__).resolve().parents[3]


def test_capabilities_help_lists_subcommands():
    res = runner.invoke(capabilities_app, ["--help"])
    assert res.exit_code == 0
    out = res.output.lower()
    assert "search" in out
    assert "show" in out
    assert "generate" in out


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
    assert "mismatch add" in [c.name for c in cap.run_search("inline pattern recording", REPO)]


def test_search_cli_no_match_wording():
    res = runner.invoke(capabilities_app, ["search", "zzz-nonexistent-capability-xyz"])
    assert res.exit_code == 0
    assert "No existing capability found via indexed search" in res.output


def test_search_cli_reports_hits():
    res = runner.invoke(capabilities_app, ["search", "scorer"])
    assert res.exit_code == 0
    assert "debug target score-source" in res.output


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


def test_find_unregistered_apps_resolves_imported_typer_alias(tmp_path):
    cli_dir = tmp_path / "tools" / "melee-agent" / "src" / "cli"
    nested_dir = cli_dir / "nested"
    nested_dir.mkdir(parents=True)
    (nested_dir / "leaf.py").write_text(
        "import typer\nleaf_app = typer.Typer()\n",
    )
    (cli_dir / "__init__.py").write_text(
        "import typer\n"
        "root_app = typer.Typer()\n"
        "from src.cli.nested.leaf import leaf_app as _leaf_app\n"
        "root_app.add_typer(_leaf_app, name='leaf')\n",
    )

    flagged_vars = {f.split(" ", 1)[0] for f in cap.find_unregistered_apps(tmp_path)}

    assert flagged_vars == {"root_app"}


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
