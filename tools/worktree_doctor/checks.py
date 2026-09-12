"""Standalone check helper functions for worktree-doctor."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

from . import ROOT, DOL_CANDIDATES, DISCORD_SEARCH_CANDIDATES, REPORT_REFRESH_FIX, STALE_GRACE_SECONDS


def resolve_discord_search(discord_cli: Path | None = None) -> Path | None:
    candidates = [discord_cli] if discord_cli is not None else DISCORD_SEARCH_CANDIDATES
    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    path_candidate = shutil.which("discord-search")
    if path_candidate:
        return Path(path_candidate)
    return None


def collect_knowledge_source_warnings(root: Path, discord_cli: Path | None = None) -> list:
    from .doctor import CheckResult

    results: list[CheckResult] = []

    discord_doc = root / "docs" / "discord-knowledge" / "DISCORD_KNOWLEDGE.md"
    if discord_doc.exists():
        results.append(CheckResult("ok", "discord knowledge document present"))
    else:
        results.append(CheckResult("warn", "docs/discord-knowledge is missing", "use the Discord archive CLI fallback"))

    resolved_discord_cli = resolve_discord_search(discord_cli)
    if resolved_discord_cli:
        results.append(CheckResult("ok", f"Discord archive CLI present: {resolved_discord_cli}"))
    else:
        results.append(
            CheckResult(
                "warn",
                "Discord archive CLI missing",
                "install /Users/mike/code/discord-archive-mcp/.venv/bin/discord-search or rely on docs/discord-knowledge",
            )
        )

    claude_skills_dir = root / ".claude" / "skills"
    decomp_skill = claude_skills_dir / "decomp" / "SKILL.md"
    if decomp_skill.exists() and not decomp_skill.is_symlink():
        results.append(CheckResult("ok", ".claude/skills/decomp/SKILL.md present"))
    elif decomp_skill.is_symlink():
        results.append(
            CheckResult(
                "warn",
                ".claude/skills/decomp/SKILL.md is a stale symlink (legacy .agents/ layout)",
                "run ./tools/workflow/sync-hooks.sh --apply to refresh from master",
            )
        )
    else:
        results.append(
            CheckResult(
                "warn",
                ".claude/skills/decomp/SKILL.md is missing",
                "run ./tools/workflow/sync-hooks.sh --apply to restore from master",
            )
        )

    if claude_skills_dir.is_dir():
        skill_count = sum(1 for p in claude_skills_dir.iterdir() if p.is_dir())
        if skill_count >= 5:
            results.append(CheckResult("ok", f".claude/skills/ has {skill_count} skills"))
        else:
            results.append(
                CheckResult(
                    "warn",
                    f".claude/skills/ has only {skill_count} skills (expected the full set)",
                    "run ./tools/workflow/sync-hooks.sh --apply to sync from master",
                )
            )

    codex_skills = root / ".codex" / "skills"
    if codex_skills.is_symlink():
        target = os.readlink(codex_skills)
        resolved = (codex_skills.parent / target).resolve()
        if resolved == claude_skills_dir.resolve():
            results.append(CheckResult("ok", ".codex/skills -> ../.claude/skills (Codex sees same skills as Claude)"))
        else:
            results.append(
                CheckResult(
                    "warn",
                    f".codex/skills symlink points at {target} (expected ../.claude/skills)",
                    "run ./tools/workflow/sync-hooks.sh --apply to fix",
                )
            )
    elif codex_skills.exists():
        results.append(
            CheckResult(
                "warn",
                ".codex/skills is a directory, expected symlink to ../.claude/skills",
                "remove it and run sync-hooks.sh --apply",
            )
        )
    else:
        results.append(
            CheckResult(
                "warn",
                ".codex/skills is missing (Codex agents will have no skills)",
                "run ./tools/workflow/sync-hooks.sh --apply",
            )
        )

    return results


def collect_stale_state_warnings(root: Path) -> list:
    from .doctor import CheckResult
    from .utils import rel_to_root

    results: list[CheckResult] = []
    newest = newest_relevant_input(root)
    report_path = root / Path("build") / "GALE01" / "report.json"

    if newest is not None and not report_path.exists():
        results.append(
            CheckResult(
                "fail",
                "build/GALE01/report.json is missing",
                REPORT_REFRESH_FIX,
            )
        )
    elif newest is not None and report_path.exists():
        newest_path, newest_mtime = newest
        if report_path.stat().st_mtime + STALE_GRACE_SECONDS < newest_mtime:
            results.append(
                CheckResult(
                    "warn",
                    f"build/GALE01/report.json is older than {rel_to_root(newest_path, root)}",
                    REPORT_REFRESH_FIX,
                )
            )

    stale_edges = stale_compile_edges(root)
    for output, input_path in stale_edges[:5]:
        results.append(
            CheckResult(
                "warn",
                f"stale object output: {rel_to_root(output, root)} is older than {rel_to_root(input_path, root)}",
                "run: ninja or rerun the compile/checkdiff command before interpreting object diffs",
            )
        )
    if len(stale_edges) > 5:
        results.append(
            CheckResult(
                "warn",
                f"{len(stale_edges) - 5} additional stale object output(s) omitted",
                "run: ninja to refresh generated objects",
            )
        )

    return results


def newest_relevant_input(root: Path) -> tuple[Path, float] | None:
    candidates: list[Path] = []
    for rel_path in ("src", "include", "config/GALE01"):
        base = root / rel_path
        if base.exists():
            candidates.extend(path for path in base.rglob("*") if path.is_file())
    for rel_path in ("configure.py", "build.ninja"):
        path = root / rel_path
        if path.exists():
            candidates.append(path)

    if not candidates:
        return None
    newest_path = max(candidates, key=lambda path: path.stat().st_mtime)
    return newest_path, newest_path.stat().st_mtime


COMPILE_RULES = {"mwcc", "mwcc_sjis", "mwcc_extab", "mwcc_sjis_extab", "as"}


def stale_compile_edges(root: Path) -> list[tuple[Path, Path]]:
    build_ninja = root / "build.ninja"
    if not build_ninja.exists():
        return []

    stale: list[tuple[Path, Path]] = []
    for output_rel, input_rel in parse_compile_edges(build_ninja):
        output_path = root / output_rel
        input_path = root / input_rel
        if "$" in str(output_rel) or "$" in str(input_rel):
            continue
        if not output_path.exists() or not input_path.exists():
            continue
        if output_path.stat().st_mtime + STALE_GRACE_SECONDS < input_path.stat().st_mtime:
            stale.append((output_path, input_path))
    return stale


def parse_compile_edges(build_ninja: Path) -> list[tuple[Path, Path]]:
    edges: list[tuple[Path, Path]] = []
    for raw_line in build_ninja.read_text(errors="ignore").splitlines():
        if not raw_line.startswith("build ") or ":" not in raw_line:
            continue
        outputs_text, rest = raw_line[len("build "):].split(":", 1)
        try:
            outputs = shlex.split(outputs_text)
            parts = shlex.split(rest)
        except ValueError:
            continue
        if not outputs or not parts or parts[0] not in COMPILE_RULES:
            continue

        input_tokens: list[str] = []
        for token in parts[1:]:
            if token in {"|", "||"}:
                break
            input_tokens.append(token)
        if not input_tokens:
            continue
        edges.append((Path(outputs[0]), Path(input_tokens[0])))
    return edges


def repair_ninja_deps_if_corrupt(root: Path, fix: bool):
    from .doctor import CheckResult
    from .utils import run_cmd, rel_to_root

    ninja_deps = root / ".ninja_deps"
    if not ninja_deps.exists():
        return None

    build_config = Path("build") / "GALE01" / "config.json"
    result = run_cmd(
        ["ninja", "-t", "deps", str(build_config)],
        timeout=10,
        cwd=root,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if "premature end of file" not in output:
        return None

    if not fix:
        return CheckResult(
            "warn",
            ".ninja_deps is corrupt; Ninja may repeatedly rebuild generated config",
            "run python tools/worktree-doctor.py --fix or delete .ninja_deps",
        )

    try:
        ninja_deps.unlink()
    except OSError as exc:
        return CheckResult(
            "fail",
            f"could not remove corrupt .ninja_deps: {exc}",
            "delete .ninja_deps and rerun ninja",
        )
    return CheckResult(
        "ok",
        "removed corrupt .ninja_deps; Ninja will rebuild its dependency database",
    )
