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

# Kept in sync with configure.py's config.wibo_tag; only used by --fix to
# re-download the right wibo binary if the existing one is wrong arch.
WIBO_DOWNLOAD_TAG = "1.0.0"


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
        self.check_build_tools()
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

    def check_build_tools(self) -> None:
        wibo = ROOT / "build" / "tools" / "wibo"
        if not wibo.exists():
            # download_tool.py will fetch on first ninja build; nothing to validate yet.
            self.ok("build/tools/wibo not present yet (will download on first build)")
            return
        try:
            with open(wibo, "rb") as f:
                magic = f.read(4)
        except OSError as exc:
            self.warn(f"could not read build/tools/wibo: {exc}")
            return
        is_macho = magic in (
            b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
            b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
        )
        is_elf = magic == b"\x7fELF"
        expected_macho = sys.platform == "darwin"
        correct = is_macho if expected_macho else is_elf
        if correct:
            kind = "Mach-O" if is_macho else "ELF"
            self.ok(f"build/tools/wibo arch is correct ({kind} for {sys.platform})")
            return

        kind_present = "Mach-O" if is_macho else ("ELF" if is_elf else "unknown")
        kind_expected = "Mach-O" if expected_macho else "ELF"
        if self.fix:
            if self._redownload_wibo(wibo):
                self.ok(
                    f"refreshed build/tools/wibo ({kind_present} -> {kind_expected}, "
                    f"tag {WIBO_DOWNLOAD_TAG})"
                )
                return
            self.fail(
                f"build/tools/wibo wrong arch ({kind_present}; expected {kind_expected}); --fix download failed",
                f"manually download from https://github.com/decompals/wibo/releases/download/"
                f"{WIBO_DOWNLOAD_TAG}/wibo-macos (or wibo-x86_64 on Linux)",
            )
            return
        self.fail(
            f"build/tools/wibo wrong arch ({kind_present}; expected {kind_expected} on {sys.platform})",
            f"run {Path(__file__).name} --fix to re-download the right binary "
            f"(decompals/wibo tag {WIBO_DOWNLOAD_TAG})",
        )

    def _redownload_wibo(self, wibo: Path) -> bool:
        """Download the right wibo binary for this host.

        Self-contained — does not depend on tools/download_tool.py (older
        wip worktrees still ship the legacy URL that 404s on tag 1.0.0+).
        """
        import platform
        import stat
        import urllib.error
        import urllib.request

        machine = platform.machine().lower()
        if machine == "amd64":
            machine = "x86_64"
        if sys.platform == "darwin":
            asset = "wibo-macos"
        else:
            asset = f"wibo-{machine}"
        url = f"https://github.com/decompals/wibo/releases/download/{WIBO_DOWNLOAD_TAG}/{asset}"

        try:
            wibo.unlink()
        except OSError:
            pass
        wibo.parent.mkdir(parents=True, exist_ok=True)

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                with open(wibo, "wb") as f:
                    shutil.copyfileobj(response, f)
        except (urllib.error.URLError, OSError):
            return False
        wibo.chmod(wibo.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return wibo.exists() and wibo.stat().st_size > 0

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

        ghidra_install = detect_ghidra_install()
        if ghidra_install is not None:
            env_path_str = os.environ.get("GHIDRA_INSTALL_DIR")
            via = "GHIDRA_INSTALL_DIR" if env_path_str and Path(env_path_str) == ghidra_install else "auto-detected"
            self.ok(f"Ghidra install: {ghidra_install} ({via})")
        else:
            self.warn(
                "Ghidra install not found",
                "set GHIDRA_INSTALL_DIR or install under /opt/homebrew/Cellar/ghidra, /Applications, /opt, or ~/ghidra",
            )

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


# Mirrors tools/melee-agent/src/cli/ghidra/detect.py so worktree-doctor can
# validate Ghidra availability without depending on melee-agent being importable.
# If the search/detection logic changes there, update here too.
_GHIDRA_SEARCH_PATHS = [
    Path("/opt/homebrew/Cellar/ghidra"),       # macOS arm64 Homebrew
    Path("/usr/local/Cellar/ghidra"),          # macOS x86_64 Homebrew
    Path("/Applications"),                      # macOS manual install
    Path.home() / "Library" / "ghidra",        # macOS user-local
    Path("/opt"),                               # Linux manual install
    Path.home() / "ghidra",                    # user home tarball
]


def _ghidra_install_valid(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / "application.properties").is_file() or (path / "Ghidra" / "application.properties").is_file()


def _ghidra_search_under(root: Path) -> Path | None:
    if not root.exists():
        return None
    if _ghidra_install_valid(root):
        return root
    for child in sorted(root.iterdir(), reverse=True):  # newest version first
        if not child.is_dir():
            continue
        if _ghidra_install_valid(child):
            return child
        nested = child / "libexec"
        if _ghidra_install_valid(nested):
            return nested
        nested2 = child / "Ghidra"
        if _ghidra_install_valid(nested2):
            return nested2
    return None


def detect_ghidra_install() -> Path | None:
    """Return path to a valid Ghidra install, or None. Honors GHIDRA_INSTALL_DIR
    first, then searches common installation roots."""
    env_val = os.environ.get("GHIDRA_INSTALL_DIR")
    if env_val:
        env_path = Path(env_val)
        if _ghidra_install_valid(env_path):
            return env_path
    for root in _GHIDRA_SEARCH_PATHS:
        found = _ghidra_search_under(root)
        if found is not None:
            return found
    return None


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

    # Skills now live canonically under .claude/skills/ (Claude's native layout)
    # and are exposed to Codex via the .codex/skills symlink. Both providers
    # see the same set.
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


BANNER_TOOL_NAMES = {
    "tools/checkdiff.py": "checkdiff",
    "tools/decomp.py": "decomp",
    "tools/workflow/status.sh": "workflow",
    "tools/workflow/create-pr.sh": "workflow",
    "tools/workflow/update-pr.sh": "workflow",
    "tools/workflow/pr-worktree.sh": "workflow",
}


def collect_banner_tooling_status(root: Path) -> tuple[str, list[str]]:
    """Derive banner-level tooling status from existence checks.

    Returns ("ok"|"partial"|"broken", missing_short_names). "broken" means a
    core tool (checkdiff.py) is absent; "partial" means some non-core tooling
    is missing.
    """
    missing: list[str] = []
    seen: set[str] = set()
    for rel_path in TOOLING_FILES:
        if (root / rel_path).exists():
            continue
        name = BANNER_TOOL_NAMES.get(rel_path, rel_path)
        if name not in seen:
            missing.append(name)
            seen.add(name)

    if shutil.which("melee-agent") is None and "melee-agent" not in seen:
        missing.append("melee-agent")
        seen.add("melee-agent")

    if not missing:
        return "ok", []
    if not (root / "tools" / "checkdiff.py").exists():
        return "broken", missing
    return "partial", missing


def banner_line(root: Path) -> str:
    branch = run_git(["branch", "--show-current"], allow_fail=True).strip()
    head = run_git(["rev-parse", "--short", "HEAD"], allow_fail=True).strip() or "?"
    branch_str = branch if branch else f"detached@{head}"

    status, missing = collect_banner_tooling_status(root)
    if status == "ok":
        tooling_str = "ok"
    elif status == "broken":
        tooling_str = "broken"
    else:
        tooling_str = f"partial:{','.join(missing)}"

    return f"WORKTREE {root} | BRANCH {branch_str} | TOOLING {tooling_str}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Apply safe local bootstrap fixes")
    parser.add_argument(
        "--banner",
        action="store_true",
        help="Print a single-line worktree/branch/tooling status and exit 0",
    )
    args = parser.parse_args()
    if args.banner:
        print(banner_line(ROOT))
        return 0
    return Doctor(fix=args.fix).run()


if __name__ == "__main__":
    raise SystemExit(main())
