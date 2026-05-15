"""Smoke tests for the repo-local decomp skill."""

from pathlib import Path


def test_decomp_skill_includes_agent_guardrails():
    skill_path = Path(".agents") / "skills" / "decomp" / "SKILL.md"

    assert skill_path.exists()
    text = skill_path.read_text()
    for required in (
        "tools/worktree-doctor.py",
        "tools/checkdiff.py",
        "melee-agent attempts record",
        "melee-agent patterns inlines",
        "tools/symbol-layout-analyzer.py",
        "docs/large-function-checkpoint.md",
        "docs/discord-search-recipes.md",
    ):
        assert required in text


def test_decomp_skill_has_agent_specific_compatibility_links():
    canonical = (Path(".agents") / "skills" / "decomp" / "SKILL.md").resolve()

    claude_skill = Path(".claude") / "skills" / "decomp" / "SKILL.md"
    assert claude_skill.is_symlink()
    assert claude_skill.resolve() == canonical

    codex_skills = Path(".codex") / "skills"
    assert codex_skills.is_symlink()
    assert codex_skills.resolve() == (Path(".agents") / "skills").resolve()
    assert (codex_skills / "decomp" / "SKILL.md").resolve() == canonical
