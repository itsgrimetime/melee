"""Diagnostic engine — Doctor class and CheckResult for worktree checks."""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import (
    COMPILE_RULES,
    DTK_DOWNLOAD_TAG,
    REPORT_REFRESH_FIX,
    REPORT_REFRESH_TIMEOUT_SECONDS,
    STALE_GRACE_SECONDS,
    TOOLING_FILES,
    WIBO_DOWNLOAD_TAG,
)
from . import utils as _utils
from .utils import (
    detect_ghidra_install,
    install_base_dol,
    refresh_report_json,
    resolve_melee_agent_module_path,
    run_git,
)
# Access ROOT via _utils.ROOT so monkeypatching tests can change it dynamically.


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
        required = [_utils.ROOT / "configure.py", _utils.ROOT / "src", _utils.ROOT / "config" / "GALE01"]
        if all(path.exists() for path in required):
            self.ok(f"repo root detected: {_utils.ROOT}")
        else:
            self.fail(f"{_utils.ROOT} does not look like a Melee repo root")

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
        self.results.extend(collect_local_exclude_warnings(_utils.ROOT, fix=self.fix))

    def check_tooling_overlay(self) -> None:
        for rel_path in TOOLING_FILES:
            path = _utils.ROOT / rel_path
            if path.exists():
                self.ok(f"tooling present: {rel_path}")
                continue

            restored = False
            if self.fix:
                from .utils import restore_from_master
                restored = restore_from_master(rel_path, path)
            if restored:
                self.ok(f"restored tooling from master: {rel_path}")
            else:
                self.fail(
                    f"missing tooling file: {rel_path}",
                    f"run {Path(__file__).name} --fix or restore the fork tooling overlay",
                )

    def check_base_dol(self) -> None:
        dol_path = _utils.ROOT / "orig" / "GALE01" / "sys" / "main.dol"
        if dol_path.exists():
            self.ok("base DOL present: orig/GALE01/sys/main.dol")
            return

        from . import DOL_CANDIDATES as _dol_cands
        candidate = next((path for path in _dol_cands if path.exists()), None)
        if candidate and self.fix:
            action = install_base_dol(candidate, dol_path)
            self.ok(f"{action} base DOL from {candidate}")
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
        self.check_wibo_tool()
        self.check_dtk_tool()

    def check_wibo_tool(self) -> None:
        wibo = _utils.ROOT / "build" / "tools" / "wibo"
        if not wibo.exists():
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

    def check_dtk_tool(self) -> None:
        dtk = _utils.ROOT / "build" / "tools" / "dtk"
        if not dtk.exists():
            self.ok("build/tools/dtk not present yet (will download on first build)")
            return

        if sys.platform != "darwin" or platform.machine().lower() not in ("aarch64", "arm64"):
            self.ok("build/tools/dtk present")
            return

        arch = _utils.detect_macho_arch(dtk)
        if arch == "x86_64":
            self.ok("build/tools/dtk arch is safe (x86_64 via Rosetta)")
            return
        if arch == "universal":
            self.ok("build/tools/dtk arch is safe (universal Mach-O)")
            return
        if arch != "arm64":
            self.warn(f"could not confirm build/tools/dtk arch ({arch or 'unknown'})")
            return

        if self.fix:
            if _utils.redownload_dtk(dtk, dtk_download_tag=DTK_DOWNLOAD_TAG):
                self.ok(
                    f"refreshed build/tools/dtk (arm64 -> x86_64 via Rosetta, "
                    f"tag {DTK_DOWNLOAD_TAG})"
                )
                return
            self.fail(
                "build/tools/dtk is macOS arm64 and --fix download failed",
                f"manually download https://github.com/encounter/decomp-toolkit/releases/download/"
                f"{DTK_DOWNLOAD_TAG}/dtk-macos-x86_64 to build/tools/dtk",
            )
            return

        self.fail(
            "build/tools/dtk is macOS arm64 and can hang before main on this host",
            f"run {Path(__file__).name} --fix to replace it with the x86_64/Rosetta DTK",
        )

    def _redownload_wibo(self, wibo: Path) -> bool:
        import platform
        import urllib.request
        import urllib.error

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
        checkdiff = _utils.ROOT / "tools" / "checkdiff.py"
        if checkdiff.exists():
            result = _utils.run_cmd([sys.executable, str(checkdiff), "--help"], timeout=10)
            if result.returncode == 0:
                self.ok("tools/checkdiff.py --help works")
            else:
                self.fail("tools/checkdiff.py --help failed", result.stderr.strip() or result.stdout.strip())

        melee_agent = shutil.which("melee-agent")
        if melee_agent:
            result = _utils.run_cmd(["melee-agent", "--help"], timeout=10)
            if result.returncode == 0:
                self.ok(f"melee-agent resolves: {melee_agent}")
                collect_melee_agent_entrypoint_warnings = _utils.collect_melee_agent_entrypoint_warnings
                from .utils import is_stale_melee_agent_entrypoint
                entrypoint_results = collect_melee_agent_entrypoint_warnings(_utils.ROOT, Path(melee_agent))
                if self.fix and any(is_stale_melee_agent_entrypoint(result) for result in entrypoint_results):
                    self.warn(
                        "stale melee-agent entrypoint was not auto-reinstalled",
                        "refresh the global install from the authoritative shared checkout; "
                        "worktree-doctor --fix will not repoint it from a matcher worktree",
                    )
                self.results.extend(entrypoint_results)
                self.results.extend(_utils.collect_melee_agent_distribution_warnings())
            else:
                self.warn("melee-agent exists but --help failed", result.stderr.strip() or result.stdout.strip())
        else:
            self.warn("melee-agent is not on PATH", "use python -m src.cli with the repo-local package")

        self.check_table_typer()

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

    def check_table_typer(self) -> None:
        table_typer_dir = _utils.ROOT / "tools" / "table-typer"
        table_typer = table_typer_dir / "table-typer"
        if table_typer.exists():
            self.ok("table-typer binary present")
            return
        if not (table_typer_dir / "go.mod").exists():
            self.warn(
                "table-typer sources missing",
                "opseq workflows are unavailable until the fork tooling "
                "overlay is restored; run: python tools/worktree-doctor.py --fix",
            )
            return
        if self.fix:
            print("[FIX] building table-typer via `go build`...", flush=True)
            build = _utils.build_table_typer(_utils.ROOT)
            if build.returncode == 0 and table_typer.exists():
                self.ok("table-typer binary built (via --fix)")
                return
            if build.returncode == 127:
                self.warn(
                    "table-typer binary missing",
                    "Go toolchain not found, so --fix could not build it; install "
                    "Go then: cd tools/table-typer && go build -o table-typer "
                    "(opseq workflows only; optional)",
                )
                return
            detail = (build.stderr or build.stdout or "").strip().splitlines()
            tail = detail[-1] if detail else f"exit code {build.returncode}"
            self.warn(
                "table-typer binary missing",
                f"--fix go build failed ({tail}); build manually: "
                "cd tools/table-typer && go build -o table-typer "
                "(opseq workflows only; optional)",
            )
            return
        self.warn(
            "table-typer binary missing",
            "run python tools/worktree-doctor.py --fix to build it (needs Go), or: "
            "cd tools/table-typer && go build -o table-typer "
            "(opseq workflows only; optional)",
        )

    def check_knowledge_sources(self) -> None:
        from .checks import collect_knowledge_source_warnings
        self.results.extend(collect_knowledge_source_warnings(_utils.ROOT))

    def check_stale_state(self) -> None:
        from .checks import collect_stale_state_warnings, repair_ninja_deps_if_corrupt

        ninja_deps_result = repair_ninja_deps_if_corrupt(_utils.ROOT, self.fix)
        if ninja_deps_result is not None:
            self.results.append(ninja_deps_result)

        stale_results = collect_stale_state_warnings(_utils.ROOT)
        if not stale_results:
            self.ok("build/report freshness checks passed")
            return

        if self.fix:
            print("[FIX] refreshing build/GALE01/report.json via configure.py and ninja...", flush=True)
            result = refresh_report_json(_utils.ROOT)
            if result.returncode == 0:
                remaining_results = collect_stale_state_warnings(_utils.ROOT)
                if remaining_results:
                    self.warn(
                        "refreshed build/GALE01/report.json, but stale generated state remains",
                        REPORT_REFRESH_FIX,
                    )
                    self.results.extend(remaining_results)
                else:
                    self.ok("refreshed build/GALE01/report.json via configure.py and ninja")
                return

            self.results.extend(stale_results)
            self.fail(
                "failed to refresh build/GALE01/report.json",
                (result.stderr.strip() or result.stdout.strip() or REPORT_REFRESH_FIX),
            )
            return

        self.results.extend(stale_results)

    def print_results(self) -> None:
        labels = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
        for result in self.results:
            print(f"[{labels[result.level]}] {result.message}")
            if result.fix:
                print(f"      fix: {result.fix}")


# ── local-exclude helpers (used by Doctor.check_git_state) ────────────────────

TRACKED_TOOLING_EXCLUDE_PATTERNS = {
    "tools",
    "tools/",
    "tools/melee-agent",
    "tools/melee-agent/",
    "tools/workflow",
    "tools/workflow/",
    "tools/mwcc_debug",
    "tools/mwcc_debug/",
}


def _normalized_exclude_pattern(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    return stripped.lstrip("/")


def local_exclude_path(root: Path) -> Path | None:
    from .utils import _git_for_root
    path_text = _git_for_root(
        root,
        ["rev-parse", "--git-path", "info/exclude"],
        allow_fail=True,
    ).strip()
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        path = root / path
    return path


def has_tracked_path_under(root: Path, rel_path: str) -> bool:
    from .utils import _git_for_root
    return bool(
        _git_for_root(root, ["ls-files", "--", rel_path], allow_fail=True).strip()
    )


def blocked_tracked_tooling_exclude_patterns(root: Path) -> list[str]:
    exclude = local_exclude_path(root)
    if exclude is None or not exclude.exists():
        return []
    blocked: list[str] = []
    for line in exclude.read_text(encoding="utf-8").splitlines():
        pattern = _normalized_exclude_pattern(line)
        if pattern is None:
            continue
        if pattern not in TRACKED_TOOLING_EXCLUDE_PATTERNS:
            continue
        tracked_path = pattern.rstrip("/")
        if has_tracked_path_under(root, tracked_path):
            blocked.append(pattern)
    return blocked


def remove_blocked_tracked_tooling_excludes(root: Path) -> list[str]:
    exclude = local_exclude_path(root)
    if exclude is None or not exclude.exists():
        return []
    blocked = set(blocked_tracked_tooling_exclude_patterns(root))
    if not blocked:
        return []
    lines = exclude.read_text(encoding="utf-8").splitlines()
    kept = [
        line for line in lines
        if (_normalized_exclude_pattern(line) not in blocked)
    ]
    exclude.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return sorted(blocked)


def collect_local_exclude_warnings(root: Path, *, fix: bool = False) -> list[CheckResult]:
    blocked = blocked_tracked_tooling_exclude_patterns(root)
    if not blocked:
        return []
    joined = ", ".join(sorted(set(blocked)))
    if fix:
        removed = remove_blocked_tracked_tooling_excludes(root)
        if removed:
            return [
                CheckResult(
                    "ok",
                    "removed local exclude pattern(s) that hid tracked tooling: "
                    + ", ".join(removed),
                )
            ]
    return [
        CheckResult(
            "warn",
            "local .git/info/exclude hides tracked tooling path(s): " + joined,
            "run python tools/worktree-doctor.py --fix or remove those local exclude entries",
        )
    ]
