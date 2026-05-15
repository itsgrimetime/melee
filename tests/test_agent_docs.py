"""Tests for agent-facing decomp documentation artifacts."""

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text()


def test_agent_tool_manifest_lists_canonical_commands():
    text = read("docs/agent-tool-manifest.md")
    for required in (
        "tools/worktree-doctor.py",
        "tools/checkdiff.py",
        "tools/symbol-layout-analyzer.py",
        ".agents/skills/decomp/SKILL.md",
        ".claude/skills/decomp/SKILL.md",
        ".codex/skills",
        "melee-agent attempts",
        "melee-agent patterns wrappers",
        "melee-agent patterns anti-patterns",
        "GHIDRA_INSTALL_DIR",
        "table-typer",
        "discord-search",
    ):
        assert required in text


def test_discord_search_recipes_cover_decomp_failure_modes():
    text = read("docs/discord-search-recipes.md")
    for required in (
        "MWCC regalloc",
        "varargs",
        "by-value Vec3",
        "PAD_STACK",
        "small-data",
        "gc-wii-decomp",
    ):
        assert required in text


def test_mn_module_notes_cover_requested_modules():
    text = read("docs/mn-module-notes.md")
    for required in (
        "mnsnap",
        "mnvibration",
        "mnnamenew",
        "known local maxima",
        "successful source shapes",
    ):
        assert required in text


def test_large_function_checkpoint_covers_required_context():
    text = read("docs/large-function-checkpoint.md")
    for required in (
        "callers/callees",
        "data layout",
        "asset loads",
        "varargs lists",
        "intended behavior",
    ):
        assert required in text


def test_improvement_checklist_tracks_original_followups():
    text = read("docs/agent-decomp-improvement-checklist.md")
    for required in (
        "stable tool manifest",
        "Discord query recipes",
        "per-module `mn` notes",
        "large-function checkpoint",
        "signature/type mismatch",
        "map/object layout evidence",
    ):
        assert required in text
