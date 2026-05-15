"""Tests for worktree doctor stale-state checks."""

import importlib.util
import os
import sys
from pathlib import Path


def load_worktree_doctor():
    path = Path(__file__).parents[1] / "tools" / "worktree-doctor.py"
    spec = importlib.util.spec_from_file_location("worktree_doctor", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (mtime, mtime))


def test_stale_state_warns_when_report_is_older_than_sources(tmp_path):
    doctor = load_worktree_doctor()
    write_file(tmp_path / "src" / "melee" / "ft" / "file.c", "void f(void) {}\n", 200.0)
    write_file(tmp_path / "include" / "melee" / "ft" / "file.h", "void f(void);\n", 180.0)
    write_file(tmp_path / "build" / "GALE01" / "report.json", "{}", 100.0)

    results = doctor.collect_stale_state_warnings(tmp_path)

    assert any("build/GALE01/report.json is older" in result.message for result in results)


def test_stale_state_warns_when_build_edge_output_is_older_than_input(tmp_path):
    doctor = load_worktree_doctor()
    write_file(tmp_path / "src" / "melee" / "ft" / "file.c", "void f(void) {}\n", 200.0)
    write_file(tmp_path / "build" / "GALE01" / "src" / "melee" / "ft" / "file.o", "", 100.0)
    write_file(
        tmp_path / "build.ninja",
        "build build/GALE01/src/melee/ft/file.o: mwcc src/melee/ft/file.c\n",
        150.0,
    )

    results = doctor.collect_stale_state_warnings(tmp_path)

    assert any("stale object output" in result.message for result in results)


def test_knowledge_sources_warn_when_discord_archive_cli_missing(tmp_path):
    doctor = load_worktree_doctor()

    results = doctor.collect_knowledge_source_warnings(tmp_path, discord_cli=tmp_path / "missing-discord-search")

    assert any("Discord archive CLI missing" in result.message for result in results)


def test_knowledge_sources_require_canonical_decomp_skill(tmp_path):
    doctor = load_worktree_doctor()
    old_skill = tmp_path / ".claude" / "skills" / "decomp" / "SKILL.md"
    old_skill.parent.mkdir(parents=True, exist_ok=True)
    old_skill.write_text("---\nname: decomp\n---\n")

    results = doctor.collect_knowledge_source_warnings(tmp_path, discord_cli=tmp_path / "missing-discord-search")

    assert any(".agents/skills/decomp/SKILL.md is missing" in result.message for result in results)
