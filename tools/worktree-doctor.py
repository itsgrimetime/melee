#!/usr/bin/env python3
"""Check and optionally repair local agent workflow prerequisites."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

TOOLING_FILES = [
    "tools/checkdiff.py",
    "tools/decomp.py",
    "tools/workflow/status.sh",
    "tools/workflow/create-pr.sh",
    "tools/workflow/update-pr.sh",
    "tools/workflow/pr-worktree.sh",
]

DOL_CANDIDATES = [
    Path.home() / "code" / "melee" / "orig" / "GALE01" / "sys" / "main.dol",
    Path.home() / ".config" / "decomp-me" / "orig" / "GALE01" / "main.dol",
]

DISCORD_SEARCH_CANDIDATES = [
    Path("/Users/mike/code/discord-archive-mcp/.venv/bin/discord-search"),
]

COMPILE_RULES = {"mwcc", "mwcc_sjis", "mwcc_extab", "mwcc_sjis_extab", "as"}
STALE_GRACE_SECONDS = 1.0


@dataclass
class CheckResult:
    level: str
    message: str
    fix: str | None = None


class Doctor:
    def __init__(self, fix: bool = False):
        self.fix = fix
        self.results: list[CheckResult] = []

    def ok(self, message: str) -> None:
        self.results.append(CheckResult("ok", message))

    def warn(self, message: str, fix: str | None = None) -> None:
        self.results.append(CheckResult("warn", message, fix))

    def fail(self, message: str, fix: str | None = None) -> None:
        self.results.append(CheckResult("fail", message, fix))

    def run(self) -> int:
        self.check_repo_root()
        self.check_git_state()
        self.check_tooling_overlay()
        self.check_base_dol()
        self.check_cli_tools()
        self.check_knowledge_sources()
        self.check_stale_state()
        self.print_results()
        return 1 if any(result.level == "fail" for result in self.results) else 0

    def check_repo_root(self) -> None:
        required = [ROOT / "configure.py", ROOT / "src", ROOT / "config" / "GALE01"]
        if all(path.exists() for path in required):
            self.ok(f"repo root detected: {ROOT}")
        else:
            self.fail(f"{ROOT} does not look like a Melee repo root")

    def check_git_state(self) -> None:
        branch = run_git(["branch", "--show-current"], allow_fail=True).strip()
        head = run_git(["rev-parse", "--short", "HEAD"], allow_fail=True).strip()
        if branch:
            self.ok(f"git branch: {branch} ({head})")
        else:
            self.warn(f"detached HEAD: {head}", "create a named codex/* branch before committing")

        status = run_git(["status", "--short"], allow_fail=True).splitlines()
        if status:
            self.warn(f"working tree has {len(status)} dirty path(s)", "review dirty files before editing")
        else:
            self.ok("working tree is clean")

        for remote in ("upstream", "origin"):
            url = run_git(["remote", "get-url", remote], allow_fail=True).strip()
            if url:
                self.ok(f"remote {remote}: {url}")
            else:
                self.warn(f"remote {remote} is not configured")

    def check_tooling_overlay(self) -> None:
        for rel_path in TOOLING_FILES:
            path = ROOT / rel_path
            if path.exists():
                self.ok(f"tooling present: {rel_path}")
                continue

            restored = False
            if self.fix:
                restored = restore_from_master(rel_path, path)
            if restored:
                self.ok(f"restored tooling from master: {rel_path}")
            else:
                self.fail(
                    f"missing tooling file: {rel_path}",
                    f"run {Path(__file__).name} --fix or restore the fork tooling overlay",
                )

    def check_base_dol(self) -> None:
        dol_path = ROOT / "orig" / "GALE01" / "sys" / "main.dol"
        if dol_path.exists():
            self.ok("base DOL present: orig/GALE01/sys/main.dol")
            return

        candidate = next((path for path in DOL_CANDIDATES if path.exists()), None)
        if candidate and self.fix:
            dol_path.parent.mkdir(parents=True, exist_ok=True)
            dol_path.symlink_to(candidate)
            self.ok(f"linked base DOL from {candidate}")
            return

        if candidate:
            self.fail(
                "base DOL missing from this worktree",
                f"run {Path(__file__).name} --fix to symlink {candidate}",
            )
        else:
            self.fail(
                "base DOL missing and no shared copy was found",
                "provide orig/GALE01/sys/main.dol or ~/.config/decomp-me/orig/GALE01/main.dol",
            )

    def check_cli_tools(self) -> None:
        checkdiff = ROOT / "tools" / "checkdiff.py"
        if checkdiff.exists():
            result = run_cmd([sys.executable, str(checkdiff), "--help"], timeout=10)
            if result.returncode == 0:
                self.ok("tools/checkdiff.py --help works")
            else:
                self.fail("tools/checkdiff.py --help failed", result.stderr.strip() or result.stdout.strip())

        melee_agent = shutil.which("melee-agent")
        if melee_agent:
            result = run_cmd(["melee-agent", "--help"], timeout=10)
            if result.returncode == 0:
                self.ok(f"melee-agent resolves: {melee_agent}")
            else:
                self.warn("melee-agent exists but --help failed", result.stderr.strip() or result.stdout.strip())
        else:
            self.warn("melee-agent is not on PATH", "use python -m src.cli with the repo-local package")

        table_typer = ROOT / "tools" / "table-typer" / "table-typer"
        if table_typer.exists():
            self.ok("table-typer binary present")
        elif (ROOT / "tools" / "table-typer" / "go.mod").exists():
            self.warn("table-typer binary missing", "run: cd tools/table-typer && go build -o table-typer")

        ghidra_dir = os.environ.get("GHIDRA_INSTALL_DIR")
        if ghidra_dir and Path(ghidra_dir).exists():
            self.ok(f"GHIDRA_INSTALL_DIR set: {ghidra_dir}")
        else:
            self.warn("GHIDRA_INSTALL_DIR is not configured", "ghidra helper commands will be unavailable")

    def check_knowledge_sources(self) -> None:
        self.results.extend(collect_knowledge_source_warnings(ROOT))

    def check_stale_state(self) -> None:
        stale_results = collect_stale_state_warnings(ROOT)
        if stale_results:
            self.results.extend(stale_results)
        else:
            self.ok("build/report freshness checks passed")

    def print_results(self) -> None:
        labels = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
        for result in self.results:
            print(f"[{labels[result.level]}] {result.message}")
            if result.fix:
                print(f"      fix: {result.fix}")


def run_git(args: list[str], allow_fail: bool = False) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0 and not allow_fail:
        raise RuntimeError(result.stderr.strip())
    return result.stdout if result.returncode == 0 else ""


def run_cmd(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(args, 124, exc.stdout or "", exc.stderr or "timed out")
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def restore_from_master(rel_path: str, dest: Path) -> bool:
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"master:{rel_path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if exists.returncode != 0:
        return False

    content = subprocess.run(
        ["git", "show", f"master:{rel_path}"],
        cwd=ROOT,
        capture_output=True,
        text=False,
    )
    if content.returncode != 0:
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content.stdout)
    return True


def collect_knowledge_source_warnings(root: Path, discord_cli: Path | None = None) -> list[CheckResult]:
    """Collect checks for local knowledge docs, Discord archive CLI, and repo skill."""
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

    decomp_skill = root / ".agents" / "skills" / "decomp" / "SKILL.md"
    if decomp_skill.exists():
        results.append(CheckResult("ok", "repo-local decomp skill present: .agents/skills/decomp/SKILL.md"))
    else:
        results.append(
            CheckResult(
                "warn",
                ".agents/skills/decomp/SKILL.md is missing",
                "restore the canonical repo-local decomp skill or use AGENTS.md/CLAUDE.md workflow instructions",
            )
        )

    claude_skill = root / ".claude" / "skills" / "decomp" / "SKILL.md"
    codex_skills = root / ".codex" / "skills"
    if claude_skill.exists():
        results.append(CheckResult("ok", "Claude decomp skill compatibility path resolves"))
    else:
        results.append(
            CheckResult("warn", ".claude/skills/decomp/SKILL.md is missing", "symlink it to .agents/skills/decomp/SKILL.md")
        )
    if codex_skills.exists():
        results.append(CheckResult("ok", "Codex skills compatibility path resolves"))
    else:
        results.append(CheckResult("warn", ".codex/skills is missing", "symlink it to ../.agents/skills"))

    return results


def resolve_discord_search(discord_cli: Path | None = None) -> Path | None:
    candidates = [discord_cli] if discord_cli is not None else DISCORD_SEARCH_CANDIDATES
    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    path_candidate = shutil.which("discord-search")
    if path_candidate:
        return Path(path_candidate)
    return None


def collect_stale_state_warnings(root: Path) -> list[CheckResult]:
    """Collect warnings for generated build state older than source inputs."""
    results: list[CheckResult] = []
    newest = newest_relevant_input(root)
    report_path = root / "build" / "GALE01" / "report.json"

    if newest is not None and report_path.exists():
        newest_path, newest_mtime = newest
        if report_path.stat().st_mtime + STALE_GRACE_SECONDS < newest_mtime:
            results.append(
                CheckResult(
                    "warn",
                    f"build/GALE01/report.json is older than {rel_to_root(newest_path, root)}",
                    "run: python configure.py && ninja before trusting match/report data",
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
        outputs_text, rest = raw_line[len("build ") :].split(":", 1)
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


def rel_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Apply safe local bootstrap fixes")
    args = parser.parse_args()
    return Doctor(fix=args.fix).run()


if __name__ == "__main__":
    raise SystemExit(main())
