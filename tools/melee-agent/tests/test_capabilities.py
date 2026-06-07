import textwrap

from pathlib import Path
from typer.testing import CliRunner

from src.cli import capabilities as cap
from src.cli.capabilities import capabilities_app

runner = CliRunner()


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
